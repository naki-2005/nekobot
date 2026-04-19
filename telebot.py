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
import re
import zipfile
import requests
from concurrent.futures import ThreadPoolExecutor
from pyrogram import Client, filters
from pyrogram.types import Message, BotCommand, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors import FloodWait
from neko import Neko
from server import run_flask
import hashlib
from io import BytesIO
from PIL import Image
import json
import dlselenium
import dlyt
import uuid
from botcmd.manga import MangaCommands
from botcmd.adult_manga import AdultMangaCommands
from botcmd.tdl import TorrentDownloadCommands
from botcmd.files import FileCommands

set_cmd = False
user_settings = {}
user_manga_settings = {}
user_auto_settings = {}
user_nextnames = {}
user_premium_settings = {}
user_nh_quality = {}
premium_enabled = False
premium_limit = 3995
normal_limit = 1995

async def convert_video_to_mp3(video_path: str, output_path: str = None, metadata: dict = None) -> str:
    import subprocess
    
    if output_path is None:
        output_path = os.path.splitext(video_path)[0] + ".mp3"
    
    try:
        cmd = [
            'ffmpeg',
            '-i', video_path,
            '-acodec', 'mp3',
            '-ab', '192k',
            '-ar', '44100',
            '-y'
        ]
        
        if metadata:
            if 'title' in metadata:
                cmd.extend(['-metadata', f'title={metadata["title"]}'])
            if 'artist' in metadata:
                cmd.extend(['-metadata', f'artist={metadata["artist"]}'])
            if 'album' in metadata:
                cmd.extend(['-metadata', f'album={metadata["album"]}'])
            if 'year' in metadata:
                cmd.extend(['-metadata', f'date={metadata["year"]}'])
        
        cmd.append(output_path)
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        await process.communicate()
        
        if process.returncode != 0:
            raise Exception(f"FFmpeg error code: {process.returncode}")
        
        if metadata and 'cover' in metadata and metadata['cover']:
            await add_cover_art(output_path, metadata['cover'])
        
        return output_path
    except Exception as e:
        print(f"Error converting video to audio: {e}")
        raise

