import json
import anthropic
import requests
from datetime import datetime
from json_repair import repair_json
from config import ANTHROPIC_API_KEY, SITES
from prompts.system import (get_system_prompt, get_arcade_system_prompt, get_arcade_review_system_prompt,
                            get_agency_system_prompt, get_waldorf_system_prompt, bloque_enlaces_waldorf,
                            get_informativo_system_prompt)
from tools.arcade import list_guides as arcade_list_guides


def fetch_product_map(site_key: str) -> str:
    """Mapa {compuesto -> URL de ficha} desde el agente SEO, ANTES de generar.

    Devuelve "" si el sitio no lo tiene configurado o si el agente no responde:
    en ese caso el prompt no exige enlaces internos, porque exigirlos sin darle
    las URLs reales es pedirle al modelo que las invente.
    """
    site = SITES[site_key]
    base = site.get("seo_agent_url")
    ruta = site.get("product_map_path")
    if not base or not ruta:
        return ""
    try:
        r = requests.get(f"{base}{ruta}", timeout=45)
        fichas = (r.json() or {}).get("fichas") or []
        if not fichas:
            print("[Writer] /product-map devolvió 0 fichas — sigo sin mapa")
            return ""
        print(f"[Writer] Mapa de fichas cargado: {len(fichas)} fichas enlazables")
        lineas = [f"- {f['nombre']} -> {f['url']}" for f in fichas if f.get("url")]
        return "\n".join(lineas)
    except Exception as e:
        print(f"[Writer] No se pudo cargar el mapa de fichas ({e}) — sigo sin mapa")
        return ""


def _parse_json(text: str) -> dict:
    """Extrae y parsea JSON de la respuesta de Claude, con reparación automática."""
    clean = text.strip()
    if "```" in clean:
        parts = clean.split("```")
        for part in parts[1::2]:
            candidate = part.lstrip("json").strip()
            if candidate.startswith("{"):
                clean = candidate
                break
    clean = clean.strip()

    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        repaired = repair_json(clean, return_objects=True)
        if isinstance(repaired, dict):
            return repaired
        raise ValueError(f"No se pudo parsear el JSON: {clean[:200]}")


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
- NUNCA incluyas etiquetas <img> en el content — las imágenes se manejan por separado

FORMATO DE RESPUESTA:
Responde ÚNICAMENTE con un JSON válido con esta estructura exacta:
{{
  "title": "Título del artículo",
  "slug": "titulo-del-articulo-en-slug",
  "content": "Contenido HTML completo del artículo",
  "excerpt": "Resumen de 150 caracteres máximo",
  "rank_math_title": "Meta title SEO (60 caracteres máximo)",
  "rank_math_description": "Meta description SEO (160 caracteres máximo)",
  "rank_math_focus_keyword": "keyword principal: 2 o 3 palabras, sin interrogativas ('bajar de peso', no 'como bajar de peso rapido'). DEBE aparecer literal y contigua dentro de rank_math_title, o Rank Math pierde 38 de sus 100 puntos",
  "tags": ["tag1", "tag2", "tag3"],
  "unsplash_query": "2-3 palabras en inglés para buscar imagen en Unsplash"
}}

REGLAS DEL JSON:
- El campo "content" es HTML — escapa TODAS las comillas internas como \\\"
- No incluyas el H1 dentro del content, solo el cuerpo del artículo
- No agregues texto fuera del JSON"""

    tags_str = ", ".join(current_post.get("tags", [])) or "(ninguno)"
    user_message = f"""Corrige y mejora el siguiente artículo según esta instrucción:

INSTRUCCIÓN DEL EDITOR: {instruction}

ARTÍCULO ACTUAL:
Título: {current_post.get('title', '')}
Excerpt: {current_post.get('excerpt', '')}
Meta title: {current_post.get('rank_math_title', '')}
Meta description: {current_post.get('rank_math_description', '')}
Focus keyword: {current_post.get('rank_math_focus_keyword', '')}
Tags: {tags_str}

CONTENIDO ACTUAL:
{current_post.get('content', '')}

