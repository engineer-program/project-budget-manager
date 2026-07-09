# Project Budget Manager

Веб-приложение для управления проектными бюджетами, зарплатами сотрудников, премиями, компенсациями, доходами, расходами и отчётностью по проектам.

Приложение синхронизирует справочные данные и трудозатраты из Easy Redmine, а финансовые данные хранит в отдельной базе данных MySQL.

## Основные возможности

- Авторизация пользователей через Django.
- Управление зарплатами сотрудников по месяцам.
- Ведение стартовых бюджетов проектов.
- Ведение доходов и расходов проектов.
- Древовидное отображение проектов и подпроектов.
- Расчётные отчёты по сотрудникам.
- Расчётные отчёты по проектам.
- Фильтрация сотрудников по группам, статусу и датам трудоустройства/увольнения.
- Фильтрация проектов по статусу.
- Синхронизация данных из Easy Redmine.
- Логирование запусков синхронизации.
- История пользовательских изменений.
- Экспорт таблиц в Excel и PDF.
- Docker-развёртывание с Gunicorn и Nginx.

## Стек технологий

- Python 3.14
- Django 6.1
- MySQL
- Docker Compose
- Tabulator.js
- HTML/CSS/JavaScript
- Gunicorn
- Nginx

## Структура проекта

```text
project-budget-manager/
├── backend/
│   ├── apps/
│   │   ├── audit/
│   │   ├── common/
│   │   ├── employees/
│   │   ├── finance/
│   │   ├── projects/
│   │   ├── redmine_sync/
│   │   └── reference/
│   ├── config/
│   ├── static/
│   ├── templates/
│   ├── Dockerfile
│   ├── manage.py
│   └── pyproject.toml
├── docker/
│   └── nginx/
│       └── default.conf
├── design/
│   └── docs/
├── var/
│   └── sync_logs/
├── docker-compose.yml
└── README.md
```

## Переменные окружения

Приложение использует `.env` в корне проекта.

Пример:

```env
DJANGO_SECRET_KEY=change-me
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,finances.example.ru
DJANGO_SETTINGS_MODULE=config.settings.prod

DB_ENGINE=mysql
DB_NAME=project_finance
DB_USER=project_user
DB_PASSWORD=project_password
DB_HOST=127.0.0.1
DB_PORT=3306
DB_TIME_ZONE=+03:00

REDMINE_DB_NAME=easy
REDMINE_DB_USER=redmine_readonly
REDMINE_DB_PASSWORD=redmine_password
REDMINE_DB_HOST=127.0.0.1
REDMINE_DB_PORT=3306

TZ=Europe/Moscow
DJANGO_USE_TZ=0

DATA_UPLOAD_MAX_NUMBER_FIELDS=10000

SESSION_COOKIE_AGE=7200
SESSION_SAVE_EVERY_REQUEST=1
SESSION_EXPIRE_AT_BROWSER_CLOSE=1
```

Важно: файл `.env` содержит секреты и не должен попадать в Git.

## Локальный запуск без Docker

Создать виртуальное окружение:

```bash
python -m venv .venv
```

Активировать окружение:

```bash
source .venv/bin/activate
```

Для Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Установить зависимости:

```bash
pip install --upgrade pip
pip install .
```

Перейти в директорию backend:

```bash
cd backend
```

Проверить Django-проект:

```bash
python manage.py check
```

Применить миграции:

```bash
python manage.py migrate
```

Создать суперпользователя:

```bash
python manage.py createsuperuser
```

Запустить сервер разработки:

```bash
python manage.py runserver
```

Приложение будет доступно по адресу:

```text
http://127.0.0.1:8000/
```

## Запуск через Docker

Собрать контейнеры:

```bash
docker compose build
```

Применить миграции:

```bash
docker compose run --rm backend python manage.py migrate
```

Собрать статические файлы:

```bash
docker compose run --rm backend python manage.py collectstatic --noinput
```

Создать суперпользователя:

```bash
docker compose run --rm backend python manage.py createsuperuser
```

Запустить приложение:

```bash
docker compose up -d
```

Посмотреть статус контейнеров:

```bash
docker compose ps
```

Посмотреть логи backend:

```bash
docker compose logs -f backend
```

## Production-запуск

Для production-развёртывания используется `docker-compose.yml`.

Сборка:

```bash
docker compose -f docker-compose.yml build
```

Миграции:

```bash
docker compose -f docker-compose.yml run --rm backend python manage.py migrate
```

Сборка статики:

```bash
docker compose -f docker-compose.yml run --rm backend python manage.py collectstatic --noinput
```

Запуск:

```bash
docker compose -f docker-compose.yml up -d
```

Проверка состояния:

```bash
docker compose -f docker-compose.yml ps
```

Проверка логов:

```bash
docker compose -f docker-compose.yml logs -f backend
docker compose -f docker-compose.yml logs -f nginx
```

