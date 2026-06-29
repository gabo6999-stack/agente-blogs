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
        "unsplash_fallback": "peptides supplements sports performance",
        "seo_agent_url": os.getenv("SEO_AGENT_URL", "https://web-production-3743c.up.railway.app"),
        "seo_optimize_path": "/optimize-blog",
        "wp_author_name": " ",
        "default_categories": ["Blog"],
    },
    "grupoptm": {
        "wp_url": os.getenv("SITE2_WP_URL"),
        "wp_user": os.getenv("SITE2_WP_USER"),
        "wp_password": os.getenv("SITE2_WP_PASSWORD"),
        "niche": "telemedicina de péptidos y salud hormonal en México",
        "language": "es",
        "keywords_seed": [
            "telemedicina péptidos México", "semaglutide México", "péptidos para adelgazar",
            "consulta médica péptidos", "retatrutide México", "longevidad péptidos",
            "pérdida de peso péptidos", "GLP-1 México", "péptidos hormonales",
            "medicina anti-aging México", "BPC-157 médico", "hormona de crecimiento terapéutica",
            "médico especialista péptidos", "telemedicina bienestar", "tratamiento hormonal péptidos"
        ],
        "publish_days": ["monday", "tuesday", "thursday", "friday"],
        "publish_time": "09:00",
        "post_length": 1500,
        "unsplash_fallback": "telemedicine doctor consultation health",
        "seo_agent_url": os.getenv("SEO_AGENT_URL", "https://web-production-3743c.up.railway.app"),
        "seo_optimize_path": "/optimize-ptm-blog",
        "wp_author_name": "PTM",
        "default_categories": ["Blog"],
    },
    "arcademotors": {
        "platform": "arcade",                                   # NO es WordPress: postea al endpoint propio
        "arcade_url": os.getenv("ARCADE_URL", "https://arcademotorsmx.com/api/blog-publish.php"),
        "arcade_api_key": os.getenv("ARCADE_API_KEY"),
        "niche": "compra y venta de autos usados y seminuevos en México",
        "language": "es",
        "keywords_seed": [
            "autos usados", "autos seminuevos", "comprar auto", "vender auto",
            "precio de autos", "trámites vehiculares", "cambio de propietario",
            "factura de auto", "tenencia", "verificación vehicular", "REPUVE",
            "financiamiento de autos", "inspección pre-compra", "kilometraje",
            "autos en México", "consejos para vender un auto", "evitar estafas al comprar auto",
        ],
        "publish_days": ["monday", "wednesday", "friday"],
        "publish_time": "10:00",
        "post_length": 1200,
        "unsplash_fallback": "used car mexico",
    },
}

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY")