Responde únicamente con el JSON corregido."""

    print(f"[Writer] Editando post con instrucción: {instruction}")

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=8000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}]
    )

    full_text = "".join(block.text for block in response.content if hasattr(block, "text"))

    try:
        blog_data = _parse_json(full_text)
        print(f"[Writer] Blog editado: {blog_data.get('title', 'Sin título')}")
        return blog_data
    except Exception as e:
        print(f"[Writer] Error parseando JSON: {e}")
        print(f"[Writer] Respuesta cruda: {full_text[:500]}")
        raise


def _review_blog_arcade(client, site: dict, blog_data: dict, existing_guides, year: int) -> dict:
    """Segunda pasada (editor SEO): pule el borrador de Arcade antes de publicar.
    Si el review falla o devuelve algo incompleto, conserva el borrador original."""
    try:
        review_system = get_arcade_review_system_prompt(
            site["niche"], site["post_length"], existing_guides, year
        )
        user = "BORRADOR A PULIR (JSON):\n\n" + json.dumps(blog_data, ensure_ascii=False)
        print("[Writer] Puliendo con editor SEO (review)...")
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=16000,
            system=review_system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in resp.content if hasattr(b, "text"))
        polished = _parse_json(text)
        if polished.get("content") and polished.get("title"):
            polished.setdefault("slug", blog_data.get("slug", ""))
            print(f"[Writer] ✅ Guía pulida: {polished.get('title')}")
            return polished
        print("[Writer] Review incompleto; se conserva el borrador.")
    except Exception as e:
        print(f"[Writer] Review falló ({e}); se conserva el borrador.")
    return blog_data


def contar_palabras(html: str) -> int:
    """Cuenta palabras reales del cuerpo (sin contar etiquetas HTML)."""
    import re
    text = re.sub(r"<[^>]+>", " ", html or "")
    return len(re.findall(r"\w+", text))


def piso_de_palabras(site: dict) -> int:
    """Mínimo de palabras publicable para el sitio."""
    return max(1100, site.get("post_length", 1400) - 200)


_EXPANSION_POR_ESTILO = {
    "agency": ("de una agencia digital",
               "comparativas, checklists y datos útiles para un dueño de PyME",
               "el CTA a la agencia y la sección de FAQ. No inventes URLs ni uses fuentes médicas/científicas."),
    "informativo": ("de divulgación científica",
                    "mecanismos, datos de estudios con su fuente enlazada y limitaciones de la evidencia",
                    "la frase de cierre y la sección de FAQ. No inventes URLs. PROHIBIDO añadir "
                    "cualquier lenguaje de venta (precio, compra, envío, tienda, pedido, etc.)."),
    "waldorf": ("de un jardín de infancia Waldorf",
                "escenas cotidianas y sugerencias prácticas que una familia pueda aplicar en casa",
                "la invitación final a conocer la escuela y la sección de FAQ. No inventes URLs ni datos de la escuela."),
}


def _expand_if_thin_agency(client, site: dict, blog_data: dict, intentos: int = 2) -> dict:
    """Guard de longitud para posts de agencia (content_style='agency').

    Reintenta la expansión hasta `intentos` veces y se queda con el borrador más
    largo que consiga. Antes hacía una sola pasada y, si no alcanzaba, devolvía el
    original sin avisar: así se publicaron entradas de 700-900 palabras. Quien
    llama debe revisar la longitud final (ver `piso_de_palabras`) y decidir.
    """
    target = site.get("post_length", 1400)
    floor = piso_de_palabras(site)
    mejor = blog_data
    palabras = contar_palabras(blog_data.get("content", ""))

    for intento in range(1, intentos + 1):
        if palabras >= floor:
            return mejor
        print(f"[Writer] Borrador flaco ({palabras} palabras < {floor}); "
              f"expandiendo (intento {intento}/{intentos})...")
        try:
            quien, como, conserva = _EXPANSION_POR_ESTILO.get(
                site.get("content_style"), _EXPANSION_POR_ESTILO["agency"])
            prompt = (
                f"El siguiente artículo de blog {quien} está demasiado corto "
                f"({palabras} palabras). Amplíalo a MÍNIMO {target} palabras REALES de cuerpo, "
                f"profundizando CADA sección con ejemplos concretos, {como}. "
                f"NO cambies el título ni el slug. CONSERVA y refuerza los enlaces existentes "
                f"(internos y externos), {conserva} Responde "
                f"ÚNICAMENTE con el MISMO JSON (misma estructura de campos) ya expandido.\n\n"
                f"JSON ACTUAL:\n" + json.dumps(mejor, ensure_ascii=False)
            )
            resp = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=16000,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(b.text for b in resp.content if hasattr(b, "text"))
            expanded = _parse_json(text)
            nuevas = contar_palabras(expanded.get("content", ""))
            if expanded.get("content") and nuevas > palabras:
                expanded.setdefault("slug", mejor.get("slug", ""))
                mejor, palabras = expanded, nuevas
                print(f"[Writer] ✅ Expandido a {palabras} palabras")
            else:
                print("[Writer] La expansión no aumentó el texto.")
        except Exception as e:
            print(f"[Writer] Expansión falló ({e}).")

    if palabras < floor:
        print(f"[Writer] ⚠️ El artículo sigue flaco: {palabras} palabras (piso {floor})")
    return mejor


def _corrige_frases(client, blog_data: dict, revisar, instruccion: str, etiqueta: str,
                    intentos: int = 2, antes=None) -> dict:
    """Reescribe SOLO las frases que una compuerta señala, hasta `intentos` veces.

    `revisar(blog_data) -> [hallazgos]`. `antes(blog_data)` repara lo que se
    puede reparar sin el modelo (p. ej. desenvolver enlaces) en cada vuelta.
    En vez de tirar un artículo entero (~$0.30) por una frase, se le devuelve
    al modelo la lista exacta. Si tras los intentos sigue habiendo hallazgos se
    devuelve tal cual: la compuerta del pipeline/publish_post lo rechazará.
    """
    NL = chr(10)
    for intento in range(1, intentos + 1):
        if antes:
            antes(blog_data)
        hallazgos = revisar(blog_data)
        if not hallazgos:
            return blog_data
        print(f"[Writer] {len(hallazgos)} hallazgo(s) de {etiqueta}; reescribiendo esas frases "
              f"(intento {intento}/{intentos})...")
        prompt = (
            instruccion + NL + "Hallazgos:" + NL + "- " + (NL + "- ").join(hallazgos[:40]) + NL + NL
            + "Reescribe SOLO esas frases (o elimínalas si no aportan), sin tocar el resto del "
            + "artículo. Responde ÚNICAMENTE con el MISMO JSON (mismos campos) corregido." + NL + NL
            + "JSON ACTUAL:" + NL + json.dumps(blog_data, ensure_ascii=False)
        )
        try:
            resp = client.messages.create(model="claude-sonnet-4-6", max_tokens=16000,
                                          messages=[{"role": "user", "content": prompt}])
            texto = "".join(b.text for b in resp.content if hasattr(b, "text"))
            corregido = _parse_json(texto)
            if corregido.get("content"):
                corregido.setdefault("slug", blog_data.get("slug", ""))
                blog_data = corregido
        except Exception as e:
            print(f"[Writer] La corrección de {etiqueta} falló ({e}).")
    if antes:
        antes(blog_data)
    restantes = revisar(blog_data)
    if restantes:
        print(f"[Writer] ⚠️ Siguen {len(restantes)} hallazgo(s) de {etiqueta}: no se publicará")
    return blog_data


def _limpia_lenguaje_de_venta(client, site: dict, blog_data: dict, intentos: int = 2) -> dict:
    """Sitios con sales_gate: fuera el lenguaje de venta y los enlaces a la tienda."""
    from tools.revisor_ventas import revisa_articulo, quita_enlaces_a_hosts
    hosts = site.get("forbidden_hosts", [])

    def antes(bd):
        bd["content"], _ = quita_enlaces_a_hosts(bd.get("content", ""), hosts)

    return _corrige_frases(
        client, blog_data, lambda bd: revisa_articulo(bd, hosts),
        "Este artículo es para un sitio INFORMATIVO que no vende nada. Tiene frases con lenguaje "
        "de venta o menciones prohibidas. Reescríbelas de forma neutral y científica sin usar "
        "NINGUNA de estas palabras: precio, costo, comprar, vender, venta, adquirir, pedido, envío, "
        "pago, tienda, catálogo, existencias, stock, oferta, descuento, promoción, cupón, cliente, "
        "proveedor (di 'profesional de la salud'), distribuidor, factura, lote, COA, certificado de "
        "análisis, farmacia, dopaje, WADA. Nunca menciones otra web ni tienda.",
        "lenguaje de venta", intentos, antes=antes)


def _quita_pautas_de_dosis(client, site: dict, blog_data: dict, intentos: int = 2) -> dict:
    """Sitios con dose_gate: ninguna pauta de uso para personas (ver compuerta_dosis)."""
    from tools.compuerta_dosis import revisa_dosis
    modo = site.get("dose_gate")
    if modo == "citado":
        regla = ("Solo puedes conservar una cifra si la MISMA oración la atribuye a un estudio "
                 "concreto con su enlace a la fuente, en pasado y como dato del estudio (\"en el "
                 "ensayo X, los participantes recibieron...\"). Si no, quita la cifra. Nada de tablas "
                 "de dosis.")
    else:
        regla = ("En este sitio no puede aparecer NINGUNA cifra de dosis, ni siquiera atribuida a "
                 "un estudio: describe lo que se investigó de forma cualitativa. Nada de tablas de dosis.")
    return _corrige_frases(
        client, blog_data, lambda bd: revisa_dosis(bd, modo),
        "Este artículo contiene pautas de uso para personas (cantidades en mg/mcg/UI/mL junto a "
        "vía, frecuencia, horario, ciclos o protocolos, o instrucciones de cómo aplicarse algo). "
        "Un artículo de blog NO da indicaciones de uso. " + regla + " Recuerda que cualquier "
        "decisión de salud se toma con un médico.",
        "pautas de dosis", intentos)


def _recorta_enlaces_internos(html: str, dominio: str, tope: int, conservar=()) -> str:
    """Deja solo los primeros `tope` enlaces internos; el resto conserva su texto.

    En la prueba de Tlaollin el modelo metió 14 enlaces internos aunque el prompt
    pedía 3-5: con tantos, ninguno pesa y el artículo parece un índice. El CTA a
    WhatsApp no cuenta (es externo), y las URLs de `conservar` (el CTA del cierre)
    nunca se quitan ni cuentan.
    """
    import re
    from urllib.parse import urlparse
    host = urlparse(dominio).netloc.replace("www.", "")
    if not host:
        return html
    vistos = 0

    def cambia(m):
        nonlocal vistos
        if host not in m.group(1) or m.group(1) in conservar:
            return m.group(0)
        vistos += 1
        return m.group(0) if vistos <= tope else m.group(2)

    return re.sub(r'<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>', cambia, html, flags=re.S | re.I)


def generate_blog(site_key: str, topic: str) -> dict:
    """
    Usa Claude para investigar y escribir el blog completo.
    Para Arcade: inyecta las guías existentes (cross-links + no-repetir) y hace un
    segundo paso de review (editor SEO) antes de devolver.
    Retorna diccionario con título, contenido, SEO metadata, etc.
    """
    site = SITES[site_key]
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    is_arcade = site.get("platform") == "arcade"
    year = datetime.now().year
    existing_guides = arcade_list_guides(site_key) if is_arcade else None

    if is_arcade:
        system_prompt = get_arcade_system_prompt(site["niche"], site["post_length"], existing_guides, year)
        titulos = "; ".join(g.get("titulo", "") for g in (existing_guides or [])) or "(ninguna aún)"
        user_message = f"""Escribe una guía completa y optimizada para SEO sobre: "{topic}"

