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
from nekoapis.mangadex import MangaDex
from server import run_flask
import hashlib
from io import BytesIO
from PIL import Image
import json
import dlselenium
import dlyt
import uuid

set_cmd = False
user_settings = {}
user_manga_settings = {}
user_auto_settings = {}
user_nextnames = {}

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
        self.mangadex = MangaDex()
        self.app = Client("nekobot", api_id=int(api_id), api_hash=api_hash, bot_token=bot_token)
        self.flask_thread = None
        self.me_id = None
        self.download_pool = ThreadPoolExecutor(max_workers=20)
        self.nyaa_cache = {}
        self.current_positions = {}
        self.user_downloads = {}

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
                await self._start_torrent_download(callback_query.message, result, user_id)
                await callback_query.answer("✅ Descarga iniciada")
                return
            else:
                return

            self.current_positions[cache_key] = new_pos
            await self._update_nyaa_message(callback_query.message, results, new_pos, query_hash)
            await callback_query.answer()

    async def _send_document_with_progress(self, chat_id, document_path, caption="", thumb=None):
        print(f"[DEBUG] Intentando enviar: {document_path}, tamaño: {os.path.getsize(document_path) if os.path.exists(document_path) else 'NO EXISTE'}")

        if not os.path.exists(document_path):
            print(f"[ERROR] Archivo no existe: {document_path}")
            await safe_call(self.app.send_message, chat_id, f"❌ Error: Archivo no encontrado: {os.path.basename(document_path)}")
            return

        file_size_mb = os.path.getsize(document_path) / (1024 * 1024)

        if file_size_mb > 2000:
            parts = self.neko.compress_to_7z(document_path, 2000)
            if parts:
                for part in parts:
                    await self._send_document_with_progress(chat_id, part, f"{caption} (Parte {os.path.basename(part).split('.')[-1]})")
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
            BotCommand("3h", "Descarga un doujin de 3hentai"),
            BotCommand("snh", "Busca doujins por filtros en nhentai"),
            BotCommand("s3h", "Busca doujins por filtros en 3hentai"),
            BotCommand("hito", "Descarga doujin de hitomi (usa -s y -f para rango)"),
            BotCommand("up", "Subir archivo al vault"),
            BotCommand("setfile", "Configurar formato de salida (cbz/pdf/raw)"),
            BotCommand("mangasearch", "Buscar manga por término"),
            BotCommand("mangafile", "Configurar formato de manga (cbz/pdf)"),
            BotCommand("mangadlset", "Configurar descarga por volumen o capítulo"),
            BotCommand("mangadlquality", "Configurar calidad de descarga (hd/sd)"),
            BotCommand("mangadl", "Descargar manga por ID o enlace"),
            BotCommand("auto", "Configurar acciones automáticas"),
            BotCommand("nextnames", "Configurar nombres para próximos archivos"),
            BotCommand("nyaa", "Buscar en Nyaa"),
            BotCommand("nyaa18", "Buscar en Sukebei (Nyaa 18+)"),
            BotCommand("leech", "Descargar torrent/magnet"),
            BotCommand("mega", "Descargar archivo de MEGA"),
            BotCommand("reset", "Reiniciar servicio Render (ServiceID BearerToken)"),
            BotCommand("scrap", "Scrapea una pagina y busca coincidencias"),
            BotCommand("dl", "Descarga un enlace y elige formato: Imagen/Video/Audio/Documento")
        ])
        print("Comandos configurados en el bot")

    async def _handle_message(self, client: Client, message: Message):
        if not message.text:
            await self._handle_auto_actions(message)
            return

        text = message.text.strip()
        user_id = message.from_user.id

        if text.startswith("/listfiles"):
            vault_dir = os.path.join(os.getcwd(), "vault")
            if not os.path.exists(vault_dir):
                await safe_call(message.reply_text, "❌ La carpeta vault no existe")
                return

            items = self.neko.sort_directory(vault_dir)

            if not items:
                await safe_call(message.reply_text, "❌ La carpeta vault está vacía")
                return

            files_list = []
            for idx, item in enumerate(items, 1):
                item_path = os.path.join(vault_dir, item)
                if os.path.isfile(item_path):
                    size = os.path.getsize(item_path)
                    size_mb = size / (1024 * 1024)
                    files_list.append(f"{idx}. {item} ({size_mb:.2f} MB)")
                else:
                    files_list.append(f"{idx}. 📁 {item}/")

            message_text = "📁 **Archivos en vault:**\n\n" + "\n".join(files_list[:50])

            if len(files_list) > 50:
                message_text += f"\n\n... y {len(files_list) - 50} archivos más"

            await safe_call(message.reply_text, message_text)
            return

        elif text.startswith("/start"):
            await safe_call(client.send_photo, chat_id=message.chat.id, photo="https://cdn.imgchest.com/files/93cb097b575e.webp", protect_content=True, caption="Nyaa, Hello, I'm Alice. The cute pet of @nakigeplayer")
            return

        elif text.startswith("/cookies"):
            if not message.reply_to_message or not message.reply_to_message.document:
                await safe_call(message.reply_text, "❌ Responde a un archivo con /cookies")
                return

            progress_msg = await safe_call(message.reply_text, "📥 Descargando archivo cookies...")

            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
            temp_path = temp_file.name
            temp_file.close()

            await message.reply_to_message.download(file_name=temp_path)

            SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
            DATA_DIR = os.path.join(SCRIPT_DIR, "data")
            os.makedirs(DATA_DIR, exist_ok=True)
            cookies_path = os.path.join(DATA_DIR, "cookies.txt")
            shutil.move(temp_path, cookies_path)

            await safe_call(progress_msg.edit_text, "✅ Archivo cookies.txt guardado correctamente en /data/")
            return
        elif text.startswith("/ytv "):
            parts = text.split(maxsplit=1)
            if len(parts) < 2:
                await safe_call(message.reply_text, "❌ Usa: /ytv URL")
                return

            url = parts[1].strip()
            progress_msg = await safe_call(message.reply_text, "📥 Descargando video...")

            try:
                archivo = dlyt.yt_video(url)
                if archivo is False:
                    await safe_call(progress_msg.edit_text, "❌ Error: cookies.txt no encontrado")
                    return

                await safe_call(progress_msg.delete)

                if os.path.exists(archivo):
                    await self._send_document_with_progress(message.chat.id, archivo, f"🎬 {os.path.basename(archivo)}")
                else:
                    await safe_call(message.reply_text, f"✅ Video descargado: {archivo}")
            except Exception as e:
                await safe_call(progress_msg.edit_text, f"❌ Error: {str(e)}")
            return

        elif text.startswith("/yta "):
            parts = text.split(maxsplit=1)
            if len(parts) < 2:
                await safe_call(message.reply_text, "❌ Usa: /yta URL")
                return

            url = parts[1].strip()
            progress_msg = await safe_call(message.reply_text, "📥 Descargando audio...")

            try:
                archivo = dlyt.yt_audio(url)
                if archivo is False:
                    await safe_call(progress_msg.edit_text, "❌ Error: cookies.txt no encontrado")
                    return

                await safe_call(progress_msg.delete)

                if os.path.exists(archivo):
                    await self._send_document_with_progress(message.chat.id, archivo, f"🎵 {os.path.basename(archivo)}")
                else:
                    await safe_call(message.reply_text, f"✅ Audio descargado: {archivo}")
            except Exception as e:
                await safe_call(progress_msg.edit_text, f"❌ Error: {str(e)}")
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

        elif text.startswith("/dl "):
            parts = text.split(maxsplit=1)
            if len(parts) < 2:
                await safe_call(message.reply_text, "Usa: `/dl link`")
                return

            link = parts[1].strip()
            await self.dl(message, link)
            return

        elif text.startswith("/sendfile "):
            parts = text.split()
            if len(parts) != 2:
                await safe_call(message.reply_text, "Usa: `/sendfile número`")
                return

            try:
                file_num = int(parts[1])
            except ValueError:
                await safe_call(message.reply_text, "❌ El número debe ser un entero válido")
                return

            vault_dir = os.path.join(os.getcwd(), "vault")
            if not os.path.exists(vault_dir):
                await safe_call(message.reply_text, "❌ La carpeta vault no existe")
                return

            items = self.neko.sort_directory(vault_dir)

            if file_num < 1 or file_num > len(items):
                await safe_call(message.reply_text, f"❌ Número fuera de rango (1-{len(items)})")
                return

            selected_item = items[file_num - 1]
            item_path = os.path.join(vault_dir, selected_item)

            if os.path.isfile(item_path):
                await self._send_document_with_progress(
                    message.chat.id,
                    item_path,
                    caption=f"📄 {selected_item}"
                )
            elif os.path.isdir(item_path):
                await safe_call(message.reply_text, f"📁 {selected_item} es una carpeta. Usa /listfiles para ver su contenido.")
            else:
                await safe_call(message.reply_text, "❌ Archivo no encontrado")
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
            parts = text.split(maxsplit=1)
            if len(parts) < 2:
                current = user_manga_settings.get(user_id, {}).get("format", "cbz")
                await safe_call(message.reply_text, f"📚 Formato actual de manga: **{current.upper()}**\nUsa: `/mangafile cbz` o `/mangafile pdf`")
                return

            format_option = parts[1].lower()
            if format_option not in ["cbz", "pdf"]:
                await safe_call(message.reply_text, "❌ Formato inválido. Usa: cbz o pdf")
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

        elif text.startswith("/mangadlquality"):
            parts = text.split()
            if len(parts) == 1:
                current = user_manga_settings.get(user_id, {}).get("quality", "hd")
                await safe_call(message.reply_text, f"📊 Calidad actual de manga: **{current.upper()}**\nUsa: `/mangadlquality hd` o `/mangadlquality sd`")
                return

            if len(parts) != 2:
                await safe_call(message.reply_text, "Usa: `/mangadlquality hd` o `/mangadlquality sd`")
                return

            quality_option = parts[1].lower()
            if quality_option not in ["hd", "sd"]:
                await safe_call(message.reply_text, "Calidad inválida. Usa: hd o sd")
                return

            if user_id not in user_manga_settings:
                user_manga_settings[user_id] = {}

            user_manga_settings[user_id]["quality"] = quality_option
            await safe_call(message.reply_text, f"✅ Calidad de manga configurado a: **{quality_option.upper()}**")
            return

        elif text.startswith("/mangasearch "):
            parts = text.split(maxsplit=1)
            if len(parts) < 2:
                await safe_call(message.reply_text, "Usa: `/mangasearch término`")
                return

            search_term = parts[1]
            await safe_call(message.reply_text, f"🔍 Buscando manga: **{search_term}**...")

            try:
                search_json = self.mangadex.search(search_term)
                if not search_json:
                    await safe_call(message.reply_text, "❌ No se encontraron resultados")
                    return

                results = json.loads(search_json)
                top_results = results[:5]

                for manga in top_results:
                    manga_id = manga.get("id", "")
                    title = manga.get("title", "Sin título")
                    description = manga.get("description", "Sin descripción")

                    covers_json = self.mangadex.covers([manga_id])
                    covers = json.loads(covers_json) if covers_json else []

                    cover_url = None
                    if covers:
                        cover_url = covers[0].get("cover", "") if isinstance(covers[0], dict) else ""

                    caption = f"**{title}**\n\n{description[:300]}...\n\nID: `{manga_id}`"

                    if cover_url and cover_url != "No disponible":
                        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
                        temp_path = temp_file.name
                        temp_file.close()

                        if await self.async_download(cover_url, temp_path):
                            await safe_call(message.reply_photo, temp_path, caption=caption)
                            os.remove(temp_path)
                        else:
                            await safe_call(message.reply_text, caption)
                    else:
                        await safe_call(message.reply_text, caption)

            except Exception as e:
                print(f"Error buscando manga: {e}")
                await safe_call(message.reply_text, "❌ Error en la búsqueda")
            return

        elif text.startswith("/mangadl "):
            parts = text.split()
            if len(parts) < 2:
                await safe_call(message.reply_text, "Usa: `/mangadl MangaID` o `/mangadl MangaID -sc # -sv # -fc # -fv #`")
                return

            input_text = parts[1]

            manga_id = self._extract_manga_id_from_input(input_text)
            if not manga_id:
                await safe_call(message.reply_text, "❌ No se pudo extraer el ID del manga del enlace proporcionado")
                return

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
            user_quality = user_manga_settings.get(user_id, {}).get("quality", "hd")

            await self._process_manga_download(
                message, manga_id, user_mode, user_format, user_quality,
                start_chapter, start_volume, end_chapter, end_volume, user_id
            )
            return

        elif text.startswith("/mega "):
            parts = text.split(maxsplit=1)
            if len(parts) < 2:
                await safe_call(message.reply_text, "Usa: `/mega mega_link`")
                return

            mega_link = parts[1].strip()
            await self._process_mega_download(message, mega_link)
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

            if format_choice == "raw":
                await self._process_gallery_json_with_range(message, result, code, format_choice, start_page, end_page, user_id)
            else:
                await self._process_gallery_with_format(message, result, code, format_choice, start_page, end_page, user_id)

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

            format_choice = user_settings.get(user_id, "raw")

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
                await self._download_hitomi_with_format(message, g, pages_to_download, titulo, progress_msg, start_page, end_page, total_pages, format_choice, user_id)

        elif text.startswith("/up"):
            parts = text.split(maxsplit=1)
            custom_path = parts[1].strip() if len(parts) > 1 else None
            rm = message.reply_to_message
            if not rm or not (rm.document or rm.photo or rm.video or rm.audio or rm.voice or rm.sticker):
                await safe_call(message.reply_text, "Responde a un archivo con /up")
                return

            vault_dir = os.path.join(os.getcwd(), "vault")

            if user_id in user_nextnames:
                pattern_info = user_nextnames[user_id]
                pattern = pattern_info["pattern"]
                current = pattern_info["current"]
                start = pattern_info["start"]
                end = pattern_info["end"]

                if current > end:
                    await safe_call(message.reply_text, f"✅ Secuencia completada ({start}-{end})")
                    del user_nextnames[user_id]
                    return

                filename = pattern.replace("{no}", str(current).zfill(len(str(start)) if str(start).startswith("0") else 1))

                user_nextnames[user_id]["current"] = current + 1

                target_path = os.path.join(vault_dir, filename)
            else:
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

            if user_id in user_nextnames:
                next_num = user_nextnames[user_id]["current"]
                end_num = user_nextnames[user_id]["end"]
                if next_num <= end_num:
                    await safe_call(progress_msg.edit_text, f"✅ Archivo guardado como `{os.path.basename(target_path)}`\nPróximo: {next_num}/{end_num}")
                else:
                    await safe_call(progress_msg.edit_text, f"✅ Archivo guardado como `{os.path.basename(target_path)}`\n✅ Secuencia completada")
                    del user_nextnames[user_id]
            else:
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

    async def _process_manga_download(self, message, manga_id, mode, format_choice, quality_choice, start_chapter, start_volume, end_chapter, end_volume, user_id):
        try:
            progress_msg = await safe_call(message.reply_text, f"📚 Obteniendo información para manga {manga_id}...")

            try:
                feed_json = self.mangadex.feed(manga_id)
                if not feed_json:
                    await safe_call(progress_msg.edit_text, "❌ No se pudo obtener información del manga (feed)")
                    return

                feed_data = json.loads(feed_json)

                covers_json = self.mangadex.covers([manga_id])
                covers_data = json.loads(covers_json) if covers_json else []

                covers_dict = {}
                for cover in covers_data:
                    if isinstance(cover, dict) and 'volume' in cover and 'cover' in cover:
                        covers_dict[str(cover['volume'])] = cover['cover']

                if mode == "vol":
                    await self._download_manga_by_volumes(progress_msg, manga_id, feed_data, covers_dict, format_choice, start_chapter, start_volume, end_chapter, end_volume, user_id
                    )
                else:
                    await self._download_manga_by_chapters(
                        progress_msg, manga_id, feed_data, covers_dict,
                        format_choice, quality_choice,
                        start_chapter, start_volume, end_chapter, end_volume, user_id
                    )

            except Exception as e:
                print(f"Error obteniendo datos: {e}")
                await safe_call(progress_msg.edit_text, f"❌ Error al obtener datos: {e}")

        except Exception as e:
            print(f"Error en _process_manga_download: {e}")
            await safe_call(message.reply_text, f"❌ Error al procesar la descarga: {e}")

    async def _download_manga_by_volumes(self, progress_msg, manga_id, feed_data, covers_dict, format_choice, start_chapter, start_volume, end_chapter, end_volume, user_id):
        try:
            total_volumes = len(feed_data)

            vault_dir = os.path.join(os.getcwd(), "vault", "manga", manga_id)
            os.makedirs(vault_dir, exist_ok=True)

            for volume_index, volume_data in enumerate(feed_data, 1):
                volume = volume_data.get('volume')
                chapters = volume_data.get('chapters', [])

                if not chapters:
                    continue

                if start_volume and volume is not None:
                    try:
                        vol_float = float(str(volume))
                        start_vol_float = float(str(start_volume))
                        if vol_float < start_vol_float:
                            continue
                    except:
                        continue

                if end_volume and volume is not None:
                    try:
                        vol_float = float(str(volume))
                        end_vol_float = float(str(end_volume))
                        if vol_float > end_vol_float:
                            break
                    except:
                        continue

                chapters.sort(key=lambda x: self._sort_key(x.get('chapter', '0')))

                all_volume_images = []
                chapter_range = []
                total_images_downloaded = 0
                total_images_expected = 0

                for chapter in chapters:
                    chapter_num = chapter.get('chapter')

                    if start_chapter:
                        try:
                            chap_float = self._sort_key(str(chapter_num))
                            start_chap_float = self._sort_key(str(start_chapter))
                            if chap_float < start_chap_float:
                                continue
                        except:
                            continue

                    if end_chapter:
                        try:
                            chap_float = self._sort_key(str(chapter_num))
                            end_chap_float = self._sort_key(str(end_chapter))
                            if chap_float > end_chap_float:
                                break
                        except:
                            continue

                    chapter_range.append(float(chapter_num) if chapter_num and chapter_num.replace('.', '', 1).isdigit() else chapter_num)

                    chapter_id = chapter.get('chapter_id')
                    if chapter_id:
                        try:
                            dl_json = self.mangadex.dl(chapter_id)
                            if dl_json:
                                dl_data = json.loads(dl_json)
                                if 'error' not in dl_data:
                                    image_urls = dl_data.get('hd', [])
                                    total_images_expected += len(image_urls)
                        except:
                            continue

                if total_images_expected == 0:
                    continue

                thumbnail_path = None
                if volume is not None:
                    volume_str = str(volume)
                    if volume_str in covers_dict:
                        cover_url = covers_dict[volume_str]
                    elif "1" in covers_dict:
                        cover_url = covers_dict["1"]
                    else:
                        cover_url = None
                else:
                    if "1" in covers_dict:
                        cover_url = covers_dict["1"]
                    else:
                        cover_url = None

                if cover_url:
                    try:
                        thumbnail_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
                        thumbnail_path = thumbnail_file.name
                        thumbnail_file.close()

                        if await self.async_download(cover_url, thumbnail_path):
                            img = Image.open(thumbnail_path)
                            img.thumbnail((320, 320))
                            img.save(thumbnail_path, "JPEG")
                        else:
                            thumbnail_path = None
                    except Exception as e:
                        print(f"Error descargando miniatura: {e}")
                        thumbnail_path = None

                volume_name = f"Volumen {volume}" if volume is not None else "Sin volumen"
                await safe_call(progress_msg.edit_text, f"📦 Procesando {volume_name} ({volume_index}/{total_volumes})... (0/{total_images_expected} Imágenes descargadas)")

                for chapter in chapters:
                    chapter_num = chapter.get('chapter')

                    if start_chapter:
                        try:
                            chap_float = self._sort_key(str(chapter_num))
                            start_chap_float = self._sort_key(str(start_chapter))
                            if chap_float < start_chap_float:
                                continue
                        except:
                            continue

                    if end_chapter:
                        try:
                            chap_float = self._sort_key(str(chapter_num))
                            end_chap_float = self._sort_key(str(end_chapter))
                            if chap_float > end_chap_float:
                                break
                        except:
                            continue

                    chapter_id = chapter.get('chapter_id')
                    if not chapter_id:
                        continue

                    try:
                        dl_json = self.mangadex.dl(chapter_id)
                        if not dl_json:
                            continue

                        dl_data = json.loads(dl_json)
                        if 'error' in dl_data:
                            continue

                        image_urls = dl_data.get('hd', [])

                        if not image_urls:
                            continue

                        downloaded_images = await self.download_images_concurrently(image_urls, max_concurrent=10)

                        volume_dir = os.path.join(vault_dir, f"vol_{volume if volume is not None else 'sin_volumen'}")
                        os.makedirs(volume_dir, exist_ok=True)

                        for img_idx, img_path in enumerate(downloaded_images):
                            safe_chapter = str(chapter_num).replace('.', '_').replace('/', '_')
                            new_name = f"vol_{volume if volume is not None else '0'}_chap_{safe_chapter}_img_{img_idx+1:03d}.jpg"
                            new_path = os.path.join(volume_dir, new_name)
                            shutil.move(img_path, new_path)
                            all_volume_images.append(new_path)

                        total_images_downloaded += len(downloaded_images)

                        await safe_call(progress_msg.edit_text, f"📦 Procesando {volume_name} ({volume_index}/{total_volumes})... ({total_images_downloaded}/{total_images_expected} Imágenes descargadas)")

                    except Exception as e:
                        print(f"Error procesando capítulo {chapter_num}: {e}")
                        continue

                if not all_volume_images:
                    continue

                if chapter_range:
                    try:
                        min_chap = min(chapter_range)
                        max_chap = max(chapter_range)

                        if volume is None:
                            volume_name = f"Capítulos {min_chap}-{max_chap}"
                        else:
                            if len(chapter_range) > 1:
                                volume_name = f"Volumen {volume} ({min_chap}-{max_chap})"
                            else:
                                volume_name = f"Volumen {volume} ({min_chap})"
                    except:
                        volume_name = f"Volumen {volume}" if volume is not None else "Sin volumen"

                if format_choice == "cbz" and all_volume_images:
                    cbz_path = await self._create_cbz_from_images(volume_name, all_volume_images, user_id)
                    if cbz_path:
                        await self._send_document_with_progress(progress_msg.chat.id, cbz_path, f"📚 {volume_name}", thumb=thumbnail_path)

                elif format_choice == "pdf" and all_volume_images:
                    pdf_path = await self._create_pdf_from_images(volume_name, all_volume_images, user_id)
                    if pdf_path:
                        await self._send_document_with_progress(progress_msg.chat.id, pdf_path, f"📚 {volume_name}", thumb=thumbnail_path)

        except Exception as e:
            print(f"Error en _download_manga_by_volumes: {e}")
            await safe_call(progress_msg.edit_text, f"❌ Error descargando por volúmenes: {e}")

    async def _create_cbz_from_images(self, name, image_paths, user_id):
        try:
            safe_name = self.neko.clean_name(name)
            cbz_path = os.path.join(os.getcwd(), "vault", f"{safe_name}.cbz")
            os.makedirs(os.path.dirname(cbz_path), exist_ok=True)

            with zipfile.ZipFile(cbz_path, 'w', zipfile.ZIP_DEFLATED) as cbz:
                for i, img_path in enumerate(image_paths):
                    arcname = f"{i+1:04d}.jpg"
                    cbz.write(img_path, arcname)

            return cbz_path
        except Exception as e:
            print(f"Error creando CBZ: {e}")
            return None

    async def _create_pdf_from_images(self, name, image_paths, user_id):
        try:
            safe_name = self.neko.clean_name(name)
            pdf_path = os.path.join(os.getcwd(), "vault", f"{safe_name}.pdf")
            os.makedirs(os.path.dirname(pdf_path), exist_ok=True)

            images = []
            for img_path in image_paths:
                img = Image.open(img_path).convert("RGB")
                images.append(img)

            if images:
                images[0].save(pdf_path, "PDF", save_all=True, append_images=images[1:])
                return pdf_path
            return None
        except Exception as e:
            print(f"Error creando PDF: {e}")
            return None

    async def _process_gallery_json_with_range(self, message, result, code, format_choice, start_page, end_page, user_id):
        try:
            images = result.get("image_links", [])
            title = result.get("title", f"Doujin {code}")
            if end_page is None or end_page > len(images):
                end_page = len(images)

            if start_page < 1:
                start_page = 1
            if end_page < start_page:
                start_page, end_page = end_page, start_page

            selected_images = images[start_page-1:end_page]

            if not selected_images:
                await safe_call(message.reply_text, "No hay imágenes en el rango seleccionado")
                return

            if len(selected_images) == 1:
                img_url = selected_images[0]
                temp_path = await self._download_and_convert_image(img_url)
                if temp_path:
                    caption = f"**{title}**\nCódigo: `{code}`\nPágina única"
                    await safe_call(message.reply_photo, temp_path, caption=caption)
                    os.remove(temp_path)
                else:
                    await safe_call(message.reply_text, "Error al descargar la imagen")
                return

            progress_msg = await safe_call(message.reply_text, f"Preparando {len(selected_images)} imágenes...")

            first_image_url = selected_images[0]
            first_image_path = await self._download_and_convert_image(first_image_url)

            if first_image_path:
                caption = f"**{title}**\nCódigo: `{code}`\nPáginas: {start_page}-{end_page} (total {len(images)})"
                await safe_call(message.reply_photo, first_image_path, caption=caption)
                os.remove(first_image_path)
            else:
                await safe_call(message.reply_text, f"**{title}**\nCódigo: `{code}`\nPáginas: {start_page}-{end_page} (total {len(images)})")

            temp_dir = tempfile.mkdtemp()
            downloaded_paths = []

            for i, img_url in enumerate(selected_images):
                temp_path = os.path.join(temp_dir, f"{i+1:04d}.jpg")
                if await self.async_download(img_url, temp_path):
                    downloaded_paths.append(temp_path)

            if downloaded_paths:
                media_group = []
                for i, path in enumerate(downloaded_paths[:10]):
                    if i == 0:
                        continue
                    media_group.append(InputMediaPhoto(media=path))

                if media_group:
                    await safe_call(message.reply_media_group, media_group)

            shutil.rmtree(temp_dir)

        except Exception as e:
            print(f"Error en _process_gallery_json_with_range: {e}")
            await safe_call(message.reply_text, f"❌ Error procesando galería: {e}")

    async def _process_gallery_with_format(self, message, result, code, format_choice, start_page, end_page, user_id):
        try:
            images = result.get("image_links", [])
            title = result.get("title", f"Doujin {code}")

            if end_page is None or end_page > len(images):
                end_page = len(images)

            if start_page < 1:
                start_page = 1
            if end_page < start_page:
                start_page, end_page = end_page, start_page

            selected_images = images[start_page-1:end_page]

            if not selected_images:
                await safe_call(message.reply_text, "No hay imágenes en el rango seleccionado")
                return

            progress_msg = await safe_call(message.reply_text, f"📥 Descargando {len(selected_images)} imágenes...")

            temp_paths = await self.download_images_concurrently(selected_images)

            if not temp_paths:
                await safe_call(progress_msg.edit_text, "❌ Error al descargar imágenes")
                return

            first_image_path = temp_paths[0]
            thumb_path = await self._convert_to_thumbnail(first_image_path)

            base_name = f"{title} - {code} (págs {start_page}-{end_page})"

            if format_choice == "cbz":
                file_path = await self.neko.create_cbz_async(base_name, temp_paths)
            else:
                file_path = await self.neko.create_pdf_async(base_name, temp_paths)

            if file_path and os.path.exists(file_path):
                await self._send_document_with_progress(message.chat.id, file_path, f"📚 {base_name}", thumb=thumb_path)
            else:
                await safe_call(message.reply_text, "❌ Error al crear el archivo")

            for p in temp_paths:
                if os.path.exists(p):
                    os.remove(p)
            if thumb_path and os.path.exists(thumb_path):
                os.remove(thumb_path)

        except Exception as e:
            print(f"Error en _process_gallery_with_format: {e}")
            await safe_call(message.reply_text, f"❌ Error: {e}")

    async def _download_and_convert_image(self, url):
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        temp_path = temp_file.name
        temp_file.close()

        if await self.async_download(url, temp_path):
            try:
                img = Image.open(temp_path)
                if img.format == "WEBP":
                    rgb_img = img.convert("RGB")
                    rgb_img.save(temp_path, "JPEG")
                return temp_path
            except Exception as e:
                print(f"Error convirtiendo imagen: {e}")
                return temp_path
        return None

    async def _convert_to_thumbnail(self, image_path, size=(320, 320)):
        try:
            thumb_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
            thumb_path = thumb_file.name
            thumb_file.close()

            img = Image.open(image_path)
            img.thumbnail(size)
            img.save(thumb_path, "JPEG")
            return thumb_path
        except Exception as e:
            print(f"Error creando miniatura: {e}")
            return None

    def _sort_key(self, val):
        if not val or val == 'sin_volumen':
            return (float('inf'), '')
        try:
            return (float(val), '')
        except ValueError:
            return (float('inf'), val)
