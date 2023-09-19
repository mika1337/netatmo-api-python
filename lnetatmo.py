# Published Jan 2013
# Author : Philippe Larduinat, ph.larduinat@wanadoo.fr
# Multiple contributors : see https://github.com/philippelt/netatmo-api-python
# License : GPL V3
"""
This API provides access to the Netatmo weather station or/and the Welcome camera
This package can be used with Python2 or Python3 applications and do not
require anything else than standard libraries

PythonAPI Netatmo REST data access
coding=utf-8
"""

import warnings
if __name__ == "__main__": warnings.filterwarnings("ignore") # For installation test only

from sys import version_info
from os import getenv
from os.path import expanduser, exists
import json, time
import imghdr
import warnings
import logging

# Just in case method could change
PYTHON3 = (version_info.major > 2)

# HTTP libraries depends upon Python 2 or 3
if PYTHON3 :
    import urllib.parse, urllib.request
else:
    from urllib import urlencode
    import urllib2


######################## AUTHENTICATION INFORMATION ######################

# To be able to have a program accessing your netatmo data, you have to register your program as
# a Netatmo app in your Netatmo account. All you have to do is to give it a name (whatever) and you will be
# returned a client_id and secret that your app has to supply to access netatmo servers.

#########################################################################


# Common definitions

_BASE_URL = "https://api.netatmo.com/"
_AUTH_REQ              = _BASE_URL + "oauth2/token"
_GETMEASURE_REQ        = _BASE_URL + "api/getmeasure"
_GETSTATIONDATA_REQ    = _BASE_URL + "api/getstationsdata"
_GETTHERMOSTATDATA_REQ = _BASE_URL + "api/getthermostatsdata"
_GETHOMEDATA_REQ       = _BASE_URL + "api/gethomedata"
_GETCAMERAPICTURE_REQ  = _BASE_URL + "api/getcamerapicture"
_GETEVENTSUNTIL_REQ    = _BASE_URL + "api/geteventsuntil"
_HOMESDATA_REQ         = _BASE_URL + "api/homesdata"
_HOMESTATUS_REQ        = _BASE_URL + "api/homestatus"


#TODO# Undocumented (but would be very usefull) API : Access currently forbidden (403)

_POST_UPDATE_HOME_REQ  = _BASE_URL + "/api/updatehome"

# For presence setting (POST BODY):
# _PRES_BODY_REC_SET     = "home_id=%s&presence_settings[presence_record_%s]=%s"   # (HomeId, DetectionKind, DetectionSetup.index)
_PRES_DETECTION_KIND   = ("humans", "animals", "vehicles", "movements")
_PRES_DETECTION_SETUP  = ("ignore", "record", "record & notify")

# _PRES_BODY_ALERT_TIME  = "home_id=%s&presence_settings[presence_notify_%s]=%s"   # (HomeID, "from"|"to", "hh:mm")

# Regular (documented) commands (both cameras)

_PRES_CDE_GET_SNAP     = "/live/snapshot_720.jpg"

#TODO# Undocumented (taken from https://github.com/KiboOst/php-NetatmoCameraAPI/blob/master/class/NetatmoCameraAPI.php)
# Work with local_url only (undocumented scope control probably)

# For Presence camera

_PRES_CDE_GET_LIGHT    = "/command/floodlight_get_config"
# Not working yet, probably due to scope restriction
#_PRES_CDE_SET_LIGHT    = "/command/floodlight_set_config?config=mode:%s"    # "auto"|"on"|"off"


# For all cameras

_CAM_CHANGE_STATUS     = "/command/changestatus?status=%s"            # "on"|"off"
# Not working yet
#_CAM_FTP_ACTIVE        = "/command/ftp_set_config?config=on_off:%s"   # "on"|"off"

# UNITS used by Netatmo services
UNITS = {
    "unit" : {
        0: "metric",
        1: "imperial"
    },
    "windunit" : {
        0: "kph",
        1: "mph",
        2: "ms",
        3: "beaufort",
        4: "knot"
    },
    "pressureunit" : {
        0: "mbar",
        1: "inHg",
        2: "mmHg"
    }
}

