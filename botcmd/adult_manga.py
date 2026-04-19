import os
import asyncio
import tempfile
import base64
from botcmd.utils import safe_call

class AdultMangaCommands:
    def __init__(self, bot):
        self.bot = bot
        self.neko = bot.neko

    async def nh_or_3h(self, message, user_id, user_settings, user_nh_quality):
        parts = message.text.split()
        if len(parts) < 2:
            await safe_call(message.reply_text, "Usa: `/nh codigo` o `/3h codigo`")
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
                await safe_call(message.reply_text, "Formato -s inválido")
                return
        if "-f" in text:
            try:
                f_idx = text.index("-f")
                end_page = int(text[f_idx:].split()[1])
            except:
                await safe_call(message.reply_text, "Formato -f inválido")
                return
        if "-p" in text:
            try:
                p_idx = text.index("-p")
                single_page = int(text[p_idx:].split()[1])
            except:
                await safe_call(message.reply_text, "Formato -p inválido")
                return
        format_choice = user_settings.get(user_id, "cbz")
        quality_choice = user_nh_quality.get(user_id, "hd")
        result = self.neko.vnh(code, quality_choice) if command == "/nh" else self.neko.v3h(code)
        if single_page:
            images = result.get("image_links", [])
            if images and 0 < single_page <= len(images):
                selected_url = images[single_page-1]
                temp_path = await self.bot._prepare_image_for_telegram(selected_url)
                if temp_path:
                    await safe_call(message.reply_photo, temp_path, caption=f"Página {single_page}/{len(images)}")
                    os.remove(temp_path)
                else:
                    await safe_call(message.reply_text, f"Error descargando página {single_page}")
            else:
                await safe_call(message.reply_text, f"Página {single_page} no encontrada")
            return
        if format_choice == "raw":
            await self.bot._process_gallery_json_with_range(message, result, code, format_choice, start_page, end_page, user_id)
        else:
            await self.bot._process_gallery_with_format(message, result, code, format_choice, start_page, end_page, user_id)

    async def snh_or_s3h(self, message):
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            await safe_call(message.reply_text, "Usa: `/snh busqueda` o `/s3h busqueda`")
            return
        search = parts[1]
        result = self.neko.snh(search) if message.text.startswith("/snh ") else self.neko.s3h(search)
        await self.bot._process_search_json(message, result, 0)

    async def hito(self, message, user_id, user_settings):
        parts = message.text.split()
        if len(parts) < 2:
            await safe_call(message.reply_text, "Usa: `/hito ID` o `/hito ID -s inicio -f final`")
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
                await safe_call(message.reply_text, "Formato de enlace inválido")
                return
        else:
            try:
                g = arg.split("-")[-1].split(".html")[0]
            except:
                await safe_call(message.reply_text, "Formato de enlace inválido")
                return
        text = message.text
        if "-s" in text:
            try:
                s_idx = text.index("-s")
                start_page = int(text[s_idx:].split()[1])
            except:
                await safe_call(message.reply_text, "Formato -s inválido")
                return
        if "-f" in text:
            try:
                f_idx = text.index("-f")
                end_page = int(text[f_idx:].split()[1])
            except:
                await safe_call(message.reply_text, "Formato -f inválido")
                return
        if "-p" in text:
            try:
                p_idx = text.index("-p")
                single_page = int(text[p_idx:].split()[1])
                result = self.neko.hito(g, single_page)
                if "error" in result:
                    await safe_call(message.reply_text, f"Error: {result['error']}")
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
                await safe_call(message.reply_photo, nombre_salida, caption=f"Página {pagina_actual}/{paginas_totales} de {titulo}")
                os.remove(nombre_salida)
                return
            except Exception as e:
                await safe_call(message.reply_text, f"Error procesando página única: {e}")
                return
        format_choice = user_settings.get(user_id, "raw")
        result_first = self.neko.hito(g, 1)
        if "error" in result_first:
            await safe_call(message.reply_text, f"Error: {result_first['error']}")
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
        if len(pages_to_download) == 0:
            await safe_call(message.reply_text, "No hay páginas para descargar en el rango especificado")
            return
        progress_msg = await safe_call(message.reply_text, f"Preparando descarga de {g}...")
        if format_choice == "raw":
            await self.bot._download_hitomi_raw(message, g, pages_to_download, titulo, progress_msg, start_page, end_page, total_pages, user_id)
        else:
            await self.bot._download_hitomi_with_format(message, g, pages_to_download, titulo, progress_msg, start_page, end_page, total_pages, format_choice, user_id)
