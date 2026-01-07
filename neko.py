import nekoapis.hapi
import os
import zipfile
import requests
import tempfile
import shutil
from PIL import Image
from io import BytesIO

class Neko:
    def __init__(self):
        self.hapi = nekoapis.hapi.NakiBotAPI()
    
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