# Logger context
logger = logging.getLogger("lnetatmo")


class NoDevice( Exception ):
    pass


class NoHome( Exception ):
    pass


class AuthFailure( Exception ):
    pass

class TokenError( Exception ):
    pass

class AccessToken:
    def __init__( self, client_id, client_secret, access_token, refresh_token, expiration_time ):
        self._client_id     = client_id
        self._client_secret = client_secret
        self._access_token  = access_token
        self._refresh_token = refresh_token
        self._expiration_time = expiration_time

    def getAccessToken( self ):
        if self._expiration_time < time.time(): # Token should be renewed
            postParams = {
                    "grant_type"    : "refresh_token",
                    "refresh_token" : self._refresh_token,
                    "client_id"     : self._client_id,
                    "client_secret" : self._client_secret
                    }
            resp = postRequest(_AUTH_REQ, postParams)
            self._access_token    = resp['access_token']
            self._refresh_token   = resp['refresh_token']
            self._expiration_time = int(resp['expire_in'] + time.time())
        return self._access_token

def generateToken( client_id, client_secret, refresh_token ):
    # Initialize token
    access_token = AccessToken( client_id, client_secret, None, refresh_token, 0 )

    # Force token refresh
    access_token.getAccessToken()

    return access_token


def saveTokenToFile( token, filename ):
    if not isinstance( token, AccessToken):
        raise ValueError( 'Token is not an access token, not writing file' )
    with open(filename, 'w') as f:
        json.dump( token.__dict__, f )

def loadTokenFromFile( filename ):
    with open(filename, 'r') as f:
        token_data = json.load( f )
        return AccessToken( token_data['_client_id'], token_data['_client_secret']
                          , token_data['_access_token'], token_data['_refresh_token']
                          , token_data['_expiration_time'] )

class User:
    """
    This class returns basic information about the user

    Args:
        token: Access token
    """
    warnings.warn("The 'User' class is no longer maintained by Netatmo",
            DeprecationWarning )
    def __init__(self, token):
        postParams = {
                "access_token" : token.getAccessToken()
                }
        resp = postRequest(_GETSTATIONDATA_REQ, postParams)
        self.rawData = resp['body']
        self.devList = self.rawData['devices']
        self.ownerMail = self.rawData['user']['mail']


class UserInfo:
    """
    This class is populated with data from various Netatmo requests to provide
    complimentary data (eg Units for Weatherdata)
    """
    pass


class ThermostatData:
    """
    List the Thermostat and temperature modules

    Args:
        token: Access token
        home : Home name or id of the home who's thermostat belongs to
    """
    def __init__(self, token, home=None):

        # I don't own a thermostat thus I am not able to test the Thermostat support
        warnings.warn("The Thermostat code is not tested due to the lack of test environment.\n" \
                      "As Netatmo is continuously breaking API compatibility, risk that current bindings are wrong is high.\n" \
                      "Please report found issues (https://github.com/philippelt/netatmo-api-python/issues)",
                       RuntimeWarning )

        postParams = {
                "access_token" : token.getAccessToken()
                }
        resp = postRequest(_GETTHERMOSTATDATA_REQ, postParams)
        self.rawData = resp['body']['devices']
        if not self.rawData : raise NoDevice("No thermostat available")
        self.thermostatData = filter_home_data(self.rawData, home)
        if not self.thermostatData : raise NoHome("No home %s found" % home)
        self.thermostatData['name'] = self.thermostatData['home_name']
        for m in self.thermostatData['modules']:
            m['name'] = m['module_name']
        self.defaultThermostat = self.thermostatData['home_name']
        self.defaultThermostatId = self.thermostatData['_id']
        self.defaultModule = self.thermostatData['modules'][0]

    def getThermostat(self, name=None):
        if ['name'] != name: return None
        else: return 
        return self.thermostat[self.defaultThermostatId]

    def moduleNamesList(self, name=None, tid=None):
        thermostat = self.getThermostat(name=name, tid=tid)
        return [m['name'] for m in thermostat['modules']] if thermostat else None

    def getModuleByName(self, name, thermostatId=None):
        thermostat = self.getThermostat(tid=thermostatId)
        for m in thermostat['modules']:
            if m['name'] == name: return m
        return None

