"""
Agente de publicación automática de blogs
Sitio: peptidosysuplementos.mx
Frecuencia: Lunes, Martes, Jueves, Viernes @ 9:00am
"""

import schedule
import time
from datetime import datetime

from config import SITES
from tools.trends import pick_topic
from tools.writer import generate_blog
from tools.images import get_unsplash_image, upload_image_to_wordpress
from tools.wordpress import publish_post, get_wp_headers
from tools.logger import log_post, get_used_topics


def run_pipeline(site_key: str):
    """
    Pipeline completo: tendencias → escritura → imágenes → publicación
    """
    print(f"\n{'='*50}")
    print(f"[Pipeline] Iniciando para: {site_key}")
    print(f"[Pipeline] Hora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}\n")

    try:
        # 1. Seleccionar tema basado en tendencias
        used_topics = get_used_topics(site_key)
        topic = pick_topic(site_key, used_topics)
        print(f"[Pipeline] Tema seleccionado: {topic}")

        # 2. Generar blog con Claude + web_search
        blog_data = generate_blog(site_key, topic)

        # 3. Obtener imagen de Unsplash
        unsplash_query = blog_data.get("unsplash_query", topic)
        image_data = get_unsplash_image(unsplash_query)

        # 4. Subir imagen a WordPress
        featured_media_id = None
        if image_data:
            wp_url, headers = get_wp_headers(site_key)
            featured_media_id = upload_image_to_wordpress(image_data, wp_url, headers)

        # 5. Publicar post
        post = publish_post(site_key, blog_data, featured_media_id)

        # 6. Registrar resultado
        if post:
            log_post(site_key, topic, post, success=True)
            print(f"\n[Pipeline] ✅ Blog publicado exitosamente!")
            print(f"[Pipeline] URL: {post.get('link', 'N/A')}")
        else:
            log_post(site_key, topic, None, success=False, error="Post creation failed")

    except Exception as e:
        print(f"[Pipeline] ❌ Error en pipeline: {e}")
        log_post(site_key, topic if 'topic' in locals() else "unknown",
                 None, success=False, error=str(e))


def schedule_sites():
    """
    Configura el scheduler para todos los sitios.
    """
    for site_key, site_config in SITES.items():
        publish_time = site_config.get("publish_time", "09:00")
        publish_days = site_config.get("publish_days", ["monday", "tuesday", "thursday", "friday"])

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


if __name__ == "__main__":
    print("🚀 Agente de blogs iniciado")
    print(f"Sitios configurados: {list(SITES.keys())}\n")

    # Configurar scheduler
    schedule_sites()

    print("\n⏰ Esperando próxima publicación programada...")
    print("(Ctrl+C para detener)\n")

    # Loop principal
    while True:
        schedule.run_pending()
        time.sleep(60)
