import os
from django.conf import settings
from celery import shared_task
from django.utils import timezone
from datetime import timedelta

from mcserver.models import DownloadLog
from mcserver.zipsession_v2 import (
    SessionDirectoryConstructor,
    SubjectDirectoryConstructor,
    zipdir
)


@shared_task
def cleanup_trashed_sessions():
    from .models import Session
    now = timezone.now()
    Session.objects.filter(
        trashed=True,
        trashed_at__lt=now-timedelta(days=settings.TRASHED_OBJECTS_CLEANUP_DAYS)).delete()


@shared_task
def cleanup_trashed_trials():
    from .models import Trial
    now = timezone.now()
    Trial.objects.filter(
        trashed=True,
        trashed_at__lt=now-timedelta(days=settings.TRASHED_OBJECTS_CLEANUP_DAYS)).delete()


@shared_task(bind=True)
def download_session_archive(self, session_id, user_id=None):
    """ This task is responsible for asynchronous session archive download.
        If user_id is None, the public session download occurred.
    """
    session_dir_path = SessionDirectoryConstructor().build(session_id)
    session_zip_path = zipdir(session_dir_path)
    with open(session_zip_path, "rb") as archive:
        log = DownloadLog.objects.create(task_id=str(self.request.id), user_id=user_id)
        log.media.save(os.path.basename(session_zip_path), archive)
        os.remove(session_zip_path)


@shared_task(bind=True)
def download_subject_archive(self, subject_id, user_id):
    """ This task is responsible for asynchronous subject archive download
    """
    subject_dir_path = SubjectDirectoryConstructor().build(subject_id)
    subject_zip_path = zipdir(subject_dir_path)
    with open(subject_zip_path, "rb") as archive:
        log = DownloadLog.objects.create(task_id=str(self.request.id), user_id=user_id)
        log.media.save(os.path.basename(subject_zip_path), archive)
        os.remove(subject_zip_path)


@shared_task
def cleanup_archives():
    """ This task deletes DownloadLogs and related files
        that older than ARCHIVE_CLEANUP_DAYS
    """
    now = timezone.now()
    for log in DownloadLog.objects.filter(
        created_at__lt=now - timedelta(days=settings.ARCHIVE_CLEANUP_DAYS)
    ):
        log.media.delete(save=False)
        log.delete()
