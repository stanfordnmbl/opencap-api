import os
import json
import shutil
import tempfile
import zipfile
from unittest import mock

from django.conf import settings
from django.test import TestCase, override_settings

from mcserver.models import (
    User,
    DownloadLog,
    Session,
    AnalysisFunction,
    AnalysisResult,
    AnalysisResultState,
    Result,
    Trial,
    Session
)
from mcserver.tasks import (
    download_session_archive,
    download_subject_archive,
    delete_pingdom_sessions,
    invoke_aws_lambda_function
)
from mcserver.zipsession_v2 import (
    SessionDirectoryConstructor, SubjectDirectoryConstructor
)

_temp_media = tempfile.mkdtemp()
_download_tmp = tempfile.mkdtemp()  # isolated dir for DownloadArchiveTests' tearDown


@override_settings(
    MEDIA_ROOT=_temp_media,
    DEFAULT_FILE_STORAGE="django.core.files.storage.FileSystemStorage",
    task_always_eager=True
)
class TasksTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="johndoe",
            email="johndoe@email.com",
            first_name="John",
            last_name="Dou",
            password="testpass"
        )
        self.pingdom_user = User.objects.create_user(
            username="pingdom",
            email="pingdom@mail.com",
            first_name="John",
            last_name="Dou",
            password="testpass"
        )
        self.session = Session.objects.create(user=self.user)
        self.trial_one = Trial.objects.create(session=self.session, name="testone")
        self.trial_two = Trial.objects.create(session=self.session, name="testtwo")

    def test_delete_pingdom_sessions_successful(self):
        Session.objects.create(user=self.pingdom_user)
        Session.objects.create(user=self.pingdom_user)
        self.assertTrue(
            Session.objects.filter(user=self.pingdom_user).exists()
        )
        delete_pingdom_sessions.delay()
        self.assertFalse(
            Session.objects.filter(user=self.pingdom_user).exists()
        )

    def test_delete_pingdom_sessions_if_user_does_not_exist(self):
        self.pingdom_user.delete()
        Session.objects.create(user=self.user)
        Session.objects.create(user=self.user)
        self.assertTrue(Session.objects.filter(user=self.user).exists())
        delete_pingdom_sessions.delay()
        self.assertTrue(Session.objects.filter(user=self.user).exists())

    def test_delete_pingdom_sessions_no_sessions(self):
        self.assertFalse(Session.objects.filter(user=self.pingdom_user).exists())
        delete_pingdom_sessions.delay()
        self.assertFalse(Session.objects.filter(user=self.pingdom_user).exists())

    @mock.patch("requests.post")
    def test_invoke_aws_lambda_function_commits_successful_analysis_result(
        self, mock_post_request
    ):
        response_data, status_code = {
            'message': 'Maximal center of mass vertical position: 1.07 m'
        }, 200
        mock_post_request.return_value.status_code = status_code
        mock_post_request.return_value.json.return_value = response_data
        function = AnalysisFunction.objects.create(
            title='func 0',
            description='desc 0',
            url='http://localhost:5000/functions/invokations'
        )
        data = {'session_id': str(self.session.id), 'specific_trial_names': [self.trial_one.name]}
        before_analysis_results = AnalysisResult.objects.count()
        before_results = Result.objects.count()
        task = invoke_aws_lambda_function.delay(self.user.id, function.id, data)
        after_analysis_results = AnalysisResult.objects.count()
        after_results = Result.objects.count()
        self.assertEqual(after_analysis_results, before_analysis_results + 1)
        self.assertEqual(after_results, before_results + 1)
        result = Result.objects.last()
        self.assertEqual(result.trial, self.trial_one)
        self.assertEqual(result.tag, function.title)
        with open(result.media.path, 'r') as json_file:
            self.assertEqual(json.loads(json_file.read()), response_data)
        analisys_result = AnalysisResult.objects.last()
        self.assertEqual(analisys_result.user, self.user)
        self.assertEqual(analisys_result.function, function)
        self.assertEqual(analisys_result.data, data)
        self.assertEqual(analisys_result.status, status_code)
        self.assertEqual(analisys_result.result, result)
        self.assertEqual(analisys_result.state, AnalysisResultState.SUCCESSFULL)

    @mock.patch("requests.post")
    def test_invoke_aws_lambda_function_commits_failed_analysis_result_if_aws_error(
        self, mock_post_request
    ):
        response_data, status_code = {'error': 'session_id is required.'}, 400
        mock_post_request.return_value.status_code = status_code
        mock_post_request.return_value.json.return_value = response_data
        function = AnalysisFunction.objects.create(
            title='func 0',
            description='desc 0',
            url='http://localhost:5000/functions/invokations'
        )
        data = {'specific_trial_names': [self.trial_one.name]}
        before_analysis_results = AnalysisResult.objects.count()
        before_results = Result.objects.count()
        task = invoke_aws_lambda_function.delay(self.user.id, function.id, data)
        after_analysis_results = AnalysisResult.objects.count()
        after_results = Result.objects.count()
        self.assertEqual(after_analysis_results, before_analysis_results + 1)
        self.assertEqual(after_results, before_results)
        analysis_result = AnalysisResult.objects.last()
        self.assertEqual(analysis_result.user, self.user)
        self.assertEqual(analysis_result.function, function)
        self.assertEqual(analysis_result.data, data)
        self.assertEqual(analysis_result.status, status_code)
        self.assertIsNone(analysis_result.result)
        self.assertEqual(analysis_result.response, {'error': 'session_id is required.'})
        self.assertEqual(analysis_result.state, AnalysisResultState.FAILED)

    def test_invoke_aws_lambda_function_commits_failed_analysis_result_if_request_exception(
        self
    ):
        function = AnalysisFunction.objects.create(title='func 0', description='desc 0')
        data = {'specific_trial_names': [self.trial_two.name]}
        before_analysis_results = AnalysisResult.objects.count()
        before_results = Result.objects.count()
        task = invoke_aws_lambda_function.delay(self.user.id, function.id, data)
        after_analysis_results = AnalysisResult.objects.count()
        after_results = Result.objects.count()
        self.assertEqual(after_analysis_results, before_analysis_results + 1)
        self.assertEqual(after_results, before_results)
        analysis_result = AnalysisResult.objects.last()
        self.assertEqual(analysis_result.user, self.user)
        self.assertEqual(analysis_result.function, function)
        self.assertEqual(analysis_result.data, data)
        self.assertEqual(analysis_result.status, 500)
        self.assertEqual(
            analysis_result.response,
            {'error': 'Invalid URL \'\': No scheme supplied. Perhaps you meant https://?'}
        )
        self.assertIsNone(analysis_result.result)
        self.assertEqual(analysis_result.state, AnalysisResultState.FAILED)

    @mock.patch("requests.post")
    def test_invoke_aws_lambda_function_commits_failed_analysis_result_if_json_invalid(
        self, mock_post_request
    ):
        mock_post_request.side_effect = ValueError('Invalid JSON.')
        function = AnalysisFunction.objects.create(
            title='func 0',
            description='desc 0',
            url='https://localhost:5000/functions/invokations'
        )
        data = {'specific_trial_names': ['test', {'name': 'test'}]}
        before_analysis_results = AnalysisResult.objects.count()
        before_results = Result.objects.count()
        task = invoke_aws_lambda_function.delay(self.user.id, function.id, data)
        after_analysis_results = AnalysisResult.objects.count()
        after_results = Result.objects.count()
        self.assertEqual(after_analysis_results, before_analysis_results + 1)
        self.assertEqual(after_results, before_results)
        analysis_result = AnalysisResult.objects.last()
        self.assertEqual(analysis_result.user, self.user)
        self.assertEqual(analysis_result.function, function)
        self.assertEqual(analysis_result.data, data)
        self.assertEqual(analysis_result.status, 500)
        self.assertIsNone(analysis_result.result)
        self.assertEqual(analysis_result.response, {'error': 'Invalid JSON.'})
        self.assertEqual(analysis_result.state, AnalysisResultState.FAILED)

    @mock.patch("requests.post")
    def test_invoke_aws_lambda_function_re_run_analysis_function_in_the_same_result_instance(
        self, mock_post_request
    ):
        response_data, status_code = {
            'message': 'Maximal center of mass vertical position: 1.07 m'
        }, 200
        mock_post_request.return_value.status_code = status_code
        mock_post_request.return_value.json.return_value = response_data
        function = AnalysisFunction.objects.create(
            title='func 0',
            description='desc 0',
            url='http://localhost:5000/functions/invokations'
        )
        result = Result.objects.create(
            trial=self.trial_one, tag=function.title, meta={'error': 'Invalid JSON'}
        )
        other_result = Result.objects.create(trial=self.trial_two, tag=function.title)
        data = {'session_id': str(self.session.id), 'specific_trial_names': [self.trial_one.name]}
        before_analysis_results = AnalysisResult.objects.count()
        before_results = Result.objects.count()
        task = invoke_aws_lambda_function.delay(self.user.id, function.id, data)
        after_analysis_results = AnalysisResult.objects.count()
        after_results = Result.objects.count()
        self.assertEqual(after_analysis_results, before_analysis_results + 1)
        self.assertEqual(after_results, before_results)
        analisys_result = AnalysisResult.objects.last()
        self.assertEqual(analisys_result.user, self.user)
        self.assertEqual(analisys_result.function, function)
        self.assertEqual(analisys_result.data, data)
        self.assertEqual(analisys_result.status, status_code)
        self.assertEqual(analisys_result.result, result)
        self.assertEqual(analisys_result.state, AnalysisResultState.SUCCESSFULL)


