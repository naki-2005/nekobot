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
from bs4 import BeautifulSoup
from collections import defaultdict
import math
import random

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

class NakiBotAPI:
    def __init__(self):
        self.session = requests.Session()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        self.driver = None
        self.tag_cache = {}
        self.tag_cache_lock = threading.Lock()
        self.last_request_time = 0
        self.min_request_interval = 4.0
    
    def _rate_limit(self):
        current_time = time.time()
        elapsed = current_time - self.last_request_time
        if elapsed < self.min_request_interval:
            time.sleep(self.min_request_interval - elapsed)
        self.last_request_time = time.time()
    
    def _fetch_tags_by_ids(self, tag_ids):
        if not tag_ids:
            return {}
        
        with self.tag_cache_lock:
            cached_tags = {tid: self.tag_cache[tid] for tid in tag_ids if tid in self.tag_cache}
            missing_ids = [tid for tid in tag_ids if tid not in self.tag_cache]
        
        if not missing_ids:
            return cached_tags
        
        all_tag_data = {}
        all_tag_data.update(cached_tags)
        
        for i in range(0, len(missing_ids), 100):
            batch = missing_ids[i:i+100]
            ids_param = ','.join(str(tid) for tid in batch)
            api_url = f"https://nhentai.net/api/v2/tags/ids?ids={ids_param}"
            
            self._rate_limit()
            
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    response = self.session.get(api_url, timeout=30)
                    if response.status_code == 200:
                        data = response.json()
                        with self.tag_cache_lock:
                            for tag in data:
                                tag_id = tag.get('id')
                                if tag_id:
                                    self.tag_cache[tag_id] = tag
                                    all_tag_data[tag_id] = tag
                        break
                    else:
                        if attempt < max_retries - 1:
                            time.sleep(2)
                            continue
                except Exception as e:
                    if attempt < max_retries - 1:
                        time.sleep(2)
                        continue
        
        return all_tag_data
    
    def _format_tags_for_display(self, tag_data):
        if not tag_data:
            return ""
        
        tags_by_type = defaultdict(list)
        for tag_id, tag_info in tag_data.items():
            tag_type = tag_info.get('type', 'unknown')
            tag_name = tag_info.get('name', '')
            if tag_name:
                tags_by_type[tag_type].append(tag_name)
        
        tag_lines = []
        for tag_type, tag_names in tags_by_type.items():
            if tag_names:
                tag_names_str = ', '.join(tag_names)
                tag_lines.append(f"**{tag_type}:** {tag_names_str}")
        
        return "\n".join(tag_lines)
    
    
    def snh(self, search_term, page=1):
        api_url = f"https://nhentai.net/api/v2/search?query={search_term}&page={page}"
        
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                self._rate_limit()
                response = self.session.get(api_url, timeout=30)
                
                if response.status_code != 200:
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
                    return {"error": f"API error: {response.status_code}"}
                
                data = response.json()
                
                results_data = []
                all_tag_ids = set()
                
                for item in data.get('result', []):
                    tag_ids = item.get('tag_ids', [])
                    for tid in tag_ids:
                        all_tag_ids.add(tid)
                    
                    thumbnail_url = f"https://t2.nhentai.net/{item['thumbnail']}" if item.get('thumbnail') else ''
                    
                    results_data.append({
                        'nombre': item.get('english_title', ''),
                        'miniatura': thumbnail_url,
                        'codigo': str(item.get('id', '')),
                        'num_pages': item.get('num_pages', 0),
                        'tag_ids': tag_ids
                    })
                
                tag_data = self._fetch_tags_by_ids(list(all_tag_ids))
                
                for result in results_data:
                    tag_ids = result.pop('tag_ids', [])
                    result['tags'] = self._format_tags_for_display({tid: tag_data[tid] for tid in tag_ids if tid in tag_data})
                
                total = data.get('total', 0)
                num_pages = data.get('num_pages', 0)
                per_page = data.get('per_page', 25)
                
                return {
                    'total_resultados': total,
                    'total_paginas': num_pages,
                    'pagina_actual': page,
                    'termino_busqueda': search_term,
                    'resultados': results_data,
                    'resultados_por_pagina': per_page
                }
                
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (attempt + 1))
                    continue
                return {"error": "Timeout o error de conexión después de múltiples intentos"}
            except json.JSONDecodeError:
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                return {"error": "Error decodificando la respuesta JSON"}
            except Exception as e:
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
            
    def vnh(self, code, quality="hd"):
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                api_url = f"https://nhentai.net/api/v2/galleries/{code}"
                self._rate_limit()
                response = self.session.get(api_url, timeout=30)
                
                if response.status_code != 200:
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
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
                tag_ids = []
                if 'tags' in data:
                    for tag in data['tags']:
                        tag_type = tag.get('type', 'unknown')
                        tag_name = tag.get('name', '')
                        tag_id = tag.get('id')
                        if tag_id:
                            tag_ids.append(tag_id)
                        if tag_type not in tags_dict:
                            tags_dict[tag_type] = []
                        tags_dict[tag_type].append(tag_name)
                
                image_links = []
                cover_image = ""
                
                if 'pages' in data and data['pages']:
                    for page in data['pages']:
                        page_path = page.get('path', '')
                        if page_path:
                            if quality == "thumb":
                                page_path = page_path.replace('.', 't.')
                                image_link = f"https://t2.nhentai.net/{page_path}"
                            else:
                                image_link = f"https://i2.nhentai.net/{page_path}"
                            image_links.append(image_link)
                    
                    if image_links:
                        cover_image = image_links[0]
                else:
                    media_id = data.get('media_id', '')
                    num_pages = data.get('num_pages', 0)
                    
                    if media_id and num_pages > 0:
                        for page_num in range(1, num_pages + 1):
                            if quality == "thumb":
                                image_link = f"https://t2.nhentai.net/galleries/{media_id}/{page_num}t.jpg"
                            else:
                                image_link = f"https://i2.nhentai.net/galleries/{media_id}/{page_num}.jpg"
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
                
            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (attempt + 1))
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
            except json.JSONDecodeError as e:
                return {
                    'title': '',
                    'code': int(code) if str(code).isdigit() else 0,
                    'cover_image': '',
                    'tags': {},
                    'image_links': [],
                    'success': False,
                    'error': f"JSON decode error: {str(e)}"
                }
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (attempt + 1))
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

    def hito(self, g, p=1):
        try:
            if not self._create_driver():
                return {
                    "title": "",
                    "actual_page": str(p),
                    "total_pages": "0",
                    "img": "",
                    "error": "No se pudo crear el driver"
                }
            
            url = f"https://hitomi.la/reader/{g}.html#{p}"
            self.driver.get(url)
            
            min_sleep = 0.5
            max_sleep = 1.0
            while True:
                time.sleep(random.uniform(min_sleep, max_sleep))
                
                screenshot = self.driver.get_screenshot_as_png()
                img = Image.open(io.BytesIO(screenshot))
                
                img_crop = img.crop((0, 41, img.size[0], img.size[1]))
                img_array = img_crop.load()
                
                is_all_dark = True
                for x in range(img_crop.size[0]):
                    for y in range(img_crop.size[1]):
                        color = img_array[x, y]
                        if isinstance(color, tuple) and len(color) >= 3:
                            if not (abs(color[0] - 0x17) <= 5 and abs(color[1] - 0x17) <= 5 and abs(color[2] - 0x17) <= 5):
                                is_all_dark = False
                                break
                    if not is_all_dark:
                        break
                
                if not is_all_dark:
                    break
                
                min_sleep += 0.5
                max_sleep += 0.5
            
            width, height = img.size
            img_crop = img.crop((0, 41, width, height))
            img_array = img_crop.load()
            new_width, new_height = img_crop.size
            
            left_crop = 0
            right_crop = new_width
            bottom_crop = new_height
            
            for x in range(new_width):
                color = img_array[x, 0]
                if isinstance(color, tuple) and len(color) >= 3:
                    if abs(color[0] - 0x17) <= 5 and abs(color[1] - 0x17) <= 5 and abs(color[2] - 0x17) <= 5:
                        left_crop = x + 1
                    else:
                        break
            
            for x in range(new_width - 1, -1, -1):
                color = img_array[x, 0]
                if isinstance(color, tuple) and len(color) >= 3:
                    if abs(color[0] - 0x17) <= 5 and abs(color[1] - 0x17) <= 5 and abs(color[2] - 0x17) <= 5:
                        right_crop = x
                    else:
                        break
            
            for y in range(new_height - 1, -1, -1):
                color = img_array[new_width // 2, y]
                if isinstance(color, tuple) and len(color) >= 3:
                    if abs(color[0] - 0x17) <= 5 and abs(color[1] - 0x17) <= 5 and abs(color[2] - 0x17) <= 5:
                        bottom_crop = y
                    else:
                        break
            
            if left_crop < right_crop and bottom_crop > 0:
                final_img = img_crop.crop((left_crop, 0, right_crop, bottom_crop))
            else:
                final_img = img_crop
            
            buffered = io.BytesIO()
            final_img.save(buffered, format="PNG")
            img_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
            
            page_source = self.driver.page_source
            soup = BeautifulSoup(page_source, 'html.parser')
            
            title = soup.find('title').text if soup.find('title') else ""
            
            total_pages = 0
            select_element = soup.find('select', {'id': 'single-page-select'})
            if select_element:
                options = select_element.find_all('option')
                if options:
                    last_option = options[-1]
                    total_pages = int(last_option.get('value', 0))
            
            return {
                "title": title,
                "actual_page": str(p),
                "total_pages": str(total_pages),
                "img": img_base64
            }
            
        except Exception as e:
            return {
                "title": "",
                "actual_page": str(p),
                "total_pages": "0",
                "img": "",
                "error": str(e)
            }
        finally:
            if self.driver:
                try:
                    self.driver.quit()
                    self.driver = None
                except:
                    pass
    
    def __del__(self):
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass

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
        self.naki_api = NakiBotAPI()
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
                await self._start_torrent_download(callback_query.message, result, user_id)
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

        elif text.startswith("/snh ") or text.startswith("/s3h "):
            parts = text.split(maxsplit=1)
            if len(parts) < 2:
                await safe_call(message.reply_text, "Usa: `/snh búsqueda -p página` o `/s3h búsqueda -p página`\nEjemplos: `/snh yuri -p 2` o `/snh yuri -p 2,3` o `/snh yuri -p 2-4`")
                return
            
            full_search = parts[1]
            search_term = full_search
            pages = [1]
            
            if " -p " in full_search:
                parts_search = full_search.split(" -p ")
                search_term = parts_search[0]
                page_param = parts_search[1].strip()
                
                if "," in page_param:
                    pages = [int(p.strip()) for p in page_param.split(",")]
                elif "-" in page_param:
                    start_end = page_param.split("-")
                    if len(start_end) == 2:
                        start = int(start_end[0].strip())
                        end = int(start_end[1].strip())
                        pages = list(range(start, end + 1))
                else:
                    pages = [int(page_param)]
            
            if text.startswith("/snh "):
                for page in pages:
                    result = self.naki_api.snh(search_term, page)
                    await self._process_search_json(message, result, user_id)
                    if len(pages) > 1 and page != pages[-1]:
                        await safe_call(message.reply_text, f"📄 Mostrando página {page} de {len(pages)}")
            else:
                for page in pages:
                    result = self.neko.s3h(search_term, page)
                    await self._process_search_json(message, result, user_id)
                    if len(pages) > 1 and page != pages[-1]:
                        await safe_call(message.reply_text, f"📄 Mostrando página {page} de {len(pages)}")

        elif text.startswith("/nh ") or text.startswith("/3h "):
            parts = text.split()
            if len(parts) < 2:
                await safe_call(message.reply_text, "Usa: `/nh codigo1 codigo2 codigo3` o `/3h https://3hentai.net/d/12345`\nOpciones: `-p 5` `-s 2` `-f 4`")
                return
            
            command = parts[0]
            raw_inputs = parts[1:]
            
            codes = []
            for inp in raw_inputs:
                if inp.startswith("-"):
                    break
                if "nhentai.net/g/" in inp:
                    match = re.search(r'/g/(\d+)', inp)
                    if match:
                        codes.append(match.group(1))
                elif "3hentai.net/d/" in inp or "es.3hentai.net/d/" in inp:
                    match = re.search(r'/d/(\d+)', inp)
                    if match:
                        codes.append(match.group(1))
                else:
                    codes.append(inp)
            
            if not codes:
                await safe_call(message.reply_text, "No se encontraron códigos válidos")
                return
            
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
            quality_choice = user_nh_quality.get(user_id, "hd")
            
            for code in codes:
                if command == "/nh":
                    result = self.naki_api.vnh(code, quality_choice)
                else:
                    result = self.neko.v3h(code)
                
                if "error" in result:
                    await safe_call(message.reply_text, f"Error con código {code}: {result['error']}")
                    continue
                
                if single_page:
                    images = result.get("image_links", [])
                    if images and 0 < single_page <= len(images):
                        selected_url = images[single_page-1]
                        temp_path = await self._prepare_image_for_telegram(selected_url)
                        if temp_path:
                            await safe_call(message.reply_photo, temp_path, caption=f"Código: {code} - Página {single_page}/{len(images)}")
                            os.remove(temp_path)
                        else:
                            await safe_call(message.reply_text, f"Código {code}: Error descargando página {single_page}")
                    else:
                        await safe_call(message.reply_text, f"Código {code}: Página {single_page} no encontrada")
                elif format_choice == "raw":
                    await self._process_gallery_json_with_range(message, result, code, format_choice, start_page, end_page, user_id)
                else:
                    await self._process_gallery_with_format(message, result, code, format_choice, start_page, end_page, user_id)
                
                if len(codes) > 1 and code != codes[-1]:
                    await safe_call(message.reply_text, f"✅ Procesado {code}, continuando...")

        if text.startswith("/listfiles") or text.startswith("/ls"):
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
                    await self._send_document_with_progress(message.chat.id, archivo, f"🎬 {os.path.basename(archivo)}", user_id=user_id)
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
                    await self._send_document_with_progress(message.chat.id, archivo, f"🎵 {os.path.basename(archivo)}", user_id=user_id)
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

        elif text.startswith("/mp3"):
            if message.reply_to_message:
                reply = message.reply_to_message
                video_file = None
                
                if reply.video:
                    video_file = reply.video
                elif reply.document and reply.document.mime_type and reply.document.mime_type.startswith("video/"):
                    video_file = reply.document
                else:
                    await safe_call(message.reply_text, "❌ Responde a un video o archivo de video con /mp3")
                    return
                
                parts = text.split(maxsplit=1)
                metadata = {}
                custom_filename = None
                
                if len(parts) > 1:
                    args = parts[1]
                    if "-f" in args:
                        match = re.search(r'-f "([^"]+)"', args)
                        if match:
                            custom_filename = match.group(1)
                    if "-n" in args:
                        match = re.search(r'-n "([^"]+)"', args)
                        if match:
                            metadata['title'] = match.group(1)
                    if "-a" in args:
                        match = re.search(r'-a "([^"]+)"', args)
                        if match:
                            metadata['artist'] = match.group(1)
                    if "-A" in args:
                        match = re.search(r'-A "([^"]+)"', args)
                        if match:
                            metadata['album'] = match.group(1)
                    if "-y" in args:
                        match = re.search(r'-y "(\d{4})"', args)
                        if match:
                            metadata['year'] = match.group(1)
                    if "-c" in args:
                        match = re.search(r'-c "([^"]+)"', args)
                        if match:
                            metadata['cover'] = match.group(1)
                
                progress_msg = await safe_call(message.reply_text, "📥 Descargando video...")
                
                temp_video = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
                temp_video_path = temp_video.name
                temp_video.close()
                
                await self.app.download_media(video_file, file_name=temp_video_path)
                
                await safe_call(progress_msg.edit_text, "🎵 Convirtiendo a MP3...")
                
                if custom_filename:
                    temp_audio = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3", prefix=custom_filename)
                else:
                    temp_audio = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
                temp_audio_path = temp_audio.name
                temp_audio.close()
                
                try:
                    output_path = await convert_video_to_mp3(temp_video_path, temp_audio_path, metadata)
                    
                    await safe_call(progress_msg.edit_text, "📤 Enviando audio...")
                    
                    await safe_call(
                        message.reply_audio,
                        audio=output_path,
                        caption="🎵 Audio convertido desde video"
                    )
                    
                    await safe_call(progress_msg.delete)
                    
                except Exception as e:
                    await safe_call(progress_msg.edit_text, f"❌ Error: {str(e)}")
                finally:
                    if os.path.exists(temp_video_path):
                        os.remove(temp_video_path)
                    if os.path.exists(temp_audio_path):
                        os.remove(temp_audio_path)
            else:
                await safe_call(message.reply_text, "❌ Responde a un video o archivo de video con /mp3")
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
                    caption=f"📄 {selected_item}",
                    user_id=user_id
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
                await safe_call(message.reply_text, f"📚 Formato actual de manga: **{current.upper()}**\nUsa: `/mangafile cbz` o `/mangafile pdf` o `/mangafile zip`")
                return
            format_option = parts[1].lower()
            if format_option not in ["cbz", "pdf", "zip"]:
                await safe_call(message.reply_text, "❌ Formato inválido. Usa: cbz, pdf o zip")
                return
            if user_id not in user_manga_settings:
                user_manga_settings[user_id] = {}
            user_manga_settings[user_id]["format"] = format_option
            await safe_call(message.reply_text, f"✅ Formato de manga configurado a: **{format_option.upper()}**")
            return

        elif text.startswith("/mangadllang"):
            parts = text.split(maxsplit=1)
            if len(parts) < 2:
                current = user_manga_settings.get(user_id, {}).get("language", "en")
                await safe_call(message.reply_text, f"🌐 Idioma actual: **{current}**\nUsa: `/mangadllang en` o `/mangadllang es`")
                return
            lang_option = parts[1].lower()
            if lang_option not in ["en", "es"]:
                await safe_call(message.reply_text, "❌ Idioma inválido. Usa: en o es")
                return
            if user_id not in user_manga_settings:
                user_manga_settings[user_id] = {}
            user_manga_settings[user_id]["language"] = lang_option
            await safe_call(message.reply_text, f"✅ Idioma de manga configurado a: **{lang_option}**")
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
            user_lang = user_manga_settings.get(user_id, {}).get("language", "en")
            await self._process_manga_download(
                message, manga_id, user_mode, user_format, user_quality, user_lang,
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
            quality_choice = user_nh_quality.get(user_id, "hd")
            if command == "/nh":
                result = self.naki_api.vnh(code, quality_choice)
            else:
                result = self.neko.v3h(code)
            if single_page:
                images = result.get("image_links", [])
                if images and 0 < single_page <= len(images):
                    selected_url = images[single_page-1]
                    temp_path = await self._prepare_image_for_telegram(selected_url)
                    if temp_path:
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
    
    async def _process_manga_download(self, message, manga_id, mode, format_choice, quality_choice, language, start_chapter, start_volume, end_chapter, end_volume, user_id):
        try:
            progress_msg = await safe_call(message.reply_text, f"📚 Obteniendo información para manga {manga_id}...")
            try:
                feed_json = self.mangadex.feed(manga_id, language=language)
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
                    await self._download_manga_by_volumes(progress_msg, manga_id, feed_data, covers_dict, format_choice, start_chapter, start_volume, end_chapter, end_volume, user_id)
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
                        await self._send_document_with_progress(progress_msg.chat.id, cbz_path, f"📚 {volume_name}", thumb=thumbnail_path, user_id=user_id)
                elif format_choice == "pdf" and all_volume_images:
                    pdf_path = await self._create_pdf_from_images(volume_name, all_volume_images, user_id)
                    if pdf_path:
                        await self._send_document_with_progress(progress_msg.chat.id, pdf_path, f"📚 {volume_name}", thumb=thumbnail_path, user_id=user_id)
                elif format_choice == "zip" and all_volume_images:
                    zip_path = self.neko.create_zip(volume_name, all_volume_images)
                    if zip_path:
                        await self._send_document_with_progress(progress_msg.chat.id, zip_path, f"📚 {volume_name}", thumb=thumbnail_path, user_id=user_id)
                else:
                    await safe_call(progress_msg.edit_text, f"✅ Volumen {volume} guardado en vault: {vault_dir}")
                if thumbnail_path and os.path.exists(thumbnail_path):
                    try:
                        os.remove(thumbnail_path)
                    except:
                        pass
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
                            await self._send_document_with_progress(progress_msg.chat.id, cbz_path, f"📖 Capítulo {chapter_num}", thumb=thumbnail_path, user_id=user_id)
                    elif format_choice == "pdf" and chapter_images:
                        pdf_path = await self._create_pdf_from_images(f"Capítulo {chapter_num}", chapter_images, user_id)
                        if pdf_path:
                            await self._send_document_with_progress(progress_msg.chat.id, pdf_path, f"📖 Capítulo {chapter_num}", thumb=thumbnail_path, user_id=user_id)
                    elif format_choice == "zip" and chapter_images:
                        zip_path = self.neko.create_zip(f"Capítulo {chapter_num}", chapter_images)
                        if zip_path:
                            await self._send_document_with_progress(progress_msg.chat.id, zip_path, f"📖 Capítulo {chapter_num}", thumb=thumbnail_path, user_id=user_id)
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
            with zipfile.ZipFile(cbz_path, 'w', zipfile.ZIP_LZMA) as cbz:
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
        if downloaded_images:
            thumb_path = await self._convert_to_thumbnail(downloaded_images[0])
            if format_choice == "cbz":
                cbz_path = await self._create_cbz_from_images(titulo, downloaded_images, user_id)
                if cbz_path:
                    await self._send_document_with_progress(message.chat.id, cbz_path, f"📖 {titulo}", thumb=thumb_path, user_id=user_id)
            elif format_choice == "pdf":
                pdf_path = await self._create_pdf_from_images(titulo, downloaded_images, user_id)
                if pdf_path:
                    await self._send_document_with_progress(message.chat.id, pdf_path, f"📖 {titulo}", thumb=thumb_path, user_id=user_id)
            elif format_choice == "zip":
                zip_path = self.neko.create_zip(titulo, downloaded_images)
                if zip_path:
                    await self._send_document_with_progress(message.chat.id, zip_path, f"📖 {titulo}", thumb=thumb_path, user_id=user_id)
            if thumb_path:
                os.remove(thumb_path)
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
    
    async def _prepare_image_for_telegram(self, url):
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
                print(f"Error preparando imagen: {e}")
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
                prepared_image = await self._convert_to_thumbnail(first_image_path)
                await safe_call(message.reply_photo, prepared_image, caption=caption)
                if prepared_image:
                    os.remove(prepared_image)
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
        if downloaded_images:
            thumb_path = await self._convert_to_thumbnail(downloaded_images[0])
            caption = f"**{nombre}**\nCódigo: `{code}`\nRango: {start_page}-{end_page} de {total_images}\n\n{self._format_tags(tags)}"
            if format_choice == "cbz":
                cbz_path = await self._create_cbz_from_images(f"{nombre} - {code}", downloaded_images, user_id)
                if cbz_path:
                    await safe_call(message.reply_photo, photo=thumb_path, reply_to_message_id=message.id, caption=caption)
                    await self._send_document_with_progress(message.chat.id, cbz_path, thumb=thumb_path, reply_to_message_id=message.id, user_id=user_id)
            elif format_choice == "pdf":
                pdf_path = await self._create_pdf_from_images(f"{nombre} - {code}", downloaded_images, user_id)
                if pdf_path:
                    await safe_call(message.reply_photo, photo=thumb_path, reply_to_message_id=message.id, caption=caption)
                    await self._send_document_with_progress(message.chat.id, pdf_path, thumb=thumb_path, reply_to_message_id=message.id, user_id=user_id)
            elif format_choice == "zip":
                zip_path = self.neko.create_zip(f"{nombre} - {code}", downloaded_images)
                if zip_path:
                    await safe_call(message.reply_photo, photo=thumb_path, reply_to_message_id=message.id, caption=caption)
                    await self._send_document_with_progress(message.chat.id, zip_path, thumb=thumb_path, reply_to_message_id=message.id, user_id=user_id)
            if thumb_path:
                os.remove(thumb_path)
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
        
        total_resultados = result.get("total_resultados", 0)
        total_paginas = result.get("total_paginas", 0)
        pagina_actual = result.get("pagina_actual", 1)
        termino = result.get("termino_busqueda", "")
        resultados = result.get("resultados", [])
        
        info_text = f"🔍 **Búsqueda:** {termino}\n"
        info_text += f"📊 **Resultados:** {total_resultados}\n"
        info_text += f"📄 **Páginas:** {pagina_actual}/{total_paginas}\n\n"
        
        await safe_call(message.reply_text, info_text)
        
        if not resultados:
            await safe_call(message.reply_text, "No se encontraron resultados")
            return
        
        for item in resultados:
            code = item.get("codigo", "")
            nombre = item.get("nombre", "Sin titulo")
            miniatura = item.get("miniatura", "")
            num_pages = item.get("num_pages", 0)
            tags = item.get("tags", "")
            
            if miniatura.startswith("//"):
                miniatura = f"https:{miniatura}"
            
            caption = f"**{nombre}**\n📖 Código: `{code}`\n📄 Páginas: {num_pages}"
            if tags:
                caption += f"\n\n🏷️ **Tags:**\n{tags}"
            caption += f"\n\n📥 Usa `/nh {code}` para descargar"
            
            if miniatura:
                temp_path = await self._prepare_image_for_telegram(miniatura)
                if temp_path:
                    await safe_call(message.reply_photo, temp_path, caption=caption)
                    os.remove(temp_path)
                else:
                    await safe_call(message.reply_text, caption)
            else:
                await safe_call(message.reply_text, caption)
            
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
        compress_7z = "-7" in message.text
        compress_zip = "-z" in message.text.lower()
        if message.reply_to_message:
            reply = message.reply_to_message
            if reply.document and reply.document.file_size <= 5 * 1024 * 1024:
                await self._process_torrent_file(message, reply.document, compress_7z, compress_zip)
                return
            elif reply.text:
                await self._process_torrent_text(message, reply.text, compress_7z, compress_zip)
                return
            else:
                await safe_call(message.reply_text, "❌ Responde a un mensaje con texto o archivo .torrent (<5MB)")
                return
        parts = message.text.split()
        torrent_input = None
        if len(parts) > 1:
            filtered_parts = [p for p in parts[1:] if p != "-7" and p.lower() != "-z"]
            if filtered_parts:
                torrent_input = filtered_parts[0].strip()
        if torrent_input:
            await self._process_torrent_text(message, torrent_input, compress_7z, compress_zip)
        else:
            await safe_call(message.reply_text, "❌ Usa: `/leech magnet:...` o `/leech http://...torrent` o responde a un archivo\nUsa `/leech -7` para comprimir en 7z\nUsa `/leech -z` para comprimir en zip")
    
    async def _process_torrent_file(self, message, document, compress_7z=False, compress_zip=False):
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
        await self._start_torrent_download(message, {"magnet": magnet}, message.from_user.id, compress_7z, compress_zip)
    
    async def _process_torrent_text(self, message, text, compress_7z=False, compress_zip=False):
        text = text.strip()
        if text.startswith("magnet:?"):
            magnet = text
            await self._start_torrent_download(message, {"magnet": magnet}, message.from_user.id, compress_7z, compress_zip)
            return
        elif text.endswith(".torrent"):
            if text.startswith("http://") or text.startswith("https://"):
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(text) as response:
                            if response.status == 200:
                                torrent_data = await response.read()
                                magnet = self._torrent_to_magnet(torrent_data)
                                await self._start_torrent_download(message, {"magnet": magnet}, message.from_user.id, compress_7z, compress_zip)
                            else:
                                await safe_call(message.reply_text, f"❌ Error al descargar")
                except Exception as e:
                    await safe_call(message.reply_text, f"❌ Error")
            else:
                if os.path.exists(text):
                    with open(text, "rb") as f:
                        torrent_data = f.read()
                    magnet = self._torrent_to_magnet(torrent_data)
                    await self._start_torrent_download(message, {"magnet": magnet}, message.from_user.id, compress_7z, compress_zip)
                else:
                    await safe_call(message.reply_text, "❌ Archivo no encontrado")
        else:
            await safe_call(message.reply_text, "❌ Enlace no válido")
    
    async def _start_torrent_download(self, message, result, user_id, compress_7z=False, compress_zip=False):
        magnet = result.get("magnet", "")
        if not magnet:
            return
        download_path = os.path.join(os.getcwd(), "vault", str(user_id), "torrents")
        os.makedirs(download_path, exist_ok=True)
        status_msg = await safe_call(message.reply_text, "⏳ Iniciando descarga torrent..." + (" (comprimirá en 7z antes de enviar)" if compress_7z else " (comprimirá en zip antes de enviar)" if compress_zip else ""))
        try:
            download_generator = self.neko.download_magnet(magnet, download_path)
            final_path = None
            last_progress = ""
            last_update_time = time.time()
            async for progress_text in download_generator:
                if progress_text.startswith("📥"):
                    current_time = time.time()
                    if progress_text != last_progress and current_time - last_update_time >= 10:
                        await safe_call(status_msg.edit_text, progress_text + (" (comprimirá al finalizar)" if compress_7z or compress_zip else ""))
                        last_progress = progress_text
                        last_update_time = current_time
                elif progress_text.startswith("✅") and "COMPLETADO" in progress_text:
                    continue
                else:
                    if os.path.exists(progress_text):
                        final_path = progress_text
            if final_path and os.path.exists(final_path):
                try:
                    await status_msg.delete()
                except:
                    pass
                if compress_7z:
                    await safe_call(message.reply_text, "🗜️ Comprimiendo en 7z...")
                    global premium_enabled
                    if premium_enabled:
                        target_size = premium_limit
                    else:
                        target_size = normal_limit
                    parts = self.neko.compress_to_7z(final_path, target_size)
                    if parts:
                        for part in parts:
                            await self._send_document_with_progress(
                                message.chat.id,
                                part,
                                caption=f"🗜️ {os.path.basename(part)}",
                                user_id=user_id
                            )
                    else:
                        await safe_call(message.reply_text, "❌ Error al comprimir en 7z, enviando archivos sin comprimir...")
                        await self._send_files_normally(message, final_path, user_id)
                elif compress_zip:
                    await safe_call(message.reply_text, "🗜️ Comprimiendo en zip...")
                    zip_path = await self._create_zip_from_path(final_path)
                    if zip_path and os.path.exists(zip_path):
                        await self._send_document_with_progress(
                            message.chat.id,
                            zip_path,
                            caption=f"🗜️ {os.path.basename(zip_path)}",
                            user_id=user_id
                        )
                        try:
                            os.remove(zip_path)
                        except:
                            pass
                    else:
                        await safe_call(message.reply_text, "❌ Error al comprimir en zip, enviando archivos sin comprimir...")
                        await self._send_files_normally(message, final_path, user_id)
                else:
                    await self._send_files_normally(message, final_path, user_id)
                
                download_base = os.path.dirname(download_path)
                if os.path.exists(download_base):
                    shutil.rmtree(download_base, ignore_errors=True)
            else:
                try:
                    await status_msg.delete()
                except:
                    pass
                await safe_call(message.reply_text, "✅ Descarga completada pero no se encontraron archivos para enviar")
        except Exception as e:
            try:
                await status_msg.delete()
            except:
                pass
            await safe_call(message.reply_text, f"❌ Error en la descarga torrent: {str(e)}")
    
    async def _create_zip_from_path(self, path):
        try:
            if os.path.isfile(path):
                zip_name = os.path.splitext(os.path.basename(path))[0] + ".zip"
                zip_path = os.path.join(os.path.dirname(path), zip_name)
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_LZMA) as zipf:
                    zipf.write(path, os.path.basename(path))
                os.remove(path)
                return zip_path
            elif os.path.isdir(path):
                zip_name = os.path.basename(os.path.normpath(path)) + ".zip"
                zip_path = os.path.join(os.path.dirname(path), zip_name)
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_LZMA) as zipf:
                    for root, dirs, files in os.walk(path):
                        for file in files:
                            file_path = os.path.join(root, file)
                            arcname = os.path.relpath(file_path, os.path.dirname(path))
                            zipf.write(file_path, arcname)
                shutil.rmtree(path, ignore_errors=True)
                return zip_path
            return None
        except Exception as e:
            print(f"Error creando zip: {e}")
            return None
    
    async def _send_files_normally(self, message, final_path, user_id):
        if os.path.isfile(final_path):
            await self._send_document_with_progress(
                message.chat.id,
                final_path,
                caption=f"✅ {os.path.basename(final_path)}",
                user_id=user_id
            )
        elif os.path.isdir(final_path):
            for root, dirs, files in os.walk(final_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    try:
                        await self._send_document_with_progress(
                            message.chat.id,
                            file_path,
                            caption=f"✅ {os.path.basename(file_path)}",
                            user_id=user_id
                        )
                        await asyncio.sleep(0.5)
                    except Exception as e:
                        print(f"Error enviando archivo {file_path}: {e}")
    
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
                        caption=f"✅ {os.path.basename(single_item)}",
                        user_id=message.from_user.id
                    )
                elif os.path.isdir(single_item):
                    global premium_enabled
                    if premium_enabled:
                        parts = self.neko.compress_to_7z(single_item, 3995)
                    else:
                        parts = self.neko.compress_to_7z(single_item, 1995)
                    if parts:
                        for part in parts:
                            await self._send_document_with_progress(
                                message.chat.id,
                                part,
                                f"✅ {os.path.basename(part)}",
                                user_id=message.from_user.id
                            )
                    else:
                        await safe_call(status_msg.edit_text, "❌ Error al comprimir carpeta")
                else:
                    await safe_call(status_msg.edit_text, "❌ Tipo de archivo no soportado")
            else:
                if premium_enabled:
                    parts = self.neko.compress_to_7z(download_path, 3995)
                else:
                    parts = self.neko.compress_to_7z(download_path, 1995)
                if parts:
                    for part in parts:
                        await self._send_document_with_progress(
                            message.chat.id,
                            part,
                            f"✅ {os.path.basename(part)}",
                            user_id=message.from_user.id
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
