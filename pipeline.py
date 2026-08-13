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
from tools.trends import pick_topic, TemasAgotados
from tools.writer import generate_blog, edit_blog, contar_palabras, piso_de_palabras
from tools.images import get_unsplash_image, upload_image_to_wordpress
from tools.wordpress import (publish_post, get_wp_headers, get_post, get_tag_names, update_post,
                             set_featured_image, get_posts_list, update_author_display_name,
                             inject_hide_author_css, get_used_photo_ids, get_featured_media_id,
                             contar_posts_por_categoria)
from tools.arcade import publish_post as arcade_publish_post
from tools.logger import log_post, get_used_topics, get_history, get_last_post

app = FastAPI()

SCHEDULE_FILE = os.path.join(os.getenv("DATA_DIR", "."), "schedule_config.json")
TOPIC_QUEUE_FILE = os.path.join(os.getenv("DATA_DIR", "."), "topic_queue.json")
DAY_MAP_ES = {
    "monday": "Lunes", "tuesday": "Martes", "wednesday": "Miércoles",
    "thursday": "Jueves", "friday": "Viernes", "saturday": "Sábado", "sunday": "Domingo"
}

# ─── COLA DE TEMAS PRIORIZADOS ───────────────────────────
# Cola FIFO por sitio: si hay temas encolados, la corrida programada los consume
# EN ORDEN antes de caer al pick_topic automático (DataForSEO/pytrends).
# Persistida en el volumen (/data) para sobrevivir redeploys.
_queue_lock = threading.Lock()


