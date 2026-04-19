
import os
import asyncio
import tempfile
import shutil
import zipfile
import aiohttp
import bencodepy
import hashlib
from pyrogram.types import Message

class TorrentDownloadCommands:
    def __init__(self, bot):
        self.bot = bot
        self.neko = bot.neko
    
    async def leech(self, message):
        user_id = message.from_user.id
        compress_7z = "-7" in message.text
        compress_zip = "-z" in message.text.lower()
        if message.reply_to_message:
            reply = message.reply_to_message
            if reply.document and reply.document.file_size <= 5 * 1024 * 1024:
                await self._process_torrent_file(message, reply.document, compress_7z, compress_zip)
                return
            elif reply.text:
                await self._process_torrent_text(message, reply.text, compress_7z, compress_zip)
                return
            else:
                await self.bot.safe_call(message.reply_text, "❌ Responde a un mensaje con texto o archivo .torrent (<5MB)")
                return
        parts = message.text.split()
        torrent_input = None
        if len(parts) > 1:
            filtered_parts = [p for p in parts[1:] if p != "-7" and p.lower() != "-z"]
            if filtered_parts:
                torrent_input = filtered_parts[0].strip()
        if torrent_input:
            await self._process_torrent_text(message, torrent_input, compress_7z, compress_zip)
        else:
            await self.bot.safe_call(message.reply_text, "❌ Usa: `/leech magnet:...` o `/leech http://...torrent` o responde a un archivo\nUsa `/leech -7` para comprimir en 7z\nUsa `/leech -z` para comprimir en zip")
    
    async def _process_torrent_file(self, message, document, compress_7z=False, compress_zip=False):
        if not document.file_name.endswith('.torrent'):
            await self.bot.safe_call(message.reply_text, "❌ El archivo debe ser .torrent")
            return
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".torrent")
        temp_path = temp_file.name
        temp_file.close()
        await self.bot.app.download_media(document, file_name=temp_path)
        with open(temp_path, "rb") as f:
            torrent_data = f.read()
        magnet = self._torrent_to_magnet(torrent_data)
        os.remove(temp_path)
        await self.start_torrent_download(message, {"magnet": magnet}, message.from_user.id, compress_7z, compress_zip)
    
    async def _process_torrent_text(self, message, text, compress_7z=False, compress_zip=False):
        text = text.strip()
        if text.startswith("magnet:?"):
            magnet = text
            await self.start_torrent_download(message, {"magnet": magnet}, message.from_user.id, compress_7z, compress_zip)
            return
        elif text.endswith(".torrent"):
            if text.startswith("http://") or text.startswith("https://"):
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(text) as response:
                            if response.status == 200:
                                torrent_data = await response.read()
                                magnet = self._torrent_to_magnet(torrent_data)
                                await self.start_torrent_download(message, {"magnet": magnet}, message.from_user.id, compress_7z, compress_zip)
                            else:
                                await self.bot.safe_call(message.reply_text, f"❌ Error al descargar")
                except Exception as e:
                    await self.bot.safe_call(message.reply_text, f"❌ Error")
            else:
                if os.path.exists(text):
                    with open(text, "rb") as f:
                        torrent_data = f.read()
                    magnet = self._torrent_to_magnet(torrent_data)
                    await self.start_torrent_download(message, {"magnet": magnet}, message.from_user.id, compress_7z, compress_zip)
                else:
                    await self.bot.safe_call(message.reply_text, "❌ Archivo no encontrado")
        else:
            await self.bot.safe_call(message.reply_text, "❌ Enlace no válido")
    
    async def start_torrent_download(self, message, result, user_id, compress_7z=False, compress_zip=False):
        global premium_enabled, premium_limit, normal_limit
        magnet = result.get("magnet", "")
        if not magnet:
            return
        download_path = os.path.join(os.getcwd(), "vault", str(user_id), "torrents")
        os.makedirs(download_path, exist_ok=True)
        status_msg = await self.bot.safe_call(message.reply_text, "⏳ Iniciando descarga torrent..." + (" (comprimirá en 7z antes de enviar)" if compress_7z else " (comprimirá en zip antes de enviar)" if compress_zip else ""))
        try:
            download_generator = self.neko.download_magnet(magnet, download_path)
            final_path = None
            last_progress = ""
            last_update_time = time.time()
            async for progress_text in download_generator:
                if progress_text.startswith("📥"):
                    current_time = time.time()
                    if progress_text != last_progress and current_time - last_update_time >= 10:
                        await self.bot.safe_call(status_msg.edit_text, progress_text + (" (comprimirá al finalizar)" if compress_7z or compress_zip else ""))
                        last_progress = progress_text
                        last_update_time = current_time
                elif progress_text.startswith("✅") and "COMPLETADO" in progress_text:
                    continue
                else:
                    if os.path.exists(progress_text):
                        final_path = progress_text
            if final_path and os.path.exists(final_path):
                try:
                    await status_msg.delete()
                except:
                    pass
                if compress_7z:
                    await self.bot.safe_call(message.reply_text, "🗜️ Comprimiendo en 7z...")
                    if premium_enabled:
                        target_size = premium_limit
                    else:
                        target_size = normal_limit
                    parts = self.neko.compress_to_7z(final_path, target_size)
                    if parts:
                        for part in parts:
                            await self.bot._send_document_with_progress(
                                message.chat.id,
                                part,
                                caption=f"🗜️ {os.path.basename(part)}",
                                user_id=user_id
                            )
                    else:
                        await self.bot.safe_call(message.reply_text, "❌ Error al comprimir en 7z, enviando archivos sin comprimir...")
                        await self._send_files_normally(message, final_path, user_id)
                elif compress_zip:
                    await self.bot.safe_call(message.reply_text, "🗜️ Comprimiendo en zip...")
                    zip_path = await self._create_zip_from_path(final_path)
                    if zip_path and os.path.exists(zip_path):
                        await self.bot._send_document_with_progress(
                            message.chat.id,
                            zip_path,
                            caption=f"🗜️ {os.path.basename(zip_path)}",
                            user_id=user_id
                        )
                        try:
                            os.remove(zip_path)
                        except:
                            pass
                    else:
                        await self.bot.safe_call(message.reply_text, "❌ Error al comprimir en zip, enviando archivos sin comprimir...")
                        await self._send_files_normally(message, final_path, user_id)
                else:
                    await self._send_files_normally(message, final_path, user_id)
                
                download_base = os.path.dirname(download_path)
                if os.path.exists(download_base):
                    shutil.rmtree(download_base, ignore_errors=True)
            else:
                try:
                    await status_msg.delete()
                except:
                    pass
                await self.bot.safe_call(message.reply_text, "✅ Descarga completada pero no se encontraron archivos para enviar")
        except Exception as e:
            try:
                await status_msg.delete()
            except:
                pass
            await self.bot.safe_call(message.reply_text, f"❌ Error en la descarga torrent: {str(e)}")
    
    async def _create_zip_from_path(self, path):
        try:
            if os.path.isfile(path):
                zip_name = os.path.splitext(os.path.basename(path))[0] + ".zip"
                zip_path = os.path.join(os.path.dirname(path), zip_name)
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zipf:
                    zipf.write(path, os.path.basename(path))
                os.remove(path)
                return zip_path
            elif os.path.isdir(path):
                zip_name = os.path.basename(os.path.normpath(path)) + ".zip"
                zip_path = os.path.join(os.path.dirname(path), zip_name)
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zipf:
                    for root, dirs, files in os.walk(path):
                        for file in files:
                            file_path = os.path.join(root, file)
                            arcname = os.path.relpath(file_path, os.path.dirname(path))
                            zipf.write(file_path, arcname)
                shutil.rmtree(path, ignore_errors=True)
                return zip_path
            return None
        except Exception as e:
            print(f"Error creando zip: {e}")
            return None
    
    async def _send_files_normally(self, message, final_path, user_id):
        if os.path.isfile(final_path):
            await self.bot._send_document_with_progress(
                message.chat.id,
                final_path,
                caption=f"✅ {os.path.basename(final_path)}",
                user_id=user_id
            )
        elif os.path.isdir(final_path):
            for root, dirs, files in os.walk(final_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    try:
                        await self.bot._send_document_with_progress(
                            message.chat.id,
                            file_path,
                            caption=f"✅ {os.path.basename(file_path)}",
                            user_id=user_id
                        )
                        await asyncio.sleep(0.5)
                    except Exception as e:
                        print(f"Error enviando archivo {file_path}: {e}")
    
    def _torrent_to_magnet(self, torrent_data: bytes) -> str:
        try:
            torrent_dict = bencodepy.decode(torrent_data)
            info = torrent_dict[b'info']
            info_bencoded = bencodepy.encode(info)
            infohash = hashlib.sha1(info_bencoded).hexdigest()
            trackers = []
            if b'announce' in torrent_dict:
                trackers.append(torrent_dict[b'announce'].decode())
            if b'announce-list' in torrent_dict:
                for tier in torrent_dict[b'announce-list']:
                    for tr in tier:
                        trackers.append(tr.decode())
            magnet = f"magnet:?xt=urn:btih:{infohash}"
            if b'name' in info:
                magnet += f"&dn={info[b'name'].decode()}"
            for tr in trackers:
                magnet += f"&tr={tr}"
            return magnet
        except Exception as e:
            raise Exception(f"Error convirtiendo torrent a magnet: {e}")
    
    async def mega(self, message):
        try:
            parts = message.text.split(maxsplit=1)
            if len(parts) < 2:
                await self.bot.safe_call(message.reply_text, "Usa: `/mega mega_link`")
                return
            mega_link = parts[1].strip()
            status_msg = await self.bot.safe_call(message.reply_text, "⏳ Iniciando descarga de MEGA...")
            download_path = self.neko.mega_download(mega_link)
            await self.bot.safe_call(status_msg.edit_text, "✅ Descarga de MEGA completada. Procesando archivos...")
            if not os.path.exists(download_path):
                await self.bot.safe_call(status_msg.edit_text, "❌ No se encontró la carpeta de descarga")
                return
            items = os.listdir(download_path)
            if len(items) == 0:
                await self.bot.safe_call(status_msg.edit_text, "❌ La carpeta está vacía")
                shutil.rmtree(download_path, ignore_errors=True)
                return
            elif len(items) == 1:
                single_item = os.path.join(download_path, items[0])
                if os.path.isfile(single_item):
                    await self.bot._send_document_with_progress(
                        message.chat.id,
                        single_item,
                        caption=f"✅ {os.path.basename(single_item)}",
                        user_id=message.from_user.id
                    )
                elif os.path.isdir(single_item):
                    global premium_enabled
                    if premium_enabled:
                        parts = self.neko.compress_to_7z(single_item, 3995)
                    else:
                        parts = self.neko.compress_to_7z(single_item, 1995)
                    if parts:
                        for part in parts:
                            await self.bot._send_document_with_progress(
                                message.chat.id,
                                part,
                                f"✅ {os.path.basename(part)}",
                                user_id=message.from_user.id
                            )
                    else:
                        await self.bot.safe_call(status_msg.edit_text, "❌ Error al comprimir carpeta")
                else:
                    await self.bot.safe_call(status_msg.edit_text, "❌ Tipo de archivo no soportado")
            else:
                if premium_enabled:
                    parts = self.neko.compress_to_7z(download_path, 3995)
                else:
                    parts = self.neko.compress_to_7z(download_path, 1995)
                if parts:
                    for part in parts:
                        await self.bot._send_document_with_progress(
                            message.chat.id,
                            part,
                            f"✅ {os.path.basename(part)}",
                            user_id=message.from_user.id
                        )
                else:
                    await self.bot.safe_call(status_msg.edit_text, "❌ Error al comprimir archivos")
            try:
                await status_msg.delete()
            except:
                pass
            if os.path.exists(download_path):
                shutil.rmtree(download_path, ignore_errors=True)
        except Exception as e:
            try:
                await status_msg.delete()
            except:
                pass
            await self.bot.safe_call(message.reply_text, f"❌ Error en la descarga de MEGA: {str(e)}")