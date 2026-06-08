"""
Script de corrección única: actualiza el display_name del autor en WordPress.
WordPress almacena al autor como user_id (no como string), así que cambiar
el display_name actualiza automáticamente todos los posts publicados Y los futuros.

Uso: python fix_author_name.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from config import SITES
from tools.wordpress import update_author_display_name


def main():
    print("=== Corrección de nombre de autor en WordPress ===\n")

    results = []
    for site_key, cfg in SITES.items():
        wp_url = cfg.get("wp_url")
        author_name = cfg.get("wp_author_name")

        if not wp_url:
            print(f"[{site_key}] ⚠️  Sin wp_url configurado — saltando")
            results.append((site_key, False))
            continue

        if not author_name:
            print(f"[{site_key}] ⚠️  Sin wp_author_name en config — saltando")
            results.append((site_key, False))
            continue

        print(f"[{site_key}] Actualizando display name → '{author_name}' en {wp_url}")
        ok = update_author_display_name(site_key, author_name)
        results.append((site_key, ok))

    print("\n=== Resultado ===")
    for site_key, ok in results:
        icon = "✅" if ok else "❌"
        print(f"  {icon} {site_key}")

    print("\nTodos los posts publicados muestran el nuevo nombre automáticamente.")
    print("No se requiere ningún cambio adicional en WordPress.")


if __name__ == "__main__":
    main()
