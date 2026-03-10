import os
import json
import threading
import time
import uuid
import urllib.parse
import asyncio
import aiohttp
import tempfile
import shutil
import zipfile
from flask import Flask, request, redirect, url_for, send_file, render_template_string
from werkzeug.utils import secure_filename
from neko import Neko

async def async_download(self, url, save_path):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=30) as response:
                if response.status == 200:
                    with open(save_path, 'wb') as f:
                        f.write(await response.read())
                    return True
                return False
    except Exception:
        return False

async def download_images_concurrently(self, image_urls, max_concurrent=10):
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def download_one(url, index):
        async with semaphore:
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
            temp_path = temp_file.name
            temp_file.close()
            
            if await self.async_download(url, temp_path):
                return (index, temp_path)
            return (index, None)
    
    tasks = [download_one(url, i) for i, url in enumerate(image_urls)]
    results = await asyncio.gather(*tasks)
    
    results.sort(key=lambda x: x[0])
    return [r[1] for r in results if r[1]]

async def create_cbz_async(self, nombre, lista):
    try:
        safe_nombre = self.clean_name(nombre)
        temp_dir = tempfile.mkdtemp()
        
        downloaded_files = []
        
        for i, item in enumerate(lista):
            if item.startswith('http'):
                downloaded_files.append((i, item, True))
            else:
                if os.path.exists(item):
                    file_path = os.path.join(temp_dir, f"{i:04d}.jpg")
                    shutil.copy2(item, file_path)
                    downloaded_files.append((i, file_path, False))
                else:
                    return None
        
        url_items = [(i, url) for i, url, is_url in downloaded_files if is_url]
        
        if url_items:
            urls = [url for _, url in url_items]
            indices = [idx for idx, _ in url_items]
            
            temp_paths = await self.download_images_concurrently(urls)
            
            for idx, temp_path in zip(indices, temp_paths):
                if temp_path:
                    dest_path = os.path.join(temp_dir, f"{idx:04d}.jpg")
                    shutil.move(temp_path, dest_path)
        
        cbz_path = os.path.join(os.getcwd(), "vault", f"{safe_nombre}.cbz")
        with zipfile.ZipFile(cbz_path, 'w', zipfile.ZIP_DEFLATED) as cbz:
            for i in range(len(lista)):
                file_path = os.path.join(temp_dir, f"{i:04d}.jpg")
                if os.path.exists(file_path):
                    cbz.write(file_path, f"{i:04d}.jpg")
        
        shutil.rmtree(temp_dir)
        return cbz_path
    except Exception as e:
        print(f"Error en create_cbz_async: {e}")
        return None

Neko.async_download = async_download
Neko.download_images_concurrently = download_images_concurrently
Neko.create_cbz_async = create_cbz_async

app = Flask(__name__)
app.secret_key = 'clave-secreta-temp-123'
BASE_DIR = os.path.join(os.getcwd(), "vault")
os.makedirs(BASE_DIR, exist_ok=True)

neko_instance = Neko()

download_queues = {}

def format_size(size_bytes):
    size_kb = size_bytes / 1024
    if size_kb < 1024:
        return f"{size_kb:.2f} KB"
    size_mb = size_kb / 1024
    if size_mb < 1024:
        return f"{size_mb:.2f} MB"
    size_gb = size_mb / 1024
    return f"{size_gb:.2f} GB"

def split_codes(code_string):
    if not code_string:
        return []
    import re
    codes = re.split(r'[,\s;/]+', code_string)
    return [c.strip() for c in codes if c.strip()]

