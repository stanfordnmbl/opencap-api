import os
import shutil
import pickle
import boto3
from urllib.parse import urlparse

from django.conf import settings

from mcserver.models import Trial, Result, Session
from mcserver.constants import README_TXT_PATH, AWS_S3_GEOMETRY_VTP_FILENAMES, ResultTag


class SessionDirectoryConstructor:
    """ This class is responsible for building directory
        with organized files related to Session with `object_id`

        Directory structure:
        - OpenCapData_<object_id>
            - Videos
                - Cam0
                    - OutputPkl
                        - squats_keypoints.pkl
                        - ...
                        - trialN_keypoints.pkl
                    - InputMedia
                        - squats
                            - squats.mov
                            - squats_sync.mp4
                        - ...
                        - trialN
                            - trialN.mov
                            - trialN_sync.mp4
                    - cameraIntrinsicsExtrinsics.pickle
                - ...
                - CamN
                - mappingCamDevice.pickle
            - MarkerData
                - neutral.trc
                - ...
                - trialN.trc
            - OpenSimData
                - Model
                    - Geometry
                    - ModelName.osim
                - Kinematics
                    - squats.mot
                    - ...
                    - trialN.mot
            - CalibrationImages
                - calib_imgCam0.jpg
                - ...
                - calib_imgCamN.jpg
            - sessionMetadata.yaml
            - README.txt
    """
    def __init__(self, *args, **kwargs):
        self.root_dir_path = settings.MEDIA_ROOT

    def set_root_dir_path(self, root_dir_path):
        self.root_dir_path = root_dir_path
    
    def get_root_dir_path(self):
        return self.root_dir_path

    def download_file_from_s3(self, s3_src, dist):
        with open(dist, "wb") as dist_file:
            dist_file.write(s3_src.read())
    
    def collect_video_files(self, trial):
        root_dir_path = self.get_root_dir_path()
        mapping_cam_device = {}
        for idx, video in enumerate(trial.video_set.all().only("device_id", "video")):
            video_root = os.path.join(
                root_dir_path, "Videos", f"Cam{idx}", "InputMedia", trial.formated_name
            )
            os.makedirs(video_root, exist_ok=True)
            self.download_file_from_s3(
                video.video, os.path.join(video_root, f"{trial.formated_name}.mov")
            )
            mapping_cam_device[str(video.device_id).replace('-', '').upper()] = idx

        mapping_cam_device_path = os.path.join(root_dir_path, "Videos", 'mappingCamDevice.pickle')
        if os.path.exists(mapping_cam_device_path):
            with open(mapping_cam_device_path, "rb") as handle:
                mapping_cam_device = {**mapping_cam_device, **pickle.load(handle)}
        with open(mapping_cam_device_path, "wb") as handle:
            pickle.dump(mapping_cam_device, handle)
    
    def collect_sync_video_files(self, trial):
        root_dir_path = self.get_root_dir_path()
        for result in trial.result_set.filter(tag=ResultTag.VIDEO_SYNC.value).only("media"):
            video_root = os.path.join(
                root_dir_path, "Videos", result.device_id, "InputMedia", trial.formated_name
            )
            os.makedirs(video_root, exist_ok=True)
            ext = urlparse(result.media.url).path.split(".")[-1]
            self.download_file_from_s3(
                result.media,
                os.path.join(video_root, f"{trial.formated_name}_sync.{ext}")
            )
    
    def collect_pose_pickle_files(self, trial):
        root_dir_path = self.get_root_dir_path()
        for result in trial.result_set.filter(tag=ResultTag.POSE_PICKLE.value).only("device_id", "media"):
            device_pickle_root = os.path.join(root_dir_path, "Videos", result.device_id, "OutputPkl")
            os.makedirs(device_pickle_root, exist_ok=True)
            self.download_file_from_s3(
                result.media,
                os.path.join(device_pickle_root, f"{trial.formated_name}_keypoints.pkl")
            )
    
    def collect_marker_data_files(self, trial):
        root_dir_path = self.get_root_dir_path()
        for result in trial.result_set.filter(tag=ResultTag.MARKER_DATA.value).only("media"):
            marker_data_root = os.path.join(root_dir_path, "MarkerData")
            os.makedirs(marker_data_root, exist_ok=True)
            self.download_file_from_s3(
                result.media,
                os.path.join(marker_data_root, f"{trial.formated_name}.trc")
            )
    
    def collect_kinematics_files(self, trial):
        root_dir_path = self.get_root_dir_path()
        for result in trial.result_set.filter(tag=ResultTag.IK_RESULTS.value).only("media"):
            kinematics_root = os.path.join(root_dir_path, "OpenSimData", "Kinematics")
            os.makedirs(kinematics_root, exist_ok=True)
            self.download_file_from_s3(
                result.media,
                os.path.join(kinematics_root, f"{trial.formated_name}.mot")
            )
    
    def collect_geometry_vtp_files_from_s3(self, model_name):
        s3 = boto3.client("s3")
        root_dir_path = self.get_root_dir_path()
        geometry_dir = os.path.join(root_dir_path, "OpenSimData", "Model", "Geometry")
        os.makedirs(geometry_dir, exist_ok=True)
        for name in AWS_S3_GEOMETRY_VTP_FILENAMES:
            s3.download_file(
                settings.AWS_S3_OPENCAP_PUBLIC_BUCKET,
                f"geometries_vtp/{model_name}/{name}.vtp",
                os.path.join(geometry_dir, f"{name}.vtp")
            )

    def collect_opensim_model_files(self, trial):
        root_dir_path = self.get_root_dir_path()
        opensim_result = trial.result_set.filter(tag=ResultTag.OPENSIM_MODEL.value).first()
        if opensim_result:
            opensim_model_short_filename = urlparse(
                opensim_result.media.url
            ).path.split('-')[-1]
            model_root = os.path.join(root_dir_path, "OpenSimData", "Model")
            os.makedirs(model_root, exist_ok=True)
            self.download_file_from_s3(
                opensim_result.media,
                os.path.join(model_root, opensim_model_short_filename)
            )

            if "LaiArnold" in opensim_model_short_filename:
                self.collect_geometry_vtp_files_from_s3("LaiArnold")
    
    def collect_calibration_images_files(self, trial):
        if trial.meta and "calibration" in trial.meta:
            calibration_images = trial.result_set.filter(
                tag=ResultTag.CALIBRATION_IMAGE.value
            ).only("device_id", "media")
            for camera_id, priority in trial.meta["calibration"].items():
                if priority not in [0, 1]:
                    return

                calib_img_device_id = camera_id
                if priority == 1:
                    calib_img_device_id = f"{camera_id}_altSoln"

                camera_calib_img = calibration_images.filter(device_id=calib_img_device_id).first()
                if camera_calib_img:
                    root_dir_path = self.get_root_dir_path()
                    calibration_images_dir = os.path.join(root_dir_path, "CalibrationImages")
                    os.makedirs(calibration_images_dir, exist_ok=True)
                    ext = urlparse(camera_calib_img.media.url).path.split(".")[-1]
                    self.download_file_from_s3(
                        camera_calib_img.media,
                        os.path.join(calibration_images_dir, f"calib_img{camera_id}.{ext}")
                    )

    def collect_camera_calibration_files(self, trial):
        if trial.meta and "calibration" in trial.meta:
            root_dir_path = self.get_root_dir_path()
            calibration_opts = trial.result_set.filter(
                tag=ResultTag.CAMERA_CALIBRATION_OPTS.value
            ).only("device_id", "media")
            for camera_id, priority in trial.meta["calibration"].items():
                calib_opt_device_id = f"{camera_id}_soln{priority}"
                camera_calib_opt = calibration_opts.filter(device_id=calib_opt_device_id).first()
                if camera_calib_opt:
                    camera_dir = os.path.join(root_dir_path, "Videos", camera_id)
                    os.makedirs(camera_dir, exist_ok=True)
                    self.download_file_from_s3(
                        camera_calib_opt.media,
                        os.path.join(camera_dir, "cameraIntrinsicsExtrinsics.pickle")
                    )

    def collect_docs(self, trial):
        root_dir_path = self.get_root_dir_path()
        session_metadata_result = trial.result_set.filter(
            tag=ResultTag.SESSION_METADATA.value
        ).first()
        if session_metadata_result:
            self.download_file_from_s3(
                session_metadata_result.media,
                os.path.join(root_dir_path, "sessionMetadata.yaml")
            )

        shutil.copy2(README_TXT_PATH, os.path.join(root_dir_path, "README.txt"))

    def build(self, object_id, upload_to=settings.MEDIA_ROOT):
        session_dir_path = os.path.join(upload_to, f"OpenCapData_{object_id}")
        self.set_root_dir_path(session_dir_path)
        
        calibration_trial = Trial.get_calibration_obj_or_none(object_id)
        if calibration_trial:
            self.collect_camera_calibration_files(calibration_trial)
            self.collect_calibration_images_files(calibration_trial)

        neutral_and_dynamic_trials = Trial.objects.filter(
            session_id=object_id
        ).exclude(name="calibration")
        for trial in neutral_and_dynamic_trials:
            self.collect_video_files(trial)
            self.collect_sync_video_files(trial)
            self.collect_marker_data_files(trial)
            self.collect_pose_pickle_files(trial)
            self.collect_kinematics_files(trial)
        
        neutral_trial = Trial.get_neutral_obj_or_none(object_id)
        if neutral_trial:
            self.collect_opensim_model_files(neutral_trial)
            self.collect_docs(neutral_trial)

        return session_dir_path


class SubjectDirectoryConstructor(SessionDirectoryConstructor):
    """ This class is responsible for building directory
        with organized files related to Subject with `object_id`

        Directory structure:
        - OpenCapData_Subject_<object_id>:
            - OpenCapData_<session_0_id>
            - ...
            - OpenCapData_<session_n_id>
    """
    def build(self, object_id, upload_to=settings.MEDIA_ROOT):
        subject_dir_path = os.path.join(upload_to, f"OpenCapData_Subject_{object_id}")
        os.makedirs(subject_dir_path, exist_ok=True)
        for session in Session.objects.filter(subject_id=object_id).only("id"):
            super().build(session.id, upload_to=subject_dir_path)
        return subject_dir_path


class Zip:
    def __init__(
        self,
        constructor_class,
        object_id,
        delete_directory_after_zip=True,
        commit_zip_result=False,
    ):
        self.constructor = constructor_class()
        self.object_id = object_id
        self.delete_directory_after_zip = delete_directory_after_zip
        self.commit_zip_result = commit_zip_result
    
    def zip(self):
        pass
