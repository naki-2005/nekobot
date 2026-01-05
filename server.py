import os
from flask import Flask, request, redirect, url_for, send_file, render_template_string
from werkzeug.utils import secure_filename
from PIL import Image

app = Flask(__name__)
BASE_DIR = os.path.join(os.getcwd(), "vault")
os.makedirs(BASE_DIR, exist_ok=True)

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

def run_flask():
    app.run(host="0.0.0.0", port=5000)

if __name__ == "__main__":
    run_flask()

