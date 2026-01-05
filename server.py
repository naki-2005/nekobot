import os
from flask import Flask, request, redirect, url_for, send_from_directory, render_template_string

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
        return send_from_directory(os.path.dirname(abs_path), os.path.basename(abs_path))
    files = os.listdir(abs_path)
    file_links = []
    for f in files:
        full_path = os.path.join(req_path, f)
        if os.path.isdir(os.path.join(abs_path, f)):
            file_links.append(f'<li><a href="/{full_path}">{f}/</a></li>')
        else:
            file_links.append(
                f'<li><a href="/{full_path}">{f}</a> '
                f'<form style="display:inline;" method="post" action="/delete">'
                f'<input type="hidden" name="path" value="{full_path}">'
                f'<button type="submit">Borrar</button></form></li>'
            )
    upload_form = '''
    <form method="post" action="/upload" enctype="multipart/form-data">
        <input type="file" name="file">
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
    if os.path.exists(abs_path) and os.path.isfile(abs_path):
        os.remove(abs_path)
    return redirect(url_for("dir_listing", req_path=os.path.dirname(rel_path)))

@app.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return redirect(url_for("dir_listing", req_path=""))
    file = request.files["file"]
    if file.filename == "":
        return redirect(url_for("dir_listing", req_path=""))
    save_path = os.path.join(BASE_DIR, file.filename)
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    file.save(save_path)
    return redirect(url_for("dir_listing", req_path=""))

def run_flask():
    app.run(host="0.0.0.0", port=5000)

if __name__ == "__main__":
    run_flask()
