import json
import tempfile
import os

class MangaCommands:
    def __init__(self, bot):
        self.bot = bot
        self.neko = bot.neko

    def get_user_manga_format(self, user_id, user_manga_settings):
        return user_manga_settings.get(user_id, {}).get("format", "cbz")

    def get_user_manga_language(self, user_id, user_manga_settings):
        return user_manga_settings.get(user_id, {}).get("language", "en")

    def get_user_manga_mode(self, user_id, user_manga_settings):
        return user_manga_settings.get(user_id, {}).get("mode", "vol")

    def get_user_manga_quality(self, user_id, user_manga_settings):
        return user_manga_settings.get(user_id, {}).get("quality", "hd")

    def set_user_manga_format(self, user_id, user_manga_settings, format_option):
        if user_id not in user_manga_settings:
            user_manga_settings[user_id] = {}
        user_manga_settings[user_id]["format"] = format_option
        return f"✅ Formato de manga configurado a: **{format_option.upper()}**"

    def set_user_manga_language(self, user_id, user_manga_settings, lang_option):
        if user_id not in user_manga_settings:
            user_manga_settings[user_id] = {}
        user_manga_settings[user_id]["language"] = lang_option
        return f"✅ Idioma de manga configurado a: **{lang_option}**"

    def set_user_manga_mode(self, user_id, user_manga_settings, mode_option):
        if user_id not in user_manga_settings:
            user_manga_settings[user_id] = {}
        user_manga_settings[user_id]["mode"] = mode_option
        mode_text = "volúmenes" if mode_option == "vol" else "capítulos"
        return f"✅ Modo de descarga configurado a: **{mode_text}**"

    def set_user_manga_quality(self, user_id, user_manga_settings, quality_option):
        if user_id not in user_manga_settings:
            user_manga_settings[user_id] = {}
        user_manga_settings[user_id]["quality"] = quality_option
        return f"✅ Calidad de manga configurado a: **{quality_option.upper()}**"

    async def search_manga(self, search_term):
        from nekoapis.mangadex import MangaDex
        mangadex = MangaDex()
        search_json = mangadex.search(search_term)
        if not search_json:
            return []
        results = json.loads(search_json)
        mangas = []
        for manga in results[:5]:
            manga_id = manga.get("id", "")
            title = manga.get("title", "Sin título")
            description = manga.get("description", "Sin descripción")
            covers_json = mangadex.covers([manga_id])
            covers = json.loads(covers_json) if covers_json else []
            cover_url = None
            if covers:
                cover_url = covers[0].get("cover", "") if isinstance(covers[0], dict) else ""
            mangas.append({
                "id": manga_id,
                "title": title,
                "description": description[:300],
                "cover_url": cover_url
            })
        return mangas

    def extract_manga_id(self, input_text):
        import re
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
