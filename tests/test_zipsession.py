import uuid
import os
import shutil
import tempfile
import pickle
import glob

from django.conf import settings
from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile

from mcserver.models import User, Session, Trial, Result, Video
from mcserver.zipsession_v2 import ZipSession
from mcserver.zipsession import downloadAndZipSession

_temp_media = tempfile.mkdtemp()


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


@override_settings(
    MEDIA_ROOT=_temp_media,
    DEFAULT_FILE_STORAGE="django.core.files.storage.FileSystemStorage"
)
class TestZipSession(TestCase):
    def setUp(self):
        """ Full session configuration
        """
        self.zip_session = ZipSession()
        self.zip_session.set_root_dir_path(settings.MEDIA_ROOT)
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
            # /OpenSimData/Kinematics
            Result.objects.create(
                trial=trial,
                tag="ik_results",
                device_id="all",
                media=SimpleUploadedFile(f"{trial_name}.mot", content=b"ikresults")
            )

            # /OpenSimData/Model
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
                Result.objects.create(
                    trial=trial,
                    tag="opensim_model",
                    device_id="all",
                    media=SimpleUploadedFile("randommodel-LaiArnold.osim", content=b"")
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

    def setUpCalibration(self):
        # /CalibrationImages/
        calibration_trial = Trial.objects.create(
            session=self.session,
            name="calibration",
            meta={"calibration": {"Cam0": 0, "Cam1": 1}}
        )
        for device_id in ["Cam0", "Cam1"]:
            Result.objects.create(
                trial=calibration_trial,
                device_id=device_id,
                tag="calibration-img",
                media=SimpleUploadedFile(
                    f"random-extrinsicCalib_{device_id}.jpg",
                    content=b"extrinsicCalib"
                )
            )
            Result.objects.create(
                trial=calibration_trial,
                device_id=f"{device_id}_altSoln",
                tag="calibration-img",
                media=SimpleUploadedFile(
                    f"random-extrinsicCalib_{device_id}.jpg",
                    content=b"extrinsicCalib"
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

    def test_collect_videos_for_neutral_trial(self):
        neutral_trial = Trial.objects.get(name="neutral")
        videos_folder = os.path.join(settings.MEDIA_ROOT, "Videos")
        self.assertFalse(os.path.exists(videos_folder))
        self.zip_session.collect_video_data(neutral_trial)
        self.assertTrue(os.path.exists(videos_folder))
        for idx in range(2):
            trial_video_path = os.path.join(
                videos_folder, f"Cam{idx}", "InputMedia", "neutral", "neutral.mov"
            )
            self.assertTrue(os.path.exists(trial_video_path))
        
        mapping_cam_device_path = os.path.join(videos_folder, "mappingCamDevice.pickle")
        self.assertTrue(os.path.exists(mapping_cam_device_path))
        with open(mapping_cam_device_path, 'rb') as handle:
            mapping_cam_device = pickle.load(handle)
            for idx, video in enumerate(neutral_trial.video_set.all().only("device_id")):
                expected_device_key = str(video.device_id).replace('-', '').upper()
                self.assertEqual(mapping_cam_device[expected_device_key], idx)
    
    def test_collect_videos_for_multiple_trials_with_correct_mapping_cam_device_overwriting(self):
        videos_folder = os.path.join(settings.MEDIA_ROOT, "Videos")
        self.assertFalse(os.path.exists(videos_folder))
        for trial_name in self.trials[2:4]:
            trial = Trial.objects.get(name=trial_name)
            self.zip_session.collect_video_data(trial)
            for idx in range(2):
                trial_video_path = os.path.join(
                    videos_folder,
                    f"Cam{idx}",
                    "InputMedia",
                    trial.formated_name,
                    f"{trial.formated_name}.mov"
                )
                self.assertTrue(os.path.exists(trial_video_path))

        mapping_cam_device_path = os.path.join(videos_folder, "mappingCamDevice.pickle")
        self.assertTrue(os.path.exists(mapping_cam_device_path))
        with open(mapping_cam_device_path, 'rb') as handle:
            mapping_cam_device = pickle.load(handle)
            for trial in Trial.objects.filter(name__in=self.trials[2:4]):
                for idx, video in enumerate(trial.video_set.only("device_id")):
                    expected_device_key = str(video.device_id).replace('-', '').upper()
                    self.assertEqual(mapping_cam_device[expected_device_key], idx)
    
    def test_collect_sync_videos_for_trial(self):
        videos_folder = os.path.join(settings.MEDIA_ROOT, "Videos")
        self.assertFalse(os.path.exists(videos_folder))
        trial = Trial.objects.first()
        self.zip_session.collect_sync_videos(trial)
        self.assertTrue(os.path.exists(videos_folder))
        for idx in range(2):
            trial_sync_video_path = os.path.join(
                videos_folder,
                f"Cam{idx}",
                "InputMedia",
                trial.formated_name,
                f"{trial.formated_name}_sync.mp4"
            )
            self.assertTrue(os.path.exists(trial_sync_video_path))
    
    def test_collect_pose_pickle_files_for_trial(self):
        videos_folder = os.path.join(settings.MEDIA_ROOT, "Videos")
        self.assertFalse(os.path.exists(videos_folder))
        trial = Trial.objects.first()
        self.zip_session.collect_pose_pickles(trial)
        self.assertTrue(os.path.exists(videos_folder))
        for idx in range(2):
            trial_pose_pickle_path = os.path.join(
                videos_folder,
                f"Cam{idx}",
                "OutputPkl",
                f"{trial.formated_name}_keypoints.pkl"
            )
            self.assertTrue(os.path.exists(trial_pose_pickle_path))
            with open(trial_pose_pickle_path, "rb") as pose_pickle:
                self.assertEqual(pose_pickle.read(), b"posepickle")
    
    def test_collect_marker_data_files_for_trial(self):
        marker_data_folder = os.path.join(settings.MEDIA_ROOT, "MarkerData")
        self.assertFalse(os.path.exists(marker_data_folder))
        trial = Trial.objects.first()
        self.zip_session.collect_marker_data(trial)
        self.assertTrue(os.path.exists(marker_data_folder))
        expected_marker_data_file_path = os.path.join(
            marker_data_folder, f"{trial.formated_name}.trc"
        )
        self.assertTrue(os.path.exists(expected_marker_data_file_path))
        with open(expected_marker_data_file_path, "rb") as marker_data:
            self.assertEqual(marker_data.read(), b"markerdata")
    
    def test_collect_kinematics_data_files_for_trial(self):
        kinematics_folder = os.path.join(
            settings.MEDIA_ROOT, "OpenSimData", "Kinematics"
        )
        self.assertFalse(os.path.exists(kinematics_folder))
        trial = Trial.objects.first()
        self.zip_session.collect_kinematics_data(trial)
        self.assertTrue(os.path.exists(kinematics_folder))
        expected_kinematics_file_path = os.path.join(
            kinematics_folder, f"{trial.formated_name}.mot"
        )
        self.assertTrue(os.path.exists(expected_kinematics_file_path))
        with open(expected_kinematics_file_path, "rb") as kinematics_data:
            self.assertEqual(kinematics_data.read(), b"ikresults")
    
    def test_collect_opensim_model_file_for_neutral_trial(self):
        trial = Trial.objects.get(name="neutral")
        opensim_model_folder = os.path.join(
            settings.MEDIA_ROOT, "OpenSimData", "Model"
        )
        self.assertFalse(os.path.exists(opensim_model_folder))
        self.zip_session.collect_opensim_model_data(trial)
        self.assertTrue(opensim_model_folder)
        expected_opensim_model_file_path = os.path.join(
            opensim_model_folder, "LaiArnold.osim"
        )
        self.assertTrue(os.path.exists(expected_opensim_model_file_path))

    def test_collect_opensim_model_skips_data_upload_if_trial_has_no_opensim_result(self):
        trial = Trial.objects.get(name="jump")
        self.assertFalse(
            trial.result_set.filter(tag="opensim_model").exists()
        )
        opensim_model_folder = os.path.join(
            settings.MEDIA_ROOT, "OpenSimData", "Model"
        )
        self.assertFalse(os.path.exists(opensim_model_folder))
        self.zip_session.collect_opensim_model_data(trial)
        self.assertFalse(os.path.exists(opensim_model_folder))
    
    def test_collect_docs(self):
        trial = Trial.objects.get(name="neutral")
        session_metadata_yml_path = os.path.join(settings.MEDIA_ROOT, "sessionMetadata.yml")
        readme_txt_path = os.path.join(settings.MEDIA_ROOT, "README.txt")
        self.assertFalse(os.path.exists(session_metadata_yml_path))
        self.assertFalse(os.path.exists(readme_txt_path))
        zip_session =self.zip_session
        zip_session.collect_docs(trial)
        self.assertTrue(os.path.exists(session_metadata_yml_path))
        self.assertTrue(os.path.exists(readme_txt_path))

        with open(zip_session.readme_txt, "rb") as src, open(readme_txt_path, "rb") as dist:
            self.assertEqual(dist.read(), src.read())

    def test_create_session_dir_with_correct_structure_and_name(self):
        session_dir = os.path.join(
            settings.MEDIA_ROOT, f"OpenCapData_{self.session.id}"
        )
        res_session_dir = self.zip_session.collect_session_data(self.session.id)
        self.assertEqual(res_session_dir, session_dir)
        self.assertTrue(os.path.exists(session_dir))
        for root, dirs, files in os.walk(session_dir):
            if root == session_dir:
                self.assertEqual(set(dirs), {"Videos", "OpenSimData", "MarkerData"})
                self.assertEqual(set(files), {"sessionMetadata.yml", "README.txt"})
            
            if root == os.path.join(session_dir, "Videos"):
                self.assertEqual(set(dirs), {"Cam0", "Cam1"})
                self.assertEqual(set(files), {"mappingCamDevice.pickle"})
            
            if (
                root == os.path.join(session_dir, "Videos", "Cam0")
                or root == os.path.join(session_dir, "Videos", "Cam1")
            ):
                self.assertEqual(set(dirs), {"OutputPkl", "InputMedia"})
                # self.assertEqual(set(files), {"cameraIntrinsicsExtrinsics.pickle"})
            
            if root == os.path.join(session_dir, "OpenSimData"):
                self.assertEqual(set(dirs), {"Kinematics", "Model"})
                self.assertEqual(set(files), set())
            
            if root == os.path.join(session_dir, "OpenSimData", "Kinematics"):
                self.assertEqual(set(dirs), set())
                self.assertEqual(set(files), {f"{name}.mot" for name in self.trials})
            
            if root == os.path.join(session_dir, "OpenSimData", "Model"):
                self.assertEqual(set(dirs), set())
                self.assertEqual(set(files), {"LaiArnold.osim"})

    def test_zip_session_dir_successful(self):
        pass

    def test_zip_subject_folder_successful(self):
        pass

    def tearDown(self):
        shutil.rmtree(settings.MEDIA_ROOT)
