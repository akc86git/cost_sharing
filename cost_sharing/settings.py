"""
Настройки Django-проекта cost_sharing (сервис «Разделение затрат»).

СУБД — SQLite, связь с Python-проектом реализована через ORM Django.
Путь к файлу базы можно переопределить переменной окружения
COST_SHARING_DB_PATH (удобно для тестов и копий проекта).
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# ВНИМАНИЕ: ключ сгенерирован для учебного/демонстрационного проекта.
# Для боевого окружения сгенерируйте свой:
#   python -c "import secrets; print(secrets.token_urlsafe(50))"
SECRET_KEY = 'oTaS-BIc7xXCQkzdNaA3aVXHds4-I5yko1GLjuJ6CBAz75pptFjNVvkB9WVW7_jA8KA'

DEBUG = True  # режим разработки; в продакшене выключить

ALLOWED_HOSTS = ['localhost', '127.0.0.1', '[::1]', 'testserver']


INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'core',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'cost_sharing.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'cost_sharing.wsgi.application'


# СУБД SQLite: именно здесь создаётся схема из 4 таблиц
# people / events / purchases / debtors (см. core/models.py).
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.environ.get('COST_SHARING_DB_PATH', str(BASE_DIR / 'db.sqlite3')),
    }
}


AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# Локализация интерфейса под русскоязычного пользователя.
LANGUAGE_CODE = 'ru-ru'
TIME_ZONE = 'Asia/Yekaterinburg'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