class WeatherStationsData:
    """
    List the Weather Station devices (stations and modules)

    Args:
        token: Access token
    """
    def __init__(self, token, stationName=None):
        postParams = {
                "access_token" : token.getAccessToken()
                }
        resp = postRequest(_GETSTATIONDATA_REQ, postParams)

        # Weather data
        self.stations = dict()
        self.default_station_id = None

        self.rawData = resp['body']['devices']
        if self.rawData:
            for device in self.rawData:
                if device['station_name'] == stationName:
                    self.default_station_id = device['_id']

                modules = dict()
                if 'modules' in device:
                    for module in device['modules']:
                        modules[module['_id']] = module

                self.stations[device['_id']] = device
                self.stations[device['_id']]['modules'] = modules

        if self.default_station_id == None:
            if stationName != None:
                raise NoDevice("No station with name %s" % stationName)
            else:
                self.default_station_id = next(iter(self.stations.keys()))

        # User data
        userData = resp['body']['user']
        self.user = UserInfo()
        setattr(self.user, "mail", userData['mail'])
        for k,v in userData['administrative'].items():
            if k in UNITS:
                setattr(self.user, k, UNITS[k][v])
            else:
                setattr(self.user, k, v)

    def stationById(self, sid):
        return self.stations.get(sid)

    def stationByName(self, stationName=None):
        if not stationName:
            return self.stations[self.default_station_id]

        for i,s in self.stations.items():
            if s['station_name'] == stationName :
                return self.stations[i]

        raise NoDevice("No station with name %s" % stationName)

    def modulesIdsList(self, stationName=None):
        station = self.stationByName(stationName)
        res = list(station['modules'].keys())
        res.append(station['_id'])
        return res

    def modulesNamesList(self, stationName=None):
        station = self.stationByName(stationName)
        res = [m['module_name'] for m in station['modules'].values()]
        res.append(station['module_name'])
        return res

    def moduleByName(self, moduleName, stationName=None ):
        station = self.stationByName(stationName)
        import pprint
        if station['module_name'] == moduleName:
            return station
        for module in station['modules'].values():
            if module['module_name'] == moduleName :
                return module

        raise NoDevice("No module with name %s" % moduleName)

    def moduleById(self, moduleId, stationName=None ):
        station = self.stationByName(stationName)
        if station['_id'] == moduleId:
            return station

        for module in station['modules'].values():
            if module['_id'] == moduleId :
                return module

        raise NoDevice("No module with id %s" % moduleId)

    def lastData(self, exclude=0):
        s = self.default_station_data
        # Breaking change from Netatmo : dashboard_data no longer available if station lost
        if not s or 'dashboard_data' not in s : return None
        lastD = dict()
        # Define oldest acceptable sensor measure event
        limit = (time.time() - exclude) if exclude else 0
        ds = s['dashboard_data']
        if ds.get('time_utc',limit+10) > limit :
            lastD[s['module_name']] = ds.copy()
            lastD[s['module_name']]['When'] = lastD[s['module_name']].pop("time_utc") if 'time_utc' in lastD[s['module_name']] else time.time()
            lastD[s['module_name']]['wifi_status'] = s['wifi_status']
        if 'modules' in s:
            for module in s["modules"]:
                # Skip lost modules that no longer have dashboard data available
                if 'dashboard_data' not in module : continue
                ds = module['dashboard_data']
                if ds.get('time_utc',limit+10) > limit :
                    # If no module_name has been setup, use _id by default
                    if "module_name" not in module : module['module_name'] = module["_id"]
                    lastD[module['module_name']] = ds.copy()
                    lastD[module['module_name']]['When'] = lastD[module['module_name']].pop("time_utc") if 'time_utc' in lastD[module['module_name']] else time.time()
                    # For potential use, add battery and radio coverage information to module data if present
                    for i in ('battery_vp', 'battery_percent', 'rf_status') :
                        if i in module : lastD[module['module_name']][i] = module[i]
        return lastD

    def checkNotUpdated(self, delay=3600):
        res = self.lastData()
        ret = []
        for mn,v in res.items():
            if time.time()-v['When'] > delay:
                ret.append(mn)
        return ret if ret else None

    def checkUpdated(self, delay=3600):
        res = self.lastData()
        ret = []
        for mn,v in res.items():
            if time.time()-v['When'] < delay:
                ret.append(mn)
        return ret if ret else None

    def getMeasure(self, device_id, scale, mtype, module_id=None, date_begin=None, date_end=None, limit=None, optimize=False, real_time=False):
        postParams = { "access_token" : self.getAuthToken }
        postParams['device_id']  = device_id
        if module_id : postParams['module_id'] = module_id
        postParams['scale']      = scale
        postParams['type']       = mtype
        if date_begin : postParams['date_begin'] = date_begin
        if date_end : postParams['date_end'] = date_end
        if limit : postParams['limit'] = limit
        postParams['optimize'] = "true" if optimize else "false"
        postParams['real_time'] = "true" if real_time else "false"
        return postRequest(_GETMEASURE_REQ, postParams)

    def MinMaxTH(self, module=None, frame="last24"):
        s = self.default_station_data
        if frame == "last24":
            end = time.time()
            start = end - 24*3600 # 24 hours ago
        elif frame == "day":
            start, end = todayStamps()
        if module and module != s['module_name']:
            m = self.moduleById(module) or self.moduleByName(module)
            if not m : raise NoDevice("Can't find module %s" % module)
            # retrieve module's data
            resp = self.getMeasure(
                    device_id  = s['_id'],
                    module_id  = m['_id'],
                    scale      = "max",
                    mtype      = "Temperature,Humidity",
                    date_begin = start,
                    date_end   = end)
        else : # retrieve station's data
            resp = self.getMeasure(
                    device_id  = s['_id'],
                    scale      = "max",
                    mtype      = "Temperature,Humidity",
                    date_begin = start,
                    date_end   = end)
        if resp:
            T = [v[0] for v in resp['body'].values()]
            H = [v[1] for v in resp['body'].values()]
            return min(T), max(T), min(H), max(H)
        else:
            return None

