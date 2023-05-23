import os
import shutil
import pickle
from urllib.parse import urlparse

from django.conf import settings

from mcserver.models import Trial, Result



# class SessionDirectoryConstructor:
#     def build(self, session_id):
#         pass


# class SubjectDirectoryConstructor(SessionDirectoryConstructor):
#     def build(self, subject_id):
#         pass


# class Zip:
#     def __init__(
#         self,
#         constructor_class,
#         object_id,
#         delete_directory_after_zip=True,
#         commit_zip_result=False,
#     ):
#         self.constructor = constructor_class()
#         self.object_id = object_id
#         self.delete_directory_after_zip = delete_directory_after_zip
#         self.commit_zip_result = commit_zip_result

#     def remove_old_zip_files(self):
#         pass
    
#     def zip(self):
#         pass


class ZipSession():
    def __init__(
        self,
        *args,
        delete_folder_after_zip=True,
        commit_zip_result=False,
        **kwargs
    ):
        self.delete_folder_after_zip = delete_folder_after_zip
        self.commit_zip_result = commit_zip_result
        self.readme_txt = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "data",
            "README.txt"
        )

    def set_root_dir_path(self, root_dir_path):
        self.root_dir_path = root_dir_path
    
    def get_root_dir_path(self):
        return self.root_dir_path

    def download_file_from_s3(self, s3_src, dist):
        with open(dist, "wb") as dist_file:
            dist_file.write(s3_src.read())
    
    def collect_video_data(self, trial):
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
    
    def collect_sync_videos(self, trial):
        root_dir_path = self.get_root_dir_path()
        for result in trial.result_set.filter(tag="video-sync").only("media"):
            video_root = os.path.join(
                root_dir_path, "Videos", result.device_id, "InputMedia", trial.formated_name
            )
            os.makedirs(video_root, exist_ok=True)
            ext = urlparse(result.media.url).path.split(".")[-1]
            self.download_file_from_s3(
                result.media,
                os.path.join(video_root, f"{trial.formated_name}_sync.{ext}")
            )
    
    def collect_pose_pickles(self, trial):
        root_dir_path = self.get_root_dir_path()
        for result in trial.result_set.filter(tag="pose_pickle").only("device_id", "media"):
            device_pickle_root = os.path.join(root_dir_path, "Videos", result.device_id, "OutputPkl")
            os.makedirs(device_pickle_root, exist_ok=True)
            self.download_file_from_s3(
                result.media,
                os.path.join(device_pickle_root, f"{trial.formated_name}_keypoints.pkl")
            )
    
    def collect_marker_data(self, trial):
        root_dir_path = self.get_root_dir_path()
        for result in trial.result_set.filter(tag="marker_data").only("media"):
            marker_data_root = os.path.join(root_dir_path, "MarkerData")
            os.makedirs(marker_data_root, exist_ok=True)
            self.download_file_from_s3(
                result.media,
                os.path.join(marker_data_root, f"{trial.formated_name}.trc")
            )
    
    def collect_kinematics_data(self, trial):
        root_dir_path = self.get_root_dir_path()
        for result in trial.result_set.filter(tag="ik_results").only("media"):
            kinematics_root = os.path.join(root_dir_path, "OpenSimData", "Kinematics")
            os.makedirs(kinematics_root, exist_ok=True)
            self.download_file_from_s3(
                result.media,
                os.path.join(kinematics_root, f"{trial.formated_name}.mot")
            )

    def collect_opensim_model_data(self, trial):
        root_dir_path = self.get_root_dir_path()
        opensim_result = trial.result_set.filter(tag="opensim_model").first()
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
                print("Download geometry...")
    
    def collect_docs(self, trial):
        root_dir_path = self.get_root_dir_path()
        session_metadata_result = trial.result_set.filter(tag="session_metadata").first()
        if session_metadata_result:
            self.download_file_from_s3(
                session_metadata_result.media,
                os.path.join(root_dir_path, "sessionMetadata.yml")
            )

        shutil.copy2(self.readme_txt, os.path.join(root_dir_path, "README.txt"))
    
    def collect_calibration_images(self, trial):
        if trial.meta and "calibration" in trial.meta:
            calibration_images = trial.result_set.filter(
                tag="calibration-img"
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

    def collect_camera_calibration_options(self, trial):
        if trial.meta and "calibration" in trial.meta:
            root_dir_path = self.get_root_dir_path()
            calibration_opts = trial.result_set.filter(tag="calibration_parameters_options").only(
                "device_id", "media"
            )
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

    def collect_session_data(self, session_id, root_dir_path=settings.MEDIA_ROOT):
        session_path = os.path.join(settings.MEDIA_ROOT, f"OpenCapData_{session_id}")
        self.set_root_dir_path(session_path)
        
        calibration_trial = Trial.get_calibration_obj_or_none(session_id)
        if calibration_trial:
            self.collect_camera_calibration_options(calibration_trial)
            self.collect_calibration_images(calibration_trial)

        neutral_and_dynamic_trials = Trial.objects.filter(
            session_id=session_id
        ).exclude(name="calibration")
        for trial in neutral_and_dynamic_trials:
            self.collect_video_data(trial)
            self.collect_sync_videos(trial)
            self.collect_marker_data(trial)
            self.collect_pose_pickles(trial)
            self.collect_kinematics_data(trial)
        
        neutral_trial = Trial.get_neutral_obj_or_none(session_id)
        if neutral_trial:
            self.collect_opensim_model_data(neutral_trial)
            self.collect_docs(neutral_trial)

        return session_path
