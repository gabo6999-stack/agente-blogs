import os
import random
import requests
from pytrends.request import TrendReq
from config import SITES

# Sitios del Blog Agent que tienen un market en DataForSEO (vía el SEO Agent).
# grupoptm/PTM NO está (telemedicina, fuera del alcance de DataForSEO).
SITE_TO_MARKET = {
    "peptidosysuplementos": "pys",
    "arcademotors": "arcade",
    "nodarishub": "nodaris_ec",
}
# Override de ubicación SOLO para temas de blog. nodarishub sirve MX+EC con un
# solo blog en español; México tiene 5-6x el volumen de Ecuador para las mismas
# keywords, así que los temas se sacan de México (2484). El content_gap del
# mismo sitio se mide aparte contra competidores de Ecuador (market nodaris_ec).
SITE_TOPICS_LOCATION = {
    "nodarishub": 2484,  # México
}
DEFAULT_SEO_AGENT_URL = "https://web-production-3743c.up.railway.app"


def get_dataforseo_topics(site_key: str, max_seeds: int = 4) -> list[str]:
    """Temas data-driven (volumen real + KD alcanzable) vía el endpoint
    /blog-topics del SEO Agent, que consulta DataForSEO Labs.

    Muestrea max_seeds semillas al azar de la config (acota costo: cada semilla
    = 1 llamada a la API, ~$0.018). Devuelve keywords ordenadas por volumen, o
    [] si el sitio no tiene market DataForSEO o si algo falla (el caller cae al
    fallback de pytrends/seeds).
    """
    market = SITE_TO_MARKET.get(site_key)
    if not market:
        return []  # p. ej. grupoptm: sin market DataForSEO
    site = SITES[site_key]
    seo_url = site.get("seo_agent_url") or os.getenv("SEO_AGENT_URL") or DEFAULT_SEO_AGENT_URL

    seeds = list(site.get("keywords_seed", []))
    if not seeds:
        return []
    random.shuffle(seeds)
    seeds = seeds[:max_seeds]

    payload = {"market": market, "seeds": seeds}
    loc = SITE_TOPICS_LOCATION.get(site_key)
    if loc:
        payload["location_code"] = loc

    try:
        r = requests.post(
            f"{seo_url.rstrip('/')}/blog-topics",
            json=payload,
            timeout=120,
        )
        r.raise_for_status()
        data = r.json()
        topics = [t.get("keyword") for t in data.get("topics", []) if t.get("keyword")]
        if topics:
            print(f"[DataForSEO] {site_key}: {len(topics)} temas (costo ${data.get('cost_usd')})")
        return topics
    except Exception as e:
        print(f"[DataForSEO] fallo para {site_key}, uso fallback: {e}")
        return []


def get_trending_topics(site_key: str) -> list[str]:
    """
    Obtiene tendencias relevantes para el nicho del sitio.
    Combina Google Trends con keywords seed del config.
    """
    site = SITES[site_key]
    keywords_seed = site["keywords_seed"]

    try:
        pytrends = TrendReq(hl='es-MX', tz=360)

        # Buscar tendencias relacionadas con keywords seed (en grupos de 5)
        trending = []
        sample_keywords = random.sample(keywords_seed, min(5, len(keywords_seed)))

        pytrends.build_payload(sample_keywords, cat=0, timeframe='now 7-d', geo='MX')
        related = pytrends.related_queries()

        for kw in sample_keywords:
            if related.get(kw) and related[kw].get('top') is not None:
                top_queries = related[kw]['top']['query'].tolist()[:3]
                trending.extend(top_queries)

        # Si no hay tendencias, usar keywords seed directamente
        if not trending:
            trending = keywords_seed

        # Mezclar y retornar top 10 únicos
        unique_trending = list(dict.fromkeys(trending))
        random.shuffle(unique_trending)
        return unique_trending[:10]

    except Exception as e:
        print(f"[Trends] Error obteniendo tendencias: {e}")
        # Fallback a keywords seed
        shuffled = keywords_seed.copy()
        random.shuffle(shuffled)
        return shuffled[:10]


def pick_topic(site_key: str, used_topics: list[str] = []) -> str:
    """
    Selecciona el tema más relevante que no haya sido usado recientemente.

    Prioridad: (1) DataForSEO (volumen real + KD alcanzable, ordenado por
    volumen), (2) fallback a pytrends/keywords seed si DataForSEO no aplica o
    falla. Así el pipeline nunca se queda sin tema aunque la API esté caída.
    """
    topics = get_dataforseo_topics(site_key)
    if not topics:
        topics = get_trending_topics(site_key)

    for topic in topics:
        if topic not in used_topics:
            return topic

    # Si todos fueron usados, regresar el primero de todos modos
    return topics[0] if topics else SITES[site_key]["keywords_seed"][0]
