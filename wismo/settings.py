"""Django settings for the WISMO MVP backend foundation."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "django-insecure-wismo-foundation")
DEBUG = os.getenv("DJANGO_DEBUG", "True") == "True"
ALLOWED_HOSTS = [host for host in os.getenv("DJANGO_ALLOWED_HOSTS", "").split(",") if host]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "accounts",
    "consents",
    "chat",
    "runtime",
    "llm_ops",
    "memory",
    "knowledge",
    "admin_config",
]

AUTH_USER_MODEL = "accounts.User"
DATABASE_ROUTERS = ["wismo.db_router.VectorRouter"]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
}

ROOT_URLCONF = "wismo.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "wismo.wsgi.application"
ASGI_APPLICATION = "wismo.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_APP_NAME", "wismo_app"),
        "USER": os.getenv("DB_APP_USER", "wismo"),
        "PASSWORD": os.getenv("DB_APP_PASSWORD", ""),
        "HOST": os.getenv("DB_APP_HOST", "127.0.0.1"),
        "PORT": os.getenv("DB_APP_PORT", "5432"),
    },
    "vector": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_VECTOR_NAME", "wismo_vector"),
        "USER": os.getenv("DB_VECTOR_USER", "wismo_vec"),
        "PASSWORD": os.getenv("DB_VECTOR_PASSWORD", ""),
        "HOST": os.getenv("DB_VECTOR_HOST", "127.0.0.1"),
        "PORT": os.getenv("DB_VECTOR_PORT", "5433"),
    },
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 6}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Europe/Helsinki"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_HTTPONLY = True

EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "True") == "True"
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_TIMEOUT = 10
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "noreply@wismo.app")

WISMO_OTP_LENGTH = int(os.getenv("WISMO_OTP_LENGTH", "6"))
WISMO_OTP_TTL_MINUTES = int(os.getenv("WISMO_OTP_TTL_MINUTES", "30"))
WISMO_OTP_RESEND_COOLDOWN_SECONDS = int(os.getenv("WISMO_OTP_RESEND_COOLDOWN_SECONDS", "60"))
WISMO_OTP_RESEND_CAP = int(os.getenv("WISMO_OTP_RESEND_CAP", "5"))
WISMO_OTP_EMAIL_SUBJECT = os.getenv("WISMO_OTP_EMAIL_SUBJECT", "Your WISMO verification code")
WISMO_GOOGLE_CLIENT_ID = os.getenv("WISMO_GOOGLE_CLIENT_ID", "")
