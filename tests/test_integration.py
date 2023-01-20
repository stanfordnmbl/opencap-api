import unittest
import requests

class TestIntegration(unittest.TestCase):
    def test_integration(self):
#        api_url = "https://mobilecap.kidzinski.com"
        api_url = "http://127.0.0.1:8000"

        # create a session
        r = requests.get('{}/sessions/new/'.format(api_url))
        res = r.json()

        # get session ID (pretend it's from a QR code)
        session_id = res[0]["id"]

        # start pinging the session
        device_id = "test_device"
        r = requests.get('{}/sessions/{}/status/?device_id={}'.format(api_url, session_id, device_id))
        self.assertEqual(r.json()["status"],"ready")

        # start recording in the session
        r = requests.get('{}/sessions/{}/record/'.format(api_url, session_id, device_id))
        self.assertEqual(r.json()["status"],"recording")

        # phone starts recording
        device_id = "test_device"
        r = requests.get('{}/sessions/{}/status/?device_id={}'.format(api_url, session_id, device_id))
        print(r.text)
        res = r.json()
        self.assertEqual(res["status"],"recording")
        video_url = api_url + res["video"]

        # stop recording in the session
        r = requests.get('{}/sessions/{}/stop/'.format(api_url, session_id, device_id))
        self.assertEqual(r.json()["status"],"stopped")

        # phone starts recording
        device_id = "test_device"
        r = requests.get('{}/sessions/{}/status/?device_id={}'.format(api_url, session_id, device_id))
        res = r.json()
        self.assertEqual(res["status"],"uploading")

        # phones submit data
        files = {
            'video': open('tests/data/left.mp4','rb')
        }
        data = {
            'parameters': "{}"
        }
        
        r = requests.patch(video_url, files=files, data=data)
        files["video"].close()
        self.assertEqual(r.status_code, 200)
        
        # after upload status should be changed to processing
        stauts = "uploading"
        r = requests.get('{}/sessions/{}/status/?device_id={}'.format(api_url, session_id, device_id))
        res = r.json()
        trial_url = res["trial"]
        self.assertEqual(res["status"], "processing")

        # submit results
        files = {
            'json': open('tests/data/test.json','rb'),
            'trc': open('tests/data/test.trc','rb'),
        }
        data = {
            "trial": "{}{}".format(api_url, trial_url),
        }
        r = requests.post('{}/results/'.format(api_url), data=data, files=files,)
        files["json"].close()
        files["trc"].close()
        self.assertEqual(r.status_code, 201)
        
        # status ready again
        r = requests.get('{}/sessions/{}/status/?device_id={}'.format(api_url, session_id, device_id))
        res = r.json()
        self.assertEqual(res["status"], "ready")

if __name__ == '__main__':
    unittest.main()
