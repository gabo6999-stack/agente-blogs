"""Fuerza el recálculo del puntaje de Rank Math abriendo y guardando en el editor.

Por qué hace falta
------------------
`rank_math_seo_score` es un valor ALMACENADO. Solo lo escribe el analizador que
corre dentro del editor de Gutenberg al guardar. Un post creado por la API REST
—como los del agente— nunca pasa por ahí, así que su puntaje se queda vacío por
bueno que sea el contenido. No es un problema de ranking (Google no ve ese
número) pero impide auditar el blog por puntaje.

Escribir la meta a mano NO es una solución: deja un número inventado que después
se lee como si fuera real. La única forma honesta es hacer lo que haría una
persona: abrir el post en el editor y guardar.

Uso (necesita el intérprete que tiene Playwright instalado):

    py -3.11 -m tools.rankmath_score --site peptidosysuplementos --dry-run
    py -3.11 -m tools.rankmath_score --site peptidosysuplementos --limit 5

`--dry-run` abre el editor y LEE el puntaje sin guardar nada.

Salvaguarda: el primer post actúa de canario. Se compara el `content.raw` antes
y después de guardar; si Gutenberg reformateó el HTML, el script se detiene en
vez de repetir el destrozo en el resto del blog.
"""

import argparse
import hashlib
import os
import re
import sys

import requests

# La consola de Windows va en cp1252 y revienta con «→» o «·».
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)

# En Railway las credenciales son variables de entorno reales; en local viven en
# `agente-blogs__.env`, que `load_dotenv()` sin argumentos no encuentra.
from dotenv import load_dotenv                              # noqa: E402
load_dotenv(os.path.join(_RAIZ, "agente-blogs__.env"))

from config import SITES                                    # noqa: E402

# Overlays que se comen los clics. El chat de soporte del hosting (#vue-app) es
# el peor: intercepta TODO con "subtree intercepts pointer events".
LIMPIAR_OVERLAYS = """() => {
    const sels = ['#vue-app', '#hts-chat', '[class*="kodee" i]',
                  '.rank-math-modal-overlay', '.components-modal__screen-overlay',
                  '.notice-dismiss', '#wpwrap .notice.is-dismissible'];
    let n = 0;
    for (const s of sels)
        document.querySelectorAll(s).forEach(e => { e.remove(); n++; });
    return n;
}"""

# OJO: es getAnalysisScore(), no getScore(). Y el segundo `.rank-math-toolbar-score`
# del DOM es el de Content AI y siempre da 0.
LEER_PUNTAJE = """() => {
    try {
        const s = wp.data.select('rank-math');
        if (s && typeof s.getAnalysisScore === 'function') return s.getAnalysisScore();
    } catch (e) {}
    return null;
}"""


def _sesion_rest(site_key):
    site = SITES[site_key]
    wp = site["wp_url"].rstrip("/")
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 (compatible; Googlebot/2.1)"
    r = s.post(f"{wp}/wp-json/jwt-auth/v1/token",
               json={"username": site["wp_user"], "password": site["wp_password"]},
               timeout=45)
    tok = (r.json() or {}).get("token")
    if not tok:
        raise SystemExit(f"No se pudo autenticar en {wp}: {r.status_code} {r.text[:160]}")
    s.headers["Authorization"] = f"Bearer {tok}"
    return wp, s


def _huella(html):
    """Hash del contenido, ignorando solo diferencias de espacio en blanco."""
    return hashlib.sha256(re.sub(r"\s+", " ", html or "").strip().encode()).hexdigest()[:16]


def listar_posts(wp, s, solo_sin_puntaje=True):
    out, page = [], 1
    while True:
        r = s.get(f"{wp}/wp-json/wp/v2/posts",
                  params={"per_page": 50, "page": page, "status": "publish,draft,future",
                          "context": "edit", "orderby": "date", "order": "desc",
                          "_fields": "id,date,title,meta,content"}, timeout=60)
        lote = r.json()
        if not isinstance(lote, list) or not lote:
            break
        for p in lote:
            m = p.get("meta") or {}
            score = m.get("rank_math_seo_score")
            kw = (m.get("rank_math_focus_keyword") or "").split(",")[0].strip()
            try:
                score = int(score)
            except (TypeError, ValueError):
                score = 0
            if solo_sin_puntaje and score > 0:
                continue
            out.append({
                "id": p["id"], "fecha": p["date"][:10],
                "titulo": (p.get("title") or {}).get("raw", "")[:44],
                "kw": kw, "score_previo": score,
                "huella": _huella((p.get("content") or {}).get("raw", "")),
            })
        if len(lote) < 50:
            break
        page += 1
    return out


def _login(page, wp, user, password):
    """WordPress exige que la página de login se haya cargado ANTES de enviar el
    formulario: ahí es donde deja `wordpress_test_cookie`. Si LiteSpeed sirve una
    copia cacheada, la cookie no se pone y el login falla con «las cookies están
    bloqueadas» aunque la contraseña sea correcta. De ahí el cache-buster y el
    reintento."""
    ultimo_error = ""
    for intento in (1, 2):
        page.goto(f"{wp}/wp-login.php?reauth=1&_cb={intento}",
                  wait_until="domcontentloaded", timeout=60000)
        if "/wp-admin" in page.url and "wp-login" not in page.url:
            return True
        page.wait_for_selector("#user_login", timeout=30000)
        page.wait_for_timeout(800)                 # que asiente la test cookie
        page.fill("#user_login", user)
        page.fill("#user_pass", password)
        page.click("#wp-submit")
        page.wait_for_load_state("domcontentloaded", timeout=60000)
        if "wp-login.php" not in page.url:
            return True
        try:
            ultimo_error = page.inner_text("#login_error", timeout=3000)[:220]
        except Exception:
            ultimo_error = ""
        if "cookie" not in ultimo_error.lower():
            break                                   # credenciales malas: no insistir

    raise SystemExit(
        "Login rechazado. Recuerda que wp-login.php NO acepta contraseñas de "
        "aplicación: hace falta la contraseña real del usuario.\n  " + ultimo_error)


