import requests
import json

class MangaDex:
    def __init__(self):
        self.session = requests.Session()
    
    def get_first_value(self, dictionary):
        if dictionary and isinstance(dictionary, dict):
            for value in dictionary.values():
                if value:
                    return value
        return "No disponible"
    
    def sort_volumes(self, volumes):
        def volume_key(vol):
            vol_str = str(vol).strip().replace(',', '.')
            try:
                return float(vol_str)
            except:
                return float('inf')
        
        return sorted(volumes, key=lambda x: volume_key(x['volume']))
    
    def sort_chapter_dicts(self, chapters_list):
        def chapter_key(chap):
            chapter_num = chap.get('chapter', '0')
            chap_str = str(chapter_num).strip().replace(',', '.')
            if chap_str.lower() == 'null' or chap_str.lower() == 'none':
                return float('-inf')
            try:
                return float(chap_str)
            except:
                return float('inf')
        
        return sorted(chapters_list, key=chapter_key)
    
    def search(self, title):
        base_url = "https://api.mangadex.org/manga"
        all_results = []
        limit = 100
        offset = 0
        
        while True:
            params = {
                'title': title,
                'limit': limit,
                'offset': offset
            }
            
            response = self.session.get(base_url, params=params)
            if response.status_code != 200:
                break
                
            data = response.json()
            total = data.get('total', 0)
            
            for manga in data.get('data', []):
                attributes = manga.get('attributes', {})
                title_obj = attributes.get('title', {})
                description_obj = attributes.get('description', {})
                tags_list = attributes.get('tags', [])
                
                tags = []
                for tag in tags_list:
                    tag_attrs = tag.get('attributes', {})
                    tag_name = tag_attrs.get('name', {})
                    first_tag_name = self.get_first_value(tag_name)
                    if first_tag_name and first_tag_name != "No disponible":
                        tags.append(first_tag_name)
                
                manga_data = [
                    ('title', self.get_first_value(title_obj)),
                    ('id', manga.get('id', '')),
                    ('description', self.get_first_value(description_obj)),
                    ('tags', tags)
                ]
                all_results.append(dict(manga_data))
            
            offset += limit
            if offset >= total:
                break
        
        return json.dumps(all_results, ensure_ascii=False)
    
    def covers(self, manga_ids):
        if not manga_ids:
            return json.dumps({'error': 'Se requiere al menos un manga ID'}, ensure_ascii=False)
        
        base_url = "https://api.mangadex.org/cover"
        all_covers = []
        
        for manga_id in manga_ids:
            params = {
                'limit': 100,
                'manga[]': manga_id
            }
            
            response = self.session.get(base_url, params=params)
            if response.status_code != 200:
                continue
                
            data = response.json()
            
            manga_covers = []
            for cover in data.get('data', []):
                attributes = cover.get('attributes', {})
                volume = attributes.get('volume', '')
                filename = attributes.get('fileName', '')
                
                if volume and filename:
                    cover_url = f"https://uploads.mangadex.org/covers/{manga_id}/{filename}"
                    manga_covers.append({
                        'volume': volume,
                        'cover': cover_url
                    })
            
            sorted_covers = self.sort_volumes(manga_covers)
            all_covers.extend(sorted_covers)
        
        return json.dumps(all_covers, ensure_ascii=False)
    
    def feed(self, manga_id):
        if not manga_id:
            return json.dumps({'error': 'Se requiere el parámetro manga'}, ensure_ascii=False)
        
        base_url = f"https://api.mangadex.org/manga/{manga_id}/feed"
        all_chapters = []
        limit = 500
        offset = 0
        
        while True:
            params = {
                'translatedLanguage[]': 'en',
                'limit': limit,
                'offset': offset
            }
            
            response = self.session.get(base_url, params=params)
            if response.status_code != 200:
                break
                
            data = response.json()
            total = data.get('total', 0)
            
            for chapter in data.get('data', []):
                attributes = chapter.get('attributes', {})
                volume = attributes.get('volume')
                chapter_num = attributes.get('chapter')
                chapter_id = chapter.get('id', '')
                
                all_chapters.append({
                    'volume': volume if volume is not None else 'null',
                    'chapter': chapter_num if chapter_num is not None else '0',
                    'chapter_id': chapter_id
                })
            
            offset += limit
            if offset >= total:
                break
        
        volume_groups = {}
        for chapter in all_chapters:
            volume_key = chapter['volume']
            if volume_key not in volume_groups:
                volume_groups[volume_key] = []
            
            volume_groups[volume_key].append({
                'chapter': chapter['chapter'],
                'chapter_id': chapter['chapter_id']
            })
        
        result = []
        for volume in self.sort_volumes([{'volume': vol} for vol in volume_groups.keys()]):
            vol_str = volume['volume']
            chapters_list = volume_groups[vol_str]
            
            result.append({
                'volume': vol_str if vol_str != 'null' else None,
                'chapters': chapters_list
            })
        
        return json.dumps(result, ensure_ascii=False)
    
    def dl(self, chapter_id):
        if not chapter_id:
            return json.dumps({'error': 'Se requiere el parámetro chapter'}, ensure_ascii=False)
        
        base_url = f"https://api.mangadex.org/at-home/server/{chapter_id}"
        
        response = self.session.get(base_url)
        if response.status_code != 200:
            return json.dumps({'error': 'No se pudo obtener datos del capítulo'}, ensure_ascii=False)
        
        data = response.json()
        
        chapter_data = data.get('chapter', {})
        hash_value = chapter_data.get('hash', '')
        data_hd = chapter_data.get('data', [])
        data_sd = chapter_data.get('dataSaver', [])
        
        hd_urls = []
        sd_urls = []
        
        for filename in data_hd:
            hd_url = f"https://uploads.mangadex.org/data/{hash_value}/{filename}"
            hd_urls.append(hd_url)
        
        for filename in data_sd:
            sd_url = f"https://uploads.mangadex.org/data-saver/{hash_value}/{filename}"
            sd_urls.append(sd_url)
        
        result = {
            'hd': hd_urls,
            'sd': sd_urls
        }
        
        return json.dumps(result, ensure_ascii=False)
    
    def all_hd(self, manga_id):
        return self._get_all_images(manga_id, 'hd')
    
    def all_sd(self, manga_id):
        return self._get_all_images(manga_id, 'sd')
    
    def _get_all_images(self, manga_id, quality):
        if not manga_id:
            return json.dumps({'error': 'Se requiere el parámetro manga'}, ensure_ascii=False)
        
        feed_data = json.loads(self.feed(manga_id))
        if 'error' in feed_data:
            return json.dumps(feed_data, ensure_ascii=False)
        
        covers_data = json.loads(self.covers([manga_id]))
        if 'error' in covers_data:
            covers_data = []
        
        result = []
        
        for volume_data in feed_data:
            volume = volume_data['volume']
            chapters = volume_data['chapters']
            
            volume_entry = {
                'volume': volume,
                'cover': None,
                'chapters': []
            }
            
            for cover in covers_data:
                if cover['volume'] == str(volume) if volume else 'null':
                    volume_entry['cover'] = cover['cover']
                    break
            
            if not volume_entry['cover'] and covers_data:
                volume_entry['cover'] = covers_data[0]['cover']
            
            sorted_chapters = self.sort_chapter_dicts(chapters)
            
            for chapter_info in sorted_chapters:
                chapter_num = chapter_info['chapter']
                chapter_id = chapter_info['chapter_id']
                
                dl_data = json.loads(self.dl(chapter_id))
                if 'error' not in dl_data:
                    chapter_entry = {
                        'chapter': chapter_num,
                        'images': dl_data[quality]
                    }
                    volume_entry['chapters'].append(chapter_entry)
            
            result.append(volume_entry)
        
        return json.dumps(result, ensure_ascii=False)
