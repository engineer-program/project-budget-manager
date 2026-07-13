import os
import time
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


BASE_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv(PROJECT_ROOT / ".env")

APP_TIME_ZONE = os.getenv("TZ", "Europe/Moscow")
os.environ["TZ"] = APP_TIME_ZONE
if hasattr(time, "tzset"):
    time.tzset()


def _logging_time_converter(timestamp: float):
    return datetime.fromtimestamp(timestamp, ZoneInfo(APP_TIME_ZONE)).timetuple()


logging.Formatter.converter = staticmethod(_logging_time_converter)


def _patch_django_server_log_time() -> None:
    # Django's runserver passes a preformatted server_time to django.server logs.
    # On Windows it uses time.localtime(), which ignores TZ, so patch it once here.
    try:
        from django.core.servers.basehttp import WSGIRequestHandler
    except Exception:
        return

    def _project_log_date_time_string(self):
        now = datetime.now(ZoneInfo(APP_TIME_ZONE))
        return "%02d/%3s/%04d %02d:%02d:%02d" % (
            now.day,
            self.monthname[now.month],
            now.year,
            now.hour,
            now.minute,
            now.second,
        )

    WSGIRequestHandler.log_date_time_string = _project_log_date_time_string


_patch_django_server_log_time()


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-secret-key")
DEBUG = os.getenv("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = [host for host in os.getenv("DJANGO_ALLOWED_HOSTS", "*").split(",") if host]
CSRF_TRUSTED_ORIGINS = [host for host in os.getenv("CSRF_TRUSTED_ORIGINS", "*").split(",") if host]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.employees.apps.EmployeesConfig",
    "apps.projects.apps.ProjectsConfig",
    "apps.reference.apps.ReferenceConfig",
    "apps.finance.apps.FinanceConfig",
    "apps.redmine_sync.apps.RedmineSyncConfig",
    "apps.audit.apps.AuditConfig",
]

MIDDLEWARE = [
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
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


def _build_default_database():
    engine = os.getenv("DB_ENGINE", "mysql").lower()
    if engine == "mysql":
        return {
            "ENGINE": "django.db.backends.mysql",
            "NAME": os.getenv("DB_NAME", "budget_manager"),
            "USER": os.getenv("DB_USER", "budget_user"),
            "PASSWORD": os.getenv("DB_PASSWORD", "budget_password"),
            "HOST": os.getenv("DB_HOST", "db"),
            "PORT": os.getenv("DB_PORT", "3306"),
            "OPTIONS": {
                "charset": "utf8mb4",
                "init_command": f"SET time_zone = '{os.getenv('DB_TIME_ZONE', '+03:00')}'",
            },
        }
    return {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }


DATABASES = {
    "default": _build_default_database(),
    "redmine": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.getenv("REDMINE_DB_NAME", ""),
        "USER": os.getenv("REDMINE_DB_USER", ""),
        "PASSWORD": os.getenv("REDMINE_DB_PASSWORD", ""),
        "HOST": os.getenv("REDMINE_DB_HOST", ""),
        "PORT": os.getenv("REDMINE_DB_PORT", "3306"),
        "OPTIONS": {
            "charset": "utf8mb4",
        },
    },
}

DATABASE_ROUTERS = ["config.db_routers.RedmineRouter"]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = APP_TIME_ZONE
USE_I18N = True
USE_TZ = _env_bool("DJANGO_USE_TZ", default=False)

if not USE_TZ and not hasattr(time, "tzset"):
    # Windows does not apply TZ to datetime.now(); keep auto_now/auto_now_add in project local time.
    from django.utils import timezone as django_timezone

    def _project_local_now():
        return datetime.now(ZoneInfo(TIME_ZONE)).replace(tzinfo=None)

    django_timezone.now = _project_local_now

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

DATA_UPLOAD_MAX_NUMBER_FIELDS = int(os.getenv("DATA_UPLOAD_MAX_NUMBER_FIELDS", "10000"))

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"

# Sessions are intentionally short-lived because the app contains financial data.
# Django invalidates old sessions automatically after a password hash change.
SESSION_COOKIE_AGE = int(os.getenv("SESSION_COOKIE_AGE", str(60 * 60 * 2)))
SESSION_SAVE_EVERY_REQUEST = _env_bool("SESSION_SAVE_EVERY_REQUEST", default=True)
SESSION_EXPIRE_AT_BROWSER_CLOSE = _env_bool("SESSION_EXPIRE_AT_BROWSER_CLOSE", default=True)
