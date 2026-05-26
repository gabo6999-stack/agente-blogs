import json
import anthropic
from config import ANTHROPIC_API_KEY, SITES


def generate_blog(site_key: str, topic: str) -> dict:
    site = SITES[site_key]
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    print(f"[Writer] Generando blog sobre: {topic}")

    # PASO 1: Investigar
    print(f"[Writer] Investigando...")
    research_response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=3000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{
            "role": "user",
            "content": f"Investiga sobre '{topic}' en el contexto de {site['niche']}. Busca información actualizada, beneficios, estudios y datos relevantes. Haz 2-3 búsquedas y resume los puntos más importantes."
        }]
    )

    research_text = ""
    for block in research_response.content:
        if hasattr(block, "text"):
            research_text += block.text

    # PASO 2: Escribir JSON
    print(f"[Writer] Escribiendo artículo...")
    write_response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=5000,
        system="""Eres un redactor SEO experto en péptidos y suplementos deportivos.
Debes responder ÚNICAMENTE con un objeto JSON válido y completo, sin texto adicional, sin markdown, sin backticks.
El JSON debe tener exactamente estas claves:
- title: string
- slug: string (url-friendly)
- content: string (HTML con h2, h3, p, ul, strong — mínimo 1000 palabras, máximo 1200 palabras)
- excerpt: string (máximo 150 caracteres)
- rank_math_title: string (máximo 60 caracteres)
- rank_math_description: string (máximo 160 caracteres)
- rank_math_focus_keyword: string
- tags: array de 3-5 strings
- unsplash_query: string (2-3 palabras en inglés para buscar imagen)""",
        messages=[{
            "role": "user",
            "content": f"""Basándote en esta investigación:

{research_text}

Escribe un artículo de blog en español sobre "{topic}" para el sitio peptidosysuplementos.mx.
El contenido HTML debe tener entre 1000 y 1200 palabras, con introducción, 4-5 secciones con h2, y conclusión con llamada a la acción.
Responde SOLO con el JSON, sin nada más."""
        }]
    )

    full_text = ""
    for block in write_response.content:
        if hasattr(block, "text"):
            full_text += block.text

    try:
        clean = full_text.strip()
        if "```" in clean:
            import re
            match = re.search(r'\{.*\}', clean, re.DOTALL)
            if match:
                clean = match.group(0)
        blog_data = json.loads(clean)
        print(f"[Writer] Blog generado: {blog_data.get('title', 'Sin título')}")
        return blog_data
    except json.JSONDecodeError as e:
        print(f"[Writer] Error parseando JSON: {e}")
        print(f"[Writer] Respuesta cruda: {full_text[:300]}")
        raise