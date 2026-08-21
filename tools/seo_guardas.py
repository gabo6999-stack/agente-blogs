# -*- coding: utf-8 -*-
"""Guardas de Rank Math + índice de contenidos, aplicadas ANTES de publicar.

Existen por dos hallazgos medidos, no por teoría:

1. `keywordInTitle` vale **38 de los 100 puntos** de Rank Math y exige la frase
   EXACTA y contigua en el título SEO. Si falta, no hay nada más que compense.
   El escritor produce el título y la keyword como campos independientes, así
   que nada garantizaba que uno contuviera al otro. En la campaña de PYS esta
   misma guarda atrapó 13 de 30 títulos.

2. `contentHasTOC` NO necesita instalar ningún plugin: **Rank Math trae su
   propio bloque de índice** (`rank-math/toc-block`). Ponerlo valió entre +2 y
   +6 puntos por artículo en telenzia.com, sin JavaScript extra.

Todo lo que se puede reparar se repara; solo se rechaza lo que no tiene arreglo
automático (palabras vetadas por el cliente).
"""
from __future__ import annotations

import re
import unicodedata
import uuid

# Reglas de contenido del cliente (CLAUDE.md). Un generador de texto las rompe
# sin avisar, así que se verifican por código y no por buena intención.
PALABRAS_VETADAS = ["farmacia", "farmacias"]
FRASES_VETADAS = ["refrigeración adecuada", "refrigeracion adecuada"]

MAX_TITULO = 60          # más allá, Google trunca el snippet
MAX_PALABRAS_KEYWORD = 3  # con 4-5 palabras la densidad del 1% obliga a repetir
                          # la frase 11 veces en 1.100 palabras: eso es relleno


