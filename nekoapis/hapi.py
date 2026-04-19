import requests
from bs4 import BeautifulSoup
import re
import math
import time
import random
import json
import base64
import io
import os
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from PIL import Image

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
    
    def _create_driver(self):
        try:
            chrome_options = Options()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--window-size=1920,1080')
            chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option('useAutomationExtension', False)
            
            self.driver = webdriver.Chrome(options=chrome_options)
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            return True
        except Exception as e:
            try:
                base_dir = Path(__file__).parent.absolute()
                selenium_dir = base_dir / "selenium"
                
                chrome_path = selenium_dir / "chrome"
                chromedriver_path = selenium_dir / "chromedriver"
                
                if chrome_path.exists():
                    chrome_options.binary_location = str(chrome_path)
                
                if chromedriver_path.exists():
                    service = Service(executable_path=str(chromedriver_path))
                    self.driver = webdriver.Chrome(service=service, options=chrome_options)
                else:
                    self.driver = webdriver.Chrome(options=chrome_options)
                
                self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
                return True
            except Exception as e2:
                return False
    
    def snh(self, search_term, page=1):
        url = f"https://nhentai.net/search/?q={search_term}&page={page}"
        
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                response = self.session.get(url, timeout=30)
                
                if response.status_code != 200:
                    time.sleep(retry_delay)
                    continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                
                results_data = []
                
                h1_element = soup.find('h1')
                total_results = 0
                if h1_element:
                    text = h1_element.get_text(strip=True)
                    match = re.search(r'([\d,]+)\s+results', text)
                    if match:
                        total_results = int(match.group(1).replace(',', ''))
                
                total_pages = math.ceil(total_results / 25)
                
                gallery_divs = soup.find_all('div', class_='gallery')
                
                for gallery in gallery_divs[:25]:
                    link_element = gallery.find('a', class_='cover')
                    if not link_element:
                        continue
                    
                    href = link_element.get('href', '')
                    code = ''
                    if href and '/g/' in href:
                        code_match = re.search(r'/g/(\d+)/', href)
                        if code_match:
                            code = code_match.group(1)
                    
                    img_element = gallery.find('img', class_='lazyload')
                    thumbnail = ''
                    if img_element:
                        thumbnail = img_element.get('data-src', '')
                        if not thumbnail:
                            thumbnail = img_element.get('src', '')
                    
                    caption_div = gallery.find('div', class_='caption')
                    name = caption_div.get_text(strip=True) if caption_div else ''
                    
                    results_data.append({
                        'nombre': name,
                        'miniatura': thumbnail,
                        'codigo': code
                    })
                
                return {
                    'total_resultados': total_results,
                    'total_paginas': total_pages,
                    'pagina_actual': page,
                    'termino_busqueda': search_term,
                    'resultados': results_data
                }
                
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (attempt + 1))
                    continue
                return {"error": "Timeout o error de conexión después de múltiples intentos"}
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
                
                media_id = data.get('media_id', '')
                num_pages = data.get('num_pages', 0)
                
                image_links = []
                if media_id and num_pages > 0:
                    for page_num in range(1, num_pages + 1):
                        if quality == "thumb":
                            image_link = f"https://t2.nhentai.net/galleries/{media_id}/{page_num}t.webp"
                        else:
                            image_link = f"https://i2.nhentai.net/galleries/{media_id}/{page_num}.webp"
                        image_links.append(image_link)
                
                cover_image = ""
                if data.get('cover', {}).get('path'):
                    if quality == "thumb":
                        cover_path = data['cover']['path'].replace('cover.webp', 'thumb.webp')
                        cover_image = f"https://t2.nhentai.net/{cover_path}"
                    else:
                        cover_image = f"https://i2.nhentai.net/{data['cover']['path']}"
                
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
                        full_img_url = re.sub(r't(?=\.\w{3,4}$)', '', src_url)
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
