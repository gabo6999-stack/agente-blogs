# -*- coding: utf-8 -*-
"""Compuerta de dosis: ninguna pauta de uso para personas en un artículo.

Pedida por la auditoría SEO (oct-2026) con dos casos reales que se colaron:
«sermorelina 200-300 mcg subcutáneo antes de dormir, en ciclos 5/2» y
«MOTS-c 5-10 mg subcutáneo, 3 veces por semana». Un post de blog que dice
cuánto, cómo y cada cuándo inyectarse algo es una indicación de uso: para la
tienda es un riesgo legal y para el sitio informativo rompe su razón de ser.

Una PAUTA es una oración (o fila de tabla) con una cantidad (mg, mcg, µg, UI,
mL) junto a una vía, una frecuencia, un horario o un ciclo/protocolo; o, sin
cantidad, una instrucción en imperativo/infinitivo con dos de esas señales.

Modos (`dose_gate` en config):
- "estricto"  (peptidosysuplementos): ninguna pauta, ni siquiera citada.
- "citado"    (pyscom): se permite una cifra SOLO si la misma oración la
  atribuye a un estudio («en el ensayo X, los participantes recibieron…») y
  enlaza la fuente. Las filas de tabla no tienen esa atribución: se rechazan.
"""
from __future__ import annotations

import re

from tools.frases import unidades, sin_marcas, enlaces

_CANTIDAD = re.compile(
    r"\b\d+(?:[.,]\d+)?(?:\s*(?:-|–|—|a|y|o)\s*\d+(?:[.,]\d+)?)?\s*"
    r"(?:mg|mcg|µg|μg|ug|ui|iu|unidades|ml|cc)\b(?!\s*/\s*(?:d?l|kg)\b)",
    re.I)
_VIA = re.compile(
    r"\b(?:subcut[aá]ne[oa]s?|subcut[aá]neamente|subq|s\.c\.|intramuscular(?:es|mente)?|"
    r"intraven[oa]s[oa]s?|intravenosamente|endoven[oa]s[oa]|intranasal|sublingual|"
    r"v[ií]a oral|por v[ií]a|inyecci[oó]n(?:es)?|inyectad[oa]s?|inyectable)\b", re.I)
_VIA_SIGLAS = re.compile(r"(?<!fase\s)(?<!Fase\s)\b(?:IV|IM|SC)\b")  # sensible a mayúsculas
_FRECUENCIA = re.compile(
    r"\b(?:al|por|cada|a la)\s+(?:d[ií]a|semana|mes|noche|mañana)\b|"
    r"\bd[ií]as?\s*/\s*semana\b|\bdiari[oa]s?\b|\bdiariamente\b|\bsemanal(?:es|mente)?\b|"
    r"\bquincenal(?:es)?\b|\b\d+\s*(?:x|veces)\b|\b(?:una|dos|tres|cuatro|cinco|seis)\s+veces\b|"
    r"\bcada\s+\d+\s*(?:h|horas|d[ií]as|semanas)\b|\bantes de (?:dormir|acostarse|entrenar|comer|desayunar)\b|"
    r"\bdespu[eé]s de (?:entrenar|comer|cenar)\b|\ben ayunas\b|\bpor la (?:mañana|noche|tarde)\b|"
    r"\bnocturn[oa]s?\b|\bdosis (?:diaria|semanal)\b", re.I)
_CICLO = re.compile(
    r"\bciclos?\b|\bprotocolos?\b|\b\d+\s*/\s*\d+\b|\bon\s*/\s*off\b|\bsemanas? (?:on|off)\b|"
    r"\bdescanso\b|\btitulaci[oó]n\b|\bescalamiento\b|\bdosis de (?:inicio|mantenimiento|carga)\b|"
    r"\bmicrodosi\w*\b|\bstack\b|\bdurante \d+ (?:d[ií]as|semanas|meses)\b", re.I)
_INSTRUCCION = re.compile(
    r"\b(?:aplica|aplicar|apl[ií]cate|inyecta|inyectar|iny[eé]ctate|administra|administrar|"
    r"toma|tomar|t[oó]malo|usa|usar|[uú]salo|empieza|empezar|comienza|comenzar|sube|subir|"
    r"aumenta|aumentar|divide|dividir|se recomienda|recomendamos|se sugiere|se aconseja)\b", re.I)
_CABECERA_PAUTA = re.compile(r"\b(?:dosis|dosificaci[oó]n|frecuencia|v[ií]a|ciclo|protocolo|pauta|horario)\b", re.I)
_ATRIBUCION = re.compile(
    r"\b(?:en el|en un|en los|en este|en ese|del|el)\s+(?:ensayo|estudio|trial|an[aá]lisis|metaan[aá]lisis)\b|"
    r"\bparticipantes\b|\bvoluntarios\b|\b(?:pacientes|sujetos|ratas|ratones|animales)\s+(?:recibieron|fueron)\b|"
    r"\bse (?:les )?administr(?:ó|aron)\b|\brecibieron\b|\bse us(?:ó|aron)\b|\bfase\s+(?:1|2|3|I|II|III)\b", re.I)
_FUENTE = re.compile(
    r"pubmed\.ncbi|ncbi\.nlm\.nih\.gov|pmc\.ncbi|doi\.org|clinicaltrials\.gov|nejm\.org|thelancet\.com|"
    r"nature\.com|jamanetwork\.com|bmj\.com|sciencedirect\.com|cell\.com|academic\.oup\.com|"
    r"diabetesjournals\.org|fda\.gov|ema\.europa\.eu", re.I)


def _es_pauta(texto: str, cabecera: str = "") -> bool:
    plano = sin_marcas(texto)
    cantidad = bool(_CANTIDAD.search(plano))
    via = bool(_VIA.search(plano) or _VIA_SIGLAS.search(plano))
    frec = bool(_FRECUENCIA.search(plano))
    ciclo = bool(_CICLO.search(plano))
    if cantidad and (via or frec or ciclo):
        return True
    if cantidad and cabecera and _CABECERA_PAUTA.search(cabecera):
        return True  # fila "BPC-157 | 250 mcg" bajo una cabecera "Dosis | Frecuencia"
    if _INSTRUCCION.search(plano) and (via + frec + ciclo) >= 2:
        return True
    return False


def _atribuida_a_estudio(texto: str) -> bool:
    """La misma oración dice que la cifra es de un estudio Y enlaza la fuente."""
    return bool(_ATRIBUCION.search(sin_marcas(texto))
                and any(_FUENTE.search(u) for u in enlaces(texto))
                and not _INSTRUCCION.search(sin_marcas(texto)))


def revisa_dosis(blog_data: dict, modo: str = "estricto") -> list[str]:
    """Pautas de uso encontradas, como «…oración…». [] = publicable.

    Revisa el cuerpo (oraciones y filas de tabla), el extracto y las metas.
    """
    if not modo:
        return []
    hallazgos = []
    for u in unidades(blog_data.get("content", "")):
        if not _es_pauta(u["texto"], u.get("tabla_cabecera", "")):
            continue
        if modo == "citado" and u["tipo"] == "oracion" and _atribuida_a_estudio(u["texto"]):
            continue
        etiqueta = "fila de tabla" if u["tipo"] == "fila" else "oración"
        hallazgos.append(f"{etiqueta}: «{sin_marcas(u['texto'])[:220]}»")
    for campo in ("excerpt", "rank_math_description", "rank_math_title", "title"):
        if _es_pauta(blog_data.get(campo, "") or ""):
            hallazgos.append(f"{campo}: «{blog_data.get(campo)}»")
    return hallazgos
