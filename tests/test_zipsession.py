import uuid
import os
import shutil
import tempfile
import pickle
from moto import mock_s3
import boto3

from django.conf import settings
from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile

from mcserver.models import User, Session, Subject, Trial, Result, Video
from mcserver.constants import (
    README_TXT_PATH,
    AWS_S3_GEOMETRY_VTP_FILENAMES,
    ResultTag
)
from mcserver.zipsession_v2 import (
    SessionDirectoryConstructor,
    SubjectDirectoryConstructor,
    zipdir
)

_temp_media = tempfile.mkdtemp()


@override_settings(
    MEDIA_ROOT=_temp_media,
    AWS_ACCESS_KEY_ID="testing",
    AWS_SECRET_ACCESS_KEY="testing",
    AWS_STORAGE_BUCKET_NAME="test",
    AWS_S3_OPENCAP_PUBLIC_BUCKET="test-mc-opencap-public",
    AWS_S3_ENDPOINT_URL=None
)
class TestStoragesConfigClass(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mock_s3 = mock_s3()
        cls.mock_s3.start()

        s3 = boto3.resource("s3")
        bucket = s3.Bucket("test")
        bucket.create()
    
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.mock_s3.stop()

    def tearDown(self):
        if os.path.exists(settings.MEDIA_ROOT):
            shutil.rmtree(settings.MEDIA_ROOT)


class SessionTestDataClass(TestCase):
    @classmethod
    def setup_neutral_and_dynamic_trials_results(cls):
        cls.trials = ["neutral", "run", "squats", "jump", "cut"]
        
        for trial_name in cls.trials:
            # /MarkerData
            trial = Trial.objects.create(session=cls.session, name=trial_name)
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
                        "random_session_metadata.yaml",
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

    @classmethod
    def setup_calibration_trials_results(cls):
        calibration_trial = Trial.objects.create(
            session=cls.session,
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
                    content=f"calibration_img_{device_id}".encode()
                )
            )
            Result.objects.create(
                trial=calibration_trial,
                device_id=f"{device_id}_altSoln",
                tag="calibration-img",
                media=SimpleUploadedFile(
                    f"random-extrinsicCalib_{device_id}.jpg",
                    content=f"calibration_img_{device_id}_altSoln".encode()
                )
            )
            Result.objects.create(
                trial=calibration_trial,
                tag="calibration_parameters",
                device_id=device_id,
                media=SimpleUploadedFile(
                    f"{device_id}_cameraIntrinsicsExtrinsics.pickle",
                    content=f"cameraspickle_{device_id}".encode()
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
                        content=f"camera_{device_id}_{opt}".encode()
                    )
                )

    @classmethod
    def setup_geometry_vtps(cls):
        s3 = boto3.client("s3")
        s3.create_bucket(Bucket="test-mc-opencap-public")

        for name in AWS_S3_GEOMETRY_VTP_FILENAMES:
            s3.put_object(
                Bucket="test-mc-opencap-public",
                Key=f"geometries_vtp/LaiArnold/{name}.vtp",
                Body=name.encode(),
            )

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = User.objects.create_user(
            username="johndoe",
            email="johndoe@email.com",
            first_name="John",
            last_name="Dou",
            password="testpass"
        )
        cls.session = Session.objects.create(user=cls.user)
        cls.setup_neutral_and_dynamic_trials_results()
        cls.setup_calibration_trials_results()