def load_topic_queue() -> dict:
    if os.path.exists(TOPIC_QUEUE_FILE):
        try:
            with open(TOPIC_QUEUE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[Queue] ⚠️ Error leyendo cola ({e}) — se usa cola vacía")
    return {}


def save_topic_queue(queue: dict):
    with open(TOPIC_QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)


def pop_queued_topic(site_key: str):
    """Saca (FIFO) el siguiente tema encolado del sitio; None si la cola está vacía."""
    with _queue_lock:
        queue = load_topic_queue()
        site_q = queue.get(site_key) or []
        if not site_q:
            return None
        topic = site_q.pop(0)
        queue[site_key] = site_q
        save_topic_queue(queue)
        print(f"[Queue] Tema tomado de la cola ({len(site_q)} restantes): {str(topic)[:90]}")
        return topic

# Estado del agente
agent_status = {
    "running": False,
    "last_post": None,
    "last_error": None
}


def route_topic(site_key: str, topic: str) -> dict:
    """¿El tema le toca al blog o a la ficha de producto?

    Si la keyword es transaccional (precio, comprar, dosis en mg sobre un
    compuesto del catálogo), el artículo NO se escribe: esa consulta la atiende
    la ficha, y un post compitiendo por ella canibaliza. Si el sitio no tiene
    ruteo o el agente no responde se sigue adelante (fail-open: no vale la pena
    perder una publicación por un timeout).
    """
    site_cfg = SITES[site_key]
    base = site_cfg.get("seo_agent_url")
    ruta = site_cfg.get("keyword_route_path")
    if not base or not ruta:
        return {"decision": "blog", "razon": "sitio sin ruteo configurado"}
    try:
        r = requests.post(f"{base}{ruta}", json={"keyword": topic}, timeout=45)
        return r.json()
    except Exception as e:
        print(f"[SEO] ⚠️ No se pudo rutear el tema ({e}) — sigo como blog")
        return {"decision": "blog", "razon": f"ruteo no disponible: {e}"}


def notify_seo_agent(site_key: str, post_id: int, title: str, content: str, url: str,
                     keyword: str = ""):
    """Manda el borrador al agente SEO, que lo optimiza y lo PROMUEVE a publicado
    solo si pasa las compuertas. HTTP 409/422 = rechazado: se queda en borrador."""
    site_cfg = SITES[site_key]
    seo_agent_url = site_cfg.get("seo_agent_url")
    seo_optimize_path = site_cfg.get("seo_optimize_path", "/optimize-blog")
    en_borrador = site_cfg.get("publish_status", "publish") == "draft"
    if not seo_agent_url:
        print(f"[SEO] Sitio '{site_key}' no tiene seo_agent_url configurado — saltando optimización")
        if en_borrador:
            print(f"[SEO] ⚠️ El post {post_id} queda en BORRADOR: nadie puede promoverlo")
        return {"ok": False, "razon": "sin seo_agent_url"}
    try:
        print(f"[SEO] Enviando blog al agente SEO para optimización ({seo_optimize_path})...")
        response = requests.post(
            f"{seo_agent_url}{seo_optimize_path}",
            json={"post_id": post_id, "title": title, "content": content,
                  "url": url, "keyword": keyword},
            timeout=300
        )
        result = response.json()
        if response.status_code in (409, 422) or result.get("rechazado"):
            motivos = result.get("fallos") or [result.get("motivo", "sin detalle")]
            print("[SEO] ⛔ Artículo RECHAZADO — se queda en borrador:")
            for m in motivos:
                print(f"[SEO]      · {m}")
            notify_nexus(
                action="Blog rechazado por las compuertas SEO",
                detail=f"{title or post_id}: {'; '.join(str(m) for m in motivos)[:180]}",
                url=url)
            return {"ok": False, "rechazado": True, "fallos": motivos}
        if result.get("success"):
            estado = "publicado" if result.get("publicado") else "optimizado"
            print(f"[SEO] ✅ Blog {estado}: {result.get('url', url)}")
            for a in result.get("avisos", []):
                print(f"[SEO]      aviso: {a}")
            return {"ok": True, "url": result.get("url", url)}
        print(f"[SEO] ⚠️ No se pudo optimizar: {result.get('error')}")
        return {"ok": False, "razon": result.get("error")}
    except Exception as e:
        print(f"[SEO] ⚠️ Error al contactar agente SEO: {e}")
        if en_borrador:
            print(f"[SEO] ⚠️ El post {post_id} queda en BORRADOR hasta que se reintente")
        return {"ok": False, "razon": str(e)}


def notify_nexus(action: str, detail: str = None, url: str = None):
    """Reporta una actividad a NEXUS (Centro de Comando). Opcional: solo corre si hay NEXUS_URL y NEXUS_KEY."""
    nexus_url = os.getenv("NEXUS_URL")
    nexus_key = os.getenv("NEXUS_KEY")
    if not nexus_url or not nexus_key:
        return
    try:
        requests.post(
            f"{nexus_url}/api/ingest",
            json={"agent": "Agente Blogs", "action": action, "detail": detail, "url": url},
            headers={"x-nexus-key": nexus_key},
            timeout=15,
        )
        print(f"[NEXUS] ✅ Actividad reportada: {action}")
    except Exception as e:
        print(f"[NEXUS] ⚠️ No se pudo reportar a NEXUS: {e}")


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


def resolver_pais(site_key: str, country: str = None) -> str:
    """País al que le toca la próxima entrada de un sitio binacional.

    Si no se pide uno, publica en el país con MENOS artículos. Nodarishub sirve a
    México y Ecuador desde subcarpetas distintas y la estrategia es Ecuador-first,
    pero el blog arrancó con 10 entradas de México frente a 4 de Ecuador; dejar
    que el país rezagado tenga prioridad corrige ese desnivel solo.
    Devuelve "" si el sitio no es binacional.
    """
    paises = SITES[site_key].get("country_categories") or {}
    if not paises:
        return ""
    if country and country in paises:
        return country
    conteos = {}
    for clave, categoria in paises.items():
        n = contar_posts_por_categoria(site_key, categoria)
        conteos[clave] = n if n >= 0 else 0
    elegido = min(conteos, key=lambda k: conteos[k])
    print(f"[Pipeline] País por reparto: {elegido} (conteo actual: {conteos})")
    return elegido


def conseguir_portada(site_key: str, blog_data: dict, topic: str):
    """Consigue y sube la imagen de portada. Devuelve (media_id, image_data).

    Antes bastaba con que Unsplash fallara una vez para que el post saliera sin
    portada y sin que nadie se enterara: 9 de 20 entradas de nodarishub quedaron
    con el recuadro gris del listado. Ahora se intenta la consulta del artículo,
    luego el nicho del sitio, y el fallo se reporta explícitamente.
    """
    site_cfg = SITES[site_key]
    consultas = [
        blog_data.get("unsplash_query"),
        site_cfg.get("unsplash_fallback"),
        topic,
    ]
    consultas = [c for c in consultas if c]
    usados = get_used_photo_ids(site_key)

    image_data = get_unsplash_image(consultas[0], avoid_ids=usados,
                                    fallback_queries=consultas[1:])
    if not image_data:
        return None, None

    wp_url, headers = get_wp_headers(site_key)
    media_id = upload_image_to_wordpress(
        image_data, wp_url, headers,
        slug=blog_data.get("slug") or blog_data.get("title", ""),
        # El alt describe el artículo; el de Unsplash viene en inglés y genérico.
        alt_text=blog_data.get("image_alt") or blog_data.get("title", ""),
    )
    return media_id, image_data


def run_pipeline(site_key: str, topic: str = None, country: str = None):
    """
    Pipeline completo: tendencias → escritura → imágenes → publicación

    country: para sitios binacionales (nodarishub, sirve MX+EC), fija el país
    ("ec" | "mx"). Si no se indica, lo elige `resolver_pais` por reparto. El país
    decide tanto el tema (location_code de DataForSEO) como la subcarpeta de
    publicación: la categoría que se asigna es lo que hace que la entrada quede
    en /ec/blog/ o /mx/blog/. Ver "nodarishub SEO — Estrategia binacional".
    """
    agent_status["running"] = True
    print(f"\n{'='*50}")
    print(f"[Pipeline] Iniciando para: {site_key}" + (f" (país: {country})" if country else ""))
    print(f"[Pipeline] Hora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}\n")

    try:
        # 0. País (solo sitios binacionales). Se fija ANTES de elegir el tema
        # para que el tema salga del mercado correcto.
        country = resolver_pais(site_key, country) or country

        # 1. Seleccionar tema: explícito > cola priorizada > pick_topic automático
        if not topic:
            topic = pop_queued_topic(site_key)
        if not topic:
            # Los títulos que el sitio ya tiene publicados cuentan como "usados"
            # aunque no estén en el log: hay entradas subidas a mano que el
            # agente nunca registró, y repetirlas canibaliza igual.
            usados = get_used_topics(site_key)
            if SITES[site_key].get("platform", "wordpress") == "wordpress":
                usados += [p["title"] for p in get_posts_list(site_key) if p.get("title")]
            try:
                topic = pick_topic(site_key, usados, country=country)
            except TemasAgotados as e:
                print(f"[Pipeline] ⛔ {e}")
                log_post(site_key, "(sin tema nuevo)", None, success=False, error=str(e))
                notify_nexus(action="Sin tema nuevo que escribir", detail=str(e)[:180])
                agent_status["last_error"] = str(e)
                return
        print(f"[Pipeline] Tema seleccionado: {topic}")

        # 1b. Ruteo por intención: lo transaccional NO es del blog, es de la ficha
        ruta = route_topic(site_key, topic)
        if ruta.get("decision") == "ficha":
            duena = (ruta.get("ficha") or {}).get("nombre") or "una ficha de producto"
            msg = (f"tema transaccional: le corresponde a {duena} — {ruta.get('razon','')}")
            print(f"[Pipeline] ⛔ No se escribe el artículo. {msg}")
            log_post(site_key, topic, None, success=False, error=msg)
            notify_nexus(action="Tema descartado (le toca a la ficha)",
                         detail=f"{topic}: {msg}"[:180],
                         url=(ruta.get("ficha") or {}).get("url"))
            agent_status["last_error"] = msg
            return

        # 2. Generar blog
        blog_data = generate_blog(site_key, topic)

        platform = SITES[site_key].get("platform", "wordpress")

        # 2a. Categoría del país: es lo que coloca la entrada en /ec/blog/ o
        # /mx/blog/. Sin ella se quedaría colgando en la raíz.
        paises = SITES[site_key].get("country_categories") or {}
        if paises and country in paises:
            categorias = list(blog_data.get("categories")
                              or SITES[site_key].get("default_categories", []))
            if paises[country] not in categorias:
                categorias.append(paises[country])
            blog_data["categories"] = categorias
            print(f"[Pipeline] Categorías: {categorias}")

        # 2b. Compuerta de longitud: un artículo por debajo del piso no sale en
        # vivo. El writer ya reintentó expandirlo; si aún así no llega, se deja
        # en borrador para revisión en vez de publicar algo delgado.
        palabras = contar_palabras(blog_data.get("content", ""))
        piso = piso_de_palabras(SITES[site_key])
        forzar_borrador = palabras < piso
        if forzar_borrador:
            print(f"[Pipeline] ⛔ Artículo flaco ({palabras} < {piso}) — se deja en BORRADOR")
            notify_nexus(action="Blog flaco dejado en borrador",
                         detail=f"{blog_data.get('title', topic)}: {palabras} palabras (piso {piso})"[:180])

        # 3-4. Imagen de portada (solo WordPress; Arcade aún no maneja portada)
        featured_media_id, image_data = None, None
        if platform == "wordpress":
            featured_media_id, image_data = conseguir_portada(site_key, blog_data, topic)
            if not featured_media_id:
                print("[Pipeline] ⚠️ El post se publicará SIN imagen de portada")
                notify_nexus(action="Blog sin imagen de portada",
                             detail=f"{blog_data.get('title', topic)}: Unsplash no devolvió imagen usable"[:180])

        # 5. Publicar post (Arcade o WordPress según la plataforma del sitio)
        if platform == "arcade":
            post = arcade_publish_post(site_key, blog_data)
        else:
            post = publish_post(site_key, blog_data, featured_media_id,
                                image_data=image_data, force_draft=forzar_borrador)

        # 6. Registrar
        if post:
            # Comprobar contra el sitio que la portada quedó puesta: el POST de
            # creación puede devolver 200 e ignorar featured_media (p. ej. si el
            # media aún no terminó de procesarse).
            if platform == "wordpress" and featured_media_id:
                if get_featured_media_id(site_key, post["id"]) != featured_media_id:
                    print("[Pipeline] Portada no quedó asignada; reintentando...")
                    set_featured_image(site_key, post["id"], featured_media_id)

            log_post(site_key, topic, post, success=True)
            agent_status["last_post"] = {
                "title": post.get("title", {}).get("rendered", ""),
                "url": post.get("link", ""),
                "date": datetime.now().strftime("%Y-%m-%d %H:%M")
            }
            agent_status["last_error"] = None
            borrador = forzar_borrador or SITES[site_key].get("publish_status", "publish") == "draft"
            print(f"\n[Pipeline] ✅ Blog {'creado como BORRADOR' if borrador else 'publicado'}: {post.get('link')}")

            # 7. Reportar a NEXUS (Centro de Comando)
            notify_nexus(
                action="Creó un borrador de blog" if borrador else "Publicó un blog",
                detail=post.get("title", {}).get("rendered", "") or topic,
                url=post.get("link", ""),
            )

            # 8. Optimizar con agente SEO (config-driven: se salta si el sitio no
            # tiene seo_agent_url, ej. Arcade). En los sitios con
            # publish_status=draft, ESTE paso es el que promueve a publicado.
            notify_seo_agent(
                site_key=site_key,
                post_id=post.get("id"),
                title=post.get("title", {}).get("rendered", ""),
                content=blog_data.get("content", ""),
                url=post.get("link", ""),
                keyword=blog_data.get("rank_math_focus_keyword", "") or topic,
            )
        else:
            agent_status["last_error"] = "Post creation failed"
            log_post(site_key, topic, None, success=False, error="Post creation failed")

    except Exception as e:
        print(f"[Pipeline] ❌ Error: {e}")
        agent_status["last_error"] = str(e)
        log_post(site_key, topic if topic else "unknown", None, success=False, error=str(e))
        notify_nexus(action="Error al publicar un blog", detail=str(e)[:180])
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
    # Selector del editor de horario: incluye la opción "todos los sitios" al inicio
    sched_site_options = '<option value="__all__">🌐 Todos los sitios (parejo)</option>' + sites_options
    # Horario real de cada sitio, para que al cambiar de sitio el form cargue SUS días/hora
    site_schedules_js = json.dumps({
        k: {
            "days": sched_config.get(k, {}).get("publish_days", ["monday", "tuesday", "thursday", "friday"]),
            "time": sched_config.get(k, {}).get("publish_time", "09:00"),
        }
        for k in SITES.keys()
    })

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
            <select id="sched-site" onchange="cargarHorarioSitio()" style="margin-bottom:12px;">{sched_site_options}</select>
            <p style="font-size:13px;color:#aaa;margin:4px 0 10px;">Días de publicación:</p>
            <div id="sched-days" style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:14px;">
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
        const SITE_SCHEDULES = {site_schedules_js};
        function cargarHorarioSitio() {{
            const site = document.getElementById('sched-site').value;
            const sched = SITE_SCHEDULES[site];
            if (!sched) return;  // "__all__" → deja la selección actual como plantilla
            document.querySelectorAll('#sched-days input[type=checkbox]').forEach(cb => {{
                cb.checked = sched.days.includes(cb.value);
            }});
            document.getElementById('sched-time').value = sched.time;
        }}

        async function guardarHorario() {{
            const site = document.getElementById('sched-site').value;
            const time = document.getElementById('sched-time').value;
            const days = Array.from(document.querySelectorAll('#sched-days input[type=checkbox]:checked')).map(cb => cb.value);
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
                    msg.textContent = data.site === '__all__'
                        ? '✅ Horario aplicado a TODOS los sitios.'
                        : '✅ Horario guardado. Se aplicará desde ahora.';
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
    country: str = None  # sitios binacionales (nodarishub): "ec" | "mx"


@app.post("/publish")
def publish_now(req: PublishRequest):
    if agent_status["running"]:
        raise HTTPException(status_code=409, detail="Ya hay una publicación en proceso")
    if req.site_key not in SITES:
        raise HTTPException(status_code=404, detail=f"Sitio '{req.site_key}' no encontrado")

    thread = threading.Thread(target=run_pipeline, args=(req.site_key, req.topic, req.country))
    thread.daemon = True
    thread.start()

    return {"status": "started", "site": req.site_key, "topic": req.topic or "automático",
            "country": req.country or "auto"}


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


@app.get("/topic-queue")
def get_topic_queue():
    """Cola de temas priorizados por sitio (FIFO: el primero se publica en la siguiente corrida)."""
    return load_topic_queue()


class TopicQueueRequest(BaseModel):
    site_key: str
    topics: list  # lista de strings, en orden de prioridad (reemplaza la cola del sitio)


@app.post("/topic-queue")
def set_topic_queue(req: TopicQueueRequest):
    """Reemplaza la cola de temas del sitio con la lista dada (en orden de prioridad)."""
    if req.site_key not in SITES:
        raise HTTPException(status_code=404, detail=f"Sitio '{req.site_key}' no encontrado")
    topics = [str(t).strip() for t in req.topics if str(t).strip()]
    with _queue_lock:
        queue = load_topic_queue()
        queue[req.site_key] = topics
        save_topic_queue(queue)
    return {"status": "updated", "site": req.site_key, "queued": len(topics), "topics": topics}


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
    if req.site_key == "__all__":
        reschedule_all(req.days, req.publish_time)
        return {"status": "updated", "site": "__all__", "days": req.days, "time": req.publish_time}
    if req.site_key not in SITES:
        raise HTTPException(status_code=404, detail=f"Sitio '{req.site_key}' no encontrado")
    reschedule(req.site_key, req.days, req.publish_time)
    return {"status": "updated", "site": req.site_key, "days": req.days, "time": req.publish_time}


@app.post("/fix-author-name")
def fix_author_name():
    results = {}
    for site_key, cfg in SITES.items():
        site_result = {}

        # 1. Cambiar display_name a espacio (oculta el nombre en posts)
        ok = update_author_display_name(site_key, cfg.get("wp_author_name", " "))
        site_result["display_name"] = "✅ limpiado" if ok else "❌ error"

        # 2. Inyectar CSS para ocultar el bloque "Por ..." completo
        css_result = inject_hide_author_css(site_key)
        if css_result["success"]:
            site_result["css"] = f"✅ inyectado via {css_result['method']}"
        else:
            site_result["css"] = "manual"
            site_result["css_to_paste"] = css_result.get("css_to_paste", "")
            site_result["instructions"] = css_result.get("instructions", "")

        results[site_key] = site_result
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


def reschedule_all(days: list, publish_time: str):
    """Aplica el mismo horario a TODOS los sitios de una vez (parejo)."""
    config = load_schedule_config()
    for sk in SITES.keys():
        config[sk] = {"publish_days": days, "publish_time": publish_time}
    save_schedule_config(config)
    schedule.clear()
    schedule_sites()
    print(f"[Scheduler] ✅ Horario aplicado a TODOS los sitios: {days} @ {publish_time}")


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
