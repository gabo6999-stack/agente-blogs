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


def recorta_titulo(titulo: str, limite: int = MAX_TITULO) -> str:
    """Recorta por palabra, nunca a media palabra."""
    titulo = titulo.strip()
    if len(titulo) <= limite:
        return titulo
    corte = titulo[:limite].rsplit(" ", 1)[0]
    return corte.rstrip(" ,;:-–—|").strip()


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


def aplica_guardas(blog_data: dict) -> tuple[bool, list[str]]:
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

    vetadas = busca_vetadas(titulo, desc, blog_data.get("content", ""), blog_data.get("title", ""))
    if vetadas:
        notas.append(f"PALABRAS VETADAS: {', '.join(vetadas)}")
        return False, notas

    return True, notas