def normaliza(texto: str) -> str:
    """Minúsculas, sin acentos y sin puntuación, para comparar frases."""
    t = unicodedata.normalize("NFD", (texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]", " ", re.sub(r"\s+", " ", t)).strip()


def slug_ancla(texto: str) -> str:
    """Mismo formato de ancla que genera el bloque de Rank Math."""
    t = unicodedata.normalize("NFD", (texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^a-z0-9\s-]", "", t)
    return re.sub(r"\s+", "-", t.strip()).strip("-")


def _sin_html(texto: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", texto or "")).strip()


def prosa(texto: str) -> str:
    """Texto visible: sin <script>/<style> y **sin URLs**.

    Un slug dentro de un bloque JSON-LD (`/precio-retatrutida/`) se normaliza a
    "precio retatrutida" y hace creer que la keyword ya está en el cuerpo cuando
    no lo está. Rank Math no cae en eso; la verificación tampoco debe caer.
    """
    t = re.sub(r"<(script|style)\b.*?</\1\s*>", " ", texto or "", flags=re.S | re.I)
    t = re.sub(r"""\b(?:https?://|/)[^\s"'<>]+""", " ", t)
    return _sin_html(t)


# Palabras con las que un titulo no puede terminar: "...precios, dosis y" lee
# peor que "...precios, dosis". Venia del modulo seo_guards.py y se perdio al
# fusionar; sin esto el recorte deja titulos colgando en "de", "en" o "y".
_COLGANTES = {"y", "e", "o", "u", "de", "del", "la", "el", "los", "las", "un",
              "una", "con", "sin", "para", "por", "en", "a", "al", "que", "su",
              "sus", "lo", "se", "mas", "como", "donde"}


def recorta_titulo(titulo: str, limite: int = MAX_TITULO) -> str:
    """Recorta por palabra, nunca a media palabra ni dejando una preposicion."""
    titulo = titulo.strip()
    if len(titulo) <= limite:
        return titulo
    corte = titulo[:limite]
    if " " in corte:
        corte = corte[:corte.rindex(" ")]
    corte = corte.rstrip(" ,;:-–—|").strip()
    while " " in corte and normaliza(corte.rsplit(" ", 1)[1]) in _COLGANTES:
        corte = corte.rsplit(" ", 1)[0].rstrip(" ,;:-–—|")
    return corte.strip()


def revisa_keyword(keyword: str) -> str:
    """Normaliza espacios. **No acorta la keyword.**

    Se intentó acortarla automáticamente quitando la interrogativa inicial, y
    la prueba lo tumbó: funciona en "cómo bajar de peso rápido" -> "bajar de
    peso rápido", pero destroza "qué son los péptidos" -> "son los péptidos" y
    "cómo funciona la telemedicina" -> "funciona la telemedicina". No hay regla
    segura sin análisis gramatical, y una guarda que mutila en silencio es peor
    que no tenerla.

    La longitud se AVISA en `aplica_guardas` y se pide corta en el prompt del
    escritor, que es donde el problema tiene arreglo de verdad.
    """
    return " ".join((keyword or "").split())


def asegura_keyword_en_titulo(titulo: str, keyword: str) -> str:
    """Devuelve un título SEO que contiene la frase exacta y cabe en 60.

    Si ya la contiene, solo recorta. Si no, la antepone — pero elimina primero
    del título las palabras iniciales que la keyword ya aporta, o saldría
    "Cómo bajar de peso rápido: Bajar de peso rápido: por qué no conviene".
    """
    titulo = (titulo or "").strip()
    keyword = (keyword or "").strip()
    if not keyword:
        return recorta_titulo(titulo)
    if normaliza(keyword) in normaliza(titulo):
        return recorta_titulo(titulo)

    propias = set(normaliza(keyword).split())
    palabras = titulo.split()
    i = 0
    while i < len(palabras) and normaliza(palabras[i]) in propias:
        i += 1
    resto = " ".join(palabras[i:]).lstrip(" :,-–—·|").strip()

    encabezado = keyword[0].upper() + keyword[1:]
    if not resto:
        return recorta_titulo(encabezado)
    resto = recorta_titulo(resto, MAX_TITULO - len(encabezado) - 2)
    return recorta_titulo(f"{encabezado}: {resto}" if resto else encabezado)


def busca_vetadas(*textos: str) -> list[str]:
    """Palabras del cliente que no pueden salir publicadas. Sin reparación."""
    blob = normaliza(" ".join(t or "" for t in textos))
    hallazgos = [p for p in PALABRAS_VETADAS if re.search(rf"\b{p}\b", blob)]
    hallazgos += [f for f in FRASES_VETADAS if normaliza(f) in blob]
    return hallazgos


def inserta_indice(contenido: str) -> str:
    """Añade el bloque de índice de Rank Math y las anclas de los encabezados.

    No hace nada si ya hay un índice o si el artículo tiene menos de 3
    encabezados, donde un índice estorba más de lo que ayuda.

    ⚠️ **Solo aplica a contenido en bloques de Gutenberg**: el patrón exige
    `<!-- wp:heading -->`. Medido el 2026-08-21 sobre PYS, el escritor de ese
    sitio devuelve HTML plano (10 `<h2>` y cero comentarios de bloque), así que
    ahí esta función es un no-op silencioso y `contentHasTOC` sigue abierto.
    Funciona en telenzia, cuyo escritor sí emite bloques. Para cerrarlo en PYS
    hay que hacer que el escritor emita bloques o extender el patrón al H2 pelado
    — decisión pendiente, no se hizo aquí para no cambiar el formato del cuerpo
    de un sitio en producción de pasada.
    """
    if not contenido or "rank-math/toc-block" in contenido:
        return contenido

    patron = re.compile(r"<!--\s*wp:heading(\s+(\{.*?\}))?\s*-->\s*(<h([23])[^>]*>)(.*?)(</h\4>)", re.S)
    encabezados = list(patron.finditer(contenido))
    if len(encabezados) < 3:
        return contenido

    lista, vistos = [], set()
    salida, ultimo = [], 0
    for m in encabezados:
        attrs_txt, apertura, nivel, texto = m.group(2), m.group(3), int(m.group(4)), m.group(5)
        limpio = _sin_html(texto)
        ancla = slug_ancla(limpio) or f"seccion-{len(lista) + 1}"
        base, n = ancla, 2
        while ancla in vistos:                      # dos H2 iguales romperían el salto
            ancla, n = f"{base}-{n}", n + 1
        vistos.add(ancla)

        if 'id="' in apertura or (attrs_txt and '"anchor"' in attrs_txt):
            lista.append((limpio, nivel, ancla))
            continue

        attrs = {"anchor": ancla}
        if nivel != 2:
            attrs["level"] = nivel
        import json
        nuevo = ('<!-- wp:heading ' + json.dumps(attrs, ensure_ascii=False) + ' -->\n'
                 + apertura.replace(f"<h{nivel}", f'<h{nivel} id="{ancla}"', 1)
                 + texto + m.group(6))
        salida.append(contenido[ultimo:m.start()])
        salida.append(nuevo)
        ultimo = m.end()
        lista.append((limpio, nivel, ancla))
    salida.append(contenido[ultimo:])
    contenido = "".join(salida)

    import json
    headings = [{"key": str(uuid.uuid4()), "content": t, "level": n,
                 "link": f"#{a}", "disable": False, "isUpdated": False,
                 "isGeneratedLink": True} for t, n, a in lista]
    items = "".join(f'<li class=""><a href="#{a}">{t}</a></li>' for t, _, a in lista)
    bloque = (
        "<!-- wp:rank-math/toc-block " + json.dumps({"headings": headings}, ensure_ascii=False) + " -->\n"
        '<div class="wp-block-rank-math-toc-block" id="rank-math-toc"><nav><ul>'
        + items + "</ul></nav></div>\n<!-- /wp:rank-math/toc-block -->\n\n"
    )

    primero = patron.search(contenido)
    pos = primero.start() if primero else 0
    return contenido[:pos] + bloque + contenido[pos:]


def obtener_url_media(wp_url: str, headers: dict, media_id: int) -> str | None:
    """URL publica de un adjunto, para poder incrustarlo en el cuerpo."""
    import requests
    try:
        r = requests.get(f"{wp_url}/wp-json/wp/v2/media/{media_id}",
                         headers=headers, params={"_fields": "source_url"}, timeout=20)
        if r.status_code == 200:
            return (r.json() or {}).get("source_url")
    except Exception as e:
        print(f"[SEO-guarda] no se pudo leer la URL del media {media_id}: {e}")
    return None


def incrusta_imagen(contenido: str, url_imagen: str, keyword: str,
                    titulo: str = "") -> tuple[str, bool]:
    """Mete la imagen DESPUÉS del primer H2, con la keyword en el alt.

    La imagen destacada **no cuenta** para `contentHasAssets` ni para
    `keywordInImageAlt`: Rank Math solo mira el contenido. Va después del primer
    H2 a propósito, para no romper la decisión de que el artículo no abra con la
    foto de Unsplash y su crédito.

    Medido en los 8 últimos posts de PYS antes de existir esta guarda:
    keywordInImageAlt fallaba en 4 y contentHasAssets en 3.
    """
    if not url_imagen or not contenido:
        return contenido, False
    if re.search(r"<img\b", contenido, re.I):        # ya trae imagen propia
        return contenido, False

    alt = f"{keyword} — {recorta_titulo(titulo, 70)}" if titulo else keyword
    if normaliza(keyword) not in normaliza(alt):
        alt = keyword
    fig = ('<figure class="wp-block-image size-large">'
           f'<img src="{url_imagen}" alt="{alt}" loading="lazy" />'
           "</figure>")
    # Si el artículo viene en bloques de Gutenberg, la figura tiene que ir
    # envuelta en su comentario o el editor la marca como bloque inválido.
    # El escritor de PYS produce HTML plano y el de telenzia bloques: hay que
    # detectarlo, no asumirlo.
    if "<!-- wp:" in contenido:
        fig = "<!-- wp:image -->" + fig + "<!-- /wp:image -->"
    fig = "\n" + fig + "\n"

    for patron in (r"</h2\s*>", r"</p\s*>"):
        m = re.search(patron, contenido, re.I)
        if m:
            return contenido[:m.end()] + fig + contenido[m.end():], True
    return contenido + fig, True


def audita_onpage(blog_data: dict) -> dict:
    """Mide los tests on-page sobre el contenido final. No modifica nada.

    Existe porque el puntaje de Rank Math NO se puede usar para esto: solo lo
    escribe el editor de Gutenberg al guardar, así que en un post creado por
    REST viene vacío y cualquier compuerta del tipo `score >= 81` rechazaría el
    100% de los artículos.
    """
    keyword = (blog_data.get("rank_math_focus_keyword") or "").split(",")[0].strip()
    contenido = blog_data.get("content") or ""
    titulo_seo = blog_data.get("rank_math_title") or blog_data.get("title") or ""
    texto = prosa(contenido)
    inicio = texto[:max(400, int(len(texto) * 0.10))]
    encabezados = " ".join(re.findall(r"<h[23]\b[^>]*>(.*?)</h[23]\s*>",
                                      contenido, re.S | re.I))
    alts = " ".join(re.findall(r"<img\b[^>]*\balt=[\"']([^\"']*)", contenido, re.I))

    def tiene(frase, donde):
        return bool(normaliza(frase)) and normaliza(frase) in normaliza(donde)

    checks = {
        "keywordInTitle":       tiene(keyword, titulo_seo),
        "titleLength":          0 < len(titulo_seo) <= MAX_TITULO,
        "keywordInContent":     tiene(keyword, texto),
        "keywordIn10Percent":   tiene(keyword, inicio),
        "keywordInSubheadings": tiene(keyword, encabezados),
        "contentHasAssets":     bool(re.search(r"<img\b", contenido, re.I)),
        "keywordInImageAlt":    tiene(keyword, alts),
        "keywordInMetaDesc":    tiene(keyword, blog_data.get("rank_math_description", "")),
    }
    fallos = [k for k, v in checks.items() if not v]
    return {"keyword": keyword, "checks": checks, "fallos": fallos,
            "criticos": [f for f in fallos if f in ("keywordInTitle", "titleLength")]}


def aplica_guardas(blog_data: dict, url_imagen: str = "") -> tuple[bool, list[str]]:
    """Repara `blog_data` en sitio. Devuelve (publicable, notas).

    Publicable es False solo cuando hay palabras vetadas: eso no se repara solo
    y publicarlo sería peor que no publicar.
    """
    notas: list[str] = []

    keyword_original = (blog_data.get("rank_math_focus_keyword") or "").strip()
    keyword = revisa_keyword(keyword_original)
    if keyword and keyword != keyword_original:
        notas.append(f"keyword acortada al termino cabeza: {keyword_original!r} -> {keyword!r}")
    if keyword:
        blog_data["rank_math_focus_keyword"] = keyword
    if keyword and len(keyword.split()) > MAX_PALABRAS_KEYWORD:
        notas.append(f"keyword de {len(keyword.split())} palabras: keywordDensity dificilmente llegara al 1%")

    titulo_original = (blog_data.get("rank_math_title") or blog_data.get("title") or "").strip()
    titulo = asegura_keyword_en_titulo(titulo_original, keyword)
    if titulo != titulo_original:
        if normaliza(keyword) not in normaliza(titulo_original):
            notas.append(f"el título no contenía la keyword (38 pts) — reparado: {titulo!r}")
        else:
            notas.append(f"título recortado a {len(titulo)} caracteres")
    blog_data["rank_math_title"] = titulo

    desc = (blog_data.get("rank_math_description") or "").strip()
    if keyword and desc and normaliza(keyword) not in normaliza(desc):
        notas.append("la description no contiene la keyword (keywordInMetaDescription se pierde)")

    contenido = blog_data.get("content") or ""
    con_indice = inserta_indice(contenido)
    if con_indice != contenido:
        blog_data["content"] = con_indice
        notas.append("índice de contenidos insertado (cierra contentHasTOC)")

    if url_imagen:
        con_imagen, puesta = incrusta_imagen(blog_data.get("content") or "",
                                             url_imagen, keyword,
                                             blog_data.get("title", ""))
        if puesta:
            blog_data["content"] = con_imagen
            notas.append("imagen incrustada en el cuerpo con la keyword en el alt "
                         "(cierra contentHasAssets y keywordInImageAlt)")

    vetadas = busca_vetadas(titulo, desc, blog_data.get("content", ""), blog_data.get("title", ""))
    if vetadas:
        notas.append(f"PALABRAS VETADAS: {', '.join(vetadas)}")
        return False, notas

    return True, notas
