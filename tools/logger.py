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


def get_used_topics(site_key: str, last_n: int = 20) -> list[str]:
    """Retorna los últimos N temas usados para evitar repetición."""
    log = load_log()
    site_logs = [e for e in log if e["site"] == site_key and e["success"]]
    return [e["topic"] for e in site_logs[-last_n:]]


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
