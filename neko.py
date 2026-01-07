import nekoapis.hapi
import nekoapis.mangadex_api
import os
import zipfile
import requests
import tempfile
import shutil
from PIL import Image
from io import BytesIO
import json

class Neko:
    def __init__(self):
        self.hapi = nekoapis.hapi.NakiBotAPI()
        self.mangadex = nekoapis.mangadex_api.MangaDexApi()
    
    def clean_name(self, name):
        if not name:
            return "unnamed"
        
        prohibited_chars = '<>:"/\\|?*'
        cleaned = ''.join(c for c in name if c not in prohibited_chars)
        
        cleaned = cleaned.strip()
        while cleaned.endswith('.'):
            cleaned = cleaned[:-1].strip()
        
        if len(cleaned) > 248:
            cleaned = cleaned[:248]
        
        reserved_names = ['CON', 'PRN', 'AUX', 'NUL', 
                         'COM1', 'COM2', 'COM3', 'COM4', 'COM5',
                         'COM6', 'COM7', 'COM8', 'COM9',
                         'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5',
                         'LPT6', 'LPT7', 'LPT8', 'LPT9']
        
        if cleaned.upper() in reserved_names:
            cleaned = '_' + cleaned
        
        if not cleaned:
            cleaned = "unnamed"
        
        return cleaned
    
    def snh(self, search_term, page=1):
        result = self.hapi.snh(search_term, page)
        if "error" in result:
            return result
        
        if isinstance(result, list):
            return [{"code": str(item)} for item in result]
        
        return result
    
    def s3h(self, search_term, page=1):
        result = self.hapi.s3h(search_term, page)
        if "error" in result:
            return result
        
        if isinstance(result, list):
            return [{"code": str(item)} for item in result]
        
        return result
    
    def vnh(self, code):
        return self.hapi.vnh(code)
    
    def v3h(self, code):
        return self.hapi.v3h(code)

    def hito(self, g, p=1):
        result = self.hapi.hito(g, p)
        if "error" in result:
            return result
        
        return result
    
    def download(self, url, save_path):
        try:
            response = requests.get(url, stream=True, timeout=30)
            if response.status_code == 200:
                with open(save_path, 'wb') as f:
                    for chunk in response.iter_content(1024):
                        f.write(chunk)
                return True
            return False
        except Exception:
            return False
    
    def convert_to_png(self, file):
        try:
            img = Image.open(file.stream).convert("RGB")
            filename = os.path.splitext(file.filename)[0] + ".png"
            save_path = os.path.join(os.getcwd(), "vault", filename)
            img.save(save_path, "PNG")
            return filename
        except Exception:
            return None
    
    def create_cbz(self, nombre, lista):
        try:
            safe_nombre = self.clean_name(nombre)
            temp_dir = tempfile.mkdtemp()
            
            for i, item in enumerate(lista):
                if item.startswith('http'):
                    file_path = os.path.join(temp_dir, f"{i:04d}.jpg")
                    if not self.download(item, file_path):
                        return None
                else:
                    if os.path.exists(item):
                        file_path = os.path.join(temp_dir, f"{i:04d}.jpg")
                        shutil.copy2(item, file_path)
                    else:
                        return None
            
            cbz_path = os.path.join(os.getcwd(), "vault", f"{safe_nombre}.cbz")
            with zipfile.ZipFile(cbz_path, 'w', zipfile.ZIP_DEFLATED) as cbz:
                for file in sorted(os.listdir(temp_dir)):
                    cbz.write(os.path.join(temp_dir, file), file)
            
            shutil.rmtree(temp_dir)
            return cbz_path
        except Exception:
            return None
    
    def create_pdf(self, nombre, lista):
        try:
            safe_nombre = self.clean_name(nombre)
            pdf_path = os.path.join(os.getcwd(), "vault", f"{safe_nombre}.pdf")
            
            images = []
            
            for item in lista:
                try:
                    if item.startswith('http'):
                        response = requests.get(item, timeout=30)
                        if response.status_code == 200:
                            img = Image.open(BytesIO(response.content))
                            img = img.convert("RGB")
                            images.append(img)
                    else:
                        if os.path.exists(item):
                            img = Image.open(item)
                            img = img.convert("RGB")
                            images.append(img)
                except Exception:
                    continue
            
            if images:
                images[0].save(pdf_path, "PDF", save_all=True, append_images=images[1:])
                return pdf_path
            
            return None
        except Exception:
            return None
    
    def buscar_manga(self, termino):
        resultados = self.mangadex.buscar_manga(termino)
        
        for manga in resultados:
            manga_id = manga.get('id', '')
            if manga_id:
                covers = self.mangadex.get_covers(manga_id)
                cover_url = ""
                for cover in covers:
                    if cover['volume'] == '1':
                        cover_url = cover['link']
                        break
                
                if not cover_url and covers:
                    cover_url = covers[0]['link']
                
                manga['cover'] = cover_url
        
        return resultados
    
    def get_covers(self, manga_id):
        return self.mangadex.get_covers(manga_id)
    
    def list_chap(self, manga_id, language='en'):
        all_chapters = self.mangadex.list_chap(manga_id)
        
        filtered_chapters = []
        for chapter in all_chapters:
            if chapter.get('language', '').lower() == language.lower():
                filtered_chapters.append(chapter)
        
        return filtered_chapters
    
    def get_manga_info(self, manga_id, language='en'):
        try:
            chapters = self.list_chap(manga_id, language)
            covers = self.mangadex.get_covers(manga_id)
            
            manga_info = {
                "chapters": chapters,
                "covers": covers,
                "volumes": {}
            }
            
            for chapter in chapters:
                volume = chapter['volume'] if chapter['volume'] else 'sin_volumen'
                if volume not in manga_info["volumes"]:
                    manga_info["volumes"][volume] = []
                manga_info["volumes"][volume].append(chapter)
            
            return manga_info
        except Exception as e:
            print(f"Error en get_manga_info: {e}")
            return None
    
    def download_chapter(self, chapter_id):
        try:
            image_links = self.mangadex.chapter_pics(chapter_id)
            return image_links
        except Exception as e:
            print(f"Error en download_chapter: {e}")
            return []
    
    def download_manga(self, manga_id, idioma='en', cap_inicial=1, volumen_inicial=None, cap_final=None, volumen_final=None):
        try:
            filtered_chapters = self.list_chap(manga_id, idioma)
            
            if not filtered_chapters:
                return json.dumps([{"error": f"No se encontraron capítulos en {idioma}"}], ensure_ascii=False)
            
            def sort_key(val):
                if not val or val == 'sin_volumen':
                    return (float('inf'), '')
                try:
                    return (float(val), '')
                except ValueError:
                    return (float('inf'), val)
            
            filtered_chapters.sort(key=lambda x: sort_key(x['chapter']))
            
            chapters_by_volume = {}
            for chapter in filtered_chapters:
                volume = chapter['volume'] if chapter['volume'] else 'sin_volumen'
                if volume not in chapters_by_volume:
                    chapters_by_volume[volume] = []
                chapters_by_volume[volume].append(chapter)
            
            volumes_order = sorted(chapters_by_volume.keys(), key=lambda x: sort_key(x))
            
            covers = self.mangadex.get_covers(manga_id)
            covers_dict = {cover['volume']: cover['link'] for cover in covers}
            
            result_json = []
            
            default_cover = covers[0]['link'] if covers else ''
            
            for volume in volumes_order:
                if volumen_inicial and volume != 'sin_volumen':
                    if sort_key(volume) < sort_key(str(volumen_inicial)):
                        continue
                
                if volumen_final and volume != 'sin_volumen':
                    if sort_key(volume) > sort_key(str(volumen_final)):
                        break
                
                volume_chapters = chapters_by_volume[volume]
                volume_data = {
                    "no_vol": volume if volume != 'sin_volumen' else "null",
                    "cover": covers_dict.get(volume, default_cover) if volume != 'sin_volumen' else default_cover,
                    "capitulos": []
                }
                
                volume_started = False
                
                for chapter in volume_chapters:
                    chapter_num = chapter['chapter']
                    
                    if sort_key(chapter_num) < sort_key(str(cap_inicial)):
                        continue
                    
                    if cap_final and sort_key(chapter_num) > sort_key(str(cap_final)):
                        break
                    
                    if volumen_final and volume != 'sin_volumen' and sort_key(volume) == sort_key(str(volumen_final)):
                        if sort_key(chapter_num) > sort_key(str(cap_final)):
                            break
                    
                    volume_started = True
                    
                    image_links = self.mangadex.chapter_pics(chapter['id'])
                    if image_links:
                        capitulo_data = {
                            "no_cap": chapter_num,
                            "imágenes": image_links
                        }
                        volume_data["capitulos"].append(capitulo_data)
                
                if volume_started and volume_data["capitulos"]:
                    result_json.append(volume_data)
            
            return json.dumps(result_json, indent=2, ensure_ascii=False)
            
        except Exception as e:
            print(f"Error en download_manga: {e}")
            return json.dumps([])