import json
import tempfile
import os
from botcmd.utils import safe_call

class MangaCommands:
    def __init__(self, bot):
        self.bot = bot
        self.neko = bot.neko

    async def mangafile(self, message, user_id):
        global user_manga_settings
        parts = message.text.split(maxsplit=1)
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

    async def mangadllang(self, message, user_id):
        global user_manga_settings
        parts = message.text.split(maxsplit=1)
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

    async def mangadlset(self, message, user_id):
        global user_manga_settings
        parts = message.text.split()
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

    async def mangadlquality(self, message, user_id):
        global user_manga_settings
        parts = message.text.split()
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

    async def mangasearch(self, message):
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            await safe_call(message.reply_text, "Usa: `/mangasearch término`")
            return
        search_term = parts[1]
        await safe_call(message.reply_text, f"🔍 Buscando manga: **{search_term}**...")
        try:
            from nekoapis.mangadex import MangaDex
            mangadex = MangaDex()
            search_json = mangadex.search(search_term)
            if not search_json:
                await safe_call(message.reply_text, "❌ No se encontraron resultados")
                return
            results = json.loads(search_json)
            top_results = results[:5]
            for manga in top_results:
                manga_id = manga.get("id", "")
                title = manga.get("title", "Sin título")
                description = manga.get("description", "Sin descripción")
                covers_json = mangadex.covers([manga_id])
                covers = json.loads(covers_json) if covers_json else []
                cover_url = None
                if covers:
                    cover_url = covers[0].get("cover", "") if isinstance(covers[0], dict) else ""
                caption = f"**{title}**\n\n{description[:300]}...\n\nID: `{manga_id}`"
                if cover_url and cover_url != "No disponible":
                    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
                    temp_path = temp_file.name
                    temp_file.close()
                    if await self.bot.async_download(cover_url, temp_path):
                        await safe_call(message.reply_photo, temp_path, caption=caption)
                        os.remove(temp_path)
                    else:
                        await safe_call(message.reply_text, caption)
                else:
                    await safe_call(message.reply_text, caption)
        except Exception as e:
            print(f"Error buscando manga: {e}")
            await safe_call(message.reply_text, "❌ Error en la búsqueda")

    async def mangadl(self, message, user_id, user_manga_settings):
        parts = message.text.split()
        if len(parts) < 2:
            await safe_call(message.reply_text, "Usa: `/mangadl MangaID` o `/mangadl MangaID -sc # -sv # -fc # -fv #`")
            return
        input_text = parts[1]
        manga_id = self.bot._extract_manga_id_from_input(input_text)
        if not manga_id:
            await safe_call(message.reply_text, "❌ No se pudo extraer el ID del manga del enlace proporcionado")
            return
        start_chapter = None
        start_volume = None
        end_chapter = None
        end_volume = None
        text = message.text
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
        await self.bot._process_manga_download(
            message, manga_id, user_mode, user_format, user_quality, user_lang,
            start_chapter, start_volume, end_chapter, end_volume, user_id
        )
