import yaml
import os
import requests
import urllib.request
import shutil
import pickle
import glob
import zipfile
import platform
import time
from decouple import config

API_TOKEN = config("API_TOKEN")

def getDataDirectory(isDocker=False):
    computername = os.environ.get('COMPUTERNAME', None)
    
    # Paths to OpenPose folder for local testing.
    if computername == 'SUHLRICHHPLDESK': # Scott's computer
        dataDir = 'C:/Users/scott.uhlrich/MyDrive/mobilecap/'
    elif computername == "LAPTOP-7EDI4Q8Q": # Scott laptop
        dataDir = 'C:\MyDriveSym/mobilecap/'        
    elif computername == 'DESKTOP-0UPR1OH': # Antoine desktop (Windows)
        # dataDir = 'C:/MyDriveSym/Projects/mobilecap/'
        dataDir = 'C:/Users/antoi/Documents/MyRepositories/mobilecap_data/'
    elif computername == 'HPL1': # HPL dekstop 1
        # dataDir = 'C:/MyDriveSym/Projects/mobilecap/'
        dataDir = 'C:/Users/opencap/Documents/MyRepositories/mobilecap_data/'
    elif computername == 'DESKTOP-GUEOBL2': # HPL dekstop 3
        # dataDir = 'C:/MyDriveSym/Projects/mobilecap/'
        dataDir = 'C:/Users/opencap/Documents/MyRepositories/mobilecap_data/'
    elif computername == 'DESKTOP-L9OQ0MS': # Lukasz's desktop
        # dataDir = 'C:/MyDriveSym/Projects/mobilecap/'
        dataDir = 'C:/Users/antoi/Documents/MyRepositories/mobilecap_data/'
    elif computername == 'DESKTOP-NJMGEBG': # Alienware for reprocessing
        dataDir = 'C:/Users/opencap/Documents/MyRepositories/mobilecap_data/'
    elif isDocker:
        dataDir = os.path.join(os.getcwd())
    else:
        dataDir = os.path.join(os.getcwd())
    return dataDir

def importMetadata(filePath):
    myYamlFile = open(filePath)
    parsedYamlFile = yaml.load(myYamlFile, Loader=yaml.FullLoader)
    
    return parsedYamlFile

def download_file(url, file_name):
    with urllib.request.urlopen(url) as response, open(file_name, 'wb') as out_file:
        shutil.copyfileobj(response, out_file)
        
def getTrialName(trial_id, host=""):
    resp = requests.get(host + "/trials/{}/".format(trial_id),
                         headers = {"Authorization": "Token {}".format(API_TOKEN)})
    trial = resp.json()
    trial_name = trial['name']
    trial_name = trial_name.replace(' ', '')
    
    return trial_name

def downloadVideosFromServer(session_id,trial_id, isDocker=True,
                             isCalibration=False, isStaticPose=False,
                             trial_name= None, session_name = None,
                             host = ""):
    
    if session_name is None:
        session_name = session_id
    data_dir = getDataDirectory(isDocker)    
    session_path = os.path.join(data_dir,'Data', session_name)  
    if not os.path.exists(session_path): 
        os.makedirs(session_path, exist_ok=True)
    
    resp = requests.get(host + "/trials/{}/".format(trial_id),
                         headers = {"Authorization": "Token {}".format(API_TOKEN)})
    trial = resp.json()
    if trial_name is None:
        trial_name = trial['name']
    trial_name = trial_name.replace(' ', '')

    
    print("\nProcessing {}".format(trial_name))

    # The videos are not always organized in the same order. Here, we save
    # the order during the first trial processed in the session such that we
    # can use the same order for the other trials.
    if not os.path.exists(os.path.join(session_path, "Videos", 'mappingCamDevice.pickle')):
        mappingCamDevice = {}
        for k, video in enumerate(trial["videos"]):
            os.makedirs(os.path.join(session_path, "Videos", "Cam{}".format(k), "InputMedia", trial_name), exist_ok=True)
            video_path = os.path.join(session_path, "Videos", "Cam{}".format(k), "InputMedia", trial_name, trial_name + ".mov")
            download_file(video["video"], video_path)                
            mappingCamDevice[video["device_id"].replace('-', '').upper()] = k
        with open(os.path.join(session_path, "Videos", 'mappingCamDevice.pickle'), 'wb') as handle:
            pickle.dump(mappingCamDevice, handle)
    else:
        with open(os.path.join(session_path, "Videos", 'mappingCamDevice.pickle'), 'rb') as handle:
            mappingCamDevice = pickle.load(handle) 
            # ensure upper on deviceID
            for dID in mappingCamDevice.keys():
                mappingCamDevice[dID.upper()] = mappingCamDevice.pop(dID)
        for video in trial["videos"]:            
            k = mappingCamDevice[video["device_id"].replace('-', '').upper()] 
            videoDir = os.path.join(session_path, "Videos", "Cam{}".format(k), "InputMedia", trial_name)
            os.makedirs(videoDir, exist_ok=True)
            video_path = os.path.join(videoDir, trial_name + ".mov")
            if not os.path.exists(video_path):
                if video['video'] :
                    download_file(video["video"], video_path)
              
    return trial_name


