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
DEFAULT_SEO_AGENT_URL = "https://web-production-3743c.up.railway.app"

# --- SEO binacional de nodarishub (MX + EC) --------------------------------- #
# nodarishub sirve a México y Ecuador. Estrategia (2026-07-15, ver vault
# "nodarishub SEO — Estrategia binacional"): un dominio con subcarpetas /ec/ /mx/,
# esfuerzo Ecuador-first. Los temas de blog se generan por país usando el
# location_code de DataForSEO. Con un solo blog (hoy) el default combina ambos;
# cuando existan las subcarpetas, cada país publicará en la suya (el `country`
# ya fluye por el pipeline). MX tiene 5-6x el volumen de EC para las mismas kws.
NODARIS_LOCATIONS = {"ec": 2218, "mx": 2484}  # Ecuador / México
# Sitios binacionales: qué países cubren cuando no se especifica uno.
SITE_COUNTRIES = {"nodarishub": ["ec", "mx"]}


def _fetch_blog_topics(seo_url, market, seeds, location_code=None) -> tuple[list[str], float]:
    """Una llamada al endpoint /blog-topics. Devuelve (keywords, costo)."""
    payload = {"market": market, "seeds": seeds}
    if location_code:
        payload["location_code"] = location_code
    r = requests.post(f"{seo_url.rstrip('/')}/blog-topics", json=payload, timeout=120)
    r.raise_for_status()
    data = r.json()
    kws = [t.get("keyword") for t in data.get("topics", []) if t.get("keyword")]
    return kws, (data.get("cost_usd") or 0.0)


def get_dataforseo_topics(site_key: str, country: str = None, max_seeds: int = 4) -> list[str]:
    """Temas data-driven (volumen real + KD alcanzable) vía el endpoint
    /blog-topics del SEO Agent, que consulta DataForSEO Labs.

    Muestrea max_seeds semillas al azar de la config (acota costo: cada semilla
    = 1 llamada a la API, ~$0.018). Devuelve keywords ordenadas por volumen, o
    [] si el sitio no tiene market DataForSEO o si algo falla (el caller cae al
    fallback de pytrends/seeds).

    country: para sitios binacionales (nodarishub) selecciona el país ("ec" |
    "mx"). Si es None y el sitio es binacional, combina ambos países (dedup por
    keyword). Para sitios de un solo país, se ignora.
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

    # Países a consultar: el pedido explícito, o los del sitio binacional, o
    # [None] (usa la ubicación propia del market) para sitios de un solo país.
    if country:
        countries = [country]
    else:
        countries = SITE_COUNTRIES.get(site_key) or [None]

    try:
        merged: list[str] = []
        total_cost = 0.0
        for c in countries:
            loc = NODARIS_LOCATIONS.get(c) if c else None
            kws, cost = _fetch_blog_topics(seo_url, market, seeds, location_code=loc)
            total_cost += cost
            for kw in kws:
                if kw not in merged:
                    merged.append(kw)
        # Si combinamos países, reordenar no es trivial (cada país trae su orden
        # por volumen); merged preserva prioridad del primer país (ec = foco).
        if merged:
            etiqueta = f"{site_key}" + (f"/{country}" if country else "")
            print(f"[DataForSEO] {etiqueta}: {len(merged)} temas (costo ${total_cost:.5f})")
        return merged
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


def pick_topic(site_key: str, used_topics: list[str] = [], country: str = None) -> str:
    """
    Selecciona el tema más relevante que no haya sido usado recientemente.

    Prioridad: (1) DataForSEO (volumen real + KD alcanzable, ordenado por
    volumen), (2) fallback a pytrends/keywords seed si DataForSEO no aplica o
    falla. Así el pipeline nunca se queda sin tema aunque la API esté caída.

    country: para sitios binacionales (nodarishub), fija el país del tema
    ("ec" | "mx"). None = combina ambos (Ecuador primero). Se ignora en sitios
    de un solo país.
    """
    topics = get_dataforseo_topics(site_key, country=country)
    if not topics:
        topics = get_trending_topics(site_key)

    for topic in topics:
        if topic not in used_topics:
            return topic

    # Si todos fueron usados, regresar el primero de todos modos
    return topics[0] if topics else SITES[site_key]["keywords_seed"][0]
