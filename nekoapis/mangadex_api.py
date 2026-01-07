import requests

class MangaDexApi:
    def __init__(self):
        pass

    def buscar_manga(self, termino):
        if not termino:
            return []
        
        url = f'https://api.mangadex.org/manga?title={termino}&limit=100'
        
        try:
            response = requests.get(url)
            response.raise_for_status()
            datos = response.json()
            
            total = datos.get('total', 0)
            resultados = datos.get('data', [])
            
            if total > 100:
                offset = 100
                while offset < total:
                    url_offset = f'https://api.mangadex.org/manga?title={termino}&limit=100&offset={offset}'
                    resp_offset = requests.get(url_offset)
                    resp_offset.raise_for_status()
                    datos_offset = resp_offset.json()
                    resultados.extend(datos_offset.get('data', []))
                    offset += 100
            
            mangas = []
            for manga in resultados:
                atributos = manga.get('attributes', {})
                titulo = atributos.get('title', {})
                
                titulo_principal = ''
                for lang in titulo.values():
                    if lang:
                        titulo_principal = lang
                        break
                
                manga_id = manga.get('id', '')
                idiomas = atributos.get('availableTranslatedLanguages', [])
                
                covers = self.get_covers(manga_id)
                
                cover_url = ""
                for cover in covers:
                    if cover['volume'] == '1':
                        cover_url = cover['link']
                        break
                
                if not cover_url and covers:
                    cover_url = covers[0]['link']
                
                mangas.append({
                    'id': manga_id,
                    'titulo': titulo_principal,
                    'idiomas': idiomas,
                    'cover': cover_url
                })
            
            return mangas
                
        except requests.exceptions.RequestException as e:
            print(f"Error en la búsqueda: {e}")
            return []
            
    def get_covers(self, manga_id):
        covers = []
        offset = 0
        limit = 100
        
        try:
            while True:
                url = f'https://api.mangadex.org/cover?manga[]={manga_id}&limit={limit}&offset={offset}'
                response = requests.get(url)
                response.raise_for_status()
                datos = response.json()
                
                covers_data = datos.get('data', [])
                
                for cover in covers_data:
                    attributes = cover.get('attributes', {})
                    volume = attributes.get('volume', 'N/A')
                    file_name = attributes.get('fileName', '')
                    
                    if volume and file_name:
                        cover_link = f'https://uploads.mangadex.org/covers/{manga_id}/{file_name}'
                        covers.append({
                            'volume': volume,
                            'link': cover_link
                        })
                
                total = datos.get('total', 0)
                offset += limit
                
                if offset >= total:
                    break
            
            def volume_key(vol):
                if vol == 'N/A':
                    return (float('inf'), '')
                try:
                    return (float(vol), '')
                except ValueError:
                    return (float('inf'), vol)
            
            covers.sort(key=lambda x: volume_key(x['volume']))
            
            return covers
                
        except requests.exceptions.RequestException as e:
            print(f"Error obteniendo covers: {e}")
            return []

    def list_chap(self, manga_id):
        chapters = []
        offset = 0
        limit = 500
        
        try:
            while True:
                url = f'https://api.mangadex.org/manga/{manga_id}/feed?limit={limit}&offset={offset}'
                response = requests.get(url)
                response.raise_for_status()
                datos = response.json()
                
                chapters_data = datos.get('data', [])
                
                for chapter in chapters_data:
                    attributes = chapter.get('attributes', {})
                    chapter_num = attributes.get('chapter', '')
                    volume = attributes.get('volume', '')
                    title = attributes.get('title', '')
                    language = attributes.get('translatedLanguage', '')
                    chapter_id = chapter.get('id', '')
                    
                    if chapter_num:
                        chapters.append({
                            'chapter': chapter_num,
                            'volume': volume,
                            'title': title,
                            'language': language,
                            'id': chapter_id
                        })
                
                total = datos.get('total', 0)
                offset += limit
                
                if offset >= total:
                    break
            
            def chapter_key(chap):
                if not chap:
                    return (float('inf'), '')
                try:
                    return (float(chap), '')
                except ValueError:
                    return (float('inf'), chap)
            
            chapters.sort(key=lambda x: chapter_key(x['chapter']))
            
            return chapters
                
        except requests.exceptions.RequestException as e:
            print(f"Error obteniendo capítulos: {e}")
            return []

    def chapter_pics(self, chapter_id):
        try:
            url = f'https://api.mangadex.org/at-home/server/{chapter_id}'
            response = requests.get(url)
            response.raise_for_status()
            datos = response.json()
            
            if datos.get('result') != 'ok':
                print("Error en la respuesta del servidor")
                return []
            
            chapter_data = datos.get('chapter', {})
            hash_value = chapter_data.get('hash', '')
            data_files = chapter_data.get('data', [])
            
            image_links = []
            for filename in data_files:
                image_link = f'https://uploads.mangadex.org/data/{hash_value}/{filename}'
                image_links.append(image_link)
            
            return image_links
                
        except requests.exceptions.RequestException as e:
            print(f"Error obteniendo imágenes: {e}")
            return []