def switchCalibrationForCamera(cam,trial_id, session_path, host=""):
    trialName = getTrialName(trial_id, host=host)
    camPath = os.path.join(session_path,'Videos',cam)
    trialPath = os.path.join(camPath,'InputMedia',trialName)
    
    # change Picture 
    src = os.path.join(trialPath,'extrinsicCalib_soln1.jpg')
    dest = os.path.join(session_path,'CalibrationImages','extrinsicCalib' + cam + '.jpg')
    if os.path.exists(dest):
        os.remove(dest)
    shutil.copyfile(src,dest)
    
    # change calibration parameters
    src = os.path.join(trialPath,'cameraIntrinsicsExtrinsics_soln1.pickle')
    dest = os.path.join(camPath,'cameraIntrinsicsExtrinsics.pickle')
    if os.path.exists(dest):
        os.remove(dest)
    shutil.copyfile(src,dest)    
    
                 
def getMetadataFromServer(session_id,justCheckerParams=False, host=""):
    
    # defaultMetadataPath = os.path.join(os.path.dirname(os.path.abspath(__file__)),
    #                                    'defaultSessionMetadata.yaml')
    # session_desc = importMetadata(defaultMetadataPath)
    session_desc = {}
    
    # Get session-specific metadata from api.
    session = requests.get(host + "/sessions/{}/".format(session_id),
                         headers = {"Authorization": "Token {}".format(API_TOKEN)}).json()
    if session['meta'] is not None:
        if not justCheckerParams:
            session_desc["subjectID"] = session['meta']['subject']['id']
            session_desc["mass_kg"] = float(session['meta']['subject']['mass'])
            session_desc["height_m"] = float(session['meta']['subject']['height'])
            session_desc["gender_mf"] = session['meta']['subject']['gender']
        
        if 'sessionWithCalibration' in session['meta'] and 'checkerboard' not in session['meta']:
            newSessionId = session['meta']['sessionWithCalibration']['id']
            session = requests.get(host + "/sessions/{}/".format(newSessionId),
                         headers = {"Authorization": "Token {}".format(API_TOKEN)}).json()

        session_desc['checkerBoard'] = {}
        session_desc['checkerBoard']["squareSideLength_mm"] =  float(session['meta']['checkerboard']['square_size'])
        session_desc['checkerBoard']["black2BlackCornersWidth_n"] = int(session['meta']['checkerboard']['cols'])
        session_desc['checkerBoard']["black2BlackCornersHeight_n"] = int(session['meta']['checkerboard']['rows'])
        session_desc['checkerBoard']["placement"] = session['meta']['checkerboard']['placement']   
        

          
    else:
        print('Couldn''t find session metadata in API, using default metadata. May be issues.')
    
    return session_desc

def deleteResult(trial_id, tag=None,resultNum=None, host=""):
    # Delete specific result number, or all results with a specific tag
    if resultNum != None:
        resultNums = [resultNum]
    elif tag != None:
        trial = requests.get(host + "/trials/{}/".format(trial_id),
                         headers = {"Authorization": "Token {}".format(API_TOKEN)}).json()
        resultNums = [r['id'] for r in trial['results'] if r['tag']==tag]

    for rNum in resultNums:
        requests.delete(host + "/results/{}/".format(rNum),
                         headers = {"Authorization": "Token {}".format(API_TOKEN)})
        
