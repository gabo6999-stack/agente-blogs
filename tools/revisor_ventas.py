# -*- coding: utf-8 -*-
"""Compuerta de lenguaje de venta para sitios informativos (peptidosysuplementos.com).

Regla del dueño (8-oct-2026): «nunca pero que nunca diga nada la página sobre
ventas». El .com es el sitio hermano informativo de la tienda y su defensa ante
reportes es que no haya NADA reportable: ni precios, ni compra, ni envío, ni
pedidos, ni existencias, ni catálogo, ni COA, ni «nuestra tienda», ni
«disponible para investigación», ni un enlace o mención a la tienda (.mx).

El vocabulario sale del revisor que se corre en el servidor
(ecommerce-agent/infra/contingencia-hetzner/herramientas/sitio-informativo/
revisor-ventas.py), con dos cambios porque aquí la compuerta es AUTOMÁTICA y un
falso positivo bloquea la publicación:

- Límites de palabra donde el revisor del servidor matcheaba dentro de otras
  palabras ("ventas?" casaba con "ventajas", "ventana" e "inventario").
- Formas comerciales en vez de raíces que en un texto científico son normales:
  "la existencia de receptores", "inmunidad adquirida", "células distribuidas",
  "promoción de la salud". Siguen bloqueadas «en existencia», «existencias»,
  «adquirir/adquiérelo», «distribuidor», «promoción/es» comercial.

Lo que el servidor revisa además (cabeceras, schema que añade el tema, el
bloque de WhatsApp del mu-plugin) se sigue verificando allí con el revisor
original: esta compuerta cubre lo que escribe el agente.
"""
from __future__ import annotations

import html as _html
import re

# (patrón, etiqueta legible). Insensible a mayúsculas.
_PATRONES = [
    r"\bcompr(?!ob|im|om|end|ens|esi)\w*",
    r"\bvend(?!a\b|as\b|aj|ad)\w*",       # vender/vendemos/vendido; no venda/vendaje
    r"\bventas?\b", r"\bpreventa\w*", r"\bprecio\w*", r"\bcost(?:o|os|e|ará)\b(?!\s+(?:energ|metab|biol|fisiol))",
    r"\bcuesta\w*", r"\bMXN\b", r"\bUSD\b", r"\$\s?\d",
    r"\benv[ií]os?\b", r"\benv[ií]a(?:mos|r)\b", r"\benviam\w*", r"\bpedidos?\b",
    r"\bpag(?:o|os|ar|amos|ue)\b", r"\bcarrito\w*", r"\bcheckout\b", r"\btienda\w*",
    r"\bcat[aá]logo\w*", r"\ben existencia\b", r"\bexistencias\b", r"\bagotad[oa]s?\b",
    r"\bofertas?\b", r"\bdescuentos?\b", r"\bpromoci[oó]n(?:es)?\b(?!\s+de\s+la\s+salud)",
    r"\bclientes?\b", r"\bfactur\w*", r"\bcotiza\w*", r"\bmayoreo\b",
    r"\bdistribuidor(?:es|a|as)?\b", r"\badquirir(?:lo|la|los|las)?\b(?!\s+(?:resistencia|masa|fuerza|toleran))",
    r"\badqui[eé]r\w*", r"\bOXXO\b", r"\bMercado\s?Pago\b", r"\bPayPal\b", r"\btransferencia bancaria\b",
    r"\bSKU\b", r"\bstock\b", r"\binclu(?:ye|imos|idos?)\b[^.]{0,40}(?:vial|agua|mL)",
    r"\bCOA\b", r"\bcertificados? de an[aá]lisis\b", r"\blotes?\b", r"\bdisponibles? para investigaci[oó]n\b",
    r"\bcupon(?:es)?\b", r"\bcup[oó]n\b", r"\breembolso\w*", r"\bdevoluci[oó]n(?:es)?\b",
    r"ventas@", r"\bproveedor(?:es|a|as)?\b", r"\bfarmacias?\b",
    r"\bnuestr[oa]s? (?:productos?|tienda|cat[aá]logo|viales?)\b", r"\bdel cat[aá]logo\b",
    r"\bWhatsApp\b[^.]{0,60}\b(?:pedido|precio|cotiz|compr)\w*",
    # Nada de dopaje, nunca (decisión del dueño, 2026-09-23).
    r"\b(?:anti)?dopaje\b", r"\b(?:anti)?doping\b", r"\bWADA\b", r"\bAgencia Mundial Antidopaje\b",
    # Nunca mencionar a la tienda.
    r"peptidosysuplementos\.mx", r"\bPYS\.mx\b",
]
RX = re.compile("(" + "|".join(_PATRONES) + ")", re.I)

