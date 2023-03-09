from celery import Celery
import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mcserver.settings')

app = Celery('celeryapp')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