def getSessionJson(session_id, host=""):
    resp = requests.get(host + "/sessions/{}/".format(session_id),
                         headers = {"Authorization": "Token {}".format(API_TOKEN)})
    session = resp.json()
    
    def getCreatedAt(trial):
        return trial['created_at']
    session['trials'].sort(key=getCreatedAt)
    
    return session
    

def getCalibrationTrialID(session_id, host=""):
    session = getSessionJson(session_id, host=host)
    
    calib_ids = [t['id'] for t in session['trials'] if t['name'] == 'calibration']
                                                          
    if len(calib_ids)>0:
        calibID = calib_ids[-1]
    elif session['meta']['sessionWithCalibration']:
        calibID = getCalibrationTrialID(session['meta']['sessionWithCalibration']['id'], host=host)
    else:
        raise Exception('No calibration trial in session.')
    
    return calibID

def getNeutralTrialID(session_id, host=""):
    session = getSessionJson(session_id, host=host)
    
    neutral_ids = [t['id'] for t in session['trials'] if t['name'] == 'neutral']
    
    if len(neutral_ids)>0:
        neutralID = neutral_ids[-1]
    elif session['meta']['neutral_trial']:
        neutralID = session['meta']['neutral_trial']['id']
    else:
        raise Exception('No neutral trial in session.')
    
    return neutralID
    
def getCalibration(session_id,session_path, host=""):
    # look for calibration pickes on Django. If they are not there, then see if 
    # we need to do any switch calibration, then post the good calibration to django.
    calibration_id = getCalibrationTrialID(session_id, host=host)

    # Check if calibration has been posted to session
    resp = requests.get(host + "/trials/{}/".format(calibration_id),
                         headers = {"Authorization": "Token {}".format(API_TOKEN)})
    trial = resp.json()
    calibResultTags = [res['tag'] for res in trial['results']]
    
    # The code from here down could be simplified to pull the calibration from
    # the API for every trial - you would just have to run downloadAndSwitchCalibrationFromDjango
    # every time. The current implementation allows for the locally-stored calibratoin
    # to be used if there, which cuts back on downloads. 
    
    videoFolder = os.path.join(session_path,'Videos')
    os.makedirs(videoFolder, exist_ok=True)
    
    if trial['status'] != 'done':
        return
    
    mapURL = trial['results'][calibResultTags.index('camera_mapping')]['media']
    mapLocalPath = os.path.join(videoFolder,'mappingCamDevice.pickle')

    downloadAndSwitchCalibrationFromDjango(session_id,session_path,calibTrialID=calibration_id, host=host)
    
    # Download mapping
    if len(glob.glob(mapLocalPath)) == 0:
        download_file(mapURL,mapLocalPath)
                        

def downloadAndSwitchCalibrationFromDjango(session_id,session_path,calibTrialID = None, host = ""):
    if calibTrialID == None:
        calibTrialID = getCalibrationTrialID(session_id, host=host)
    resp = requests.get(host + "/trials/{}/".format(calibTrialID),
                         headers = {"Authorization": "Token {}".format(API_TOKEN)})
    trial = resp.json()
       
    calibURLs = {t['device_id']:t['media'] for t in trial['results'] if t['tag'] == 'calibration_parameters_options'}
    calibImgURLs = {t['device_id']:t['media'] for t in trial['results'] if t['tag'] == 'calibration-img'}
    _,imgExtension = os.path.splitext(calibImgURLs[list(calibImgURLs.keys())[0]])
    lastIdx = imgExtension.find('?') 
    if lastIdx >0:
        imgExtension = imgExtension[:lastIdx]
    
    if 'meta' in trial.keys() and trial['meta'] is not None and 'calibration' in trial['meta'].keys():
        calibDict = trial['meta']['calibration']
        calibImgFolder = os.path.join(session_path,'CalibrationImages')
        os.makedirs(calibImgFolder,exist_ok=True)
        for cam,calibNum in calibDict.items():
            camDir = os.path.join(session_path,'Videos',cam)
            os.makedirs(camDir,exist_ok=True)
            file_name = os.path.join(camDir,'cameraIntrinsicsExtrinsics.pickle')
            img_fileName = os.path.join(calibImgFolder,'calib_img' + cam + imgExtension)
            if calibNum == 0:
                download_file(calibURLs[cam+'_soln0'], file_name)
                download_file(calibImgURLs[cam],img_fileName)
                print('Downloading calibration for ' + cam)
            elif calibNum == 1:
                download_file(calibURLs[cam+'_soln1'], file_name) 
                download_file(calibImgURLs[cam + '_altSoln'],img_fileName)
                 
                print('Downloading alternate calibration camera for ' + cam)
    else:
        print('No metadata for camera switching')
        
