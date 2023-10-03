import os
import json
import requests
from http import HTTPStatus
from django.conf import settings
from django.core.files import File
from django.core.files.base import ContentFile
from celery import shared_task
from django.utils import timezone
from datetime import timedelta

from mcserver.models import (
    DownloadLog,
    Session,
    Result,
    Trial,
    AnalysisFunction,
    AnalysisResult,
    AnalysisResultState,
    AnalysisDashboardTemplate,
    AnalysisDashboard,
)
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


@shared_task
def delete_pingdom_sessions():
    """ This task deletes all Session's related to pingdom user
    """
    Session.objects.filter(user__username="pingdom").delete()


@shared_task(bind=True)
def invoke_aws_lambda_function(self, user_id, function_id, data):
    function = AnalysisFunction.objects.get(id=function_id)
    analysis_result = AnalysisResult(
        task_id=str(self.request.id),
        function=function,
        user_id=user_id,
        data=data,
        state=AnalysisResultState.PENDING
    )
    analysis_result.save()

    try:
        response = requests.post(
            function.url,
            json={'body': json.dumps(data)} if function.local_run else data,  # AWS RIE works different with passing parameters
            headers={'Content-Type': 'application/json; charset=utf-8'}
        )
        function_response = response.json()
        # print(f'function_response={function_response}')

        if function.local_run:
            # AWS RIE support
            function_response = function_response['body']

        analysis_result.status = response.status_code
        analysis_result.state = AnalysisResultState.SUCCESSFULL
        if response.status_code >= HTTPStatus.BAD_REQUEST.value:
            analysis_result.state = AnalysisResultState.FAILED
    except (ValueError, requests.RequestException) as e:
        function_response = {'error': str(e)}
        analysis_result.status = HTTPStatus.INTERNAL_SERVER_ERROR.value
        analysis_result.state = AnalysisResultState.FAILED

    if analysis_result.state == AnalysisResultState.SUCCESSFULL:
        trial = Trial.objects.get(
            name=data['specific_trial_names'][0],
            session_id=data['session_id']
        )

        json_path = f'{trial.id}-{function_id}-analysis_result.json'
        result = Result.objects.get_or_create(trial=trial, tag=function.title)[0]
        result.media.save(
            json_path,
            ContentFile(json.dumps(function_response).encode('utf-8'))
        )

        analysis_result.result = result
    else:
        analysis_result.response = function_response
    analysis_result.save(update_fields=['result', 'status', 'state', 'response'])

    # Crreate analysis dashboard if available
    try:
        AnalysisDashboard.objects.get(user_id=user_id, function_id=function_id)
    except AnalysisDashboard.DoesNotExist:
        dashboard_template = AnalysisDashboardTemplate.objects.filter(function_id=function_id).first()
        if dashboard_template:
            AnalysisDashboard.objects.create(
                title=dashboard_template.title,
                layout=dashboard_template.layout,
                user_id=user_id,
                function_id=function_id,
                template=dashboard_template
            )