AÑO ACTUAL: {year} (inclúyelo en el título).
GUÍAS QUE YA EXISTEN (NO las repitas; enlaza a las relevantes): {titulos}

Si "{topic}" ya está cubierto, escribe sobre un ángulo NUEVO y distinto relacionado con \
{site['niche']}. Incluye cross-links a las guías existentes y CTA internos (publicar/buscar).
Responde únicamente con el JSON solicitado."""
    elif site.get("content_style") == "agency":
        system_prompt = get_agency_system_prompt(site["niche"], site["post_length"], year)
        user_message = f"""Escribe un artículo de blog completo y optimizado para SEO sobre: "{topic}"

AÑO ACTUAL: {year}. Si incluyes un año por frescura/SEO (título o texto), usa {year}, nunca uno pasado. Solo conserva años reales al citar datos, informes o versiones concretas.
Enfócalo en el dueño de un negocio/PyME (no en un técnico): explica el "por qué le conviene".
Investiga para incluir datos actualizados y ejemplos reales, con fuentes de autoridad web/marketing.
El artículo debe ser útil para personas interesadas en {site['niche']}. Cierra con un CTA claro a la agencia.
Responde únicamente con el JSON solicitado."""
    elif site.get("content_style") == "waldorf":
        from tools.wordpress import get_posts_list
        enlaces = bloque_enlaces_waldorf(site.get("paginas_clave"), get_posts_list(site_key))
        system_prompt = get_waldorf_system_prompt(
            site["niche"], site["post_length"], year, enlaces_block=enlaces,
            categorias=site.get("allowed_categories"), whatsapp=site.get("whatsapp", ""))
        user_message = f"""Escribe un artículo de blog completo y optimizado para SEO sobre: "{topic}"