class HomesData:
    """
    List the Netatmo actual topology and static information of all devices present
    into a user account. It is also possible to specify a home_id to focus on one home.

    Args:
        token: Access token
        homeId : Home id of the home who's status is requested
    """
    def __init__(self, token, homeId=None):
        postParams = {
            "access_token" : token.getAccessToken()
            }
        if homeId:
            postParams['home_id'] = homeId
        resp = postRequest(_HOMESDATA_REQ, postParams)
        self.rawData = resp['body']

        # Collect homes
        self.homes = dict()
        for home in self.rawData['homes']:
            self.homes[home['id']] = dict()
            self.homes[home['id']]['raw_data'] = home

            self.homes[home['id']]['id'  ] = home['id']
            self.homes[home['id']]['name'] = home['name']

            self.homes[home['id']]['rooms'] = dict()
            for room in home['rooms']:
                self.homes[home['id']]['rooms'][room['id']] = room

            self.homes[home['id']]['modules'] = dict()
            for module in home['modules']:
                self.homes[home['id']]['modules'][module['id']] = module

    def homesIdList(self):
        return list(self.homes.keys())

    def homesNamesList(self):
        return [h['name'] for h in self.homes.values()]

    def homeById(self,homeId):
        return self.homes[homeId]['raw_data']

    def homeByName(self,homeName):
        for home in self.homes.values():
            if home['name'] == homeName:
                return home
        raise NoDevice("No home with name %s" % homeName)

    def roomsIdList(self,homeId):
        return list(self.homes[homeId]['rooms'].keys())

    def roomById(self,homeId,roomId):
        return self.homes[homeId]['rooms'][roomId]

    def roomByName(self,homeId,roomName):
        for room in self.homes[homeId]['rooms'].values():
            if room['name'] == roomName:
                return room
        raise NoDevice("No room with name %s" % roomName)

    def modulesIdList(self,homeId):
        return list(self.homes[homeId]['modules'].keys())

    def moduleById(self,homeId,moduleId):
        return self.homes[homeId]['modules'][moduleId]

