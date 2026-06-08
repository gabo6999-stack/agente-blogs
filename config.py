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
        "seo_agent_url": None,  # pendiente: endpoint PTM en ecommerce-agent
    },
}

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY")
