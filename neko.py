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
from pyrogram.types import Message, BotCommand
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
        
        @self.app.on_message(filters.text & filters.private)
        async def _handle_message(client: Client, message: Message):
            global set_cmd
            if not set_cmd:
                await self.lista_cmd()
                set_cmd = True
            await self._handle_message(client, message)
    
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
            BotCommand("up", "Subir archivo al vault"),
            BotCommand("setfile", "Configurar formato de salida (cbz/pdf/raw)")
        ])
        print("Comandos configurados en el bot")
    
    async def _handle_message(self, client: Client, message: Message):
        if not message.text:
            return
        text = message.text.strip()
        
        if text.startswith("/setfile "):
            parts = text.split()
            if len(parts) != 2:
                await safe_call(message.reply_text, "Usa: `/setfile cbz` o `/setfile pdf` o `/setfile raw`")
                return
            format_option = parts[1].lower()
            if format_option not in ["cbz", "pdf", "raw"]:
                await safe_call(message.reply_text, "Formato inválido. Usa: cbz, pdf o raw")
                return
            user_settings[message.from_user.id] = format_option
            await safe_call(message.reply_text, f"✅ Formato configurado a: **{format_option.upper()}**")
            return
        
        if text.startswith("/nh ") or text.startswith("/3h "):
            parts = text.split()
            if len(parts) < 2:
                await safe_call(message.reply_text, "Usa: `/nh codigo` o `/3h codigo`")
                return
            code = parts[1]
            user_id = message.from_user.id
            format_choice = user_settings.get(user_id, "cbz")
            result = self.neko.vnh(code) if text.startswith("/nh ") else self.neko.v3h(code)
            await self._process_gallery_json(message, result, code, format_choice)
        
        elif text.startswith("/snh ") or text.startswith("/s3h "):
            parts = text.split(maxsplit=1)
            if len(parts) < 2:
                await safe_call(message.reply_text, "Usa: `/snh busqueda` o `/s3h busqueda`")
                return
            search = parts[1]
            result = self.neko.snh(search) if text.startswith("/snh ") else self.neko.s3h(search)
            await self._process_search_json(message, result)

        elif text.startswith("/hito"):
            parts = text.split()
            if len(parts) < 2:
                await safe_call(message.reply_text, "Usa: `/hito codigo` o `/hito url`")
                return
            arg = parts[1]
            p_override = None
            if "-p" in text:
                try:
                    p_override = int(text.split("-p",1)[1].strip())
                except:
                    p_override = None
            g = None
            p = 1
            if arg.isdigit():
                g = arg
            elif "hitomi.la/reader/" in arg:
                try:
                    g = arg.split("reader/")[1].split(".html")[0]
                    frag = arg.split("#")
                    if len(frag) > 1 and p_override is None:
                        p = int(frag[1])
                except:
                    await safe_call(message.reply_text, "Formato de enlace inválido")
                    return
            else:
                try:
                    g = arg.split("-")[-1].split(".html")[0]
                except:
                    await safe_call(message.reply_text, "Formato de enlace inválido")
                    return
            if p_override is not None:
                p = p_override
            result = self.neko.hito(g, p)
            if "error" in result:
                await safe_call(message.reply_text, f"Error: {result['error']}")
                return
            try:
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
            except Exception as e:
                await safe_call(message.reply_text, f"Error procesando respuesta: {e}")
        
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
    
    async def _send_photos_in_batches(self, message, image_urls, batch_size=10):
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
                        if idx == 0:
                            media_group.append(InputMediaPhoto(temp_path))
                        else:
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
    
    async def _process_gallery_json(self, message, result, code, format_choice):
        if "error" in result:
            await safe_call(message.reply_text, f"Error: `{result['error']}`")
            return
        nombre = result.get("title", "Sin titulo")
        images = result.get("image_links", [])
        tags = result.get("tags", {})
        if not images:
            await safe_call(message.reply_text, "No hay imagenes")
            return
        caption = f"**{nombre}**\nCódigo: `{code}`\n\n{self._format_tags(tags)}"
        await safe_call(message.reply_photo, images[0], caption=caption)
        if len(images) > 1:
            if format_choice == "cbz":
                temp_dir = "temp_cbz"
                os.makedirs(temp_dir, exist_ok=True)
                for i, img_url in enumerate(images):
                    img_path = os.path.join(temp_dir, f"{i:04d}.jpg")
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
                    img_path = os.path.join(temp_dir, f"{i:04d}.jpg")
                    self.neko.download(img_url, img_path)
                    await asyncio.sleep(0.5)
                pdf_path = self.neko.create_pdf(nombre, [os.path.join(temp_dir, f) for f in sorted(os.listdir(temp_dir))])
                if pdf_path and os.path.exists(pdf_path):
                    await safe_call(message.reply_document, pdf_path)
                    os.remove(pdf_path)
                shutil.rmtree(temp_dir, ignore_errors=True)
            elif format_choice == "raw":
                await self._send_photos_in_batches(message, images[1:])
    
    async def _process_search_json(self, message, result):
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
                items_str = ", ".join(items[:5])
                if len(items) > 5:
                    items_str += f" y {len(items)-5} más"
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
