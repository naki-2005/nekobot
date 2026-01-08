import os
import asyncio
import sys
import argparse
import shutil
import tempfile
import time
import threading
import base64
import aiohttp
import aiofiles
import bencodepy
from concurrent.futures import ThreadPoolExecutor
from pyrogram import Client, filters
from pyrogram.types import Message, BotCommand, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors import FloodWait
from neko import Neko
from server import run_flask
import hashlib

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
        self.session = None
        self.download_pool = ThreadPoolExecutor(max_workers=20)
        self.nyaa_cache = {}
        self.current_positions = {}
        self.user_downloads = {}
        
        @self.app.on_message(filters.text & filters.private)
        async def _handle_message(client: Client, message: Message):
            global set_cmd
            if not set_cmd:
                await self.lista_cmd()
                set_cmd = True
            await self._handle_message(client, message)
        @self.app.on_callback_query()
        async def _handle_callback(client, callback_query):
            await self._handle_callback_query(callback_query)
    
    async def _handle_callback_query(self, callback_query):
        data = callback_query.data
        user_id = callback_query.from_user.id
        
        if data.startswith("nyaa_"):
            parts = data.split("_")
            if len(parts) < 3:
                return
            
            action = parts[1]
            query_hash = parts[2]
            extra = parts[3] if len(parts) > 3 else None
            
            if query_hash not in self.nyaa_cache:
                await callback_query.answer("❌ Cache expirada", show_alert=True)
                return
            
            cache_data = self.nyaa_cache[query_hash]
            results = cache_data["results"]
            total_results = len(results)
            
            cache_key = f"{user_id}_{query_hash}"
            if cache_key not in self.current_positions:
                self.current_positions[cache_key] = 0
            current_pos = self.current_positions[cache_key]
            
            if action == "first":
                new_pos = 0
            elif action == "prev":
                new_pos = max(0, current_pos - 1)
            elif action == "next":
                new_pos = min(total_results - 1, current_pos + 1)
            elif action == "last":
                new_pos = total_results - 1
            elif action == "torrent":
                result = results[current_pos]
                torrent_link = result.get("torrent", "")
                if torrent_link:
                    await callback_query.message.reply(f"📎 **Torrent:**\n`{torrent_link}`")
                    await callback_query.answer()
                else:
                    await callback_query.answer("❌ No hay enlace torrent disponible", show_alert=True)
                return
            elif action == "magnet":
                result = results[current_pos]
                magnet_link = result.get("magnet", "")
                if magnet_link:
                    await callback_query.message.reply(f"🧲 **Magnet:**\n`{magnet_link}`")
                    await callback_query.answer()
                else:
                    await callback_query.answer("❌ No hay enlace magnet disponible", show_alert=True)
                return
            elif action == "download":
                result = results[current_pos]
                await self._start_torrent_download(callback_query.message, result, user_id)
                await callback_query.answer("✅ Descarga iniciada")
                return
            else:
                return
            
            self.current_positions[cache_key] = new_pos
            await self._update_nyaa_message(callback_query.message, results, new_pos, query_hash)
            await callback_query.answer()
            
    async def _send_document_with_progress(self, chat_id, document_path, caption="", thumb=None):
        progress_msg = await safe_call(self.app.send_message, chat_id, "📤 Preparando envío...")
        start_time = time.time()
        upload_completed = False
        current_bytes = 0
        total_bytes = os.path.getsize(document_path)
        
        async def update_upload_progress():
            last_update = time.time()
            while not upload_completed:
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
                            f"📤 Enviando archivo...\n"
                            f"🕒 Tiempo: {formatted_time}\n"
                            f"📊 Progreso: {current_mb:.2f} MB / {total_mb:.2f} MB\n"
                            f"📉 [{bar}] {progress_ratio*100:.1f}%\n"
                            f"📄 Archivo: {os.path.basename(document_path)}"
                        )
                        last_update = time.time()
                await asyncio.sleep(0.5)
        
        def upload_progress(current, total):
            nonlocal current_bytes
            current_bytes = current
        
        upload_task = asyncio.create_task(update_upload_progress())
        
        try:
            await safe_call(self.app.send_document, 
                           chat_id=chat_id, 
                           document=document_path, 
                           caption=caption,
                           thumb=thumb,
                           progress=upload_progress)
            upload_completed = True
            await upload_task
            await safe_call(progress_msg.delete)
        except Exception as e:
            upload_completed = True
            await upload_task
            await safe_call(progress_msg.edit_text, f"❌ Error al enviar: {e}")
            raise
    async def get_session(self):
        if not self.session:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def async_download(self, url, save_path):
        try:
            session = await self.get_session()
            async with session.get(url, timeout=30) as response:
                if response.status == 200:
                    async with aiofiles.open(save_path, 'wb') as f:
                        await f.write(await response.read())
                    return True
        except Exception as e:
            print(f"Error descargando {url}: {e}")
        return False
    
    async def download_images_concurrently(self, image_urls, max_concurrent=10):
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def download_one(url):
            async with semaphore:
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
                temp_path = temp_file.name
                temp_file.close()
                
                if await self.async_download(url, temp_path):
                    return temp_path
                return None
        
        tasks = [download_one(url) for url in image_urls]
        results = await asyncio.gather(*tasks)
        return [r for r in results if r]
    
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
            download_tasks = []
            
            for manga in top_results:
                manga_id = manga.get("id", "")
                title = manga.get("titulo", "Sin título")
                cover_url = manga.get("cover", "")
                
                if cover_url:
                    download_tasks.append((cover_url, title, manga_id))
                else:
                    await safe_call(message.reply_text, f"**{title}**\nID: `{manga_id}`")
            
            for cover_url, title, manga_id in download_tasks:
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
                temp_path = temp_file.name
                temp_file.close()
                
                if await self.async_download(cover_url, temp_path):
                    caption = f"**{title}**\nID: `{manga_id}`"
                    await safe_call(message.reply_photo, temp_path, caption=caption)
                    os.remove(temp_path)
                else:
                    await safe_call(message.reply_text, f"**{title}**\nID: `{manga_id}`")
            
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
                    if await self.async_download(selected_url, temp_path):
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
        
        elif text.startswith("/nyaa ") or text.startswith("/nyaa18 "):
            parts = text.split(maxsplit=1)
            if len(parts) < 2:
                await safe_call(message.reply_text, "Usa: `/nyaa término` o `/nyaa18 término`")
                return
            
            search_term = parts[1]
            is_nsfw = text.startswith("/nyaa18 ")
            
            search_msg = await safe_call(message.reply_text, f"🔍 Buscando en {'Sukebei' if is_nsfw else 'Nyaa'}...")
            
            results = self.neko.nyaa_fap(search_term) if is_nsfw else self.neko.nyaa_fun(search_term)
            
            if not results:
                await safe_call(search_msg.edit_text, "❌ No se encontraron resultados")
                return
            
            query_hash = hashlib.md5(f"{search_term}_{is_nsfw}".encode()).hexdigest()[:8]
            self.nyaa_cache[query_hash] = {
                "results": results,
                "timestamp": time.time(),
                "query": search_term,
                "nsfw": is_nsfw
            }
            
            cache_key = f"{message.from_user.id}_{query_hash}"
            self.current_positions[cache_key] = 0
            
            await self._send_nyaa_message(search_msg, results, 0, query_hash)
            return
        
        elif text.startswith("/leech"):
            await self._handle_leech_command(message)
            return
    
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
                    progress_msg, manga_id, chapters, format_choice,
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
            
            for volume_index, volume in enumerate(volumes_order, 1):
                
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
                        downloaded_images = await self.download_images_concurrently(image_links, max_concurrent=10)
                        all_volume_images.extend(downloaded_images)
                        total_images_downloaded += len(downloaded_images)
                        
                        await safe_call(progress_msg.edit_text, f"📦 Procesando volumen {volume} ({volume_index}/{total_volumes}) en {user_lang.upper()}... ({total_images_downloaded}/{total_images_expected} Imágenes descargadas)")
                
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
                        
                        if await self.async_download(cover_url, temp_cover_path):
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
                
                await asyncio.sleep(0.2)
            
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
            
            for idx, chapter in enumerate(filtered_chapters, 1):
                chapter_num = chapter['chapter']
                chapter_id = chapter['id']
                
                image_links = self.neko.download_chapter(chapter_id)
                
                if not image_links:
                    continue
                
                total_images = len(image_links)
                
                await safe_call(progress_msg.edit_text, f"📖 Descargando capítulo {chapter_num} ({idx}/{total_chapters}) en {user_lang.upper()}... (0/{total_images} Imágenes descargadas)")
                
                downloaded_images = await self.download_images_concurrently(image_links, max_concurrent=10)
                
                if not downloaded_images:
                    continue
                
                await safe_call(progress_msg.edit_text, f"📖 Descargando capítulo {chapter_num} ({idx}/{total_chapters}) en {user_lang.upper()}... ({len(downloaded_images)}/{total_images} Imágenes descargadas)")
                
                chapter_name = f"Capítulo {chapter_num}"
                
                if format_choice == "cbz":
                    archive_path = self.neko.create_cbz(chapter_name, downloaded_images)
                else:
                    archive_path = self.neko.create_pdf(chapter_name, downloaded_images)
                
                for image_path in downloaded_images:
                    if os.path.exists(image_path):
                        os.remove(image_path)
                
                if archive_path and os.path.exists(archive_path):
                    await self.app.send_document(
                        progress_msg.chat.id,
                        archive_path,
                        caption=f"📖 {chapter_name}"
                    )
                    os.remove(archive_path)
                
                await asyncio.sleep(0.2)
            
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
        
        for idx, page_num in enumerate(pages, 1):
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
                
                await safe_call(progress_msg.edit_text, f"Progreso de descarga de {g} {idx}/{len(pages)}{range_info} - Página {pagina_actual}/{paginas_totales}")
                
                if len(current_batch) >= batch_size:
                    await self._send_photo_batch(message, photo_paths=current_batch, batch_number=(idx//batch_size)+1, user_id=user_id)
                    for photo in current_batch:
                        try:
                            os.remove(photo)
                        except:
                            pass
                    current_batch = []
                    await asyncio.sleep(0.2)
                    
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
        
        async def download_page(page_num):
            try:
                result = self.neko.hito(g, page_num)
                if "error" in result:
                    return None
                
                pagina_actual = int(result["actual_page"])
                paginas_totales = int(result["total_pages"])
                datos_imagen = result["img"]
                imagen_decodificada = base64.b64decode(datos_imagen)
                digitos = len(str(paginas_totales))
                nombre_salida = f"{pagina_actual:0{digitos}d}.png"
                save_path = os.path.join(temp_dir, nombre_salida)
                
                with open(save_path, 'wb') as archivo_imagen:
                    archivo_imagen.write(imagen_decodificada)
                
                return pagina_actual
            except Exception as e:
                print(f"Error descargando página {page_num}: {e}")
                return None
        
        tasks = [download_page(page_num) for page_num in pages]
        results = await asyncio.gather(*tasks)
        
        downloaded_count = sum(1 for r in results if r is not None)
        
        if downloaded_count == 0:
            await safe_call(progress_msg.edit_text, "❌ No se pudo descargar ninguna página")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return
        
        range_info = ""
        if start_page != 1 or end_page != total_pages:
            range_info = f" (Progreso limitado al rango {start_page}-{end_page})"
        
        await safe_call(progress_msg.edit_text, f"Progreso de descarga de {g} {downloaded_count}/{len(pages)}{range_info} - Preparando archivo...")
        
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
                
                download_tasks = []
                for i, img_url in enumerate(images):
                    img_path = os.path.join(temp_dir, f"{i+start_page:04d}.jpg")
                    download_tasks.append(self.async_download(img_url, img_path))
                
                await asyncio.gather(*download_tasks)
                
                cbz_path = self.neko.create_cbz(nombre, [os.path.join(temp_dir, f) for f in sorted(os.listdir(temp_dir))])
                if cbz_path and os.path.exists(cbz_path):
                    await safe_call(message.reply_document, cbz_path)
                    os.remove(cbz_path)
                shutil.rmtree(temp_dir, ignore_errors=True)
            elif format_choice == "pdf":
                temp_dir = "temp_pdf"
                os.makedirs(temp_dir, exist_ok=True)
                
                download_tasks = []
                for i, img_url in enumerate(images):
                    img_path = os.path.join(temp_dir, f"{i+start_page:04d}.jpg")
                    download_tasks.append(self.async_download(img_url, img_path))
                
                await asyncio.gather(*download_tasks)
                
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
            
            download_tasks = []
            for idx, url in enumerate(batch):
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
                temp_path = temp_file.name
                temp_file.close()
                download_tasks.append((url, temp_path))
            
            for url, temp_path in download_tasks:
                if await self.async_download(url, temp_path):
                    temp_files.append(temp_path)
                    media_group.append(InputMediaPhoto(temp_path))
            
            if media_group:
                await safe_call(message.reply_media_group, media_group)
                for tf in temp_files:
                    try:
                        os.remove(tf)
                    except:
                        pass
                await asyncio.sleep(0.2)
    
    async def _process_search_json(self, message, result, user_id):
        if "error" in result:
            await safe_call(message.reply_text, f"Error: `{result['error']}`")
            return
        resultados = result if isinstance(result, list) else result.get("resultados", [])
        if not resultados:
            await safe_call(message.reply_text, "No se encontraron resultados")
            return
        
        download_tasks = []
        for item in resultados:
            code = item.get("code") or item.get("codigo", "")
            nombre = item.get("title") or item.get("nombre", "Sin titulo")
            miniatura = item.get("thumbnail") or item.get("miniatura", "")
            if miniatura.startswith("//"):
                miniatura = f"https:{miniatura}"
            if code and miniatura:
                download_tasks.append((miniatura, nombre, code))
            elif code:
                await safe_call(message.reply_text, f"**{nombre}**\nCódigo: `{code}`")
        
        for miniatura, nombre, code in download_tasks:
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
            temp_path = temp_file.name
            temp_file.close()
            
            if await self.async_download(miniatura, temp_path):
                await safe_call(message.reply_photo, temp_path, caption=f"**{nombre}**\nCódigo: `{code}`")
                os.remove(temp_path)
            else:
                await safe_call(message.reply_text, f"**{nombre}**\nCódigo: `{code}`")
        
        await asyncio.sleep(0.2)
    
    def _format_tags(self, tags):
        if not tags:
            return ""
        tag_lines = []
        for category, items in tags.items():
            if items:
                items_str = ", ".join(items)
                tag_lines.append(f"**{category}:** {items_str}")
        return "\n".join(tag_lines)
    
    async def _send_nyaa_message(self, message, results, position, query_hash):
        result = results[position]
        total = len(results)
        
        text = f"**Resultado {position+1}/{total}**\n"
        text += f"**Nombre:** `{result['name']}`\n"
        text += f"**Tamaño:** {result['size']}\n"
        text += f"**Fecha:** {result['date']}\n"
        
        keyboard = [
            [
                InlineKeyboardButton("◀️", callback_data=f"nyaa_first_{query_hash}"),
                InlineKeyboardButton("⏪", callback_data=f"nyaa_prev_{query_hash}"),
                InlineKeyboardButton(f"{position+1}/{total}", callback_data="nyaa_page"),
                InlineKeyboardButton("⏩", callback_data=f"nyaa_next_{query_hash}"),
                InlineKeyboardButton("▶️", callback_data=f"nyaa_last_{query_hash}")
            ],
            [
                InlineKeyboardButton("📎 Torrent", callback_data=f"nyaa_torrent_{query_hash}"),
                InlineKeyboardButton("🧲 Magnet", callback_data=f"nyaa_magnet_{query_hash}")
            ],
            [
                InlineKeyboardButton("🔽 Descargar", callback_data=f"nyaa_download_{query_hash}")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await message.edit_text(text, reply_markup=reply_markup)
        except:
            await safe_call(message.reply_text, text, reply_markup=reply_markup)
    
    async def _update_nyaa_message(self, message, results, position, query_hash):
        result = results[position]
        total = len(results)
        
        text = f"**Resultado {position+1}/{total}**\n"
        text += f"**Nombre:** `{result['name']}`\n"
        text += f"**Tamaño:** {result['size']}\n"
        text += f"**Fecha:** {result['date']}\n"
        
        keyboard = [
            [
                InlineKeyboardButton("◀️", callback_data=f"nyaa_first_{query_hash}"),
                InlineKeyboardButton("⏪", callback_data=f"nyaa_prev_{query_hash}"),
                InlineKeyboardButton(f"{position+1}/{total}", callback_data="nyaa_page"),
                InlineKeyboardButton("⏩", callback_data=f"nyaa_next_{query_hash}"),
                InlineKeyboardButton("▶️", callback_data=f"nyaa_last_{query_hash}")
            ],
            [
                InlineKeyboardButton("📎 Torrent", callback_data=f"nyaa_torrent_{query_hash}"),
                InlineKeyboardButton("🧲 Magnet", callback_data=f"nyaa_magnet_{query_hash}")
            ],
            [
                InlineKeyboardButton("🔽 Descargar", callback_data=f"nyaa_download_{query_hash}")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await message.edit_text(text, reply_markup=reply_markup)
        except FloodWait as e:
            await asyncio.sleep(e.value)
            await message.edit_text(text, reply_markup=reply_markup)
    
    async def _handle_leech_command(self, message):
        user_id = message.from_user.id
        
        if message.reply_to_message:
            reply = message.reply_to_message
            if reply.document and reply.document.file_size <= 5 * 1024 * 1024:
                await self._process_torrent_file(message, reply.document)
                return
            elif reply.text:
                await self._process_torrent_text(message, reply.text)
                return
            else:
                await safe_call(message.reply_text, "❌ Responde a un mensaje con texto o archivo .torrent (<5MB)")
                return
        
        parts = message.text.split(maxsplit=1)
        if len(parts) > 1:
            torrent_input = parts[1].strip()
            await self._process_torrent_text(message, torrent_input)
        else:
            await safe_call(message.reply_text, "❌ Usa: `/leech magnet:...` o `/leech http://...torrent` o responde a un archivo")
    
    async def _process_torrent_file(self, message, document):
        if not document.file_name.endswith('.torrent'):
            await safe_call(message.reply_text, "❌ El archivo debe ser .torrent")
            return
        
        progress_msg = await safe_call(message.reply_text, "📥 Descargando archivo torrent...")
        
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".torrent")
        temp_path = temp_file.name
        temp_file.close()
        
        await self.app.download_media(document, file_name=temp_path)
        
        with open(temp_path, "rb") as f:
            torrent_data = f.read()
        
        magnet = self._torrent_to_magnet(torrent_data)
        os.remove(temp_path)
        
        await safe_call(progress_msg.edit_text, f"✅ Magnet generado:\n`{magnet[:100]}...`")
        
        await self._start_torrent_download(message, {"magnet": magnet}, message.from_user.id)
    
    async def _process_torrent_text(self, message, text):
        text = text.strip()
        
        if text.startswith("magnet:?"):
            magnet = text
            await self._start_torrent_download(message, {"magnet": magnet}, message.from_user.id)
            return
        
        elif text.endswith(".torrent"):
            if text.startswith("http://") or text.startswith("https://"):
                await safe_call(message.reply_text, "📥 Descargando torrent desde URL...")
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(text) as response:
                            if response.status == 200:
                                torrent_data = await response.read()
                                magnet = self._torrent_to_magnet(torrent_data)
                                await safe_call(message.reply_text, f"✅ Magnet generado:\n`{magnet[:100]}...`")
                                await self._start_torrent_download(message, {"magnet": magnet}, message.from_user.id)
                            else:
                                await safe_call(message.reply_text, f"❌ Error al descargar: {response.status}")
                except Exception as e:
                    await safe_call(message.reply_text, f"❌ Error: {e}")
            else:
                if os.path.exists(text):
                    with open(text, "rb") as f:
                        torrent_data = f.read()
                    magnet = self._torrent_to_magnet(torrent_data)
                    await safe_call(message.reply_text, f"✅ Magnet generado:\n`{magnet[:100]}...`")
                    await self._start_torrent_download(message, {"magnet": magnet}, message.from_user.id)
                else:
                    await safe_call(message.reply_text, "❌ Archivo no encontrado")
        else:
            await safe_call(message.reply_text, "❌ Enlace no válido. Debe ser magnet:? o .torrent")
    
    def _torrent_to_magnet(self, torrent_data: bytes) -> str:
        try:
            torrent_dict = bencodepy.decode(torrent_data)
            info = torrent_dict[b'info']
            
            info_bencoded = bencodepy.encode(info)
            infohash = hashlib.sha1(info_bencoded).hexdigest()
            
            trackers = []
            if b'announce' in torrent_dict:
                trackers.append(torrent_dict[b'announce'].decode())
            if b'announce-list' in torrent_dict:
                for tier in torrent_dict[b'announce-list']:
                    for tr in tier:
                        trackers.append(tr.decode())
            
            magnet = f"magnet:?xt=urn:btih:{infohash}"
            if b'name' in info:
                magnet += f"&dn={info[b'name'].decode()}"
            for tr in trackers:
                magnet += f"&tr={tr}"
            
            return magnet
        except Exception as e:
            raise Exception(f"Error convirtiendo torrent a magnet: {e}")
    
    async def _start_torrent_download(self, message, result, user_id):
        magnet = result.get("magnet", "")
        if not magnet:
            await safe_call(message.reply_text, "❌ No hay enlace magnet disponible")
            return
        
        download_path = os.path.join(os.getcwd(), "vault", str(user_id))
        os.makedirs(download_path, exist_ok=True)
        
        status_msg = await safe_call(message.reply_text, "⏳ Iniciando descarga torrent...")
        last_update_time = time.time()
        
        try:
            download_generator = self.neko.download_magnet(magnet, download_path)
            final_path = None
            
            async for progress_text in download_generator:
                current_time = time.time()
                if current_time - last_update_time >= 10:
                    await safe_call(status_msg.edit_text, progress_text)
                    last_update_time = current_time
                
                if not progress_text.startswith("⏳"):
                    final_path = progress_text
            
            if final_path and os.path.exists(final_path):
                if os.path.isfile(final_path):
                    await self._send_document_with_progress(
                        message.chat.id,
                        final_path,
                        caption=f"✅ Descarga completada: {os.path.basename(final_path)}"
                    )
                elif os.path.isdir(final_path):
                    for root, dirs, files in os.walk(final_path):
                        for file in files:
                            file_path = os.path.join(root, file)
                            try:
                                await self._send_document_with_progress(
                                    message.chat.id,
                                    file_path,
                                    caption=f"📁 {os.path.basename(file_path)}"
                                )
                                await asyncio.sleep(0.5)
                            except Exception as e:
                                print(f"Error enviando archivo {file_path}: {e}")
            
            await safe_call(status_msg.edit_text, f"✅ Descarga completada y enviada")
            
        except Exception as e:
            await safe_call(status_msg.edit_text, f"❌ Error en la descarga: {e}")
            
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
