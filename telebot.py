import os
import asyncio
import sys
import argparse
import shutil
import tempfile
import time
import threading
import zipfile
import stat
import subprocess
import uuid
import random
import nest_asyncio
from concurrent.futures import ThreadPoolExecutor
from pyrogram import Client, filters
from pyrogram.types import Message, BotCommand
from pyrogram.errors import FloodWait
from flask import Flask, send_file, abort, request, Response
import urllib.parse
import mimetypes

nest_asyncio.apply()

set_cmd = False
current_directories = {}
ftp_base_url = None
premium_users = set()

def get_vault_dir():
    return os.path.join(os.getcwd(), "vault")

def sanitize_path(path):
    vault_dir = get_vault_dir()
    if path.startswith(vault_dir):
        rel = os.path.relpath(path, vault_dir)
        return '/' if rel == '.' else '/' + rel.replace('\\', '/')
    return path

def run_flask(port):
    app_flask = Flask(__name__)
    vault_dir = get_vault_dir()
    os.makedirs(vault_dir, exist_ok=True)
    
    @app_flask.route('/')
    @app_flask.route('/<path:subpath>')
    def handle_path(subpath=''):
        vault_dir = get_vault_dir()
        if not subpath:
            user_id = "web"
            current_dir = get_current_directory(user_id)
            items = sort_directory(current_dir)
            html = '<html><body>'
            html += '<h1>Vault Explorer</h1>'
            html += f'<p>Current: {sanitize_path(current_dir)}</p>'
            html += '<ul>'
            if current_dir != vault_dir:
                html += '<li><a href="/">.. (parent)</a></li>'
            for item in items:
                item_path = os.path.join(current_dir, item)
                item_relative = os.path.relpath(item_path, vault_dir)
                if item_relative == '.':
                    item_relative = ''
                if os.path.isdir(item_path):
                    html += f'<li><a href="/{item_relative}">{item}/</a></li>'
                else:
                    size = os.path.getsize(item_path)
                    size_mb = size / (1024 * 1024)
                    html += f'<li><a href="/{item_relative}">{item}</a> ({size_mb:.2f} MB)</li>'
            html += '</ul>'
            html += '</body></html>'
            return html
        
        normalized_path = urllib.parse.unquote(subpath)
        full_path = os.path.join(vault_dir, normalized_path)
        
        if not os.path.exists(full_path):
            abort(404)
        
        if os.path.isdir(full_path):
            if "web" not in current_directories:
                current_directories["web"] = vault_dir
            current_directories["web"] = full_path
            items = sort_directory(full_path)
            html = '<html><body>'
            html += '<h1>Vault Explorer</h1>'
            html += f'<p>Current: {sanitize_path(full_path)}</p>'
            html += '<ul>'
            if full_path != vault_dir:
                html += '<li><a href="/">.. (parent)</a></li>'
            for item in items:
                item_path = os.path.join(full_path, item)
                item_relative = os.path.relpath(item_path, vault_dir)
                if item_relative == '.':
                    item_relative = ''
                if os.path.isdir(item_path):
                    html += f'<li><a href="/{item_relative}">{item}/</a></li>'
                else:
                    size = os.path.getsize(item_path)
                    size_mb = size / (1024 * 1024)
                    html += f'<li><a href="/{item_relative}">{item}</a> ({size_mb:.2f} MB)</li>'
            html += '</ul>'
            html += '</body></html>'
            return html
        
        if os.path.isfile(full_path):
            range_header = request.headers.get('Range', None)
            file_size = os.path.getsize(full_path)
            
            if range_header:
                byte_range = range_header.replace('bytes=', '').split('-')
                start = int(byte_range[0])
                end = int(byte_range[1]) if byte_range[1] else file_size - 1
                if start >= file_size:
                    abort(416)
                end = min(end, file_size - 1)
                content_length = end - start + 1
                
                def generate_partial():
                    with open(full_path, 'rb') as f:
                        f.seek(start)
                        remaining = content_length
                        while remaining > 0:
                            chunk_size = min(8192, remaining)
                            data = f.read(chunk_size)
                            if not data:
                                break
                            yield data
                            remaining -= len(data)
                
                response = Response(generate_partial(), status=206, mimetype=mimetypes.guess_type(full_path)[0] or 'application/octet-stream')
                response.headers['Content-Range'] = f'bytes {start}-{end}/{file_size}'
                response.headers['Content-Length'] = str(content_length)
                response.headers['Accept-Ranges'] = 'bytes'
                return response
            else:
                return send_file(full_path, as_attachment=True, conditional=True)
    
    app_flask.run(host='0.0.0.0', port=port)

def sort_directory(directory_path):
    items = []
    if not os.path.exists(directory_path):
        return items
    for item in os.listdir(directory_path):
        item_path = os.path.join(directory_path, item)
        if os.path.isdir(item_path):
            items.append(("dir", item.lower(), item))
        else:
            items.append(("file", item.lower(), item))
    items.sort(key=lambda x: (x[0], x[1]))
    return [item[2] for item in items]

def compress_with_7zz(file_path, target_size_mb=1995, output_name=None):
    sevenzz_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "7zz")
    if not os.path.exists(sevenzz_path):
        return None
    try:
        os.chmod(sevenzz_path, os.stat(sevenzz_path).st_mode | stat.S_IEXEC)
    except:
        pass
    
    if output_name is None:
        output_name = os.path.splitext(os.path.basename(file_path))[0]
    
    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    if file_size_mb <= target_size_mb:
        return None
    
    random_folder = os.path.join(tempfile.gettempdir(), str(uuid.uuid4())[:8])
    os.makedirs(random_folder, exist_ok=True)
    
    cmd = [sevenzz_path, 'a', f'-v{target_size_mb}m', '-mx0', '-r']
    archive_base = os.path.join(random_folder, output_name)
    cmd.append(archive_base)
    cmd.append(file_path)
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            part_files = []
            for f in sorted(os.listdir(random_folder)):
                full_path = os.path.join(random_folder, f)
                if os.path.isfile(full_path):
                    part_files.append(full_path)
            return part_files if part_files else None
        return None
    except Exception as e:
        print(f"Error comprimiendo con 7zz: {e}")
        return None

