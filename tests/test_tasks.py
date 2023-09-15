import os
from unittest import mock

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
        self.assertEqual(result.meta, response_data)
        self.assertEqual(result.tag, function.title)
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