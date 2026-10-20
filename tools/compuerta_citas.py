# -*- coding: utf-8 -*-
"""Compuerta de citas: cada PMID / PMCID / DOI enlazado existe y respalda la frase.

Pedida por la auditoría SEO (oct-2026). Casos reales que se publicaron:
PMC5748842 (cinasa LRRK2 en Parkinson) y PMC6048686 (circuito de memoria
espacial) citados como evidencia de «longevidad con péptidos». Los dos PMCID
existen, así que comprobar solo la existencia no basta: hay que ver que el
paper trate lo mismo que la oración que lo cita.

1. Existencia: NCBI E-utilities (esummary; DOI → esearch [doi] en PubMed).
   Sin API key se respetan 3 peticiones/s; con NCBI_API_KEY, 10/s. Un fallo
   transitorio NO se cachea ni se toma como «no existe»: la cita queda «no
   verificable» y el artículo no se publica en esa corrida.
2. Relevancia, oración por oración:
   - la molécula de la frase aparece en el título del paper → vale;
   - si no, decide Claude Haiku en UNA llamada por artículo; si Haiku no está
     disponible, solo vale si al menos coincide el tema (diccionario es→en).
3. Lo que no existe o no corresponde se desenlaza y la afirmación se manda a
   reescribir o eliminar (writer). Si quedan afirmaciones clave —cifras
   clínicas— sin fuente en su párrafo, o menos de `min_fuentes` fuentes
   válidas, el artículo se rechaza.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import unicodedata

import requests

from tools.frases import unidades, sin_marcas, enlaces, _RX_A

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
MODELO_JUEZ = "claude-haiku-5-5"
MIN_FUENTES = 2

_RX_PMID = re.compile(r"(?:pubmed\.ncbi\.nlm\.nih\.gov|ncbi\.nlm\.nih\.gov/pubmed)/(\d{1,9})", re.I)
_RX_PMC = re.compile(r"(?:ncbi\.nlm\.nih\.gov/pmc/articles|pmc\.ncbi\.nlm\.nih\.gov/articles)/(PMC\d+)", re.I)
_RX_DOI = re.compile(r"(?:dx\.)?doi\.org/(10\.\d{4,9}/[^\s?#\"'<>]+)", re.I)
# Otras fuentes de autoridad: cuentan como fuente de una afirmación, pero no se
# verifican aquí (el agente SEO comprueba por HTTP los enlaces externos del .mx).
_RX_AUTORIDAD = re.compile(
    r"(?:nejm\.org|thelancet\.com|nature\.com|jamanetwork\.com|bmj\.com|sciencedirect\.com|"
    r"cell\.com|academic\.oup\.com|diabetesjournals\.org|ahajournals\.org|cochranelibrary\.com|"
    r"clinicaltrials\.gov|fda\.gov|ema\.europa\.eu|who\.int|nih\.gov|mayoclinic\.org|examine\.com)", re.I)
# Afirmación clave = cifra clínica. La regla de los prompts: cifra y fuente en
# el mismo párrafo.
_RX_CIFRA = re.compile(r"\d+(?:[.,]\d+)?\s?%|\bp\s?[<=≤]\s?0[.,]\d+|\bn\s?=\s?\d+|\bIC\s?(?:del\s)?95|"
                       r"\bHR\s?[=:]?\s?\d|\bOR\s?[=:]\s?\d", re.I)

# es → en para molécula y tema (los títulos de PubMed están en inglés).
_MOLECULAS = {
    "retatrutida": ["retatrutide", "ly3437943"], "retatrutide": ["retatrutide", "ly3437943"],
    "tirzepatida": ["tirzepatide"], "semaglutida": ["semaglutide"], "liraglutida": ["liraglutide"],
    "cagrilintida": ["cagrilintide"], "sermorelina": ["sermorelin"], "ipamorelina": ["ipamorelin"],
    "tesamorelina": ["tesamorelin"], "glutation": ["glutathione"], "timosina": ["thymosin"],
    "testosterona": ["testosterone"], "insulina": ["insulin"], "glucagon": ["glucagon"],
    "selank": ["selank"], "semax": ["semax"], "epitalon": ["epitalon", "epithalon"],
    "mots c": ["mots c", "mots-c"], "ghk cu": ["ghk cu", "ghk-cu", "copper peptide"],
    "nad": ["nad", "nicotinamide"], "nmn": ["nmn", "nicotinamide mononucleotide"],
    "glp 1": ["glp 1", "glucagon like peptide 1"], "gip": ["gip", "glucose dependent insulinotropic"],
    "igf 1": ["igf 1", "insulin like growth factor"], "bpc 157": ["bpc 157", "pentadecapeptide"],
    "tb 500": ["tb 500", "thymosin beta 4", "thymosin beta4"], "cjc 1295": ["cjc 1295"],
    "hormona de crecimiento": ["growth hormone", "somatotropin"],
    "metformina": ["metformin"], "rapamicina": ["rapamycin", "sirolimus"],
}
_TEMAS = {
    "longevidad": ["longevity", "lifespan", "aging", "ageing", "senescen"],
    "envejecimiento": ["aging", "ageing", "senescen", "age related"],
    "mitocondri": ["mitochondri"], "obesidad": ["obes"], "peso": ["weight", "obes"],
    "grasa": ["fat", "adipos", "lipid"], "musculo": ["muscle", "muscular", "sarcopen"],
    "muscular": ["muscle", "muscular"], "sarcopenia": ["sarcopen"], "tendon": ["tendon"],
    "cicatriz": ["healing", "wound"], "herida": ["wound", "healing"], "reparacion": ["repair", "healing", "regenerat"],
    "regenera": ["regenerat"], "piel": ["skin", "dermal", "cutaneous"], "colageno": ["collagen"],
    "cobre": ["copper"], "inflama": ["inflamm"], "inmun": ["immun"], "timo": ["thym"],
    "sueno": ["sleep"], "ansiedad": ["anxi"], "memoria": ["memory"], "cognit": ["cogniti"],
    "cerebr": ["brain", "neur", "cerebr"], "glucosa": ["glucose", "glyc"], "diabetes": ["diabet"],
    "estres oxidativo": ["oxidative"], "antioxid": ["antioxid", "oxidative"], "apetito": ["appetite", "food intake"],
    "cardiovascular": ["cardiovascular", "cardiac", "heart"], "corazon": ["heart", "cardiac"],
    "higado": ["liver", "hepat"], "rinon": ["kidney", "renal"], "hueso": ["bone", "osteo"],
    "ejercicio": ["exercise"], "intestin": ["gut", "intestin", "bowel"], "gastric": ["gastric", "stomach"],
    "peptido": ["peptide"], "receptor": ["receptor"], "angiogen": ["angiogen"], "autofagia": ["autophag"],
}

_cache_ncbi: dict[str, dict] = {}
_cache_juez: dict[str, dict] = {}
_ultima_peticion = [0.0]
_lock = threading.Lock()


class NCBINoDisponible(RuntimeError):
    pass


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFD", (t or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", t)).strip()


# ── NCBI ─────────────────────────────────────────────────────────────────────

def _ncbi_get(endpoint: str, params: dict) -> dict:
    """GET a E-utilities respetando el límite de NCBI, con reintentos."""
    params = {**params, "retmode": "json", "tool": "agente-blogs"}
    api_key = os.getenv("NCBI_API_KEY")
    if api_key:
        params["api_key"] = api_key
    intervalo = 0.11 if api_key else 0.34
    ultimo_error = ""
    for intento in range(4):
        with _lock:
            espera = _ultima_peticion[0] + intervalo - time.time()
            if espera > 0:
                time.sleep(espera)
            _ultima_peticion[0] = time.time()
        try:
            r = requests.get(f"{EUTILS}/{endpoint}", params=params, timeout=25)
            if r.status_code == 200:
                return r.json()
            ultimo_error = f"HTTP {r.status_code}"
            if r.status_code not in (429, 500, 502, 503, 504):
                break
        except (requests.RequestException, ValueError) as e:
            ultimo_error = str(e)[:120]
        time.sleep(1.5 * (intento + 1))
    raise NCBINoDisponible(f"E-utilities no respondió ({ultimo_error})")


def _esummary(db: str, ids: list[str]) -> dict[str, dict]:
    """{id: {"existe": bool, "titulo": str, "pmid": str}} para un lote de ids."""
    out = {}
    for i in range(0, len(ids), 150):
        lote = ids[i:i + 150]
        res = (_ncbi_get("esummary.fcgi", {"db": db, "id": ",".join(lote)}) or {}).get("result") or {}
        for uid in lote:
            rec = res.get(uid) or {}
            titulo = (rec.get("title") or "").strip()
            pmid = next((a.get("value") for a in rec.get("articleids") or []
                         if a.get("idtype") == "pmid"), "") if db == "pmc" else uid
            out[uid] = {"existe": bool(titulo) and not rec.get("error"), "titulo": titulo, "pmid": pmid}
    return out


def verifica_existencia(citas: list[dict]) -> None:
    """Rellena en cada cita `existe`, `titulo` y `estado` ('ok'|'no_existe'|'no_verificable')."""
    pend = {"pubmed": [], "pmc": []}
    for c in citas:
        clave = f"{c['tipo']}:{c['id']}"
        if clave in _cache_ncbi:
            continue
        if c["tipo"] == "pmid":
            pend["pubmed"].append(c["id"])
        elif c["tipo"] == "pmc":
            pend["pmc"].append(c["id"][3:])
    try:
        for db, ids in pend.items():
            ids = sorted(set(ids))
            if not ids:
                continue
            for uid, rec in _esummary(db, ids).items():
                clave = f"pmid:{uid}" if db == "pubmed" else f"pmc:PMC{uid}"
                _cache_ncbi[clave] = rec
        for c in citas:
            clave = f"doi:{c['id'].lower()}"
            if c["tipo"] != "doi" or clave in _cache_ncbi:
                continue
            res = _ncbi_get("esearch.fcgi", {"db": "pubmed", "term": f"\"{c['id']}\"[doi]"})
            idlist = ((res or {}).get("esearchresult") or {}).get("idlist") or []
            if not idlist:
                _cache_ncbi[clave] = {"existe": False, "titulo": "", "pmid": ""}
            else:
                _cache_ncbi[clave] = _esummary("pubmed", idlist[:1]).get(
                    idlist[0], {"existe": False, "titulo": "", "pmid": ""})
        caido = ""
    except NCBINoDisponible as e:
        caido = str(e)
    for c in citas:
        clave = f"{c['tipo']}:{c['id'].lower() if c['tipo'] == 'doi' else c['id']}"
        rec = _cache_ncbi.get(clave)
        if rec is None:
            c.update(existe=None, titulo="", estado="no_verificable", motivo=caido or "sin respuesta")
        else:
            c.update(existe=rec["existe"], titulo=rec["titulo"],
                     estado="ok" if rec["existe"] else "no_existe",
                     motivo="" if rec["existe"] else "no existe en NCBI")


# ── Extracción ───────────────────────────────────────────────────────────────

def extrae_citas(html: str) -> list[dict]:
    """Cada enlace a PubMed/PMC/DOI con la oración y el párrafo que lo usan."""
    citas = []
    anterior = ""
    for u in unidades(html):
        for href in enlaces(u["texto"]):
            for tipo, rx in (("pmid", _RX_PMID), ("pmc", _RX_PMC), ("doi", _RX_DOI)):
                m = rx.search(href)
                if m:
                    ident = m.group(1).rstrip("/).,;")
                    if tipo == "pmc":
                        ident = ident.upper()
                    # contexto = párrafo + oración anterior: "El mismo ensayo se
                    # publicó en NEJM" solo se entiende con la frase de antes.
                    citas.append({"tipo": tipo, "id": ident, "href": href,
                                  "frase": sin_marcas(u["texto"]), "parrafo": sin_marcas(u["parrafo"]),
                                  "contexto": sin_marcas(anterior + " " + u["parrafo"])})
                    break
        anterior = u["texto"]
    return citas


# ── Relevancia ───────────────────────────────────────────────────────────────

# Palabras que preceden a un número sin ser el nombre de una molécula.
_NO_PREFIJO = {"en", "de", "del", "la", "el", "los", "las", "y", "a", "al", "con", "por", "para",
               "hasta", "desde", "entre", "sobre", "que", "fase", "phase", "n", "p", "ic", "hr",
               "or", "semana", "semanas", "dia", "dias", "mes", "meses", "ano", "anos", "mg", "mcg",
               "ml", "ui", "unas", "unos", "mas", "menos", "casi", "cerca", "solo", "tras"}


def _entidades(texto: str) -> set[str]:
    """Moléculas que nombra el texto, como claves de _MOLECULAS o códigos tipo BPC-157."""
    n = f" {_norm(texto)} "
    ents = {k for k in _MOLECULAS if f" {k} " in n}
    for m in re.finditer(r"\b([a-z]{2,6}) ?(\d{2,7})[a-z]?\b", n):
        prefijo, cifra = m.group(1), m.group(2)
        if prefijo in _NO_PREFIJO or re.fullmatch(r"(?:19|20)\d\d", cifra):
            continue
        ents.add(m.group(0).strip())
    return ents


def _variantes(ent: str) -> list[str]:
    return _MOLECULAS.get(ent, []) + [ent, ent.replace(" ", "")]


def _temas(texto: str) -> set[str]:
    n = _norm(texto)
    return {k for k in _TEMAS if k in n}


def juicio_heuristico(frase: str, titulo: str, contexto: str = "") -> str:
    """'si' (misma molécula) | 'tema' (solo coincide el tema) | 'duda' | 'no'."""
    t = f" {_norm(titulo)} "
    ents = _entidades(frase) or _entidades(contexto)
    if any(f" {_norm(v)} " in t or _norm(v) in t for e in ents for v in _variantes(e)):
        return "si"
    # "péptido" y "receptor" aparecen en medio PubMed: no cuentan como tema.
    temas = (_temas(frase) or _temas(contexto)) - {"peptido", "receptor"}
    tema_ok = any(st in t for k in temas for st in _TEMAS[k])
    if ents:
        return "duda"          # la frase nombra una molécula que el título no
    return "tema" if tema_ok else "no"


def _juez_haiku(items: list[dict], tema: str) -> dict[int, bool] | None:
    """{n: relevante} en una sola llamada; None si no se pudo consultar."""
    if not items:
        return {}
    try:
        import anthropic
        from config import ANTHROPIC_API_KEY
        from json_repair import repair_json
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        NL = chr(10)
        lista = NL.join(f'{i}. Frase del artículo: "{it["frase"][:500]}"' + NL
                        + f'   Contexto: "{(it.get("contexto") or "")[:400]}"' + NL
                        + f'   Paper citado: "{it["titulo"]}"' for i, it in enumerate(items, 1))
        prompt = (
            f'Revisas las citas de un artículo de divulgación sobre "{tema}".' + NL
            + "Para cada cita: ¿el paper citado trata directamente lo que afirma la frase (la misma "
            "molécula, el mismo mecanismo o el mismo tema clínico)? Un paper de otra enfermedad, "
            "otro órgano u otro tema NO es relevante aunque comparta una palabra suelta." + NL + NL
            + lista + NL + NL
            + 'Responde SOLO con JSON: [{"n": 1, "relevante": true, "motivo": "breve"}, ...]')
        kwargs = dict(model=MODELO_JUEZ, max_tokens=4000,
                      messages=[{"role": "user", "content": prompt}])
        try:
            resp = client.messages.create(output_config={"effort": "low"}, **kwargs)
        except TypeError:  # SDK sin output_config
            resp = client.messages.create(**kwargs)
        if getattr(resp, "stop_reason", "") == "refusal":
            return None
        texto = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        datos = repair_json(texto[texto.find("["): texto.rfind("]") + 1], return_objects=True)
        return {int(d["n"]): bool(d.get("relevante")) for d in datos if isinstance(d, dict) and "n" in d}
    except Exception as e:
        print(f"[Citas] Juez Haiku no disponible ({e}); decido por heurística")
        return None


def _clave_juez(c: dict) -> str:
    return hashlib.sha1(f"{c['tipo']}:{c['id']}|{c['frase']}".encode("utf-8")).hexdigest()


def juzga_relevancia(citas: list[dict], tema: str, juez=_juez_haiku) -> None:
    """Rellena `relevante` (bool) y `motivo` en las citas que existen."""
    dudosas = []
    for c in citas:
        if c.get("estado") != "ok":
            continue
        clave = _clave_juez(c)
        if clave in _cache_juez:
            c.update(_cache_juez[clave])
            continue
        h = juicio_heuristico(c["frase"], c["titulo"], c.get("contexto") or c["parrafo"])
        c["heuristica"] = h
        if h == "si":
            c.update(relevante=True, motivo="la molécula de la frase está en el título")
            _cache_juez[clave] = {"relevante": True, "motivo": c["motivo"]}
        else:
            dudosas.append(c)
    veredictos = juez(dudosas, tema) if (dudosas and juez) else None
    for i, c in enumerate(dudosas, 1):
        if veredictos is not None and i in veredictos:
            rel = veredictos[i]
            motivo = "relevante según el juez" if rel else "el paper no trata lo que afirma la frase (juez)"
            _cache_juez[_clave_juez(c)] = {"relevante": rel, "motivo": motivo}
        else:  # sin juez: basta con que coincida el tema
            rel = c["heuristica"] == "tema"
            motivo = ("coincide el tema (sin juez)" if rel
                      else "ni la molécula ni el tema de la frase aparecen en el título (sin juez)")
        c.update(relevante=rel, motivo=motivo)


# ── Compuerta ────────────────────────────────────────────────────────────────

def revisa_citas(blog_data: dict, tema: str = "", juez=_juez_haiku,
                 min_fuentes: int = MIN_FUENTES) -> dict:
    """{citas, invalidas, no_verificables, sin_fuente, fuentes_validas, publicable}."""
    html = blog_data.get("content", "") or ""
    tema = tema or blog_data.get("rank_math_focus_keyword") or blog_data.get("title", "")
    citas = extrae_citas(html)
    verifica_existencia(citas)
    juzga_relevancia(citas, tema, juez)
    invalidas = [c for c in citas if c["estado"] == "no_existe"
                 or (c["estado"] == "ok" and not c.get("relevante"))]
    no_verif = [c for c in citas if c["estado"] == "no_verificable"]
    malos = {c["href"] for c in invalidas}
    buenos = {c["href"] for c in citas if c["estado"] == "ok" and c.get("relevante")}

    def fuente_valida(href: str) -> bool:
        if href in malos:
            return False
        if href in buenos:
            return True
        es_ncbi = _RX_PMID.search(href) or _RX_PMC.search(href) or _RX_DOI.search(href)
        return bool(not es_ncbi and _RX_AUTORIDAD.search(href))

    sin_fuente, vistos = [], set()
    fuentes = set()
    for u in unidades(html):
        fuentes |= {h for h in enlaces(u["texto"]) if fuente_valida(h)}
        if u["tipo"] != "oracion" or not _RX_CIFRA.search(sin_marcas(u["texto"])):
            continue
        if not any(fuente_valida(h) for h in enlaces(u["parrafo"])):
            f = sin_marcas(u["texto"])
            if f not in vistos:
                vistos.add(f)
                sin_fuente.append(f)
    publicable = not invalidas and not no_verif and not sin_fuente and len(fuentes) >= min_fuentes
    return {"citas": citas, "invalidas": invalidas, "no_verificables": no_verif,
            "sin_fuente": sin_fuente, "fuentes_validas": len(fuentes), "min_fuentes": min_fuentes,
            "publicable": publicable}


def quita_citas(html: str, hrefs) -> str:
    """Desenlaza (deja el texto) los <a> cuyo href esté en `hrefs`."""
    hrefs = set(hrefs or [])
    if not hrefs:
        return html
    return _RX_A.sub(lambda m: m.group(2) if m.group(1) in hrefs else m.group(0), html or "")


def hallazgos(res: dict) -> list[str]:
    """Texto para el log y para el prompt de reescritura."""
    out = []
    for c in res["invalidas"]:
        ref = f"{c['tipo'].upper()} {c['id']}"
        titulo = f" («{c['titulo'][:90]}»)" if c.get("titulo") else ""
        out.append(f"cita quitada, {ref}{titulo}: {c.get('motivo')}. Afirmación a reescribir o "
                   f"eliminar: «{c['frase'][:260]}»")
    for f in res["sin_fuente"]:
        out.append(f"afirmación clave (cifra clínica) sin fuente en su párrafo: «{f[:260]}»")
    if res["fuentes_validas"] < res["min_fuentes"]:
        out.append(f"solo {res['fuentes_validas']} fuente(s) válida(s); mínimo {res['min_fuentes']}")
    for c in res["no_verificables"]:
        out.append(f"{c['tipo'].upper()} {c['id']}: no verificable ahora ({c.get('motivo')})")
    return out
