# 🤖 Agente de Blogs — peptidosysuplementos.mx

Agente autónomo que publica 4 blogs por semana usando tendencias de Google,
Claude AI para redacción SEO, y Unsplash para imágenes.

## Estructura

```
agente-blogs/
├── .env                  # Credenciales (nunca subir a GitHub)
├── .gitignore
├── config.py             # Configuración de sitios
├── pipeline.py           # Pipeline principal + scheduler
├── test_run.py           # Prueba manual
├── requirements.txt
├── prompts/
│   └── system.py         # Prompt del agente escritor
├── tools/
│   ├── trends.py         # Google Trends (PyTrends)
│   ├── writer.py         # Claude API + web_search
│   ├── images.py         # Unsplash API
│   ├── wordpress.py      # WordPress REST API + Rank Math
│   └── logger.py         # Log de publicaciones
└── logs/
    └── blog_log.json     # Historial de blogs publicados
```

## Instalación

```bash
# 1. Instalar dependencias
pip install -r requirements.txt

# 2. Configurar .env
# Editar .env con tus credenciales reales

# 3. Probar manualmente (publica UN blog ahora)
python test_run.py

# 4. Iniciar agente autónomo (publica automáticamente L/M/J/V @ 9am)
python pipeline.py
```

## Configuración del .env

```env
# WordPress
SITE1_WP_URL=https://peptidosysuplementos.mx
SITE1_WP_USER=tu_usuario
SITE1_WP_PASSWORD=tu_password

# Anthropic (obtener en console.anthropic.com)
ANTHROPIC_API_KEY=sk-ant-xxx

# Unsplash (obtener en unsplash.com/developers)
UNSPLASH_ACCESS_KEY=tu_access_key
```

## Agregar segundo sitio (multisitio)

1. Agregar en `.env`:
```env
SITE2_WP_URL=https://otrasitio.com
SITE2_WP_USER=usuario2
SITE2_WP_PASSWORD=pass2
```

2. Agregar en `config.py` dentro del dict `SITES`:
```python
"otrasitio": {
    "wp_url": os.getenv("SITE2_WP_URL"),
    ...
}
```

## Logs

Los blogs publicados se guardan en `logs/blog_log.json`:
```json
[
  {
    "date": "2025-01-15T09:00:00",
    "site": "peptidosysuplementos",
    "topic": "BPC-157 beneficios",
    "success": true,
    "title": "BPC-157: Guía Completa de Beneficios y Uso",
    "url": "https://peptidosysuplementos.mx/bpc-157-guia-completa",
    "post_id": 123
  }
]
```

## ⚠️ Notas importantes

- Nunca subas el archivo `.env` a GitHub
- Regenera las claves de Unsplash y cambia la contraseña de WP después de configurar
- El agente publica directamente sin revisión humana
- Para pausar: Ctrl+C en la terminal donde corre `pipeline.py`