def process_queue(queue_id, codes, mode, action):
    queue = download_queues[queue_id]
    results = []
    successful = 0
    failed = 0
    
    for i, code in enumerate(codes):
        if queue['status'] == 'cancelled':
            break
            
        queue['current'] = i + 1
        queue['current_code'] = code
        
        try:
            if mode == 'nhentai':
                result = neko_instance.vnh(code)
            else:
                result = neko_instance.v3h(code)
            
            if result and isinstance(result, dict) and "code" in result:
                base_name = f"{result.get('title', 'unknown')} - {result.get('code', 'unknown')}"
                
                if action == 'view':
                    results.append({
                        'code': code,
                        'success': True,
                        'title': result.get('title', 'unknown'),
                        'cover': result.get('cover_image') or result["image_links"][0] if result.get("image_links") else None,
                        'data': result,
                        'links': result.get("image_links", [])
                    })
                    successful += 1
                elif action == 'cbz':
                    if "image_links" in result and isinstance(result["image_links"], list):
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(neko_instance.create_cbz_async(base_name, result["image_links"]))
                        loop.close()
                        results.append({
                            'code': code,
                            'success': True,
                            'title': result.get('title', 'unknown'),
                            'cover': result.get('cover_image') or result["image_links"][0]
                        })
                        successful += 1
                elif action == 'pdf':
                    if "image_links" in result and isinstance(result["image_links"], list):
                        neko_instance.create_pdf(base_name, result["image_links"])
                        results.append({
                            'code': code,
                            'success': True,
                            'title': result.get('title', 'unknown'),
                            'cover': result.get('cover_image') or result["image_links"][0]
                        })
                        successful += 1
            else:
                results.append({'code': code, 'success': False, 'error': 'Error en respuesta'})
                failed += 1
        except Exception as e:
            results.append({'code': code, 'success': False, 'error': str(e)})
            failed += 1
        
        time.sleep(1)
    
    queue['results'] = results
    queue['successful'] = successful
    queue['failed'] = failed
    queue['status'] = 'completed'

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
                f'<li><input type="checkbox" name="selected" value="{full_path}" class="file-checkbox" onchange="updateButtons()"> '
                f'<a href="/{full_path}{"?preview=true" if preview_mode else ""}">{f}/</a> '
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
                f'<li><input type="checkbox" name="selected" value="{full_path}" class="file-checkbox" onchange="updateButtons()"> '
                f'{link} '
                f'<form style="display:inline;" method="post" action="/delete">'
                f'<input type="hidden" name="path" value="{full_path}">'
                f'<button type="submit">Borrar</button></form> ({formatted_size})</li>'
            )
    
    toggle_button = f'''
    <form method="get" style="margin-bottom: 20px;">
        <input type="hidden" name="preview" value="{str(not preview_mode).lower()}">
        <button type="submit">{"Modo Descarga" if preview_mode else "Modo Preview"}</button>
    </form>
    '''
    
    upload_form = '''
    <form method="post" action="/upload" enctype="multipart/form-data">
        <input type="file" name="file" multiple>
        <button type="submit">Subir</button>
    </form>
    '''
    
    selection_buttons = '''
    <div>
        <button type="button" id="selectAllBtn" onclick="selectAll()">Seleccionar Todo</button>
        <button type="button" id="deselectAllBtn" onclick="deselectAll()" style="display:none;">Deseleccionar Todo</button>
        <button type="button" id="selectRangeBtn" onclick="selectRange()" style="display:none;">Seleccionar Intervalo</button>
        <button type="button" id="deleteSelectedBtn" onclick="deleteSelected()" style="display:none;">Borrar Seleccionados</button>
    </div>
    '''
    
    script = '''
    <script>
    function updateButtons() {
        var checkboxes = document.getElementsByClassName('file-checkbox');
        var anyChecked = false;
        var allChecked = true;
        var checkedCount = 0;
        
        for(var i=0; i<checkboxes.length; i++) {
            if(checkboxes[i].checked) {
                anyChecked = true;
                checkedCount++;
            } else {
                allChecked = false;
            }
        }
        
        var selectAllBtn = document.getElementById('selectAllBtn');
        var deselectAllBtn = document.getElementById('deselectAllBtn');
        var selectRangeBtn = document.getElementById('selectRangeBtn');
        var deleteSelectedBtn = document.getElementById('deleteSelectedBtn');
        
        if(allChecked && checkboxes.length > 0) {
            selectAllBtn.style.display = 'none';
            deselectAllBtn.style.display = 'inline';
        } else {
            selectAllBtn.style.display = 'inline';
            deselectAllBtn.style.display = 'none';
        }
        
        if(checkedCount >= 2) {
            selectRangeBtn.style.display = 'inline';
        } else {
            selectRangeBtn.style.display = 'none';
        }
        
        if(checkedCount >= 1) {
            deleteSelectedBtn.style.display = 'inline';
        } else {
            deleteSelectedBtn.style.display = 'none';
        }
    }
    
    function selectAll() {
        var checkboxes = document.getElementsByClassName('file-checkbox');
        for(var i=0; i<checkboxes.length; i++) {
            checkboxes[i].checked = true;
        }
        updateButtons();
    }
    
    function deselectAll() {
        var checkboxes = document.getElementsByClassName('file-checkbox');
        for(var i=0; i<checkboxes.length; i++) {
            checkboxes[i].checked = false;
        }
        updateButtons();
    }
    
    function selectRange() {
        var checkboxes = document.getElementsByClassName('file-checkbox');
        var selected = [];
        for(var i=0; i<checkboxes.length; i++) {
            if(checkboxes[i].checked) {
                selected.push(i);
            }
        }
        if(selected.length >= 2) {
            var first = selected[0];
            var last = selected[selected.length-1];
            var min = Math.min(first, last);
            var max = Math.max(first, last);
            for(var i=min; i<=max; i++) {
                checkboxes[i].checked = true;
            }
        }
        updateButtons();
    }
    
    function deleteSelected() {
        var checkboxes = document.getElementsByClassName('file-checkbox');
        var selected = [];
        for(var i=0; i<checkboxes.length; i++) {
            if(checkboxes[i].checked) {
                selected.push(checkboxes[i].value);
            }
        }
        if(selected.length > 0) {
            var form = document.createElement('form');
            form.method = 'post';
            form.action = '/delete_multiple';
            for(var j=0; j<selected.length; j++) {
                var input = document.createElement('input');
                input.type = 'hidden';
                input.name = 'paths';
                input.value = selected[j];
                form.appendChild(input);
            }
            document.body.appendChild(form);
            form.submit();
        }
    }
    
    updateButtons();
    </script>
    '''
    
    return render_template_string(
        "<h1>Contenido de {{path}}</h1>{{toggle|safe}}{{selection|safe}}<ul>{{links|safe}}</ul>{{upload|safe}}{{script|safe}}",
        path=req_path or "/", links="".join(file_links), upload=upload_form, toggle=toggle_button, selection=selection_buttons, script=script
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

@app.route("/delete_multiple", methods=["POST"])
def delete_multiple():
    paths = request.form.getlist("paths")
    for rel_path in paths:
        abs_path = os.path.join(BASE_DIR, rel_path)
        if os.path.exists(abs_path):
            if os.path.isfile(abs_path):
                os.remove(abs_path)
            elif os.path.isdir(abs_path):
                import shutil
                shutil.rmtree(abs_path)
    return redirect(url_for("dir_listing", req_path=""))

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

@app.route("/viewer")
def viewer():
    links_json = request.args.get("links")
    title = request.args.get("title", "")
    if not links_json:
        return "No links provided", 400
    
    try:
        links = json.loads(links_json)
        title_tag = f"<title>{title}</title>" if title else ""
        html = f'''
        <!DOCTYPE html>
        <html>
        <head>
            {title_tag}
            <style>
                body {{
                    margin: 0;
                    padding: 20px 0;
                    background-color: #f0f0f0;
                }}
                .image-container {{
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    gap: 20px;
                }}
                .image-container img {{
                    max-width: 100%;
                    height: auto;
                    display: block;
                    box-shadow: 0 2px 5px rgba(0,0,0,0.1);
                }}
            </style>
        </head>
        <body>
            <div class="image-container">
        '''
        for link in links:
            html += f'<img src="{link}">'
        
        html += '''
            </div>
        </body>
        </html>
        '''
        return html
    except:
        return "Error loading links", 400

@app.route("/queue/<queue_id>")
def view_queue(queue_id):
    if queue_id not in download_queues:
        return "Cola no encontrada", 404
    
    queue = download_queues[queue_id]
    
    if queue['status'] == 'completed':
        html = render_template_string('''
        <h1>Proceso Completado</h1>
        <p>Total: {{ total }} codigos</p>
        <p>Exitosos: {{ successful }} | Fallidos: {{ failed }}</p>
        <h2>Resultados:</h2>
        <ul>
        {% for r in results %}
            <li>
                <b>{{ r.code }}</b> - {{ r.title if r.success else 'FALLIDO' }}
                {% if r.success and r.cover %}
                    <br><img src="{{ r.cover }}" style="max-width:100px;">
                {% endif %}
                {% if not r.success %}
                    <br>Error: {{ r.error }}
                {% endif %}
                {% if r.data %}
                    <br>
                    <a href="/viewer?links={{ r.links | tojson | urlencode }}&title={{ r.title }}" target="_blank"><button>Ver</button></a>
                    <form method="post" action="/save_json" style="display:inline;" target="_blank">
                        <input type="hidden" name="data" value='{{ r.data | tojson }}'>
                        <input type="hidden" name="filename" value="{{ r.title }} - {{ r.code }}">
                        <button type="submit">JSON</button>
                    </form>
                    <form method="post" action="/save_txt" style="display:inline;" target="_blank">
                        <input type="hidden" name="links" value='{{ r.links | tojson }}'>
                        <input type="hidden" name="filename" value="{{ r.title }} - {{ r.code }}">
                        <button type="submit">TXT</button>
                    </form>
                    <form method="post" action="/create_pdf_from_data" style="display:inline;" target="_blank">
                        <input type="hidden" name="links" value='{{ r.links | tojson }}'>
                        <input type="hidden" name="filename" value="{{ r.title }} - {{ r.code }}">
                        <button type="submit">PDF</button>
                    </form>
                    <form method="post" action="/create_cbz_from_data" style="display:inline;" target="_blank">
                        <input type="hidden" name="links" value='{{ r.links | tojson }}'>
                        <input type="hidden" name="filename" value="{{ r.title }} - {{ r.code }}">
                        <button type="submit">CBZ</button>
                    </form>
                {% endif %}
            </li>
        {% endfor %}
        </ul>
        <p><a href="/">Volver al inicio</a></p>
        ''', total=queue['total'], successful=queue['successful'], failed=queue['failed'], results=queue['results'])
        
        del download_queues[queue_id]
        return html
    
    return render_template_string('''
    <h1>Procesando...</h1>
    <p>Progreso: {{ current }}/{{ total }}</p>
    <p>Codigo actual: {{ current_code }}</p>
    <p><a href="/queue/{{ queue_id }}">Actualizar</a></p>
    ''', current=queue['current'], total=queue['total'], current_code=queue['current_code'], queue_id=queue_id)

@app.route("/process_nhentai", methods=["POST"])
def process_nhentai():
    action = request.form.get("action")
    codes_string = request.form.get("codes", "").strip()
    
    if not codes_string or not action:
        return redirect(url_for("nekotools"))
    
    if '\n' in codes_string:
        codes_string = codes_string.replace('\n', ' ')
    
    codes = split_codes(codes_string)
    if not codes:
        return redirect(url_for("nekotools", result="No se encontraron codigos validos"))
    
    if len(codes) == 1 and action == 'view':
        result = neko_instance.vnh(codes[0])
        if isinstance(result, dict) and "code" in result:
            base_name = f"{result.get('title', 'unknown')} - {result.get('code', 'unknown')}"
            safe_name = neko_instance.clean_name(base_name)
            
            links_json = json.dumps(result.get("image_links", []))
            data_json = json.dumps(result)
            title = result.get('title', 'unknown')
            
            buttons = f'''
            <h1>Resultado de {codes[0]}</h1>
            <img src="{result.get('cover_image') or result['image_links'][0]}" style="max-width:200px;">
            <pre>{json.dumps(result, indent=2, ensure_ascii=False)}</pre>
            <a href="/viewer?links={urllib.parse.quote(links_json)}&title={urllib.parse.quote(title)}" target="_blank"><button>Ver</button></a>
            <form method="post" action="/save_json" style="display:inline;" target="_blank">
                <input type="hidden" name="data" value='{data_json}'>
                <input type="hidden" name="filename" value="{base_name}">
                <button type="submit">JSON</button>
            </form>
            <form method="post" action="/save_txt" style="display:inline;" target="_blank">
                <input type="hidden" name="links" value='{links_json}'>
                <input type="hidden" name="filename" value="{base_name}">
                <button type="submit">TXT</button>
            </form>
            <form method="post" action="/create_pdf_from_data" style="display:inline;" target="_blank">
                <input type="hidden" name="links" value='{links_json}'>
                <input type="hidden" name="filename" value="{base_name}">
                <button type="submit">PDF</button>
            </form>
            <form method="post" action="/create_cbz_from_data" style="display:inline;" target="_blank">
                <input type="hidden" name="links" value='{links_json}'>
                <input type="hidden" name="filename" value="{base_name}">
                <button type="submit">CBZ</button>
            </form>
            <p><a href="/nekotools">Volver</a></p>
            '''
            return buttons
    
    queue_id = str(uuid.uuid4())
    download_queues[queue_id] = {
        'status': 'processing',
        'total': len(codes),
        'current': 0,
        'current_code': '',
        'results': [],
        'successful': 0,
        'failed': 0
    }
    
    thread = threading.Thread(target=process_queue, args=(queue_id, codes, 'nhentai', action))
    thread.daemon = True
    thread.start()
    
    return redirect(url_for('view_queue', queue_id=queue_id))

@app.route("/process_3hentai", methods=["POST"])
def process_3hentai():
    action = request.form.get("action")
    codes_string = request.form.get("codes", "").strip()
    
    if not codes_string or not action:
        return redirect(url_for("nekotools"))
    
    if '\n' in codes_string:
        codes_string = codes_string.replace('\n', ' ')
    
    codes = split_codes(codes_string)
    if not codes:
        return redirect(url_for("nekotools", result="No se encontraron codigos validos"))
    
    if len(codes) == 1 and action == 'view':
        result = neko_instance.v3h(codes[0])
        if isinstance(result, dict) and "code" in result:
            base_name = f"{result.get('title', 'unknown')} - {result.get('code', 'unknown')}"
            safe_name = neko_instance.clean_name(base_name)
            
            links_json = json.dumps(result.get("image_links", []))
            data_json = json.dumps(result)
            title = result.get('title', 'unknown')
            
            buttons = f'''
            <h1>Resultado de {codes[0]}</h1>
            <img src="{result.get('cover_image') or result['image_links'][0]}" style="max-width:200px;">
            <pre>{json.dumps(result, indent=2, ensure_ascii=False)}</pre>
            <a href="/viewer?links={urllib.parse.quote(links_json)}&title={urllib.parse.quote(title)}" target="_blank"><button>Ver</button></a>
            <form method="post" action="/save_json" style="display:inline;" target="_blank">
                <input type="hidden" name="data" value='{data_json}'>
                <input type="hidden" name="filename" value="{base_name}">
                <button type="submit">JSON</button>
            </form>
            <form method="post" action="/save_txt" style="display:inline;" target="_blank">
                <input type="hidden" name="links" value='{links_json}'>
                <input type="hidden" name="filename" value="{base_name}">
                <button type="submit">TXT</button>
            </form>
            <form method="post" action="/create_pdf_from_data" style="display:inline;" target="_blank">
                <input type="hidden" name="links" value='{links_json}'>
                <input type="hidden" name="filename" value="{base_name}">
                <button type="submit">PDF</button>
            </form>
            <form method="post" action="/create_cbz_from_data" style="display:inline;" target="_blank">
                <input type="hidden" name="links" value='{links_json}'>
                <input type="hidden" name="filename" value="{base_name}">
                <button type="submit">CBZ</button>
            </form>
            <p><a href="/nekotools">Volver</a></p>
            '''
            return buttons
    
    queue_id = str(uuid.uuid4())
    download_queues[queue_id] = {
        'status': 'processing',
        'total': len(codes),
        'current': 0,
        'current_code': '',
        'results': [],
        'successful': 0,
        'failed': 0
    }
    
    thread = threading.Thread(target=process_queue, args=(queue_id, codes, '3hentai', action))
    thread.daemon = True
    thread.start()
    
    return redirect(url_for('view_queue', queue_id=queue_id))

@app.route("/save_json", methods=["POST"])
def save_json():
    data_json = request.form.get("data")
    filename = request.form.get("filename")
    if data_json and filename:
        data = json.loads(data_json)
        safe_name = neko_instance.clean_name(filename)
        json_path = os.path.join(BASE_DIR, f"{safe_name}.json")
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        safe_filename = os.path.basename(json_path)
        return f"JSON guardado: <a href='/{urllib.parse.quote(safe_filename)}' target='_blank'>{safe_name}.json</a><br><a href='/nekotools'>Volver</a>"
    return redirect(url_for("nekotools"))

@app.route("/save_txt", methods=["POST"])
def save_txt():
    links_json = request.form.get("links")
    filename = request.form.get("filename")
    if links_json and filename:
        links = json.loads(links_json)
        safe_name = neko_instance.clean_name(filename)
        txt_path = os.path.join(BASE_DIR, f"{safe_name}.txt")
        with open(txt_path, 'w', encoding='utf-8') as f:
            for link in links:
                f.write(f"{link}\n")
        safe_filename = os.path.basename(txt_path)
        return f"TXT guardado: <a href='/{urllib.parse.quote(safe_filename)}' target='_blank'>{safe_name}.txt</a><br><a href='/nekotools'>Volver</a>"
    return redirect(url_for("nekotools"))

@app.route("/create_pdf_from_data", methods=["POST"])
def create_pdf_from_data():
    links_json = request.form.get("links")
    filename = request.form.get("filename")
    if links_json and filename:
        links = json.loads(links_json)
        result = neko_instance.create_pdf(filename, links)
        if result and os.path.exists(result):
            safe_name = neko_instance.clean_name(filename)
            safe_filename = os.path.basename(result)
            return f"PDF creado: <a href='/{urllib.parse.quote(safe_filename)}' target='_blank'>{safe_name}.pdf</a><br><a href='/nekotools'>Volver</a>"
    return redirect(url_for("nekotools"))

@app.route("/create_cbz_from_data", methods=["POST"])
def create_cbz_from_data():
    links_json = request.form.get("links")
    filename = request.form.get("filename")
    if links_json and filename:
        links = json.loads(links_json)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(neko_instance.create_cbz_async(filename, links))
        loop.close()
        if result and os.path.exists(result):
            safe_name = neko_instance.clean_name(filename)
            safe_filename = os.path.basename(result)
            return f"CBZ creado: <a href='/{urllib.parse.quote(safe_filename)}' target='_blank'>{safe_name}.cbz</a><br><a href='/nekotools'>Volver</a>"
    return redirect(url_for("nekotools"))

@app.route("/search_results")
def search_results():
    results_json = request.args.get("results")
    search_term = request.args.get("term", "")
    page = request.args.get("page", "1")
    
    if not results_json:
        return "No results provided", 400
    
    try:
        results_data = json.loads(results_json)
        resultados = results_data.get("resultados", [])
        total_resultados = results_data.get("total_resultados", 0)
        total_paginas = results_data.get("total_paginas", 1)
        pagina_actual = results_data.get("pagina_actual", 1)
        
        if not resultados:
            return f'''
            <html>
            <head><title>Sin resultados</title></head>
            <body>
                <h1>No se encontraron resultados para "{search_term}"</h1>
                <p><a href="/nekotools">Volver a NekoTools</a></p>
            </body>
            </html>
            '''
        
        html = f'''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Resultados de búsqueda: {search_term}</title>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    margin: 20px;
                    background-color: #f5f5f5;
                }}
                h1 {{
                    color: #333;
                }}
                .search-info {{
                    background-color: #fff;
                    padding: 15px;
                    border-radius: 5px;
                    margin-bottom: 20px;
                    box-shadow: 0 2px 5px rgba(0,0,0,0.1);
                }}
                .results-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
                    gap: 20px;
                    margin-top: 20px;
                }}
                .result-card {{
                    background-color: #fff;
                    border-radius: 8px;
                    overflow: hidden;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                    transition: transform 0.3s ease;
                }}
                .result-card:hover {{
                    transform: translateY(-5px);
                    box-shadow: 0 5px 20px rgba(0,0,0,0.2);
                }}
                .result-image {{
                    width: 100%;
                    height: 300px;
                    object-fit: cover;
                    border-bottom: 1px solid #eee;
                }}
                .result-info {{
                    padding: 15px;
                }}
                .result-code {{
                    background-color: #007bff;
                    color: white;
                    display: inline-block;
                    padding: 3px 8px;
                    border-radius: 4px;
                    font-size: 12px;
                    margin-bottom: 8px;
                }}
                .result-title {{
                    font-size: 14px;
                    line-height: 1.4;
                    margin-bottom: 10px;
                    max-height: 60px;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    display: -webkit-box;
                    -webkit-line-clamp: 3;
                    -webkit-box-orient: vertical;
                }}
                .result-actions {{
                    display: flex;
                    gap: 5px;
                    margin-top: 10px;
                }}
                .btn {{
                    flex: 1;
                    padding: 8px;
                    border: none;
                    border-radius: 4px;
                    cursor: pointer;
                    font-size: 12px;
                    text-align: center;
                    text-decoration: none;
                    display: inline-block;
                }}
                .btn-view {{
                    background-color: #28a745;
                    color: white;
                }}
                .btn-cbz {{
                    background-color: #ffc107;
                    color: #333;
                }}
                .btn-pdf {{
                    background-color: #dc3545;
                    color: white;
                }}
                .btn-json {{
                    background-color: #17a2b8;
                    color: white;
                }}
                .pagination {{
                    display: flex;
                    justify-content: center;
                    gap: 10px;
                    margin-top: 30px;
                    margin-bottom: 30px;
                }}
                .page-link {{
                    padding: 8px 15px;
                    background-color: #fff;
                    border: 1px solid #ddd;
                    border-radius: 4px;
                    text-decoration: none;
                    color: #007bff;
                }}
                .page-link.active {{
                    background-color: #007bff;
                    color: white;
                    border-color: #007bff;
                }}
                .page-link:hover {{
                    background-color: #f0f0f0;
                }}
                .back-link {{
                    display: inline-block;
                    margin-bottom: 20px;
                    color: #007bff;
                    text-decoration: none;
                }}
                .back-link:hover {{
                    text-decoration: underline;
                }}
            </style>
        </head>
        <body>
            <a href="/nekotools" class="back-link">← Volver a NekoTools</a>
            <h1>Resultados de búsqueda</h1>
            
            <div class="search-info">
                <p><strong>Término:</strong> {search_term}</p>
                <p><strong>Total de resultados:</strong> {total_resultados}</p>
                <p><strong>Página:</strong> {pagina_actual} de {total_paginas}</p>
            </div>
            
            <div class="results-grid">
        '''
        
        for r in resultados:
            codigo = r.get("codigo", r.get("code", ""))
            nombre = r.get("nombre", r.get("title", r.get("name", "Sin título")))
            miniatura = r.get("miniatura", r.get("cover", r.get("thumbnail", "")))
            
            html += f'''
                <div class="result-card">
                    <img src="{miniatura}" class="result-image" alt="{nombre}" onerror="this.src='https://via.placeholder.com/300x400?text=Sin+imagen'">
                    <div class="result-info">
                        <span class="result-code">{codigo}</span>
                        <div class="result-title">{nombre}</div>
                        <div class="result-actions">
                            <form method="post" action="/process_nhentai" style="margin:0;">
                                <input type="hidden" name="codes" value="{codigo}">
                                <input type="hidden" name="action" value="view">
                                <button type="submit" class="btn btn-view">Ver</button>
                            </form>
                            <form method="post" action="/process_nhentai" style="margin:0;">
                                <input type="hidden" name="codes" value="{codigo}">
                                <input type="hidden" name="action" value="cbz">
                                <button type="submit" class="btn btn-cbz">CBZ</button>
                            </form>
                            <form method="post" action="/process_nhentai" style="margin:0;">
                                <input type="hidden" name="codes" value="{codigo}">
                                <input type="hidden" name="action" value="pdf">
                                <button type="submit" class="btn btn-pdf">PDF</button>
                            </form>
                        </div>
                    </div>
                </div>
            '''
        
        html += '''
            </div>
            
            <div class="pagination">
        '''
        
        pagina_actual_int = int(pagina_actual)
        total_paginas_int = int(total_paginas)
        
        for p in range(1, min(total_paginas_int + 1, 11)):
            if p == pagina_actual_int:
                html += f'<span class="page-link active">{p}</span>'
            else:
                html += f'<a href="/search?term={urllib.parse.quote(search_term)}&page={p}" class="page-link">{p}</a>'
        
        if total_paginas_int > 10:
            html += '<span class="page-link">...</span>'
            html += f'<a href="/search?term={urllib.parse.quote(search_term)}&page={total_paginas_int}" class="page-link">{total_paginas_int}</a>'
        
        html += '''
            </div>
        </body>
        </html>
        '''
        
        return html
    except Exception as e:
        return f"Error al mostrar resultados: {str(e)}", 500

@app.route("/search")
def search():
    term = request.args.get("term", "")
    page = request.args.get("page", "1")
    site = request.args.get("site", "nhentai")
    
    if not term:
        return redirect(url_for("nekotools"))
    
    try:
        page = int(page)
    except:
        page = 1
    
    if site == "nhentai":
        resultado = neko_instance.snh(term, page)
    else:
        resultado = neko_instance.s3h(term, page)
    
    if isinstance(resultado, dict):
        if "error" in resultado:
            return f"Error en búsqueda: {resultado['error']}<br><a href='/nekotools'>Volver</a>"
        
        if "resultados" in resultado:
            return redirect(url_for("search_results", 
                                  results=json.dumps(resultado, ensure_ascii=False), 
                                  term=term, 
                                  page=page))
    
    return f"Error: formato de respuesta inesperado<br><a href='/nekotools'>Volver</a>"

@app.route("/nekotools", methods=["GET", "POST"])
def nekotools():
    result_text = request.args.get("result", "")
    
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "download_from_json":
            json_file = request.files.get("json_file")
            if json_file:
                try:
                    data = json.load(json_file)
                    return f"JSON cargado: {len(data)} items<br><a href='/nekotools'>Volver</a>"
                except:
                    return "Error al cargar JSON<br><a href='/nekotools'>Volver</a>"
        
        elif action == "download_from_txt":
            txt_file = request.files.get("txt_file")
            folder_name = request.form.get("txt_folder", "descarga")
            if txt_file:
                try:
                    content = txt_file.read().decode('utf-8')
                    lines = [line.strip() for line in content.split('\n') if line.strip()]
                    return f"TXT cargado: {len(lines)} lineas, carpeta: {folder_name}<br><a href='/nekotools'>Volver</a>"
                except:
                    return "Error al cargar TXT<br><a href='/nekotools'>Volver</a>"
        
        elif action == "download":
            url = request.form.get("download_url")
            name = request.form.get("download_name")
            if url and name:
                save_path = os.path.join(BASE_DIR, secure_filename(name))
                if neko_instance.download(url, save_path):
                    safe_filename = os.path.basename(save_path)
                    return f"Archivo descargado: <a href='/{urllib.parse.quote(safe_filename)}' target='_blank'>{name}</a><br><a href='/nekotools'>Volver</a>"
                else:
                    return "Error al descargar<br><a href='/nekotools'>Volver</a>"
        
        elif action == "convert_png":
            files = request.files.getlist("file")
            converted = []
            for file in files:
                if file and file.filename:
                    result = neko_instance.convert_to_png(file)
                    if result:
                        converted.append(result)
            return f"Convertidos: {len(converted)} archivos<br><a href='/nekotools'>Volver</a>"
        
        elif action == "create_cbz":
            name = request.form.get("cbz_name")
            lista = request.form.get("cbz_list", "").strip().split('\n')
            lista = [item.strip() for item in lista if item.strip()]
            if name and lista:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(neko_instance.create_cbz_async(name, lista))
                loop.close()
                if result:
                    safe_name = neko_instance.clean_name(name)
                    safe_filename = os.path.basename(result)
                    return f"CBZ creado: <a href='/{urllib.parse.quote(safe_filename)}' target='_blank'>{safe_name}.cbz</a><br><a href='/nekotools'>Volver</a>"
                else:
                    return "Error al crear CBZ<br><a href='/nekotools'>Volver</a>"
        
        elif action == "create_pdf":
            name = request.form.get("pdf_name")
            lista = request.form.get("pdf_list", "").strip().split('\n')
            lista = [item.strip() for item in lista if item.strip()]
            if name and lista:
                result = neko_instance.create_pdf(name, lista)
                if result:
                    safe_name = neko_instance.clean_name(name)
                    safe_filename = os.path.basename(result)
                    return f"PDF creado: <a href='/{urllib.parse.quote(safe_filename)}' target='_blank'>{safe_name}.pdf</a><br><a href='/nekotools'>Volver</a>"
                else:
                    return "Error al crear PDF<br><a href='/nekotools'>Volver</a>"
        
        elif action == "snh" or action == "s3h":
            search_term = request.form.get("snh_search") if action == "snh" else request.form.get("s3h_search")
            page = request.form.get("snh_page" if action == "snh" else "s3h_page", 1)
            
            if search_term:
                try:
                    page = int(page)
                except:
                    page = 1
                
                site = "nhentai" if action == "snh" else "3hentai"
                return redirect(url_for("search", term=search_term, page=page, site=site))
    
    html = '''
    <h1>NekoTools</h1>
    
    <h2>nhentai</h2>
    <form method="post" action="/process_nhentai">
        Codigos: <textarea name="codes" rows="3" cols="50" placeholder="318156 o 318156 318157 318158"></textarea>
        <br>
        <button type="submit" name="action" value="view">Ver</button>
        <button type="submit" name="action" value="cbz">Crear CBZ</button>
        <button type="submit" name="action" value="pdf">Crear PDF</button>
    </form>
    
    <h2>3hentai</h2>
    <form method="post" action="/process_3hentai">
        Codigos: <textarea name="codes" rows="3" cols="50" placeholder="318156 o 318156 318157 318158"></textarea>
        <br>
        <button type="submit" name="action" value="view">Ver</button>
        <button type="submit" name="action" value="cbz">Crear CBZ</button>
        <button type="submit" name="action" value="pdf">Crear PDF</button>
    </form>
    
    <h2>Descargar desde JSON</h2>
    <form method="post" enctype="multipart/form-data">
        <input type="file" name="json_file" accept=".json">
        <input type="hidden" name="action" value="download_from_json">
        <button type="submit">Descargar imagenes desde JSON</button>
    </form>
    
    <h2>Descargar desde TXT</h2>
    <form method="post" enctype="multipart/form-data">
        <input type="file" name="txt_file" accept=".txt">
        <br>
        Nombre de carpeta: <input type="text" name="txt_folder" placeholder="Nombre para la carpeta">
        <input type="hidden" name="action" value="download_from_txt">
        <button type="submit">Descargar imagenes desde TXT</button>
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
        Lista (URLs o paths, uno por linea):<br>
        <textarea name="cbz_list" rows="5" cols="50"></textarea>
        <input type="hidden" name="action" value="create_cbz">
        <button type="submit">Crear CBZ</button>
    </form>
    
    <h2>Crear PDF</h2>
    <form method="post">
        Nombre: <input type="text" name="pdf_name" placeholder="Nombre del archivo">
        <br>
        Lista (URLs o paths, uno por linea):<br>
        <textarea name="pdf_list" rows="5" cols="50"></textarea>
        <input type="hidden" name="action" value="create_pdf">
        <button type="submit">Crear PDF</button>
    </form>
    
    <h2>Buscar en nhentai</h2>
    <form method="post">
        Termino: <input type="text" name="snh_search" placeholder="Termino de busqueda">
        <br>
        Pagina: <input type="number" name="snh_page" value="1" min="1">
        <input type="hidden" name="action" value="snh">
        <button type="submit">Buscar SNH</button>
    </form>
    
    <h2>Buscar en 3hentai</h2>
    <form method="post">
        Termino: <input type="text" name="s3h_search" placeholder="Termino de busqueda">
        <br>
        Pagina: <input type="number" name="s3h_page" value="1" min="1">
        <input type="hidden" name="action" value="s3h">
        <button type="submit">Buscar S3H</button>
    </form>
    
    <h2>Resultado:</h2>
    <pre>{{result_text}}</pre>
    '''
    return render_template_string(html, result_text=result_text)

def run_flask():
    app.run(host="0.0.0.0", port=5000)

if __name__ == "__main__":
    run_flask()
