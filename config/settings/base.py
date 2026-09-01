"""Base settings for TransBooking BF."""
from datetime import timedelta
from pathlib import Path

import environ


BASE_DIR = Path(__file__).resolve().parents[2]

env = environ.Env(
    DEBUG=(bool, False),
    SECRET_KEY=(str, "change-me-in-env"),
    DATABASE_URL=(str, "postgres://postgres:postgres@localhost:5432/transbooking"),
    REDIS_URL=(str, "redis://localhost:6379/0"),
    JWT_SECRET=(str, "change-me-in-env"),
    SMS_PROVIDER=(str, "console"),
    SMS_API_KEY=(str, ""),
    SMS_SENDER_ID=(str, "TRANSBOOK"),
    STORAGE_BACKEND=(str, "local"),
    AWS_BUCKET_NAME=(str, ""),
    COMMISSION_RATE_DEFAULT=(float, 10.0),
    THROTTLE_RATE_ANON=(str, "60/min"),
    THROTTLE_RATE_USER=(str, "1000/min"),
    LOG_LEVEL=(str, "INFO"),
    AGENT_INVITE_URL=(str, "https://app.transbooking.bf/agents/invitation"),
    AGENT_INVITE_MAX_AGE_HOURS=(int, 48),
    PAYMENT_PROVIDER=(str, "mock"),
    PAYMENT_SANDBOX=(bool, True),
    PAYMENT_SANDBOX_OTP=(str, "123456"),
    PAYMENT_SANDBOX_FORCE_FAILURE=(bool, False),
    PAYMENT_API_BASE_URL=(str, ""),
    PAYMENT_API_KEY=(str, ""),
    PAYMENT_API_SECRET=(str, ""),
    PAYMENT_API_MERCHANT_ID=(str, ""),
    PAYMENT_SANDBOX_FLOW=(str, "otp"),
    PAYMENT_WEBHOOK_SECRET=(str, ""),
    SITE_BASE_URL=(str, "http://localhost:8000"),
    OTP_CODE_LENGTH=(int, 6),
    OTP_EXPIRY_MINUTES=(int, 5),
    OTP_MAX_ATTEMPTS=(int, 3),
    OTP_RESEND_INTERVAL_SECONDS=(int, 30),
)

environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[
    "localhost", "127.0.0.1", '192.168.100.86',
    '192.168.11.105', '192.168.1.75','192.168.1.68'
    ])

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "corsheaders",
    "django_filters",
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
]

LOCAL_APPS = [
    "apps.core",
    "apps.users",
    "apps.companies",
    "apps.subscriptions",
    "apps.geography",
    "apps.vehicles",
    "apps.routes",
    "apps.trips",
    "apps.bookings",
    "apps.payments",
    "apps.parcels",
    "apps.claims",
    "apps.reviews",
    "apps.speed_reports",
    "apps.messaging",
    "apps.notifications",
    "apps.sync",
    "apps.dashboard",
    # Site public rendu cote serveur : vitrine, recherche et tunnel de
    # reservation. Consomme les services du domaine, jamais l'API par HTTP.
    "apps.web",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.web.context_processors.notifications_non_lues",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": env.db("DATABASE_URL"),
}

AUTH_USER_MODEL = "users.User"

# Connexion voyageur par session (site public rendu cote serveur, distincte
# du JWT utilise par l'API mobile). Les vues de l'espace voyageur portent
# @login_required.
LOGIN_URL = "web:connexion"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Africa/Ouagadougou"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Feuille de style du systeme de design, servie telle quelle : les
# maquettes validees SONT ce fichier, il n'y a pas de traduction.
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    # Défaut sûr : tout endpoint exige l'authentification sauf override explicite
    # (jamais de AllowAny silencieux — cf. docs/specs/security.md).
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
    ],
    "DEFAULT_PAGINATION_CLASS": "utils.pagination.StandardPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": env("THROTTLE_RATE_ANON"),
        "user": env("THROTTLE_RATE_USER"),
    },
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "utils.exceptions.custom_exception_handler",
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
}

