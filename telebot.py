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
import nest_asyncio
from concurrent.futures import ThreadPoolExecutor
from pyrogram import Client, filters
from pyrogram.types import Message, BotCommand
from pyrogram.errors import FloodWait

nest_asyncio.apply()

set_cmd = False
current_directories = {}
ftp_base_url = None

def run_flask():
    from flask import Flask
    app_flask = Flask(__name__)
    
    @app_flask.route('/')
    def index():
        return "Funcionando"
    
    app_flask.run(host='0.0.0.0', port=5000)

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

def compress_with_7zz(file_path, output_name=None):
    sevenzz_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "7zz")
    if not os.path.exists(sevenzz_path):
        return None
    try:
        os.chmod(sevenzz_path, os.stat(sevenzz_path).st_mode | stat.S_IEXEC)
    except:
        pass
    
    if output_name is None:
        output_name = os.path.splitext(os.path.basename(file_path))[0]
    
    output_dir = os.path.dirname(file_path)
    output_path = os.path.join(output_dir, f"{output_name}.7z")
    
    cmd = [sevenzz_path, 'a', '-mx=0', output_path, file_path]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            return output_path
        return None
    except Exception as e:
        print(f"Error comprimiendo con 7zz: {e}")
        return None

def get_current_directory(user_id):
    if user_id not in current_directories:
        vault_dir = os.path.join(os.getcwd(), "vault")
        os.makedirs(vault_dir, exist_ok=True)
        current_directories[user_id] = vault_dir
    return current_directories[user_id]

def set_current_directory(user_id, path):
    current_directories[user_id] = path

def get_public_path(absolute_path):
    vault_dir = os.path.join(os.getcwd(), "vault")
    if absolute_path.startswith(vault_dir):
        relative = os.path.relpath(absolute_path, vault_dir)
        if relative == '.':
            return '/'
        return '/' + relative.replace('\\', '/')
    return absolute_path

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
    def __init__(self, api_id, api_hash, bot_token, admin_list):
        self.api_id = api_id
        self.api_hash = api_hash
        self.bot_token = bot_token
        self.admin_list = admin_list
        self.app = Client("nekobot", api_id=int(api_id), api_hash=api_hash, bot_token=bot_token)
        self.flask_thread = None
        self.download_pool = ThreadPoolExecutor(max_workers=20)
        
        @self.app.on_message(filters.private)
        async def _handle_message(client: Client, message: Message):
            global set_cmd
            if not set_cmd:
                await self.lista_cmd()
                set_cmd = True
            await self._handle_message(client, message)
    
    def is_admin(self, user_id, username=None):
        for admin in self.admin_list:
            if str(admin) == str(user_id):
                return True
            if username and str(admin) == username:
                return True
        return False
    
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
    
    async def _handle_message(self, client: Client, message: Message):
        if not message.text:
            return
        text = message.text.strip()
        user_id = message.from_user.id
        username = message.from_user.username

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
                    user_id=user_id
                )
            elif os.path.isdir(item_path):
                await safe_call(message.reply_text, f"{selected_item} es una carpeta. Usa /ls para ver su contenido.")
            else:
                await safe_call(message.reply_text, "Archivo no encontrado")
            return

        elif text.startswith("/cd"):
            parts = text.split()
            current_dir = get_current_directory(user_id)
            vault_dir = os.path.join(os.getcwd(), "vault")
            
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
            
            archive_path = os.path.join(current_dir, f"{archive_name}.7z")
            cmd = [sevenzz_path, 'a', '-mx=5', archive_path] + source_paths
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0 and os.path.exists(archive_path):
                await safe_call(status_msg.edit_text, f"Archivo comprimido: {archive_name}.7z en {get_public_path(current_dir)}")
            else:
                await safe_call(status_msg.edit_text, f"Error al crear el archivo 7z: {result.stderr}")
            
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
            return
    
    async def _send_document_with_progress(self, chat_id, document_path, caption="", thumb=None, reply_to_message_id=None, user_id=None):
        if not os.path.exists(document_path):
            print(f"Archivo no existe: {document_path}")
            await safe_call(self.app.send_message, chat_id, f"Error: Archivo no encontrado: {os.path.basename(document_path)}")
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
                if os.path.exists(document_path):
                    os.remove(document_path)
            except Exception as e2:
                print(f"Error en reintento: {e2}")
                raise
    
    def start_flask(self):
        if self.flask_thread and self.flask_thread.is_alive():
            print("Flask ya esta corriendo")
            return
        self.flask_thread = threading.Thread(target=run_flask, daemon=True)
        self.flask_thread.start()
        print("Servidor Flask iniciado en puerto 5000.")
    
    def run(self):
        print("Iniciando bot de Telegram...")
        self.app.run()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-A", "--api", help="API ID de Telegram")
    parser.add_argument("-H", "--hash", help="API Hash de Telegram")
    parser.add_argument("-T", "--token", help="Token del Bot")
    parser.add_argument("-F", "--flask", action="store_true", help="Incluir servidor Flask junto con el bot")
    parser.add_argument("-admin", "--admin", action="append", help="Administradores (ID o username)")
    args = parser.parse_args()
    
    api_id = args.api or os.environ.get("API_ID")
    api_hash = args.hash or os.environ.get("API_HASH")
    bot_token = args.token or os.environ.get("BOT_TOKEN")
    admin_list = args.admin if args.admin else []
    
    if not all([api_id, api_hash, bot_token]):
        print("Error: Faltan credenciales. Usa -A -H -T o variables de entorno.")
        sys.exit(1)
    
    bot = NekoTelegram(api_id, api_hash, bot_token, admin_list)
    if args.flask:
        bot.start_flask()
    
    print("Iniciando bot de Telegram...")
    bot.run()

if __name__ == "__main__":
    main()