def getMotionData(trial_id,session_path, host=""):
    trial = requests.get(host + "/trials/{}/".format(trial_id),
                         headers = {"Authorization": "Token {}".format(API_TOKEN)}).json()
    trial_name = trial['name']
    resultTags = [res['tag'] for res in trial['results']]


    # get marker data
    if 'marker_data' in resultTags:
        markerFolder = os.path.join(session_path,'MarkerData')
        markerPath = os.path.join(markerFolder,trial_name + '.trc')
        os.makedirs(markerFolder, exist_ok=True)
        markerURL = trial['results'][resultTags.index('marker_data')]['media']
        download_file(markerURL,markerPath)
    
    # get IK data
    if 'ik_results' in resultTags:
        ikFolder = os.path.join(session_path,'OpenSimData','Kinematics')
        ikPath = os.path.join(ikFolder,trial_name + '.mot')
        os.makedirs(ikFolder, exist_ok=True)
        ikURL = trial['results'][resultTags.index('ik_results')]['media']
        download_file(ikURL,ikPath)
    
    # get pose pickles
    if 'pose_pickle' in resultTags:
        poseURLs = {t['device_id']:t['media'] for t in trial['results'] if t['tag'] == 'pose_pickle'}
        camDirs = glob.glob(os.path.join(session_path,'Videos','Cam*'))
        for camDir in camDirs:
            os.makedirs(os.path.join(camDir,'OutputPkl'),exist_ok=True)
            fileName = os.path.join(camDir,'OutputPkl',trial_name + '_keypoints.pkl')
            _,cam = os.path.split(camDir)
            download_file(poseURLs[cam],fileName)
        
    return
        
def getModelAndMetadata(session_id, session_path, host=""):
    neutral_id = getNeutralTrialID(session_id, host=host)
    trial = requests.get(host + "/trials/{}/".format(neutral_id),
                         headers = {"Authorization": "Token {}".format(API_TOKEN)}).json()
    resultTags = [res['tag'] for res in trial['results']]
    
    # get metadata
    metadataPath = os.path.join(session_path,'sessionMetadata.yaml')
    if not os.path.exists(metadataPath) :
        metadataURL = trial['results'][resultTags.index('session_metadata')]['media']
        download_file(metadataURL, metadataPath)
    
    # get model if does not exist
    modelURL = trial['results'][resultTags.index('opensim_model')]['media']
    modelName = modelURL[modelURL.rfind('-')+1:modelURL.rfind('?')]
    modelFolder = os.path.join(session_path,'OpenSimData','Model')
    modelPath = os.path.join(modelFolder,modelName)
    if not os.path.exists(modelPath):
        os.makedirs(modelFolder, exist_ok=True)
        download_file(modelURL, modelPath)
        
    return modelName

def postCalibration(session_id,session_path, calibTrialID=None, host=""):
    
    videoDir = os.path.join(session_path,'Videos')
    videoFolders = glob.glob(os.path.join(videoDir,'Cam*'))
        
    if calibTrialID == None:
        calibTrialID = getCalibrationTrialID(session_id, host=host)
    
    for vf in videoFolders:
        _, camName = os.path.split(vf)
        fPath = os.path.join(vf,'cameraIntrinsicsExtrinsics.pickle')
        deviceID = camName
        postFileToTrial(fPath,calibTrialID,'calibration_parameters',deviceID, host=host)
    
    return
    
