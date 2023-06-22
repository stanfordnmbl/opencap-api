from unittest import mock

from django.test import TestCase, override_settings

from mcserver.models import User, DownloadLog, AnalysisFunction, AnalysisResult
from mcserver.tasks import (
    download_session_archive,
    download_subject_archive,
    invoke_aws_lambda_function
)
from mcserver.zipsession_v2 import (
    SessionDirectoryConstructor, SubjectDirectoryConstructor
)


@override_settings(task_always_eager=True)
class TasksTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="johndoe",
            email="johndoe@email.com",
            first_name="John",
            last_name="Dou",
            password="testpass"
        )

    @mock.patch("mcserver.tasks.zipdir")
    @mock.patch.object(SessionDirectoryConstructor, "build")
    def test_download_session_archive_creates_archive_and_logs_action(
        self, mock_dir_builder, mock_zipdir
    ):
        mock_zipdir.return_value = "archive.zip"
        mock_dir_builder.return_value = "archive"
        before_logs = DownloadLog.objects.count()
        task = download_session_archive.delay("dummy-session-id", self.user.id)
        after_logs = DownloadLog.objects.count()
        self.assertEqual(after_logs, before_logs + 1)

        log = DownloadLog.objects.last()
        self.assertEqual(log.task_id, task.id)
        self.assertEqual(log.user, self.user)
        self.assertEqual(log.media_path, "archive.zip")

        mock_dir_builder.assert_called_once_with("dummy-session-id")
        mock_zipdir.assert_called_once_with("archive")

    @mock.patch("mcserver.tasks.zipdir")
    @mock.patch.object(SessionDirectoryConstructor, "build")
    def test_download_session_archive_creates_archive_and_logs_action_for_anon_user(
        self, mock_dir_builder, mock_zipdir
    ):
        mock_zipdir.return_value = "archive.zip"
        mock_dir_builder.return_value = "archive"
        before_logs = DownloadLog.objects.count()
        task = download_session_archive.delay("dummy-session-id", None)
        after_logs = DownloadLog.objects.count()
        self.assertEqual(after_logs, before_logs + 1)

        log = DownloadLog.objects.last()
        self.assertEqual(log.task_id, task.id)
        self.assertIsNone(log.user)
        self.assertEqual(log.media_path, "archive.zip")

        mock_dir_builder.assert_called_once_with("dummy-session-id")
        mock_zipdir.assert_called_once_with("archive")
    
    @mock.patch("mcserver.tasks.zipdir")
    @mock.patch.object(SubjectDirectoryConstructor, "build")
    def test_download_subject_archive_creates_archive_and_logs_action(
        self, mock_dir_builder, mock_zipdir
    ):
        mock_zipdir.return_value = "archive.zip"
        mock_dir_builder.return_value = "archive"
        before_logs = DownloadLog.objects.count()
        task = download_subject_archive.delay("dummy-subject-id", self.user.id)
        after_logs = DownloadLog.objects.count()
        self.assertEqual(after_logs, before_logs + 1)

        log = DownloadLog.objects.last()
        self.assertEqual(log.task_id, task.id)
        self.assertEqual(log.user, self.user)
        self.assertEqual(log.media_path, "archive.zip")

        mock_dir_builder.assert_called_once_with("dummy-subject-id")
        mock_zipdir.assert_called_once_with("archive")
    
    @mock.patch("requests.post")
    def test_invoke_aws_lambda_function_commits_analysis_result(
        self, mock_post_request
    ):
        response_data, status_code = {
            'message': 'Maximal center of mass vertical position: 1.07 m'
        }, 200
        mock_post_request.return_value.status_code = status_code
        mock_post_request.return_value.json.return_value = response_data
        function = AnalysisFunction.objects.create(title='func 0', description='desc 0')
        data = {'session_id': 'dummy-session-id', 'trial_names': ['test']}
        before_results = AnalysisResult.objects.count()
        task = invoke_aws_lambda_function.delay(self.user.id, function.id, data)
        after_results = AnalysisResult.objects.count()
        result = AnalysisResult.objects.last()
        self.assertEqual(result.user, self.user)
        self.assertEqual(result.function, function)
        self.assertEqual(result.data, data)
        self.assertEqual(result.status, status_code)
        self.assertEqual(result.result, response_data)
