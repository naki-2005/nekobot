import os
import json
from flask import Flask, request, redirect, url_for, send_file, render_template_string
from werkzeug.utils import secure_filename
from PIL import Image
from neko import Neko

app = Flask(__name__)
BASE_DIR = os.path.join(os.getcwd(), "vault")
os.makedirs(BASE_DIR, exist_ok=True)

neko_instance = Neko()

@app.route("/", defaults={"req_path": ""})
@app.route("/<path:req_path>")
def dir_listing(req_path):
    abs_path = os.path.join(BASE_DIR, req_path)
    if not os.path.exists(abs_path):
        return "Ruta no encontrada", 404
    if os.path.isfile(abs_path):
        return send_file(abs_path, as_attachment=True)
    files = sorted(os.listdir(abs_path))
    file_links = []
    for f in files:
        full_path = os.path.join(req_path, f)
        abs_f = os.path.join(abs_path, f)
        size = os.path.getsize(abs_f)
        if os.path.isdir(abs_f):
            file_links.append(
                f'<li><a href="/{full_path}">{f}/</a> '
                f'<form style="display:inline;" method="post" action="/delete">'
                f'<input type="hidden" name="path" value="{full_path}">'
                f'<button type="submit">Borrar</button></form> ({size} bytes)</li>'
            )
        else:
            file_links.append(
                f'<li><a href="/{full_path}">{f}</a> '
                f'<form style="display:inline;" method="post" action="/delete">'
                f'<input type="hidden" name="path" value="{full_path}">'
                f'<button type="submit">Borrar</button></form> ({size} bytes)</li>'
            )
    upload_form = '''
    <form method="post" action="/upload" enctype="multipart/form-data">
        <input type="file" name="file" multiple>
        <button type="submit">Subir</button>
    </form>
    '''
    return render_template_string(
        "<h1>Contenido de {{path}}</h1><ul>{{links|safe}}</ul>{{upload|safe}}",
        path=req_path or "/", links="".join(file_links), upload=upload_form
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

@app.route("/webp", methods=["GET", "POST"])
def webp_convert():
    if request.method == "POST":
        target_format = request.form.get("format")
        files = request.files.getlist("file")
        converted_files = []
        for file in files:
            if file and file.filename != "":
                img = Image.open(file.stream).convert("RGB")
                filename = os.path.splitext(secure_filename(file.filename))[0] + "." + target_format.lower()
                save_path = os.path.join(BASE_DIR, filename)
                img.save(save_path, target_format.upper())
                converted_files.append(filename)
        return "<br>".join(converted_files) + " convertidos"
    form_html = '''
    <form method="post" enctype="multipart/form-data">
        <input type="file" name="file" multiple>
        <label><input type="radio" name="format" value="PNG" required> PNG</label>
        <label><input type="radio" name="format" value="JPG" required> JPG</label>
        <button type="submit">Convertir</button>
    </form>
    '''
    return form_html

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
        
        elif action == "v3h":
            code = request.form.get("v3h_code", "").strip()
            if code:
                result = neko_instance.v3h(code)
                result_text = json.dumps(result, indent=2, ensure_ascii=False)
        
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
    
    html = '''
    <h1>NekoTools</h1>
    
    <h2>Descargar Archivo</h2>
    <form method="post">
        URL: <input type="text" name="download_url" placeholder="URL del archivo">
        <br>
        Nombre: <input type="text" name="download_name" placeholder="Nombre del archivo">
        <input type="hidden" name="action" value="download">
        <button type="submit">Descargar</button>
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
