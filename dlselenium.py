import os
import requests
from pathlib import Path

def download_file(url, filename):
    try:
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()
        with open(filename, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return True
    except Exception as e:
        print(f"Error descargando {filename}: {e}")
        return False

def dl_files():
    base_dir = Path(__file__).parent.absolute()
    selenium_dir = base_dir / "selenium"
    selenium_dir.mkdir(exist_ok=True)
    
    chrome_url = "https://nakiapi-scrap.onrender.com/file/chrome"
    chromedriver_url = "https://nakiapi-scrap.onrender.com/file/chromedriver"
    
    chrome_path = selenium_dir / "chrome"
    chromedriver_path = selenium_dir / "chromedriver"
    
    chrome_success = True
    chromedriver_success = True
    
    if not chrome_path.exists():
        print("Descargando Chrome...")
        chrome_success = download_file(chrome_url, chrome_path)
    else:
        print("Chrome ya existe, omitiendo descarga")
    
    if not chromedriver_path.exists():
        print("Descargando Chromedriver...")
        chromedriver_success = download_file(chromedriver_url, chromedriver_path)
    else:
        print("Chromedriver ya existe, omitiendo descarga")
    
    if chrome_success and os.path.exists(chrome_path):
        os.chmod(chrome_path, 0o755)
        print("✓ Permisos establecidos para Chrome")
    else:
        print("✗ Error con Chrome")
    
    if chromedriver_success and os.path.exists(chromedriver_path):
        os.chmod(chromedriver_path, 0o755)
        print("✓ Permisos establecidos para Chromedriver")
    else:
        print("✗ Error con Chromedriver")
    
    if chrome_success and chromedriver_success:
        print("Instalando dependencias...")
        os.system("pip install Flask==2.3.3 selenium==4.15.0 requests==2.31.0")
        print("✓ Todo listo")
    else:
        print("✗ Algunos archivos no se descargaron correctamente")
