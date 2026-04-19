import os
import asyncio
import tempfile
import shutil
import base64
import zipfile
from PIL import Image
from pyrogram.types import InputMediaPhoto

class AdultMangaCommands:
    def __init__(self, bot):
        self.bot = bot
        self.neko = bot.neko
    
    async def nh_or_3h(self, message, user_id, user_settings, user_nh_quality):
        parts = message.text.split()
        if len(parts) < 2:
            await self.bot.safe_call(message.reply_text, "Usa: `/nh codigo` o `/3h codigo`")
            return
        command = message.text.split()[0]
        code = parts[1]
        start_page = 1
        end_page = None
        single_page = None
        text = message.text
        if "-s" in text:
            try:
                s_idx = text.index("-s")
                start_page = int(text[s_idx:].split()[1])
            except:
                await self.bot.safe_call(message.reply_text, "Formato -s inválido")
                return
        if "-f" in text:
            try:
                f_idx = text.index("-f")
                end_page = int(text[f_idx:].split()[1])
            except:
                await self.bot.safe_call(message.reply_text, "Formato -f inválido")
                return
        if "-p" in text:
            try:
                p_idx = text.index("-p")
                single_page = int(text[p_idx:].split()[1])
            except:
                await self.bot.safe_call(message.reply_text, "Formato -p inválido")
                return
        format_choice = user_settings.get(user_id, "cbz")
        quality_choice = user_nh_quality.get(user_id, "hd")
        result = self.neko.vnh(code, quality_choice) if command == "/nh" else self.neko.v3h(code)
        if single_page:
            images = result.get("image_links", [])
            if images and 0 < single_page <= len(images):
                selected_url = images[single_page-1]
                temp_path = await self.prepare_image_for_telegram(selected_url)
                if temp_path:
                    await self.bot.safe_call(message.reply_photo, temp_path, caption=f"Página {single_page}/{len(images)}")
                    os.remove(temp_path)
                else:
                    await self.bot.safe_call(message.reply_text, f"Error descargando página {single_page}")
            else:
                await self.bot.safe_call(message.reply_text, f"Página {single_page} no encontrada")
            return
        if format_choice == "raw":
            await self.process_gallery_json_with_range(message, result, code, format_choice, start_page, end_page, user_id)
        else:
            await self.process_gallery_with_format(message, result, code, format_choice, start_page, end_page, user_id)
    
    async def snh_or_s3h(self, message):
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            await self.bot.safe_call(message.reply_text, "Usa: `/snh busqueda` o `/s3h busqueda`")
            return
        search = parts[1]
        result = self.neko.snh(search) if message.text.startswith("/snh ") else self.neko.s3h(search)
        await self.process_search_json(message, result, 0)
    
    async def hito(self, message, user_id, user_settings):
        parts = message.text.split()
        if len(parts) < 2:
            await self.bot.safe_call(message.reply_text, "Usa: `/hito ID` o `/hito ID -s inicio -f final`")
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
                await self.bot.safe_call(message.reply_text, "Formato de enlace inválido")
                return
        else:
            try:
                g = arg.split("-")[-1].split(".html")[0]
            except:
                await self.bot.safe_call(message.reply_text, "Formato de enlace inválido")
                return
        text = message.text
        if "-s" in text:
            try:
                s_idx = text.index("-s")
                start_page = int(text[s_idx:].split()[1])
            except:
                await self.bot.safe_call(message.reply_text, "Formato -s inválido")
                return
        if "-f" in text:
            try:
                f_idx = text.index("-f")
                end_page = int(text[f_idx:].split()[1])
            except:
                await self.bot.safe_call(message.reply_text, "Formato -f inválido")
                return
        if "-p" in text:
            try:
                p_idx = text.index("-p")
                single_page = int(text[p_idx:].split()[1])
                result = self.neko.hito(g, single_page)
                if "error" in result:
                    await self.bot.safe_call(message.reply_text, f"Error: {result['error']}")
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
                await self.bot.safe_call(message.reply_photo, nombre_salida, caption=f"Página {pagina_actual}/{paginas_totales} de {titulo}")
                os.remove(nombre_salida)
                return
            except Exception as e:
                await self.bot.safe_call(message.reply_text, f"Error procesando página única: {e}")
                return
        format_choice = user_settings.get(user_id, "raw")
        result_first = self.neko.hito(g, 1)
        if "error" in result_first:
            await self.bot.safe_call(message.reply_text, f"Error: {result_first['error']}")
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
            await self.bot.safe_call(message.reply_text, "No hay páginas para descargar en el rango especificado")
            return
        progress_msg = await self.bot.safe_call(message.reply_text, f"Preparando descarga de {g}...")
        if format_choice == "raw":
            await self.download_hitomi_raw(message, g, pages_to_download, titulo, progress_msg, start_page, end_page, total_pages, user_id)
        else:
            await self.download_hitomi_with_format(message, g, pages_to_download, titulo, progress_msg, start_page, end_page, total_pages, format_choice, user_id)
    
    async def download_hitomi_raw(self, message, g, pages, titulo, progress_msg, start_page, end_page, total_pages, user_id):
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
                await self.bot.safe_call(progress_msg.edit_text, f"Progreso de descarga de {g} {idx}/{len(pages)}{range_info} - Página {pagina_actual}/{paginas_totales}")
                if len(current_batch) >= batch_size:
                    await self.send_photo_batch(message, photo_paths=current_batch, batch_number=(idx//batch_size)+1, user_id=user_id)
                    current_batch = []
                    await asyncio.sleep(0.2)
            except Exception as e:
                print(f"Error descargando página {page_num}: {e}")
                continue
        if current_batch:
            await self.send_photo_batch(message, photo_paths=current_batch, batch_number=(len(pages)//batch_size)+1, user_id=user_id)
        await self.bot.safe_call(progress_msg.edit_text, f"✅ Descarga RAW completada y guardada en vault: {titulo}")
    
    async def download_hitomi_with_format(self, message, g, pages, titulo, progress_msg, start_page, end_page, total_pages, format_choice, user_id):
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
                await self.bot.safe_call(progress_msg.edit_text, f"Progreso de descarga de {g} {idx}/{len(pages)}{range_info} - Página {pagina_actual}/{paginas_totales}")
            except Exception as e:
                print(f"Error descargando página {page_num}: {e}")
                continue
        if downloaded_images:
            thumb_path = await self.convert_to_thumbnail(downloaded_images[0])
            if format_choice == "cbz":
                cbz_path = await self.bot._create_cbz_from_images(titulo, downloaded_images, user_id)
                if cbz_path:
                    await self.bot._send_document_with_progress(message.chat.id, cbz_path, f"📖 {titulo}", thumb=thumb_path, user_id=user_id)
            elif format_choice == "pdf":
                pdf_path = await self.bot._create_pdf_from_images(titulo, downloaded_images, user_id)
                if pdf_path:
                    await self.bot._send_document_with_progress(message.chat.id, pdf_path, f"📖 {titulo}", thumb=thumb_path, user_id=user_id)
            elif format_choice == "zip":
                zip_path = self.neko.create_zip(titulo, downloaded_images)
                if zip_path:
                    await self.bot._send_document_with_progress(message.chat.id, zip_path, f"📖 {titulo}", thumb=thumb_path, user_id=user_id)
            if thumb_path:
                os.remove(thumb_path)
        await self.bot.safe_call(progress_msg.edit_text, f"✅ Descarga {format_choice.upper()} completada: {titulo}")
    
    async def send_photo_batch(self, message, photo_paths, batch_number, user_id):
        media_group = []
        for photo_path in photo_paths:
            try:
                media_group.append(InputMediaPhoto(photo_path))
            except Exception as e:
                print(f"Error añadiendo foto al grupo: {e}")
        if media_group:
            try:
                await self.bot.app.send_media_group(chat_id=message.chat.id, media=media_group)
            except Exception as e:
                print(f"Error enviando grupo de fotos: {e}")
    
    async def prepare_image_for_telegram(self, url):
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        temp_path = temp_file.name
        temp_file.close()
        if await self.bot.async_download(url, temp_path):
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

    async def convert_to_thumbnail(self, image_path, size=(320, 320)):
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

    async def process_gallery_json_with_range(self, message, result, code, format_choice, start_page, end_page, user_id):
        if "error" in result:
            await self.bot.safe_call(message.reply_text, f"Error: `{result['error']}`")
            return
        nombre = result.get("title", "Sin titulo")
        all_images = result.get("image_links", [])
        tags = result.get("tags", {})
        if not all_images:
            await self.bot.safe_call(message.reply_text, "No hay imagenes")
            return
        total_images = len(all_images)
        if end_page is None:
            end_page = total_images
        start_page = max(1, start_page)
        end_page = min(total_images, end_page)
        if start_page > end_page:
            start_page, end_page = end_page, start_page
        images = all_images[start_page-1:end_page]
        caption = f"**{nombre}**\nCódigo: `{code}`\nRango: {start_page}-{end_page} de {total_images}\n\n{self.format_tags(tags)}"
        vault_dir = os.path.join(os.getcwd(), "vault", "doujin", code)
        os.makedirs(vault_dir, exist_ok=True)
        download_tasks = []
        for i, img_url in enumerate(images):
            img_path = os.path.join(vault_dir, f"page_{i+start_page:04d}.jpg")
            download_tasks.append(self.bot.async_download(img_url, img_path))
        await asyncio.gather(*download_tasks)
        if images:
            first_image_path = os.path.join(vault_dir, f"page_{start_page:04d}.jpg")
            if os.path.exists(first_image_path):
                prepared_image = await self.convert_to_thumbnail(first_image_path)
                await self.bot.safe_call(message.reply_photo, prepared_image, caption=caption)
                if prepared_image:
                    os.remove(prepared_image)
        if len(images) > 1:
            await self.send_photos_in_batches(message, images[1:], start_page+1, vault_dir, user_id=user_id)
    
    async def process_gallery_with_format(self, message, result, code, format_choice, start_page, end_page, user_id):
        if "error" in result:
            await self.bot.safe_call(message.reply_text, f"Error: `{result['error']}`")
            return
        nombre = result.get("title", "Sin titulo")
        all_images = result.get("image_links", [])
        tags = result.get("tags", {})
        if not all_images:
            await self.bot.safe_call(message.reply_text, "No hay imagenes")
            return
        total_images = len(all_images)
        if end_page is None:
            end_page = total_images
        start_page = max(1, start_page)
        end_page = min(total_images, end_page)
        if start_page > end_page:
            start_page, end_page = end_page, start_page
        images = all_images[start_page-1:end_page]
        progress_msg = await self.bot.safe_call(message.reply_text, f"Descargando {len(images)} imágenes en formato {format_choice.upper()}...")
        downloaded_images = []
        for i, img_url in enumerate(images):
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
            temp_path = temp_file.name
            temp_file.close()
            if await self.bot.async_download(img_url, temp_path):
                downloaded_images.append(temp_path)
            if (i + 1) % 5 == 0 or i == len(images) - 1:
                await self.bot.safe_call(progress_msg.edit_text, f"Descargando {len(images)} imágenes en formato {format_choice.upper()}... ({i+1}/{len(images)})")
        if downloaded_images:
            thumb_path = await self.convert_to_thumbnail(downloaded_images[0])
            caption = f"**{nombre}**\nCódigo: `{code}`\nRango: {start_page}-{end_page} de {total_images}\n\n{self.format_tags(tags)}"
            if format_choice == "cbz":
                cbz_path = await self.bot._create_cbz_from_images(f"{nombre} - {code}", downloaded_images, user_id)
                if cbz_path:
                    await self.bot.safe_call(message.reply_photo, photo=thumb_path, reply_to_message_id=message.id, caption=caption)
                    await self.bot._send_document_with_progress(message.chat.id, cbz_path, thumb=thumb_path, reply_to_message_id=message.id, user_id=user_id)
            elif format_choice == "pdf":
                pdf_path = await self.bot._create_pdf_from_images(f"{nombre} - {code}", downloaded_images, user_id)
                if pdf_path:
                    await self.bot.safe_call(message.reply_photo, photo=thumb_path, reply_to_message_id=message.id, caption=caption)
                    await self.bot._send_document_with_progress(message.chat.id, pdf_path, thumb=thumb_path, reply_to_message_id=message.id, user_id=user_id)
            elif format_choice == "zip":
                zip_path = self.neko.create_zip(f"{nombre} - {code}", downloaded_images)
                if zip_path:
                    await self.bot.safe_call(message.reply_photo, photo=thumb_path, reply_to_message_id=message.id, caption=caption)
                    await self.bot._send_document_with_progress(message.chat.id, zip_path, thumb=thumb_path, reply_to_message_id=message.id, user_id=user_id)
            if thumb_path:
                os.remove(thumb_path)
        await self.bot.safe_call(progress_msg.edit_text, f"✅ Descarga {format_choice.upper()} completada: {nombre}")
    
    async def send_photos_in_batches(self, message, image_urls, start_index, vault_dir, batch_size=10, user_id=None):
        for i in range(0, len(image_urls), batch_size):
            batch_urls = image_urls[i:i+batch_size]
            media_group = []
            download_tasks = []
            for idx, url in enumerate(batch_urls):
                page_num = start_index + i + idx
                img_path = os.path.join(vault_dir, f"page_{page_num:04d}.jpg")
                download_tasks.append((url, img_path))
            for url, temp_path in download_tasks:
                if await self.bot.async_download(url, temp_path):
                    media_group.append(InputMediaPhoto(temp_path))
            if media_group:
                await self.bot.safe_call(message.reply_media_group, media_group)
                await asyncio.sleep(0.2)
    
    async def process_search_json(self, message, result, user_id):
        if "error" in result:
            await self.bot.safe_call(message.reply_text, f"Error: `{result['error']}`")
            return
        
        total_resultados = result.get("total_resultados", 0)
        total_paginas = result.get("total_paginas", 0)
        pagina_actual = result.get("pagina_actual", 1)
        termino = result.get("termino_busqueda", "")
        resultados = result.get("resultados", [])
        
        info_text = f"🔍 **Búsqueda:** {termino}\n"
        info_text += f"📊 **Resultados:** {total_resultados}\n"
        info_text += f"📄 **Páginas:** {pagina_actual}/{total_paginas}\n\n"
        
        await self.bot.safe_call(message.reply_text, info_text)
        
        if not resultados:
            await self.bot.safe_call(message.reply_text, "No se encontraron resultados")
            return
        
        download_tasks = []
        for item in resultados:
            code = item.get("code") or item.get("codigo", "")
            nombre = item.get("title") or item.get("nombre", "Sin titulo")
            miniatura = item.get("thumbnail") or item.get("miniatura", "")
            num_pages = item.get("num_pages", 0)
            tags = item.get("tags", "")
            if miniatura.startswith("//"):
                miniatura = f"https:{miniatura}"
            if code and miniatura:
                download_tasks.append((miniatura, nombre, code, num_pages, tags))
            elif code:
                caption = f"**{nombre}**\nCódigo: `{code}`\nPáginas: {num_pages}"
                if tags:
                    caption += f"\n\n{tags}"
                await self.bot.safe_call(message.reply_text, caption)
        for miniatura, nombre, code, num_pages, tags in download_tasks:
            temp_path = await self.prepare_image_for_telegram(miniatura)
            caption = f"**{nombre}**\nCódigo: `{code}`\nPáginas: {num_pages}"
            if tags:
                caption += f"\n\n{tags}"
            if temp_path:
                await self.bot.safe_call(message.reply_photo, temp_path, caption=caption)
                os.remove(temp_path)
            else:
                await self.bot.safe_call(message.reply_text, caption)
        await asyncio.sleep(0.2)
    
    def format_tags(self, tags):
        if not tags:
            return ""
        if isinstance(tags, dict):
            tag_lines = []
            for category, items in tags.items():
                if items:
                    items_str = ", ".join(items[:10])
                    if len(items) > 10:
                        items_str += f" (+{len(items)-10} más)"
                    tag_lines.append(f"**{category}:** {items_str}")
            return "\n".join(tag_lines)
        elif isinstance(tags, str):
            return tags
        return ""