AÑO ACTUAL: {year}. Si incluyes un año por frescura, usa {year}, nunca uno pasado.
Escríbelo para una familia de Cholula o Puebla con hijos pequeños. Que el artículo aporte algo que \
los posts ya publicados de la lista de enlaces no cubran, y enlaza los que se relacionen.
Responde únicamente con el JSON solicitado."""
    elif site.get("content_style") == "informativo":
        from tools.wordpress import get_posts_list, get_titulos_sitio
        enlaces = bloque_enlaces_waldorf(site.get("paginas_clave"), get_posts_list(site_key))
        evitar = []
        for otro in site.get("exclude_topics_from_sites", []):
            evitar += get_titulos_sitio(otro)
        system_prompt = get_informativo_system_prompt(
            site["niche"], site["post_length"], year, enlaces_block=enlaces,
            whatsapp=site.get("whatsapp", ""), whatsapp_en_cuerpo=site.get("whatsapp_en_cuerpo", False),
            evitar=evitar)
        user_message = f"""Escribe un artículo de divulgación científica completo y optimizado para SEO sobre: "{topic}"

AÑO ACTUAL: {year}. Si incluyes un año por frescura, usa {year}, nunca uno pasado.
Que explique cómo funciona y qué dice la evidencia, citando estudios reales. Recuerda: es un sitio
informativo, sin una sola palabra de venta y sin mencionar ninguna tienda.
Responde únicamente con el JSON solicitado."""
    else:
        fichas_block = fetch_product_map(site_key)
        system_prompt = get_system_prompt(site["niche"], site["post_length"], year,
                                          fichas_block=fichas_block,
                                          sin_pautas=bool(site.get("dose_gate")))
        user_message = f"""Escribe un artículo de blog completo y optimizado para SEO sobre: "{topic}"

