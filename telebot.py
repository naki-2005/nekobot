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
            BotCommand("reset", "Reiniciar servicio Render (ServiceID BearerToken)")
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
                current = user_settings.get(user_id, "raw")
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
            
            format_choice = user_settings.get(user_id, "raw")
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
                    await self._download_manga_by_volumes(
                        progress_msg, manga_id, feed_data, covers_dict,
                        format_choice, quality_choice, start_chapter, start_volume, end_chapter, end_volume, user_id
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
    async def _download_manga_by_volumes(self, progress_msg, manga_id, volumes_order, volumes_data, covers_dict, format_choice, start_chapter, start_volume, end_chapter, end_volume, user_id):
        try:
            user_lang = user_manga_settings.get(user_id, {}).get("language", "en")
            total_volumes = len(volumes_order)
            
            vault_dir = os.path.join(os.getcwd(), "vault", "manga", manga_id)
            os.makedirs(vault_dir, exist_ok=True)
            
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
                    
                    if start_chapter:
                        if self._sort_key(chapter_num) < self._sort_key(str(start_chapter)):
                            continue
                    
                    if end_chapter:
                        if self._sort_key(chapter_num) > self._sort_key(str(end_chapter)):
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
                    
                    if start_chapter:
                        if self._sort_key(chapter_num) < self._sort_key(str(start_chapter)):
                            continue
                    
                    if end_chapter:
                        if self._sort_key(chapter_num) > self._sort_key(str(end_chapter)):
                            break
                    
                    image_links = self.neko.download_chapter(chapter['id'])
                    if image_links:
                        downloaded_images = await self.download_images_concurrently(image_links, max_concurrent=10)
                        
                        volume_dir = os.path.join(vault_dir, f"vol_{volume}")
                        os.makedirs(volume_dir, exist_ok=True)
                        
                        for img_idx, img_path in enumerate(downloaded_images):
                            new_name = f"vol_{volume}_chap_{chapter_num}_img_{img_idx+1:03d}.jpg"
                            new_path = os.path.join(volume_dir, new_name)
                            shutil.move(img_path, new_path)
                            all_volume_images.append(new_path)
                        
                        total_images_downloaded += len(downloaded_images)
                        
                        await safe_call(progress_msg.edit_text, f"📦 Procesando volumen {volume} ({volume_index}/{total_volumes}) en {user_lang.upper()}... ({total_images_downloaded}/{total_images_expected} Imágenes descargadas)")
                
                if not all_volume_images:
                    continue
                
                if chapter_range:
                    min_chap = min(chapter_range)
                    max_chap = max(chapter_range)
                    
                    if volume == 'sin_volumen':
                        volume_name = f"Capítulos {min_chap}-{max_chap}"
                    else:
                        volume_name = f"Volumen {volume}"
                        
                        if chapter_range:
                            if len(chapter_range) > 1:
                                volume_name = f"Volumen {volume} ({min_chap}-{max_chap})"
                            else:
                                volume_name = f"Volumen {volume} ({min_chap})"
                
                if format_choice == "cbz" and all_volume_images:
                    cbz_path = await self._create_cbz_from_images(volume_name, all_volume_images, user_id)
                    if cbz_path:
                        await self._send_document_with_progress(progress_msg.chat.id, cbz_path, f"📚 {volume_name}")
                
                elif format_choice == "pdf" and all_volume_images:
                    pdf_path = await self._create_pdf_from_images(volume_name, all_volume_images, user_id)
                    if pdf_path:
                        await self._send_document_with_progress(progress_msg.chat.id, pdf_path, f"📚 {volume_name}")
                
                else:
                    await safe_call(progress_msg.edit_text, f"✅ Volumen {volume} guardado en vault: {vault_dir}")
                
                await asyncio.sleep(0.2)
            
            await safe_call(progress_msg.edit_text, "✅ Descarga de volúmenes completada y guardada en vault")
            
        except Exception as e:
            print(f"Error en _download_manga_by_volumes: {e}")
            await safe_call(progress_msg.edit_text, f"❌ Error en la descarga: {e}")
            
    async def _download_manga_by_chapters(self, progress_msg, manga_id, feed_data, covers_dict, format_choice, quality_choice, start_chapter, start_volume, end_chapter, end_volume, user_id):
        try:
            vault_dir = os.path.join(os.getcwd(), "vault", "manga", manga_id)
            os.makedirs(vault_dir, exist_ok=True)
            
            all_chapters = []
            for volume_data in feed_data:
                volume = volume_data.get('volume')
                chapters = volume_data.get('chapters', [])
                
                for chapter in chapters:
                    chapter['volume'] = volume
                    all_chapters.append(chapter)
            
            all_chapters.sort(key=lambda x: self._sort_key(x.get('chapter', '0')))
            
            filtered_chapters = []
            
            for chapter in all_chapters:
                chapter_num = chapter.get('chapter')
                volume = chapter.get('volume')
                
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
                
                filtered_chapters.append(chapter)
            
            total_chapters = len(filtered_chapters)
            
            for idx, chapter in enumerate(filtered_chapters, 1):
                chapter_num = chapter.get('chapter')
                chapter_id = chapter.get('chapter_id')
                volume = chapter.get('volume')
                
                if not chapter_id:
                    continue
                
                try:
                    dl_json = self.mangadex.dl(chapter_id)
                    if not dl_json:
                        continue
                    
                    dl_data = json.loads(dl_json)
                    if 'error' in dl_data:
                        continue
                    
                    image_urls = dl_data.get(quality_choice, [])
                    
                    if not image_urls:
                        continue
                    
                    total_images = len(image_urls)
                    
                    await safe_call(progress_msg.edit_text, f"📖 Descargando capítulo {chapter_num} ({idx}/{total_chapters})... (0/{total_images} Imágenes descargadas)")
                    
                    downloaded_images = await self.download_images_concurrently(image_urls, max_concurrent=10)
                    
                    if not downloaded_images:
                        continue
                    
                    chapter_dir = os.path.join(vault_dir, f"chap_{chapter_num}")
                    os.makedirs(chapter_dir, exist_ok=True)
                    
                    chapter_images = []
                    for img_idx, img_path in enumerate(downloaded_images):
                        chapter_safe = str(chapter_num).replace('.', '_')
                        new_name = f"vol_{volume if volume else '0'}_chap_{chapter_safe}_img_{img_idx+1:03d}.jpg"
                        new_path = os.path.join(chapter_dir, new_name)
                        shutil.move(img_path, new_path)
                        chapter_images.append(new_path)
                    
                    await safe_call(progress_msg.edit_text, f"📖 Descargando capítulo {chapter_num} ({idx}/{total_chapters})... ({len(downloaded_images)}/{total_images} Imágenes descargadas)")
                    
                    thumbnail_path = None
                    if volume is not None:
                        volume_str = str(volume)
                        if volume_str in covers_dict:
                            cover_url = covers_dict[volume_str]
                            try:
                                thumbnail_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
                                thumbnail_path = thumbnail_file.name
                                thumbnail_file.close()
                                
                                if await self.async_download(cover_url, thumbnail_path):
                                    img = Image.open(thumbnail_path)
                                    img.thumbnail((320, 320))
                                    img.save(thumbnail_path, "JPEG")
                            except Exception as e:
                                print(f"Error descargando miniatura: {e}")
                                thumbnail_path = None
                    
                    if format_choice == "cbz" and chapter_images:
                        cbz_path = await self._create_cbz_from_images(f"Capítulo {chapter_num}", chapter_images, user_id)
                        if cbz_path:
                            await self._send_document_with_progress(progress_msg.chat.id, cbz_path, f"📖 Capítulo {chapter_num}", thumb=thumbnail_path)
                    
                    elif format_choice == "pdf" and chapter_images:
                        pdf_path = await self._create_pdf_from_images(f"Capítulo {chapter_num}", chapter_images, user_id)
                        if pdf_path:
                            await self._send_document_with_progress(progress_msg.chat.id, pdf_path, f"📖 Capítulo {chapter_num}", thumb=thumbnail_path)
                    
                    else:
                        await safe_call(progress_msg.edit_text, f"✅ Capítulo {chapter_num} guardado en vault: {chapter_dir}")
                    
                    if thumbnail_path and os.path.exists(thumbnail_path):
                        try:
                            os.remove(thumbnail_path)
                        except:
                            pass
                    
                    await asyncio.sleep(0.2)
                
                except Exception as e:
                    print(f"Error descargando capítulo {chapter_num}: {e}")
                    continue
            
            await safe_call(progress_msg.edit_text, "✅ Descarga de capítulos completada y guardada en vault")
            
        except Exception as e:
            print(f"Error en _download_manga_by_chapters: {e}")
            await safe_call(progress_msg.edit_text, f"❌ Error en la descarga: {e}")
    
    async def _create_cbz_from_images(self, nombre, image_paths, user_id):
        try:
            safe_nombre = self.neko.clean_name(nombre)
            temp_dir = tempfile.mkdtemp()
            
            for i, img_path in enumerate(image_paths):
                if os.path.exists(img_path):
                    ext = os.path.splitext(img_path)[1]
                    new_name = f"{i:04d}{ext}"
                    new_path = os.path.join(temp_dir, new_name)
                    shutil.copy2(img_path, new_path)
            
            cbz_path = os.path.join(os.getcwd(), "vault", f"{safe_nombre}.cbz")
            with zipfile.ZipFile(cbz_path, 'w', zipfile.ZIP_DEFLATED) as cbz:
                for file in sorted(os.listdir(temp_dir)):
                    cbz.write(os.path.join(temp_dir, file), file)
            
            shutil.rmtree(temp_dir)
            
            for img_path in image_paths:
                try:
                    os.remove(img_path)
                except:
                    pass
            
            return cbz_path
        except Exception as e:
            print(f"Error creando CBZ: {e}")
            return None

    async def _create_pdf_from_images(self, nombre, image_paths, user_id):
        try:
            safe_nombre = self.neko.clean_name(nombre)
            pdf_path = os.path.join(os.getcwd(), "vault", f"{safe_nombre}.pdf")
            
            images = []
            for img_path in image_paths:
                if os.path.exists(img_path):
                    try:
                        img = Image.open(img_path)
                        img = img.convert("RGB")
                        images.append(img)
                    except Exception as e:
                        print(f"Error procesando imagen {img_path}: {e}")
                        continue
            
            if images:
                images[0].save(pdf_path, "PDF", save_all=True, append_images=images[1:])
                
                for img_path in image_paths:
                    try:
                        os.remove(img_path)
                    except:
                        pass
                
                return pdf_path
            
            return None
        except Exception as e:
            print(f"Error creando PDF: {e}")
            return None

    def _sort_key(self, val):
        if not val or val == 'sin_volumen' or val == 'None':
            return (float('inf'), '')
        try:
            return (float(val), '')
        except ValueError:
            return (float('inf'), val)
    
    async def _download_hitomi_raw(self, message, g, pages, titulo, progress_msg, start_page, end_page, total_pages, user_id):
        batch_size = 10
        downloaded_images = []
        current_batch = []
        
        vault_dir = os.path.join(os.getcwd(), "vault", "hitomi", g)
        os.makedirs(vault_dir, exist_ok=True)
        
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
                vault_path = os.path.join(vault_dir, nombre_salida)
                
                with open(vault_path, 'wb') as archivo_imagen:
                    archivo_imagen.write(imagen_decodificada)
                
                downloaded_images.append(vault_path)
                current_batch.append(vault_path)
                
                range_info = ""
                if start_page != 1 or end_page != total_pages:
                    range_info = f" (Progreso limitado al rango {start_page}-{end_page})"
                
                await safe_call(progress_msg.edit_text, f"Progreso de descarga de {g} {idx}/{len(pages)}{range_info} - Página {pagina_actual}/{paginas_totales}")
                
                if len(current_batch) >= batch_size:
                    await self._send_photo_batch(message, photo_paths=current_batch, batch_number=(idx//batch_size)+1, user_id=user_id)
                    current_batch = []
                    await asyncio.sleep(0.2)
                    
            except Exception as e:
                print(f"Error descargando página {page_num}: {e}")
                continue
        
        if current_batch:
            await self._send_photo_batch(message, photo_paths=current_batch, batch_number=(len(pages)//batch_size)+1, user_id=user_id)
        
        await safe_call(progress_msg.edit_text, f"✅ Descarga RAW completada y guardada en vault: {titulo}")
    
    async def _download_hitomi_with_format(self, message, g, pages, titulo, progress_msg, start_page, end_page, total_pages, format_choice, user_id):
        downloaded_images = []
        vault_dir = os.path.join(os.getcwd(), "vault", "hitomi", g)
        os.makedirs(vault_dir, exist_ok=True)
        
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
                vault_path = os.path.join(vault_dir, nombre_salida)
                
                with open(vault_path, 'wb') as archivo_imagen:
                    archivo_imagen.write(imagen_decodificada)
                
                downloaded_images.append(vault_path)
                
                range_info = ""
                if start_page != 1 or end_page != total_pages:
                    range_info = f" (Progreso limitado al rango {start_page}-{end_page})"
                
                await safe_call(progress_msg.edit_text, f"Progreso de descarga de {g} {idx}/{len(pages)}{range_info} - Página {pagina_actual}/{paginas_totales}")
                    
            except Exception as e:
                print(f"Error descargando página {page_num}: {e}")
                continue
        
        if format_choice == "cbz" and downloaded_images:
            cbz_path = await self._create_cbz_from_images(titulo, downloaded_images, user_id)
            if cbz_path:
                await self._send_document_with_progress(message.chat.id, cbz_path, f"📖 {titulo}")
        
        elif format_choice == "pdf" and downloaded_images:
            pdf_path = await self._create_pdf_from_images(titulo, downloaded_images, user_id)
            if pdf_path:
                await self._send_document_with_progress(message.chat.id, pdf_path, f"📖 {titulo}")
        
        await safe_call(progress_msg.edit_text, f"✅ Descarga {format_choice.upper()} completada: {titulo}")
    
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
        
        vault_dir = os.path.join(os.getcwd(), "vault", "doujin", code)
        os.makedirs(vault_dir, exist_ok=True)
        
        download_tasks = []
        for i, img_url in enumerate(images):
            img_path = os.path.join(vault_dir, f"page_{i+start_page:04d}.jpg")
            download_tasks.append(self.async_download(img_url, img_path))
        
        await asyncio.gather(*download_tasks)
        
        if images:
            first_image_path = os.path.join(vault_dir, f"page_{start_page:04d}.jpg")
            if os.path.exists(first_image_path):
                await safe_call(message.reply_photo, first_image_path, caption=caption)
        
        if len(images) > 1:
            await self._send_photos_in_batches(message, images[1:], start_page+1, vault_dir, user_id=user_id)
    
    async def _process_gallery_with_format(self, message, result, code, format_choice, start_page, end_page, user_id):
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
        
        progress_msg = await safe_call(message.reply_text, f"Descargando {len(images)} imágenes en formato {format_choice.upper()}...")
        
        downloaded_images = []
        for i, img_url in enumerate(images):
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
            temp_path = temp_file.name
            temp_file.close()
            
            if await self.async_download(img_url, temp_path):
                downloaded_images.append(temp_path)
            
            if (i + 1) % 5 == 0 or i == len(images) - 1:
                await safe_call(progress_msg.edit_text, f"Descargando {len(images)} imágenes en formato {format_choice.upper()}... ({i+1}/{len(images)})")
        
        if format_choice == "cbz" and downloaded_images:
            cbz_path = await self._create_cbz_from_images(f"{nombre} - {code}", downloaded_images, user_id)
            if cbz_path:
                caption = f"**{nombre}**\nCódigo: `{code}`\nRango: {start_page}-{end_page} de {total_images}\n\n{self._format_tags(tags)}"
                await self._send_document_with_progress(message.chat.id, cbz_path, caption)
        
        elif format_choice == "pdf" and downloaded_images:
            pdf_path = await self._create_pdf_from_images(f"{nombre} - {code}", downloaded_images, user_id)
            if pdf_path:
                caption = f"**{nombre}**\nCódigo: `{code}`\nRango: {start_page}-{end_page} de {total_images}\n\n{self._format_tags(tags)}"
                await self._send_document_with_progress(message.chat.id, pdf_path, caption)
        
        await safe_call(progress_msg.edit_text, f"✅ Descarga {format_choice.upper()} completada: {nombre}")
    
    async def _send_photos_in_batches(self, message, image_urls, start_index, vault_dir, batch_size=10, user_id=None):
        for i in range(0, len(image_urls), batch_size):
            batch_urls = image_urls[i:i+batch_size]
            media_group = []
            
            download_tasks = []
            for idx, url in enumerate(batch_urls):
                page_num = start_index + i + idx
                img_path = os.path.join(vault_dir, f"page_{page_num:04d}.jpg")
                download_tasks.append((url, img_path))
            
            for url, temp_path in download_tasks:
                if await self.async_download(url, temp_path):
                    media_group.append(InputMediaPhoto(temp_path))
            
            if media_group:
                await safe_call(message.reply_media_group, media_group)
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
        
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".torrent")
        temp_path = temp_file.name
        temp_file.close()
        
        await self.app.download_media(document, file_name=temp_path)
        
        with open(temp_path, "rb") as f:
            torrent_data = f.read()
        
        magnet = self._torrent_to_magnet(torrent_data)
        os.remove(temp_path)
        
        await self._start_torrent_download(message, {"magnet": magnet}, message.from_user.id)
    
    async def _process_torrent_text(self, message, text):
        text = text.strip()
        
        if text.startswith("magnet:?"):
            magnet = text
            await self._start_torrent_download(message, {"magnet": magnet}, message.from_user.id)
            return
        
        elif text.endswith(".torrent"):
            if text.startswith("http://") or text.startswith("https://"):
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(text) as response:
                            if response.status == 200:
                                torrent_data = await response.read()
                                magnet = self._torrent_to_magnet(torrent_data)
                                await self._start_torrent_download(message, {"magnet": magnet}, message.from_user.id)
                            else:
                                await safe_call(message.reply_text, f"❌ Error al descargar")
                except Exception as e:
                    await safe_call(message.reply_text, f"❌ Error")
            else:
                if os.path.exists(text):
                    with open(text, "rb") as f:
                        torrent_data = f.read()
                    magnet = self._torrent_to_magnet(torrent_data)
                    await self._start_torrent_download(message, {"magnet": magnet}, message.from_user.id)
                else:
                    await safe_call(message.reply_text, "❌ Archivo no encontrado")
        else:
            await safe_call(message.reply_text, "❌ Enlace no válido")
    
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
            return
        
        download_path = os.path.join(os.getcwd(), "vault", str(user_id))
        os.makedirs(download_path, exist_ok=True)
        
        status_msg = await safe_call(message.reply_text, "⏳ Iniciando descarga torrent...")
        
        try:
            download_generator = self.neko.download_magnet(magnet, download_path)
            final_path = None
            last_progress = ""
            last_update_time = time.time()
            
            async for progress_text in download_generator:
                if progress_text.startswith("📥"):
                    current_time = time.time()
                    if progress_text != last_progress and current_time - last_update_time >= 10:
                        await safe_call(status_msg.edit_text, progress_text)
                        last_progress = progress_text
                        last_update_time = current_time
                elif progress_text.startswith("✅") and "COMPLETADO" in progress_text:
                    continue
                else:
                    if os.path.exists(progress_text):
                        final_path = progress_text
            
            if final_path and os.path.exists(final_path):
                if os.path.isfile(final_path):
                    await self._send_document_with_progress(
                        message.chat.id,
                        final_path,
                        caption=f"✅ {os.path.basename(final_path)}"
                    )
                elif os.path.isdir(final_path):
                    for root, dirs, files in os.walk(final_path):
                        for file in files:
                            file_path = os.path.join(root, file)
                            try:
                                await self._send_document_with_progress(
                                    message.chat.id,
                                    file_path,
                                    caption=f"✅ {os.path.basename(file_path)}"
                                )
                                await asyncio.sleep(0.5)
                            except Exception as e:
                                print(f"Error enviando archivo {file_path}: {e}")
            
            try:
                await status_msg.delete()
            except:
                pass
            
        except Exception as e:
            try:
                await status_msg.delete()
            except:
                pass
            await safe_call(message.reply_text, f"❌ Error en la descarga")
    
    async def _process_mega_download(self, message, mega_link):
        try:
            status_msg = await safe_call(message.reply_text, "⏳ Iniciando descarga de MEGA...")
            
            download_path = self.neko.mega_download(mega_link)
            
            await safe_call(status_msg.edit_text, "✅ Descarga de MEGA completada. Procesando archivos...")
            
            if not os.path.exists(download_path):
                await safe_call(status_msg.edit_text, "❌ No se encontró la carpeta de descarga")
                return
            
            items = os.listdir(download_path)
            
            if len(items) == 0:
                await safe_call(status_msg.edit_text, "❌ La carpeta está vacía")
                shutil.rmtree(download_path, ignore_errors=True)
                return
            
            elif len(items) == 1:
                single_item = os.path.join(download_path, items[0])
                
                if os.path.isfile(single_item):
                    await self._send_document_with_progress(
                        message.chat.id,
                        single_item,
                        caption=f"✅ {os.path.basename(single_item)}"
                    )
                
                elif os.path.isdir(single_item):
                    parts = self.neko.compress_to_7z(single_item, 2000)
                    if parts:
                        for part in parts:
                            await self._send_document_with_progress(
                                message.chat.id,
                                part,
                                f"✅ {os.path.basename(part)}"
                            )
                    else:
                        await safe_call(status_msg.edit_text, "❌ Error al comprimir carpeta")
                
                else:
                    await safe_call(status_msg.edit_text, "❌ Tipo de archivo no soportado")
            
            else:
                parts = self.neko.compress_to_7z(download_path, 2000)
                
                if parts:
                    for part in parts:
                        await self._send_document_with_progress(
                            message.chat.id,
                            part,
                            f"✅ {os.path.basename(part)}"
                        )
                else:
                    await safe_call(status_msg.edit_text, "❌ Error al comprimir archivos")
            
            try:
                await status_msg.delete()
            except:
                pass
            
            if os.path.exists(download_path):
                shutil.rmtree(download_path, ignore_errors=True)
        
        except Exception as e:
            try:
                await status_msg.delete()
            except:
                pass
            await safe_call(message.reply_text, f"❌ Error en la descarga de MEGA: {str(e)}")
            
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
