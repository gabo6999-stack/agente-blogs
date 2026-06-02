import json
import anthropic
from config import ANTHROPIC_API_KEY, SITES
from prompts.system import get_system_prompt


def edit_blog(site_key: str, current_post: dict, instruction: str) -> dict:
    """
    Usa Claude para corregir/editar un blog existente según una instrucción.
    Retorna el mismo diccionario de blog_data con los cambios aplicados.
    """
    site = SITES[site_key]
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    system_prompt = f"""Eres un experto editor de contenido SEO especializado en {site['niche']}.
Tu tarea es corregir y mejorar un artículo de blog existente según las instrucciones del editor.

INSTRUCCIONES:
- Idioma: español (México)
- Tono: profesional pero accesible, científico pero entendible
- Aplica SOLO los cambios indicados por el editor
- Mantén la estructura HTML existente a menos que se indique lo contrario
- Conserva toda la información correcta del artículo original

FORMATO DE RESPUESTA:
Responde ÚNICAMENTE con un JSON válido con esta estructura exacta:
{{
  "title": "Título del artículo",
  "slug": "titulo-del-articulo-en-slug",
  "content": "Contenido HTML completo del artículo",
  "excerpt": "Resumen de 150 caracteres máximo",
  "rank_math_title": "Meta title SEO (60 caracteres máximo)",
  "rank_math_description": "Meta description SEO (160 caracteres máximo)",
  "rank_math_focus_keyword": "keyword principal",
  "tags": ["tag1", "tag2", "tag3"]
}}

IMPORTANTE: El campo "content" debe ser HTML válido con etiquetas <h2>, <h3>, <p>, <ul>, <strong>.
No incluyas el H1 dentro del content, solo el cuerpo del artículo.
No agregues texto fuera del JSON."""

    tags_str = ", ".join(current_post.get("tags", [])) or "(ninguno)"
    user_message = f"""Corrige y mejora el siguiente artículo según esta instrucción:

INSTRUCCIÓN DEL EDITOR: {instruction}

ARTÍCULO ACTUAL:
Título: {current_post.get('title', '')}
Contenido: {current_post.get('content', '')}
Excerpt: {current_post.get('excerpt', '')}
Meta title: {current_post.get('rank_math_title', '')}
Meta description: {current_post.get('rank_math_description', '')}
Focus keyword: {current_post.get('rank_math_focus_keyword', '')}
Tags: {tags_str}

Responde únicamente con el JSON corregido."""

    print(f"[Writer] Editando post con instrucción: {instruction}")

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=8000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}]
    )

    full_text = ""
    for block in response.content:
        if hasattr(block, "text"):
            full_text += block.text

    try:
        clean = full_text.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        blog_data = json.loads(clean.strip())
        print(f"[Writer] Blog editado: {blog_data.get('title', 'Sin título')}")
        return blog_data
    except json.JSONDecodeError as e:
        print(f"[Writer] Error parseando JSON: {e}")
        print(f"[Writer] Respuesta cruda: {full_text[:500]}")
        raise


def generate_blog(site_key: str, topic: str) -> dict:
    """
    Usa Claude con web_search para investigar y escribir el blog completo.
    Retorna diccionario con título, contenido, SEO metadata, etc.
    """
    site = SITES[site_key]
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    system_prompt = get_system_prompt(site["niche"], site["post_length"])

    user_message = f"""Escribe un artículo de blog completo y optimizado para SEO sobre: "{topic}"

Investiga con web_search para incluir información actualizada, estudios recientes y datos precisos.
El artículo debe ser útil para personas interesadas en {site['niche']}.
Responde únicamente con el JSON solicitado."""

    print(f"[Writer] Generando blog sobre: {topic}")

    messages = [{"role": "user", "content": user_message}]

    # Primera llamada — puede usar web_search
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=4000,
        system=system_prompt,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=messages
    )

    # Manejar tool_use loop
    while response.stop_reason == "tool_use":
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": "Search completed"
                })

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=4000,
            system=system_prompt,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=messages
        )

    # Extraer texto final
    full_text = ""
    for block in response.content:
        if hasattr(block, "text"):
            full_text += block.text

    # Parsear JSON
    try:
        clean = full_text.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        blog_data = json.loads(clean.strip())
        print(f"[Writer] Blog generado: {blog_data.get('title', 'Sin título')}")
        return blog_data
    except json.JSONDecodeError as e:
        print(f"[Writer] Error parseando JSON: {e}")
        print(f"[Writer] Respuesta cruda: {full_text[:500]}")
        raise