class HomeStatus:
    """
    List the Netatmo home status of all devices present into a specific home.

    Args:
        token: Access token
        homeId : Home id of the home who's status is requested
    """
    def __init__(self, token, homeId):
        postParams = {
            "access_token" : token.getAccessToken(),
            "home_id" : homeId
            }
        resp = postRequest(_HOMESTATUS_REQ, postParams)
        self.rawData = resp['body']

        # Collect rooms
        self.rooms = dict()
        if 'rooms' not in self.rawData['home']:
            raise NoDevice("No home room data available")
        for room in self.rawData['home']['rooms']:
            self.rooms[room['id']] = room

        # Collect modules
        self.modules = dict()
        if 'modules' not in self.rawData['home']:
            raise NoDevice("No home module data available")
        for module in self.rawData['home']['modules']:
            self.modules[module['id']] = module

    def roomsIdList(self):
        return list(self.rooms.keys())

    def roomById(self,rid):
        return self.rooms[rid]

    def modulesIdList(self):
        return list(self.modules.keys())

    def moduleById(self,mid):
        return self.modules[mid]

class HomeData:
    """
    List the Netatmo home informations (Homes, cameras, events, persons)
    This class is now deprecated. Use HomesData/HomeStatus instead

    Args:
        token: Access token
    """
    warnings.warn("The 'WelcomeData' class was renamed 'HomeData' to handle new Netatmo Home capabilities",
            DeprecationWarning )

    def __init__(self, token, home=None):
        postParams = {
            "access_token" : token.getAccessToken()
            }
        resp = postRequest(_GETHOMEDATA_REQ, postParams)
        self.rawData = resp['body']
        # Collect homes
        self.homes = { d['id'] : d for d in self.rawData['homes'] }
        if not self.homes : raise NoDevice("No home available")
        self.default_home = home or list(self.homes.values())[0]['name']
        # Split homes data by category
        self.persons = dict()
        self.events = dict()
        self.cameras = dict()
        self.lastEvent = dict()
        for i in range(len(self.rawData['homes'])):
            curHome = self.rawData['homes'][i]
            nameHome = curHome['name']
            if nameHome not in self.cameras:
                self.cameras[nameHome] = dict()
            if 'persons' in curHome:
                for p in curHome['persons']:
                    self.persons[ p['id'] ] = p
            if 'events' in curHome:
                    for e in curHome['events']:
                        if e['camera_id'] not in self.events:
                            self.events[ e['camera_id'] ] = dict()
                        self.events[ e['camera_id'] ][ e['time'] ] = e
            if 'cameras' in curHome:
                for c in curHome['cameras']:
                    self.cameras[nameHome][ c['id'] ] = c
                    c["home_id"] = curHome['id']
        for camera in self.events:
            self.lastEvent[camera] = self.events[camera][sorted(self.events[camera])[-1]]
        if not self.cameras[self.default_home] : raise NoDevice("No camera available in default home")
        self.default_camera = list(self.cameras[self.default_home].values())[0]

    def homeById(self, hid):
        return None if hid not in self.homes else self.homes[hid]

    def homeByName(self, home=None):
        if not home: home = self.default_home
        for key,value in self.homes.items():
            if value['name'] == home:
                return self.homes[key]

    def cameraById(self, cid):
        for home,cam in self.cameras.items():
            if cid in self.cameras[home]:
                return self.cameras[home][cid]
        return None

    def cameraByName(self, camera=None, home=None):
        if not camera and not home:
            return self.default_camera
        elif home and camera:
            if home not in self.cameras:
                return None
            for cam_id in self.cameras[home]:
                if self.cameras[home][cam_id]['name'] == camera:
                    return self.cameras[home][cam_id]
        elif not home and camera:
            for home, cam_ids in self.cameras.items():
                for cam_id in cam_ids:
                    if self.cameras[home][cam_id]['name'] == camera:
                        return self.cameras[home][cam_id]
        else:
            return list(self.cameras[home].values())[0]
        return None

    def cameraUrls(self, camera=None, home=None, cid=None):
        """
        Return the vpn_url and the local_url (if available) of a given camera
        in order to access to its live feed
        Can't use the is_local property which is mostly false in case of operator
        dynamic IP change after presence start sequence
        """
        local_url = None
        vpn_url = None
        if cid:
            camera_data=self.cameraById(cid)
        else:
            camera_data=self.cameraByName(camera=camera, home=home)
        if camera_data:
            vpn_url = camera_data['vpn_url']
            resp = postRequest(vpn_url + '/command/ping')
            temp_local_url=resp['local_url']
            try:
                resp = postRequest(temp_local_url + '/command/ping',timeout=1)
                if resp and temp_local_url == resp['local_url']:
                    local_url = temp_local_url
            except:  # On this particular request, vithout errors from previous requests, error is timeout
                local_url = None
        return vpn_url, local_url

    def url(self, camera=None, home=None, cid=None):
        vpn_url, local_url = self.cameraUrls(camera, home, cid)
        # Return local if available else vpn
        return local_url or vpn_url

    def personsAtHome(self, home=None):
        """
        Return the list of known persons who are currently at home
        """
        if not home: home = self.default_home
        home_data = self.homeByName(home)
        atHome = []
        for p in home_data['persons']:
            #Only check known persons
            if 'pseudo' in p:
                if not p["out_of_sight"]:
                    atHome.append(p['pseudo'])
        return atHome

    def getCameraPicture(self, image_id, key):
        """
        Download a specific image (of an event or user face) from the camera
        """
        postParams = {
            "access_token" : self.getAuthToken,
            "image_id" : image_id,
            "key" : key
            }
        resp = postRequest(_GETCAMERAPICTURE_REQ, postParams)
        image_type = imghdr.what('NONE.FILE',resp)
        return resp, image_type

    def getProfileImage(self, name):
        """
        Retrieve the face of a given person
        """
        for p in self.persons:
            if 'pseudo' in self.persons[p]:
                if name == self.persons[p]['pseudo']:
                    image_id = self.persons[p]['face']['id']
                    key = self.persons[p]['face']['key']
                    return self.getCameraPicture(image_id, key)
        return None, None

    def updateEvent(self, event=None, home=None):
        """
        Update the list of event with the latest ones
        """
        if not home: home=self.default_home
        if not event:
            #If not event is provided we need to retrieve the oldest of the last event seen by each camera
            listEvent = dict()
            for cam_id in self.lastEvent:
                listEvent[self.lastEvent[cam_id]['time']] = self.lastEvent[cam_id]
            event = listEvent[sorted(listEvent)[0]]

        home_data = self.homeByName(home)
        postParams = {
            "access_token" : self.getAuthToken,
            "home_id" : home_data['id'],
            "event_id" : event['id']
        }
        resp = postRequest(_GETEVENTSUNTIL_REQ, postParams)
        eventList = resp['body']['events_list']
        for e in eventList:
            self.events[ e['camera_id'] ][ e['time'] ] = e
        for camera in self.events:
            self.lastEvent[camera]=self.events[camera][sorted(self.events[camera])[-1]]

    def personSeenByCamera(self, name, home=None, camera=None):
        """
        Return True if a specific person has been seen by a camera
        """
        try:
            cam_id = self.cameraByName(camera=camera, home=home)['id']
        except TypeError:
            logger.warning("personSeenByCamera: Camera name or home is unknown")
            return False
        #Check in the last event is someone known has been seen
        if self.lastEvent[cam_id]['type'] == 'person':
            person_id = self.lastEvent[cam_id]['person_id']
            if 'pseudo' in self.persons[person_id]:
                if self.persons[person_id]['pseudo'] == name:
                    return True
        return False

    def _knownPersons(self):
        known_persons = dict()
        for p_id,p in self.persons.items():
            if 'pseudo' in p:
                known_persons[ p_id ] = p
        return known_persons

    def someoneKnownSeen(self, home=None, camera=None):
        """
        Return True if someone known has been seen
        """
        try:
            cam_id = self.cameraByName(camera=camera, home=home)['id']
        except TypeError:
            logger.warning("personSeenByCamera: Camera name or home is unknown")
            return False
        #Check in the last event is someone known has been seen
        if self.lastEvent[cam_id]['type'] == 'person':
            if self.lastEvent[cam_id]['person_id'] in self._knownPersons():
                return True
        return False

    def someoneUnknownSeen(self, home=None, camera=None):
        """
        Return True if someone unknown has been seen
        """
        try:
            cam_id = self.cameraByName(camera=camera, home=home)['id']
        except TypeError:
            logger.warning("personSeenByCamera: Camera name or home is unknown")
            return False
        #Check in the last event is someone known has been seen
        if self.lastEvent[cam_id]['type'] == 'person':
            if self.lastEvent[cam_id]['person_id'] not in self._knownPersons():
                return True
        return False

    def motionDetected(self, home=None, camera=None):
        """
        Return True if movement has been detected
        """
        try:
            cam_id = self.cameraByName(camera=camera, home=home)['id']
        except TypeError:
            logger.warning("personSeenByCamera: Camera name or home is unknown")
            return False
        if self.lastEvent[cam_id]['type'] == 'movement':
            return True
        return False

    def presenceUrl(self, camera=None, home=None, cid=None, setting=None):
        camera = self.cameraByName(home=home, camera=camera) or self.cameraById(cid=cid)
        if camera["type"] != "NOC": return None # Not a presence camera
        vpnUrl, localUrl = self.cameraUrls(cid=camera["id"])
        return localUrl
    
    def presenceLight(self, camera=None, home=None, cid=None, setting=None):
        url = self.presenceUrl(home=home, camera=camera) or self.cameraById(cid=cid)
        if not url or setting not in ("on", "off", "auto"): return None
        if setting : return "Currently unsupported"
        return cameraCommand(url, _PRES_CDE_GET_LIGHT)["mode"]
        # Not yet supported
        #if not setting: return cameraCommand(url, _PRES_CDE_GET_LIGHT)["mode"]
        #else: return cameraCommand(url, _PRES_CDE_SET_LIGHT, setting)

    def presenceStatus(self, mode, camera=None, home=None, cid=None):
        url = self.presenceUrl(home=home, camera=camera) or self.cameraById(cid=cid)
        if not url or mode not in ("on", "off") : return None
        r = cameraCommand(url, _CAM_CHANGE_STATUS, mode)
        return mode if r["status"] == "ok" else None

    def presenceSetAction(self, camera=None, home=None, cid=None,
                          eventType=_PRES_DETECTION_KIND[0], action=2):
        return "Currently unsupported"
        if eventType not in _PRES_DETECTION_KIND or \
           action not in _PRES_DETECTION_SETUP : return None
        camera = self.cameraByName(home=home, camera=camera) or self.cameraById(cid=cid)
        postParams = { "access_token" : self.getAuthToken,
                       "home_id" : camera["home_id"],
                       "presence_settings[presence_record_%s]" % eventType : _PRES_DETECTION_SETUP.index(action)
                     }
        resp = postRequest(_POST_UPDATE_HOME_REQ, postParams)
        self.rawData = resp['body']

    def getLiveSnapshot(self, camera=None, home=None, cid=None):
        camera = self.cameraByName(home=home, camera=camera) or self.cameraById(cid=cid)
        vpnUrl, localUrl = self.cameraUrls(cid=camera["id"])
        url = localUrl or vpnUrl
        return cameraCommand(url, _PRES_CDE_GET_SNAP)


