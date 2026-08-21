"""Compuertas SEO on-page: se verifican sobre el contenido ANTES de publicarlo.

Por qué no se usa el puntaje de Rank Math
-----------------------------------------
`rank_math_seo_score` **solo lo calcula el editor de Gutenberg al guardar**. Un
post creado por la API REST no tiene puntaje por bueno que sea su contenido:
leer esa meta devuelve None o 0. Cualquier compuerta del tipo `score >= 81`
rechaza entonces el 100% de los artículos y convierte cada publicación exitosa
en una falsa alarma.

Lo que se hace aquí es medir los mismos hechos que mide Rank Math, sobre el
HTML que estamos a punto de enviar:

  · keywordInTitle      — vale 38 de 100 y arrastra otros seis tests.
                          Es la única que se repara automáticamente porque el
                          título SEO es un campo de metadatos, no prosa.
  · keywordInContent    — la frase aparece en el cuerpo.
  · keywordIn10Percent  — aparece en el primer 10% del texto.
  · keywordInSubheadings— aparece en algún H2/H3.
  · contentHasAssets    — hay una imagen DENTRO del contenido (la destacada
                          no cuenta para Rank Math).
  · keywordInImageAlt   — esa imagen lleva la frase en el alt.

Las que dependen de la redacción se reportan, no se parchean: meter la keyword
a la fuerza dentro de un H2 escrito por el redactor produce títulos peores que
el punto que gana. Para esas, la corrección va en el prompt del escritor.
"""

import re
import unicodedata

import requests

MAX_TITLE = 60          # a partir de ahí Google corta el snippet
PRIMER_10_PCT = 0.10


# ─── normalización ───────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    """Minúsculas, sin acentos y sin puntuación — como compara Rank Math."""
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^\w\s]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def _prosa(html: str) -> str:
    """Texto visible: sin <script>/<style> y sin URLs.

    Un slug dentro de un bloque JSON-LD (`/precio-retatrutida/`) se normaliza a
    "precio retatrutida" y hace creer que la keyword ya está en el cuerpo cuando
    no lo está. Rank Math no cae en eso; la verificación tampoco debe caer.
    """
    html = re.sub(r"<(script|style)\b.*?</\1\s*>", " ", html or "", flags=re.S | re.I)
    html = re.sub(r"""\b(?:https?://|/)[^\s"'<>]+""", " ", html)
    return re.sub(r"<[^>]+>", " ", html)


def keyword_principal(blog_data: dict) -> str:
    """Rank Math acepta varias keywords separadas por coma; manda la primera."""
    kw = (blog_data.get("rank_math_focus_keyword") or "").split(",")[0].strip()
    return kw or (blog_data.get("title") or "").strip()


def contiene_frase(frase: str, texto: str) -> bool:
    """La frase EXACTA y contigua, como la exige Rank Math."""
    f = _norm(frase)
    return bool(f) and f in _norm(texto)


# ─── reparación 1: la keyword en el título SEO (38 pts) ──────────────────────

def asegurar_keyword_en_titulo(blog_data: dict) -> dict:
    """Garantiza que la frase exacta esté en `rank_math_title`, ≤60 caracteres.

    Devuelve {"ok", "reparado", "titulo", "motivo"}. Solo toca el título SEO:
    el H1 del artículo se queda como lo escribió el redactor.
    """
    kw = keyword_principal(blog_data)
    titulo = (blog_data.get("rank_math_title") or blog_data.get("title") or "").strip()

    if contiene_frase(kw, titulo) and len(titulo) <= MAX_TITLE:
        return {"ok": True, "reparado": False, "titulo": titulo, "motivo": ""}

    if not kw:
        return {"ok": False, "reparado": False, "titulo": titulo,
                "motivo": "el artículo no trae focus keyword"}

    if len(kw) > MAX_TITLE:
        return {"ok": False, "reparado": False, "titulo": titulo,
                "motivo": f"la keyword sola ({len(kw)}c) no cabe en {MAX_TITLE}"}

    if contiene_frase(kw, titulo):
        nuevo = _recortar(titulo, MAX_TITLE)         # ya la tenía, solo sobra largo
        if not contiene_frase(kw, nuevo):            # el recorte se la comió
            nuevo = _componer(kw, titulo)
    else:
        nuevo = _componer(kw, titulo)

    if not contiene_frase(kw, nuevo):
        return {"ok": False, "reparado": False, "titulo": titulo,
                "motivo": "no se pudo construir un título con la frase exacta"}

    blog_data["rank_math_title"] = nuevo
    return {"ok": True, "reparado": True, "titulo": nuevo,
            "motivo": f"«{titulo}» → «{nuevo}»"}


