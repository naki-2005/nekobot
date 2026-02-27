import subprocess
import os
import json

COOKIES_FILE = "cookies.txt"

def yt_video(url):
    if os.path.exists(COOKIES_FILE):
        comando = f'yt-dlp "{url}" --cookies "{COOKIES_FILE}"'
    else:
        comando = f'yt-dlp "{url}"'
    
    resultado = subprocess.run(comando, shell=True, capture_output=True, text=True)
    
    comando_info = f'yt-dlp "{url}" --print filename'
    nombre = subprocess.run(comando_info, shell=True, capture_output=True, text=True)
    return nombre.stdout.strip()

def yt_audio(url):
    if os.path.exists(COOKIES_FILE):
        comando = f'yt-dlp "{url}" -t mp3 --cookies "{COOKIES_FILE}"'
    else:
        comando = f'yt-dlp "{url}" -t mp3'
    
    resultado = subprocess.run(comando, shell=True, capture_output=True, text=True)
    
    nombre_base = subprocess.run(f'yt-dlp "{url}" --print filename', shell=True, capture_output=True, text=True)
    nombre_base = nombre_base.stdout.strip()
    nombre_audio = nombre_base.rsplit('.', 1)[0] + '.mp3'
    
    return nombre_audio
