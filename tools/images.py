import requests
from openai import OpenAI
from config import UNSPLASH_ACCESS_KEY, OPENAI_API_KEY

_openai_client = None

def _get_openai():
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(api_key=OPENAI_API_KEY)
    return _openai_client


def generate_dalle_image(topic: str, title: str) -> dict | None:
    """
    Genera una imagen con DALL-E 3 basada en el tema del blog.
    Retorna dict compatible con upload_image_to_wordpress.
    """
    try:
        prompt = (
            f"Professional, high-quality lifestyle photograph for a health and sports supplements blog. "
            f"Topic: {topic}. "
            f"Clean, modern aesthetic with natural lighting. White or light neutral background. "
            f"No text, no logos, no watermarks. "
            f"Style: editorial health magazine photography."
        )

        response = _get_openai().images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1792x1024",
            quality="standard",
            n=1
        )

        image_url = response.data[0].url
        print(f"[Images] ✅ Imagen generada con DALL-E 3 para: {topic}")

        return {
            "url": image_url,
            "full_url": image_url,
            "thumb_url": image_url,
            "photographer": "dalle-ai-generated",
            "photographer_url": "",
            "unsplash_url": "",
            "alt_text": title,
            "width": 1792,
            "height": 1024
        }

    except Exception as e:
        print(f"[Images] Error generando imagen con DALL-E: {e}")
        return None


def get_unsplash_image(query: str) -> dict | None:
    """
    Busca una imagen en Unsplash relacionada con el query.
    Retorna dict con url, photographer y attribution.
    """
    try:
        url = "https://api.unsplash.com/search/photos"
        params = {
            "query": query,
            "per_page": 5,
            "orientation": "landscape",
            "content_filter": "high"
        }
        headers = {"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"}

        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        if not data.get("results"):
            print(f"[Images] No se encontraron imágenes para: {query}")
            return None

        # Tomar la primera imagen
        photo = data["results"][0]

        # Trigger download (requerido por Unsplash API guidelines)
        download_url = photo["links"]["download_location"]
        requests.get(
            download_url,
            headers={"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"},
            timeout=10
        )

        return {
            "url": photo["urls"]["regular"],
            "full_url": photo["urls"]["full"],
            "thumb_url": photo["urls"]["small"],
            "photographer": photo["user"]["name"],
            "photographer_url": photo["user"]["links"]["html"],
            "unsplash_url": photo["links"]["html"],
            "alt_text": photo.get("alt_description", query),
            "width": photo["width"],
            "height": photo["height"]
        }

    except Exception as e:
        print(f"[Images] Error obteniendo imagen de Unsplash: {e}")
        return None


def upload_image_to_wordpress(image_data: dict, wp_url: str, headers: dict) -> int | None:
    """
    Descarga la imagen de Unsplash y la sube a WordPress Media Library.
    Retorna el media_id o None si falla.
    """
    try:
        # Descargar imagen
        img_response = requests.get(image_data["url"], timeout=30)
        img_response.raise_for_status()

        # Subir a WordPress
        media_url = f"{wp_url}/wp-json/wp/v2/media"
        filename = f"blog-image-{image_data['photographer'].replace(' ', '-').lower()}.jpg"

        media_headers = {
            **headers,
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "image/jpeg"
        }

        media_response = requests.post(
            media_url,
            headers=media_headers,
            data=img_response.content,
            timeout=30
        )
        media_response.raise_for_status()
        media_id = media_response.json()["id"]

        # Actualizar alt text
        requests.post(
            f"{media_url}/{media_id}",
            headers=headers,
            json={"alt_text": image_data["alt_text"]},
            timeout=10
        )

        print(f"[Images] Imagen subida a WordPress, ID: {media_id}")
        return media_id

    except Exception as e:
        print(f"[Images] Error subiendo imagen a WordPress: {e}")
        return None