Проверка Django:

```bash
docker compose -f docker-compose.yml exec backend python manage.py check
```

## Синхронизация с Easy Redmine

Синхронизация выполняется модулем `redmine_sync`.

Доступные команды:

```bash
python manage.py sync_redmine --mode incremental
python manage.py sync_redmine --mode window
python manage.py sync_redmine --mode full
```

В Docker:

```bash
docker compose -f docker-compose.yml exec backend python manage.py sync_redmine --mode window
```

Режимы синхронизации:

| Режим | Назначение |
| --- | --- |
| `incremental` | Быстрая синхронизация новых записей трудозатрат по растущему `redmine_time_entry_id` |
| `window` | Синхронизация записей за заданное окно времени, используется для ручного обновления и регулярной сверки |
| `full` | Полная синхронизация и сверка данных из Redmine |

Планировщик запускается отдельным Docker-сервисом:

```text
scheduler
```

## Логи синхронизации

Каждый запуск синхронизации фиксируется в базе данных и отдельном текстовом файле.

Файлы логов находятся в директории:

```text
var/sync_logs/
```

В Docker production эта директория монтируется как volume:

```yaml
./var/sync_logs:/var/sync_logs
```

В логах фиксируются:

- тип синхронизации;
- источник запуска;
- пользователь, запустивший синхронизацию;
- время начала и окончания;
- итоговая статистика;
- созданные, обновлённые, пропущенные и удалённые записи;
- изменения записей трудозатрат;
- проекты и сотрудники, помеченные удалёнными в Redmine;
- ошибки выполнения, если синхронизация завершилась неуспешно.

## Работа со статикой

Статические файлы Django собираются командой:

```bash
python manage.py collectstatic --noinput
```

В production static отдаётся через Nginx:

```nginx
location /static/ {
    alias /staticfiles/;
}
```

После изменения CSS, JS, изображений или favicon необходимо пересобрать static:

```bash
docker compose -f docker-compose.yml run --rm backend python manage.py collectstatic --noinput
docker compose -f docker-compose.yml restart nginx
```

## Работа с миграциями

Создать миграции:

```bash
python manage.py makemigrations
```

Применить миграции:

```bash
python manage.py migrate
```

В Docker:

```bash
docker compose -f docker-compose.yml run --rm backend python manage.py makemigrations
docker compose -f docker-compose.yml run --rm backend python manage.py migrate
```

## Обновление приложения на сервере

Перейти в директорию проекта:

```bash
cd /path/to/project-budget-manager
```

Получить новую версию кода:

```bash
git pull
```

Пересобрать контейнеры:

```bash
docker compose -f docker-compose.yml build
```

Применить миграции:

```bash
docker compose -f docker-compose.yml run --rm backend python manage.py migrate
```

Пересобрать статические файлы:

```bash
docker compose -f docker-compose.yml run --rm backend python manage.py collectstatic --noinput
```

Перезапустить сервисы:

```bash
docker compose -f docker-compose.yml up -d
```

Проверить логи:

```bash
docker compose -f docker-compose.yml logs --tail=100 backend
docker compose -f docker-compose.yml logs --tail=100 nginx
```

## Резервное копирование

Рекомендуется регулярно выполнять backup базы данных `project_finance`.

Пример для MySQL:

```bash
mysqldump -h DB_HOST -P DB_PORT -u DB_USER -p project_finance > backup_project_finance_$(date +%F_%H-%M).sql
```

Также рекомендуется сохранять директорию:

```text
var/sync_logs/
```

## Безопасность

Для production-режима рекомендуется:

- использовать `DJANGO_DEBUG=0`;
- использовать уникальный `DJANGO_SECRET_KEY`;
- ограничить `DJANGO_ALLOWED_HOSTS`;
- не хранить `.env` в Git;
- использовать HTTPS;
- ограничить доступ к MySQL;
- использовать отдельного read-only пользователя для базы Easy Redmine;
- регулярно делать backup базы данных;
- проверять логи синхронизации;
- не открывать наружу лишние Docker-порты.

## Полезные команды

Проверить контейнеры:

```bash
docker compose -f docker-compose.yml ps
```

Посмотреть backend-логи:

```bash
docker compose -f docker-compose.yml logs -f backend
```

Посмотреть Nginx-логи:

```bash
docker compose -f docker-compose.yml logs -f nginx
```

Зайти в контейнер backend:

```bash
docker compose -f docker-compose.yml exec backend bash
```

Выполнить Django shell:

```bash
docker compose -f docker-compose.yml exec backend python manage.py shell
```

Проверить настройки Django:

```bash
docker compose -f docker-compose.yml exec backend python manage.py check
```

Проверить доступные миграции:

```bash
docker compose -f docker-compose.yml exec backend python manage.py showmigrations
```

## Лицензия

Проект предназначен для внутреннего использования.