def _componer(kw: str, titulo: str) -> str:
    """«keyword: resto del título», recortado por palabra."""
    resto = titulo
    # si el título ya empieza por algo parecido a la keyword, no lo repitas
    if _norm(resto).startswith(_norm(kw)[:12]):
        resto = resto[len(kw):].lstrip(" :–—-")
    espacio = MAX_TITLE - len(kw) - 2                # ": "
    if espacio < 8 or not resto:
        return _recortar(kw, MAX_TITLE)
    return f"{kw}: {_recortar(resto, espacio)}"


# conectores que no deben quedar colgando al final de un título recortado
_COLGANTES = {"y", "e", "o", "u", "de", "del", "la", "el", "los", "las", "un",
              "una", "con", "sin", "para", "por", "en", "a", "al", "que", "su",
              "sus", "lo", "se", "más", "mas", "como", "donde", "dónde"}


def _recortar(texto: str, limite: int) -> str:
    texto = texto.strip()
    if len(texto) <= limite:
        return texto
    corte = texto[:limite]
    if " " in corte:
        corte = corte[:corte.rindex(" ")]
    corte = corte.rstrip(" ,;:–—-")
    # "…precios, dosis y" lee peor que "…precios, dosis"
    while " " in corte and _norm(corte.rsplit(" ", 1)[1]) in _COLGANTES:
        corte = corte.rsplit(" ", 1)[0].rstrip(" ,;:–—-")
    return corte


# ─── reparación 2: imagen dentro del cuerpo con la keyword en el alt ─────────

def obtener_url_media(wp_url: str, headers: dict, media_id: int) -> str | None:
    try:
        r = requests.get(f"{wp_url}/wp-json/wp/v2/media/{media_id}",
                         headers=headers, params={"_fields": "source_url"}, timeout=20)
        if r.status_code == 200:
            return (r.json() or {}).get("source_url")
    except Exception as e:
        print(f"[Guards] No se pudo leer la URL del media {media_id}: {e}")
    return None


def incrustar_imagen(content: str, url_imagen: str, kw: str, titulo: str = "") -> tuple[str, bool]:
    """Mete la imagen DESPUÉS del primer H2, con la keyword en el alt.

    Va después del primer H2 a propósito: la decisión de diseño era que no
    apareciera una foto grande justo antes del texto. Ahí adentro cierra
    `contentHasAssets` y `keywordInImageAlt` sin romper esa decisión.
    """
    if not url_imagen or not content:
        return content, False
    if re.search(r"<img\b", content, re.I):          # ya tiene imagen propia
        return content, False

    alt = kw if not titulo else f"{kw} — {_recortar(titulo, 70)}"
    if not contiene_frase(kw, alt):                  # cinturón y tirantes
        alt = kw
    fig = (f'\n<figure class="wp-block-image size-large">'
           f'<img src="{url_imagen}" alt="{alt}" loading="lazy" />'
           f"</figure>\n")

    m = re.search(r"</h2\s*>", content, re.I)
    if m:
        return content[:m.end()] + fig + content[m.end():], True

    m = re.search(r"</p\s*>", content, re.I)         # sin H2: tras el primer párrafo
    if m:
        return content[:m.end()] + fig + content[m.end():], True
    return content + fig, True


# ─── auditoría: los tests que dependen de la redacción ───────────────────────

def auditar_onpage(blog_data: dict) -> dict:
    """Mide los tests on-page sobre el contenido final. No modifica nada."""
    kw = keyword_principal(blog_data)
    content = blog_data.get("content", "") or ""
    titulo_seo = blog_data.get("rank_math_title") or blog_data.get("title") or ""
    prosa = _prosa(content)
    inicio = prosa[:max(400, int(len(prosa) * PRIMER_10_PCT))]
    encabezados = " ".join(re.findall(r"<h[23]\b[^>]*>(.*?)</h[23]\s*>",
                                      content, re.S | re.I))
    alts = " ".join(re.findall(r"<img\b[^>]*\balt=[\"']([^\"']*)", content, re.I))

    checks = {
        "keywordInTitle":       contiene_frase(kw, titulo_seo),
        "titleLength":          0 < len(titulo_seo) <= MAX_TITLE,
        "keywordInContent":     contiene_frase(kw, prosa),
        "keywordIn10Percent":   contiene_frase(kw, inicio),
        "keywordInSubheadings": contiene_frase(kw, encabezados),
        "contentHasAssets":     bool(re.search(r"<img\b", content, re.I)),
        "keywordInImageAlt":    contiene_frase(kw, alts),
        "keywordInMetaDesc":    contiene_frase(kw, blog_data.get("rank_math_description", "")),
    }
    fallos = [k for k, v in checks.items() if not v]
    return {"keyword": kw, "checks": checks, "fallos": fallos,
            "criticos": [f for f in fallos if f in ("keywordInTitle", "titleLength")]}
