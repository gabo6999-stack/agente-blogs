"""
Agente de publicación automática de blogs
Sitio: peptidosysuplementos.mx
Frecuencia: Lunes, Martes, Jueves, Viernes @ 9:00am
+ API web para publicación manual y edición con IA
"""

import schedule
import time
import threading
import os
import json
import requests
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
import uvicorn
from pydantic import BaseModel

from config import SITES
from tools.trends import pick_topic
from tools.writer import generate_blog, edit_blog
from tools.images import get_unsplash_image, upload_image_to_wordpress
from tools.wordpress import publish_post, get_wp_headers, get_post, get_tag_names, update_post, set_featured_image, get_posts_list, update_author_display_name
from tools.logger import log_post, get_used_topics, get_history, get_last_post

app = FastAPI()

SCHEDULE_FILE = os.path.join(os.getenv("DATA_DIR", "."), "schedule_config.json")
DAY_MAP_ES = {
    "monday": "Lunes", "tuesday": "Martes", "wednesday": "Miércoles",
    "thursday": "Jueves", "friday": "Viernes", "saturday": "Sábado", "sunday": "Domingo"
}

# Estado del agente
agent_status = {
    "running": False,
    "last_post": None,
    "last_error": None
}


def notify_seo_agent(site_key: str, post_id: int, title: str, content: str, url: str):
    site_cfg = SITES[site_key]
    seo_agent_url = site_cfg.get("seo_agent_url")
    seo_optimize_path = site_cfg.get("seo_optimize_path", "/optimize-blog")
    if not seo_agent_url:
        print(f"[SEO] Sitio '{site_key}' no tiene seo_agent_url configurado — saltando optimización")
        return
    try:
        print(f"[SEO] Enviando blog al agente SEO para optimización ({seo_optimize_path})...")
        response = requests.post(
            f"{seo_agent_url}{seo_optimize_path}",
            json={"post_id": post_id, "title": title, "content": content, "url": url},
            timeout=120
        )
        result = response.json()
        if result.get("success"):
            print(f"[SEO] ✅ Blog optimizado: {result.get('url', url)}")
        else:
            print(f"[SEO] ⚠️ No se pudo optimizar: {result.get('error')}")
    except Exception as e:
        print(f"[SEO] ⚠️ Error al contactar agente SEO: {e}")


def load_schedule_config() -> dict:
    if os.path.exists(SCHEDULE_FILE):
        with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        site_key: {
            "publish_days": cfg.get("publish_days", ["monday", "tuesday", "thursday", "friday"]),
            "publish_time": cfg.get("publish_time", "09:00")
        }
        for site_key, cfg in SITES.items()
    }


def save_schedule_config(config: dict):
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def run_pipeline(site_key: str, topic: str = None):
    """
    Pipeline completo: tendencias → escritura → imágenes → publicación
    """
    agent_status["running"] = True
    print(f"\n{'='*50}")
    print(f"[Pipeline] Iniciando para: {site_key}")
    print(f"[Pipeline] Hora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}\n")

    try:
        # 1. Seleccionar tema
        if not topic:
            used_topics = get_used_topics(site_key)
            topic = pick_topic(site_key, used_topics)
        print(f"[Pipeline] Tema seleccionado: {topic}")

        # 2. Generar blog
        blog_data = generate_blog(site_key, topic)

        # 3. Obtener imagen
        unsplash_query = blog_data.get("unsplash_query", topic)
        image_data = get_unsplash_image(unsplash_query)

        # 4. Subir imagen
        featured_media_id = None
        if image_data:
            wp_url, headers = get_wp_headers(site_key)
            featured_media_id = upload_image_to_wordpress(image_data, wp_url, headers)

        # 5. Publicar post
        post = publish_post(site_key, blog_data, featured_media_id)

        # 6. Registrar
        if post:
            log_post(site_key, topic, post, success=True)
            agent_status["last_post"] = {
                "title": post.get("title", {}).get("rendered", ""),
                "url": post.get("link", ""),
                "date": datetime.now().strftime("%Y-%m-%d %H:%M")
            }
            agent_status["last_error"] = None
            print(f"\n[Pipeline] ✅ Blog publicado: {post.get('link')}")

            # 7. Optimizar con agente SEO
            notify_seo_agent(
                site_key=site_key,
                post_id=post.get("id"),
                title=post.get("title", {}).get("rendered", ""),
                content=blog_data.get("content", ""),
                url=post.get("link", "")
            )
        else:
            agent_status["last_error"] = "Post creation failed"
            log_post(site_key, topic, None, success=False, error="Post creation failed")

    except Exception as e:
        print(f"[Pipeline] ❌ Error: {e}")
        agent_status["last_error"] = str(e)
        log_post(site_key, topic if topic else "unknown", None, success=False, error=str(e))
    finally:
        agent_status["running"] = False


