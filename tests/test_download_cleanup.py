import os
import shutil
import tempfile
import zipfile
from unittest import mock

from django.conf import settings
from django.test import TestCase, override_settings

from mcserver.models import User, DownloadLog
from mcserver.tasks import download_session_archive, download_subject_archive
from mcserver.zipsession_v2 import (
    SessionDirectoryConstructor,
    SubjectDirectoryConstructor,
)

_TMP = tempfile.mkdtemp()


@override_settings(
    MEDIA_ROOT=_TMP,
    ARCHIVES_ROOT=os.path.join(_TMP, "archives"),
    DEFAULT_FILE_STORAGE="django.core.files.storage.FileSystemStorage",
    SENTRY_DSN="",
)
class DownloadArchiveCleanupTests(TestCase):
    """The download tasks must never leave their build dir / zip on the
    worker's ephemeral disk, otherwise it fills up and downloads break."""

    def setUp(self):
        self.user = User.objects.create_user(username="dl-user", password="pw")
        os.makedirs(settings.MEDIA_ROOT, exist_ok=True)

    def tearDown(self):
        for name in os.listdir(settings.MEDIA_ROOT):
            path = os.path.join(settings.MEDIA_ROOT, name)
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                os.remove(path)

    @staticmethod
    def _build_that_creates(dir_path):
        """A build() stand-in that actually writes a build dir on disk."""
        def _build(object_id):
            os.makedirs(dir_path, exist_ok=True)
            with open(os.path.join(dir_path, "payload.txt"), "w") as fh:
                fh.write("data")
            return dir_path
        return _build

    @staticmethod
    def _zip_that_succeeds(dir_path):
        """A zipdir() stand-in mirroring the real one: remove the source dir
        and produce a real zip under ARCHIVES_ROOT."""
        shutil.rmtree(dir_path)
        os.makedirs(settings.ARCHIVES_ROOT, exist_ok=True)
        zip_path = os.path.join(
            settings.ARCHIVES_ROOT, os.path.basename(dir_path) + ".zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("payload.txt", "data")
        return zip_path

    # --- session --------------------------------------------------------

    def test_session_build_dir_removed_when_zip_fails(self):
        build_dir = os.path.join(settings.MEDIA_ROOT, "OpenCapData_sess-1")
        with mock.patch.object(
            SessionDirectoryConstructor, "build",
            side_effect=self._build_that_creates(build_dir),
        ), mock.patch(
            "mcserver.tasks.zipdir",
            side_effect=OSError("No space left on device"),
        ):
            download_session_archive.apply(args=("sess-1", self.user.id))

        self.assertFalse(
            os.path.exists(build_dir),
            "build dir must be removed after a failed download",
        )
        self.assertEqual(DownloadLog.objects.count(), 0)

    def test_session_build_dir_and_zip_removed_on_success(self):
        build_dir = os.path.join(settings.MEDIA_ROOT, "OpenCapData_sess-2")
        expected_zip = os.path.join(
            settings.ARCHIVES_ROOT, "OpenCapData_sess-2.zip")
        with mock.patch.object(
            SessionDirectoryConstructor, "build",
            side_effect=self._build_that_creates(build_dir),
        ), mock.patch(
            "mcserver.tasks.zipdir", side_effect=self._zip_that_succeeds,
        ):
            download_session_archive.apply(args=("sess-2", self.user.id))

        self.assertFalse(os.path.exists(build_dir))
        self.assertFalse(
            os.path.exists(expected_zip), "local zip must be removed after upload")
        self.assertEqual(DownloadLog.objects.count(), 1)
        self.assertEqual(DownloadLog.objects.get().user, self.user)

    # --- subject --------------------------------------------------------

    def test_subject_build_dir_removed_when_zip_fails(self):
        build_dir = os.path.join(
            settings.MEDIA_ROOT, "OpenCapData_Subject_subj-1")
        with mock.patch.object(
            SubjectDirectoryConstructor, "build",
            side_effect=self._build_that_creates(build_dir),
        ), mock.patch(
            "mcserver.tasks.zipdir",
            side_effect=OSError("No space left on device"),
        ):
            download_subject_archive.apply(args=("subj-1", self.user.id))

        self.assertFalse(
            os.path.exists(build_dir),
            "build dir must be removed after a failed download",
        )
        self.assertEqual(DownloadLog.objects.count(), 0)
