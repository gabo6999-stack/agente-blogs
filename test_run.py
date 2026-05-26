"""
Script para probar el agente manualmente sin esperar el scheduler.
Ejecuta: python test_run.py
"""

from pipeline import run_pipeline

if __name__ == "__main__":
    print("🧪 Ejecutando prueba manual del pipeline...\n")
    run_pipeline("peptidosysuplementos")