class WelcomeData(HomeData):
    """
    This class is now deprecated. Use HomeData instead
    Home can handle many devices, not only Welcome cameras
    """
    warnings.warn("The 'WelcomeData' class was renamed 'HomeData' to handle new Netatmo Home capabilities",
            DeprecationWarning )
    pass

# Utilities routines


def filter_home_data(rawData, home):
    if home:
        # Find a home who's home id or name is the one requested
        for h in rawData:
            if h["home_name"] == home or h["home_id"] == home:
                return h
        return None
    # By default, the first home is returned
    return rawData[0]

def cameraCommand(cameraUrl, commande, parameters=None, timeout=3):
    url = cameraUrl + ( commande % parameters if parameters else commande)
    return postRequest(url, timeout=timeout)
    
def postRequest(url, params=None, timeout=30):
    if PYTHON3:
        req = urllib.request.Request(url)
        if params:
            req.add_header("Content-Type","application/x-www-form-urlencoded;charset=utf-8")
            params = urllib.parse.urlencode(params).encode('utf-8')
        try:
            resp = urllib.request.urlopen(req, params, timeout=timeout) if params else urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as err:
            logger.error("code=%s, reason=%s" % (err.code, err.reason))
            return None
    else:
        if params:
            params = urlencode(params)
            headers = {"Content-Type" : "application/x-www-form-urlencoded;charset=utf-8"}
        req = urllib2.Request(url=url, data=params, headers=headers) if params else urllib2.Request(url)
        try:
            resp = urllib2.urlopen(req, timeout=timeout)
        except urllib2.HTTPError as err:
            logger.error("code=%s, reason=%s" % (err.code, err.reason))
            return None
    data = b""
    for buff in iter(lambda: resp.read(65535), b''): data += buff
    # Return values in bytes if not json data to handle properly camera images
    returnedContentType = resp.getheader("Content-Type") if PYTHON3 else resp.info()["Content-Type"]
    return json.loads(data.decode("utf-8")) if "application/json" in returnedContentType else data

