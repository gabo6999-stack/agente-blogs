import os
from dotenv import load_dotenv

load_dotenv()

# Site config — fácil de extender para multisitio
SITES = {
    "peptidosysuplementos": {
        "wp_url": os.getenv("SITE1_WP_URL"),
        "wp_user": os.getenv("SITE1_WP_USER"),
        "wp_password": os.getenv("SITE1_WP_PASSWORD"),
        "niche": "péptidos y suplementos deportivos",
        "language": "es",
        "keywords_seed": [
            "péptidos", "BPC-157", "TB-500", "retatrutide", "IGF-1",
            "suplementos deportivos", "pérdida de grasa", "masa muscular",
            "recuperación muscular", "biohacking", "longevidad",
            "GHK-Cu", "MOTS-c", "hormona de crecimiento", "testosterona",
            "composición corporal", "rendimiento deportivo"
        ],
        "publish_days": ["monday", "tuesday", "thursday", "friday"],
        "publish_time": "09:00",
        "post_length": 1500,
        "unsplash_fallback": "peptides supplements sports performance",
        "seo_agent_url": os.getenv("SEO_AGENT_URL", "https://web-production-3743c.up.railway.app"),
        "seo_optimize_path": "/optimize-blog",
        # El artículo nace en BORRADOR: el agente SEO lo promueve a `publish`
        # solo si pasa las compuertas (2-3 enlaces a ficha, ningún 404, no
        # canibaliza una ficha, retrofeed). Si se publicara de entrada, el
        # rechazo llegaría con el artículo ya en vivo y no serviría de nada.
        "publish_status": "draft",
        "product_map_path": "/product-map",
        "keyword_route_path": "/keyword-route",
        "wp_author_name": " ",
        "default_categories": ["Blog"],
    },
    # Antes se llamaba "grupoptm" y apuntaba a grupoptm.com. PTM se rebrandeó a
    # Telenzia, así que la clave y el sitio se movieron a telenzia.com. Las
    # variables de entorno siguen siendo SITE2_* para no renombrarlas en Railway.
    "telenzia": {
        "wp_url": os.getenv("SITE2_WP_URL"),
        "wp_user": os.getenv("SITE2_WP_USER"),
        "wp_password": os.getenv("SITE2_WP_PASSWORD"),
        "niche": "telemedicina en salud hormonal y metabólica en México: control de peso con GLP-1, péptidos, terapia de reemplazo hormonal en hombres y salud hormonal en mujeres",
        "language": "es",
        # Semillas alineadas con los 4 tipos de consulta del sitio, y todas de
        # intención INFORMACIONAL a propósito: lo transaccional vive en las
        # landings, y mandar un post a una consulta de compra no convierte.
        "keywords_seed": [
            "salud hormonal", "salud metabólica", "control de peso con GLP-1",
            "semaglutida", "tirzepatida", "análogos de GLP-1",
            "péptidos", "terapia con péptidos", "recuperación y rendimiento",
            "terapia de reemplazo hormonal", "testosterona baja", "TRH en hombres",
            "menopausia", "perimenopausia", "SOP", "salud hormonal femenina",
            "telemedicina en México", "consulta médica en línea", "cita médica virtual",
            "estudios de laboratorio hormonales", "biohacking", "longevidad",
        ],
        "publish_days": ["monday", "thursday", "sunday"],
        "publish_time": "09:00",
        "post_length": 1500,
        "unsplash_fallback": "telemedicine doctor consultation hormonal health",
        # SIN seo_agent_url a propósito: la ruta /optimize-ptm-blog del agente SEO
        # está cableada a grupoptm.com (lee SU catálogo para los interlinks), así
        # que optimizar por ahí inyectaría enlaces del sitio equivocado. Hasta que
        # exista una ruta propia, el pipeline salta ese paso y publica directo.
        "wp_author_name": "Telenzia",
        "default_categories": ["Salud hormonal y metabólica"],
    },
    "arcademotors": {
        "platform": "arcade",                                   # NO es WordPress: postea al endpoint propio
        "arcade_url": os.getenv("ARCADE_URL", "https://arcademotorsmx.com/api/blog-publish.php"),
        "arcade_api_key": os.getenv("ARCADE_API_KEY"),
        "niche": "compra y venta de autos usados y seminuevos en México",
        "language": "es",
        "keywords_seed": [
            "autos usados", "autos seminuevos", "comprar auto", "vender auto",
            "precio de autos", "trámites vehiculares", "cambio de propietario",
            "factura de auto", "tenencia", "verificación vehicular", "REPUVE",
            "financiamiento de autos", "inspección pre-compra", "kilometraje",
            "autos en México", "consejos para vender un auto", "evitar estafas al comprar auto",
        ],
        "publish_days": ["monday", "wednesday", "friday"],
        "publish_time": "10:00",
        "post_length": 1500,
        "unsplash_fallback": "used car mexico",
        "arcade_list_url": os.getenv("ARCADE_LIST_URL", "https://arcademotorsmx.com/api/blog-list.php"),
    },
    "nodarishub": {
        "wp_url": os.getenv("SITE3_WP_URL"),
        "wp_user": os.getenv("SITE3_WP_USER"),
        "wp_password": os.getenv("SITE3_WP_PASSWORD"),
        "content_style": "agency",                              # usa get_agency_system_prompt (nicho NO médico)
        "seo_agent_url": os.getenv("SEO_AGENT_URL", "https://web-production-3743c.up.railway.app"),
        "seo_optimize_path": "/optimize-nodarishub-blog",
        "niche": "diseño de páginas web a código, SEO y desarrollo de software a la medida para PyMEs en México y Ecuador",
        "language": "es",
        "keywords_seed": [
            "diseño web para PyME", "página web para negocio", "página web a la medida",
            "página web a código vs plantilla", "SEO para PyMEs", "posicionamiento web en Google",
            "cómo aparecer en Google", "Core Web Vitals", "velocidad de carga web",
            "software a la medida para empresas", "automatización de procesos",
            "tienda en línea para PyME", "e-commerce para negocio", "landing page que convierte",
            "rediseño de página web", "Google Search Console", "analítica web GA4",
            "marketing digital para PyMEs", "página web profesional", "dominio y hosting para negocio",
            "cuánto cuesta una página web", "WordPress vs desarrollo a medida",
            # Clusters ganables medidos (DataForSEO EC 2218, ago-2026): buyer-intent
            # + baja competencia. El motor de tráfico real, no el diseño web genérico
            # (KD 100). Los temas de país-específico (SRI/SAT, Kushki/Mercado Pago) el
            # redactor los localiza según la categoría de mercado de la entrada.
            "desarrollo de software a la medida",      # 1.600/mes KD 0 — el más blando
            "aplicaciones móviles a la medida",         # 260/mes KD 1 — era hueco
            "app para tu negocio",
            "qué es el e-commerce",                     # 480/mes KD 5, informacional-buyer
            "cómo vender por internet desde cero",
            "pago contra entrega en tu tienda en línea",   # 590/mes KD 0 (fuerte en EC)
            "pasarela de pagos para tienda en línea",      # 320/mes KD 2
            "facturación electrónica para tu tienda en línea",  # SRI (EC) / CFDI-SAT (MX)
            "sistema de inventario y ventas para tu negocio",
            "cuánto cobra una agencia de diseño web",   # buyer-research, no DIY
        ],
        "publish_days": ["monday", "wednesday", "friday"],
        "publish_time": "09:00",
        "post_length": 1400,
        "unsplash_fallback": "web design development software office",
        "wp_author_name": "Nodaris Hub",
        "default_categories": ["Blog"],
        # El blog vive separado por país: /mx/blog/ y /ec/blog/. La categoría es
        # lo que decide la subcarpeta (la construye el mu-plugin
        # `nodaris-blog-paises` a partir de ella), así que cada entrada tiene que
        # nacer con la de su mercado.
        "country_categories": {"ec": "Ecuador", "mx": "México"},
    },
    # Colegio Waldorf en San Andrés Cholula. Antes publicaba Rafael Mena a mano con
    # su propio Claude: tandas sin portada e imágenes de Wikimedia elegidas por
    # palabra clave sin mirarlas (grabados, estatuas, un cartel político). Por eso
    # este sitio pasa cada foto por una revisión con visión antes de usarla.
    "tlaollin": {
        "wp_url": os.getenv("SITE4_WP_URL"),
        "wp_user": os.getenv("SITE4_WP_USER"),
        "wp_password": os.getenv("SITE4_WP_PASSWORD"),
        "content_style": "waldorf",
        "niche": "pedagogía Waldorf, crianza consciente y desarrollo en la primera infancia (0 a 7 años) para familias de Cholula y Puebla",
        "language": "es",
        "keywords_seed": [
            "pedagogía Waldorf", "escuela Waldorf en Puebla", "jardín de infancia Waldorf",
            "primera infancia", "juego libre", "crianza consciente", "ritmo diario en casa",
            "euritmia", "festivales de las estaciones", "huerto escolar", "arte en la infancia",
            "lectoescritura en Waldorf", "madurez escolar", "naturaleza y niños",
        ],
        # Un artículo por semana, los lunes, sin fecha de fin (dueño, 2026-10-01).
        # El contenedor corre en UTC: 15:00 UTC = 9:00 en el centro de México.
        "publish_days": ["monday"],
        "publish_time": "15:00",
        # Sin market DataForSEO y publicando sin fin: cuando la cola se vacía,
        # Claude propone temas nuevos contra lo ya publicado (ver get_idea_topics).
        "topic_ideas": True,
        "post_length": 1500,
        "unsplash_fallback": "children playing outdoors nature",
        "image_vision_check": True,
        "default_categories": ["Pedagogía Walforf"],
        # Nombres EXACTOS de las categorías del sitio ("Walforf" incluido: así se
        # llama allá). Uno distinto crearía una categoría nueva.
        "allowed_categories": [
            "Pedagogía Walforf", "Primera Infancia", "Crianza Consciente",
            "Juego y Aprendizaje", "Desarrollo Emocional", "Naturaleza y Sustentabilidad",
            "Comunidad Educativa",
        ],
        "whatsapp": "5215534668552",
        # Enlaces internos máximos en el cuerpo; el CTA del cierre no cuenta.
        "max_internal_links": 5,
        "cta_links": ["https://tlaollinwaldorfcholula.com/camino-de-ingreso-tlaollin/"],
        # Páginas del sitio que el redactor puede enlazar (además de los posts).
        "paginas_clave": {
            "Pedagogía Waldorf y crianza positiva": "https://tlaollinwaldorfcholula.com/crianza-positiva-pedagogia-waldorf/",
            "Euritmia en Tlaollin": "https://tlaollinwaldorfcholula.com/euritmia/",
            "Camino de ingreso": "https://tlaollinwaldorfcholula.com/camino-de-ingreso-tlaollin/",
            "Nuestra comunidad": "https://tlaollinwaldorfcholula.com/desarrollo-infantil-comunidad/",
            "Nosotros": "https://tlaollinwaldorfcholula.com/comunidad-educativa-tlaollin-nosotros/",
            "Nuestro equipo": "https://tlaollinwaldorfcholula.com/escuelas-alternativas-en-puebla-equipo/",
        },
    },
}

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY")
