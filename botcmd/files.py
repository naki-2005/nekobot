import os
import tempfile
import shutil

class FileCommands:
    def __init__(self, bot):
        self.bot = bot
        self.neko = bot.neko

    def get_vault_files(self):
        vault_dir = os.path.join(os.getcwd(), "vault")
        if not os.path.exists(vault_dir):
            return []
        items = self.neko.sort_directory(vault_dir)
        files_list = []
        for idx, item in enumerate(items, 1):
            item_path = os.path.join(vault_dir, item)
            if os.path.isfile(item_path):
                size = os.path.getsize(item_path)
                size_mb = size / (1024 * 1024)
                files_list.append({
                    "index": idx,
                    "name": item,
                    "size_mb": size_mb,
                    "is_dir": False,
                    "path": item_path
                })
            else:
                files_list.append({
                    "index": idx,
                    "name": item,
                    "is_dir": True,
                    "path": item_path
                })
        return files_list

    def get_file_by_index(self, index):
        files = self.get_vault_files()
        for f in files:
            if f["index"] == index:
                return f
        return None

    def save_cookies(self, file_path):
        SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
        DATA_DIR = os.path.join(SCRIPT_DIR, "data")
        os.makedirs(DATA_DIR, exist_ok=True)
        cookies_path = os.path.join(DATA_DIR, "cookies.txt")
        shutil.move(file_path, cookies_path)
        return cookies_path

    def get_nextname_pattern(self, user_id, user_nextnames):
        if user_id not in user_nextnames:
            return None
        pattern_info = user_nextnames[user_id]
        current = pattern_info["current"]
        start = pattern_info["start"]
        end = pattern_info["end"]
        if current > end:
            del user_nextnames[user_id]
            return None, None, None, None
        pattern = pattern_info["pattern"]
        filename = pattern.replace("{no}", str(current).zfill(len(str(start)) if str(start).startswith("0") else 1))
        user_nextnames[user_id]["current"] = current + 1
        return filename, start, end, current

    def set_nextname_pattern(self, user_id, user_nextnames, pattern_str):
        import re
        match = re.match(r'(\d+)-(\d+)\s+(.+)', pattern_str)
        if not match:
            return None, None, None
        start_num = int(match.group(1))
        end_num = int(match.group(2))
        pattern = match.group(3)
        if "{no}" not in pattern:
            return None, None, None
        if start_num > end_num:
            return None, None, None
        user_nextnames[user_id] = {
            "pattern": pattern,
            "start": start_num,
            "end": end_num,
            "current": start_num
        }
        first_example = pattern.replace("{no}", str(start_num).zfill(len(str(start_num)) if str(start_num).startswith("0") else 1))
        return start_num, end_num, first_example