def toTimeString(value):
    return time.strftime("%Y-%m-%d_%H:%M:%S", time.localtime(int(value)))

def toEpoch(value):
    return int(time.mktime(time.strptime(value,"%Y-%m-%d_%H:%M:%S")))

def todayStamps():
    today = time.strftime("%Y-%m-%d")
    today = int(time.mktime(time.strptime(today,"%Y-%m-%d")))
    return today, today+3600*24

# Global shortcut

def getStationMinMaxTH(station=None, module=None, home=None):
    authorization = ClientAuth()
    devList = WeatherStationData(authorization, station=station, home=home)
    if module == "*":
        pass
    elif module:
        module = devList.moduleById(module) or devList.moduleByName(module)
        if not module: raise NoDevice("No such module %s" % module)
        else: module = module["module_name"]
    else:
        module = list(devList.modules.values())[0]["module_name"]
    lastD = devList.lastData()
    if module == "*":
        result = dict()
        for m in lastD.keys():
            if time.time()-lastD[m]['When'] > 3600 : continue
            r = devList.MinMaxTH(module=m)
            result[m] = (r[0], lastD[m]['Temperature'], r[1])
    else:
        if time.time()-lastD[module]['When'] > 3600 : result = ["-", "-"]
        else : 
            result = [lastD[module]['Temperature'], lastD[module]['Humidity']]
            result.extend(devList.MinMaxTH(module))
    return result