def run_edit_pipeline(site_key: str, post_id: int, instruction: str, update_image: bool = False):
    """
    Pipeline de edición: fetch post actual → Claude corrige → actualiza en WP
    """
    agent_status["running"] = True
    print(f"\n{'='*50}")
    print(f"[Edit Pipeline] Editando post {post_id} en: {site_key}")
    print(f"[Edit Pipeline] Instrucción: {instruction}")
    print(f"{'='*50}\n")

    try:
        # 1. Obtener post actual de WP
        raw_post = get_post(site_key, post_id)
        if not raw_post:
            raise Exception(f"No se encontró el post con ID {post_id}")

        # 2. Normalizar datos del post
        meta = raw_post.get("meta", {})
        tag_ids = raw_post.get("tags", [])
        tag_names = get_tag_names(site_key, tag_ids)

        current_post = {
            "title": raw_post.get("title", {}).get("raw") or raw_post.get("title", {}).get("rendered", ""),
            "content": raw_post.get("content", {}).get("raw") or raw_post.get("content", {}).get("rendered", ""),
            "excerpt": raw_post.get("excerpt", {}).get("raw") or raw_post.get("excerpt", {}).get("rendered", ""),
            "rank_math_title": meta.get("rank_math_title", ""),
            "rank_math_description": meta.get("rank_math_description", ""),
            "rank_math_focus_keyword": meta.get("rank_math_focus_keyword", ""),
            "tags": tag_names,
        }

        # 3. Editar con IA
        updated_blog_data = edit_blog(site_key, current_post, instruction)

        # 4. Buscar nueva imagen si se solicitó
        featured_media_id = None
        if update_image:
            unsplash_query = updated_blog_data.get("unsplash_query", current_post.get("title", ""))
            image_data = get_unsplash_image(unsplash_query)
            if image_data:
                wp_url, headers = get_wp_headers(site_key)
                featured_media_id = upload_image_to_wordpress(image_data, wp_url, headers)
                print(f"[Edit Pipeline] Nueva imagen subida: media_id={featured_media_id}")

        # 5. Actualizar en WP
        post = update_post(site_key, post_id, updated_blog_data, featured_media_id)

        if post:
            agent_status["last_post"] = {
                "title": post.get("title", {}).get("rendered", ""),
                "url": post.get("link", ""),
                "date": datetime.now().strftime("%Y-%m-%d %H:%M")
            }
            agent_status["last_error"] = None
            print(f"\n[Edit Pipeline] ✅ Post actualizado: {post.get('link')}")
        else:
            agent_status["last_error"] = "Post update failed"

    except Exception as e:
        print(f"[Edit Pipeline] ❌ Error: {e}")
        agent_status["last_error"] = str(e)
    finally:
        agent_status["running"] = False


