# 🎯 OpenCap API

[![Python Version](https://img.shields.io/badge/python-3.7+-blue.svg)](https://www.python.org/downloads/)
[![Django Version](https://img.shields.io/badge/django-3.1.14+-green.svg)](https://www.djangoproject.com/)
[![License](https://img.shields.io/badge/license-APACHE_2.0-blue.svg)](LICENSE.md)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/opencap-org/opencap-api/pulls)

> Backend API for OpenCap - The open-source platform for biomechanical motion capture and gait analysis using mobile devices.

## 📖 Table of Contents

- [Overview](#overview)
- [Workflow](#workflow)
- [Getting Started](#getting-started)
- [API Documentation](#api-documentation)
- [Development](#development)
- [Testing](#testing)
- [Internationalization](#internationalization)
- [Deployment](#deployment)
- [Contributing](#contributing)
- [License](#license)

## 🔭 Overview

OpenCap is an open source biomechanical motion capture platform that leverages iOS devices to capture and analyze human movement. This repository contains the Django-based backend API that orchestrates the entire workflow, from session management to video processing and biomechanical analysis.

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

- Python 3.7+
- [gettext](https://www.gnu.org/software/gettext/) (for internationalization)

### Installation

1. Clone the repository:
```bash
git clone https://github.com/opencap-org/opencap-api.git
cd opencap-api
```

2. Create and activate a conda environment:
```bash
conda create -n opencap python=3.7
conda activate opencap
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Create environment variables file:
```bash
touch .env
# Edit .env with your credentials
```

5. Start the development server:
```bash
python manage.py runserver
```

The API will be available at `http://localhost:8000/` by default.

## 📚 API Documentation

### Interactive Docs

Once the server is running, access the auto-generated documentation:

- **Swagger UI**: `http://localhost:8000/docs/`
- **ReDoc**: `http://localhost:8000/redocs/`

## 💻 Development

### Adding New Fields to the Data Model

1. Update models in `mcserver/models.py`:
```python
class YourModel(models.Model):
    new_field = models.CharField(max_length=255)
```

2. Create migration:
```bash
python manage.py makemigrations
```

3. Apply migration:
```bash
python manage.py migrate  # Careful: modifies database!
```

4. Update serializers in `mcserver/serializers.py`:
```python
class YourModelSerializer(serializers.ModelSerializer):
    class Meta:
        fields = [... 'new_field']
```

5. Potentially update `mcserver/admin.py`

### Running Tests

```bash
python manage.py test ./tests/
```

> **Note**: Some tests may be outdated and fail. Test `test_permissions.SessionsPermissionsTests` may fail on Windows but works on Ubuntu and macOS.

## 🌍 Internationalization

### Adding New Languages

Navigate to the `mcserver` folder:

1. Create translation files for a language:
```bash
django-admin makemessages -l <language-code>
# Example: django-admin makemessages -l es
```

2. Compile translation messages:
```bash
django-admin compilemessages
```

> **Note**: Make sure gettext is installed and your IDE/Terminal is restarted after installation.

## 🚢 Deployment

### Production Deployment Steps

1. Pull the latest code:
```bash
git pull origin main
```

2. Update dependencies:
```bash
pip install -r requirements.txt
```

3. Run migrations:
```bash
python manage.py migrate
```

4. Restart the application server (Gunicorn/uWSGI/etc.)

## 🧪 Testing

### Test

Run tests with:

```bash
run manage.py test ./tests/
```

### API Testing

Use the Swagger UI at `/docs/` or use tools like curl:

```bash
# Create a session
curl -X POST http://localhost:8000/sessions/ \
  -H "Authorization: Token your_token" \
  -H "Content-Type: application/json" \
  -d '{"subject": "subject_uuid"}'
```

## 🤝 Contributing

We welcome contributions! Please submit an [Issue](https://github.com/opencap-org/opencap-api/issues) or create a [PR](https://github.com/opencap-org/opencap-api/pulls).

### Development Workflow

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request


## 📄 License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE.md) file for details.

