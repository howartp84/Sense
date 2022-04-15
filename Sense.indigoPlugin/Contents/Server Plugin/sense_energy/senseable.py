import json
import requests
from requests.exceptions import ReadTimeout
from websocket import create_connection
from websocket._exceptions import WebSocketTimeoutException

from .sense_api import *
from .sense_exceptions import *

class Senseable(SenseableBase):

    def authenticate(self, username, password, rateLimit):
        auth_data = {
            "email": username,
            "password": password
        }
        self.rate_limit = int(rateLimit)

        # Create session
        self.s = requests.session()

        # Get auth token
        try:
            response = self.s.post(API_URL+'authenticate',
                                   auth_data, timeout=self.api_timeout)
        except Exception as e:
            raise Exception('Connection failure: {}'.format(e))

        # check for 200 return
        if response.status_code != 200:
            raise SenseAuthenticationException(
                "Please check username and password. API Return Code: {}".format(response.status_code))

        self.set_auth_data(response.json())

        return "Rate limit is: {}".format(self.rate_limit)

    # Update the realtime data
    def update_realtime(self):
        # rate limit API calls
        if self._realtime and self.rate_limit and \
           self.last_realtime_call + self.rate_limit > time():
            return self._realtime
        url = WS_URL.format(self.sense_monitor_id, self.sense_access_token)
        next(self.get_realtime_stream())

    def getRealtimeCall(self):
        return self.last_realtime_call

    def get_realtime_stream(self):
        """ Reads realtime data from websocket
            Continues until loop broken"""
        ws = 0
        url = WS_URL.format(self.sense_monitor_id, self.sense_access_token)
        try:
            ws = create_connection(url, timeout=self.wss_timeout)
            while True: # hello, features, [updates,] data
                result = json.loads(ws.recv())
                if result.get('type') == 'realtime_update':
                    data = result['payload']
                    self.set_realtime(data)
                    yield data
        except WebSocketTimeoutException:
            raise SenseAPITimeoutException("API websocket timed out")
        finally:
            if ws: ws.close()

    def get_trend_data(self, scale):
        if scale.upper() not in valid_scales:
            raise Exception("{} not a valid scale".format(scale))
        t = datetime.now().replace(hour=12)
        self._trend_data[scale] = self.api_call('app/history/trends?monitor_id={}&scale={}&start={}'.format(self.sense_monitor_id, scale, t.isoformat()))

    def update_trend_data(self):
        for scale in valid_scales:
            self.get_trend_data(scale)

    def api_call(self, url, payload={}):
        try:
            return self.s.get(API_URL + url,
                              headers=self.headers,
                              timeout=self.api_timeout,
                              data=payload).json()
        except ReadTimeout:
            raise SenseAPITimeoutException("API call timed out")

    def get_discovered_device_names(self):
        # lots more info in here to be parsed out
        json = self.api_call('app/monitors/{}/devices'.format(self.sense_monitor_id))
        self._devices = [entry['name'] for entry in json]
        return self._devices

    def get_discovered_device_data(self):
        return self.api_call('monitors/{}/devices'.format(self.sense_monitor_id))

    def always_on_info(self):
        # Always on info - pretty generic similar to the web page
        return self.api_call('app/monitors/{}/devices/always_on'.format(self.sense_monitor_id))

    def get_monitor_info(self):
        # View info on your monitor & device detection status
        return self.api_call('app/monitors/{}/status'.format(self.sense_monitor_id))

    def get_device_info(self, device_id):
        # Get specific informaton about a device
        return self.api_call('app/monitors/{}/devices/{}'.format(self.sense_monitor_id, device_id))

    def get_notification_preferences(self):
        # Get notification preferences
        payload = {'monitor_id': '{}'.format(self.sense_monitor_id)}
        return self.api_call('users/{}/notifications'.format(self.sense_user_id, payload))

    def get_all_usage_data(self):
        payload = {'n_items': 30}
        # lots of info in here to be parsed out
        return self.s.get('users/{}/timeline'.format(self.sense_user_id))#, payload)


