# -*- coding: utf-8 -*-
"""Parte el HTML de un artículo en unidades de texto (oraciones y filas de tabla).

Las compuertas de dosis y de citas juzgan ORACIÓN por oración: una cifra solo
está permitida si la misma oración la atribuye a un estudio, y una cita solo
vale si la oración que la usa habla de lo mismo que el paper. Cada unidad
conserva sus enlaces como marcas `[[href:URL]]` para poder saber qué oración
cita qué.
"""
from __future__ import annotations

import html as _html
import re

_RX_A = re.compile(r"<a\s[^>]*?href\s*=\s*[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.I | re.S)
_RX_TABLA = re.compile(r"<table\b.*?</table>", re.I | re.S)
_RX_FILA = re.compile(r"<tr\b.*?</tr>", re.I | re.S)
_RX_CELDA = re.compile(r"<t[hd]\b[^>]*>(.*?)</t[hd]>", re.I | re.S)
_RX_BLOQUE = re.compile(r"</?(?:p|li|ul|ol|h[1-6]|div|section|blockquote|br|figure|figcaption)\b[^>]*>", re.I)
_RX_ORACION = re.compile(r"(?<=[.!?])\s+(?=[\"«¿¡(]?[A-ZÁÉÍÓÚÑÜ0-9])")
RX_MARCA = re.compile(r"\[\[href:([^\]]+)\]\]")


def _con_marcas(h: str) -> str:
    """<a href="X">texto</a> -> 'texto [[href:X]]' ; el resto de etiquetas fuera."""
    h = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", h or "", flags=re.S | re.I)
    h = _RX_A.sub(lambda m: f"{m.group(2)} [[href:{m.group(1)}]]", h)
    return h


def _limpia(t: str) -> str:
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", _html.unescape(t)).strip()


def unidades(h: str) -> list[dict]:
    """[{tipo: 'oracion'|'fila', texto, parrafo, tabla_cabecera}] en orden.

    `parrafo` es el bloque completo al que pertenece la oración (la regla de
    los prompts es «cifra y fuente en el mismo párrafo»). En una fila,
    `tabla_cabecera` trae el texto de la primera fila de su tabla.
    """
    h = _con_marcas(h)
    out: list[dict] = []

    def tabla(m):
        filas = _RX_FILA.findall(m.group(0))
        textos = [" | ".join(_limpia(c) for c in _RX_CELDA.findall(f)) for f in filas]
        cab = textos[0] if textos else ""
        for t in textos:
            if t:
                out.append({"tipo": "fila", "texto": t, "parrafo": t, "tabla_cabecera": cab})
        return "\n\n"

    resto = _RX_TABLA.sub(tabla, h)
    for bloque in _RX_BLOQUE.split(resto):
        bloque = _limpia(bloque)
        if not bloque:
            continue
        for o in _RX_ORACION.split(bloque):
            o = o.strip()
            if o:
                out.append({"tipo": "oracion", "texto": o, "parrafo": bloque, "tabla_cabecera": ""})
    return out


def sin_marcas(t: str) -> str:
    return re.sub(r"\s+", " ", RX_MARCA.sub("", t or "")).strip()


def enlaces(t: str) -> list[str]:
    return RX_MARCA.findall(t or "")
