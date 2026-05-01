import os
import sys
import argparse
import asyncio
import threading
import tempfile
import time
import aiohttp
import aiofiles
import re
import requests
import json
import math
import shutil
import zipfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request, send_file, render_template_string, jsonify
from pyrogram import Client, filters
from pyrogram.types import Message, BotCommand, InputMediaPhoto
from pyrogram.errors import FloodWait
from bs4 import BeautifulSoup
from collections import defaultdict
from PIL import Image
import io
import base64

set_cmd = False
user_settings = {}

flask_app = Flask(__name__)
BASE_DIR = os.path.join(os.getcwd(), "vault")
os.makedirs(BASE_DIR, exist_ok=True)

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

def clean_name(name):
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    name = name.replace('\n', ' ').replace('\r', ' ')
    name = ' '.join(name.split())
    if len(name) > 200:
        name = name[:197] + '...'
    return name

class NakiBotAPI:
    def __init__(self):
        self.session = requests.Session()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }
        self.tag_cache = {}
        self.last_request_time = 0
        self.min_request_interval = 4.0
    
    def _rate_limit(self):
        current_time = time.time()
        elapsed = current_time - self.last_request_time
        if elapsed < self.min_request_interval:
            time.sleep(self.min_request_interval - elapsed)
        self.last_request_time = time.time()
    
    def snh(self, search_term, page=1):
        api_url = f"https://nhentai.net/api/v2/search?query={search_term}&page={page}"
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self._rate_limit()
                response = self.session.get(api_url, timeout=30)
                
                if response.status_code != 200:
                    if attempt < max_retries - 1:
                        time.sleep(2)
                        continue
                    return {"error": f"API error: {response.status_code}"}
                
                data = response.json()
                
                results_data = []
                for item in data.get('result', []):
                    thumbnail_url = f"https://t2.nhentai.net/{item['thumbnail']}" if item.get('thumbnail') else ''
                    results_data.append({
                        'nombre': item.get('english_title', ''),
                        'miniatura': thumbnail_url,
                        'codigo': str(item.get('id', '')),
                        'num_pages': item.get('num_pages', 0)
                    })
                
                return {
                    'total_resultados': data.get('total', 0),
                    'total_paginas': data.get('num_pages', 0),
                    'pagina_actual': page,
                    'termino_busqueda': search_term,
                    'resultados': results_data
                }
                
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
                return {"error": f"Error: {str(e)}"}
        
        return {"error": "Falló después de múltiples intentos"}

    def s3h(self, search_term, page=1):
        encoded_search = requests.utils.quote(search_term)
        url = f"https://es.3hentai.net/search?q={encoded_search}&page={page}"
        
        try:
            response = self.session.get(url, timeout=30)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            total_results_text = soup.find('div', class_='search-result-nb-result')
            total_results = 0
            if total_results_text:
                total_text = total_results_text.text.strip()
                total_results = int(total_text.replace(' resultados', '').replace(' ', '').replace('\xa0', ''))
            
            total_pages = math.ceil(total_results / 25)
            
            doujin_cols = soup.find_all('div', class_='doujin-col')
            results_data = []
            
            for col in doujin_cols[:25]:
                doujin = col.find('div', class_='doujin')
                if doujin:
                    cover = doujin.find('a', class_='cover')
                    if cover:
                        title_div = cover.find('div', class_='title')
                        titulo = title_div.text.strip() if title_div else "Título no disponible"
                        
                        img = cover.find('img')
                        imagen_url = ""
                        if img and 'data-src' in img.attrs:
                            imagen_url = img['data-src'].replace('thumb.jpg', '1.jpg')
                        elif img and 'src' in img.attrs:
                            imagen_url = img['src'].replace('thumb.jpg', '1.jpg')
                        
                        href = cover.get('href', '')
                        codigo_match = re.search(r'/d/(\d+)', href)
                        codigo = codigo_match.group(1) if codigo_match else ""
                        
                        results_data.append({
                            'nombre': titulo,
                            'miniatura': imagen_url,
                            'codigo': codigo
                        })
            
            return {
                'total_resultados': total_results,
                'total_paginas': total_pages,
                'pagina_actual': page,
                'termino_busqueda': search_term,
                'resultados': results_data
            }
            
        except Exception as e:
            return {
                'total_resultados': 0,
                'total_paginas': 0,
                'pagina_actual': page,
                'termino_busqueda': search_term,
                'resultados': [],
                'error': str(e)
            }
            
    def vnh(self, code):
        api_url = f"https://nhentai.net/api/v2/galleries/{code}"
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self._rate_limit()
                response = self.session.get(api_url, timeout=30)
                
                if response.status_code != 200:
                    if attempt < max_retries - 1:
                        time.sleep(2)
                        continue
                    return {
                        'title': '',
                        'code': int(code) if str(code).isdigit() else 0,
                        'cover_image': '',
                        'tags': {},
                        'image_links': [],
                        'success': False,
                        'error': f"API error: {response.status_code}"
                    }
                
                data = response.json()
                
                title = ""
                if 'title' in data:
                    if data['title'].get('pretty'):
                        title = data['title']['pretty']
                    elif data['title'].get('english'):
                        title = data['title']['english']
                    elif data['title'].get('japanese'):
                        title = data['title']['japanese']
                
                tags_dict = {}
                if 'tags' in data:
                    for tag in data['tags']:
                        tag_type = tag.get('type', 'unknown')
                        tag_name = tag.get('name', '')
                        if tag_type not in tags_dict:
                            tags_dict[tag_type] = []
                        tags_dict[tag_type].append(tag_name)
                
                image_links = []
                cover_image = ""
                
                if 'pages' in data and data['pages']:
                    for page in data['pages']:
                        page_path = page.get('path', '')
                        if page_path:
                            image_link = f"https://i2.nhentai.net/{page_path}"
                            image_links.append(image_link)
                    
                    if image_links:
                        cover_image = image_links[0]
                
                return {
                    'title': title,
                    'code': data.get('id', int(code) if str(code).isdigit() else 0),
                    'cover_image': cover_image,
                    'tags': tags_dict,
                    'image_links': image_links,
                    'success': True
                }
                
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
                return {
                    'title': '',
                    'code': int(code) if str(code).isdigit() else 0,
                    'cover_image': '',
                    'tags': {},
                    'image_links': [],
                    'success': False,
                    'error': str(e)[:100]
                }
        
        return {
            'title': '',
            'code': int(code) if str(code).isdigit() else 0,
            'cover_image': '',
            'tags': {},
            'image_links': [],
            'success': False,
            'error': "Falló después de múltiples intentos"
        }

    def v3h(self, code):
        url = f"https://es.3hentai.net/d/{code}"
        
        try:
            response = self.session.get(url, timeout=30)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            title_element = soup.title
            title = title_element.string.strip() if title_element and title_element.string else "Sin título"
            
            tags_dict = {}
            tag_containers = soup.find_all("div", class_="tag-container")
            for container in tag_containers:
                field_name = container.get_text(strip=True).split(':')[0].strip()
                tags = []
                for tag_link in container.find_all("a", class_="name"):
                    tags.append(tag_link.get_text(strip=True))
                if tags:
                    tags_dict[field_name] = tags
            
            gallery = soup.find("div", id="main-content")
            thumbs = gallery.find("div", id="thumbnail-gallery") if gallery else None
            thumb_divs = thumbs.find_all("div", class_="single-thumb") if thumbs else []
            
            image_links = []
            for div in thumb_divs:
                img_tag = div.find("img")
                if img_tag:
                    src_url = img_tag.get("data-src") or img_tag.get("src")
                    if src_url:
                        full_img_url = re.sub(r't(?=\.\w{3,4})$', '', src_url)
                        image_links.append(full_img_url)
            
            cover_image = image_links[0] if image_links else ""
            
            return {
                'title': title,
                'code': code,
                'cover_image': cover_image,
                'tags': tags_dict,
                'image_links': image_links,
                'success': True
            }
            
        except Exception as e:
            return {
                'title': '',
                'code': code,
                'cover_image': '',
                'tags': {},
                'image_links': [],
                'success': False,
                'error': str(e)
            }

