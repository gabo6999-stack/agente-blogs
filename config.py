import os
from dotenv import load_dotenv

load_dotenv()

# Site config — fácil de extender para multisitio
SITES = {
    "peptidosysuplementos": {
        "wp_url": os.getenv("SITE1_WP_URL"),
        "wp_user": os.getenv("SITE1_WP_USER"),
        "wp_password": os.getenv("SITE1_WP_PASSWORD"),
        "niche": "péptidos y suplementos deportivos",
        "language": "es",
        "keywords_seed": [
            "péptidos", "BPC-157", "TB-500", "retatrutide", "IGF-1",
            "suplementos deportivos", "pérdida de grasa", "masa muscular",
            "recuperación muscular", "biohacking", "longevidad",
            "GHK-Cu", "MOTS-c", "hormona de crecimiento", "testosterona",
            "composición corporal", "rendimiento deportivo"
        ],
        "publish_days": ["monday", "tuesday", "thursday", "friday"],
        "publish_time": "09:00",
        "post_length": 1500,
    }
}

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY")