AÑO ACTUAL: {year}. Si incluyes un año por frescura/SEO (título o texto), usa {year}, nunca uno pasado. Solo conserva años reales al citar estudios, ensayos o eventos concretos.
Investiga para incluir información actualizada, estudios recientes y datos precisos.
El artículo debe ser útil para personas interesadas en {site['niche']}.
Responde únicamente con el JSON solicitado."""

    print(f"[Writer] Generando blog sobre: {topic}")

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=16000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}]
    )

    full_text = "".join(block.text for block in response.content if hasattr(block, "text"))

    try:
        blog_data = _parse_json(full_text)
        print(f"[Writer] Blog generado: {blog_data.get('title', 'Sin título')}")
    except Exception as e:
        print(f"[Writer] Error parseando JSON: {e}")
        print(f"[Writer] Respuesta cruda: {full_text[:500]}")
        raise

    if is_arcade:
        blog_data = _review_blog_arcade(client, site, blog_data, existing_guides, year)
    elif site.get("content_style") in ("agency", "waldorf", "informativo"):
        blog_data = _expand_if_thin_agency(client, site, blog_data)

    if site.get("sales_gate"):
        blog_data = _limpia_lenguaje_de_venta(client, site, blog_data)
    if site.get("dose_gate"):
        blog_data = _quita_pautas_de_dosis(client, site, blog_data)

    tope = site.get("max_internal_links")
    if tope:
        blog_data["content"] = _recorta_enlaces_internos(
            blog_data.get("content", ""), site.get("wp_url") or "", tope,
            conservar=site.get("cta_links", ()))

    # Solo categorías que ya existen en el sitio: un nombre con otra grafía
    # crearía una categoría nueva y vacía.
    permitidas = site.get("allowed_categories")
    if permitidas:
        elegidas = [c for c in (blog_data.get("categories") or []) if c in permitidas]
        blog_data["categories"] = elegidas[:1] or list(site.get("default_categories", []))

    return blog_data