_RX_HREF = re.compile(r'''href\s*=\s*["']([^"']+)["']''', re.I)
_RX_A = re.compile(r"<a\s[^>]*href\s*=\s*[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.I | re.S)


def _texto_visible(h: str) -> str:
    """Texto + atributos que el lector o Google ven (alt, title, aria-label)."""
    h = h or ""
    attrs = re.findall(r'''\b(?:alt|title|aria-label|placeholder)\s*=\s*["']([^"']*)["']''', h, re.I)
    sin_script = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", h, flags=re.S | re.I)
    texto = re.sub(r"<[^>]+>", " ", sin_script)
    return _html.unescape(" ".join([texto] + attrs))


def hallazgos_venta(texto: str, contexto: int = 45) -> list[str]:
    """Cada coincidencia con su contexto: «palabra» …frase…"""
    out = []
    plano = re.sub(r"\s+", " ", texto or "")
    for m in RX.finditer(plano):
        ctx = plano[max(0, m.start() - contexto): m.end() + contexto]
        out.append(f"«{m.group(0)}» …{ctx.strip()}…")
    return out


def quita_enlaces_a_hosts(h: str, hosts) -> tuple[str, int]:
    """Desenvuelve los <a> que apunten a un host prohibido (queda el texto)."""
    hosts = [x.lower() for x in (hosts or []) if x]
    if not hosts:
        return h, 0
    quitados = 0

    def cambia(m):
        nonlocal quitados
        if any(x in m.group(1).lower() for x in hosts):
            quitados += 1
            return m.group(2)
        return m.group(0)

    return _RX_A.sub(cambia, h or ""), quitados


def revisa_articulo(blog_data: dict, hosts_prohibidos=()) -> list[str]:
    """Todos los hallazgos de venta del artículo, por campo. [] = publicable.

    Revisa lo que el agente controla: título, slug, extracto, metas de Rank
    Math, keyword, tags, alt de la imagen y el cuerpo (texto visible y
    atributos), más cualquier href a un host prohibido.
    """
    campos = {
        "title": blog_data.get("title", ""),
        "slug": (blog_data.get("slug") or "").replace("-", " "),
        "excerpt": blog_data.get("excerpt", ""),
        "rank_math_title": blog_data.get("rank_math_title", ""),
        "rank_math_description": blog_data.get("rank_math_description", ""),
        "rank_math_focus_keyword": blog_data.get("rank_math_focus_keyword", ""),
        "tags": " · ".join(blog_data.get("tags") or []),
        "image_alt": blog_data.get("image_alt", ""),
        "content": _texto_visible(blog_data.get("content", "")),
    }
    out = []
    for campo, texto in campos.items():
        for h in hallazgos_venta(_html.unescape(str(texto or ""))):
            out.append(f"{campo}: {h}")
    hosts = [x.lower() for x in (hosts_prohibidos or []) if x]
    for href in _RX_HREF.findall(blog_data.get("content", "") or ""):
        if any(x in href.lower() for x in hosts):
            out.append(f"content: enlace a host prohibido → {href}")
    return out