def procesar(page, wp, post, guardar=True):
    """Abre el post, deja que Rank Math analice, guarda y devuelve el puntaje."""
    page.goto(f"{wp}/wp-admin/post.php?post={post['id']}&action=edit",
              wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(1500)
    page.keyboard.press("Escape")                # guía de bienvenida de Gutenberg
    page.evaluate(LIMPIAR_OVERLAYS)

    # El analizador tarda en arrancar; se le dan hasta ~20 s a que dé un número.
    puntaje = None
    for _ in range(40):
        puntaje = page.evaluate(LEER_PUNTAJE)
        if isinstance(puntaje, (int, float)) and puntaje > 0:
            break
        page.wait_for_timeout(500)

    if not guardar:
        return puntaje, None

    page.evaluate(LIMPIAR_OVERLAYS)
    # Dice "Guardar" aunque ya esté publicado; get_by_role('Actualizar') no lo encuentra.
    boton = page.locator("button.editor-post-publish-button").first
    if not boton.count():
        return puntaje, "no se encontró el botón de guardar"
    boton.click(timeout=20000)
    page.wait_for_timeout(6000)
    return puntaje, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="peptidosysuplementos")
    ap.add_argument("--limit", type=int, default=0, help="0 = todos")
    ap.add_argument("--dry-run", action="store_true", help="lee el puntaje sin guardar")
    ap.add_argument("--todos", action="store_true", help="incluye los que ya tienen puntaje")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright   # import tardío: solo hace falta aquí

    site = SITES[args.site]
    wp, s = _sesion_rest(args.site)
    posts = listar_posts(wp, s, solo_sin_puntaje=not args.todos)
    if args.limit:
        posts = posts[:args.limit]
    if not posts:
        print("No hay posts sin puntaje. Nada que hacer.")
        return

    print(f"{len(posts)} posts a procesar en {wp}"
          + (" (DRY-RUN, no se guarda nada)" if args.dry_run else ""))

    resultados, alterados = [], []
    with sync_playwright() as pw:
        nav = pw.chromium.launch(headless=not args.headed)
        page = nav.new_page(viewport={"width": 1500, "height": 1000})
        _login(page, wp, site["wp_user"], site["wp_password"])
        print("Sesión de wp-admin iniciada\n")

        for i, post in enumerate(posts, 1):
            etiqueta = f"[{i}/{len(posts)}] #{post['id']} {post['titulo']}"
            if not post["kw"]:
                print(f"{etiqueta}\n    ⚠️ sin focus keyword — Rank Math no tiene qué analizar, se salta")
                continue
            try:
                puntaje, err = procesar(page, wp, post, guardar=not args.dry_run)
            except Exception as e:
                print(f"{etiqueta}\n    ❌ {type(e).__name__}: {str(e)[:140]}")
                continue
            if err:
                print(f"{etiqueta}\n    ⚠️ {err}")
                continue

            nota = ""
            if not args.dry_run:
                fresco = s.get(f"{wp}/wp-json/wp/v2/posts/{post['id']}",
                               params={"context": "edit", "_fields": "meta,content"},
                               timeout=45).json()
                guardado = (fresco.get("meta") or {}).get("rank_math_seo_score")
                nueva = _huella((fresco.get("content") or {}).get("raw", ""))
                if nueva != post["huella"]:
                    alterados.append(post["id"])
                    nota = "  ⚠️ EL EDITOR CAMBIÓ EL HTML"
                puntaje = guardado or puntaje

            resultados.append((post, puntaje))
            print(f"{etiqueta}\n    kw «{post['kw']}» · {post['score_previo']} → {puntaje}{nota}")

            # Canario: si el primer guardado tocó el HTML, no repetirlo en el resto.
            if alterados and i == 1:
                print("\n⛔ El editor reformateó el contenido del primer post.\n"
                      "   Me detengo aquí en vez de hacerlo con todo el blog.\n"
                      f"   Revisa el post {post['id']} antes de continuar.")
                break
        nav.close()

    print("\n" + "=" * 58)
    logrados = [(p, v) for p, v in resultados if isinstance(v, (int, float)) and v > 0]
    if logrados:
        prom = sum(v for _, v in logrados) / len(logrados)
        print(f"{len(logrados)} posts con puntaje real · promedio {prom:.1f}")
        for p, v in sorted(logrados, key=lambda x: x[1]):
            marca = "  " if v >= 81 else "⚠️"
            print(f"  {marca} {v:>3}  #{p['id']}  {p['titulo']}")
    bajos = [p for p, v in logrados if v < 81]
    if bajos:
        print(f"\n{len(bajos)} por debajo de 81 — ahí sí hay trabajo de contenido.")
    if alterados:
        print(f"\n⚠️ El editor modificó el HTML de: {alterados}")


if __name__ == "__main__":
    main()
