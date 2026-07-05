import os
import tempfile
import base64
from PIL import Image

class AdultMangaCommands:
    def __init__(self, bot):
        self.bot = bot
        self.neko = bot.neko

    async def get_doujin_info(self, code, quality="hd"):
        return self.neko.vnh(code, quality)

    async def get_3h_info(self, code):
        return self.neko.v3h(code)

    async def search_nhentai(self, search_term):
        return self.neko.snh(search_term)

    async def search_3hentai(self, search_term):
        return self.neko.s3h(search_term)

    async def get_hitomi_page(self, g, p):
        return self.neko.hito(g, p)

    async def get_hitomi_total_pages(self, g):
        result = self.neko.hito(g, 1)
        if "error" in result:
            return 0, ""
        return int(result.get("total_pages", 0)), result.get("title", "")

    async def download_hitomi_pages_raw(self, g, pages, vault_dir):
        downloaded_paths = []
        for page_num in pages:
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
            downloaded_paths.append(vault_path)
        return downloaded_paths

    async def prepare_image(self, url):
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
            except Exception:
                return temp_path
        return None

    def format_tags(self, tags):
        if not tags:
            return ""
        if isinstance(tags, dict):
            tag_lines = []
            for category, items in tags.items():
                if items:
                    items_str = ", ".join(items)
                    tag_lines.append(f"**{category}:** {items_str}")
            return "\n".join(tag_lines)
        elif isinstance(tags, str):
            return tags
        return ""