class SessionDirectoryConstructorTests(SessionTestDataClass, TestStoragesConfigClass):
    def test_collect_videos_for_neutral_trial(self):
        neutral_trial = Trial.objects.get(name="neutral")
        videos_dir = os.path.join(settings.MEDIA_ROOT, "Videos")
        self.assertFalse(os.path.exists(videos_dir))
        SessionDirectoryConstructor().collect_video_files(neutral_trial)
        self.assertTrue(os.path.exists(videos_dir))
        for idx in range(2):
            trial_video_path = os.path.join(
                videos_dir, f"Cam{idx}", "InputMedia", "neutral", "neutral.mov"
            )
            self.assertTrue(os.path.exists(trial_video_path))
        
        mapping_cam_device_path = os.path.join(videos_dir, "mappingCamDevice.pickle")
        self.assertTrue(os.path.exists(mapping_cam_device_path))
        with open(mapping_cam_device_path, 'rb') as handle:
            mapping_cam_device = pickle.load(handle)
            for idx, video in enumerate(neutral_trial.video_set.all().only("device_id")):
                expected_device_key = str(video.device_id).replace('-', '').upper()
                self.assertEqual(mapping_cam_device[expected_device_key], idx)
    
    def test_collect_videos_for_multiple_trials_with_correct_mapping_cam_device_overwriting(self):
        videos_dir = os.path.join(settings.MEDIA_ROOT, "Videos")
        self.assertFalse(os.path.exists(videos_dir))
        for trial_name in self.trials[2:4]:
            trial = Trial.objects.get(name=trial_name)
            SessionDirectoryConstructor().collect_video_files(trial)
            for idx in range(2):
                trial_video_path = os.path.join(
                    videos_dir,
                    f"Cam{idx}",
                    "InputMedia",
                    trial.formated_name,
                    f"{trial.formated_name}.mov"
                )
                self.assertTrue(os.path.exists(trial_video_path))

        mapping_cam_device_path = os.path.join(videos_dir, "mappingCamDevice.pickle")
        self.assertTrue(os.path.exists(mapping_cam_device_path))
        with open(mapping_cam_device_path, 'rb') as handle:
            mapping_cam_device = pickle.load(handle)
            for trial in Trial.objects.filter(name__in=self.trials[2:4]):
                for idx, video in enumerate(trial.video_set.only("device_id")):
                    expected_device_key = str(video.device_id).replace('-', '').upper()
                    self.assertEqual(mapping_cam_device[expected_device_key], idx)
    
    def test_collect_sync_video_files_for_trial(self):
        videos_dir = os.path.join(settings.MEDIA_ROOT, "Videos")
        self.assertFalse(os.path.exists(videos_dir))
        trial = Trial.objects.first()
        SessionDirectoryConstructor().collect_sync_video_files(trial)
        self.assertTrue(os.path.exists(videos_dir))
        for idx in range(2):
            trial_sync_video_path = os.path.join(
                videos_dir,
                f"Cam{idx}",
                "InputMedia",
                trial.formated_name,
                f"{trial.formated_name}_sync.mp4"
            )
            self.assertTrue(os.path.exists(trial_sync_video_path))
    
    def test_collect_pose_pickle_files_for_trial(self):
        videos_dir = os.path.join(settings.MEDIA_ROOT, "Videos")
        self.assertFalse(os.path.exists(videos_dir))
        trial = Trial.objects.first()
        SessionDirectoryConstructor().collect_pose_pickle_files(trial)
        self.assertTrue(os.path.exists(videos_dir))
        for idx in range(2):
            trial_pose_pickle_path = os.path.join(
                videos_dir,
                f"Cam{idx}",
                "OutputPkl",
                f"{trial.formated_name}_keypoints.pkl"
            )
            self.assertTrue(os.path.exists(trial_pose_pickle_path))
            with open(trial_pose_pickle_path, "rb") as pose_pickle:
                self.assertEqual(pose_pickle.read(), b"posepickle")
    
    def test_collect_marker_data_files_for_trial(self):
        marker_data_dir = os.path.join(settings.MEDIA_ROOT, "MarkerData")
        self.assertFalse(os.path.exists(marker_data_dir))
        trial = Trial.objects.first()
        SessionDirectoryConstructor().collect_marker_data_files(trial)
        self.assertTrue(os.path.exists(marker_data_dir))
        expected_marker_data_file_path = os.path.join(
            marker_data_dir, f"{trial.formated_name}.trc"
        )
        self.assertTrue(os.path.exists(expected_marker_data_file_path))
        with open(expected_marker_data_file_path, "rb") as marker_data:
            self.assertEqual(marker_data.read(), b"markerdata")
    
    def test_collect_kinematics_data_files_for_trial(self):
        kinematics_dir = os.path.join(
            settings.MEDIA_ROOT, "OpenSimData", "Kinematics"
        )
        self.assertFalse(os.path.exists(kinematics_dir))
        trial = Trial.objects.first()
        SessionDirectoryConstructor().collect_kinematics_files(trial)
        self.assertTrue(os.path.exists(kinematics_dir))
        expected_kinematics_file_path = os.path.join(
            kinematics_dir, f"{trial.formated_name}.mot"
        )
        self.assertTrue(os.path.exists(expected_kinematics_file_path))
        with open(expected_kinematics_file_path, "rb") as kinematics_data:
            self.assertEqual(kinematics_data.read(), b"ikresults")
    
    def test_collect_opensim_model_file_for_neutral_trial(self):
        trial = Trial.objects.get(name="neutral")
        opensim_model_dir = os.path.join(
            settings.MEDIA_ROOT, "OpenSimData", "Model"
        )
        self.assertFalse(os.path.exists(opensim_model_dir))
        SessionDirectoryConstructor().collect_opensim_model_files(trial)
        self.assertTrue(opensim_model_dir)
        expected_opensim_model_file_path = os.path.join(
            opensim_model_dir, "LaiArnold.osim"
        )
        self.assertTrue(os.path.exists(expected_opensim_model_file_path))

    def test_collect_opensim_model_skips_data_upload_if_trial_has_no_opensim_result(self):
        trial = Trial.objects.get(name="jump")
        self.assertFalse(
            trial.result_set.filter(tag="opensim_model").exists()
        )
        opensim_model_dir = os.path.join(
            settings.MEDIA_ROOT, "OpenSimData", "Model"
        )
        self.assertFalse(os.path.exists(opensim_model_dir))
        SessionDirectoryConstructor().collect_opensim_model_files(trial)
        self.assertFalse(os.path.exists(opensim_model_dir))
    
    def test_collect_camera_calibration_options(self):
        trial = Trial.objects.get(name="calibration")
        calibration_opt_camera_0_path = os.path.join(
            settings.MEDIA_ROOT, "Videos", "Cam0", "cameraIntrinsicsExtrinsics.pickle"
        )
        calibration_opt_camera_1_path = os.path.join(
            settings.MEDIA_ROOT, "Videos", "Cam1", "cameraIntrinsicsExtrinsics.pickle"
        )
        self.assertFalse(os.path.exists(calibration_opt_camera_0_path))
        self.assertFalse(os.path.exists(calibration_opt_camera_1_path))
        SessionDirectoryConstructor().collect_camera_calibration_files(trial)
        self.assertTrue(os.path.exists(calibration_opt_camera_0_path))
        self.assertTrue(os.path.exists(calibration_opt_camera_1_path))
        for idx, path in enumerate(
            (calibration_opt_camera_0_path, calibration_opt_camera_1_path)
        ):
            self.assertTrue(os.path.exists(path))
            with open(path) as opt_camera:
                self.assertEqual(opt_camera.read(), f"camera_Cam{idx}_soln{idx}")
    
    def test_collect_camera_calibration_opt_no_trial_metadata(self):
        trial = Trial.objects.get(name="calibration")
        trial.meta = None
        trial.save()
        trial.refresh_from_db()
        videos_dir = os.path.join(settings.MEDIA_ROOT, "Videos")
        self.assertFalse(os.path.exists(videos_dir))
        SessionDirectoryConstructor().collect_camera_calibration_files(trial)
        self.assertFalse(os.path.exists(videos_dir))
    
    def test_collect_camera_calibration_opt_no_calibration_metadata(self):
        trial = Trial.objects.get(name="calibration")
        trial.meta = {"calibration": {}}
        trial.save()
        trial.refresh_from_db()
        videos_dir = os.path.join(settings.MEDIA_ROOT, "Videos")
        self.assertFalse(os.path.exists(videos_dir))
        SessionDirectoryConstructor().collect_camera_calibration_files(trial)
        self.assertFalse(os.path.exists(videos_dir))
    
    def test_collect_camera_calibration_opt_no_data_for_calibration_metadata(self):
        trial = Trial.objects.get(name="calibration")
        trial.meta = {"calibration": {"Cam0": 1234, "Camera34": 1}}
        trial.save()
        trial.refresh_from_db()
        videos_dir = os.path.join(settings.MEDIA_ROOT, "Videos")
        self.assertFalse(os.path.exists(videos_dir))
        SessionDirectoryConstructor().collect_camera_calibration_files(trial)
        self.assertFalse(os.path.exists(videos_dir))
    
    def test_collect_calibration_images(self):
        trial = Trial.objects.get(name="calibration")
        calibration_images_dir = os.path.join(settings.MEDIA_ROOT, "CalibrationImages")
        self.assertFalse(os.path.exists(calibration_images_dir))
        SessionDirectoryConstructor().collect_calibration_images_files(trial)
        self.assertTrue(os.path.exists(calibration_images_dir))
        for priority in range(2):
            calib_img_content = f"calibration_img_Cam{priority}"
            if priority:
                calib_img_content += "_altSoln"
            calib_img_path = os.path.join(calibration_images_dir, f"calib_imgCam{priority}.jpg")
            self.assertTrue(os.path.exists(calib_img_path))
            with open(calib_img_path) as calib_img:
                self.assertEqual(calib_img.read(), calib_img_content)

    def test_collect_calibration_images_no_trial_metadata(self):
        trial = Trial.objects.get(name="calibration")
        trial.meta = None
        trial.save()
        trial.refresh_from_db()
        calib_imgs_dir = os.path.join(settings.MEDIA_ROOT, "CalibrationImages")
        self.assertFalse(os.path.exists(calib_imgs_dir))
        SessionDirectoryConstructor().collect_calibration_images_files(trial)
        self.assertFalse(os.path.exists(calib_imgs_dir))
    
    def test_collect_calibration_images_no_calibration_metadata(self):
        trial = Trial.objects.get(name="calibration")
        trial.meta = {"calibration": {}}
        trial.save()
        trial.refresh_from_db()
        calib_imgs_dir = os.path.join(settings.MEDIA_ROOT, "CalibrationImages")
        self.assertFalse(os.path.exists(calib_imgs_dir))
        SessionDirectoryConstructor().collect_calibration_images_files(trial)
        self.assertFalse(os.path.exists(calib_imgs_dir))
    
    def test_collect_calibration_images_no_data_for_calibration_metadata(self):
        trial = Trial.objects.get(name="calibration")
        trial.meta = {"calibration": {"Cam0": 1234, "Camera34": 1}}
        trial.save()
        trial.refresh_from_db()
        calib_imgs_dir = os.path.join(settings.MEDIA_ROOT, "CalibrationImages")
        self.assertFalse(os.path.exists(calib_imgs_dir))
        SessionDirectoryConstructor().collect_calibration_images_files(trial)
        self.assertFalse(os.path.exists(calib_imgs_dir))
    
    def test_collect_geometry_vtp_files(self):
        self.setup_geometry_vtps()
        geometry_dir = os.path.join(settings.MEDIA_ROOT, "OpenSimData", "Model", "Geometry")
        self.assertFalse(os.path.exists(geometry_dir))
        SessionDirectoryConstructor().collect_geometry_vtp_files_from_s3("LaiArnold")
        self.assertTrue(os.path.exists(geometry_dir))
        for name in AWS_S3_GEOMETRY_VTP_FILENAMES:
            vtp_file_path = os.path.join(geometry_dir, f"{name}.vtp")
            self.assertTrue(os.path.exists(vtp_file_path))
            with open(vtp_file_path) as vtp_file:
                self.assertEqual(vtp_file.read(), name)

    def test_collect_docs(self):
        trial = Trial.objects.get(name="neutral")
        session_metadata_yml_path = os.path.join(settings.MEDIA_ROOT, "sessionMetadata.yaml")
        readme_txt_path = os.path.join(settings.MEDIA_ROOT, "README.txt")
        self.assertFalse(os.path.exists(session_metadata_yml_path))
        self.assertFalse(os.path.exists(readme_txt_path))
        SessionDirectoryConstructor().collect_docs(trial)
        self.assertTrue(os.path.exists(session_metadata_yml_path))
        self.assertTrue(os.path.exists(readme_txt_path))

        with open(README_TXT_PATH, "rb") as src, open(readme_txt_path, "rb") as dist:
            self.assertEqual(dist.read(), src.read())

    def test_create_session_dir_with_correct_structure_and_name(self):
        self.setup_geometry_vtps()
        session_dir = os.path.join(
            settings.MEDIA_ROOT, f"OpenCapData_{self.session.id}"
        )
        res_session_dir = SessionDirectoryConstructor().build(
            self.session.id, upload_to=settings.MEDIA_ROOT
        )
        self.assertEqual(res_session_dir, session_dir)
        self.assertTrue(os.path.exists(session_dir))
        for root, dirs, files in os.walk(session_dir):
            if root == session_dir:
                self.assertEqual(
                    set(dirs), {"Videos", "OpenSimData", "MarkerData", "CalibrationImages"}
                )
                self.assertEqual(set(files), {"sessionMetadata.yaml", "README.txt"})
            
            if root == os.path.join(session_dir, "Videos"):
                self.assertEqual(set(dirs), {"Cam0", "Cam1"})
                self.assertEqual(set(files), {"mappingCamDevice.pickle"})
            
            if (
                root == os.path.join(session_dir, "Videos", "Cam0")
                or root == os.path.join(session_dir, "Videos", "Cam1")
            ):
                self.assertEqual(set(dirs), {"OutputPkl", "InputMedia"})
                self.assertEqual(set(files), {"cameraIntrinsicsExtrinsics.pickle"})
            
            if root == os.path.join(session_dir, "OpenSimData"):
                self.assertEqual(set(dirs), {"Kinematics", "Model"})
                self.assertEqual(set(files), set())
            
            if root == os.path.join(session_dir, "OpenSimData", "Kinematics"):
                self.assertEqual(set(dirs), set())
                self.assertEqual(set(files), {f"{name}.mot" for name in self.trials})
            
            if root == os.path.join(session_dir, "OpenSimData", "Model"):
                self.assertEqual(set(dirs), {"Geometry"})
                self.assertEqual(set(files), {"LaiArnold.osim"})
            
            if root == os.path.join(session_dir, "CalibrationImages"):
                self.assertEqual(set(dirs), set())
                self.assertEqual(set(files), {"calib_imgCam0.jpg", "calib_imgCam1.jpg"})