SPECTACULAR_SETTINGS = {
    "TITLE": "TransBooking BF API",
    "DESCRIPTION": (
        "API de la plateforme SaaS de gestion du transport interurbain au Burkina Faso "
        "(réservations, colis, paiements Mobile Money, mode hors ligne)."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "SIGNING_KEY": env("JWT_SECRET"),
    "AUTH_HEADER_TYPES": ("Bearer",),
}

CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS",
    default=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
)

REDIS_URL = env("REDIS_URL")
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60

# Cache Redis partagé entre workers (throttling DRF + cache_page des dashboards).
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("CACHE_URL", default=REDIS_URL),
    }
}

# Rate limiting (django-ratelimit) s'appuie sur le cache « default » (cf. security.md §4).
RATELIMIT_USE_CACHE = "default"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": env("LOG_LEVEL"),
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": env("LOG_LEVEL"),
            "propagate": False,
        },
    },
}

SMS_PROVIDER = env("SMS_PROVIDER")
SMS_API_KEY = env("SMS_API_KEY")
SMS_SENDER_ID = env("SMS_SENDER_ID")
STORAGE_BACKEND = env("STORAGE_BACKEND")
AWS_BUCKET_NAME = env("AWS_BUCKET_NAME")
COMMISSION_RATE_DEFAULT = env("COMMISSION_RATE_DEFAULT")

# Invitation d'agent par le company admin : base du lien envoye par SMS et duree
# de validite du jeton signe (cf. PROMPT_SUP A4).
AGENT_INVITE_URL = env("AGENT_INVITE_URL")
AGENT_INVITE_MAX_AGE_HOURS = env("AGENT_INVITE_MAX_AGE_HOURS")

# --------------------------------------------------------------------------- #
# Paiement Mobile Money par OTP (cf. PROMPT_SUP partie B)
# --------------------------------------------------------------------------- #
# Fournisseur utilise hors sandbox : cle du registre apps.payments.providers
# (`orange_money`, `moov_money`, `coris_money`, `telecel_money`) ou `mock`.
PAYMENT_PROVIDER = env("PAYMENT_PROVIDER")
# En sandbox : OTP de test fixe, aucun debit reel, aucun appel operateur.
PAYMENT_SANDBOX = env("PAYMENT_SANDBOX")
PAYMENT_SANDBOX_OTP = env("PAYMENT_SANDBOX_OTP")
PAYMENT_SANDBOX_FORCE_FAILURE = env("PAYMENT_SANDBOX_FORCE_FAILURE")
# Parcours simule : « otp » (defaut, comportement historique) ou « redirect »,
# pour developper le tunnel Orange Money direct avant les identifiants
# marchands. Sans effet hors sandbox.
PAYMENT_SANDBOX_FLOW = env("PAYMENT_SANDBOX_FLOW")

# Secret partage servant a verifier la signature HMAC des notifications
# d'operateur. Sans lui, aucune notification n'est acceptee : c'est voulu.
PAYMENT_WEBHOOK_SECRET = env("PAYMENT_WEBHOOK_SECRET")

# Racine publique du site, pour construire les URL de retour et de
# notification transmises a l'operateur.
SITE_BASE_URL = env("SITE_BASE_URL")

# Identifiants de l'agregateur Mobile Money : JAMAIS en dur, uniquement via
# l'environnement (cf. security.md §« Secrets »). Vides tant que le contrat
# agregateur n'est pas signe.
PAYMENT_API_BASE_URL = env("PAYMENT_API_BASE_URL")
PAYMENT_API_KEY = env("PAYMENT_API_KEY")
PAYMENT_API_SECRET = env("PAYMENT_API_SECRET")
PAYMENT_API_MERCHANT_ID = env("PAYMENT_API_MERCHANT_ID")

# Cycle de vie d'un OTP de paiement : 6 chiffres, 5 min, 3 tentatives, 1 renvoi/30 s.
OTP_CODE_LENGTH = env("OTP_CODE_LENGTH")
OTP_EXPIRY_MINUTES = env("OTP_EXPIRY_MINUTES")
OTP_MAX_ATTEMPTS = env("OTP_MAX_ATTEMPTS")
OTP_RESEND_INTERVAL_SECONDS = env("OTP_RESEND_INTERVAL_SECONDS")
