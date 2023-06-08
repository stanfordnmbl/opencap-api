from unittest import mock

from django.test import TestCase, override_settings

from mcserver.models import User, DownloadLog
from mcserver.tasks import (
    download_session_archive, download_subject_archive
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
