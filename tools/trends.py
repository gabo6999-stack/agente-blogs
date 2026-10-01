import os
import random
import re
import requests
from pytrends.request import TrendReq
from config import SITES


class TemasAgotados(RuntimeError):
    """No queda ningún tema que no repita contenido ya publicado."""

# Sitios del Blog Agent que tienen un market en DataForSEO (vía el SEO Agent).
# telenzia NO está (telemedicina, fuera del alcance de DataForSEO).
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


def get_dataforseo_topics(site_key: str, country: str = None, max_seeds: int = 8) -> list[str]:
    """Temas data-driven (volumen real + KD alcanzable) vía el endpoint
    /blog-topics del SEO Agent, que consulta DataForSEO Labs.

    Muestrea max_seeds semillas al azar de la config (acota costo: cada semilla
    = 1 llamada a la API, ~$0.018). Devuelve keywords ordenadas por volumen, o
    [] si el sitio no tiene market DataForSEO o si algo falla (el caller cae al
    fallback de pytrends/seeds).

    max_seeds subió de 4 a 8 el 2026-08-13: con 4, el agente veía una fracción
    tan pequeña del universo de keywords que el tema elegido dependía de qué
    semillas tocaran esa corrida. Medido sobre nodarishub, 4 semillas devolvían
    7 temas y las 14 semillas devuelven 38 con el filtro ya endurecido.

    country: para sitios binacionales (nodarishub) selecciona el país ("ec" |
    "mx"). Si es None y el sitio es binacional, combina ambos países (dedup por
    keyword). Para sitios de un solo país, se ignora.
    """
    market = SITE_TO_MARKET.get(site_key)
    if not market:
        return []  # p. ej. telenzia: sin market DataForSEO
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


def get_idea_topics(site_key: str, used_topics: list[str]) -> list[str]:
    """Temas propuestos por Claude a partir de lo ya publicado (topic_ideas=True).

    Para sitios que publican sin fecha de fin y sin market en DataForSEO: con solo
    las semillas, "primera infancia" o "juego libre" chocan enseguida con los
    artículos que ya existen y el agente se queda sin tema. Aquí el modelo ve los
    títulos publicados y propone ángulos concretos que no estén cubiertos.
    """
    import json
    import anthropic
    from config import ANTHROPIC_API_KEY

    site = SITES[site_key]
    publicados = "\n".join(f"- {t}" for t in (used_topics or [])[:150])
    prompt = (
        f"Eres editor del blog de un sitio sobre {site['niche']}.\n"
        f"Estos artículos YA están publicados:\n{publicados or '(ninguno)'}\n\n"
        "Propón 12 temas NUEVOS para el blog, que una familia buscaría en Google y que no repitan "
        "ni parafraseen los de la lista. Prefiere ángulos concretos (una edad, una situación, una "
        "época del año, una pregunta práctica) sobre temas generales. Inspírate en: "
        f"{', '.join(site.get('keywords_seed', []))}.\n"
        'Responde SOLO con un JSON: ["tema 1", "tema 2", ...] (cada tema de 4 a 10 palabras, en español).'
    )
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(model="claude-sonnet-4-6", max_tokens=1200,
                                      messages=[{"role": "user", "content": prompt}])
        texto = "".join(b.text for b in resp.content if hasattr(b, "text"))
        temas = json.loads(texto[texto.find("["):texto.rfind("]") + 1])
        temas = [t.strip() for t in temas if isinstance(t, str) and t.strip()]
        print(f"[Trends] {len(temas)} ideas de tema propuestas para {site_key}")
        return temas
    except Exception as e:
        print(f"[Trends] Ideas de tema fallaron ({e}); uso las semillas")
        return []


_VACIAS = {
    "de", "la", "el", "en", "para", "que", "tu", "un", "una", "y", "o", "por", "con",
    "los", "las", "del", "al", "es", "como", "cómo", "mi", "se", "sirve", "son", "guia",
    "guía", "paso", "mejor", "mejores", "sobre", "cual", "cuál", "qué", "que",
}


def _nucleo(frase: str) -> set:
    """Palabras con carga semántica de un tema, sin acentos ni relleno."""
    import unicodedata
    plano = unicodedata.normalize("NFKD", (frase or "").lower()).encode("ascii", "ignore").decode()
    return {w for w in re.findall(r"[a-z0-9]+", plano) if w not in _VACIAS and len(w) > 2}


def es_tema_repetido(topic: str, usados, umbral: float = 0.6) -> bool:
    """¿El tema repite uno ya publicado, aunque esté redactado distinto?

    El filtro anterior comparaba cadenas exactas, así que "para que sirve google
    search console", "google search console para que sirve" y "google search
    console tools" pasaron como temas distintos y produjeron tres artículos que
    compiten entre sí. Se compara el núcleo de palabras, no el texto literal.
    """
    nuevo = _nucleo(topic)
    if not nuevo:
        return False
    for usado in usados or []:
        viejo = _nucleo(usado)
        if not viejo:
            continue
        if len(nuevo & viejo) / min(len(nuevo), len(viejo)) >= umbral:
            return True
    return False


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
    if not topics and SITES[site_key].get("topic_ideas"):
        topics = get_idea_topics(site_key, used_topics)
    if not topics:
        topics = get_trending_topics(site_key)

    for topic in topics:
        if not es_tema_repetido(topic, used_topics):
            return topic

    # Todo lo disponible ya está cubierto. Devolver algo igual sería escribir un
    # artículo que canibaliza a uno propio, así que se avisa y se deja que el
    # pipeline lo trate como corrida sin tema.
    print(f"[Trends] ⚠️ Todos los temas de {site_key} repiten contenido ya publicado")
    raise TemasAgotados(
        f"No hay tema nuevo para '{site_key}': los {len(topics)} candidatos repiten "
        f"artículos existentes. Encola un tema manualmente o amplía keywords_seed."
    )