class SubjectDirectoryConstructorTests(SessionTestDataClass, TestStoragesConfigClass):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.setup_geometry_vtps()
        cls.subject = Subject.objects.create(name="Human", user=cls.user)
        cls.session.subject = cls.subject
        cls.session.save()
        cls.session.refresh_from_db()
        cls.session_no_data = Session.objects.create(
            user=cls.user, subject=cls.subject
        )
    
    def test_build_subject_directory_with_session_data(self):
        subject_dir = os.path.join(settings.MEDIA_ROOT, f"OpenCapData_Subject_{self.subject.id}")
        self.assertFalse(os.path.exists(subject_dir))
        result_subject_dir = SubjectDirectoryConstructor().build(
            self.subject.id, upload_to=settings.MEDIA_ROOT
        )
        self.assertEqual(result_subject_dir, subject_dir)
        self.assertTrue(os.path.exists(subject_dir))
        self.assertTrue(
            os.path.exists(
                os.path.join(subject_dir, f"OpenCapData_{self.session.id}")
            )
        )
        self.assertFalse(
            os.path.exists(
                os.path.join(subject_dir, f"OpenCapData_{self.session_no_data.id}")
            )
        )


@override_settings(
    MEDIA_ROOT=_temp_media,
    ARCHIVES_ROOT=os.path.join(_temp_media, "archives")
)
class OpencapZipTests(TestCase):
    def setUp(self):
        self.session_id = uuid.uuid4()
        self.session_dir_path = os.path.join(
            settings.MEDIA_ROOT, f"OpenCapData_{self.session_id}"
        )
        os.makedirs(self.session_dir_path)
        self.session_dir_zip_path = os.path.join(
            settings.ARCHIVES_ROOT, f"OpenCapData_{self.session_id}.zip"
        )
    
    def test_create_zip_file_with_default_config(self):
        self.assertTrue(os.path.exists(self.session_dir_path))
        self.assertFalse(os.path.exists(self.session_dir_zip_path))
        res_zip_file_path = zipdir(self.session_dir_path)
        self.assertEqual(res_zip_file_path, self.session_dir_zip_path)
        self.assertFalse(os.path.exists(self.session_dir_path))
        self.assertTrue(os.path.exists(self.session_dir_zip_path))
