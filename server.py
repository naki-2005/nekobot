import os
import json
from flask import Flask, request, redirect, url_for, send_file, render_template_string, Response
from werkzeug.utils import secure_filename
from neko import Neko

app = Flask(__name__)
BASE_DIR = os.path.join(os.getcwd(), "vault")
os.makedirs(BASE_DIR, exist_ok=True)

neko_instance = Neko()

def format_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} bytes"
    size_kb = size_bytes / 1024
    if size_kb < 1024:
        return f"{size_kb:.2f} KB"
    size_mb = size_kb / 1024
    if size_mb < 1024:
        return f"{size_mb:.2f} MB"
    size_gb = size_mb / 1024
    return f"{size_gb:.2f} GB"

@app.route("/", defaults={"req_path": ""})
@app.route("/<path:req_path>")
def dir_listing(req_path):
    preview_mode = request.args.get('preview', 'false') == 'true'
    
    abs_path = os.path.join(BASE_DIR, req_path)
    if not os.path.exists(abs_path):
        return "Ruta no encontrada", 404
    if os.path.isfile(abs_path):
        return send_file(abs_path, as_attachment=not preview_mode)
    
    files = neko_instance.sort_directory(abs_path)
    file_links = []
    for f in files:
        full_path = os.path.join(req_path, f)
        abs_f = os.path.join(abs_path, f)
        size = os.path.getsize(abs_f) if os.path.isfile(abs_f) else 0
        formatted_size = format_size(size)
        
        if os.path.isdir(abs_f):
            file_links.append(
                f'<li><a href="/{full_path}{"?preview=true" if preview_mode else ""}">{f}/</a> '
                f'<form style="display:inline;" method="post" action="/delete">'
                f'<input type="hidden" name="path" value="{full_path}">'
                f'<button type="submit">Borrar</button></form> ({formatted_size})</li>'
            )
        else:
            if preview_mode:
                link = f'<a href="/{full_path}?preview=true" target="_blank">{f}</a>'
            else:
                link = f'<a href="/{full_path}">{f}</a>'
            
            file_links.append(
                f'<li>{link} '
                f'<form style="display:inline;" method="post" action="/delete">'
                f'<input type="hidden" name="path" value="{full_path}">'
                f'<button type="submit">Borrar</button></form> ({formatted_size})</li>'
            )
    
    toggle_button = f'''
    <form method="get" style="margin-bottom: 20px;">
        <input type="hidden" name="preview" value="{str(not preview_mode).lower()}">
        <button type="submit">{"🔗 Modo Descarga" if preview_mode else "👁️ Modo Preview"}</button>
    </form>
    '''
    
    upload_form = '''
    <form method="post" action="/upload" enctype="multipart/form-data">
        <input type="file" name="file" multiple>
        <button type="submit">Subir</button>
    </form>
    '''
    
    return render_template_string(
        "<h1>Contenido de {{path}}</h1>{{toggle|safe}}<ul>{{links|safe}}</ul>{{upload|safe}}",
        path=req_path or "/", links="".join(file_links), upload=upload_form, toggle=toggle_button
    )

@app.route("/delete", methods=["POST"])
def delete_file():
    rel_path = request.form.get("path")
    abs_path = os.path.join(BASE_DIR, rel_path)
    if os.path.exists(abs_path):
        if os.path.isfile(abs_path):
            os.remove(abs_path)
        elif os.path.isdir(abs_path):
            import shutil
            shutil.rmtree(abs_path)
    return redirect(url_for("dir_listing", req_path=os.path.dirname(rel_path)))

@app.route("/upload", methods=["POST"])
def upload_file():
    files = request.files.getlist("file")
    for file in files:
        if file and file.filename != "":
            filename = secure_filename(file.filename)
            save_path = os.path.join(BASE_DIR, filename)
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            file.save(save_path)
    return redirect(url_for("dir_listing", req_path=""))

