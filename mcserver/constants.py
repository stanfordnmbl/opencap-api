import os
from enum import Enum


class ResultTag(Enum):
    CALIBRATION_IMAGE = "calibration-img"
    CAMERA_CALIBRATION_OPTS = "calibration_parameters_options"
    IK_RESULTS= "ik_results"
    MARKER_DATA = "marker_data"
    OPENSIM_MODEL = "opensim_model"
    POSE_PICKLE = "pose_pickle"
    SESSION_METADATA = "session_metadata"
    VIDEO_SYNC = "video-sync"


README_TXT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    "README.txt"
)

AWS_S3_GEOMETRY_VTP_FILENAMES = [
    'capitate_lvs',
    'capitate_rvs',
    'hamate_lvs',
    'hamate_rvs',
    'hat_jaw',
    'hat_ribs_scap',
    'hat_skull',
    'hat_spine',
    'humerus_lv',
    'humerus_rv',
    'index_distal_lvs',
    'index_distal_rvs',
    'index_medial_lvs',
    'index_medial_rvs',
    'index_proximal_lvs',
    'index_proximal_rvs',
    'l_bofoot',
    'l_femur',
    'l_fibula',
    'l_foot',
    'l_patella',
    'l_pelvis',
    'l_talus',
    'l_tibia',
    'little_distal_lvs',
    'little_distal_rvs',
    'little_medial_lvs',
    'little_medial_rvs',
    'little_proximal_lvs',
    'little_proximal_rvs',
    'lunate_lvs',
    'lunate_rvs',
    'metacarpal1_lvs',
    'metacarpal1_rvs',
    'metacarpal2_lvs',
    'metacarpal2_rvs',
    'metacarpal3_lvs',
    'metacarpal3_rvs',
    'metacarpal4_lvs',
    'metacarpal4_rvs',
    'metacarpal5_lvs',
    'metacarpal5_rvs',
    'middle_distal_lvs',
    'middle_distal_rvs',
    'middle_medial_lvs',
    'middle_medial_rvs',
    'middle_proximal_lvs',
    'middle_proximal_rvs',
    'pisiform_lvs',
    'pisiform_rvs',
    'r_patella',
    'r_pelvis',
    'r_talus',
    'r_tibia',
    'sacrum',
    'scaphoid_lvs',
    'radius_lv',
    'radius_rv',
    'ring_distal_lvs',
    'ring_distal_rvs',
    'ring_medial_lvs',
    'ring_medial_rvs',
    'ring_proximal_lvs',
    'ring_proximal_rvs',
    'r_bofoot',
    'r_femur',
    'r_fibula',
    'r_foot',
    'scaphoid_rvs',
    'thumb_distal_lvs',
    'thumb_distal_rvs',
    'thumb_proximal_lvs',
    'thumb_proximal_rvs',
    'trapezium_lvs',
    'trapezium_rvs',
    'trapezoid_lvs',
    'trapezoid_rvs',
    'triquetrum_lvs',
    'triquetrum_rvs',
    'ulna_lv',
    'ulna_rv'
]
