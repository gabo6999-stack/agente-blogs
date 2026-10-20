# -*- coding: utf-8 -*-
"""Compuerta de keyword con dueño: un post no compite con una ficha o monografía del .mx.

Regla del dueño (CLAUDE.md): cada molécula tiene DOS páginas en la tienda.
La ficha (/product/<slug>/) reclama el nombre comercial + gramaje/país/precio;
la monografía (/monografia/<slug>/) reclama el nombre científico, la grafía
inglesa, el código de laboratorio y «qué es / mecanismo / evidencia». Un post
de blog cuya keyword principal se reduce a uno de esos nombres canibaliza a
su dueña, y Google puede elegir el post (sin botón de compra).

Por qué no basta el ruteo actual (`/keyword-route` del agente SEO,
ecommerce-agent/web.py `route_keyword`):
- solo conoce FICHAS publicadas y con existencias (`build_product_map`
  descarta agotadas) y no sabe nada de las monografías;
- manda a la ficha solo con señal de compra o con modificador de dosis/país,
  y los marcadores informativos («qué es», «para qué sirve», «beneficios»,
  «efectos», «guía», «protocolo») GANAN: «tirzepatida para qué sirve» o
  «mots-c» a secas salen como «blog»;
- es fail-open (si no responde, se escribe) y pyscom no tiene ruteo.

Aquí: se leen (público, sin auth) las fichas y monografías del .mx, se sacan
sus alias, y una keyword tiene dueño si, quitando los modificadores
informativos/comerciales, solo queda el nombre de uno o varios compuestos.
«receptor GLP-1», «ensayo TRIUMPH de retatrutide» o «biogénesis mitocondrial»
conservan un tema propio y pasan.
"""
from __future__ import annotations

import html as _html
import re
import time
import unicodedata

import requests

_TTL = 1800
_cache: dict[str, tuple[float, list[dict]]] = {}

# Modificadores que NO le dan a la keyword un tema propio.
_MODIF = set("""
que es son para sirve sirven como funciona funcionan beneficios beneficio efectos efecto
secundarios adversos riesgos riesgo dosis dosificacion guia completa definitiva todo sobre
precio precios comprar compra costo costos cuanto cuesta donde venta mexico cdmx original originales
mg mcg ml ui de del la el los las y o e en con por un una al a lo mi tu se mas mejor
vs versus contra diferencia diferencias entre mecanismo accion historia evidencia estudios estudio
ensayos ensayo clinicos clinico clinica ciencia cientifica resultados opiniones resenas
inyectable inyectables peptido peptidos ha han publicado informacion usos uso significa
tomar usar aplicar ciclo ciclos protocolo protocolos original generico suplemento suplementos
""".split())
# Ruido de los títulos de producto que no forma parte del nombre.
_RUIDO = set("nutricost caps capsulas softgels mexico no dac suplemento energia metabolismo "
             "balance hormonal epa dha".split())
_VARIANTES = {
    "retatrutida": ["retatrutide", "ly3437943"], "tirzepatida": ["tirzepatide", "mounjaro"],
    "semaglutida": ["semaglutide", "ozempic", "wegovy"], "cagrilintida": ["cagrilintide"],
    "sermorelina": ["sermorelin"], "ipamorelina": ["ipamorelin"], "glutation": ["glutathione"],
    "timosina alfa 1": ["thymosin alpha 1", "timosina alfa1", "ta1"], "nad": ["nad+"],
    "agua bacteriostatica": ["bacteriostatic water"], "igf 1 lr3": ["igf1 lr3"],
    "mots c": ["motsc"], "ghk cu": ["ghkcu", "ghk"], "bpc 157": ["bpc157"], "tb 500": ["tb500"],
}


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFD", _html.unescape(t or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", t)).strip()


