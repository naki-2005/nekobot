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
user_manga_settings = {}

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
            BotCommand("setfile", "Configurar formato de salida (cbz/pdf/raw)"),
            BotCommand("mangasearch", "Buscar manga por término"),
            BotCommand("mangafile", "Configurar formato de manga (cbz/pdf)"),
            BotCommand("mangadlset", "Configurar descarga por volumen o capítulo"),
            BotCommand("mangalang", "Configurar idioma para manga (en/es/ko/etc)"),
            BotCommand("mangadl", "Descargar manga por ID")
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
        
        elif text.startswith("/mangafile"):
            parts = text.split()
            if len(parts) == 1:
                current = user_manga_settings.get(user_id, {}).get("format", "cbz")
                await safe_call(message.reply_text, f"📚 Formato actual de manga: **{current.upper()}**\nUsa: `/mangafile cbz` o `/mangafile pdf`")
                return
            
            if len(parts) != 2:
                await safe_call(message.reply_text, "Usa: `/mangafile cbz` o `/mangafile pdf`")
                return
            
            format_option = parts[1].lower()
            if format_option not in ["cbz", "pdf"]:
                await safe_call(message.reply_text, "Formato inválido. Usa: cbz o pdf")
                return
            
            if user_id not in user_manga_settings:
                user_manga_settings[user_id] = {}
            
            user_manga_settings[user_id]["format"] = format_option
            await safe_call(message.reply_text, f"✅ Formato de manga configurado a: **{format_option.upper()}**")
            return
        
        elif text.startswith("/mangadlset"):
            parts = text.split()
            if len(parts) == 1:
                current = user_manga_settings.get(user_id, {}).get("mode", "vol")
                mode_text = "volúmenes" if current == "vol" else "capítulos"
                await safe_call(message.reply_text, f"📚 Modo actual de descarga: **{mode_text}**\nUsa: `/mangadlset vol` o `/mangadlset chap`")
                return
            
            if len(parts) != 2:
                await safe_call(message.reply_text, "Usa: `/mangadlset vol` o `/mangadlset chap`")
                return
            
            mode_option = parts[1].lower()
            if mode_option not in ["vol", "chap"]:
                await safe_call(message.reply_text, "Modo inválido. Usa: vol o chap")
                return
            
            if user_id not in user_manga_settings:
                user_manga_settings[user_id] = {}
            
            user_manga_settings[user_id]["mode"] = mode_option
            mode_text = "volúmenes" if mode_option == "vol" else "capítulos"
            await safe_call(message.reply_text, f"✅ Modo de descarga configurado a: **{mode_text}**")
            return
        
        elif text.startswith("/mangalang"):
            parts = text.split()
            if len(parts) == 1:
                current_lang = user_manga_settings.get(user_id, {}).get("language", "en")
                await safe_call(message.reply_text, f"🌐 Idioma actual de manga: **{current_lang.upper()}**\nUsa: `/mangalang en` o `/mangalang es` o `/mangalang ko`")
                return
            
            if len(parts) != 2:
                await safe_call(message.reply_text, "Usa: `/mangalang en` o `/mangalang es` o `/mangalang ko`")
                return
            
            lang = parts[1].lower()
            valid_langs = ['en', 'es', 'ko', 'ja', 'zh', 'fr', 'de', 'ru', 'pt']
            
            if lang not in valid_langs:
                await safe_call(message.reply_text, f"❌ Idioma no válido. Usa uno de: {', '.join(valid_langs)}")
                return
            
            if user_id not in user_manga_settings:
                user_manga_settings[user_id] = {}
            
            user_manga_settings[user_id]["language"] = lang
            await safe_call(message.reply_text, f"✅ Idioma de manga configurado a: **{lang.upper()}**")
            return
        
        elif text.startswith("/mangasearch "):
            parts = text.split(maxsplit=1)
            if len(parts) < 2:
                await safe_call(message.reply_text, "Usa: `/mangasearch término`")
                return
            
            search_term = parts[1]
            await safe_call(message.reply_text, f"🔍 Buscando manga: **{search_term}**...")
            
            results = self.neko.buscar_manga(search_term)
            
            if not results or len(results) == 0:
                await safe_call(message.reply_text, "❌ No se encontraron resultados")
                return
            
            top_results = results[:5]
            for manga in top_results:
                manga_id = manga.get("id", "")
                title = manga.get("titulo", "Sin título")
                cover_url = manga.get("cover", "")
                
                if cover_url:
                    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
                    temp_path = temp_file.name
                    temp_file.close()
                    
                    if self.neko.download(cover_url, temp_path):
                        caption = f"**{title}**\nID: `{manga_id}`"
                        await safe_call(message.reply_photo, temp_path, caption=caption)
                        os.remove(temp_path)
                    else:
                        await safe_call(message.reply_text, f"**{title}**\nID: `{manga_id}`")
                else:
                    await safe_call(message.reply_text, f"**{title}**\nID: `{manga_id}`")
                
                await asyncio.sleep(0.5)
            
            return
        
        elif text.startswith("/mangadl "):
            parts = text.split()
            if len(parts) < 2:
                await safe_call(message.reply_text, "Usa: `/mangadl MangaID` o `/mangadl MangaID -sc # -sv # -fc # -fv #`")
                return
            
            manga_id = parts[1]
            
            start_chapter = None
            start_volume = None
            end_chapter = None
            end_volume = None
            
            if "-sc" in text:
                try:
                    sc_idx = text.index("-sc")
                    start_chapter = float(text[sc_idx:].split()[1])
                except:
                    await safe_call(message.reply_text, "Formato -sc inválido")
                    return
            
            if "-sv" in text:
                try:
                    sv_idx = text.index("-sv")
                    start_volume = float(text[sv_idx:].split()[1])
                except:
                    await safe_call(message.reply_text, "Formato -sv inválido")
                    return
            
            if "-fc" in text:
                try:
                    fc_idx = text.index("-fc")
                    end_chapter = float(text[fc_idx:].split()[1])
                except:
                    await safe_call(message.reply_text, "Formato -fc inválido")
                    return
            
            if "-fv" in text:
                try:
                    fv_idx = text.index("-fv")
                    end_volume = float(text[fv_idx:].split()[1])
                except:
                    await safe_call(message.reply_text, "Formato -fv inválido")
                    return
            
            if start_chapter and start_volume:
                await safe_call(message.reply_text, "❌ No puedes usar -sc y -sv al mismo tiempo")
                return
            
            if end_chapter and end_volume:
                await safe_call(message.reply_text, "❌ No puedes usar -fc y -fv al mismo tiempo")
                return
            
            user_mode = user_manga_settings.get(user_id, {}).get("mode", "vol")
            user_format = user_manga_settings.get(user_id, {}).get("format", "cbz")
            
            await self._process_manga_download(
                message, manga_id, user_mode, user_format,
                start_chapter, start_volume, end_chapter, end_volume, user_id
            )
            return
        
        elif text.startswith("/nh ") or text.startswith("/3h "):
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
    
    async def _process_manga_download(self, message, manga_id, mode, format_choice,
                                     start_chapter, start_volume, end_chapter, end_volume, user_id):
        try:
            user_lang = user_manga_settings.get(user_id, {}).get("language", "en")
            
            progress_msg = await safe_call(message.reply_text, 
                                          f"📚 Obteniendo capítulos en {user_lang.upper()} para manga {manga_id}...")
            
            manga_info = self.neko.get_manga_info(manga_id, language=user_lang)
            if not manga_info:
                await safe_call(progress_msg.edit_text, "❌ No se pudo obtener información del manga")
                return
            
            chapters = manga_info.get("chapters", [])
            
            if not chapters:
                await safe_call(progress_msg.edit_text, 
                              f"❌ No se encontraron capítulos en {user_lang.upper()} para este manga")
                return
            
            covers = manga_info.get("covers", [])
            volumes_data = manga_info.get("volumes", {})
            
            covers_dict = {}
            for cover in covers:
                covers_dict[cover['volume']] = cover['link']
            
            volumes_order = sorted(volumes_data.keys(), key=lambda x: self._sort_key(x))
            
            if mode == "vol":
                await self._download_manga_by_volumes(
                    progress_msg, manga_id, volumes_order, volumes_data, covers_dict,
                    format_choice, start_chapter, start_volume, end_chapter, end_volume, user_id
                )
            else:
                await self._download_manga_by_chapters(
                    progress_msg, manga_id, chapters, covers_dict, format_choice,
                    start_chapter, start_volume, end_chapter, end_volume, user_id
                )
            
        except Exception as e:
            print(f"Error en _process_manga_download: {e}")
            await safe_call(message.reply_text, f"❌ Error al procesar la descarga: {e}")

    async def _download_manga_by_volumes(self, progress_msg, manga_id, volumes_order, volumes_data, covers_dict,
                                        format_choice, start_chapter, start_volume, end_chapter, end_volume, user_id):
        try:
            user_lang = user_manga_settings.get(user_id, {}).get("language", "en")
            total_volumes = len(volumes_order)
            volume_index = 0
            
            for volume in volumes_order:
                volume_index += 1
                
                if start_volume and volume != 'sin_volumen':
                    if self._sort_key(volume) < self._sort_key(str(start_volume)):
                        continue
                
                if end_volume and volume != 'sin_volumen':
                    if self._sort_key(volume) > self._sort_key(str(end_volume)):
                        break
                
                volume_chapters = volumes_data[volume]
                volume_chapters.sort(key=lambda x: self._sort_key(x['chapter']))
                
                all_volume_images = []
                chapter_range = []
                total_images_downloaded = 0
                total_images_expected = 0
                
                for chapter in volume_chapters:
                    chapter_num = chapter['chapter']
                    
                    if start_chapter and self._sort_key(chapter_num) < self._sort_key(str(start_chapter)):
                        continue
                    
                    if end_chapter and self._sort_key(chapter_num) > self._sort_key(str(end_chapter)):
                        break
                    
                    chapter_range.append(float(chapter_num) if chapter_num.replace('.', '', 1).isdigit() else chapter_num)
                    
                    image_links = self.neko.download_chapter(chapter['id'])
                    if image_links:
                        total_images_expected += len(image_links)
                
                if total_images_expected == 0:
                    continue
                
                await safe_call(progress_msg.edit_text, f"📦 Procesando volumen {volume} ({volume_index}/{total_volumes}) en {user_lang.upper()}... (0/{total_images_expected} Imágenes descargadas)")
                
                for chapter in volume_chapters:
                    chapter_num = chapter['chapter']
                    
                    if start_chapter and self._sort_key(chapter_num) < self._sort_key(str(start_chapter)):
                        continue
                    
                    if end_chapter and self._sort_key(chapter_num) > self._sort_key(str(end_chapter)):
                        break
                    
                    image_links = self.neko.download_chapter(chapter['id'])
                    if image_links:
                        for image_link in image_links:
                            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
                            temp_path = temp_file.name
                            temp_file.close()
                            
                            if self.neko.download(image_link, temp_path):
                                all_volume_images.append(temp_path)
                                total_images_downloaded += 1
                                
                                start_time = time.time()
                                while time.time() - start_time < 5:
                                    await asyncio.sleep(0.1)
                                
                                await safe_call(progress_msg.edit_text, f"📦 Procesando volumen {volume} ({volume_index}/{total_volumes}) en {user_lang.upper()}... ({total_images_downloaded}/{total_images_expected} Imágenes descargadas)")
                            else:
                                os.remove(temp_path)
                    
                    await asyncio.sleep(0.5)
                
                if not all_volume_images:
                    continue
                
                if chapter_range:
                    min_chap = min(chapter_range)
                    max_chap = max(chapter_range)
                    
                    if volume == 'sin_volumen':
                        volume_name = f"Capítulos {min_chap}-{max_chap}"
                        
                        known_volumes = [v for v in volumes_order if v != 'sin_volumen']
                        if known_volumes:
                            last_known_vol = max([float(v) for v in known_volumes if v.replace('.', '', 1).isdigit()], default=1)
                            next_vol_num = int(last_known_vol) + 1
                            volume_name = f"Volumen {next_vol_num} ({min_chap}-{max_chap} Incomplete)"
                    else:
                        volume_name = f"Volumen {volume}"
                        
                        if chapter_range:
                            if len(chapter_range) > 1:
                                volume_name = f"Volumen {volume} ({min_chap}-{max_chap})"
                            else:
                                volume_name = f"Volumen {volume} ({min_chap})"
                
                if format_choice == "cbz":
                    archive_path = self.neko.create_cbz(volume_name, all_volume_images)
                else:
                    archive_path = self.neko.create_pdf(volume_name, all_volume_images)
                
                for image_path in all_volume_images:
                    if os.path.exists(image_path):
                        os.remove(image_path)
                
                if archive_path and os.path.exists(archive_path):
                    cover_url = covers_dict.get(volume, "")
                    
                    if cover_url:
                        temp_cover = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
                        temp_cover_path = temp_cover.name
                        temp_cover.close()
                        
                        if self.neko.download(cover_url, temp_cover_path):
                            await self.app.send_document(
                                progress_msg.chat.id,
                                archive_path,
                                thumb=temp_cover_path,
                                caption=f"📚 {volume_name}"
                            )
                            os.remove(temp_cover_path)
                        else:
                            await self.app.send_document(
                                progress_msg.chat.id,
                                archive_path,
                                caption=f"📚 {volume_name}"
                            )
                    else:
                        await self.app.send_document(
                            progress_msg.chat.id,
                            archive_path,
                            caption=f"📚 {volume_name}"
                        )
                    
                    os.remove(archive_path)
                
                await asyncio.sleep(1)
            
            await safe_call(progress_msg.edit_text, "✅ Descarga de volúmenes completada")
            
        except Exception as e:
            print(f"Error en _download_manga_by_volumes: {e}")
            await safe_call(progress_msg.edit_text, f"❌ Error en la descarga: {e}")
    
    async def _download_manga_by_chapters(self, progress_msg, manga_id, chapters, format_choice,
                                         start_chapter, start_volume, end_chapter, end_volume, user_id):
        try:
            user_lang = user_manga_settings.get(user_id, {}).get("language", "en")
            chapters.sort(key=lambda x: self._sort_key(x['chapter']))
            
            filtered_chapters = []
            
            for chapter in chapters:
                chapter_num = chapter['chapter']
                volume = chapter['volume'] if chapter['volume'] else 'sin_volumen'
                
                if start_chapter and self._sort_key(chapter_num) < self._sort_key(str(start_chapter)):
                    continue
                
                if end_chapter and self._sort_key(chapter_num) > self._sort_key(str(end_chapter)):
                    break
                
                if start_volume and volume != 'sin_volumen':
                    if self._sort_key(volume) < self._sort_key(str(start_volume)):
                        continue
                
                if end_volume and volume != 'sin_volumen':
                    if self._sort_key(volume) > self._sort_key(str(end_volume)):
                        break
                
                filtered_chapters.append(chapter)
            
            total_chapters = len(filtered_chapters)
            
            for idx, chapter in enumerate(filtered_chapters):
                chapter_num = chapter['chapter']
                chapter_id = chapter['id']
                
                image_links = self.neko.download_chapter(chapter_id)
                
                if not image_links:
                    continue
                
                total_images = len(image_links)
                downloaded_images = 0
                
                await safe_call(progress_msg.edit_text, f"📖 Descargando capítulo {chapter_num} ({idx+1}/{total_chapters}) en {user_lang.upper()}... (0/{total_images} Imágenes descargadas)")
                
                all_chapter_images = []
                for image_link in image_links:
                    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
                    temp_path = temp_file.name
                    temp_file.close()
                    
                    if self.neko.download(image_link, temp_path):
                        all_chapter_images.append(temp_path)
                        downloaded_images += 1
                        
                        start_time = time.time()
                        while time.time() - start_time < 5:
                            await asyncio.sleep(0.1)
                        
                        await safe_call(progress_msg.edit_text, f"📖 Descargando capítulo {chapter_num} ({idx+1}/{total_chapters}) en {user_lang.upper()}... ({downloaded_images}/{total_images} Imágenes descargadas)")
                    else:
                        os.remove(temp_path)
                
                if not all_chapter_images:
                    continue
                
                chapter_name = f"Capítulo {chapter_num}"
                
                if format_choice == "cbz":
                    archive_path = self.neko.create_cbz(chapter_name, all_chapter_images)
                else:
                    archive_path = self.neko.create_pdf(chapter_name, all_chapter_images)
                
                for image_path in all_chapter_images:
                    if os.path.exists(image_path):
                        os.remove(image_path)
                
                if archive_path and os.path.exists(archive_path):
                    await self.app.send_document(
                        progress_msg.chat.id,
                        archive_path,
                        caption=f"📖 {chapter_name}"
                    )
                    os.remove(archive_path)
                
                await asyncio.sleep(1)
            
            await safe_call(progress_msg.edit_text, "✅ Descarga de capítulos completada")
            
        except Exception as e:
            print(f"Error en _download_manga_by_chapters: {e}")
            await safe_call(progress_msg.edit_text, f"❌ Error en la descarga: {e}")
    
    def _sort_key(self, val):
        if not val or val == 'sin_volumen':
            return (float('inf'), '')
        try:
            return (float(val), '')
        except ValueError:
            return (float('inf'), val)
    
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