@override_settings(
    MEDIA_ROOT=_download_tmp,
    ARCHIVES_ROOT=os.path.join(_download_tmp, "archives"),
    DEFAULT_FILE_STORAGE="django.core.files.storage.FileSystemStorage",
    SENTRY_DSN="",
)
class DownloadArchiveTests(TestCase):
    """download_session_archive / download_subject_archive must create a
    DownloadLog on success and never leave the build dir or zip on the
    worker's ephemeral disk (which otherwise fills up and breaks downloads).
    """

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
    def _make_fake_build(dir_path):
        """Return a fake build() (Session/SubjectDirectoryConstructor.build)
        that writes a real build dir on disk and returns its path."""
        def _build(object_id):
            os.makedirs(dir_path, exist_ok=True)
            with open(os.path.join(dir_path, "payload.txt"), "w") as fh:
                fh.write("data")
            return dir_path
        return _build

    @staticmethod
    def _fake_zipdir(dir_path):
        """Fake zipdir() for the success path, mirroring the real one: remove
        the source dir and write a real zip under ARCHIVES_ROOT."""
        shutil.rmtree(dir_path)
        os.makedirs(settings.ARCHIVES_ROOT, exist_ok=True)
        zip_path = os.path.join(
            settings.ARCHIVES_ROOT, os.path.basename(dir_path) + ".zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("payload.txt", "data")
        return zip_path

    # --- success: DownloadLog created and temp files cleaned up ---------

    def test_session_success_creates_log_and_cleans_up(self):
        build_dir = os.path.join(settings.MEDIA_ROOT, "OpenCapData_sess-1")
        leftover_zip = os.path.join(
            settings.ARCHIVES_ROOT, "OpenCapData_sess-1.zip")
        with mock.patch.object(
            SessionDirectoryConstructor, "build",
            side_effect=self._make_fake_build(build_dir),
        ), mock.patch(
            "mcserver.tasks.zipdir", side_effect=self._fake_zipdir,
        ):
            result = download_session_archive.apply(args=("sess-1", self.user.id))

        self.assertEqual(DownloadLog.objects.count(), 1)
        log = DownloadLog.objects.get()
        self.assertEqual(log.user, self.user)
        self.assertEqual(log.task_id, result.id)
        self.assertTrue(log.media.name)  # a file was actually stored
        self.assertFalse(os.path.exists(build_dir))
        self.assertFalse(os.path.exists(leftover_zip))

    def test_session_success_for_anonymous_user(self):
        build_dir = os.path.join(settings.MEDIA_ROOT, "OpenCapData_sess-anon")
        with mock.patch.object(
            SessionDirectoryConstructor, "build",
            side_effect=self._make_fake_build(build_dir),
        ), mock.patch(
            "mcserver.tasks.zipdir", side_effect=self._fake_zipdir,
        ):
            download_session_archive.apply(args=("sess-anon", None))

        self.assertEqual(DownloadLog.objects.count(), 1)
        self.assertIsNone(DownloadLog.objects.get().user)

    def test_subject_success_creates_log_and_cleans_up(self):
        build_dir = os.path.join(
            settings.MEDIA_ROOT, "OpenCapData_Subject_subj-1")
        leftover_zip = os.path.join(
            settings.ARCHIVES_ROOT, "OpenCapData_Subject_subj-1.zip")
        with mock.patch.object(
            SubjectDirectoryConstructor, "build",
            side_effect=self._make_fake_build(build_dir),
        ), mock.patch(
            "mcserver.tasks.zipdir", side_effect=self._fake_zipdir,
        ):
            result = download_subject_archive.apply(args=("subj-1", self.user.id))

        self.assertEqual(DownloadLog.objects.count(), 1)
        log = DownloadLog.objects.get()
        self.assertEqual(log.user, self.user)
        self.assertEqual(log.task_id, result.id)
        self.assertFalse(os.path.exists(build_dir))
        self.assertFalse(os.path.exists(leftover_zip))

    # --- failure: no DownloadLog, but temp still cleaned up ------------

    def test_session_cleans_up_build_dir_when_zip_fails(self):
        build_dir = os.path.join(settings.MEDIA_ROOT, "OpenCapData_sess-2")
        with mock.patch.object(
            SessionDirectoryConstructor, "build",
            side_effect=self._make_fake_build(build_dir),
        ), mock.patch(
            "mcserver.tasks.zipdir",
            side_effect=OSError("No space left on device"),
        ):
            download_session_archive.apply(args=("sess-2", self.user.id))

        self.assertFalse(
            os.path.exists(build_dir),
            "build dir must be removed after a failed download",
        )
        self.assertEqual(DownloadLog.objects.count(), 0)

    def test_subject_cleans_up_build_dir_when_zip_fails(self):
        build_dir = os.path.join(
            settings.MEDIA_ROOT, "OpenCapData_Subject_subj-2")
        with mock.patch.object(
            SubjectDirectoryConstructor, "build",
            side_effect=self._make_fake_build(build_dir),
        ), mock.patch(
            "mcserver.tasks.zipdir",
            side_effect=OSError("No space left on device"),
        ):
            download_subject_archive.apply(args=("subj-2", self.user.id))

        self.assertFalse(
            os.path.exists(build_dir),
            "build dir must be removed after a failed download",
        )
        self.assertEqual(DownloadLog.objects.count(), 0)