class NekoTelegram:
    def __init__(self, api_id, api_hash, bot_token):
        self.api_id = api_id
        self.api_hash = api_hash
        self.bot_token = bot_token
        self.naki_api = NakiBotAPI()
        self.app = Client("nekobot", api_id=int(api_id), api_hash=api_hash, bot_token=bot_token)
        self.download_pool = ThreadPoolExecutor(max_workers=20)
        self.flask_thread = None
        
        @self.app.on_message(filters.private)
        async def _handle_message(client: Client, message: Message):
            global set_cmd
            if not set_cmd:
                await self.lista_cmd()
                set_cmd = True
            await self._handle_message(client, message)
    
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
    
    async def lista_cmd(self):
        await self.app.set_bot_commands([
            BotCommand("start", "Iniciar bot"),
            BotCommand("nh", "Descarga un doujin de nhentai"),
            BotCommand("3h", "Descarga un doujin de 3hentai"),
            BotCommand("snh", "Busca doujins por filtros en nhentai"),
            BotCommand("s3h", "Busca doujins por filtros en 3hentai"),
            BotCommand("setfile", "Configurar formato de salida (cbz/pdf/raw)"),
        ])
        print("Comandos configurados en el bot")

    async def _create_thumbnail(self, image_path, size=(320, 320)):
        try:
            img = Image.open(image_path)
            img.thumbnail(size)
            thumb_path = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg").name
            img.save(thumb_path, "JPEG")
            return thumb_path
        except Exception as e:
            print(f"Error creando thumbnail: {e}")
            return None

    async def _create_cbz_from_images(self, nombre, image_paths, thumb_path=None):
        try:
            safe_nombre = clean_name(nombre)
            temp_dir = tempfile.mkdtemp()
            for i, img_path in enumerate(image_paths):
                if os.path.exists(img_path):
                    ext = os.path.splitext(img_path)[1]
                    new_name = f"{i:04d}{ext}"
                    new_path = os.path.join(temp_dir, new_name)
                    shutil.copy2(img_path, new_path)
            
            cbz_path = os.path.join(BASE_DIR, f"{safe_nombre}.cbz")
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

    async def _create_pdf_from_images(self, nombre, image_paths, thumb_path=None):
        try:
            safe_nombre = clean_name(nombre)
            pdf_path = os.path.join(BASE_DIR, f"{safe_nombre}.pdf")
            
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

    async def _send_photos_in_batches(self, message, image_paths):
        batch_size = 19
        for i in range(0, len(image_paths), batch_size):
            batch = image_paths[i:i+batch_size]
            media_group = []
            for img_path in batch:
                try:
                    media_group.append(InputMediaPhoto(img_path))
                except Exception as e:
                    print(f"Error añadiendo foto: {e}")
            
            if media_group:
                try:
                    await self.app.send_media_group(chat_id=message.chat.id, media=media_group)
                except Exception as e:
                    print(f"Error enviando grupo: {e}")
                await asyncio.sleep(0.5)

    async def _download_and_send_cover(self, message, cover_url, caption):
        if cover_url:
            cover_path = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg").name
            if await self.async_download(cover_url, cover_path):
                await safe_call(message.reply_photo, cover_path, caption=caption)
                os.remove(cover_path)
                return cover_path
        return None

    async def _handle_message(self, client: Client, message: Message):
        if not message.text:
            return
        
        text = message.text.strip()
        user_id = message.from_user.id

        if text.startswith("/start"):
            await safe_call(client.send_photo, chat_id=message.chat.id, photo="https://cdn.imgchest.com/files/93cb097b575e.webp", protect_content=True, caption="Nyaa, Hello, I'm Alice. The cute pet of @nakigeplayer")
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

        elif text.startswith("/nh ") or text.startswith("/3h "):
            parts = text.split()
            if len(parts) < 2:
                await safe_call(message.reply_text, "Usa: `/nh codigo` o `/3h codigo`")
                return
            
            command = text.split()[0]
            code = parts[1]
            
            if command == "/nh":
                result = self.naki_api.vnh(code)
            else:
                result = self.naki_api.v3h(code)
            
            if "error" in result or not result.get('success', False) and result.get('error'):
                await safe_call(message.reply_text, f"Error: `{result.get('error', 'Error desconocido')}`")
                return
            
            nombre = result.get("title", "Sin titulo")
            all_images = result.get("image_links", [])
            tags = result.get("tags", {})
            cover_image = result.get("cover_image", all_images[0] if all_images else "")
            
            if not all_images:
                await safe_call(message.reply_text, "No hay imagenes")
                return
            
            format_choice = user_settings.get(user_id, "cbz")
            
            caption = f"**{nombre}**\nCódigo: `{code}`\nTotal: {len(all_images)} páginas\nFormato: {format_choice.upper()}"
            
            if tags:
                tag_lines = []
                for category, items in tags.items():
                    if items:
                        tag_lines.append(f"**{category.upper()}:** {', '.join(items)}")
                caption += "\n\n" + "\n".join(tag_lines)
            
            cover_path = await self._download_and_send_cover(message, cover_image, caption)
            
            if format_choice == "raw":
                temp_files = []
                for i, img_url in enumerate(all_images, 1):
                    temp_path = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg").name
                    if await self.async_download(img_url, temp_path):
                        temp_files.append(temp_path)
                    
                    if len(temp_files) >= 19:
                        await self._send_photos_in_batches(message, temp_files)
                        for f in temp_files:
                            try:
                                os.remove(f)
                            except:
                                pass
                        temp_files = []
                    
                    await asyncio.sleep(0.2)
                
                if temp_files:
                    await self._send_photos_in_batches(message, temp_files)
                    for f in temp_files:
                        try:
                            os.remove(f)
                        except:
                            pass
                
                await safe_call(message.reply_text, f"✅ Descarga RAW completada: {nombre}")
            
            elif format_choice == "cbz":
                downloaded_images = await self.download_images_concurrently(all_images, max_concurrent=10)
                thumb_for_file = cover_path if cover_path and os.path.exists(cover_path) else None
                if thumb_for_file:
                    thumb_for_file = await self._create_thumbnail(thumb_for_file)
                cbz_path = await self._create_cbz_from_images(f"{nombre} - {code}", downloaded_images, thumb_for_file)
                if cbz_path:
                    await self._send_document_with_progress(message.chat.id, cbz_path, f"📚 {nombre} - {code}", thumb=thumb_for_file)
                    await safe_call(message.reply_text, f"✅ CBZ creado y enviado")
                if thumb_for_file and os.path.exists(thumb_for_file):
                    os.remove(thumb_for_file)
            
            elif format_choice == "pdf":
                downloaded_images = await self.download_images_concurrently(all_images, max_concurrent=10)
                thumb_for_file = cover_path if cover_path and os.path.exists(cover_path) else None
                if thumb_for_file:
                    thumb_for_file = await self._create_thumbnail(thumb_for_file)
                pdf_path = await self._create_pdf_from_images(f"{nombre} - {code}", downloaded_images, thumb_for_file)
                if pdf_path:
                    await self._send_document_with_progress(message.chat.id, pdf_path, f"📚 {nombre} - {code}", thumb=thumb_for_file)
                    await safe_call(message.reply_text, f"✅ PDF creado y enviado")
                if thumb_for_file and os.path.exists(thumb_for_file):
                    os.remove(thumb_for_file)
            
            if cover_path and os.path.exists(cover_path):
                os.remove(cover_path)

        elif text.startswith("/snh ") or text.startswith("/s3h "):
            parts = text.split(maxsplit=1)
            if len(parts) < 2:
                await safe_call(message.reply_text, "Usa: `/snh busqueda` o `/s3h busqueda`")
                return
            
            search = parts[1]
            page = 1
            
            if " -p " in search:
                search_term, page_param = search.split(" -p ")
                try:
                    page = int(page_param.strip())
                except:
                    page = 1
            else:
                search_term = search
            
            if text.startswith("/snh "):
                result = self.naki_api.snh(search_term, page)
            else:
                result = self.naki_api.s3h(search_term, page)
            
            if "error" in result:
                await safe_call(message.reply_text, f"Error: `{result['error']}`")
                return
            
            resultados = result.get("resultados", [])
            
            if not resultados:
                await safe_call(message.reply_text, "No se encontraron resultados")
                return
            
            info_text = f"🔍 **{result.get('termino_busqueda', search)}**\n"
            info_text += f"📊 Resultados: {result.get('total_resultados', 0)}\n"
            info_text += f"📄 Página: {result.get('pagina_actual', page)}/{result.get('total_paginas', 1)}\n\n"
            
            await safe_call(message.reply_text, info_text)
            
            for item in resultados[:50]:
                code = item.get("codigo", "")
                nombre = item.get("nombre", "Sin titulo")
                miniatura = item.get("miniatura", "")
                num_pages = item.get("num_pages", 0)
                
                if miniatura.startswith("//"):
                    miniatura = f"https:{miniatura}"
                
                caption = f"**{nombre}**\n📖 Código: `{code}`\n📄 Páginas: {num_pages}\n\n📥 Usa `/nh {code}` para descargar"
                
                if miniatura:
                    temp_path = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg").name
                    if await self.async_download(miniatura, temp_path):
                        await safe_call(message.reply_photo, temp_path, caption=caption)
                        os.remove(temp_path)
                    else:
                        await safe_call(message.reply_text, caption)
                else:
                    await safe_call(message.reply_text, caption)
                
                await asyncio.sleep(0.2)
    
    async def _send_document_with_progress(self, chat_id, document_path, caption="", thumb=None):
        if not os.path.exists(document_path):
            await safe_call(self.app.send_message, chat_id, f"❌ Error: Archivo no encontrado")
            return
        
        if thumb and os.path.exists(thumb):
            await safe_call(
                self.app.send_document,
                chat_id=chat_id,
                document=document_path,
                caption=caption,
                thumb=thumb
            )
        else:
            await safe_call(
                self.app.send_document,
                chat_id=chat_id,
                document=document_path,
                caption=caption
            )
        
        try:
            os.remove(document_path)
        except:
            pass
    
    def start_flask(self):
        if self.flask_thread and self.flask_thread.is_alive():
            return
        
        def run_flask():
            flask_app.run(host="0.0.0.0", port=5001, debug=False, use_reloader=False)
        
        self.flask_thread = threading.Thread(target=run_flask, daemon=True)
        self.flask_thread.start()
        print("[INFO] Servidor Flask iniciado en puerto 5001")
    
    def run(self):
        print("[INFO] Iniciando bot de Telegram...")
        self.app.run()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-A", "--api", help="API ID de Telegram")
    parser.add_argument("-H", "--hash", help="API Hash de Telegram")
    parser.add_argument("-T", "--token", help="Token del Bot")
    parser.add_argument("-F", "--flask", action="store_true", help="Incluir servidor Flask junto con el bot")
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
    
    bot.run()

if __name__ == "__main__":
    main()