async def add_cover_art(mp3_path: str, cover_url: str) -> None:
    import subprocess
    import aiohttp
    import aiofiles
    
    temp_cover = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
    temp_cover_path = temp_cover.name
    temp_cover.close()
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(cover_url) as response:
                if response.status == 200:
                    async with aiofiles.open(temp_cover_path, 'wb') as f:
                        await f.write(await response.read())
                else:
                    raise Exception("Failed to download cover image")
        
        temp_path = mp3_path + ".temp.mp3"
        
        cmd = [
            'ffmpeg',
            '-i', mp3_path,
            '-i', temp_cover_path,
            '-c', 'copy',
            '-map', '0',
            '-map', '1',
            '-metadata', 's:v=title=Album cover',
            '-metadata', 's:v=comment=Cover (front)',
            '-id3v2_version', '3',
            temp_path
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        await process.communicate()
        
        if process.returncode == 0:
            shutil.move(temp_path, mp3_path)
    except Exception as e:
        print(f"Error adding cover art: {e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)
    finally:
        if os.path.exists(temp_cover_path):
            os.remove(temp_cover_path)
            
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
    def __init__(self, api_id, api_hash, bot_token, admin_list):
        self.api_id = api_id
        self.api_hash = api_hash
        self.bot_token = bot_token
        self.admin_list = admin_list
        self.neko = Neko()
        self.app = Client("nekobot", api_id=int(api_id), api_hash=api_hash, bot_token=bot_token)
        self.flask_thread = None
        self.me_id = None
        self.download_pool = ThreadPoolExecutor(max_workers=20)
        self.nyaa_cache = {}
        self.current_positions = {}
        self.user_downloads = {}
        
        self.manga_cmd = MangaCommands(self)
        self.adult_manga_cmd = AdultMangaCommands(self)
        self.tdl_cmd = TorrentDownloadCommands(self)
        self.files_cmd = FileCommands(self)
        
        @self.app.on_message(filters.private)
        async def _handle_message(client: Client, message: Message):
            global set_cmd
            if not set_cmd:
                await self.lista_cmd()
                set_cmd = True
            await self._handle_message(client, message)
        @self.app.on_callback_query()
        async def _handle_callback(client, callback_query):
            await self._handle_callback_query(callback_query)
    
    def is_admin(self, user_id, username=None):
        for admin in self.admin_list:
            if str(admin) == str(user_id):
                return True
            if username and str(admin) == username:
                return True
        return False
    
    async def _handle_callback_query(self, callback_query):
        data = callback_query.data
        user_id = callback_query.from_user.id
        
        if data.startswith("dl_"):
            parts = data.split("_", 2)
            if len(parts) < 3:
                return
            action = parts[1]
            cache_id = parts[2]
            if cache_id not in self.user_downloads:
                await callback_query.answer("❌ Enlace expirado, descarga de nuevo", show_alert=True)
                return
            link = self.user_downloads[cache_id]
            await callback_query.answer(f"Enviando como {action}...")
            await callback_query.message.delete()
            await self._send_as_format(callback_query.message.chat.id, link, action)
            return
        
        if data.startswith("auto_"):
            action = data[5:]
            if action == "info":
                await callback_query.answer("Este boton solo es de información", show_alert=True)
                return
            if user_id not in user_auto_settings:
                user_auto_settings[user_id] = {
                    "file_to_link": False,
                    "doujins": False,
                    "mangas": False,
                    "torrents": False
                }
            current_state = user_auto_settings[user_id].get(action, False)
            user_auto_settings[user_id][action] = not current_state
            await self._show_auto_menu(callback_query.message, user_id)
            await callback_query.answer()
            return
        
        if data.startswith("nhq_"):
            action = data[4:]
            if action == "hd":
                user_nh_quality[user_id] = "hd"
                await callback_query.answer("✅ Calidad HD activada (alta calidad)", show_alert=True)
            elif action == "sd":
                user_nh_quality[user_id] = "thumb"
                await callback_query.answer("✅ Calidad SD activada (miniaturas)", show_alert=True)
            await self._show_nh_quality_menu(callback_query.message, user_id)
            return
        
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
                    await callback_query.message.reply(f"`{torrent_link}`")
                    await callback_query.answer()
                else:
                    await callback_query.answer("❌ No hay enlace torrent disponible", show_alert=True)
                return
            elif action == "magnet":
                result = results[current_pos]
                magnet_link = result.get("magnet", "")
                if magnet_link:
                    await callback_query.message.reply(f"`{magnet_link}`")
                    await callback_query.answer()
                else:
                    await callback_query.answer("❌ No hay enlace magnet disponible", show_alert=True)
                return
            elif action == "download":
                result = results[current_pos]
                await self.tdl_cmd.start_torrent_download(callback_query.message, result, user_id)
                await callback_query.answer("✅ Descarga iniciada")
                return
            else:
                return
            self.current_positions[cache_key] = new_pos
            await self._update_nyaa_message(callback_query.message, results, new_pos, query_hash)
            await callback_query.answer()

    async def _show_nh_quality_menu(self, message, user_id):
        current_quality = user_nh_quality.get(user_id, "hd")
        hd_status = "✅" if current_quality == "hd" else "❌"
        sd_status = "✅" if current_quality == "thumb" else "❌"
        text = f"🎨 **Calidad de descarga nhentai**\n\n"
        text += f"**HD** {hd_status} - Alta calidad (imágenes originales)\n"
        text += f"**SD** {sd_status} - Miniaturas (menor tamaño)\n\n"
        text += f"Selecciona tu calidad preferida:"
        keyboard = [
            [
                InlineKeyboardButton(f"{hd_status} HD", callback_data="nhq_hd"),
                InlineKeyboardButton(f"{sd_status} SD", callback_data="nhq_sd")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await message.edit_text(text, reply_markup=reply_markup)
        except:
            await safe_call(message.reply_text, text, reply_markup=reply_markup)

    async def _send_document_with_progress(self, chat_id, document_path, caption="", thumb=None, reply_to_message_id=None, user_id=None):
        print(f"[DEBUG] Intentando enviar: {document_path}, tamaño: {os.path.getsize(document_path) if os.path.exists(document_path) else 'NO EXISTE'}")
        if not os.path.exists(document_path):
            print(f"[ERROR] Archivo no existe: {document_path}")
            await safe_call(self.app.send_message, chat_id, f"❌ Error: Archivo no encontrado: {os.path.basename(document_path)}")
            return
        file_size_mb = os.path.getsize(document_path) / (1024 * 1024)
        
        global premium_enabled
        
        if premium_enabled:
            if file_size_mb > 4000:
                parts = self.neko.compress_to_7z(document_path, 3995)
                if parts:
                    for part in parts:
                        await self._send_document_with_progress(chat_id, part, f"{caption} (Parte {os.path.basename(part).split('.')[-1]})", user_id=user_id)
                    return
        else:
            if file_size_mb > 1995:
                parts = self.neko.compress_to_7z(document_path, 1995)
                if parts:
                    for part in parts:
                        await self._send_document_with_progress(chat_id, part, f"{caption} (Parte {os.path.basename(part).split('.')[-1]})", user_id=user_id)
                    return
        
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
                    if elapsed == 0:
                        speed = 0
                    else:
                        speed = (current_bytes / elapsed) / (1024 * 1024)
                    formatted_time = format_time(elapsed)
                    progress_ratio = current_bytes / total_bytes if total_bytes else 0
                    bar_length = 20
                    filled_length = int(bar_length * progress_ratio)
                    bar = "█" * filled_length + "▒" * (bar_length - filled_length)
                    current_mb = current_bytes / (1024 * 1024)
                    total_mb = total_bytes / (1024 * 1024)
                    if time.time() - last_update >= 10:
                        progress_text = (
                            f"📤 Enviando archivo...\n"
                            f"🕒 Tiempo: {formatted_time}\n"
                            f"📊 Progreso: {current_mb:.2f} MB / {total_mb:.2f} MB\n"
                            f"📉 [{bar}] {progress_ratio*100:.1f}%\n"
                            f"🚀 Velocidad: {speed:.1f} MB/s\n"
                            f"📄 Archivo: {os.path.basename(document_path)}"
                        )
                        await safe_call(progress_msg.edit_text, progress_text)
                        last_update = time.time()
                await asyncio.sleep(1)
        def upload_progress(current, total):
            nonlocal current_bytes
            current_bytes = current
        upload_task = asyncio.create_task(update_upload_progress())
        try:
            await safe_call(
                self.app.send_document,
                chat_id=chat_id,
                document=document_path,
                caption=caption,
                thumb=thumb,
                progress=upload_progress
            )
            upload_completed = True
            await upload_task
            try:
                await safe_call(progress_msg.delete)
            except:
                pass
            try:
                os.remove(document_path)
            except:
                pass
        except Exception as e:
            upload_completed = True
            await upload_task
            try:
                await safe_call(progress_msg.delete)
            except:
                pass
            print(f"❌ Error enviando documento: {e}")
            try:
                await safe_call(
                    self.app.send_document,
                    chat_id=chat_id,
                    document=document_path,
                    caption=caption,
                    thumb=thumb
                )
                if os.path.exists(document_path):
                    os.remove(document_path)
            except Exception as e2:
                print(f"❌ Error en reintento: {e2}")
                raise

    async def scrap(self, message, link, texto_buscar):
        try:
            progress_msg = await safe_call(message.reply_text, f"🔍 Escaneando {link}...")
            resultados = self.neko.scrap(link, texto_buscar)
            if not resultados:
                await safe_call(progress_msg.edit_text, f"❌ No se encontraron coincidencias para '{texto_buscar}'")
                return
            await safe_call(progress_msg.delete)
            for url in resultados:
                await safe_call(message.reply_text, url)
                await asyncio.sleep(0.2)
        except Exception as e:
            await safe_call(message.reply_text, f"❌ Error en scrap: {str(e)}")
    
    async def dl(self, message, link):
        try:
            progress_msg = await safe_call(message.reply_text, "📥 Procesando enlace...")
            cache_id = str(uuid.uuid4())[:8]
            self.user_downloads[cache_id] = link
            buttons = [
                [
                    InlineKeyboardButton("🖼️ Imagen", callback_data=f"dl_image_{cache_id}"),
                    InlineKeyboardButton("🎬 Video", callback_data=f"dl_video_{cache_id}")
                ],
                [
                    InlineKeyboardButton("🎵 Audio", callback_data=f"dl_audio_{cache_id}"),
                    InlineKeyboardButton("📄 Documento", callback_data=f"dl_document_{cache_id}")
                ]
            ]
            await safe_call(progress_msg.edit_text, 
                f"📌 Enlace guardado\n\nElige el formato de envío:",
                reply_markup=InlineKeyboardMarkup(buttons))
        except Exception as e:
            await safe_call(message.reply_text, f"❌ Error: {str(e)}")
    
    async def _send_as_format(self, chat_id, link, format_type):
        temp_path = None
        try:
            temp_file = tempfile.NamedTemporaryFile(delete=False)
            temp_path = temp_file.name
            temp_file.close()
            success = await self.async_download(link, temp_path)
            if not success or os.path.getsize(temp_path) == 0:
                await safe_call(self.app.send_message, chat_id, "❌ Error al descargar el contenido")
                if temp_path and os.path.exists(temp_path):
                    os.remove(temp_path)
                return
            if format_type == "image":
                try:
                    img = Image.open(temp_path)
                    img.verify()
                    await safe_call(self.app.send_photo, chat_id, temp_path)
                except:
                    await safe_call(self.app.send_message, chat_id, "❌ El archivo no es una imagen válida")
            elif format_type == "video":
                try:
                    await safe_call(self.app.send_video, chat_id, temp_path)
                except:
                    await safe_call(self.app.send_message, chat_id, "❌ El archivo no es un video válido")
            elif format_type == "audio":
                try:
                    await safe_call(self.app.send_audio, chat_id, temp_path)
                except:
                    await safe_call(self.app.send_message, chat_id, "❌ El archivo no es un audio válido")
            elif format_type == "document":
                await self._send_document_with_progress(chat_id, temp_path, f"📄 Archivo")
        except Exception as e:
            await safe_call(self.app.send_message, chat_id, f"❌ Error al enviar: {str(e)}")
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass
    
    async def async_download(self, url, save_path):
        try:
            async with aiohttp.ClientSession() as session:
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
            BotCommand("nhq", "Configurar calidad de descarga nhentai (HD/SD)"),
            BotCommand("3h", "Descarga un doujin de 3hentai"),
            BotCommand("snh", "Busca doujins por filtros en nhentai"),
            BotCommand("s3h", "Busca doujins por filtros en 3hentai"),
            BotCommand("hito", "Descarga doujin de hitomi (usa -s y -f para rango)"),
            BotCommand("up", "Subir archivo al vault"),
            BotCommand("setfile", "Configurar formato de salida (cbz/pdf/raw)"),
            BotCommand("mangasearch", "Buscar manga por término"),
            BotCommand("mangafile", "Configurar formato de manga (cbz/pdf/zip)"),
            BotCommand("mangadlset", "Configurar descarga por volumen o capítulo"),
            BotCommand("mangadlquality", "Configurar calidad de descarga (hd/sd)"),
            BotCommand("mangadllang", "Configurar idioma de manga (en/es)"),
            BotCommand("mangadl", "Descargar manga por ID o enlace"),
            BotCommand("auto", "Configurar acciones automáticas"),
            BotCommand("nextnames", "Configurar nombres para próximos archivos"),
            BotCommand("nyaa", "Buscar en Nyaa"),
            BotCommand("nyaa18", "Buscar en Sukebei (Nyaa 18+)"),
            BotCommand("leech", "Descargar torrent/magnet"),
            BotCommand("mega", "Descargar archivo de MEGA"),
            BotCommand("reset", "Reiniciar servicio Render (ServiceID BearerToken)"),
            BotCommand("scrap", "Scrapea una pagina y busca coincidencias"),
            BotCommand("dl", "Descarga un enlace y elige formato: Imagen/Video/Audio/Documento"),
            BotCommand("premium", "Activar/desactivar modo premium (solo admins)")
        ])
        print("Comandos configurados en el bot")

    async def _handle_message(self, client: Client, message: Message):
        if not message.text:
            await self._handle_auto_actions(message)
            return
        text = message.text.strip()
        user_id = message.from_user.id
        username = message.from_user.username

        if text.startswith("/premium"):
            if not self.is_admin(user_id, username):
                await safe_call(message.reply_text, "❌ No tienes permiso para usar este comando")
                return
            
            global premium_enabled
            parts = text.split()
            
            if len(parts) == 1:
                estado = "activado" if premium_enabled else "desactivado"
                await safe_call(message.reply_text, f"⚙️ Modo premium: **{estado}**\nLímite de compresión: {'4000 MB' if premium_enabled else '1995 MB'}\n\nUsa `/premium on` para activar\nUsa `/premium off` para desactivar")
                return
            
            if len(parts) >= 2:
                if parts[1].lower() == "on":
                    premium_enabled = True
                    await safe_call(message.reply_text, "✅ Modo premium **activado**\nAhora los archivos > 4000 MB se comprimirán automáticamente")
                elif parts[1].lower() == "off":
                    premium_enabled = False
                    await safe_call(message.reply_text, "❌ Modo premium **desactivado**\nAhora los archivos > 1995 MB se comprimirán automáticamente")
                else:
                    await safe_call(message.reply_text, "❌ Usa: `/premium on` o `/premium off`")
            return

        if text.startswith("/nhq"):
            await self._show_nh_quality_menu(message, user_id)
            return

        if text.startswith("/listfiles"):
            await self.files_cmd.listfiles(message)
            return

        elif text.startswith("/start"):
            await safe_call(client.send_photo, chat_id=message.chat.id, photo="https://cdn.imgchest.com/files/93cb097b575e.webp", protect_content=True, caption="Nyaa, Hello, I'm Alice. The cute pet of @nakigeplayer")
            return

        elif text.startswith("/cookies"):
            await self.files_cmd.cookies(message)
            return
            
        elif text.startswith("/ytv "):
            await self.files_cmd.ytv(message, user_id)
            return

        elif text.startswith("/yta "):
            await self.files_cmd.yta(message, user_id)
            return

        elif text.startswith("/code"):
            await safe_call(message.reply_text, disable_web_page_preview=True, text="Code of bot: https://github.com/naki-2005/nekobot/")
            return

        elif text.startswith("/scrap "):
            parts = text.split(maxsplit=2)
            if len(parts) < 3:
                await safe_call(message.reply_text, "Usa: `/scrap link texto_a_buscar`")
                return
            link = parts[1].strip()
            texto_buscar = parts[2].strip()
            await self.scrap(message, link, texto_buscar)
            return

        elif text.startswith("/mp3"):
            await self.files_cmd.mp3(message)
            return
            
        elif text.startswith("/dl "):
            parts = text.split(maxsplit=1)
            if len(parts) < 2:
                await safe_call(message.reply_text, "Usa: `/dl link`")
                return
            link = parts[1].strip()
            await self.dl(message, link)
            return

        elif text.startswith("/sendfile "):
            await self.files_cmd.sendfile(message, user_id)
            return

        elif text.startswith("/reset "):
            parts = text.split(maxsplit=2)
            if len(parts) < 3:
                await safe_call(message.reply_text, "Usa: `/reset ServiceID BearerToken`")
                return
            service_id = parts[1].strip()
            bearer_token = parts[2].strip()
            await self._process_reset_render(message, service_id, bearer_token)
            return
        
        elif text.startswith("/setfile "):
            parts = text.split(maxsplit=1)
            if len(parts) < 2:
                current = user_settings.get(user_id, "cbz")
                await safe_call(message.reply_text, f"Formato actual: **{current.upper()}**\nUsa: `/setfile cbz` o `/setfile pdf` o `/setfile raw`")
                return
            format_option = parts[1].lower()
            if format_option not in ["cbz", "pdf", "raw"]:
                await safe_call(message.reply_text, "❌ Formato inválido. Usa: cbz, pdf o raw")
                return
            user_settings[user_id] = format_option
            await safe_call(message.reply_text, f"✅ Formato configurado a: **{format_option.upper()}**")
            return
        
        elif text.startswith("/mangafile"):
            await self.manga_cmd.mangafile(message, user_id)
            return

        elif text.startswith("/mangadllang"):
            await self.manga_cmd.mangadllang(message, user_id)
            return
        
        elif text.startswith("/mangadlset"):
            await self.manga_cmd.mangadlset(message, user_id)
            return
        
        elif text.startswith("/mangadlquality"):
            await self.manga_cmd.mangadlquality(message, user_id)
            return
        
        elif text.startswith("/mangasearch "):
            await self.manga_cmd.mangasearch(message)
            return
        
        elif text.startswith("/mangadl "):
            await self.manga_cmd.mangadl(message, user_id, user_manga_settings)
            return

        elif text.startswith("/mega "):
            await self.tdl_cmd.mega(message)
            return
        
        elif text.startswith("/nh ") or text.startswith("/3h "):
            await self.adult_manga_cmd.nh_or_3h(message, user_id, user_settings, user_nh_quality)
        
        elif text.startswith("/snh ") or text.startswith("/s3h "):
            await self.adult_manga_cmd.snh_or_s3h(message)

        elif text.startswith("/hito"):
            await self.adult_manga_cmd.hito(message, user_id, user_settings)
        
        elif text.startswith("/up"):
            await self.files_cmd.up(message, user_id, user_nextnames)
        
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
            await self.tdl_cmd.leech(message)
            return
        
        elif text.startswith("/auto"):
            await self._show_auto_menu(message, user_id)
            return
        
        elif text.startswith("/nextnames "):
            parts = text.split(maxsplit=1)
            if len(parts) < 2:
                if user_id in user_nextnames:
                    info = user_nextnames[user_id]
                    await safe_call(message.reply_text, f"📝 Patrón actual: `{info['pattern']}`\nRango: {info['start']}-{info['end']}\nPróximo número: {info['current']}")
                else:
                    await safe_call(message.reply_text, "Usa: `/nextnames 1-10 Example {no}.ext`")
                return
            pattern_str = parts[1]
            match = re.match(r'(\d+)-(\d+)\s+(.+)', pattern_str)
            if not match:
                await safe_call(message.reply_text, "Formato inválido. Usa: `/nextnames 1-10 Example {no}.ext`")
                return
            start_num = int(match.group(1))
            end_num = int(match.group(2))
            pattern = match.group(3)
            if "{no}" not in pattern:
                await safe_call(message.reply_text, "El patrón debe contener `{no}`")
                return
            if start_num > end_num:
                await safe_call(message.reply_text, "El número inicial debe ser menor o igual al final")
                return
            user_nextnames[user_id] = {
                "pattern": pattern,
                "start": start_num,
                "end": end_num,
                "current": start_num
            }
            first_example = pattern.replace("{no}", str(start_num).zfill(len(str(start_num)) if str(start_num).startswith("0") else 1))
            await safe_call(message.reply_text, f"✅ Patrón configurado\nRango: {start_num}-{end_num}\nPrimer archivo: `{first_example}`")
            return
        
        else:
            await self._handle_auto_actions(message)
    
    def _extract_manga_id_from_input(self, input_text):
        patterns = [
            r"https://mangadex\.org/title/([a-f0-9-]{36})",
            r"https://mangadex\.org/title/([a-f0-9-]{36})/",
            r"([a-f0-9-]{36})"
        ]
        for pattern in patterns:
            match = re.search(pattern, input_text)
            if match:
                return match.group(1)
        return None
    
    async def _handle_auto_actions(self, message):
        user_id = message.from_user.id
        if user_id not in user_auto_settings:
            return
        settings = user_auto_settings[user_id]
        if message.media and settings.get("file_to_link", False):
            await self._auto_upload_file(message)
            return
        if message.text:
            text = message.text.strip()
            if settings.get("doujins", False):
                doujin_match = self._extract_doujin_info(text)
                if doujin_match:
                    code, source = doujin_match
                    await self._auto_download_doujin(message, code, source)
                    return
            if settings.get("mangas", False):
                manga_id = self._extract_manga_id_from_input(text)
                if manga_id:
                    await self._auto_download_manga(message, manga_id)
                    return
            if settings.get("torrents", False):
                if text.startswith("magnet:?") or text.endswith(".torrent"):
                    await self._auto_download_torrent(message, text)
                    return
    
    async def _auto_upload_file(self, message):
        vault_dir = os.path.join(os.getcwd(), "vault")
        if message.document:
            fname = message.document.file_name or "file.bin"
        elif message.photo:
            fname = "photo.jpg"
        elif message.video:
            fname = message.video.file_name or "video.mp4"
        elif message.audio:
            fname = message.audio.file_name or "audio.mp3"
        elif message.voice:
            fname = "voice.ogg"
        elif message.sticker:
            fname = "sticker.webp"
        else:
            return
        target_path = os.path.join(vault_dir, fname)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        progress_msg = await safe_call(message.reply_text, "📥 Subiendo automáticamente...")
        await self.app.download_media(message, file_name=target_path)
        await safe_call(progress_msg.edit_text, f"✅ Archivo subido automáticamente: `{fname}`")
    
    def _extract_doujin_info(self, text):
        patterns = [
            (r"https://nhentai\.net/g/(\d+)", "nh"),
            (r"https://es\.3hentai\.net/d/(\d+)", "3h"),
            (r"https://hitomi\.la/reader/(\d+)\.html", "hito"),
            (r"https://hitomi\.la/galleries/(\d+)\.html", "hito")
        ]
        for pattern, source in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1), source
        return None
    
    async def _auto_download_doujin(self, message, code, source):
        if source == "nh":
            command = f"/nh {code}"
        elif source == "3h":
            command = f"/3h {code}"
        elif source == "hito":
            command = f"/hito {code}"
        else:
            return
        msg = message
        msg.text = command
        await self._handle_message(self.app, msg)
    
    async def _auto_download_manga(self, message, manga_id):
        msg = message
        msg.text = f"/mangadl {manga_id}"
        await self._handle_message(self.app, msg)
    
    async def _auto_download_torrent(self, message, text):
        msg = message
        msg.text = f"/leech {text}"
        await self._handle_message(self.app, msg)
    
    async def _show_auto_menu(self, message, user_id):
        if user_id not in user_auto_settings:
            user_auto_settings[user_id] = {
                "file_to_link": False,
                "doujins": False,
                "mangas": False,
                "torrents": False
            }
        settings = user_auto_settings[user_id]
        text = "🤖 **Configuración Automática**\n\n"
        text += "Activa/desactiva las acciones que se ejecutarán automáticamente:\n\n"
        file_to_link_icon = "✅" if settings["file_to_link"] else "❌"
        doujins_icon = "✅" if settings["doujins"] else "❌"
        mangas_icon = "✅" if settings["mangas"] else "❌"
        torrents_icon = "✅" if settings["torrents"] else "❌"
        text += f"{file_to_link_icon} **Archivos a Vault**: Subir automáticamente archivos recibidos\n"
        text += f"{doujins_icon} **Doujins**: Descargar automáticamente enlaces de doujins\n"
        text += f"{mangas_icon} **Mangas**: Descargar automáticamente enlaces de MangaDex\n"
        text += f"{torrents_icon} **Torrents**: Descargar automáticamente magnet/torrent\n"
        keyboard = [
            [
                InlineKeyboardButton("📁 Archivos", callback_data="auto_file_to_link"),
                InlineKeyboardButton("📖 Doujins", callback_data="auto_doujins")
            ],
            [
                InlineKeyboardButton("📚 Mangas", callback_data="auto_mangas"),
                InlineKeyboardButton("🧲 Torrents", callback_data="auto_torrents")
            ],
            [
                InlineKeyboardButton("ℹ️ Info", callback_data="auto_info")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await message.edit_text(text, reply_markup=reply_markup)
        except:
            await safe_call(message.reply_text, text, reply_markup=reply_markup)    
    
    async def _process_manga_download(self, message, manga_id, mode, format_choice, quality_choice, language, start_chapter, start_volume, end_chapter, end_volume, user_id):
        await self.manga_cmd.process_manga_download(message, manga_id, mode, format_choice, quality_choice, language, start_chapter, start_volume, end_chapter, end_volume, user_id)

    async def _download_manga_by_volumes(self, progress_msg, manga_id, feed_data, covers_dict, format_choice, start_chapter, start_volume, end_chapter, end_volume, user_id):
        await self.manga_cmd.download_manga_by_volumes(progress_msg, manga_id, feed_data, covers_dict, format_choice, start_chapter, start_volume, end_chapter, end_volume, user_id)
    
    async def _download_manga_by_chapters(self, progress_msg, manga_id, feed_data, covers_dict, format_choice, quality_choice, start_chapter, start_volume, end_chapter, end_volume, user_id):
        await self.manga_cmd.download_manga_by_chapters(progress_msg, manga_id, feed_data, covers_dict, format_choice, quality_choice, start_chapter, start_volume, end_chapter, end_volume, user_id)
    
    async def _create_cbz_from_images(self, nombre, image_paths, user_id):
        return await self.manga_cmd.create_cbz_from_images(nombre, image_paths, user_id)

    async def _create_pdf_from_images(self, nombre, image_paths, user_id):
        return await self.manga_cmd.create_pdf_from_images(nombre, image_paths, user_id)

    def _sort_key(self, val):
        return self.manga_cmd.sort_key(val)
    
    async def _download_hitomi_raw(self, message, g, pages, titulo, progress_msg, start_page, end_page, total_pages, user_id):
        await self.adult_manga_cmd.download_hitomi_raw(message, g, pages, titulo, progress_msg, start_page, end_page, total_pages, user_id)
    
    async def _download_hitomi_with_format(self, message, g, pages, titulo, progress_msg, start_page, end_page, total_pages, format_choice, user_id):
        await self.adult_manga_cmd.download_hitomi_with_format(message, g, pages, titulo, progress_msg, start_page, end_page, total_pages, format_choice, user_id)
    
    async def _send_photo_batch(self, message, photo_paths, batch_number, user_id):
        await self.adult_manga_cmd.send_photo_batch(message, photo_paths, batch_number, user_id)
    
    async def _prepare_image_for_telegram(self, url):
        return await self.adult_manga_cmd.prepare_image_for_telegram(url)

    async def _convert_to_thumbnail(self, image_path, size=(320, 320)):
        return await self.adult_manga_cmd.convert_to_thumbnail(image_path, size)

    async def _process_gallery_json_with_range(self, message, result, code, format_choice, start_page, end_page, user_id):
        await self.adult_manga_cmd.process_gallery_json_with_range(message, result, code, format_choice, start_page, end_page, user_id)
    
    async def _process_gallery_with_format(self, message, result, code, format_choice, start_page, end_page, user_id):
        await self.adult_manga_cmd.process_gallery_with_format(message, result, code, format_choice, start_page, end_page, user_id)
    
    async def _send_photos_in_batches(self, message, image_urls, start_index, vault_dir, batch_size=10, user_id=None):
        await self.adult_manga_cmd.send_photos_in_batches(message, image_urls, start_index, vault_dir, batch_size, user_id)
    
    async def _process_search_json(self, message, result, user_id):
        await self.adult_manga_cmd.process_search_json(message, result, user_id)
    
    def _format_tags(self, tags):
        return self.adult_manga_cmd.format_tags(tags)
    
    async def _send_nyaa_message(self, message, results, position, query_hash):
        result = results[position]
        total = len(results)
        text = f"**Resultado {position+1}/{total}**\n"
        text += f"**Nombre:** `{result['name']}`\n"
        text += f"**Tamaño:** {result['size']}\n"
        text += f"**Fecha:** {result['date']}\n"
        keyboard = [
            [
                InlineKeyboardButton("⏪", callback_data=f"nyaa_first_{query_hash}"),
                InlineKeyboardButton("◀️", callback_data=f"nyaa_prev_{query_hash}"),
                InlineKeyboardButton(f"{position+1}/{total}", callback_data="nyaa_page"),
                InlineKeyboardButton("▶️", callback_data=f"nyaa_next_{query_hash}"),
                InlineKeyboardButton("⏩", callback_data=f"nyaa_last_{query_hash}")
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
                InlineKeyboardButton("⏪", callback_data=f"nyaa_first_{query_hash}"),
                InlineKeyboardButton("◀️", callback_data=f"nyaa_prev_{query_hash}"),
                InlineKeyboardButton(f"{position+1}/{total}", callback_data="nyaa_page"),
                InlineKeyboardButton("▶️", callback_data=f"nyaa_next_{query_hash}"),
                InlineKeyboardButton("⏩", callback_data=f"nyaa_last_{query_hash}")
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
    
    async def _process_reset_render(self, message, service_id, bearer_token):
        try:
            status_msg = await safe_call(message.reply_text, "🔄 Reiniciando servicio Render...")
            success = self.neko.reset_render_service(service_id, bearer_token)
            if success:
                await safe_call(status_msg.edit_text, "✅ Servicio Render reiniciado exitosamente")
            else:
                await safe_call(status_msg.edit_text, "❌ Error al reiniciar el servicio Render")
        except Exception as e:
            await safe_call(message.reply_text, f"❌ Error: {str(e)}")
    
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
    parser.add_argument("-admin", "--admin", action="append", help="Administradores (ID o username)")
    args = parser.parse_args()
    api_id = args.api or os.environ.get("API_ID")
    api_hash = args.hash or os.environ.get("API_HASH")
    bot_token = args.token or os.environ.get("BOT_TOKEN")
    admin_list = args.admin if args.admin else []
    if not all([api_id, api_hash, bot_token]):
        print("Error: Faltan credenciales. Usa -A -H -T o variables de entorno.")
        sys.exit(1)
    dlselenium.dl_files()
    bot = NekoTelegram(api_id, api_hash, bot_token, admin_list)
    if args.flask:
        bot.start_flask()
    print("[INFO] Iniciando bot de Telegram...")
    bot.run()

if __name__ == "__main__":
    main()
