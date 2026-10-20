import json
import os
from datetime import datetime


_DATA_DIR = os.getenv("DATA_DIR", ".")
LOG_FILE = os.path.join(_DATA_DIR, "logs", "blog_log.json")


def load_log() -> list:
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_log(log: list):
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def log_post(site_key: str, topic: str, post: dict, success: bool, error: str = None):
    log = load_log()
    entry = {
        "date": datetime.now().isoformat(),
        "site": site_key,
        "topic": topic,
        "success": success,
    }
    if success and post:
        entry["title"] = post.get("title", {}).get("rendered", "")
        entry["url"] = post.get("link", "")
        entry["post_id"] = post.get("id", "")
    if error:
        entry["error"] = error

    log.append(entry)
    save_log(log)
    
    status = "✅" if success else "❌"
    print(f"[Log] {status} {entry.get('title', topic)} → {entry.get('url', error)}")


# Errores que descartan un tema PARA SIEMPRE (no son fallos transitorios). Si
# no se cuentan como "usados", pick_topic vuelve a elegir el mismo tema en cada
# corrida y la corrida se pierde: "ghk cu mexico" se descartó el 5-oct y el
# 19-oct (y se habría seguido eligiendo) porque el ruteo lo manda a la ficha.
_DESCARTE_PERMANENTE = ("tema transaccional", "tema de venta", "tema fuera de nicho",
                        "keyword con dueño")


def get_used_topics(site_key: str, last_n: int = 20) -> list[str]:
    """Últimos N temas publicados + todos los descartados de forma permanente.

    Los fallos transitorios (auth, red, créditos de la API) NO cuentan: ese
    tema se debe reintentar.
    """
    log = load_log()
    site_logs = [e for e in log if e.get("site") == site_key]
    usados = [e["topic"] for e in site_logs if e.get("success")][-last_n:]
    for e in site_logs:
        error = str(e.get("error") or "")
        if not e.get("success") and error.startswith(_DESCARTE_PERMANENTE):
            if e.get("topic") and e["topic"] not in usados:
                usados.append(e["topic"])
    return usados


def get_history(site_key: str = None, limit: int = 20) -> list:
    """Retorna las últimas N entradas del log, opcionalmente filtradas por sitio."""
    log = load_log()
    if site_key:
        log = [e for e in log if e.get("site") == site_key]
    return list(reversed(log[-limit:]))


def get_last_post(site_key: str = None) -> dict | None:
    """Retorna el último post publicado exitosamente."""
    log = load_log()
    successful = [e for e in log if e.get("success") and e.get("url")]
    if site_key:
        successful = [e for e in successful if e.get("site") == site_key]
    return successful[-1] if successful else None
