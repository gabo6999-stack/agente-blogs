"""Publicador para Arcade Motors MX (sitio PHP propio, NO WordPress).
Postea al endpoint /api/blog-publish.php. Arcade arma solo el schema, canonical,
sitemap e IndexNow; aquí solo mandamos título + contenido + meta + slug."""

import requests
from config import SITES


def publish_post(site_key: str, blog_data: dict, featured_media_id=None) -> dict | None:
    """Publica un post en Arcade Motors MX. Devuelve un dict con forma compatible
    con la respuesta de WordPress (id, link, title) para que el pipeline lo registre igual."""
    site = SITES[site_key]
    url = site.get("arcade_url")
    api_key = site.get("arcade_api_key")
    if not url or not api_key:
        print("[Arcade] Falta arcade_url o arcade_api_key en la config (revisa el .env)")
        return None

    payload = {
        "titulo": blog_data.get("title", ""),
        "slug": blog_data.get("slug", ""),
        "contenido": blog_data.get("content", ""),
        "resumen": blog_data.get("excerpt") or blog_data.get("rank_math_description", ""),
        "status": "publicado",
    }

    try:
        r = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            print(f"[Arcade] Error del endpoint: {data.get('error')}")
            return None
        post_url = data.get("url", "")
        print(f"[Arcade] Post publicado: {post_url}")
        return {
            "id": data.get("id"),
            "link": post_url,
            "title": {"rendered": blog_data.get("title", "")},
        }
    except Exception as e:
        print(f"[Arcade] Error publicando post: {e}")
        if hasattr(e, "response") and e.response is not None:
            print(f"[Arcade] Respuesta: {e.response.text[:500]}")
        return None
