from django.conf import settings


class ZipSession():
    def __init__(
        *args,
        delete_folder_after_zip=True,
        commit_zip_result=False,
        **kwargs
    ):
        self.delete_folder_after_zip = delete_folder_after_zip
        self.commit_zip_result = commit_zip_result

    def collect_session_data(self, session_id):
        pass

    def collect_subject_data(self, subject_id):
        pass

    def zip(self, root_path):
        pass
