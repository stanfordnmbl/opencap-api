import uuid

from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile

from mcserver.models import User, Session, Trial, Result, Video
from mcserver.zipsession_v2 import ZipSession
from mcserver.zipsession import downloadAndZipSession


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


class TestZipSession(TestCase):
    def setUp(self):
        """ Full session configuration
        """
        self.user = User.objects.create_user(
            username="johndoe",
            email="johndoe@email.com",
            first_name="John",
            last_name="Dou",
            password="testpass"
        )
        self.session = Session.objects.create(user=self.user)
        self.trials = ["neutral", "run", "squats", "jump", "cut"]
        
        for trial_name in self.trials:
            # /MarkerData
            trial = Trial.objects.create(session=self.session, name=trial_name)
            Result.objects.create(
                trial=trial,
                tag="marker_data",
                device_id="all",
                media=SimpleUploadedFile(f"{trial_name}.trc", content=b"markerdata")
            )
            
            for device_id in ["Cam0", "Cam1"]:
                # /Videos/Cam*/OutputPkl
                Result.objects.create(
                    trial=trial,
                    tag="pose_pickle",
                    device_id=device_id,
                    media=SimpleUploadedFile(
                        f"{trial_name}_keypoints.pkl", content=b"posepickle"
                    )
                )
                # /Videos/Cam*/InputMedia/{trial_name}
                Result.objects.create(
                    trial=trial,
                    tag="video-sync",
                    device_id=device_id,
                    media=SimpleUploadedFile(
                        f"randomsync_{device_id}.mp4",
                        f"randomsync_{device_id}".encode(),
                        content_type="video/mp4"
                    )
                )
                Video.objects.create(
                    trial=trial,
                    device_id=uuid.uuid4(),
                    video=SimpleUploadedFile(
                        f"randomvideo_{device_id}.mp4",
                        f"randomvideo_{device_id}".encode(),
                        content_type="video/mp4"
                    )
                )

                # /OpenSimData/Kinematics
                if trial_name == "neutral":
                    Result.objects.create(
                        trial=trial,
                        tag="session_metadata",
                        device_id="all",
                        media=SimpleUploadedFile(
                            "random_session_metadata.yml",
                            content=b"metadata"
                        )
                    )
                else:
                    Result.objects.create(
                        trial=trial,
                        tag="ik_results",
                        device_id="all",
                        media=SimpleUploadedFile(f"{trial_name}.mot", content=b"ikresults")
                    )

            # /CalibrationImages/
            calibration_trial = Trial.objects.create(
                session=self.session,
                name="calibration",
                meta={"calibration": {"Cam0": 0, "Cam1": 1}}
            )
            Result.objects.create(
                trial=calibration_trial,
                tag="opensim_model",
                device_id="all",
                media=SimpleUploadedFile("LaiArnold.osim", content=b"")
            )
            for device_id in ["Cam0", "Cam1"]:
                Result.objects.create(
                    trial=calibration_trial,
                    device_id=device_id,
                    tag="calibration-img",
                    media=SimpleUploadedFile(
                        f"random-extrinsicCalib_{device_id}.jpg"
                    )
                )
                Result.objects.create(
                    trial=calibration_trial,
                    device_id=f"{device_id}_altSoln",
                    tag="calobration-img",
                    media=SimpleUploadedFile(
                        f"random-extrinsicCalib_{device_id}.jpg"
                    )
                )
                Result.objects.create(
                    trial=calibration_trial,
                    tag="calibration_parameters",
                    device_id=device_id,
                    media=SimpleUploadedFile(
                        f"{device_id}_cameraIntrinsicsExtrinsics.pickle",
                        content=b"cameraintrinsicsextrinsicspickle"
                    )
                )
                Result.objects.create(
                    trial=calibration_trial,
                    tag="camera_mapping",
                    device_id="all",
                    media=SimpleUploadedFile(
                        f"{device_id}_mappingCamDevice.pickle",
                        content=b"mappinCamDevice",
                    )
                )
                for opt in ["soln0", "soln1"]:
                    Result.objects.create(
                        trial=calibration_trial,
                        tag="calibration_parameters_options",
                        device_id=f"{device_id}_{opt}",
                        media=SimpleUploadedFile(
                            f"{device_id}-cameraintrinsicsExtrinsics_{opt}.pickle",
                            content=b"intrisicsExtrisics"
                        )
                    )

    def test_create_session_folder_with_correct_structure_and_name(self):
        data = ZipSession().collect_session_data(self.session.id)

    def test_zip_session_folder_successful(self):
        pass

    def test_zip_subject_folder_successful(self):
        pass
