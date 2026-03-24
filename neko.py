def compress_to_7z(self, path, target_size=2000):
    if not os.path.exists(path):
        print(f"[ERROR] Path does not exist: {path}")
        return []
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    seven_zip = os.path.join(script_dir, "7zz")
    
    if not os.path.exists(seven_zip):
        seven_zip = shutil.which("7zz")
    if not seven_zip:
        seven_zip = shutil.which("7z")
    if not seven_zip:
        print("[ERROR] 7zip not found")
        return []
    
    try:
        if os.path.isdir(path):
            base_name = os.path.basename(os.path.normpath(path))
            parent_dir = os.path.dirname(os.path.abspath(path))
            output_file = os.path.join(parent_dir, base_name + ".7z")
        else:
            base_name = os.path.splitext(os.path.basename(path))[0]
            output_dir = os.path.dirname(os.path.abspath(path))
            output_file = os.path.join(output_dir, base_name + ".7z")
        
        volume_option = f"-v{target_size}m"
        
        if os.path.isdir(path):
            cmd = [seven_zip, "a", output_file, path, "-mx9", volume_option]
        else:
            cmd = [seven_zip, "a", output_file, path, "-mx9", volume_option]
        
        print(f"[DEBUG] Running: {' '.join(cmd)}")
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        
        if result.returncode != 0:
            print(f"[ERROR] 7zip failed: {result.stderr}")
            return []
        
        parts = []
        part_base = output_file
        part_num = 1
        
        while True:
            part_name = f"{part_base}.{part_num:03d}"
            if os.path.exists(part_name):
                parts.append(part_name)
                part_num += 1
                continue
            
            part_name = f"{part_base}.{part_num:02d}"
            if os.path.exists(part_name):
                parts.append(part_name)
                part_num += 1
                continue
            
            part_name = f"{part_base[:-3]}.{part_num:03d}"
            if os.path.exists(part_name):
                parts.append(part_name)
                part_num += 1
                continue
            
            break
        
        if not parts and os.path.exists(output_file):
            parts.append(output_file)
        
        if parts:
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                os.remove(path)
        
        return parts
        
    except subprocess.TimeoutExpired:
        print("[ERROR] 7zip timeout")
        return []
    except Exception as e:
        print(f"[ERROR] Exception: {e}")
        return []
