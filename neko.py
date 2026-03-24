import nekoapis.hapi
import nekoapis.mangadex_api
import nekoapis.nyaa_api
import os
import json
import datetime
import libtorrent as lt
import asyncio
import threading
import subprocess
import shutil
import tempfile
import zipfile
import requests
import uuid
import aiohttp
import aiofiles
from io import BytesIO
from PIL import Image
from typing import List, Optional

class Neko:
    def __init__(self):
        self.hapi = nekoapis.hapi.NakiBotAPI()
        self.mangadex = nekoapis.mangadex_api.MangaDexApi()
        self.nyaa = nekoapis.nyaa_api.Nyaa_search()
        self.active_downloads = {}
        self.downloads_lock = threading.Lock()

    def compress_to_7z(self, path, target_size=2000):
    if not os.path.exists(path):
        print(f"[ERROR] Path does not exist: {path}")
        return []
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    seven_zip = os.path.join(script_dir, "7zz")
    
    if not os.path.exists(seven_zip):
        seven_zip = shutil.which("7zz")
    if not seven_zip:
        seven_zip = shutil.which("7z")
    if not seven_zip:
        print("[ERROR] 7zip not found")
        return []
    
    try:
        if os.path.isdir(path):
            base_name = os.path.basename(os.path.normpath(path))
            parent_dir = os.path.dirname(os.path.abspath(path))
            output_file = os.path.join(parent_dir, base_name + ".7z")
        else:
            base_name = os.path.splitext(os.path.basename(path))[0]
            output_dir = os.path.dirname(os.path.abspath(path))
            output_file = os.path.join(output_dir, base_name + ".7z")
        
        volume_option = f"-v{target_size}m"
        
        if os.path.isdir(path):
            cmd = [seven_zip, "a", output_file, path, "-mx9", volume_option]
        else:
            cmd = [seven_zip, "a", output_file, path, "-mx9", volume_option]
        
        print(f"[DEBUG] Running: {' '.join(cmd)}")
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        
        if result.returncode != 0:
            print(f"[ERROR] 7zip failed: {result.stderr}")
            return []
        
        parts = []
        part_base = output_file
        part_num = 1
        
        while True:
            part_name = f"{part_base}.{part_num:03d}"
            if os.path.exists(part_name):
                parts.append(part_name)
                part_num += 1
                continue
            
            part_name = f"{part_base}.{part_num:02d}"
            if os.path.exists(part_name):
                parts.append(part_name)
                part_num += 1
                continue
            
            part_name = f"{part_base[:-3]}.{part_num:03d}"
            if os.path.exists(part_name):
                parts.append(part_name)
                part_num += 1
                continue
            
            break
        
        if not parts and os.path.exists(output_file):
            parts.append(output_file)
        
        if parts:
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                os.remove(path)
        
        return parts
        
    except subprocess.TimeoutExpired:
        print("[ERROR] 7zip timeout")
        return []
    except Exception as e:
        print(f"[ERROR] Exception: {e}")
        return []

    def nyaa_fun(self, query):
        return self.nyaa.nyaafun(query)

    def nyaa_fap(self, query):
        return self.nyaa.nyaafap(query)

    def log(self, msg):
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")

    def start_session(self):
        ses = lt.session()
        ses.listen_on(6881, 6891)
        ses.start_dht()
        return ses

    def add_torrent(self, ses, magnet_uri, save_path):
        params = {'save_path': save_path, 'storage_mode': lt.storage_mode_t.storage_mode_sparse}
        handle = lt.add_magnet_uri(ses, magnet_uri, params)
        handle.set_sequential_download(False)
        return handle

    async def wait_for_metadata(self, handle):
        self.log("Descargando metadata...")
        while not handle.has_metadata():
            await asyncio.sleep(1)
        self.log("Metadata obtenida")

    async def monitor_download(self, handle):
        state_str = ['queued', 'checking', 'downloading metadata', 'downloading', 'finished', 'seeding', 'allocating']
        while handle.status().state != lt.torrent_status.seeding:
            s = handle.status()
            self.log(f"{s.progress * 100:.2f}% | ↓ {s.download_rate / 1000:.1f} kB/s | estado: {state_str[s.state]}")
            await asyncio.sleep(5)

    async def download_magnet(self, magnet_link, save_path="."):
        try:
            ses = self.start_session()
            handle = self.add_torrent(ses, magnet_link, save_path)
            await self.wait_for_metadata(handle)
            state_str = ['queued', 'checking', 'downloading metadata', 'downloading', 'finished', 'seeding', 'allocating']
            start_time = datetime.datetime.now()
            while handle.status().state != lt.torrent_status.seeding:
                s = handle.status()
                elapsed = datetime.datetime.now() - start_time
                elapsed_str = str(elapsed).split('.')[0]
                if s.state == lt.torrent_status.downloading:
                    progress = s.progress * 100
                    download_rate = s.download_rate / 1000
                    download_rate_mb = download_rate / 1024
                    current_mb = s.total_done / (1024 * 1024)
                    total_mb = s.total_wanted / (1024 * 1024)
                    bar_length = 20
                    filled_length = int(bar_length * progress / 100)
                    bar = "█" * filled_length + "▒" * (bar_length - filled_length)
                    torrent_name = handle.name() or "Descarga en curso"
                    if len(torrent_name) > 50:
                        torrent_name = torrent_name[:47] + "..."
                    progress_msg = f"📥 Descargando: {torrent_name}\n"
                    progress_msg += f"📊 Progreso: {progress:.2f}%\n"
                    progress_msg += f"📉 [{bar}]\n"
                    progress_msg += f"📦 Tamaño: {current_mb:.2f} MB / {total_mb:.2f} MB\n"
                    progress_msg += f"🚀 Velocidad: {download_rate_mb:.1f} MB/s\n"
                    progress_msg += f"⏱️ Tiempo: {elapsed_str}"
                    yield progress_msg
                await asyncio.sleep(1)
            elapsed = datetime.datetime.now() - start_time
            elapsed_str = str(elapsed).split('.')[0]
            self.log(f"✅ {handle.name()} COMPLETADO en {elapsed_str}")
            torrent_name = handle.name()
            if not torrent_name:
                torrent_name = "unnamed"
            final_path = os.path.join(save_path, self.clean_name(torrent_name))
            yield f"✅ {handle.name()} COMPLETADO en {elapsed_str}"
            yield final_path
        except Exception as e:
            self.log(f"❌ Error en download_magnet: {e}")
            raise e

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

    async def _async_download(self, url: str, save_path: str) -> bool:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=30) as response:
                    if response.status == 200:
                        async with aiofiles.open(save_path, 'wb') as f:
                            await f.write(await response.read())
                        return True
                    return False
        except Exception:
            return False

    async def _download_images_concurrently(self, image_urls: List[str], max_concurrent: int = 10) -> List[Optional[str]]:
        semaphore = asyncio.Semaphore(max_concurrent)
        async def download_one(url: str, index: int):
            async with semaphore:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    temp_path = tmp.name
                success = await self._async_download(url, temp_path)
                if success:
                    return (index, temp_path)
                else:
                    if os.path.exists(temp_path):
                        os.unlink(temp_path)
                    return (index, None)
        tasks = [download_one(url, i) for i, url in enumerate(image_urls)]
        results = await asyncio.gather(*tasks)
        results.sort(key=lambda x: x[0])
        return [path for _, path in results]

    async def create_cbz_async(self, nombre: str, lista: List[str]) -> Optional[str]:
        try:
            safe_nombre = self.clean_name(nombre)
            temp_dir = tempfile.mkdtemp()
            archivos_procesados = []
            urls_con_indices = [(i, item) for i, item in enumerate(lista) if item.startswith(('http://', 'https://'))]
            locales_con_indices = [(i, item) for i, item in enumerate(lista) if not item.startswith(('http://', 'https://'))]
            for i, path in locales_con_indices:
                if os.path.exists(path):
                    dest = os.path.join(temp_dir, f"{i:04d}.jpg")
                    shutil.copy2(path, dest)
                    archivos_procesados.append((i, dest))
            if urls_con_indices:
                indices, urls = zip(*urls_con_indices)
                rutas_temporales = await self._download_images_concurrently(list(urls))
                for idx, temp_path in zip(indices, rutas_temporales):
                    if temp_path:
                        dest = os.path.join(temp_dir, f"{idx:04d}.jpg")
                        shutil.move(temp_path, dest)
                        archivos_procesados.append((idx, dest))
            if not archivos_procesados:
                shutil.rmtree(temp_dir)
                return None
            cbz_path = os.path.join(os.getcwd(), "vault", f"{safe_nombre}.cbz")
            os.makedirs(os.path.dirname(cbz_path), exist_ok=True)
            archivos_procesados.sort(key=lambda x: x[0])
            with zipfile.ZipFile(cbz_path, 'w', zipfile.ZIP_DEFLATED) as cbz:
                for idx, file_path in archivos_procesados:
                    cbz.write(file_path, f"{idx:04d}.jpg")
            shutil.rmtree(temp_dir)
            return cbz_path
        except Exception as e:
            print(f"Error en create_cbz_async: {e}")
            if 'temp_dir' in locals():
                shutil.rmtree(temp_dir, ignore_errors=True)
            return None

    async def create_pdf_async(self, nombre: str, lista: List[str]) -> Optional[str]:
        try:
            safe_nombre = self.clean_name(nombre)
            pdf_path = os.path.join(os.getcwd(), "vault", f"{safe_nombre}.pdf")
            os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
            temp_dir_idx = {}
            urls_con_indices = [(i, item) for i, item in enumerate(lista) if item.startswith(('http://', 'https://'))]
            locales_con_indices = [(i, item) for i, item in enumerate(lista) if not item.startswith(('http://', 'https://')) and os.path.exists(item)]
            if urls_con_indices:
                indices, urls_list = zip(*urls_con_indices)
                rutas = await self._download_images_concurrently(list(urls_list))
                for idx, ruta in zip(indices, rutas):
                    if ruta:
                        temp_dir_idx[idx] = ruta
            for idx, path in locales_con_indices:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    temp_path = tmp.name
                shutil.copy2(path, temp_path)
                temp_dir_idx[idx] = temp_path
            images = []
            for i in range(len(lista)):
                if i in temp_dir_idx:
                    img_path = temp_dir_idx[i]
                    try:
                        img = Image.open(img_path).convert("RGB")
                        images.append(img)
                    except Exception:
                        continue
            if images:
                images[0].save(pdf_path, "PDF", save_all=True, append_images=images[1:])
                return pdf_path
            return None
        except Exception as e:
            print(f"Error en create_pdf_async: {e}")
            return None
        finally:
            for f in temp_dir_idx.values():
                if os.path.exists(f) and f not in [item for _, item in locales_con_indices if item.startswith('/')]:
                    try:
                        os.unlink(f)
                    except:
                        pass

    def create_cbz(self, nombre, lista):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(self.create_cbz_async(nombre, lista))
        finally:
            loop.close()
        return result

    def create_pdf(self, nombre, lista):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(self.create_pdf_async(nombre, lista))
        finally:
            loop.close()
        return result

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

    def sort_directory(self, path):
        if not os.path.exists(path) or not os.path.isdir(path):
            return []
        items = os.listdir(path)
        folders = []
        files = []
        for item in items:
            full_path = os.path.join(path, item)
            if os.path.isdir(full_path):
                folders.append(item)
            else:
                files.append(item)
        folders.sort()
        files.sort()
        return folders + files

    def mega_download(self, mega_link):
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            megadl_path = os.path.join(script_dir, "megadl")
            if not os.path.exists(megadl_path):
                raise FileNotFoundError("megadl not found in script directory")
            if not os.access(megadl_path, os.X_OK):
                os.chmod(megadl_path, 0o755)
            folder_name = str(uuid.uuid4())
            current_dir = os.getcwd()
            download_path = os.path.join(current_dir, "vault", folder_name)
            os.makedirs(download_path, exist_ok=True)
            cmd = [megadl_path, mega_link, "--path", download_path]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
            if result.returncode != 0:
                if os.path.exists(download_path) and not os.listdir(download_path):
                    os.rmdir(download_path)
                raise Exception(f"megadl failed: {result.stderr}")
            return download_path
        except Exception as e:
            if 'download_path' in locals() and os.path.exists(download_path):
                shutil.rmtree(download_path, ignore_errors=True)
            raise e

    def reset_render_service(self, render_service_id, render_bearer):
        try:
            url = f"https://api.render.com/v1/services/{render_service_id}/restart"
            headers = {
                "accept": "application/json",
                "authorization": f"Bearer {render_bearer}"
            }
            response = requests.post(url, headers=headers)
            print(response.text)
            return response.status_code == 200
        except Exception as e:
            print(f"Error en reset_render_service: {e}")
            return False

    def scrap(self, link, texto):
        try:
            response = requests.get(link, timeout=30)
            if response.status_code != 200:
                return []
            html = response.text
            coincidencias = []
            urls_vistas = set()
            import re
            patron_url = r'https?://[^\s"\'<>]+'
            urls = re.findall(patron_url, html)
            for url in urls:
                if texto.lower() in url.lower() and url not in urls_vistas:
                    urls_vistas.add(url)
                    coincidencias.append(url)
            return coincidencias
        except Exception:
            return []