@app.route("/nekotools", methods=["GET", "POST"])
def nekotools():
    result_text = ""
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "snh":
            search_term = request.form.get("snh_search", "").strip()
            page = request.form.get("snh_page", "1").strip()
            if search_term:
                result = neko_instance.snh(search_term, int(page) if page.isdigit() else 1)
                result_text = json.dumps(result, indent=2, ensure_ascii=False)
        
        elif action == "s3h":
            search_term = request.form.get("s3h_search", "").strip()
            page = request.form.get("s3h_page", "1").strip()
            if search_term:
                result = neko_instance.s3h(search_term, int(page) if page.isdigit() else 1)
                result_text = json.dumps(result, indent=2, ensure_ascii=False)
        
        elif action == "vnh":
            code = request.form.get("vnh_code", "").strip()
            if code:
                result = neko_instance.vnh(code)
                result_text = json.dumps(result, indent=2, ensure_ascii=False)
                if isinstance(result, dict) and "code" in result:
                    base_name = f"{result.get('title', 'unknown')} - {result.get('code', 'unknown')}"
                    safe_name = neko_instance.clean_name(base_name)
                    json_path = os.path.join(BASE_DIR, f"{safe_name}.json")
                    txt_path = os.path.join(BASE_DIR, f"{safe_name}.txt")
                    
                    with open(json_path, 'w', encoding='utf-8') as f:
                        json.dump(result, f, indent=2, ensure_ascii=False)
                    
                    if "image_links" in result and isinstance(result["image_links"], list):
                        with open(txt_path, 'w', encoding='utf-8') as f:
                            for link in result["image_links"]:
                                f.write(f"{link}\n")
                    
                    result_text += f"\n\n✅ JSON guardado: {safe_name}.json"
                    result_text += f"\n✅ TXT guardado: {safe_name}.txt"
        
        elif action == "v3h":
            code = request.form.get("v3h_code", "").strip()
            if code:
                result = neko_instance.v3h(code)
                result_text = json.dumps(result, indent=2, ensure_ascii=False)
                if isinstance(result, dict) and "code" in result:
                    base_name = f"{result.get('title', 'unknown')} - {result.get('code', 'unknown')}"
                    safe_name = neko_instance.clean_name(base_name)
                    json_path = os.path.join(BASE_DIR, f"{safe_name}.json")
                    txt_path = os.path.join(BASE_DIR, f"{safe_name}.txt")
                    
                    with open(json_path, 'w', encoding='utf-8') as f:
                        json.dump(result, f, indent=2, ensure_ascii=False)
                    
                    if "image_links" in result and isinstance(result["image_links"], list):
                        with open(txt_path, 'w', encoding='utf-8') as f:
                            for link in result["image_links"]:
                                f.write(f"{link}\n")
                    
                    result_text += f"\n\n✅ JSON guardado: {safe_name}.json"
                    result_text += f"\n✅ TXT guardado: {safe_name}.txt"
        
        elif action == "download":
            url = request.form.get("download_url", "").strip()
            filename = request.form.get("download_name", "downloaded_file").strip()
            if url and filename:
                safe_filename = neko_instance.clean_name(filename)
                save_path = os.path.join(BASE_DIR, safe_filename)
                success = neko_instance.download(url, save_path)
                if success:
                    result_text = f"✅ Descarga exitosa: {safe_filename}"
                else:
                    result_text = "❌ Error en la descarga"
        
        elif action == "convert_png":
            files = request.files.getlist("file")
            converted_files = []
            for file in files:
                if file and file.filename != "":
                    result = neko_instance.convert_to_png(file)
                    if result:
                        converted_files.append(result)
            result_text = "<br>".join(converted_files) + " convertidos"
        
        elif action == "create_cbz":
            nombre = request.form.get("cbz_name", "").strip()
            lista_text = request.form.get("cbz_list", "").strip()
            if nombre and lista_text:
                lista = [item.strip() for item in lista_text.split("\n") if item.strip()]
                result = neko_instance.create_cbz(nombre, lista)
                if result and os.path.exists(result):
                    result_text = f"✅ CBZ creado: {result}"
                else:
                    result_text = "❌ Error al crear CBZ"
        
        elif action == "create_pdf":
            nombre = request.form.get("pdf_name", "").strip()
            lista_text = request.form.get("pdf_list", "").strip()
            if nombre and lista_text:
                lista = [item.strip() for item in lista_text.split("\n") if item.strip()]
                result = neko_instance.create_pdf(nombre, lista)
                if result and os.path.exists(result):
                    result_text = f"✅ PDF creado: {result}"
                else:
                    result_text = "❌ Error al crear PDF"
        
        elif action == "download_from_json":
            json_file = request.files.get("json_file")
            if json_file and json_file.filename.endswith('.json'):
                try:
                    data = json.load(json_file.stream)
                    if isinstance(data, dict) and "image_links" in data and "title" in data and "code" in data:
                        base_name = f"{data['title']} - {data['code']}"
                        safe_name = neko_instance.clean_name(base_name)
                        folder_path = os.path.join(BASE_DIR, safe_name)
                        os.makedirs(folder_path, exist_ok=True)
                        
                        success_count = 0
                        total_count = len(data["image_links"])
                        
                        for i, link in enumerate(data["image_links"], 1):
                            ext = os.path.splitext(link)[1]
                            if not ext:
                                ext = ".jpg"
                            filename = f"{i:04d}{ext}"
                            file_path = os.path.join(folder_path, filename)
                            if neko_instance.download(link, file_path):
                                success_count += 1
                        
                        result_text = f"✅ Descargadas {success_count}/{total_count} imágenes en: {safe_name}/"
                    else:
                        result_text = "❌ JSON no tiene el formato esperado"
                except Exception as e:
                    result_text = f"❌ Error al procesar JSON: {str(e)}"
        
        elif action == "download_from_txt":
            txt_file = request.files.get("txt_file")
            folder_name = request.form.get("txt_folder", "").strip()
            if txt_file and txt_file.filename.endswith('.txt') and folder_name:
                try:
                    content = txt_file.stream.read().decode('utf-8')
                    links = [line.strip() for line in content.split('\n') if line.strip()]
                    
                    safe_name = neko_instance.clean_name(folder_name)
                    folder_path = os.path.join(BASE_DIR, safe_name)
                    os.makedirs(folder_path, exist_ok=True)
                    
                    success_count = 0
                    total_count = len(links)
                    
                    for i, link in enumerate(links, 1):
                        ext = os.path.splitext(link)[1]
                        if not ext:
                            ext = ".jpg"
                        filename = f"{i:04d}{ext}"
                        file_path = os.path.join(folder_path, filename)
                        if neko_instance.download(link, file_path):
                            success_count += 1
                    
                    result_text = f"✅ Descargadas {success_count}/{total_count} imágenes en: {safe_name}/"
                except Exception as e:
                    result_text = f"❌ Error al procesar TXT: {str(e)}"
    
    html = '''
    <h1>NekoTools</h1>
    
    <h2>Descargar desde JSON</h2>
    <form method="post" enctype="multipart/form-data">
        <input type="file" name="json_file" accept=".json">
        <input type="hidden" name="action" value="download_from_json">
        <button type="submit">Descargar imágenes desde JSON</button>
    </form>
    
    <h2>Descargar desde TXT</h2>
    <form method="post" enctype="multipart/form-data">
        <input type="file" name="txt_file" accept=".txt">
        <br>
        Nombre de carpeta: <input type="text" name="txt_folder" placeholder="Nombre para la carpeta">
        <input type="hidden" name="action" value="download_from_txt">
        <button type="submit">Descargar imágenes desde TXT</button>
    </form>
    
    <h2>Descargar Archivo</h2>
    <form method="post">
        URL: <input type="text" name="download_url" placeholder="URL del archivo">
        <br>
        Nombre: <input type="text" name="download_name" placeholder="Nombre del archivo">
        <input type="hidden" name="action" value="download">
        <button type="submit">Descargar</button>
    </form>
    
    <h2>Convertir a PNG</h2>
    <form method="post" enctype="multipart/form-data">
        <input type="file" name="file" multiple>
        <input type="hidden" name="action" value="convert_png">
        <button type="submit">Convertir</button>
    </form>
    
    <h2>Crear CBZ</h2>
    <form method="post">
        Nombre: <input type="text" name="cbz_name" placeholder="Nombre del archivo">
        <br>
        Lista (URLs o paths, uno por línea):<br>
        <textarea name="cbz_list" rows="5" cols="50"></textarea>
        <input type="hidden" name="action" value="create_cbz">
        <button type="submit">Crear CBZ</button>
    </form>
    
    <h2>Crear PDF</h2>
    <form method="post">
        Nombre: <input type="text" name="pdf_name" placeholder="Nombre del archivo">
        <br>
        Lista (URLs o paths, uno por línea):<br>
        <textarea name="pdf_list" rows="5" cols="50"></textarea>
        <input type="hidden" name="action" value="create_pdf">
        <button type="submit">Crear PDF</button>
    </form>
    
    <h2>Buscar en nhentai</h2>
    <form method="post">
        Término: <input type="text" name="snh_search" placeholder="Término de búsqueda">
        <br>
        Página: <input type="number" name="snh_page" value="1" min="1">
        <input type="hidden" name="action" value="snh">
        <button type="submit">Buscar SNH</button>
    </form>
    
    <h2>Buscar en 3hentai</h2>
    <form method="post">
        Término: <input type="text" name="s3h_search" placeholder="Término de búsqueda">
        <br>
        Página: <input type="number" name="s3h_page" value="1" min="1">
        <input type="hidden" name="action" value="s3h">
        <button type="submit">Buscar S3H</button>
    </form>
    
    <h2>Ver nhentai</h2>
    <form method="post">
        Código: <input type="text" name="vnh_code" placeholder="Código del doujin">
        <input type="hidden" name="action" value="vnh">
        <button type="submit">Ver VNH</button>
    </form>
    
    <h2>Ver 3hentai</h2>
    <form method="post">
        Código: <input type="text" name="v3h_code" placeholder="Código del doujin">
        <input type="hidden" name="action" value="v3h">
        <button type="submit">Ver V3H</button>
    </form>
    
    <h2>Resultado:</h2>
    <pre>{{result_text}}</pre>
    '''
    return render_template_string(html, result_text=result_text)

def run_flask():
    app.run(host="0.0.0.0", port=5000)

if __name__ == "__main__":
    run_flask()
