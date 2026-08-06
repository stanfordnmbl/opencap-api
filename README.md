# 🎯 OpenCap API

[![Python Version](https://img.shields.io/badge/python-3.7-blue.svg)](https://www.python.org/downloads/)
[![Django Version](https://img.shields.io/badge/django-3.1.14-green.svg)](https://www.djangoproject.com/)
[![License](https://img.shields.io/badge/license-APACHE_2.0-blue.svg)](LICENSE.md)

> Django backend for [OpenCap](https://app.opencap.ai).

## 🔭 Overview

The API serves both the webapp and the iOS app. It stores sessions, subjects, trials, and videos, and queues recordings for the processing pipeline. Background work (archive builds, session downloads, scheduled cleanup) runs in Celery workers backed by Redis, not in the web process.

## 🔄 Workflow

1. User enters the website (app.opencap.ai)
2. The website calls the backend and creates a session
3. The session generates a QR code displayed in the webapp
4. User scans the code with the iOS app. App uses the code to connect directly to the backend
5. User clicks record in the webapp -> this invokes backend to change session state to recording
6. iPhones pull session state every 1sec and see it's in 'recording' state. They start recording
7. User clicks stop recording changing state to 'upload'
8. iPhones upload the videos
9. When all videos are uploaded, backend changes the state to processing and adds videos to the queue for processing
10. Video processing pipeline pools sessions in 'processing' state and processes them
11. After processing, results are sent to the backend and the backend changes its state to 'done'

## 🚀 Getting Started

### Prerequisites

Beyond `requirements.txt`, which covers pip packages only:

- **Python 3.7** — the pinned dependencies do not install on newer versions
- **PostgreSQL** — `mcserver/settings.py` always uses the `postgresql` backend

Depending on the work:

- **Redis** — to run Celery. The API serves requests without it, but asynchronous work (session downloads, cleanup jobs) never runs
- **[gettext](https://www.gnu.org/software/gettext/)** — to compile translations

### Installation

```bash
git clone https://github.com/opencap-org/opencap-api.git
cd opencap-api
conda create -n opencap python=3.7
conda activate opencap
pip install -r requirements.txt
```

### Configuration

Create a `.env` file in the repository root. The required variables are the `config(...)` calls in `mcserver/settings.py` that have no default; ask a maintainer for development values.

### Running locally

```bash
python manage.py migrate
python manage.py runserver
```

The API is served at `http://localhost:8000/`.

Asynchronous work needs Celery processes running alongside the server:

```bash
celery -A mcserver worker -l info  # session downloads, archive builds
celery -A mcserver beat -l info    # scheduled jobs
```

## 📚 API Documentation

With the server running:

- **Swagger UI**: `http://localhost:8000/docs/`
- **ReDoc**: `http://localhost:8000/redocs/`

Routes are registered in `mcserver/urls.py`. Most come from the viewsets in `mcserver/views.py`, which also add a number of custom actions on top of the standard REST routes. Requests authenticate with a DRF token, or a session cookie for the browsable API.

## 💻 Development

### Adding new fields to the data model

1. Add the field to the model in `mcserver/models.py`
2. Run `python manage.py makemigrations`
3. Run `python manage.py migrate` — careful, this modifies the database
4. Add the field to `mcserver/serializers.py` if the API should expose it
5. Update `mcserver/admin.py` if it should appear in the admin

### Running tests

Tests need a valid `.env` and a database they are allowed to create.

```bash
python manage.py test tests                   # whole suite
python manage.py test tests.test_permissions  # one module
```

> **Note**: Some tests may be outdated and fail. Test `test_permissions.SessionsPermissionsTests` may fail on Windows but works on Ubuntu and macOS.

## 🌍 Internationalization

See the [Django translation docs](https://docs.djangoproject.com/en/3.1/topics/i18n/translation/). This requires [gettext](https://www.gnu.org/software/gettext/) — restart your terminal or IDE after installing it.

From the `mcserver` folder:

```bash
django-admin makemessages -l es   # create or refresh files for a language
django-admin compilemessages      # compile them
```

## 🚢 Deployment

Deployment is automated with GitHub Actions. Each push builds `Dockerfile`, pushes the image to ECR, and forces a new ECS deployment.

| Branch | Workflow | Effect |
| --- | --- | --- |
| `dev` | `.github/workflows/ecr-dev.yml` | Builds `opencap/api-dev`; redeploys `api-server-dev`, `api-server-celery-dev`, `api-server-celery-beat-dev` in `opencap-api-cluster-dev` |
| `main` | `.github/workflows/ecr.yml` | Builds `opencap/api`; redeploys `api-server`, `api-server-celery`, `api-server-celery-beat` in `opencap-api-cluster` |

Two things are not automated:

- **Migrations.** If your change adds one, run `python manage.py migrate` against that environment's database after the deploy.
- **Environment variables.** New settings have to be added to the ECS task definitions; they are not read from this repository.

## 🤝 Contributing

1. Open an [issue](https://github.com/opencap-org/opencap-api/issues) describing the change first
2. Branch off `dev`
3. Open a pull request against `dev`, referencing the issue

`dev` is the integration branch. Changes reach production through a `dev` → `main` pull request. Since a push to `main` deploys production immediately, work should not target it directly.

## 📄 License

Apache License 2.0 — see [LICENSE.md](LICENSE.md) for details.
