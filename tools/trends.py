import random
from pytrends.request import TrendReq
from config import SITES


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
    """
    topics = get_trending_topics(site_key)
    
    for topic in topics:
        if topic not in used_topics:
            return topic
    
    # Si todos fueron usados, regresar el primero de todos modos
    return topics[0] if topics else SITES[site_key]["keywords_seed"][0]