def get_current_directory(user_id):
    if user_id not in current_directories:
        vault_dir = get_vault_dir()
        os.makedirs(vault_dir, exist_ok=True)
        current_directories[user_id] = vault_dir
    return current_directories[user_id]

def set_current_directory(user_id, path):
    current_directories[user_id] = path

def get_public_path(absolute_path):
    return sanitize_path(absolute_path)

def get_display_path(absolute_path):
    public_path = get_public_path(absolute_path)
    if ftp_base_url:
        base = ftp_base_url.rstrip('/')
        return f"{base}{public_path}"
    return public_path

def get_upload_message(file_path):
    display_path = get_display_path(file_path)
    if ftp_base_url:
        return f"Archivo disponible en {display_path}"
    else:
        return f"Archivo guardado en {display_path}"

def format_time(seconds):
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

async def safe_call(func, *args, **kwargs):
    while True:
        try:
            return await func(*args, **kwargs)
        except FloodWait as e:
            print(f"Esperando {e.value} seg para continuar")
            await asyncio.sleep(e.value)
        except Exception as e:
            print(f"Error inesperado en {func.__name__}: {type(e).__name__}: {e}")
            raise

class NekoTelegram:
    def __init__(self, api_id, api_hash, auth_string, admin_list, is_bot_token=True):
        self.api_id = api_id
        self.api_hash = api_hash
        self.auth_string = auth_string
        self.admin_list = admin_list
        self.is_bot_token = is_bot_token
        random_name = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=10))
        
        if is_bot_token:
            self.app = Client(random_name, api_id=int(api_id), api_hash=api_hash, bot_token=auth_string)
        else:
            self.app = Client(random_name, api_id=int(api_id), api_hash=api_hash, session_string=auth_string, in_memory=True)
        
        self.flask_thread = None
        self.download_pool = ThreadPoolExecutor(max_workers=20)
        
        if self.is_bot_token:
            @self.app.on_message(filters.private)
            async def _handle_message(client: Client, message: Message):
                global set_cmd
                if not set_cmd:
                    await self.lista_cmd()
                    set_cmd = True
                await self._handle_message(client, message)
        else:
            @self.app.on_message()
            async def _handle_user_message(client: Client, message: Message):
                await self._handle_user_message(client, message)
    
    def is_admin(self, user_id, username=None):
        for admin in self.admin_list:
            if str(admin) == str(user_id):
                return True
            if username and str(admin) == username:
                return True
        return False
    
    def is_premium(self, user_id):
        return user_id in premium_users
    
    async def lista_cmd(self):
        await self.app.set_bot_commands([
            BotCommand("start", "Iniciar el bot"),
            BotCommand("ls", "Lista archivos del directorio actual"),
            BotCommand("cd", "Cambia el directorio actual"),
            BotCommand("mkdir", "Crea una nueva carpeta en el directorio actual"),
            BotCommand("mv", "Renombra o mueve un archivo/carpeta"),
            BotCommand("zip", "Comprime archivos en zip"),
            BotCommand("7z", "Comprime archivos en 7z"),
            BotCommand("up", "Subir archivo al vault"),
            BotCommand("send", "Envia un archivo del directorio actual por numero")
        ])
        print("Comandos configurados en el bot")
    
    async def _handle_user_message(self, client: Client, message: Message):
        if not message.text:
            return
        text = message.text.strip()
        user_id = message.from_user.id
        username = message.from_user.username
        
        if text == ".enablepremium":
            if str(user_id) == "@me" or str(user_id) == "me":
                premium_users.add(user_id)
                await safe_call(message.reply_text, "✅ Modo premium activado. Puedes enviar archivos de hasta 3999 MB sin comprimir. Archivos mayores a 3999 MB se comprimiran en partes de 3995 MB.")
            else:
                await safe_call(message.reply_text, "❌ No tienes permiso para usar este comando.")
            return
        
        elif text == ".disablepremium":
            if str(user_id) == "@me" or str(user_id) == "me":
                if user_id in premium_users:
                    premium_users.remove(user_id)
                    await safe_call(message.reply_text, "✅ Modo premium desactivado. Limite normal restaurado (1995 MB).")
                else:
                    await safe_call(message.reply_text, "⚠️ El modo premium ya estaba desactivado.")
            else:
                await safe_call(message.reply_text, "❌ No tienes permiso para usar este comando.")
            return
        
        elif text.startswith("/start") or text.startswith(".start"):
            await safe_call(client.send_photo, chat_id=message.chat.id, photo="https://cdn.imgchest.com/files/93cb097b575e.webp", protect_content=True, caption="Nyaa, Hello, I'm Alice. The cute pet of @nakigeplayer")
            return
        
        elif text.startswith("/ls") or text.startswith(".ls") or text.startswith("/listfiles") or text.startswith(".listfiles"):
            current_dir = get_current_directory(user_id)
            if not os.path.exists(current_dir):
                await safe_call(message.reply_text, "El directorio no existe")
                return
            items = sort_directory(current_dir)
            if not items:
                await safe_call(message.reply_text, "El directorio esta vacio")
                return
            files_list = []
            for idx, item in enumerate(items, 1):
                item_path = os.path.join(current_dir, item)
                if os.path.isfile(item_path):
                    size = os.path.getsize(item_path)
                    size_mb = size / (1024 * 1024)
                    files_list.append(f"{idx}. {item} ({size_mb:.2f} MB)")
                else:
                    files_list.append(f"{idx}. {item}/")
            display_dir = get_public_path(current_dir)
            message_text = f"Directorio actual: {display_dir}\n\n" + "\n".join(files_list[:50])
            if len(files_list) > 50:
                message_text += f"\n\n... y {len(files_list) - 50} archivos mas"
            await safe_call(message.reply_text, message_text)
            return
        
        elif text.startswith("/send ") or text.startswith(".send "):
            parts = text.split()
            if len(parts) != 2:
                await safe_call(message.reply_text, "Usa: /send numero")
                return
            try:
                file_num = int(parts[1])
            except ValueError:
                await safe_call(message.reply_text, "El numero debe ser un entero valido")
                return
            current_dir = get_current_directory(user_id)
            if not os.path.exists(current_dir):
                await safe_call(message.reply_text, "El directorio no existe")
                return
            items = sort_directory(current_dir)
            if file_num < 1 or file_num > len(items):
                await safe_call(message.reply_text, f"Numero fuera de rango (1-{len(items)})")
                return
            selected_item = items[file_num - 1]
            item_path = os.path.join(current_dir, selected_item)
            if os.path.isfile(item_path):
                await self._send_document_with_progress(
                    message.chat.id,
                    item_path,
                    caption=f"{selected_item}",
                    user_id=user_id,
                    delete_after=False
                )
            elif os.path.isdir(item_path):
                await safe_call(message.reply_text, f"{selected_item} es una carpeta. Usa /ls para ver su contenido.")
            else:
                await safe_call(message.reply_text, "Archivo no encontrado")
            return
        
        elif text.startswith("/cd") or text.startswith(".cd"):
            parts = text.split()
            current_dir = get_current_directory(user_id)
            vault_dir = get_vault_dir()
            
            if len(parts) == 1:
                display_dir = get_public_path(current_dir)
                await safe_call(message.reply_text, f"Directorio actual: {display_dir}")
                return
            
            target = parts[1]
            
            if target == "/":
                set_current_directory(user_id, vault_dir)
                await safe_call(message.reply_text, "Cambiado a /")
                return
            
            if target == "0":
                parent_dir = os.path.dirname(current_dir)
                if parent_dir and os.path.exists(parent_dir) and parent_dir.startswith(vault_dir):
                    set_current_directory(user_id, parent_dir)
                    display_parent = get_public_path(parent_dir)
                    await safe_call(message.reply_text, f"Directorio cambiado a: {display_parent}")
                else:
                    await safe_call(message.reply_text, "No se puede retroceder mas alla de /")
                return
            
            try:
                target_num = int(target)
                items = sort_directory(current_dir)
                if 1 <= target_num <= len(items):
                    selected_item = items[target_num - 1]
                    target_path = os.path.join(current_dir, selected_item)
                    if os.path.isdir(target_path):
                        set_current_directory(user_id, target_path)
                        display_target = get_public_path(target_path)
                        await safe_call(message.reply_text, f"Directorio cambiado a: {display_target}")
                    else:
                        await safe_call(message.reply_text, "El ID indicado no es una carpeta")
                else:
                    await safe_call(message.reply_text, f"Numero fuera de rango (1-{len(items)})")
            except ValueError:
                await safe_call(message.reply_text, "El ID debe ser un numero o / para vault o 0 para retroceder")
            return
        
        elif text.startswith("/mkdir ") or text.startswith(".mkdir "):
            parts = text.split(maxsplit=1)
            if len(parts) < 2:
                await safe_call(message.reply_text, "Usa: /mkdir nombre_carpeta")
                return
            
            folder_name = parts[1].strip()
            current_dir = get_current_directory(user_id)
            new_folder_path = os.path.join(current_dir, folder_name)
            
            try:
                os.makedirs(new_folder_path, exist_ok=False)
                display_dir = get_public_path(current_dir)
                await safe_call(message.reply_text, f"Carpeta '{folder_name}' creada en {display_dir}")
            except FileExistsError:
                await safe_call(message.reply_text, f"La carpeta '{folder_name}' ya existe")
            except Exception as e:
                await safe_call(message.reply_text, f"Error al crear carpeta: {str(e)}")
            return
        
        elif text.startswith("/mv") or text.startswith(".mv"):
            parts = text.split()
            if len(parts) < 3:
                await safe_call(message.reply_text, "Usa: /mv # NuevoNombre o /mv #1 #2")
                return
            
            current_dir = get_current_directory(user_id)
            items = sort_directory(current_dir)
            
            try:
                source_num = int(parts[1])
                if source_num < 1 or source_num > len(items):
                    await safe_call(message.reply_text, f"Numero fuera de rango (1-{len(items)})")
                    return
                
                source_item = items[source_num - 1]
                source_path = os.path.join(current_dir, source_item)
                
                if len(parts) >= 3:
                    target = parts[2]
                    try:
                        target_num = int(target)
                        if target_num < 1 or target_num > len(items):
                            await safe_call(message.reply_text, f"Numero destino fuera de rango (1-{len(items)})")
                            return
                        target_item = items[target_num - 1]
                        target_path = os.path.join(current_dir, target_item)
                        if not os.path.isdir(target_path):
                            await safe_call(message.reply_text, "El destino debe ser una carpeta")
                            return
                        dest_path = os.path.join(target_path, source_item)
                        shutil.move(source_path, dest_path)
                        await safe_call(message.reply_text, f"Movido '{source_item}' a '{target_item}/'")
                    except ValueError:
                        new_name = " ".join(parts[2:])
                        dest_path = os.path.join(current_dir, new_name)
                        shutil.move(source_path, dest_path)
                        await safe_call(message.reply_text, f"Renombrado '{source_item}' a '{new_name}'")
                else:
                    await safe_call(message.reply_text, "Usa: /mv # NuevoNombre o /mv #1 #2")
            except ValueError:
                await safe_call(message.reply_text, "El numero debe ser un entero valido")
            except Exception as e:
                await safe_call(message.reply_text, f"Error: {str(e)}")
            return
        
        elif text.startswith("/zip ") or text.startswith(".zip "):
            parts = text.split()
            if len(parts) < 3:
                await safe_call(message.reply_text, "Usa: /zip # Nombre o /zip #,# Nombre")
                return
            
            current_dir = get_current_directory(user_id)
            items = sort_directory(current_dir)
            source_numbers = []
            archive_name = None
            
            i = 1
            while i < len(parts):
                if ',' in parts[i]:
                    nums = parts[i].split(',')
                    for num in nums:
                        try:
                            source_numbers.append(int(num))
                        except ValueError:
                            pass
                else:
                    try:
                        source_numbers.append(int(parts[i]))
                    except ValueError:
                        if archive_name is None:
                            archive_name = parts[i]
                        else:
                            archive_name = " ".join(parts[i:])
                            break
                i += 1
            
            if not source_numbers:
                await safe_call(message.reply_text, "No se especificaron numeros de archivo")
                return
            
            if not archive_name:
                archive_name = "archive"
            
            source_paths = []
            for num in source_numbers:
                if 1 <= num <= len(items):
                    item_path = os.path.join(current_dir, items[num-1])
                    source_paths.append(item_path)
                else:
                    await safe_call(message.reply_text, f"Numero {num} fuera de rango")
                    return
            
            if not source_paths:
                await safe_call(message.reply_text, "No se encontraron archivos validos")
                return
            
            status_msg = await safe_call(message.reply_text, f"Comprimiendo {len(source_paths)} archivos en zip...")
            
            archive_path = os.path.join(current_dir, f"{archive_name}.zip")
            with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_LZMA) as zipf:
                for src_path in source_paths:
                    zipf.write(src_path, os.path.basename(src_path))
            
            if os.path.exists(archive_path):
                await safe_call(status_msg.edit_text, f"Archivo comprimido: {archive_name}.zip en {get_public_path(current_dir)}")
            else:
                await safe_call(status_msg.edit_text, "Error al crear el archivo zip")
            
            await asyncio.sleep(3)
            await status_msg.delete()
            return
        
        elif text.startswith("/7z ") or text.startswith(".7z "):
            parts = text.split()
            if len(parts) < 3:
                await safe_call(message.reply_text, "Usa: /7z # Nombre o /7z #,# Nombre")
                return
            
            current_dir = get_current_directory(user_id)
            items = sort_directory(current_dir)
            source_numbers = []
            archive_name = None
            
            i = 1
            while i < len(parts):
                if ',' in parts[i]:
                    nums = parts[i].split(',')
                    for num in nums:
                        try:
                            source_numbers.append(int(num))
                        except ValueError:
                            pass
                else:
                    try:
                        source_numbers.append(int(parts[i]))
                    except ValueError:
                        if archive_name is None:
                            archive_name = parts[i]
                        else:
                            archive_name = " ".join(parts[i:])
                            break
                i += 1
            
            if not source_numbers:
                await safe_call(message.reply_text, "No se especificaron numeros de archivo")
                return
            
            if not archive_name:
                archive_name = "archive"
            
            source_paths = []
            for num in source_numbers:
                if 1 <= num <= len(items):
                    item_path = os.path.join(current_dir, items[num-1])
                    source_paths.append(item_path)
                else:
                    await safe_call(message.reply_text, f"Numero {num} fuera de rango")
                    return
            
            if not source_paths:
                await safe_call(message.reply_text, "No se encontraron archivos validos")
                return
            
            status_msg = await safe_call(message.reply_text, f"Comprimiendo {len(source_paths)} archivos en 7z...")
            
            sevenzz_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "7zz")
            if not os.path.exists(sevenzz_path):
                await safe_call(status_msg.edit_text, "7zz no encontrado")
                return
            
            try:
                os.chmod(sevenzz_path, os.stat(sevenzz_path).st_mode | stat.S_IEXEC)
            except:
                pass
            
            random_folder = os.path.join(tempfile.gettempdir(), str(uuid.uuid4())[:8])
            os.makedirs(random_folder, exist_ok=True)
            
            archive_base = os.path.join(random_folder, archive_name)
            cmd = [sevenzz_path, 'a', '-mx=5', archive_base] + source_paths
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            part_files = []
            for f in sorted(os.listdir(random_folder)):
                full_path = os.path.join(random_folder, f)
                if os.path.isfile(full_path):
                    part_files.append(full_path)
            
            if part_files:
                main_archive = part_files[0]
                final_path = os.path.join(current_dir, f"{archive_name}.7z")
                shutil.move(main_archive, final_path)
                for part in part_files[1:]:
                    os.remove(part)
                shutil.rmtree(random_folder, ignore_errors=True)
                
                await safe_call(status_msg.edit_text, f"Archivo comprimido: {archive_name}.7z en {get_public_path(current_dir)}")
            else:
                await safe_call(status_msg.edit_text, f"Error al crear el archivo 7z")
                shutil.rmtree(random_folder, ignore_errors=True)
            
            await asyncio.sleep(3)
            await status_msg.delete()
            return
        
        elif text.startswith("/up") or text.startswith(".up"):
            rm = message.reply_to_message
            if not rm or not (rm.document or rm.photo or rm.video or rm.audio or rm.voice or rm.sticker):
                await safe_call(message.reply_text, "Responde a un archivo con /up")
                return
            current_dir = get_current_directory(user_id)
            if rm.document:
                fname = rm.document.file_name
            elif rm.photo:
                fname = "photo.jpg"
            elif rm.video:
                fname = rm.video.file_name or "video.mp4"
            elif rm.audio:
                fname = rm.audio.file_name or "audio.mp3"
            elif rm.voice:
                fname = "voice.ogg"
            elif rm.sticker:
                fname = "sticker.webp"
            else:
                fname = "file.bin"
            target_path = os.path.join(current_dir, fname)
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            progress_msg = await safe_call(message.reply_text, "Iniciando descarga...")
            start_time = time.time()
            download_completed = False
            current_bytes = 0
            total_bytes = rm.document.file_size if rm.document else 0
            async def update_download_progress():
                nonlocal current_bytes, total_bytes, download_completed, start_time, progress_msg, target_path
                last_update = time.time()
                while not download_completed:
                    if total_bytes > 0:
                        elapsed = int(time.time() - start_time)
                        formatted_time = format_time(elapsed)
                        progress_ratio = current_bytes / total_bytes if total_bytes else 0
                        bar_length = 20
                        filled_length = int(bar_length * progress_ratio)
                        bar = "#" * filled_length + "-" * (bar_length - filled_length)
                        current_mb = current_bytes / (1024 * 1024)
                        total_mb = total_bytes / (1024 * 1024)
                        if time.time() - last_update >= 10:
                            await safe_call(
                                progress_msg.edit_text,
                                f"Descargando archivo...\n"
                                f"Tiempo: {formatted_time}\n"
                                f"Progreso: {current_mb:.2f} MB / {total_mb:.2f} MB\n"
                                f"[{bar}] {progress_ratio*100:.1f}%\n"
                                f"Velocidad: {(current_bytes/elapsed)/(1024*1024) if elapsed>0 else 0:.1f} MB/s\n"
                                f"Archivo: {os.path.basename(target_path)}"
                            )
                            last_update = time.time()
                    await asyncio.sleep(0.5)
            async def progress_callback(current, total):
                nonlocal current_bytes
                current_bytes = current
            asyncio.create_task(update_download_progress())
            await self.app.download_media(rm, file_name=target_path, progress=progress_callback)
            download_completed = True
            upload_msg = get_upload_message(target_path)
            await safe_call(progress_msg.edit_text, upload_msg)
            return
    
    async def _handle_message(self, client: Client, message: Message):
        if not message.text:
            return
        text = message.text.strip()
        user_id = message.from_user.id
        delete_after_send = "-d" in text
        text = text.replace("-d", "").strip()
        
        if text.startswith("/start"):
            await safe_call(client.send_photo, chat_id=message.chat.id, photo="https://cdn.imgchest.com/files/93cb097b575e.webp", protect_content=True, caption="Nyaa, Hello, I'm Alice. The cute pet of @nakigeplayer")
            return
        
        elif text.startswith("/ls") or text.startswith("/listfiles"):
            current_dir = get_current_directory(user_id)
            if not os.path.exists(current_dir):
                await safe_call(message.reply_text, "El directorio no existe")
                return
            items = sort_directory(current_dir)
            if not items:
                await safe_call(message.reply_text, "El directorio esta vacio")
                return
            files_list = []
            for idx, item in enumerate(items, 1):
                item_path = os.path.join(current_dir, item)
                if os.path.isfile(item_path):
                    size = os.path.getsize(item_path)
                    size_mb = size / (1024 * 1024)
                    files_list.append(f"{idx}. {item} ({size_mb:.2f} MB)")
                else:
                    files_list.append(f"{idx}. {item}/")
            display_dir = get_public_path(current_dir)
            message_text = f"Directorio actual: {display_dir}\n\n" + "\n".join(files_list[:50])
            if len(files_list) > 50:
                message_text += f"\n\n... y {len(files_list) - 50} archivos mas"
            await safe_call(message.reply_text, message_text)
            return
        
        elif text.startswith("/send "):
            parts = text.split()
            if len(parts) != 2:
                await safe_call(message.reply_text, "Usa: /send numero")
                return
            try:
                file_num = int(parts[1])
            except ValueError:
                await safe_call(message.reply_text, "El numero debe ser un entero valido")
                return
            current_dir = get_current_directory(user_id)
            if not os.path.exists(current_dir):
                await safe_call(message.reply_text, "El directorio no existe")
                return
            items = sort_directory(current_dir)
            if file_num < 1 or file_num > len(items):
                await safe_call(message.reply_text, f"Numero fuera de rango (1-{len(items)})")
                return
            selected_item = items[file_num - 1]
            item_path = os.path.join(current_dir, selected_item)
            if os.path.isfile(item_path):
                await self._send_document_with_progress(
                    message.chat.id,
                    item_path,
                    caption=f"{selected_item}",
                    user_id=user_id,
                    delete_after=delete_after_send
                )
            elif os.path.isdir(item_path):
                await safe_call(message.reply_text, f"{selected_item} es una carpeta. Usa /ls para ver su contenido.")
            else:
                await safe_call(message.reply_text, "Archivo no encontrado")
            return
        
        elif text.startswith("/cd"):
            parts = text.split()
            current_dir = get_current_directory(user_id)
            vault_dir = get_vault_dir()
            
            if len(parts) == 1:
                display_dir = get_public_path(current_dir)
                await safe_call(message.reply_text, f"Directorio actual: {display_dir}")
                return
            
            target = parts[1]
            
            if target == "/":
                set_current_directory(user_id, vault_dir)
                await safe_call(message.reply_text, "Cambiado a /")
                return
            
            if target == "0":
                parent_dir = os.path.dirname(current_dir)
                if parent_dir and os.path.exists(parent_dir) and parent_dir.startswith(vault_dir):
                    set_current_directory(user_id, parent_dir)
                    display_parent = get_public_path(parent_dir)
                    await safe_call(message.reply_text, f"Directorio cambiado a: {display_parent}")
                else:
                    await safe_call(message.reply_text, "No se puede retroceder mas alla de /")
                return
            
            try:
                target_num = int(target)
                items = sort_directory(current_dir)
                if 1 <= target_num <= len(items):
                    selected_item = items[target_num - 1]
                    target_path = os.path.join(current_dir, selected_item)
                    if os.path.isdir(target_path):
                        set_current_directory(user_id, target_path)
                        display_target = get_public_path(target_path)
                        await safe_call(message.reply_text, f"Directorio cambiado a: {display_target}")
                    else:
                        await safe_call(message.reply_text, "El ID indicado no es una carpeta")
                else:
                    await safe_call(message.reply_text, f"Numero fuera de rango (1-{len(items)})")
            except ValueError:
                await safe_call(message.reply_text, "El ID debe ser un numero o / para vault o 0 para retroceder")
            return
        
        elif text.startswith("/mkdir "):
            parts = text.split(maxsplit=1)
            if len(parts) < 2:
                await safe_call(message.reply_text, "Usa: /mkdir nombre_carpeta")
                return
            
            folder_name = parts[1].strip()
            current_dir = get_current_directory(user_id)
            new_folder_path = os.path.join(current_dir, folder_name)
            
            try:
                os.makedirs(new_folder_path, exist_ok=False)
                display_dir = get_public_path(current_dir)
                await safe_call(message.reply_text, f"Carpeta '{folder_name}' creada en {display_dir}")
            except FileExistsError:
                await safe_call(message.reply_text, f"La carpeta '{folder_name}' ya existe")
            except Exception as e:
                await safe_call(message.reply_text, f"Error al crear carpeta: {str(e)}")
            return
        
        elif text.startswith("/mv"):
            parts = text.split()
            if len(parts) < 3:
                await safe_call(message.reply_text, "Usa: /mv # NuevoNombre o /mv #1 #2")
                return
            
            current_dir = get_current_directory(user_id)
            items = sort_directory(current_dir)
            
            try:
                source_num = int(parts[1])
                if source_num < 1 or source_num > len(items):
                    await safe_call(message.reply_text, f"Numero fuera de rango (1-{len(items)})")
                    return
                
                source_item = items[source_num - 1]
                source_path = os.path.join(current_dir, source_item)
                
                if len(parts) >= 3:
                    target = parts[2]
                    try:
                        target_num = int(target)
                        if target_num < 1 or target_num > len(items):
                            await safe_call(message.reply_text, f"Numero destino fuera de rango (1-{len(items)})")
                            return
                        target_item = items[target_num - 1]
                        target_path = os.path.join(current_dir, target_item)
                        if not os.path.isdir(target_path):
                            await safe_call(message.reply_text, "El destino debe ser una carpeta")
                            return
                        dest_path = os.path.join(target_path, source_item)
                        shutil.move(source_path, dest_path)
                        await safe_call(message.reply_text, f"Movido '{source_item}' a '{target_item}/'")
                    except ValueError:
                        new_name = " ".join(parts[2:])
                        dest_path = os.path.join(current_dir, new_name)
                        shutil.move(source_path, dest_path)
                        await safe_call(message.reply_text, f"Renombrado '{source_item}' a '{new_name}'")
                else:
                    await safe_call(message.reply_text, "Usa: /mv # NuevoNombre o /mv #1 #2")
            except ValueError:
                await safe_call(message.reply_text, "El numero debe ser un entero valido")
            except Exception as e:
                await safe_call(message.reply_text, f"Error: {str(e)}")
            return
        
        elif text.startswith("/zip "):
            parts = text.split()
            if len(parts) < 3:
                await safe_call(message.reply_text, "Usa: /zip # Nombre o /zip #,# Nombre")
                return
            
            current_dir = get_current_directory(user_id)
            items = sort_directory(current_dir)
            source_numbers = []
            archive_name = None
            
            i = 1
            while i < len(parts):
                if ',' in parts[i]:
                    nums = parts[i].split(',')
                    for num in nums:
                        try:
                            source_numbers.append(int(num))
                        except ValueError:
                            pass
                else:
                    try:
                        source_numbers.append(int(parts[i]))
                    except ValueError:
                        if archive_name is None:
                            archive_name = parts[i]
                        else:
                            archive_name = " ".join(parts[i:])
                            break
                i += 1
            
            if not source_numbers:
                await safe_call(message.reply_text, "No se especificaron numeros de archivo")
                return
            
            if not archive_name:
                archive_name = "archive"
            
            source_paths = []
            for num in source_numbers:
                if 1 <= num <= len(items):
                    item_path = os.path.join(current_dir, items[num-1])
                    source_paths.append(item_path)
                else:
                    await safe_call(message.reply_text, f"Numero {num} fuera de rango")
                    return
            
            if not source_paths:
                await safe_call(message.reply_text, "No se encontraron archivos validos")
                return
            
            status_msg = await safe_call(message.reply_text, f"Comprimiendo {len(source_paths)} archivos en zip...")
            
            archive_path = os.path.join(current_dir, f"{archive_name}.zip")
            with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_LZMA) as zipf:
                for src_path in source_paths:
                    zipf.write(src_path, os.path.basename(src_path))
            
            if os.path.exists(archive_path):
                await safe_call(status_msg.edit_text, f"Archivo comprimido: {archive_name}.zip en {get_public_path(current_dir)}")
                if delete_after_send:
                    for src_path in source_paths:
                        try:
                            if os.path.isfile(src_path):
                                os.remove(src_path)
                            elif os.path.isdir(src_path):
                                shutil.rmtree(src_path)
                        except:
                            pass
                    await safe_call(message.reply_text, "Archivos originales eliminados")
            else:
                await safe_call(status_msg.edit_text, "Error al crear el archivo zip")
            
            await asyncio.sleep(3)
            await status_msg.delete()
            return
        
        elif text.startswith("/7z "):
            parts = text.split()
            if len(parts) < 3:
                await safe_call(message.reply_text, "Usa: /7z # Nombre o /7z #,# Nombre")
                return
            
            current_dir = get_current_directory(user_id)
            items = sort_directory(current_dir)
            source_numbers = []
            archive_name = None
            
            i = 1
            while i < len(parts):
                if ',' in parts[i]:
                    nums = parts[i].split(',')
                    for num in nums:
                        try:
                            source_numbers.append(int(num))
                        except ValueError:
                            pass
                else:
                    try:
                        source_numbers.append(int(parts[i]))
                    except ValueError:
                        if archive_name is None:
                            archive_name = parts[i]
                        else:
                            archive_name = " ".join(parts[i:])
                            break
                i += 1
            
            if not source_numbers:
                await safe_call(message.reply_text, "No se especificaron numeros de archivo")
                return
            
            if not archive_name:
                archive_name = "archive"
            
            source_paths = []
            for num in source_numbers:
                if 1 <= num <= len(items):
                    item_path = os.path.join(current_dir, items[num-1])
                    source_paths.append(item_path)
                else:
                    await safe_call(message.reply_text, f"Numero {num} fuera de rango")
                    return
            
            if not source_paths:
                await safe_call(message.reply_text, "No se encontraron archivos validos")
                return
            
            status_msg = await safe_call(message.reply_text, f"Comprimiendo {len(source_paths)} archivos en 7z...")
            
            sevenzz_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "7zz")
            if not os.path.exists(sevenzz_path):
                await safe_call(status_msg.edit_text, "7zz no encontrado")
                return
            
            try:
                os.chmod(sevenzz_path, os.stat(sevenzz_path).st_mode | stat.S_IEXEC)
            except:
                pass
            
            random_folder = os.path.join(tempfile.gettempdir(), str(uuid.uuid4())[:8])
            os.makedirs(random_folder, exist_ok=True)
            
            archive_base = os.path.join(random_folder, archive_name)
            cmd = [sevenzz_path, 'a', '-mx=5', archive_base] + source_paths
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            part_files = []
            for f in sorted(os.listdir(random_folder)):
                full_path = os.path.join(random_folder, f)
                if os.path.isfile(full_path):
                    part_files.append(full_path)
            
            if part_files:
                main_archive = part_files[0]
                final_path = os.path.join(current_dir, f"{archive_name}.7z")
                shutil.move(main_archive, final_path)
                for part in part_files[1:]:
                    os.remove(part)
                shutil.rmtree(random_folder, ignore_errors=True)
                
                await safe_call(status_msg.edit_text, f"Archivo comprimido: {archive_name}.7z en {get_public_path(current_dir)}")
                if delete_after_send:
                    for src_path in source_paths:
                        try:
                            if os.path.isfile(src_path):
                                os.remove(src_path)
                            elif os.path.isdir(src_path):
                                shutil.rmtree(src_path)
                        except:
                            pass
                    await safe_call(message.reply_text, "Archivos originales eliminados")
            else:
                await safe_call(status_msg.edit_text, f"Error al crear el archivo 7z")
                shutil.rmtree(random_folder, ignore_errors=True)
            
            await asyncio.sleep(3)
            await status_msg.delete()
            return
        
        elif text.startswith("/up"):
            rm = message.reply_to_message
            if not rm or not (rm.document or rm.photo or rm.video or rm.audio or rm.voice or rm.sticker):
                await safe_call(message.reply_text, "Responde a un archivo con /up")
                return
            current_dir = get_current_directory(user_id)
            if rm.document:
                fname = rm.document.file_name
            elif rm.photo:
                fname = "photo.jpg"
            elif rm.video:
                fname = rm.video.file_name or "video.mp4"
            elif rm.audio:
                fname = rm.audio.file_name or "audio.mp3"
            elif rm.voice:
                fname = "voice.ogg"
            elif rm.sticker:
                fname = "sticker.webp"
            else:
                fname = "file.bin"
            target_path = os.path.join(current_dir, fname)
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            progress_msg = await safe_call(message.reply_text, "Iniciando descarga...")
            start_time = time.time()
            download_completed = False
            current_bytes = 0
            total_bytes = rm.document.file_size if rm.document else 0
            async def update_download_progress():
                nonlocal current_bytes, total_bytes, download_completed, start_time, progress_msg, target_path
                last_update = time.time()
                while not download_completed:
                    if total_bytes > 0:
                        elapsed = int(time.time() - start_time)
                        formatted_time = format_time(elapsed)
                        progress_ratio = current_bytes / total_bytes if total_bytes else 0
                        bar_length = 20
                        filled_length = int(bar_length * progress_ratio)
                        bar = "#" * filled_length + "-" * (bar_length - filled_length)
                        current_mb = current_bytes / (1024 * 1024)
                        total_mb = total_bytes / (1024 * 1024)
                        if time.time() - last_update >= 10:
                            await safe_call(
                                progress_msg.edit_text,
                                f"Descargando archivo...\n"
                                f"Tiempo: {formatted_time}\n"
                                f"Progreso: {current_mb:.2f} MB / {total_mb:.2f} MB\n"
                                f"[{bar}] {progress_ratio*100:.1f}%\n"
                                f"Velocidad: {(current_bytes/elapsed)/(1024*1024) if elapsed>0 else 0:.1f} MB/s\n"
                                f"Archivo: {os.path.basename(target_path)}"
                            )
                            last_update = time.time()
                    await asyncio.sleep(0.5)
            async def progress_callback(current, total):
                nonlocal current_bytes
                current_bytes = current
            asyncio.create_task(update_download_progress())
            await self.app.download_media(rm, file_name=target_path, progress=progress_callback)
            download_completed = True
            upload_msg = get_upload_message(target_path)
            await safe_call(progress_msg.edit_text, upload_msg)
            if delete_after_send:
                try:
                    os.remove(target_path)
                    await safe_call(message.reply_text, "Archivo eliminado despues de subir")
                except:
                    pass
            return
    
    async def _send_document_with_progress(self, chat_id, document_path, caption="", thumb=None, reply_to_message_id=None, user_id=None, delete_after=False):
        if not os.path.exists(document_path):
            print(f"Archivo no existe: {document_path}")
            await safe_call(self.app.send_message, chat_id, f"Error: Archivo no encontrado: {os.path.basename(document_path)}")
            return
        
        file_size_mb = os.path.getsize(document_path) / (1024 * 1024)
        
        is_premium_user = self.is_premium(user_id) if user_id else False
        
        if not is_premium_user and file_size_mb > 1995:
            parts = compress_with_7zz(document_path, 1995)
            if parts:
                for part in parts:
                    await safe_call(
                        self.app.send_document,
                        chat_id=chat_id,
                        document=part,
                        caption=f"{caption} (parte {os.path.basename(part)})"
                    )
                    try:
                        os.remove(part)
                    except:
                        pass
                if delete_after:
                    try:
                        os.remove(document_path)
                    except:
                        pass
                return
        elif is_premium_user and file_size_mb > 3999:
            parts = compress_with_7zz(document_path, 3995)
            if parts:
                for part in parts:
                    await safe_call(
                        self.app.send_document,
                        chat_id=chat_id,
                        document=part,
                        caption=f"{caption} (parte {os.path.basename(part)})"
                    )
                    try:
                        os.remove(part)
                    except:
                        pass
                if delete_after:
                    try:
                        os.remove(document_path)
                    except:
                        pass
                return
        
        progress_msg = await safe_call(self.app.send_message, chat_id, "Preparando envio...")
        start_time = time.time()
        upload_completed = False
        current_bytes = 0
        total_bytes = os.path.getsize(document_path)
        
        async def update_upload_progress():
            nonlocal upload_completed, current_bytes, start_time, total_bytes, progress_msg, document_path
            last_update = time.time()
            while not upload_completed:
                if total_bytes > 0:
                    elapsed = int(time.time() - start_time)
                    if elapsed == 0:
                        speed = 0
                    else:
                        speed = (current_bytes / elapsed) / (1024 * 1024)
                    formatted_time = format_time(elapsed)
                    progress_ratio = current_bytes / total_bytes if total_bytes else 0
                    bar_length = 20
                    filled_length = int(bar_length * progress_ratio)
                    bar = "#" * filled_length + "-" * (bar_length - filled_length)
                    current_mb = current_bytes / (1024 * 1024)
                    total_mb = total_bytes / (1024 * 1024)
                    if time.time() - last_update >= 10:
                        progress_text = (
                            f"Enviando archivo...\n"
                            f"Tiempo: {formatted_time}\n"
                            f"Progreso: {current_mb:.2f} MB / {total_mb:.2f} MB\n"
                            f"[{bar}] {progress_ratio*100:.1f}%\n"
                            f"Velocidad: {speed:.1f} MB/s\n"
                            f"Archivo: {os.path.basename(document_path)}"
                        )
                        await safe_call(progress_msg.edit_text, progress_text)
                        last_update = time.time()
                await asyncio.sleep(1)
        
        def upload_progress(current, total):
            nonlocal current_bytes
            current_bytes = current
        
        upload_task = asyncio.create_task(update_upload_progress())
        try:
            await safe_call(
                self.app.send_document,
                chat_id=chat_id,
                document=document_path,
                caption=caption,
                thumb=thumb,
                progress=upload_progress
            )
            upload_completed = True
            await upload_task
            try:
                await safe_call(progress_msg.delete)
            except:
                pass
            if delete_after:
                try:
                    os.remove(document_path)
                except:
                    pass
        except Exception as e:
            upload_completed = True
            await upload_task
            try:
                await safe_call(progress_msg.delete)
            except:
                pass
            print(f"Error enviando documento: {e}")
            try:
                await safe_call(
                    self.app.send_document,
                    chat_id=chat_id,
                    document=document_path,
                    caption=caption,
                    thumb=thumb
                )
                if delete_after and os.path.exists(document_path):
                    os.remove(document_path)
            except Exception as e2:
                print(f"Error en reintento: {e2}")
                raise
    
    def start_flask(self, port):
        if self.flask_thread and self.flask_thread.is_alive():
            print("Flask ya esta corriendo")
            return
        self.flask_thread = threading.Thread(target=run_flask, args=(port,), daemon=True)
        self.flask_thread.start()
        print(f"Servidor Flask iniciado en puerto {port}.")
    
    def run(self):
        print("Iniciando cliente de Telegram...")
        self.app.run()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-A", "--api", help="API ID de Telegram")
    parser.add_argument("-H", "--hash", help="API Hash de Telegram")
    parser.add_argument("-T", "--token", help="Token del Bot")
    parser.add_argument("-SS", "--session", help="Session String para usuario")
    parser.add_argument("-F", "--flask", nargs='?', const=5000, type=int, help="Puerto para Flask (ej: -F 5005)")
    parser.add_argument("-admin", "--admin", action="append", help="Administradores (ID o username)")
    args = parser.parse_args()
    
    api_id = args.api or os.environ.get("API_ID")
    api_hash = args.hash or os.environ.get("API_HASH")
    bot_token = args.token or os.environ.get("BOT_TOKEN")
    session_string = args.session or os.environ.get("SESSION_STRING")
    admin_list = args.admin if args.admin else []
    
    if not all([api_id, api_hash]):
        print("Error: Faltan API_ID y API_HASH. Usa -A -H o variables de entorno.")
        sys.exit(1)
    
    if not (bot_token or session_string):
        print("Error: Debes especificar -T (token) o -SS (session string)")
        sys.exit(1)
    
    if bot_token and session_string:
        print("Error: No puedes usar -T y -SS al mismo tiempo")
        sys.exit(1)
    
    is_bot = bool(bot_token)
    auth_string = bot_token if is_bot else session_string
    
    bot = NekoTelegram(api_id, api_hash, auth_string, admin_list, is_bot_token=is_bot)
    
    if args.flask is not None:
        bot.start_flask(args.flask)
    
    print("Iniciando cliente de Telegram...")
    bot.run()

if __name__ == "__main__":
    main()