# auto-test when executed directly
def selfTest():
    from sys import exit, stdout, stderr
    
    logging.basicConfig(format='%(name)s - %(levelname)s: %(message)s', level=logging.INFO)

    if not _CLIENT_ID or not _CLIENT_SECRET or not _USERNAME or not _PASSWORD :
           stderr.write("Library source missing identification arguments to check lnetatmo.py (user/password/etc...)")
           exit(1)

    authorization = ClientAuth()  # Test authentication method
    
    try:
        weatherStation = WeatherStationsData(authorization)         # Test DEVICELIST
    except NoDevice:
        logger.warning("No weather station available for testing")
    else:
        weatherStation.MinMaxTH()                          # Test GETMEASUR

    try:
        homes = HomeData(authorization)
    except NoDevice :
        logger.warning("No home available for testing")

    try:
        thermostat = ThermostatData(authorization)
    except NoDevice:
        logger.warning("No thermostat avaible for testing")

    # If we reach this line, all is OK
    logger.info("OK")

if __name__ == "__main__":
    import sys
    from getpass import getpass

    logging.basicConfig(level=logging.DEBUG)

    if len(sys.argv) != 5:
        logger.info(f'To generate token file: {sys.argv[0]} <client id> <client secret> <refresh token> <new token file>')
        sys.exit(1)
    else:
        client_id = sys.argv[1]
        client_secret = sys.argv[2]
        refresh_token = sys.argv[3]
        token_file = sys.argv[4]

        token = generateToken( client_id, client_secret, refresh_token )
        saveTokenToFile( token, token_file )