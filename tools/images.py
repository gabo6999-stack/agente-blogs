import re
import unicodedata

import requests
from config import UNSPLASH_ACCESS_KEY

UNSPLASH_SEARCH = "https://api.unsplash.com/search/photos"


def _slugify(texto: str, limite: int = 60) -> str:
    plano = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    plano = re.sub(r"[^a-zA-Z0-9]+", "-", plano).strip("-").lower()
    return plano[:limite].strip("-") or "blog"


def _buscar(query: str, per_page: int = 12) -> list[dict]:
    r = requests.get(
        UNSPLASH_SEARCH,
        params={"query": query, "per_page": per_page,
                "orientation": "landscape", "content_filter": "high"},
        headers={"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json().get("results", []) or []


def get_unsplash_image(query: str, avoid_ids=None, fallback_queries=None) -> dict | None:
    """Busca en Unsplash una foto que NO se haya usado ya en el blog.

    Antes tomaba siempre `results[0]`, así que dos temas parecidos aterrizaban en
    la misma foto: tres pares de posts terminaron compartiendo portada. Ahora
    recorre los resultados y descarta los ids ya usados, y si una búsqueda se
    queda sin candidatos nuevos prueba las siguientes (`fallback_queries`) antes
    de rendirse.
    """
    avoid = set(avoid_ids or ())
    intentos = [q for q in [query, *(fallback_queries or [])] if q]
    repetida = None

    for q in intentos:
        try:
            resultados = _buscar(q)
        except Exception as e:
            print(f"[Images] Búsqueda fallida para '{q}': {e}")
            continue
        if not resultados:
            print(f"[Images] Sin resultados para: {q}")
            continue
        nuevas = [p for p in resultados if p["id"] not in avoid]
        if not nuevas:
            repetida = repetida or resultados[0]
            print(f"[Images] Todas las fotos de '{q}' ya se usaron; sigo buscando")
            continue
        return _empaquetar(nuevas[0], q)

    if repetida:
        # Mejor una portada repetida que ninguna: el placeholder gris del listado
        # es peor para el lector que ver dos veces la misma foto.
        print("[Images] ⚠️ Sin fotos nuevas; reutilizo una ya publicada")
        return _empaquetar(repetida, intentos[0] if intentos else query)

    print(f"[Images] ❌ Ninguna búsqueda dio imagen: {intentos}")
    return None


def _empaquetar(photo: dict, query: str) -> dict:
    try:
        requests.get(
            photo["links"]["download_location"],
            headers={"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"},
            timeout=10,
        )
    except Exception:
        pass  # el ping de descarga es cortesía con Unsplash, no debe tumbar la publicación

    return {
        "id": photo["id"],
        "url": photo["urls"]["regular"],
        "full_url": photo["urls"]["full"],
        "thumb_url": photo["urls"]["small"],
        "photographer": photo["user"]["name"],
        "photographer_url": photo["user"]["links"]["html"],
        "unsplash_url": photo["links"]["html"],
        "alt_text": photo.get("alt_description") or query,
        "width": photo["width"],
        "height": photo["height"],
    }


def upload_image_to_wordpress(image_data: dict, wp_url: str, headers: dict,
                              slug: str = "", alt_text: str = "") -> int | None:
    """Sube la foto a la biblioteca de medios y devuelve su media_id.

    El nombre de archivo lleva el slug del post y el id de Unsplash: así cada
    entrada tiene su propio archivo (antes se nombraban por fotógrafo y WordPress
    los desambiguaba con sufijos -1, -2) y se puede saber qué fotos ya se usaron
    sin guardar estado aparte.
    """
    try:
        img = requests.get(image_data["url"], timeout=30)
        img.raise_for_status()

        media_url = f"{wp_url}/wp-json/wp/v2/media"
        nombre = f"blog-{_slugify(slug) if slug else 'post'}-{image_data.get('id', 'unsplash')}.jpg"

        subida = requests.post(
            media_url,
            headers={**headers,
                     "Content-Disposition": f'attachment; filename="{nombre}"',
                     "Content-Type": "image/jpeg"},
            data=img.content,
            timeout=60,
        )
        subida.raise_for_status()
        media_id = subida.json()["id"]

        # Alt descriptivo del artículo, no la descripción cruda en inglés que trae
        # Unsplash ("monitor screengrab"), que no dice nada del contenido.
        alt = (alt_text or image_data.get("alt_text") or "").strip()
        requests.post(media_url + f"/{media_id}", headers=headers,
                      json={"alt_text": alt, "title": alt}, timeout=15)

        print(f"[Images] Imagen subida: {nombre} (media_id={media_id})")
        return media_id

    except Exception as e:
        print(f"[Images] Error subiendo imagen a WordPress: {e}")
        return None
