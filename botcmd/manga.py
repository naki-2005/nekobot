import os
import asyncio
import shutil
import tempfile
import zipfile
import json
from PIL import Image
from pyrogram.types import Message
from neko import Neko

class MangaCommands:
    def __init__(self, bot):
        self.bot = bot
        self.neko = bot.neko
    
    async def mangafile(self, message, user_id):
        global user_manga_settings
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            current = user_manga_settings.get(user_id, {}).get("format", "cbz")
            await self.bot.safe_call(message.reply_text, f"📚 Formato actual de manga: **{current.upper()}**\nUsa: `/mangafile cbz` o `/mangafile pdf` o `/mangafile zip`")
            return
        format_option = parts[1].lower()
        if format_option not in ["cbz", "pdf", "zip"]:
            await self.bot.safe_call(message.reply_text, "❌ Formato inválido. Usa: cbz, pdf o zip")
            return
        if user_id not in user_manga_settings:
            user_manga_settings[user_id] = {}
        user_manga_settings[user_id]["format"] = format_option
        await self.bot.safe_call(message.reply_text, f"✅ Formato de manga configurado a: **{format_option.upper()}**")
    
    async def mangadllang(self, message, user_id):
        global user_manga_settings
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            current = user_manga_settings.get(user_id, {}).get("language", "en")
            await self.bot.safe_call(message.reply_text, f"🌐 Idioma actual: **{current}**\nUsa: `/mangadllang en` o `/mangadllang es`")
            return
        lang_option = parts[1].lower()
        if lang_option not in ["en", "es"]:
            await self.bot.safe_call(message.reply_text, "❌ Idioma inválido. Usa: en o es")
            return
        if user_id not in user_manga_settings:
            user_manga_settings[user_id] = {}
        user_manga_settings[user_id]["language"] = lang_option
        await self.bot.safe_call(message.reply_text, f"✅ Idioma de manga configurado a: **{lang_option}**")
    
    async def mangadlset(self, message, user_id):
        global user_manga_settings
        parts = message.text.split()
        if len(parts) == 1:
            current = user_manga_settings.get(user_id, {}).get("mode", "vol")
            mode_text = "volúmenes" if current == "vol" else "capítulos"
            await self.bot.safe_call(message.reply_text, f"📚 Modo actual de descarga: **{mode_text}**\nUsa: `/mangadlset vol` o `/mangadlset chap`")
            return
        if len(parts) != 2:
            await self.bot.safe_call(message.reply_text, "Usa: `/mangadlset vol` o `/mangadlset chap`")
            return
        mode_option = parts[1].lower()
        if mode_option not in ["vol", "chap"]:
            await self.bot.safe_call(message.reply_text, "Modo inválido. Usa: vol o chap")
            return
        if user_id not in user_manga_settings:
            user_manga_settings[user_id] = {}
        user_manga_settings[user_id]["mode"] = mode_option
        mode_text = "volúmenes" if mode_option == "vol" else "capítulos"
        await self.bot.safe_call(message.reply_text, f"✅ Modo de descarga configurado a: **{mode_text}**")
    
    async def mangadlquality(self, message, user_id):
        global user_manga_settings
        parts = message.text.split()
        if len(parts) == 1:
            current = user_manga_settings.get(user_id, {}).get("quality", "hd")
            await self.bot.safe_call(message.reply_text, f"📊 Calidad actual de manga: **{current.upper()}**\nUsa: `/mangadlquality hd` o `/mangadlquality sd`")
            return
        if len(parts) != 2:
            await self.bot.safe_call(message.reply_text, "Usa: `/mangadlquality hd` o `/mangadlquality sd`")
            return
        quality_option = parts[1].lower()
        if quality_option not in ["hd", "sd"]:
            await self.bot.safe_call(message.reply_text, "Calidad inválida. Usa: hd o sd")
            return
        if user_id not in user_manga_settings:
            user_manga_settings[user_id] = {}
        user_manga_settings[user_id]["quality"] = quality_option
        await self.bot.safe_call(message.reply_text, f"✅ Calidad de manga configurado a: **{quality_option.upper()}**")
    
    async def mangasearch(self, message):
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            await self.bot.safe_call(message.reply_text, "Usa: `/mangasearch término`")
            return
        search_term = parts[1]
        await self.bot.safe_call(message.reply_text, f"🔍 Buscando manga: **{search_term}**...")
        try:
            from nekoapis.mangadex import MangaDex
            mangadex = MangaDex()
            search_json = mangadex.search(search_term)
            if not search_json:
                await self.bot.safe_call(message.reply_text, "❌ No se encontraron resultados")
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
                        await self.bot.safe_call(message.reply_photo, temp_path, caption=caption)
                        os.remove(temp_path)
                    else:
                        await self.bot.safe_call(message.reply_text, caption)
                else:
                    await self.bot.safe_call(message.reply_text, caption)
        except Exception as e:
            print(f"Error buscando manga: {e}")
            await self.bot.safe_call(message.reply_text, "❌ Error en la búsqueda")
    
    async def mangadl(self, message, user_id, user_manga_settings):
        parts = message.text.split()
        if len(parts) < 2:
            await self.bot.safe_call(message.reply_text, "Usa: `/mangadl MangaID` o `/mangadl MangaID -sc # -sv # -fc # -fv #`")
            return
        input_text = parts[1]
        manga_id = self._extract_manga_id_from_input(input_text)
        if not manga_id:
            await self.bot.safe_call(message.reply_text, "❌ No se pudo extraer el ID del manga del enlace proporcionado")
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
                await self.bot.safe_call(message.reply_text, "Formato -sc inválido")
                return
        if "-sv" in text:
            try:
                sv_idx = text.index("-sv")
                start_volume = float(text[sv_idx:].split()[1])
            except:
                await self.bot.safe_call(message.reply_text, "Formato -sv inválido")
                return
        if "-fc" in text:
            try:
                fc_idx = text.index("-fc")
                end_chapter = float(text[fc_idx:].split()[1])
            except:
                await self.bot.safe_call(message.reply_text, "Formato -fc inválido")
                return
        if "-fv" in text:
            try:
                fv_idx = text.index("-fv")
                end_volume = float(text[fv_idx:].split()[1])
            except:
                await self.bot.safe_call(message.reply_text, "Formato -fv inválido")
                return
        if start_chapter and start_volume:
            await self.bot.safe_call(message.reply_text, "❌ No puedes usar -sc y -sv al mismo tiempo")
            return
        if end_chapter and end_volume:
            await self.bot.safe_call(message.reply_text, "❌ No puedes usar -fc y -fv al mismo tiempo")
            return
        user_mode = user_manga_settings.get(user_id, {}).get("mode", "vol")
        user_format = user_manga_settings.get(user_id, {}).get("format", "cbz")
        user_quality = user_manga_settings.get(user_id, {}).get("quality", "hd")
        user_lang = user_manga_settings.get(user_id, {}).get("language", "en")
        await self.process_manga_download(
            message, manga_id, user_mode, user_format, user_quality, user_lang,
            start_chapter, start_volume, end_chapter, end_volume, user_id
        )
    
    def _extract_manga_id_from_input(self, input_text):
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
    
    async def process_manga_download(self, message, manga_id, mode, format_choice, quality_choice, language, start_chapter, start_volume, end_chapter, end_volume, user_id):
        try:
            from nekoapis.mangadex import MangaDex
            mangadex = MangaDex()
            progress_msg = await self.bot.safe_call(message.reply_text, f"📚 Obteniendo información para manga {manga_id}...")
            try:
                feed_json = mangadex.feed(manga_id, language=language)
                if not feed_json:
                    await self.bot.safe_call(progress_msg.edit_text, "❌ No se pudo obtener información del manga (feed)")
                    return
                feed_data = json.loads(feed_json)
                covers_json = mangadex.covers([manga_id])
                covers_data = json.loads(covers_json) if covers_json else []
                covers_dict = {}
                for cover in covers_data:
                    if isinstance(cover, dict) and 'volume' in cover and 'cover' in cover:
                        covers_dict[str(cover['volume'])] = cover['cover']
                if mode == "vol":
                    await self.download_manga_by_volumes(progress_msg, manga_id, feed_data, covers_dict, format_choice, start_chapter, start_volume, end_chapter, end_volume, user_id)
                else:
                    await self.download_manga_by_chapters(
                        progress_msg, manga_id, feed_data, covers_dict,
                        format_choice, quality_choice,
                        start_chapter, start_volume, end_chapter, end_volume, user_id
                    )
            except Exception as e:
                print(f"Error obteniendo datos: {e}")
                await self.bot.safe_call(progress_msg.edit_text, f"❌ Error al obtener datos: {e}")
        except Exception as e:
            print(f"Error en process_manga_download: {e}")
            await self.bot.safe_call(message.reply_text, f"❌ Error al procesar la descarga: {e}")
    
    async def download_manga_by_volumes(self, progress_msg, manga_id, feed_data, covers_dict, format_choice, start_chapter, start_volume, end_chapter, end_volume, user_id):
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
                chapters.sort(key=lambda x: self.sort_key(x.get('chapter', '0')))
                all_volume_images = []
                chapter_range = []
                total_images_downloaded = 0
                total_images_expected = 0
                for chapter in chapters:
                    chapter_num = chapter.get('chapter')
                    if start_chapter:
                        try:
                            chap_float = self.sort_key(str(chapter_num))
                            start_chap_float = self.sort_key(str(start_chapter))
                            if chap_float < start_chap_float:
                                continue
                        except:
                            continue
                    if end_chapter:
                        try:
                            chap_float = self.sort_key(str(chapter_num))
                            end_chap_float = self.sort_key(str(end_chapter))
                            if chap_float > end_chap_float:
                                break
                        except:
                            continue
                    chapter_range.append(float(chapter_num) if chapter_num and chapter_num.replace('.', '', 1).isdigit() else chapter_num)
                    chapter_id = chapter.get('chapter_id')
                    if chapter_id:
                        try:
                            from nekoapis.mangadex import MangaDex
                            mangadex = MangaDex()
                            dl_json = mangadex.dl(chapter_id)
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
                        if await self.bot.async_download(cover_url, thumbnail_path):
                            img = Image.open(thumbnail_path)
                            img.thumbnail((320, 320))
                            img.save(thumbnail_path, "JPEG")
                        else:
                            thumbnail_path = None
                    except Exception as e:
                        print(f"Error descargando miniatura: {e}")
                        thumbnail_path = None
                volume_name = f"Volumen {volume}" if volume is not None else "Sin volumen"
                await self.bot.safe_call(progress_msg.edit_text, f"📦 Procesando {volume_name} ({volume_index}/{total_volumes})... (0/{total_images_expected} Imágenes descargadas)")
                for chapter in chapters:
                    chapter_num = chapter.get('chapter')
                    if start_chapter:
                        try:
                            chap_float = self.sort_key(str(chapter_num))
                            start_chap_float = self.sort_key(str(start_chapter))
                            if chap_float < start_chap_float:
                                continue
                        except:
                            continue
                    if end_chapter:
                        try:
                            chap_float = self.sort_key(str(chapter_num))
                            end_chap_float = self.sort_key(str(end_chapter))
                            if chap_float > end_chap_float:
                                break
                        except:
                            continue
                    chapter_id = chapter.get('chapter_id')
                    if not chapter_id:
                        continue
                    try:
                        from nekoapis.mangadex import MangaDex
                        mangadex = MangaDex()
                        dl_json = mangadex.dl(chapter_id)
                        if not dl_json:
                            continue
                        dl_data = json.loads(dl_json)
                        if 'error' in dl_data:
                            continue
                        image_urls = dl_data.get('hd', [])
                        if not image_urls:
                            continue
                        downloaded_images = await self.bot.download_images_concurrently(image_urls, max_concurrent=10)
                        volume_dir = os.path.join(vault_dir, f"vol_{volume if volume is not None else 'sin_volumen'}")
                        os.makedirs(volume_dir, exist_ok=True)
                        for img_idx, img_path in enumerate(downloaded_images):
                            safe_chapter = str(chapter_num).replace('.', '_').replace('/', '_')
                            new_name = f"vol_{volume if volume is not None else '0'}_chap_{safe_chapter}_img_{img_idx+1:03d}.jpg"
                            new_path = os.path.join(volume_dir, new_name)
                            shutil.move(img_path, new_path)
                            all_volume_images.append(new_path)
                        total_images_downloaded += len(downloaded_images)
                        await self.bot.safe_call(progress_msg.edit_text, f"📦 Procesando {volume_name} ({volume_index}/{total_volumes})... ({total_images_downloaded}/{total_images_expected} Imágenes descargadas)")
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
                    cbz_path = await self.create_cbz_from_images(volume_name, all_volume_images, user_id)
                    if cbz_path:
                        await self.bot._send_document_with_progress(progress_msg.chat.id, cbz_path, f"📚 {volume_name}", thumb=thumbnail_path, user_id=user_id)
                elif format_choice == "pdf" and all_volume_images:
                    pdf_path = await self.create_pdf_from_images(volume_name, all_volume_images, user_id)
                    if pdf_path:
                        await self.bot._send_document_with_progress(progress_msg.chat.id, pdf_path, f"📚 {volume_name}", thumb=thumbnail_path, user_id=user_id)
                elif format_choice == "zip" and all_volume_images:
                    zip_path = self.neko.create_zip(volume_name, all_volume_images)
                    if zip_path:
                        await self.bot._send_document_with_progress(progress_msg.chat.id, zip_path, f"📚 {volume_name}", thumb=thumbnail_path, user_id=user_id)
                else:
                    await self.bot.safe_call(progress_msg.edit_text, f"✅ Volumen {volume} guardado en vault: {vault_dir}")
                if thumbnail_path and os.path.exists(thumbnail_path):
                    try:
                        os.remove(thumbnail_path)
                    except:
                        pass
                await asyncio.sleep(0.2)
            await self.bot.safe_call(progress_msg.edit_text, "✅ Descarga de volúmenes completada y guardada en vault")
        except Exception as e:
            print(f"Error en download_manga_by_volumes: {e}")
            await self.bot.safe_call(progress_msg.edit_text, f"❌ Error en la descarga: {e}")
    
    async def download_manga_by_chapters(self, progress_msg, manga_id, feed_data, covers_dict, format_choice, quality_choice, start_chapter, start_volume, end_chapter, end_volume, user_id):
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
            all_chapters.sort(key=lambda x: self.sort_key(x.get('chapter', '0')))
            filtered_chapters = []
            for chapter in all_chapters:
                chapter_num = chapter.get('chapter')
                volume = chapter.get('volume')
                if start_chapter:
                    try:
                        chap_float = self.sort_key(str(chapter_num))
                        start_chap_float = self.sort_key(str(start_chapter))
                        if chap_float < start_chap_float:
                            continue
                    except:
                        continue
                if end_chapter:
                    try:
                        chap_float = self.sort_key(str(chapter_num))
                        end_chap_float = self.sort_key(str(end_chapter))
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
                    from nekoapis.mangadex import MangaDex
                    mangadex = MangaDex()
                    dl_json = mangadex.dl(chapter_id)
                    if not dl_json:
                        continue
                    dl_data = json.loads(dl_json)
                    if 'error' in dl_data:
                        continue
                    image_urls = dl_data.get(quality_choice, [])
                    if not image_urls:
                        continue
                    total_images = len(image_urls)
                    await self.bot.safe_call(progress_msg.edit_text, f"📖 Descargando capítulo {chapter_num} ({idx}/{total_chapters})... (0/{total_images} Imágenes descargadas)")
                    downloaded_images = await self.bot.download_images_concurrently(image_urls, max_concurrent=10)
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
                    await self.bot.safe_call(progress_msg.edit_text, f"📖 Descargando capítulo {chapter_num} ({idx}/{total_chapters})... ({len(downloaded_images)}/{total_images} Imágenes descargadas)")
                    thumbnail_path = None
                    if volume is not None:
                        volume_str = str(volume)
                        if volume_str in covers_dict:
                            cover_url = covers_dict[volume_str]
                            try:
                                thumbnail_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
                                thumbnail_path = thumbnail_file.name
                                thumbnail_file.close()
                                if await self.bot.async_download(cover_url, thumbnail_path):
                                    img = Image.open(thumbnail_path)
                                    img.thumbnail((320, 320))
                                    img.save(thumbnail_path, "JPEG")
                            except Exception as e:
                                print(f"Error descargando miniatura: {e}")
                                thumbnail_path = None
                    if format_choice == "cbz" and chapter_images:
                        cbz_path = await self.create_cbz_from_images(f"Capítulo {chapter_num}", chapter_images, user_id)
                        if cbz_path:
                            await self.bot._send_document_with_progress(progress_msg.chat.id, cbz_path, f"📖 Capítulo {chapter_num}", thumb=thumbnail_path, user_id=user_id)
                    elif format_choice == "pdf" and chapter_images:
                        pdf_path = await self.create_pdf_from_images(f"Capítulo {chapter_num}", chapter_images, user_id)
                        if pdf_path:
                            await self.bot._send_document_with_progress(progress_msg.chat.id, pdf_path, f"📖 Capítulo {chapter_num}", thumb=thumbnail_path, user_id=user_id)
                    elif format_choice == "zip" and chapter_images:
                        zip_path = self.neko.create_zip(f"Capítulo {chapter_num}", chapter_images)
                        if zip_path:
                            await self.bot._send_document_with_progress(progress_msg.chat.id, zip_path, f"📖 Capítulo {chapter_num}", thumb=thumbnail_path, user_id=user_id)
                    else:
                        await self.bot.safe_call(progress_msg.edit_text, f"✅ Capítulo {chapter_num} guardado en vault: {chapter_dir}")
                    if thumbnail_path and os.path.exists(thumbnail_path):
                        try:
                            os.remove(thumbnail_path)
                        except:
                            pass
                    await asyncio.sleep(0.2)
                except Exception as e:
                    print(f"Error descargando capítulo {chapter_num}: {e}")
                    continue
            await self.bot.safe_call(progress_msg.edit_text, "✅ Descarga de capítulos completada y guardada en vault")
        except Exception as e:
            print(f"Error en download_manga_by_chapters: {e}")
            await self.bot.safe_call(progress_msg.edit_text, f"❌ Error en la descarga: {e}")
    
    async def create_cbz_from_images(self, nombre, image_paths, user_id):
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
            with zipfile.ZipFile(cbz_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as cbz:
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

    async def create_pdf_from_images(self, nombre, image_paths, user_id):
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

    def sort_key(self, val):
        if not val or val == 'sin_volumen' or val == 'None':
            return (float('inf'), '')
        try:
            return (float(val), '')
        except ValueError:
            return (float('inf'), val)