import subprocess
import os
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VAULT_DIR = os.path.join(SCRIPT_DIR, "vault", "yt")
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
COOKIES_FILE = os.path.join(DATA_DIR, "cookies.txt")

def yt_video(url):
    os.makedirs(VAULT_DIR, exist_ok=True)
    
    if os.path.exists(COOKIES_FILE):
        comando = f'cd "{VAULT_DIR}" && yt-dlp "{url}" --cookies "{COOKIES_FILE}"'
    else:
        comando = f'cd "{VAULT_DIR}" && yt-dlp "{url}"'
    
    resultado = subprocess.run(comando, shell=True, capture_output=True, text=True)
    
    comando_info = f'cd "{VAULT_DIR}" && yt-dlp "{url}" --print filename'
    nombre = subprocess.run(comando_info, shell=True, capture_output=True, text=True)
    
    return os.path.join(VAULT_DIR, nombre.stdout.strip())

def yt_audio(url):
    os.makedirs(VAULT_DIR, exist_ok=True)
    
    if os.path.exists(COOKIES_FILE):
        comando = f'cd "{VAULT_DIR}" && yt-dlp "{url}" -x --audio-format mp3 --cookies "{COOKIES_FILE}"'
    else:
        comando = f'cd "{VAULT_DIR}" && yt-dlp "{url}" -x --audio-format mp3'
    
    resultado = subprocess.run(comando, shell=True, capture_output=True, text=True)
    
    comando_info = f'cd "{VAULT_DIR}" && yt-dlp "{url}" --print filename'
    nombre_base = subprocess.run(comando_info, shell=True, capture_output=True, text=True)
    nombre_base = nombre_base.stdout.strip()
    nombre_audio = nombre_base.rsplit('.', 1)[0] + '.mp3'
    
    return os.path.join(VAULT_DIR, nombre_audio)