# ─── API ENDPOINTS ───────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def dashboard():
    last_post = agent_status.get("last_post") or get_last_post()
    last_error = agent_status.get("last_error")
    running = agent_status.get("running")
    history = get_history(limit=10)

    last_post_html = ""
    if last_post:
        last_post_html = f"""
        <div class="card success">
            <h3>✅ Último blog publicado</h3>
            <p><strong>{last_post.get('title', last_post.get('topic', ''))}</strong></p>
            <p>{last_post.get('date', '')[:16].replace('T', ' ')}</p>
            <a href="{last_post.get('url', '#')}" target="_blank">{last_post.get('url', '')}</a>
        </div>"""

    error_html = ""
    if last_error:
        error_html = f'<div class="card error"><h3>❌ Último error</h3><p>{last_error}</p></div>'

    running_html = '<div class="card warning"><h3>⏳ Publicando ahora...</h3></div>' if running else ""

    history_rows = ""
    for entry in history:
        status_icon = "✅" if entry.get("success") else "❌"
        date = entry.get("date", "")[:16].replace("T", " ")
        title = entry.get("title") or entry.get("topic", "—")
        url = entry.get("url", "")
        link = f'<a href="{url}" target="_blank">Ver</a>' if url else "—"
        error = entry.get("error", "")
        detail = f'<span style="color:#ef4444;font-size:12px">{error}</span>' if error else link
        history_rows += f"<tr><td>{status_icon}</td><td>{date}</td><td>{title}</td><td>{detail}</td></tr>"

    history_html = f"""
    <div class="card info">
        <h3>📋 Historial de publicaciones</h3>
        <table style="width:100%;border-collapse:collapse;font-size:14px;">
            <thead>
                <tr style="border-bottom:1px solid #444;">
                    <th style="padding:8px;text-align:left;width:30px"></th>
                    <th style="padding:8px;text-align:left;">Fecha</th>
                    <th style="padding:8px;text-align:left;">Título / Tema</th>
                    <th style="padding:8px;text-align:left;">Link</th>
                </tr>
            </thead>
            <tbody>{history_rows if history_rows else '<tr><td colspan="4" style="padding:12px;color:#666;">Sin publicaciones aún</td></tr>'}</tbody>
        </table>
    </div>"""

    sched_config = load_schedule_config()
    sites_options = "".join([f'<option value="{k}">{k}</option>' for k in SITES.keys()])

    schedule_cards = ""
    for site_key in SITES.keys():
        site_sched = sched_config.get(site_key, {})
        active_days = site_sched.get("publish_days", ["monday", "tuesday", "thursday", "friday"])
        pub_time = site_sched.get("publish_time", "09:00")
        days_display = " · ".join(DAY_MAP_ES.get(d, d).capitalize() for d in active_days)
        schedule_cards += f'<div class="day">{days_display} @ {pub_time}</div>'

    first_site = list(SITES.keys())[0]
    first_sched = sched_config.get(first_site, {})
    active_days_first = first_sched.get("publish_days", ["monday", "tuesday", "thursday", "friday"])
    pub_time_first = first_sched.get("publish_time", "09:00")

    all_days = [("monday","Lunes"),("tuesday","Martes"),("wednesday","Miércoles"),
                ("thursday","Jueves"),("friday","Viernes"),("saturday","Sábado"),("sunday","Domingo")]
    day_checkboxes = ""
    for val, label in all_days:
        checked = "checked" if val in active_days_first else ""
        day_checkboxes += f'<label style="display:flex;align-items:center;gap:6px;cursor:pointer;"><input type="checkbox" value="{val}" {checked} style="width:auto;margin:0;"> {label}</label>'

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Agente Blogs — peptidosysuplementos.mx</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{ font-family: Arial, sans-serif; max-width: 700px; margin: 40px auto; padding: 20px; background: #0f0f0f; color: #eee; }}
            h1 {{ color: #7c3aed; }}
            .card {{ background: #1a1a1a; border-radius: 10px; padding: 20px; margin: 20px 0; }}
            .success {{ border-left: 4px solid #22c55e; }}
            .error {{ border-left: 4px solid #ef4444; }}
            .warning {{ border-left: 4px solid #f59e0b; }}
            .info {{ border-left: 4px solid #7c3aed; }}
            input, select {{ background: #2a2a2a; color: #eee; border: 1px solid #444; padding: 10px; border-radius: 6px; width: 100%; margin: 8px 0; box-sizing: border-box; }}
            button {{ background: #7c3aed; color: white; border: none; padding: 12px 24px; border-radius: 6px; cursor: pointer; font-size: 16px; width: 100%; margin-top: 10px; }}
            button:hover {{ background: #6d28d9; }}
            a {{ color: #818cf8; }}
            .schedule {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
            .day {{ background: #2a2a2a; padding: 10px; border-radius: 6px; text-align: center; }}
            textarea {{ background: #2a2a2a; color: #eee; border: 1px solid #444; padding: 10px; border-radius: 6px; width: 100%; min-height: 80px; box-sizing: border-box; font-family: Arial; resize: vertical; margin: 8px 0; }}
        </style>
    </head>
    <body>
        <h1>🤖 Agente de Blogs</h1>
        <p>peptidosysuplementos.mx</p>

        {running_html}
        {last_post_html}
        {error_html}
        {history_html}

        <div class="card info">
            <h3>📅 Publicación automática</h3>
            <div class="schedule">{schedule_cards}</div>
        </div>

        <div class="card" style="border-left: 4px solid #f59e0b;">
            <h3>⚙️ Cambiar horario</h3>
            <select id="sched-site" style="margin-bottom:12px;">{sites_options}</select>
            <p style="font-size:13px;color:#aaa;margin:4px 0 10px;">Días de publicación:</p>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:14px;">
                {day_checkboxes}
            </div>
            <label style="font-size:13px;color:#aaa;">Hora de publicación:</label>
            <input type="time" id="sched-time" value="{pub_time_first}" style="margin-bottom:10px;">
            <button onclick="guardarHorario()" style="background:#f59e0b;">💾 Guardar horario</button>
            <p id="sched-msg" style="margin-top:10px;font-size:13px;"></p>
        </div>

        <div class="card">
            <h3>⚡ Publicar ahora manualmente</h3>
            <select id="site">{sites_options}</select>
            <input type="text" id="topic" placeholder="Tema (opcional — dejar vacío para usar tendencias)">
            <button onclick="publicar()">🚀 Publicar Blog Ahora</button>
            <p id="msg" style="margin-top:10px; color: #22c55e;"></p>
        </div>

        <div class="card" style="border-left: 4px solid #22c55e;">
            <h3>✏️ Editar blog existente con IA</h3>
            <select id="edit-site" onchange="resetPostSelector()">{sites_options}</select>
            <div style="position:relative; margin:8px 0;">
                <input type="text" id="post-search" placeholder="Busca un blog por nombre..." autocomplete="off"
                    oninput="filterPosts()" onfocus="openDropdown()" onblur="closeDropdownDelayed()"
                    style="margin:0; padding-right:40px;">
                <button onclick="loadPosts()" title="Cargar lista de blogs"
                    style="position:absolute;right:0;top:0;bottom:0;width:40px;margin:0;padding:0;border-radius:0 6px 6px 0;font-size:18px;">🔄</button>
                <div id="post-dropdown" style="display:none;position:absolute;top:100%;left:0;right:0;background:#2a2a2a;border:1px solid #555;border-top:none;border-radius:0 0 8px 8px;max-height:220px;overflow-y:auto;z-index:100;"></div>
            </div>
            <p id="post-info" style="font-size:13px; color:#888; margin:4px 0 8px 0;"></p>
            <textarea id="instruction" placeholder="Instrucción — ej: 'Mejora la introducción', 'Agrega sección sobre dosis recomendadas', 'Cambia el tono a más formal'"></textarea>
            <label style="display:flex; align-items:center; gap:8px; margin:8px 0; cursor:pointer;">
                <input type="checkbox" id="update-image" style="width:auto; margin:0;">
                Reemplazar imagen (Unsplash)
            </label>
            <button onclick="editar()" style="background:#16a34a;">✏️ Editar con IA</button>
            <p id="edit-msg" style="margin-top:10px; color: #22c55e;"></p>
        </div>

        <script>
        async function guardarHorario() {{
            const site = document.getElementById('sched-site').value;
            const time = document.getElementById('sched-time').value;
            const days = Array.from(document.querySelectorAll('input[type=checkbox]:not(#update-image):checked')).map(cb => cb.value);
            const msg = document.getElementById('sched-msg');
            if (!days.length) {{ msg.textContent = '❌ Selecciona al menos un día'; msg.style.color='#ef4444'; return; }}
            msg.textContent = '⏳ Guardando...'; msg.style.color = '#f59e0b';
            try {{
                const res = await fetch('/schedule', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{site_key: site, days, publish_time: time}})
                }});
                const data = await res.json();
                if (data.status === 'updated') {{
                    msg.textContent = '✅ Horario guardado. Se aplicará desde ahora.';
                    msg.style.color = '#22c55e';
                    setTimeout(() => location.reload(), 1500);
                }} else {{
                    msg.textContent = '❌ ' + (data.detail || 'Error');
                    msg.style.color = '#ef4444';
                }}
            }} catch(e) {{
                msg.textContent = '❌ Error de conexión';
                msg.style.color = '#ef4444';
            }}
        }}

        async function publicar() {{
            const site = document.getElementById('site').value;
            const topic = document.getElementById('topic').value;
            const msg = document.getElementById('msg');
            msg.textContent = '⏳ Publicando... esto tarda 1-2 minutos';
            msg.style.color = '#f59e0b';
            try {{
                const res = await fetch('/publish', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{site_key: site, topic: topic || null}})
                }});
                const data = await res.json();
                if (data.status === 'started') {{
                    msg.textContent = '✅ Publicación iniciada — revisa los logs en Railway';
                    msg.style.color = '#22c55e';
                }} else {{
                    msg.textContent = '❌ ' + (data.detail || 'Error');
                    msg.style.color = '#ef4444';
                }}
            }} catch(e) {{
                msg.textContent = '❌ Error de conexión';
                msg.style.color = '#ef4444';
            }}
        }}

        let allPosts = [];
        let selectedPostId = null;

        async function loadPosts() {{
            const site = document.getElementById('edit-site').value;
            const info = document.getElementById('post-info');
            const search = document.getElementById('post-search');
            info.textContent = '⏳ Cargando lista de blogs...';
            info.style.color = '#888';
            try {{
                const res = await fetch(`/posts/${{site}}`);
                const data = await res.json();
                allPosts = data.posts || [];
                info.textContent = `${{allPosts.length}} blogs cargados — escribe para filtrar`;
                info.style.color = '#888';
                search.focus();
                filterPosts();
            }} catch(e) {{
                info.textContent = '❌ Error cargando blogs';
                info.style.color = '#ef4444';
            }}
        }}

        function filterPosts() {{
            const q = document.getElementById('post-search').value.toLowerCase();
            const dropdown = document.getElementById('post-dropdown');
            const filtered = allPosts.filter(p => p.title.toLowerCase().includes(q));
            if (!filtered.length) {{
                dropdown.innerHTML = '<div style="padding:10px;color:#666;font-size:13px;">Sin resultados</div>';
            }} else {{
                dropdown.innerHTML = filtered.slice(0, 30).map(p =>
                    `<div onclick="selectPost(${{p.id}}, '${{p.title.replace(/'/g, "&#39;")}}')"
                        style="padding:10px 14px;cursor:pointer;font-size:14px;border-bottom:1px solid #333;"
                        onmouseover="this.style.background='#3a3a3a'" onmouseout="this.style.background=''">${{p.title}}</div>`
                ).join('');
            }}
            dropdown.style.display = 'block';
        }}

        function selectPost(id, title) {{
            selectedPostId = id;
            document.getElementById('post-search').value = title;
            document.getElementById('post-dropdown').style.display = 'none';
            const info = document.getElementById('post-info');
            const post = allPosts.find(p => p.id === id);
            info.innerHTML = `✅ ID: ${{id}} — <a href="${{post?.url || '#'}}" target="_blank">ver post</a>`;
            info.style.color = '#22c55e';
        }}

        function openDropdown() {{
            if (allPosts.length) filterPosts();
        }}

        function closeDropdownDelayed() {{
            setTimeout(() => {{ document.getElementById('post-dropdown').style.display = 'none'; }}, 200);
        }}

        function resetPostSelector() {{
            allPosts = [];
            selectedPostId = null;
            document.getElementById('post-search').value = '';
            document.getElementById('post-info').textContent = '';
            document.getElementById('post-dropdown').style.display = 'none';
        }}

        async function editar() {{
            const site = document.getElementById('edit-site').value;
            const instruction = document.getElementById('instruction').value;
            const updateImage = document.getElementById('update-image').checked;
            const msg = document.getElementById('edit-msg');
            if (!selectedPostId) {{
                msg.textContent = '❌ Selecciona un blog de la lista primero';
                msg.style.color = '#ef4444';
                return;
            }}
            if (!instruction.trim()) {{
                msg.textContent = '❌ Escribe una instrucción de edición';
                msg.style.color = '#ef4444';
                return;
            }}
            msg.textContent = updateImage ? '⏳ Editando con IA y buscando nueva imagen...' : '⏳ Editando con IA... esto tarda 1-2 minutos';
            msg.style.color = '#f59e0b';
            try {{
                const res = await fetch('/edit', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{site_key: site, post_id: selectedPostId, instruction: instruction, update_image: updateImage}})
                }});
                const data = await res.json();
                if (data.status === 'started') {{
                    msg.textContent = '✅ Edición iniciada — revisa los logs en Railway';
                    msg.style.color = '#22c55e';
                }} else {{
                    msg.textContent = '❌ ' + (data.detail || 'Error');
                    msg.style.color = '#ef4444';
                }}
            }} catch(e) {{
                msg.textContent = '❌ Error de conexión';
                msg.style.color = '#ef4444';
            }}
        }}
        </script>
    </body>
    </html>
    """


class PublishRequest(BaseModel):
    site_key: str
    topic: str = None


@app.post("/publish")
def publish_now(req: PublishRequest):
    if agent_status["running"]:
        raise HTTPException(status_code=409, detail="Ya hay una publicación en proceso")
    if req.site_key not in SITES:
        raise HTTPException(status_code=404, detail=f"Sitio '{req.site_key}' no encontrado")

    thread = threading.Thread(target=run_pipeline, args=(req.site_key, req.topic))
    thread.daemon = True
    thread.start()

    return {"status": "started", "site": req.site_key, "topic": req.topic or "automático"}


class EditRequest(BaseModel):
    site_key: str
    post_id: int
    instruction: str
    update_image: bool = False


@app.post("/edit")
def edit_now(req: EditRequest):
    if agent_status["running"]:
        raise HTTPException(status_code=409, detail="Ya hay una operación en proceso")
    if req.site_key not in SITES:
        raise HTTPException(status_code=404, detail=f"Sitio '{req.site_key}' no encontrado")
    if not req.instruction.strip():
        raise HTTPException(status_code=400, detail="La instrucción no puede estar vacía")

    thread = threading.Thread(target=run_edit_pipeline, args=(req.site_key, req.post_id, req.instruction, req.update_image))
    thread.daemon = True
    thread.start()

    return {"status": "started", "site": req.site_key, "post_id": req.post_id, "instruction": req.instruction}


class ImageRequest(BaseModel):
    site_key: str
    post_id: int
    query: str = None


@app.post("/image")
def update_image(req: ImageRequest):
    if req.site_key not in SITES:
        raise HTTPException(status_code=404, detail=f"Sitio '{req.site_key}' no encontrado")

    raw_post = get_post(req.site_key, req.post_id)
    if not raw_post:
        raise HTTPException(status_code=404, detail=f"Post {req.post_id} no encontrado en WordPress")

    site_niche_en = SITES[req.site_key].get("unsplash_fallback", "sports supplement fitness")
    search_query = req.query or site_niche_en

    image_data = get_unsplash_image(search_query)
    if not image_data:
        raise HTTPException(status_code=502, detail="No se encontró imagen en Unsplash")

    wp_url, headers = get_wp_headers(req.site_key)
    media_id = upload_image_to_wordpress(image_data, wp_url, headers)
    if not media_id:
        raise HTTPException(status_code=502, detail="Error subiendo imagen a WordPress")

    post = set_featured_image(req.site_key, req.post_id, media_id)
    if not post:
        raise HTTPException(status_code=502, detail="Error actualizando imagen en el post")

    return {
        "status": "ok",
        "post_id": req.post_id,
        "media_id": media_id,
        "url": post.get("link", ""),
        "query_used": search_query,
    }


@app.get("/posts/{site_key}")
def list_posts(site_key: str):
    if site_key not in SITES:
        raise HTTPException(status_code=404, detail=f"Sitio '{site_key}' no encontrado")
    posts = get_posts_list(site_key)
    return {"posts": posts}


@app.get("/post/{site_key}/{post_id}")
def fetch_post_info(site_key: str, post_id: int):
    if site_key not in SITES:
        raise HTTPException(status_code=404, detail=f"Sitio '{site_key}' no encontrado")
    raw_post = get_post(site_key, post_id)
    if not raw_post:
        raise HTTPException(status_code=404, detail=f"Post {post_id} no encontrado en WordPress")
    return {
        "id": raw_post.get("id"),
        "title": raw_post.get("title", {}).get("rendered", ""),
        "url": raw_post.get("link", ""),
        "date": raw_post.get("date", ""),
        "status": raw_post.get("status", ""),
    }


@app.get("/status")
def status():
    last_post = agent_status["last_post"] or get_last_post()
    return {
        "online": True,
        "running": agent_status["running"],
        "last_post": last_post,
        "last_error": agent_status["last_error"],
        "sites": list(SITES.keys())
    }


@app.get("/history")
def history(site: str = None, limit: int = 20):
    return {"history": get_history(site_key=site, limit=limit)}


class LogEntryRequest(BaseModel):
    site_key: str
    topic: str
    title: str
    url: str
    post_id: int = None


@app.post("/log/add")
def log_add(req: LogEntryRequest):
    log_post(
        site_key=req.site_key,
        topic=req.topic,
        post={"title": {"rendered": req.title}, "link": req.url, "id": req.post_id},
        success=True
    )
    return {"status": "ok", "added": req.title}


@app.get("/schedule")
def get_schedule():
    return load_schedule_config()


class ScheduleRequest(BaseModel):
    site_key: str
    days: list
    publish_time: str


@app.post("/schedule")
def update_schedule(req: ScheduleRequest):
    valid_days = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
    invalid = [d for d in req.days if d not in valid_days]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Días inválidos: {invalid}")
    if not req.days:
        raise HTTPException(status_code=400, detail="Debes seleccionar al menos un día")
    if req.site_key not in SITES:
        raise HTTPException(status_code=404, detail=f"Sitio '{req.site_key}' no encontrado")
    reschedule(req.site_key, req.days, req.publish_time)
    return {"status": "updated", "site": req.site_key, "days": req.days, "time": req.publish_time}


@app.post("/fix-author-name")
def fix_author_name():
    results = {}
    for site_key, cfg in SITES.items():
        author_name = cfg.get("wp_author_name")
        if not author_name:
            results[site_key] = "sin wp_author_name configurado"
            continue
        ok = update_author_display_name(site_key, author_name)
        results[site_key] = f"✅ actualizado a '{author_name}'" if ok else "❌ error"
    return {"results": results}


# ─── SCHEDULER ───────────────────────────────────────────

def schedule_sites():
    config = load_schedule_config()
    for site_key in SITES.keys():
        site_sched = config.get(site_key, {})
        publish_time = site_sched.get("publish_time", "09:00")
        publish_days = site_sched.get("publish_days", ["monday", "tuesday", "thursday", "friday"])

        day_map = {
            "monday": schedule.every().monday,
            "tuesday": schedule.every().tuesday,
            "wednesday": schedule.every().wednesday,
            "thursday": schedule.every().thursday,
            "friday": schedule.every().friday,
            "saturday": schedule.every().saturday,
            "sunday": schedule.every().sunday,
        }

        for day in publish_days:
            if day in day_map:
                day_map[day].at(publish_time).do(run_pipeline, site_key=site_key)
                print(f"[Scheduler] {site_key} → {day} @ {publish_time}")


def reschedule(site_key: str, days: list, publish_time: str):
    config = load_schedule_config()
    config[site_key] = {"publish_days": days, "publish_time": publish_time}
    save_schedule_config(config)
    schedule.clear()
    schedule_sites()
    print(f"[Scheduler] ✅ Horario actualizado: {days} @ {publish_time}")


def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    print("🚀 Agente de blogs iniciado")
    print(f"Sitios configurados: {list(SITES.keys())}\n")

    schedule_sites()

    scheduler_thread = threading.Thread(target=run_scheduler)
    scheduler_thread.daemon = True
    scheduler_thread.start()

    print("⏰ Scheduler activo")
    print("🌐 Dashboard disponible en el URL de Railway\n")

    uvicorn.run(app, host="0.0.0.0", port=8000)
