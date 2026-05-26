import requests
from requests.auth import HTTPBasicAuth
from config import SITES


def get_wp_headers(site_key: str) -> tuple[str, dict]:
    """
    Retorna la URL base y headers de autenticación para WordPress.
    """
    site = SITES[site_key]
    wp_url = site["wp_url"]
    
    # Autenticación básica (funciona con Application Passwords de WP)
    auth = HTTPBasicAuth(site["wp_user"], site["wp_password"])
    
    # Obtener JWT token
    token_response = requests.post(
        f"{wp_url}/wp-json/jwt-auth/v1/token",
        json={
            "username": site["wp_user"],
            "password": site["wp_password"]
        },
        timeout=15
    )
    
    if token_response.status_code == 200:
        token = token_response.json().get("token")
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
    else:
        # Fallback a Basic Auth si JWT falla
        print("[WP] JWT falló, usando Basic Auth")
        import base64
        credentials = base64.b64encode(
            f"{site['wp_user']}:{site['wp_password']}".encode()
        ).decode()
        headers = {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json"
        }
    
    return wp_url, headers


def publish_post(site_key: str, blog_data: dict, featured_media_id: int = None) -> dict | None:
    """
    Publica el post en WordPress con metadatos de Rank Math.
    Retorna el post creado o None si falla.
    """
    wp_url, headers = get_wp_headers(site_key)

    # Agregar atribución de Unsplash al final del contenido si hay imagen
    content = blog_data.get("content", "")

    payload = {
        "title": blog_data["title"],
        "slug": blog_data.get("slug", ""),
        "content": content,
        "excerpt": blog_data.get("excerpt", ""),
        "status": "publish",
        "meta": {
            "rank_math_title": blog_data.get("rank_math_title", blog_data["title"]),
            "rank_math_description": blog_data.get("rank_math_description", ""),
            "rank_math_focus_keyword": blog_data.get("rank_math_focus_keyword", ""),
        }
    }

    # Agregar imagen destacada si existe
    if featured_media_id:
        payload["featured_media"] = featured_media_id

    # Agregar tags si existen
    tags = blog_data.get("tags", [])
    if tags:
        tag_ids = get_or_create_tags(wp_url, headers, tags)
        if tag_ids:
            payload["tags"] = tag_ids

    try:
        response = requests.post(
            f"{wp_url}/wp-json/wp/v2/posts",
            headers=headers,
            json=payload,
            timeout=30
        )
        response.raise_for_status()
        post = response.json()
        print(f"[WP] Post publicado: {post['link']}")
        return post

    except Exception as e:
        print(f"[WP] Error publicando post: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"[WP] Respuesta: {e.response.text[:500]}")
        return None


def get_or_create_tags(wp_url: str, headers: dict, tag_names: list[str]) -> list[int]:
    """
    Obtiene o crea tags en WordPress. Retorna lista de IDs.
    """
    tag_ids = []
    
    for tag_name in tag_names:
        try:
            # Buscar si ya existe
            search = requests.get(
                f"{wp_url}/wp-json/wp/v2/tags",
                headers=headers,
                params={"search": tag_name},
                timeout=10
            )
            results = search.json()
            
            if results:
                tag_ids.append(results[0]["id"])
            else:
                # Crear nuevo tag
                create = requests.post(
                    f"{wp_url}/wp-json/wp/v2/tags",
                    headers=headers,
                    json={"name": tag_name},
                    timeout=10
                )
                if create.status_code == 201:
                    tag_ids.append(create.json()["id"])
        except Exception as e:
            print(f"[WP] Error con tag '{tag_name}': {e}")
    
    return tag_ids