def postFileToTrial(filePath, trial_id,tag, device_id, host=""):
    files = {'media': open(filePath, 'rb')}
    data = {
        "trial": trial_id,
        "tag": tag,
        "device_id" : device_id
    }

    requests.post(host + "/results/", files=files, data=data,
                         headers = {"Authorization": "Token {}".format(API_TOKEN)})
    files["media"].close()
    
    return

def getSyncdVideos(trial_id,session_path, host=""):
    trial = requests.get(host + "/trials/{}/".format(trial_id),
                         headers = {"Authorization": "Token {}".format(API_TOKEN)}).json()
    trial_name = trial['name']
    
    if trial['results']:
        for result in trial['results']:
            if result['tag'] == 'video-sync':
                url = result['media']
                cam,suff = os.path.splitext(url[url.rfind('_')+1:])
                lastIdx = suff.find('?') 
                if lastIdx >0:
                    suff = suff[:lastIdx]
                
                syncVideoPath = os.path.join(session_path,'Videos',cam,'InputMedia',trial_name,trial_name + '_sync' + suff)
                download_file(url,syncVideoPath)
        
def downloadAndZipSession(session_id,deleteFolderWhenZipped=True,isDocker=True,
                          writeToDjango=False, host=""):
    
    data_dir = getDataDirectory(isDocker=isDocker)
    
    session = requests.get(host + "/sessions/{}/".format(session_id),
                         headers = {"Authorization": "Token {}".format(API_TOKEN)}).json()
    session_name = 'OpenCapData_' + session_id
    baseDir = os.path.join(data_dir,'Data')
    session_path = os.path.join(baseDir,session_name)
    
    # Look for old folders in this directory and delete them
    if os.path.isdir(baseDir):
        folders = os.listdir(baseDir) 
        timeSinceModified = [(-os.path.getmtime(os.path.join(baseDir,f)) +int(time.time()))/60 for f in folders]
        
        for i,f in enumerate(folders):
            if timeSinceModified[i] > 15: # delete if older than 15 mins
                try:
                    os.remove(os.path.join(baseDir,f)) # files
                except:
                    try:
                        shutil.rmtree(os.path.join(baseDir,f)) # folders
                    except:
                        pass
        
    calib_id = getCalibrationTrialID(session_id, host=host)
    neutral_id = getNeutralTrialID(session_id, host=host)
    dynamic_ids = [t['id'] for t in session['trials'] if (t['name'] != 'calibration' and t['name'] !='neutral')]
    
    # see if it's already been done, if so just pull from django
    # trial_last = requests.get(host + "/trials/{}/".format(dynamic_ids[-1])).json()
    # if trial_last['results']:
    #     tagsTrialLast = [res['tag'] for res in trial_last['results']]
    #     if 'session_zip' in tagsTrialLast:
    #         print('Zip for this session is up to date.')
    #         return
    
    # Calibration
    try:
        downloadVideosFromServer(session_id,calib_id,isDocker=isDocker,
                             isCalibration=True,isStaticPose=False, host=host) 
        getCalibration(session_id,session_path, host=host)
    except:
        pass
    
    # Neutral
    try:
        modelName = getModelAndMetadata(session_id,session_path, host=host)
        getMotionData(neutral_id,session_path, host=host)
        downloadVideosFromServer(session_id,neutral_id,isDocker=isDocker,
                         isCalibration=False,isStaticPose=True,session_name=session_name, host=host)
        getSyncdVideos(neutral_id,session_path, host=host)
    except:
        pass

    # Dynamic
    for dynamic_id in dynamic_ids:
        try:
            getMotionData(dynamic_id,session_path, host=host)
            downloadVideosFromServer(session_id,dynamic_id,isDocker=isDocker,
                     isCalibration=False,isStaticPose=False,session_name=session_name, host=host)
            getSyncdVideos(dynamic_id,session_path, host=host)
        except:
            pass
        
    mcserverDir = os.path.dirname(os.path.abspath(__file__))
    # Readme  
    try:        
        pathReadme = os.path.join(mcserverDir, 'data', 'README.txt')
        pathReadmeEnd = os.path.join(session_path, 'README.txt')
        shutil.copy2(pathReadme, pathReadmeEnd)
    except:
        pass
        
    # Geometry
    try:
        if 'LaiArnold' in modelName:
            modelType = 'LaiArnold'
        else:
            raise ValueError("Geometries not available for this model, please contact us")
        if platform.system() == 'Windows':
            geometryDir = os.path.join(mcserverDir, 'tmp', modelType, 'Geometry')
        else:
            geometryDir = "/tmp/{}/Geometry".format(modelType)
        # If not in cache, download from s3.
        if not os.path.exists(geometryDir):
            os.makedirs(geometryDir, exist_ok=True)
            if 'LaiArnold' in modelName:
                vtpNames = ['capitate_lvs','capitate_rvs','hamate_lvs','hamate_rvs',
                            'hat_jaw','hat_ribs_scap','hat_skull','hat_spine','humerus_lv',
                            'humerus_rv','index_distal_lvs','index_distal_rvs','index_medial_lvs',
                            'index_medial_rvs','index_proximal_lvs','index_proximal_rvs',
                            'little_distal_lvs','little_distal_rvs','little_medial_lvs',
                            'little_medial_rvs','little_proximal_lvs','little_proximal_rvs',
                            'lunate_lvs','lunate_rvs','l_bofoot','l_femur','l_fibula',
                            'l_foot','l_patella','l_pelvis','l_talus','l_tibia',
                            'metacarpal1_lvs','metacarpal1_rvs','metacarpal2_lvs',
                            'metacarpal2_rvs','metacarpal3_lvs','metacarpal3_rvs',
                            'metacarpal4_lvs','metacarpal4_rvs','metacarpal5_lvs',
                            'metacarpal5_rvs','middle_distal_lvs','middle_distal_rvs',
                            'middle_medial_lvs','middle_medial_rvs','middle_proximal_lvs',
                            'middle_proximal_rvs','pisiform_lvs','pisiform_rvs',
                            'radius_lv','radius_rv','ring_distal_lvs','ring_distal_rvs',
                            'ring_medial_lvs','ring_medial_rvs','ring_proximal_lvs',
                            'ring_proximal_rvs','r_bofoot','r_femur','r_fibula','r_foot',
                            'r_patella','r_pelvis','r_talus','r_tibia','sacrum','scaphoid_lvs',
                            'scaphoid_rvs','thumb_distal_lvs','thumb_distal_rvs',
                            'thumb_proximal_lvs','thumb_proximal_rvs','trapezium_lvs',
                            'trapezium_rvs','trapezoid_lvs','trapezoid_rvs','triquetrum_lvs',
                            'triquetrum_rvs','ulna_lv','ulna_rv']
            else:
                raise ValueError("Geometries not available for this model, please contact us")                
            for vtpName in vtpNames:
                url = 'https://mc-opencap-public.s3.us-west-2.amazonaws.com/geometries_vtp/{}/{}.vtp'.format(modelType, vtpName)
                filename = os.path.join(geometryDir, '{}.vtp'.format(vtpName))                
                download_file(url, filename)
        geometryDirEnd = os.path.join(session_path, 'OpenSimData', 'Model', 'Geometry')
        shutil.copytree(geometryDir, geometryDirEnd)
    except:
        pass
    
    # Zip   
    def zipdir(path, ziph):
        # ziph is zipfile handle
        for root, dirs, files in os.walk(path):
            for file in files:
                ziph.write(os.path.join(root, file), 
                           os.path.relpath(os.path.join(root, file), 
                                           os.path.join(path, '..')))
    
    session_zip = '{}.zip'.format(session_path)

    if os.path.isfile(session_zip):
        os.remove(session_zip)
  
    zipf = zipfile.ZipFile(session_zip, 'w', zipfile.ZIP_DEFLATED)
    zipdir(session_path, zipf)
    zipf.close()
    
    # write zip as a result to last trial for now
    if writeToDjango:
        postFileToTrial(session_zip,dynamic_ids[-1],tag='session_zip',device_id='all', host=host)
    
    if deleteFolderWhenZipped:
        if os.path.exists(session_path):
            shutil.rmtree(session_path)
    #if os.path.exists(session_zip):
    #    os.remove(session_zip)
    
    return session_zip

# test session
# downloadAndZipSession('9557d441-8da1-408e-938f-7fb66225c9a5')
# test=1
