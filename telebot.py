import os
import asyncio
import sys
import argparse
import tempfile
import time
import aiohttp
import aiofiles
import re
import requests
from concurrent.futures import ThreadPoolExecutor
from pyrogram import Client, filters
from pyrogram.types import Message, BotCommand
from pyrogram.errors import FloodWait
import json
import math
from bs4 import BeautifulSoup
from collections import defaultdict

set_cmd = False

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

class NakiBotAPI:
    def __init__(self):
        self.session = requests.Session()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
        }
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

class NekoTelegram:
    def __init__(self, api_id, api_hash, bot_token):
        self.api_id = api_id
        self.api_hash = api_hash
        self.bot_token = bot_token
        self.naki_api = NakiBotAPI()
        self.app = Client("nekobot", api_id=int(api_id), api_hash=api_hash, bot_token=bot_token)
        self.download_pool = ThreadPoolExecutor(max_workers=20)
        
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
    
    async def lista_cmd(self):
        await self.app.set_bot_commands([
            BotCommand("nh", "Descarga un doujin de nhentai"),
            BotCommand("3h", "Descarga un doujin de 3hentai"),
            BotCommand("snh", "Busca doujins por filtros en nhentai"),
            BotCommand("s3h", "Busca doujins por filtros en 3hentai"),
        ])
        print("Comandos configurados en el bot")

    async def _handle_message(self, client: Client, message: Message):
        if not message.text:
            return
        
        text = message.text.strip()

        if text.startswith("/start"):
            await safe_call(client.send_photo, chat_id=message.chat.id, photo="https://cdn.imgchest.com/files/93cb097b575e.webp", protect_content=True, caption="Nyaa, Hello, I'm Alice. The cute pet of @nakigeplayer")
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
            
            if not all_images:
                await safe_call(message.reply_text, "No hay imagenes")
                return
            
            caption = f"**{nombre}**\nCódigo: `{code}`\nTotal: {len(all_images)} páginas\n\n{self._format_tags(tags)}"
            
            await safe_call(message.reply_text, caption)
            
            for i, img_url in enumerate(all_images, 1):
                temp_path = await self._prepare_image_for_telegram(img_url)
                if temp_path:
                    await safe_call(message.reply_photo, temp_path, caption=f"Página {i}/{len(all_images)}")
                    os.remove(temp_path)
                
                await asyncio.sleep(0.2)

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
            
            total_resultados = result.get("total_resultados", 0)
            total_paginas = result.get("total_paginas", 0)
            pagina_actual = result.get("pagina_actual", 1)
            termino = result.get("termino_busqueda", "")
            resultados = result.get("resultados", [])
            
            info_text = f"🔍 **Búsqueda:** {termino}\n"
            info_text += f"📊 **Resultados:** {total_resultados}\n"
            info_text += f"📄 **Página:** {pagina_actual}/{total_paginas}\n\n"
            
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
    
    async def _prepare_image_for_telegram(self, url):
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        temp_path = temp_file.name
        temp_file.close()
        if await self.async_download(url, temp_path):
            return temp_path
        return None
    
    def _format_tags(self, tags):
        if not tags:
            return ""
        tag_lines = []
        for category, items in tags.items():
            if items:
                items_str = ", ".join(items)
                tag_lines.append(f"**{category.upper()}:** {items_str}")
        return "\n".join(tag_lines)
    
    def run(self):
        print("[INFO] Iniciando bot de Telegram...")
        self.app.run()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-A", "--api", help="API ID de Telegram")
    parser.add_argument("-H", "--hash", help="API Hash de Telegram")
    parser.add_argument("-T", "--token", help="Token del Bot")
    args = parser.parse_args()

    api_id = args.api or os.environ.get("API_ID")
    api_hash = args.hash or os.environ.get("API_HASH")
    bot_token = args.token or os.environ.get("BOT_TOKEN")
    
    if not all([api_id, api_hash, bot_token]):
        print("Error: Faltan credenciales. Usa -A -H -T o variables de entorno.")
        sys.exit(1)
    
    bot = NekoTelegram(api_id, api_hash, bot_token)
    bot.run()

if __name__ == "__main__":
    main()
