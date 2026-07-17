import os
import asyncio
import sys
import argparse
import shutil
import tempfile
import time
from pyrogram import Client, filters
from pyrogram.types import Message, BotCommand
from pyrogram.errors import FloodWait

class NekoTelegram:
    def __init__(self, api_id, api_hash, bot_token, admin_list):
        self.api_id = api_id
        self.api_hash = api_hash
        self.bot_token = bot_token
        self.admin_list = admin_list
        self.app = Client("nekobot", api_id=int(api_id), api_hash=api_hash, bot_token=bot_token)

        @self.app.on_message(filters.private)
        async def _handle_message(client: Client, message: Message):
            await self._handle_message(client, message)

    async def safe_call(self, func, *args, **kwargs):
        while True:
            try:
                return await func(*args, **kwargs)
            except FloodWait as e:
                await asyncio.sleep(e.value)
            except Exception:
                raise

    async def lista_cmd(self):
        await self.app.set_bot_commands([
            BotCommand("start", "Inicio"),
            BotCommand("up", "Subir archivo al vault"),
            BotCommand("drive", "Subir y mover a Google Drive")
        ])

    async def _handle_message(self, client: Client, message: Message):
        if not message.text:
            return
        text = message.text.strip()

        if text.startswith("/start"):
            await self.safe_call(client.send_photo, chat_id=message.chat.id, photo="https://cdn.imgchest.com/files/93cb097b575e.webp", protect_content=True, caption="Nyaa, Hello, I'm Alice. The cute pet of @nakigeplayer")
            return

        elif text.startswith("/up"):
            await self._handle_up(message, drive_mode=False)
            return

        elif text.startswith("/drive"):
            await self._handle_up(message, drive_mode=True)
            return

    async def _handle_up(self, message: Message, drive_mode: bool = False):
        parts = message.text.split(maxsplit=1)
        custom_path = parts[1].strip() if len(parts) > 1 else None
        rm = message.reply_to_message
        if not rm or not (rm.document or rm.photo or rm.video or rm.audio or rm.voice or rm.sticker):
            await self.safe_call(message.reply_text, "Responde a un archivo con /up o /drive")
            return

        user_id = message.from_user.id
        current_dir = os.path.join(os.getcwd(), "vault")
        os.makedirs(current_dir, exist_ok=True)

        if rm.document:
            fname = rm.document.file_name or "file.bin"
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

        if custom_path:
            target_path = os.path.join(current_dir, custom_path)
        else:
            target_path = os.path.join(current_dir, fname)

        os.makedirs(os.path.dirname(target_path), exist_ok=True)

        progress_msg = await self.safe_call(message.reply_text, "📥 Iniciando descarga...")

        start_time = time.time()
        download_completed = False
        current_bytes = 0
        total_bytes = rm.document.file_size if rm.document else 0

        async def update_download_progress():
            nonlocal current_bytes, download_completed
            last_update = time.time()
            while not download_completed:
                if total_bytes > 0 and time.time() - last_update >= 5:
                    elapsed = int(time.time() - start_time)
                    progress_ratio = current_bytes / total_bytes
                    current_mb = current_bytes / (1024 * 1024)
                    total_mb = total_bytes / (1024 * 1024)
                    await self.safe_call(progress_msg.edit_text, f"📥 Descargando...\n{current_mb:.2f}/{total_mb:.2f} MB ({progress_ratio*100:.1f}%)")
                    last_update = time.time()
                await asyncio.sleep(0.5)

        async def progress_callback(current, total):
            nonlocal current_bytes
            current_bytes = current

        asyncio.create_task(update_download_progress())

        await self.app.download_media(rm, file_name=target_path, progress=progress_callback)
        download_completed = True

        if drive_mode:
            drive_folder = "/content/drive/MyDrive/TelegramBot"
            os.makedirs(drive_folder, exist_ok=True)
            final_drive_path = os.path.join(drive_folder, os.path.basename(target_path))
            shutil.move(target_path, final_drive_path)
            await self.safe_call(progress_msg.edit_text, f"✅ Archivo movido a Google Drive:\n`{final_drive_path}`")
        else:
            await self.safe_call(progress_msg.edit_text, f"✅ Archivo guardado en vault:\n`{target_path}`")

    def run(self):
        self.app.run()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-A", "--api", help="API ID")
    parser.add_argument("-H", "--hash", help="API Hash")
    parser.add_argument("-T", "--token", help="Bot Token")
    args = parser.parse_args()

    api_id = args.api or os.environ.get("API_ID")
    api_hash = args.hash or os.environ.get("API_HASH")
    bot_token = args.token or os.environ.get("BOT_TOKEN")

    if not all([api_id, api_hash, bot_token]):
        print("Faltan credenciales")
        sys.exit(1)

    bot = NekoTelegram(api_id, api_hash, bot_token, [])
    bot.run()

if __name__ == "__main__":
    main()
