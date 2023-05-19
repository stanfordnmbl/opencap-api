import uuid

from django.test import TestCase

from mcserver.models import User, Session, Trial


class TrialTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="johndoe",
            email="johndoe@email.com",
            first_name="John",
            last_name="Dou",
            password="testpass"
        )
        self.session = Session.objects.create(
            user=self.user, public=True
        )
        self.trial = Trial.objects.create(
            session=self.session, name="test"
        )
        self.dummy_session_id = str(uuid.uuid4())

    def test_trial_formated_name_property(self):
        trial = Trial.objects.create(session=self.session, name="test trial")
        self.assertEqual(trial.formated_name, "testtrial")
        trial = Trial.objects.create(session=self.session, name="calibration")
        self.assertEqual(trial.formated_name, "calibration")
        trial = Trial.objects.create(session=self.session, name=None)
        self.assertEqual(trial.formated_name, "")

    def test_session_get_neutral_trial_or_none_returns_last_created_trial_for_session(
        self
    ):
        session = Session.objects.create(
            user=self.user,
            meta={"neutral_trial": {"id": "test-neutral-trial-id"}}
        )
        Trial.objects.create(session=session, name="neutral")
        Trial.objects.create(session=session, name="calibration")
        Trial.objects.create(session=session, name="custom")
        expected_trial = Trial.objects.create(session=session, name="neutral")

        self.assertEqual(
            Trial.get_neutral_obj_or_none(session.id), expected_trial
        )
    
    def test_get_neutral_trial_or_none_returns_id_from_session_meta(self):
        session = Session.objects.create(
            user=self.user,
            meta={"neutral_trial": {"id": str(self.trial.id)}}
        )
        Trial.objects.create(session=session, name="calibration")
        Trial.objects.create(session=session, name="custom")

        self.assertEqual(
            Trial.get_neutral_obj_or_none(session.id), self.trial
        )
    
    def test_get_neutral_trial_or_none_session_does_not_exist(self):
        self.assertIsNone(Trial.get_neutral_obj_or_none(self.dummy_session_id))
    
    def test_get_neutral_trial_or_none_session_has_no_meta(self):
        self.assertIsNone(self.session.meta)
        self.assertIsNone(Trial.get_neutral_obj_or_none(self.session.id))
    
    def test_get_neutral_trial_or_none_session_meta_no_neutral_key(self):
        session = Session.objects.create(
            user=self.user,
            meta={
                "settings": {"framerate": "60"},
                "sessionWithCalibration": {"id": self.dummy_session_id}
            }
        )
        self.assertIsNone(Trial.get_neutral_obj_or_none(session.id))
    
    def test_get_calibration_trial_or_none_returns_last_created_trial_id_for_session(
        self
    ):
        session = Session.objects.create(
            user=self.user,
            meta={
                "neutral_trial": {"id": str(self.trial.id)},
                "sessionWithCalibration": {"id": self.dummy_session_id}
            }
        )
        Trial.objects.create(session=session, name="calibration")
        Trial.objects.create(session=session, name="calibration")
        Trial.objects.create(session=session, name="neutral")
        expected_trial = Trial.objects.create(session=session, name="calibration")

        self.assertEqual(
            Trial.get_calibration_obj_or_none(session.id),
            expected_trial
        )

    def test_get_calibration_trial_or_none_from_session_meta(self):
        session_with_calibration = Session.objects.create(
            user=self.user
        )
        calibration_trial = Trial.objects.create(
            session=session_with_calibration, name="calibration"
        )
        session = Session.objects.create(
            user=self.user,
            meta={
                "neutral_trial": {"id": str(self.trial.id)},
                "sessionWithCalibration": {"id": str(session_with_calibration.id)}
            }
        )
        Trial.objects.create(session=session, name="neutral")

        self.assertEqual(
            Trial.get_calibration_obj_or_none(session.id),
            calibration_trial
        )

    def test_get_calibration_trial_or_none_deep_search(self):
        session_with_calibration = Session.objects.create(
            user=self.user
        )
        calibration_trial = Trial.objects.create(
            session=session_with_calibration, name="calibration"
        )
        session = Session.objects.create(
            user=self.user,
            meta={
                "neutral_trial": {"id": str(self.trial.id)},
                "sessionWithCalibration": {"id": str(session_with_calibration.id)}
            }
        )
        Trial.objects.create(session=session, name="neutral")
        root_session = Session.objects.create(
            user=self.user,
            meta={"sessionWithCalibration": {"id": str(session.id)}}
        )

        self.assertEqual(
            Trial.get_calibration_obj_or_none(root_session.id),
            calibration_trial
        )
    
    def test_get_calibration_trial_or_none_no_session(self):
        self.assertIsNone(Trial.get_calibration_obj_or_none(self.dummy_session_id))
    
    def test_get_calibration_trial_or_none_session_with_no_meta(self):
        self.assertIsNone(self.session.meta)
        self.assertIsNone(Trial.get_calibration_obj_or_none(self.session.id))
    
    def test_get_calibration_trial_or_none_no_session_id_in_meta(self):
        session = Session.objects.create(
            user=self.user,
            meta={"neutral_trial": {"id": "someid"}}
        )
        self.assertIsNone(Trial.get_calibration_obj_or_none(session.id))
    
    def test_get_calibration_trial_or_none_no_id_found(self):
        session_no_calibration = Session.objects.create(
            user=self.user
        )
        session = Session.objects.create(
            user=self.user,
            meta={
                "neutral_trial": {"id": "test-neutral-trial-id"},
                "sessionWithCalibration": {"id": str(session_no_calibration.id)}
            }
        )
        Trial.objects.create(session=session, name="neutral")
        root_session = Session.objects.create(
            user=self.user,
            meta={"sessionWithCalibration": {"id": str(session.id)}}
        )

        self.assertIsNone(
            Trial.get_calibration_obj_or_none(root_session.id)
        )