def _alias_de_nombre(nombre: str, conservar_parentesis: bool) -> set[str]:
    """«CJC-1295 (no-DAC) + Ipamorelina» -> {cjc 1295 ipamorelina, cjc 1295, ipamorelina}."""
    nombre = _html.unescape(nombre or "").split("|")[0]
    extra = set()
    if conservar_parentesis:
        extra |= {_norm(p) for p in re.findall(r"\(([^)]+)\)", nombre)}
    nombre = re.sub(r"\([^)]*\)", " ", nombre)
    nombre = re.sub(r"\b\d+(?:[.,]\d+)?\s*(?:mg|mcg|ml|ui|caps?|c[aá]psulas|softgels)\b", " ", nombre, flags=re.I)
    partes = [nombre] + re.split(r"\s\+\s|\+|\s(?:e|y)\s", nombre)
    out = set()
    for p in partes:
        # Los números que quedan son parte del nombre (bpc 157, igf 1, timosina
        # alfa 1): gramajes y conteos ya se quitaron arriba.
        toks = [t for t in _norm(p).split() if t not in _RUIDO]
        a = " ".join(toks).strip()
        if a and a not in _MODIF:
            out.add(a)
    out |= {e for e in extra if e}
    for a in list(out):
        out |= set(_VARIANTES.get(a, []))
    return out


def duenos(sitio_url: str) -> list[dict]:
    """[{tipo, nombre, url, alias}] de fichas y monografías del sitio (cacheado 30 min)."""
    ahora = time.time()
    if sitio_url in _cache and ahora - _cache[sitio_url][0] < _TTL:
        return _cache[sitio_url][1]
    out = []
    for tipo, ruta in (("ficha", "product"), ("monografía", "monografia")):
        for pagina in (1, 2, 3):
            try:
                r = requests.get(f"{sitio_url}/wp-json/wp/v2/{ruta}",
                                 params={"per_page": 100, "page": pagina, "_fields": "title,slug,link"},
                                 timeout=20)
                if r.status_code != 200:
                    break
                lote = r.json()
            except Exception as e:
                print(f"[Dueño] No pude leer {ruta} de {sitio_url} ({e})")
                break
            if not isinstance(lote, list) or not lote:
                break
            for p in lote:
                nombre = (p.get("title") or {}).get("rendered", "")
                if tipo == "monografía":
                    nombre_base = nombre.split(":")[0]
                else:
                    nombre_base = nombre
                alias = _alias_de_nombre(nombre_base, conservar_parentesis=(tipo == "monografía"))
                alias |= _alias_de_nombre((p.get("slug") or "").replace("-", " "), False)
                out.append({"tipo": tipo, "nombre": _html.unescape(nombre), "url": p.get("link", ""),
                            "alias": sorted(alias, key=len, reverse=True)})
            if len(lote) < 100:
                break
    if out:  # una lectura fallida no se cachea
        _cache[sitio_url] = (ahora, out)
    return out


def dueno_de_keyword(keyword: str, lista: list[dict]) -> list[dict]:
    """Dueñas de la keyword ([] = no tiene dueño).

    Tiene dueño si contiene al menos un alias y, quitando los alias y los
    modificadores (qué es, para qué sirve, dosis, precio, México, años,
    gramajes...), no queda ninguna palabra con tema propio.
    """
    kw = f" {_norm(keyword)} "
    if not kw.strip():
        return []
    todas = sorted({(a, i) for i, d in enumerate(lista) for a in d["alias"]},
                   key=lambda x: len(x[0]), reverse=True)
    encontradas = []
    resto = kw
    for alias, i in todas:
        if f" {alias} " in resto:
            resto = resto.replace(f" {alias} ", " ")
            if lista[i] not in encontradas:
                encontradas.append(lista[i])
        elif f" {alias} " in kw and lista[i] not in encontradas:
            encontradas.append(lista[i])  # el mismo alias en ficha y monografía
    if not encontradas:
        return []
    sobra = [t for t in resto.split() if t not in _MODIF and not re.fullmatch(r"\d+", t)]
    return [] if sobra else encontradas


def keywords_con_dueno_para_prompt(lista: list[dict]) -> str:
    """Lista corta de nombres con dueño para inyectarla en el prompt del redactor."""
    nombres = sorted({d["nombre"].split(":")[0].split("|")[0].strip() for d in lista})
    return "- " + "\n- ".join(nombres) if nombres else ""
