import requests
from requests.auth import HTTPBasicAuth
from config import SITES


def get_current_user_id(site_key: str) -> int | None:
    wp_url, headers = get_wp_headers(site_key)
    try:
        r = requests.get(f"{wp_url}/wp-json/wp/v2/users/me", headers=headers, timeout=10)
        return r.json().get("id")
    except Exception as e:
        print(f"[WP] Error obteniendo usuario actual: {e}")
        return None


def update_author_display_name(site_key: str, display_name: str) -> bool:
    wp_url, headers = get_wp_headers(site_key)
    user_id = get_current_user_id(site_key)
    if not user_id:
        print(f"[WP] No se pudo obtener el ID del usuario para {site_key}")
        return False
    try:
        r = requests.post(
            f"{wp_url}/wp-json/wp/v2/users/{user_id}",
            headers=headers,
            json={"name": display_name},
            timeout=10
        )
        result = r.json()
        if "id" in result:
            print(f"[WP] ✅ Display name actualizado a '{display_name}' en {site_key}")
            return True
        print(f"[WP] ❌ Error: {result}")
        return False
    except Exception as e:
        print(f"[WP] Error actualizando display name: {e}")
        return False


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


def get_posts_list(site_key: str, per_page: int = 100) -> list[dict]:
    """
    Retorna lista de posts publicados: id, title, url.
    """
    wp_url, headers = get_wp_headers(site_key)
    try:
        response = requests.get(
            f"{wp_url}/wp-json/wp/v2/posts",
            headers=headers,
            params={"per_page": per_page, "orderby": "date", "order": "desc", "status": "publish"},
            timeout=15
        )
        response.raise_for_status()
        return [
            {"id": p["id"], "title": p["title"]["rendered"], "url": p["link"]}
            for p in response.json()
        ]
    except Exception as e:
        print(f"[WP] Error obteniendo lista de posts: {e}")
        return []


def get_post(site_key: str, post_id: int) -> dict | None:
    """
    Obtiene un post existente de WordPress por ID.
    Retorna el post raw o None si falla.
    """
    wp_url, headers = get_wp_headers(site_key)
    try:
        response = requests.get(
            f"{wp_url}/wp-json/wp/v2/posts/{post_id}",
            headers=headers,
            params={"context": "edit"},
            timeout=15
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"[WP] Error obteniendo post {post_id}: {e}")
        return None


def get_tag_names(site_key: str, tag_ids: list[int]) -> list[str]:
    """
    Convierte una lista de IDs de tags a nombres.
    """
    if not tag_ids:
        return []
    wp_url, headers = get_wp_headers(site_key)
    try:
        response = requests.get(
            f"{wp_url}/wp-json/wp/v2/tags",
            headers=headers,
            params={"include": ",".join(map(str, tag_ids)), "per_page": 100},
            timeout=10
        )
        if response.status_code == 200:
            return [t["name"] for t in response.json()]
    except Exception as e:
        print(f"[WP] Error obteniendo nombres de tags: {e}")
    return []


def set_featured_image(site_key: str, post_id: int, featured_media_id: int) -> dict | None:
    """
    Actualiza solo la imagen destacada de un post existente.
    """
    wp_url, headers = get_wp_headers(site_key)
    try:
        response = requests.put(
            f"{wp_url}/wp-json/wp/v2/posts/{post_id}",
            headers=headers,
            json={"featured_media": featured_media_id},
            timeout=30
        )
        response.raise_for_status()
        post = response.json()
        print(f"[WP] Imagen actualizada en post: {post['link']}")
        return post
    except Exception as e:
        print(f"[WP] Error actualizando imagen: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"[WP] Respuesta: {e.response.text[:500]}")
        return None


def update_post(site_key: str, post_id: int, blog_data: dict, featured_media_id: int = None) -> dict | None:
    """
    Actualiza un post existente en WordPress con los campos proporcionados.
    Retorna el post actualizado o None si falla.
    """
    wp_url, headers = get_wp_headers(site_key)

    payload = {
        "title": blog_data["title"],
        "content": blog_data.get("content", ""),
        "excerpt": blog_data.get("excerpt", ""),
        "meta": {
            "rank_math_title": blog_data.get("rank_math_title", ""),
            "rank_math_description": blog_data.get("rank_math_description", ""),
            "rank_math_focus_keyword": blog_data.get("rank_math_focus_keyword", ""),
        }
    }

    if featured_media_id:
        payload["featured_media"] = featured_media_id

    tags = blog_data.get("tags", [])
    if tags:
        tag_ids = get_or_create_tags(wp_url, headers, tags)
        if tag_ids:
            payload["tags"] = tag_ids

    try:
        response = requests.put(
            f"{wp_url}/wp-json/wp/v2/posts/{post_id}",
            headers=headers,
            json=payload,
            timeout=30
        )
        response.raise_for_status()
        post = response.json()
        print(f"[WP] Post actualizado: {post['link']}")
        return post
    except Exception as e:
        print(f"[WP] Error actualizando post: {e}")
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
