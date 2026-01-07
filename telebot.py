import os
import asyncio
import sys
import argparse
import shutil
import tempfile
import time
import threading
import base64
from pyrogram import Client, filters
from pyrogram.types import Message, BotCommand, InputMediaPhoto
from pyrogram.errors import FloodWait
from neko import Neko
from server import run_flask

set_cmd = False
user_settings = {}

async def safe_call(func, *args, **kwargs):
    while True:
        try:
            return await func(*args, **kwargs)
        except FloodWait as e:
            print(f"⏳ Esperando {e.value} seg para continuar")
            await asyncio.sleep(e.value)
        except Exception as e:
            print(f"❌ Error inesperado en {func.__name__}: {type(e).__name__}: {e}")
            raise

def format_time(seconds):
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

class NekoTelegram:
    def __init__(self, api_id, api_hash, bot_token):
        self.api_id = api_id
        self.api_hash = api_hash
        self.bot_token = bot_token
        self.neko = Neko()
        self.app = Client("nekobot", api_id=int(api_id), api_hash=api_hash, bot_token=bot_token)
        self.flask_thread = None
        self.me_id = None
        
        @self.app.on_message(filters.text & filters.private)
        async def _handle_message(client: Client, message: Message):
            global set_cmd
            if not set_cmd:
                await self.lista_cmd()
                set_cmd = True
            await self._handle_message(client, message)
    
    async def get_me_id(self):
        if not self.me_id:
            me = await self.app.get_me()
            self.me_id = me.id
        return self.me_id
    
    def start_flask(self):
        if self.flask_thread and self.flask_thread.is_alive():
            print("[INFO] Flask ya está corriendo")
            return
            
        self.flask_thread = threading.Thread(target=run_flask, daemon=True)
        self.flask_thread.start()
        print("[INFO] Servidor Flask iniciado en puerto 5000.")
        
    async def lista_cmd(self):
        await self.app.set_bot_commands([
            BotCommand("nh", "Descarga un doujin de nhentai"),
            BotCommand("3h", "Descarga un doujin de 3hentai"),
            BotCommand("snh", "Busca doujins por filtros en nhentai"),
            BotCommand("s3h", "Busca doujins por filtros en 3hentai"),
            BotCommand("hito", "Descarga doujin de hitomi (usa -s y -f para rango)"),
            BotCommand("up", "Subir archivo al vault"),
            BotCommand("setfile", "Configurar formato de salida (cbz/pdf/raw)")
        ])
        print("Comandos configurados en el bot")
    
    async def _handle_message(self, client: Client, message: Message):
        if not message.text:
            return
        text = message.text.strip()
        user_id = message.from_user.id
        
        if text.startswith("/setfile "):
            parts = text.split()
            if len(parts) != 2:
                await safe_call(message.reply_text, "Usa: `/setfile cbz` o `/setfile pdf` o `/setfile raw`")
                return
            format_option = parts[1].lower()
            if format_option not in ["cbz", "pdf", "raw"]:
                await safe_call(message.reply_text, "Formato inválido. Usa: cbz, pdf o raw")
                return
            user_settings[user_id] = format_option
            await safe_call(message.reply_text, f"✅ Formato configurado a: **{format_option.upper()}**")
            return
        
        if text.startswith("/nh ") or text.startswith("/3h "):
            parts = text.split()
            if len(parts) < 2:
                await safe_call(message.reply_text, "Usa: `/nh codigo` o `/3h codigo`")
                return
            
            command = text.split()[0]
            code = parts[1]
            start_page = 1
            end_page = None
            single_page = None
            
            if "-s" in text:
                try:
                    s_idx = text.index("-s")
                    start_page = int(text[s_idx:].split()[1])
                except:
                    await safe_call(message.reply_text, "Formato -s inválido")
                    return
            
            if "-f" in text:
                try:
                    f_idx = text.index("-f")
                    end_page = int(text[f_idx:].split()[1])
                except:
                    await safe_call(message.reply_text, "Formato -f inválido")
                    return
            
            if "-p" in text:
                try:
                    p_idx = text.index("-p")
                    single_page = int(text[p_idx:].split()[1])
                except:
                    await safe_call(message.reply_text, "Formato -p inválido")
                    return
            
            format_choice = user_settings.get(user_id, "cbz")
            result = self.neko.vnh(code) if command == "/nh" else self.neko.v3h(code)
            
            if single_page:
                images = result.get("image_links", [])
                if images and 0 < single_page <= len(images):
                    selected_url = images[single_page-1]
                    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
                    temp_path = temp_file.name
                    temp_file.close()
                    if self.neko.download(selected_url, temp_path):
                        await safe_call(message.reply_photo, temp_path, caption=f"Página {single_page}/{len(images)}")
                        os.remove(temp_path)
                    else:
                        await safe_call(message.reply_text, f"Error descargando página {single_page}")
                else:
                    await safe_call(message.reply_text, f"Página {single_page} no encontrada")
                return
            
            await self._process_gallery_json_with_range(message, result, code, format_choice, start_page, end_page, user_id)
        
        elif text.startswith("/snh ") or text.startswith("/s3h "):
            parts = text.split(maxsplit=1)
            if len(parts) < 2:
                await safe_call(message.reply_text, "Usa: `/snh busqueda` o `/s3h busqueda`")
                return
            search = parts[1]
            result = self.neko.snh(search) if text.startswith("/snh ") else self.neko.s3h(search)
            await self._process_search_json(message, result, user_id)

        elif text.startswith("/hito"):
            parts = text.split()
            if len(parts) < 2:
                await safe_call(message.reply_text, "Usa: `/hito ID` o `/hito ID -s inicio -f final`")
                return
            
            arg = parts[1]
            g = None
            start_page = 1
            end_page = None
            
            if arg.isdigit():
                g = arg
            elif "hitomi.la/reader/" in arg:
                try:
                    g = arg.split("reader/")[1].split(".html")[0]
                except:
                    await safe_call(message.reply_text, "Formato de enlace inválido")
                    return
            else:
                try:
                    g = arg.split("-")[-1].split(".html")[0]
                except:
                    await safe_call(message.reply_text, "Formato de enlace inválido")
                    return
            
            if "-s" in text:
                try:
                    s_idx = text.index("-s")
                    start_page = int(text[s_idx:].split()[1])
                except:
                    await safe_call(message.reply_text, "Formato -s inválido")
                    return
            
            if "-f" in text:
                try:
                    f_idx = text.index("-f")
                    end_page = int(text[f_idx:].split()[1])
                except:
                    await safe_call(message.reply_text, "Formato -f inválido")
                    return
            
            if "-p" in text:
                try:
                    p_idx = text.index("-p")
                    single_page = int(text[p_idx:].split()[1])
                    result = self.neko.hito(g, single_page)
                    if "error" in result:
                        await safe_call(message.reply_text, f"Error: {result['error']}")
                        return
                    
                    pagina_actual = int(result["actual_page"])
                    paginas_totales = int(result["total_pages"])
                    datos_imagen = result["img"]
                    titulo = result["title"]
                    digitos = len(str(paginas_totales))
                    nombre_salida = f"{pagina_actual:0{digitos}d}.png"
                    imagen_decodificada = base64.b64decode(datos_imagen)
                    with open(nombre_salida, 'wb') as archivo_imagen:
                        archivo_imagen.write(imagen_decodificada)
                    await safe_call(message.reply_photo, nombre_salida, caption=f"Página {pagina_actual}/{paginas_totales} de {titulo}")
                    os.remove(nombre_salida)
                    return
                except Exception as e:
                    await safe_call(message.reply_text, f"Error procesando página única: {e}")
                    return
            
            format_choice = user_settings.get(user_id, "cbz")
            
            result_first = self.neko.hito(g, 1)
            if "error" in result_first:
                await safe_call(message.reply_text, f"Error: {result_first['error']}")
                return
            
            total_pages = int(result_first["total_pages"])
            titulo = result_first["title"]
            
            if end_page is None:
                end_page = total_pages
            
            start_page = max(1, start_page)
            end_page = min(total_pages, end_page)
            
            if start_page > end_page:
                start_page, end_page = end_page, start_page
            
            pages_to_download = list(range(start_page, end_page + 1))
            total_to_download = len(pages_to_download)
            
            if total_to_download == 0:
                await safe_call(message.reply_text, "No hay páginas para descargar en el rango especificado")
                return
            
            progress_msg = await safe_call(message.reply_text, f"Preparando descarga de {g}...")
            
            if format_choice == "raw":
                await self._download_hitomi_raw(message, g, pages_to_download, titulo, progress_msg, start_page, end_page, total_pages, user_id)
            else:
                await self._download_hitomi_archive(g, pages_to_download, titulo, format_choice, progress_msg, start_page, end_page, total_pages, user_id)
        
        elif text.startswith("/up"):
            parts = text.split(maxsplit=1)
            custom_path = parts[1].strip() if len(parts) > 1 else None
            rm = message.reply_to_message
            if not rm or not (rm.document or rm.photo or rm.video or rm.audio or rm.voice or rm.sticker):
                await safe_call(message.reply_text, "Responde a un archivo con /up")
                return
            
            vault_dir = os.path.join(os.getcwd(), "vault")
            if custom_path:
                target_path = os.path.join(vault_dir, custom_path)
            else:
                if rm.document:
                    fname = rm.document.file_name
                elif rm.photo:
                    fname = "photo.jpg"
                elif rm.video:
                    fname = rm.video.file_name or "video.mp4"
                elif rm.audio:
                    fname = rm.audio.file_name or "audio.mp3"
                elif rm.voice:
                    fname = "voice.ogg"
                elif rm.sticker:
                    fname = "sticker.webp"
                else:
                    fname = "file.bin"
                target_path = os.path.join(vault_dir, fname)
            
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            progress_msg = await safe_call(message.reply_text, "📥 Iniciando descarga...")
            start_time = time.time()
            download_completed = False
            current_bytes = 0
            total_bytes = rm.document.file_size if rm.document else 0

            async def update_download_progress():
                nonlocal current_bytes, total_bytes, download_completed, start_time, progress_msg, target_path
                last_update = time.time()
                while not download_completed:
                    if total_bytes > 0:
                        elapsed = int(time.time() - start_time)
                        formatted_time = format_time(elapsed)
                        progress_ratio = current_bytes / total_bytes if total_bytes else 0
                        bar_length = 20
                        filled_length = int(bar_length * progress_ratio)
                        bar = "█" * filled_length + "▒" * (bar_length - filled_length)
                        current_mb = current_bytes / (1024 * 1024)
                        total_mb = total_bytes / (1024 * 1024)
                        if time.time() - last_update >= 10:
                            await safe_call(
                                progress_msg.edit_text,
                                f"📥 Descargando archivo...\n"
                                f"🕒 Tiempo: {formatted_time}\n"
                                f"📊 Progreso: {current_mb:.2f} MB / {total_mb:.2f} MB\n"
                                f"📉 [{bar}] {progress_ratio*100:.1f}%\n"
                                f"📄 Archivo: {os.path.basename(target_path)}"
                            )
                            last_update = time.time()
                    await asyncio.sleep(0.5)

            async def progress_callback(current, total):
                nonlocal current_bytes
                current_bytes = current

            asyncio.create_task(update_download_progress())
            await self.app.download_media(rm, file_name=target_path, progress=progress_callback)
            download_completed = True
            await safe_call(progress_msg.edit_text, f"✅ Archivo guardado en `{target_path}`")
    
    async def _download_hitomi_raw(self, message, g, pages, titulo, progress_msg, start_page, end_page, total_pages, user_id):
        batch_size = 10
        downloaded_images = []
        current_batch = []
        
        for idx, page_num in enumerate(pages):
            try:
                result = self.neko.hito(g, page_num)
                if "error" in result:
                    continue
                
                datos_imagen = result["img"]
                imagen_decodificada = base64.b64decode(datos_imagen)
                pagina_actual = int(result["actual_page"])
                paginas_totales = int(result["total_pages"])
                digitos = len(str(paginas_totales))
                nombre_salida = f"{pagina_actual:0{digitos}d}.png"
                
                with open(nombre_salida, 'wb') as archivo_imagen:
                    archivo_imagen.write(imagen_decodificada)
                
                downloaded_images.append(nombre_salida)
                current_batch.append(nombre_salida)
                
                range_info = ""
                if start_page != 1 or end_page != total_pages:
                    range_info = f" (Progreso limitado al rango {start_page}-{end_page})"
                
                await safe_call(progress_msg.edit_text, f"Progreso de descarga de {g} {idx+1}/{len(pages)}{range_info} - Página {pagina_actual}/{paginas_totales}")
                
                if len(current_batch) >= batch_size:
                    await self._send_photo_batch(message, photo_paths=current_batch, batch_number=(idx//batch_size)+1, user_id=user_id)
                    for photo in current_batch:
                        try:
                            os.remove(photo)
                        except:
                            pass
                    current_batch = []
                    await asyncio.sleep(1)
                    
            except Exception as e:
                print(f"Error descargando página {page_num}: {e}")
                continue
        
        if current_batch:
            await self._send_photo_batch(message, photo_paths=current_batch, batch_number=(len(pages)//batch_size)+1, user_id=user_id)
            for photo in current_batch:
                try:
                    os.remove(photo)
                except:
                    pass
        
        await safe_call(progress_msg.edit_text, f"✅ Descarga RAW completada: {titulo}")
    
    async def _download_hitomi_archive(self, g, pages, titulo, format_choice, progress_msg, start_page, end_page, total_pages, user_id):
        temp_dir = tempfile.mkdtemp()
        downloaded_count = 0
        
        for idx, page_num in enumerate(pages):
            try:
                result = self.neko.hito(g, page_num)
                if "error" in result:
                    continue
                
                pagina_actual = int(result["actual_page"])
                paginas_totales = int(result["total_pages"])
                datos_imagen = result["img"]
                imagen_decodificada = base64.b64decode(datos_imagen)
                digitos = len(str(paginas_totales))
                nombre_salida = f"{pagina_actual:0{digitos}d}.png"
                save_path = os.path.join(temp_dir, nombre_salida)
                
                with open(save_path, 'wb') as archivo_imagen:
                    archivo_imagen.write(imagen_decodificada)
                
                downloaded_count += 1
                
                range_info = ""
                if start_page != 1 or end_page != total_pages:
                    range_info = f" (Progreso limitado al rango {start_page}-{end_page})"
                
                await safe_call(progress_msg.edit_text, f"Progreso de descarga de {g} {idx+1}/{len(pages)}{range_info} - Página {pagina_actual}/{paginas_totales}")
                
            except Exception as e:
                print(f"Error descargando página {page_num}: {e}")
                continue
        
        if downloaded_count == 0:
            await safe_call(progress_msg.edit_text, "❌ No se pudo descargar ninguna página")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return
        
        image_list = [os.path.join(temp_dir, f) for f in sorted(os.listdir(temp_dir))]
        
        if format_choice == "cbz":
            archive_path = self.neko.create_cbz(titulo, image_list)
        else:
            archive_path = self.neko.create_pdf(titulo, image_list)
        
        if archive_path and os.path.exists(archive_path):
            await safe_call(progress_msg.edit_text, f"✅ {format_choice.upper()} creado, enviando...")
            await self.app.send_document(progress_msg.chat.id, archive_path, caption=f"{titulo}")
            os.remove(archive_path)
        else:
            await safe_call(progress_msg.edit_text, f"❌ Error creando {format_choice.upper()}")
        
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    async def _send_photo_batch(self, message, photo_paths, batch_number, user_id):
        media_group = []
        for photo_path in photo_paths:
            try:
                media_group.append(InputMediaPhoto(photo_path))
            except Exception as e:
                print(f"Error añadiendo foto al grupo: {e}")
        
        if media_group:
            try:
                await self.app.send_media_group(chat_id=message.chat.id, media=media_group)
            except Exception as e:
                print(f"Error enviando grupo de fotos: {e}")
    
    async def _process_gallery_json_with_range(self, message, result, code, format_choice, start_page, end_page, user_id):
        if "error" in result:
            await safe_call(message.reply_text, f"Error: `{result['error']}`")
            return
        
        nombre = result.get("title", "Sin titulo")
        all_images = result.get("image_links", [])
        tags = result.get("tags", {})
        
        if not all_images:
            await safe_call(message.reply_text, "No hay imagenes")
            return
        
        total_images = len(all_images)
        
        if end_page is None:
            end_page = total_images
        
        start_page = max(1, start_page)
        end_page = min(total_images, end_page)
        
        if start_page > end_page:
            start_page, end_page = end_page, start_page
        
        images = all_images[start_page-1:end_page]
        
        caption = f"**{nombre}**\nCódigo: `{code}`\nRango: {start_page}-{end_page} de {total_images}\n\n{self._format_tags(tags)}"
        
        if images:
            await safe_call(message.reply_photo, images[0], caption=caption)
        
        if len(images) > 1:
            if format_choice == "cbz":
                temp_dir = "temp_cbz"
                os.makedirs(temp_dir, exist_ok=True)
                for i, img_url in enumerate(images):
                    img_path = os.path.join(temp_dir, f"{i+start_page:04d}.jpg")
                    self.neko.download(img_url, img_path)
                    await asyncio.sleep(0.5)
                cbz_path = self.neko.create_cbz(nombre, [os.path.join(temp_dir, f) for f in sorted(os.listdir(temp_dir))])
                if cbz_path and os.path.exists(cbz_path):
                    await safe_call(message.reply_document, cbz_path)
                    os.remove(cbz_path)
                shutil.rmtree(temp_dir, ignore_errors=True)
            elif format_choice == "pdf":
                temp_dir = "temp_pdf"
                os.makedirs(temp_dir, exist_ok=True)
                for i, img_url in enumerate(images):
                    img_path = os.path.join(temp_dir, f"{i+start_page:04d}.jpg")
                    self.neko.download(img_url, img_path)
                    await asyncio.sleep(0.5)
                pdf_path = self.neko.create_pdf(nombre, [os.path.join(temp_dir, f) for f in sorted(os.listdir(temp_dir))])
                if pdf_path and os.path.exists(pdf_path):
                    await safe_call(message.reply_document, pdf_path)
                    os.remove(pdf_path)
                shutil.rmtree(temp_dir, ignore_errors=True)
            elif format_choice == "raw":
                await self._send_photos_in_batches(message, images[1:], user_id=user_id)
    
    async def _send_photos_in_batches(self, message, image_urls, batch_size=10, user_id=None):
        for i in range(0, len(image_urls), batch_size):
            batch = image_urls[i:i+batch_size]
            media_group = []
            temp_files = []
            for idx, url in enumerate(batch):
                try:
                    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
                    temp_path = temp_file.name
                    temp_file.close()
                    if self.neko.download(url, temp_path):
                        temp_files.append(temp_path)
                        media_group.append(InputMediaPhoto(temp_path))
                except Exception as e:
                    print(f"Error descargando imagen: {e}")
            if media_group:
                await safe_call(message.reply_media_group, media_group)
                for tf in temp_files:
                    try:
                        os.remove(tf)
                    except:
                        pass
                await asyncio.sleep(1)
    
    async def _process_search_json(self, message, result, user_id):
        if "error" in result:
            await safe_call(message.reply_text, f"Error: `{result['error']}`")
            return
        resultados = result if isinstance(result, list) else result.get("resultados", [])
        if not resultados:
            await safe_call(message.reply_text, "No se encontraron resultados")
            return
        for item in resultados:
            code = item.get("code") or item.get("codigo", "")
            nombre = item.get("title") or item.get("nombre", "Sin titulo")
            miniatura = item.get("thumbnail") or item.get("miniatura", "")
            if miniatura.startswith("//"):
                miniatura = f"https:{miniatura}"
            if code and miniatura:
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
                temp_path = temp_file.name
                temp_file.close()
                if self.neko.download(miniatura, temp_path):
                    await safe_call(message.reply_photo, temp_path, caption=f"**{nombre}**\nCódigo: `{code}`")
                    os.remove(temp_path)
                else:
                    await safe_call(message.reply_text, f"**{nombre}**\nCódigo: `{code}`")
            elif code:
                await safe_call(message.reply_text, f"**{nombre}**\nCódigo: `{code}`")
            await asyncio.sleep(0.5)
    
    def _format_tags(self, tags):
        if not tags:
            return ""
        tag_lines = []
        for category, items in tags.items():
            if items:
                items_str = ", ".join(items)
                tag_lines.append(f"**{category}:** {items_str}")
        return "\n".join(tag_lines)
    
    def run(self):
        print("[INFO] Iniciando bot de Telegram...")
        self.app.run()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-A", "--api", help="API ID de Telegram")
    parser.add_argument("-H", "--hash", help="API Hash de Telegram")
    parser.add_argument("-T", "--token", help="Token del Bot")
    parser.add_argument("-F", "--flask", action="store_true", 
                       help="Incluir servidor Flask junto con el bot")
    args = parser.parse_args()

    api_id = args.api or os.environ.get("API_ID")
    api_hash = args.hash or os.environ.get("API_HASH")
    bot_token = args.token or os.environ.get("BOT_TOKEN")
    
    if not all([api_id, api_hash, bot_token]):
        print("Error: Faltan credenciales. Usa -A -H -T o variables de entorno.")
        sys.exit(1)
    
    bot = NekoTelegram(api_id, api_hash, bot_token)

    if args.flask:
        bot.start_flask()
    
    print("[INFO] Iniciando bot de Telegram...")
    bot.run()

if __name__ == "__main__":
    main()
