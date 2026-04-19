import os
import asyncio
import tempfile
import shutil
import re
from pyrogram.types import Message

class FileCommands:
    def __init__(self, bot):
        self.bot = bot
    
    async def listfiles(self, message):
        vault_dir = os.path.join(os.getcwd(), "vault")
        if not os.path.exists(vault_dir):
            await self.bot.safe_call(message.reply_text, "❌ La carpeta vault no existe")
            return
        items = self.bot.neko.sort_directory(vault_dir)
        if not items:
            await self.bot.safe_call(message.reply_text, "❌ La carpeta vault está vacía")
            return
        files_list = []
        for idx, item in enumerate(items, 1):
            item_path = os.path.join(vault_dir, item)
            if os.path.isfile(item_path):
                size = os.path.getsize(item_path)
                size_mb = size / (1024 * 1024)
                files_list.append(f"{idx}. {item} ({size_mb:.2f} MB)")
            else:
                files_list.append(f"{idx}. 📁 {item}/")
        message_text = "📁 **Archivos en vault:**\n\n" + "\n".join(files_list[:50])
        if len(files_list) > 50:
            message_text += f"\n\n... y {len(files_list) - 50} archivos más"
        await self.bot.safe_call(message.reply_text, message_text)
    
    async def cookies(self, message):
        if not message.reply_to_message or not message.reply_to_message.document:
            await self.bot.safe_call(message.reply_text, "❌ Responde a un archivo con /cookies")
            return
        progress_msg = await self.bot.safe_call(message.reply_text, "📥 Descargando archivo cookies...")
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        temp_path = temp_file.name
        temp_file.close()
        await message.reply_to_message.download(file_name=temp_path)
        SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
        DATA_DIR = os.path.join(SCRIPT_DIR, "data")
        os.makedirs(DATA_DIR, exist_ok=True)
        cookies_path = os.path.join(DATA_DIR, "cookies.txt")
        shutil.move(temp_path, cookies_path)
        await self.bot.safe_call(progress_msg.edit_text, "✅ Archivo cookies.txt guardado correctamente en /data/")
    
    async def ytv(self, message, user_id):
        import dlyt
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            await self.bot.safe_call(message.reply_text, "❌ Usa: /ytv URL")
            return
        url = parts[1].strip()
        progress_msg = await self.bot.safe_call(message.reply_text, "📥 Descargando video...")
        try:
            archivo = dlyt.yt_video(url)
            if archivo is False:
                await self.bot.safe_call(progress_msg.edit_text, "❌ Error: cookies.txt no encontrado")
                return
            await self.bot.safe_call(progress_msg.delete)
            if os.path.exists(archivo):
                await self.bot._send_document_with_progress(message.chat.id, archivo, f"🎬 {os.path.basename(archivo)}", user_id=user_id)
            else:
                await self.bot.safe_call(message.reply_text, f"✅ Video descargado: {archivo}")
        except Exception as e:
            await self.bot.safe_call(progress_msg.edit_text, f"❌ Error: {str(e)}")
    
    async def yta(self, message, user_id):
        import dlyt
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            await self.bot.safe_call(message.reply_text, "❌ Usa: /yta URL")
            return
        url = parts[1].strip()
        progress_msg = await self.bot.safe_call(message.reply_text, "📥 Descargando audio...")
        try:
            archivo = dlyt.yt_audio(url)
            if archivo is False:
                await self.bot.safe_call(progress_msg.edit_text, "❌ Error: cookies.txt no encontrado")
                return
            await self.bot.safe_call(progress_msg.delete)
            if os.path.exists(archivo):
                await self.bot._send_document_with_progress(message.chat.id, archivo, f"🎵 {os.path.basename(archivo)}", user_id=user_id)
            else:
                await self.bot.safe_call(message.reply_text, f"✅ Audio descargado: {archivo}")
        except Exception as e:
            await self.bot.safe_call(progress_msg.edit_text, f"❌ Error: {str(e)}")
    
    async def mp3(self, message):
        from telebot import convert_video_to_mp3
        if message.reply_to_message:
            reply = message.reply_to_message
            video_file = None
            
            if reply.video:
                video_file = reply.video
            elif reply.document and reply.document.mime_type and reply.document.mime_type.startswith("video/"):
                video_file = reply.document
            else:
                await self.bot.safe_call(message.reply_text, "❌ Responde a un video o archivo de video con /mp3")
                return
            
            parts = message.text.split(maxsplit=1)
            metadata = {}
            custom_filename = None
            
            if len(parts) > 1:
                args = parts[1]
                if "-f" in args:
                    match = re.search(r'-f "([^"]+)"', args)
                    if match:
                        custom_filename = match.group(1)
                if "-n" in args:
                    match = re.search(r'-n "([^"]+)"', args)
                    if match:
                        metadata['title'] = match.group(1)
                if "-a" in args:
                    match = re.search(r'-a "([^"]+)"', args)
                    if match:
                        metadata['artist'] = match.group(1)
                if "-A" in args:
                    match = re.search(r'-A "([^"]+)"', args)
                    if match:
                        metadata['album'] = match.group(1)
                if "-y" in args:
                    match = re.search(r'-y "(\d{4})"', args)
                    if match:
                        metadata['year'] = match.group(1)
                if "-c" in args:
                    match = re.search(r'-c "([^"]+)"', args)
                    if match:
                        metadata['cover'] = match.group(1)
            
            progress_msg = await self.bot.safe_call(message.reply_text, "📥 Descargando video...")
            
            temp_video = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
            temp_video_path = temp_video.name
            temp_video.close()
            
            await self.bot.app.download_media(video_file, file_name=temp_video_path)
            
            await self.bot.safe_call(progress_msg.edit_text, "🎵 Convirtiendo a MP3...")
            
            if custom_filename:
                temp_audio = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3", prefix=custom_filename)
            else:
                temp_audio = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
            temp_audio_path = temp_audio.name
            temp_audio.close()
            
            try:
                output_path = await convert_video_to_mp3(temp_video_path, temp_audio_path, metadata)
                
                await self.bot.safe_call(progress_msg.edit_text, "📤 Enviando audio...")
                
                await self.bot.safe_call(
                    message.reply_audio,
                    audio=output_path,
                    caption="🎵 Audio convertido desde video"
                )
                
                await self.bot.safe_call(progress_msg.delete)
                
            except Exception as e:
                await self.bot.safe_call(progress_msg.edit_text, f"❌ Error: {str(e)}")
            finally:
                if os.path.exists(temp_video_path):
                    os.remove(temp_video_path)
                if os.path.exists(temp_audio_path):
                    os.remove(temp_audio_path)
        else:
            await self.bot.safe_call(message.reply_text, "❌ Responde a un video o archivo de video con /mp3")
    
    async def sendfile(self, message, user_id):
        parts = message.text.split()
        if len(parts) != 2:
            await self.bot.safe_call(message.reply_text, "Usa: `/sendfile número`")
            return
        try:
            file_num = int(parts[1])
        except ValueError:
            await self.bot.safe_call(message.reply_text, "❌ El número debe ser un entero válido")
            return
        vault_dir = os.path.join(os.getcwd(), "vault")
        if not os.path.exists(vault_dir):
            await self.bot.safe_call(message.reply_text, "❌ La carpeta vault no existe")
            return
        items = self.bot.neko.sort_directory(vault_dir)
        if file_num < 1 or file_num > len(items):
            await self.bot.safe_call(message.reply_text, f"❌ Número fuera de rango (1-{len(items)})")
            return
        selected_item = items[file_num - 1]
        item_path = os.path.join(vault_dir, selected_item)
        if os.path.isfile(item_path):
            await self.bot._send_document_with_progress(
                message.chat.id,
                item_path,
                caption=f"📄 {selected_item}",
                user_id=user_id
            )
        elif os.path.isdir(item_path):
            await self.bot.safe_call(message.reply_text, f"📁 {selected_item} es una carpeta. Usa /listfiles para ver su contenido.")
        else:
            await self.bot.safe_call(message.reply_text, "❌ Archivo no encontrado")
    
    async def up(self, message, user_id, user_nextnames):
        parts = message.text.split(maxsplit=1)
        custom_path = parts[1].strip() if len(parts) > 1 else None
        rm = message.reply_to_message
        if not rm or not (rm.document or rm.photo or rm.video or rm.audio or rm.voice or rm.sticker):
            await self.bot.safe_call(message.reply_text, "Responde a un archivo con /up")
            return
        vault_dir = os.path.join(os.getcwd(), "vault")
        if user_id in user_nextnames:
            pattern_info = user_nextnames[user_id]
            pattern = pattern_info["pattern"]
            current = pattern_info["current"]
            start = pattern_info["start"]
            end = pattern_info["end"]
            if current > end:
                await self.bot.safe_call(message.reply_text, f"✅ Secuencia completada ({start}-{end})")
                del user_nextnames[user_id]
                return
            filename = pattern.replace("{no}", str(current).zfill(len(str(start)) if str(start).startswith("0") else 1))
            user_nextnames[user_id]["current"] = current + 1
            target_path = os.path.join(vault_dir, filename)
        else:
            if custom_path:
                target_path = os.path.join(vault_dir, custom_path)
            else:
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
                target_path = os.path.join(vault_dir, fname)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        progress_msg = await self.bot.safe_call(message.reply_text, "📥 Iniciando descarga...")
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
                    if elapsed == 0:
                        speed = 0
                    else:
                        speed = (current_bytes / elapsed) / (1024 * 1024)
                    formatted_time = format_time(elapsed)
                    progress_ratio = current_bytes / total_bytes if total_bytes else 0
                    bar_length = 20
                    filled_length = int(bar_length * progress_ratio)
                    bar = "█" * filled_length + "▒" * (bar_length - filled_length)
                    current_mb = current_bytes / (1024 * 1024)
                    total_mb = total_bytes / (1024 * 1024)
                    if time.time() - last_update >= 10:
                        await self.bot.safe_call(
                            progress_msg.edit_text,
                            f"📥 Descargando archivo...\n"
                            f"🕒 Tiempo: {formatted_time}\n"
                            f"📊 Progreso: {current_mb:.2f} MB / {total_mb:.2f} MB\n"
                            f"📉 [{bar}] {progress_ratio*100:.1f}%\n"
                            f"📄 Archivo: {os.path.basename(target_path)}"
                        )
                        last_update = time.time()
                await asyncio.sleep(0.5)
        async def progress_callback(current, total):
            nonlocal current_bytes
            current_bytes = current
        asyncio.create_task(update_download_progress())
        await self.bot.app.download_media(rm, file_name=target_path, progress=progress_callback)
        download_completed = True
        if user_id in user_nextnames:
            next_num = user_nextnames[user_id]["current"]
            end_num = user_nextnames[user_id]["end"]
            if next_num <= end_num:
                await self.bot.safe_call(progress_msg.edit_text, f"✅ Archivo guardado como `{os.path.basename(target_path)}`\nPróximo: {next_num}/{end_num}")
            else:
                await self.bot.safe_call(progress_msg.edit_text, f"✅ Archivo guardado como `{os.path.basename(target_path)}`\n✅ Secuencia completada")
                del user_nextnames[user_id]
        else:
            await self.bot.safe_call(progress_msg.edit_text, f"✅ Archivo guardado en `{target_path}`")