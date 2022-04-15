#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################
# Copyright (c) 2016, Perceptive Automation, LLC. All rights reserved.
# http://www.indigodomo.com

import indigo

import os
import sys

from datetime import datetime

import json, requests

import sense_energy
from sense_energy.sense_exceptions import *

# Note the "indigo" module is automatically imported and made available inside
# our global name space by the host process.

################################################################################
class Plugin(indigo.PluginBase):
	########################################
	def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
		super(Plugin, self).__init__(pluginId, pluginDisplayName, pluginVersion, pluginPrefs)
		self.debug = pluginPrefs.get("showDebugInfo", False)
		self.version = pluginVersion

		self.rateLimit = pluginPrefs.get("rateLimit", 30)
		self.doSolar = bool(pluginPrefs.get("solarEnabled", False))
		self.folderID = pluginPrefs.get("folderID", None)

		self.devIDs = list()

		self.sidFromDev = dict()
		self.devFromSid = dict()

		self.rt  = dict() #RealTime

		self.dontStart = True

		self.csvPath = "{}/Preferences/Plugins/{}".format(indigo.server.getInstallFolderPath(), self.pluginId)

		self.csvActive = "{}/Preferences/Plugins/{}/activeLog.csv".format(indigo.server.getInstallFolderPath(), self.pluginId)
		self.csvDaily = "{}/Preferences/Plugins/{}/dailyLog.csv".format(indigo.server.getInstallFolderPath(), self.pluginId)

		if not os.path.exists(self.csvPath):
			os.mkdir(self.csvPath)
			csv_file = open(self.csvActive, 'w+')
			csv_file.write("Timestamp,power\n")
			csv_file.close()

	def validatePrefsConfigUi(self, valuesDict):
		fid = int(valuesDict["folderID"])
		if (fid in indigo.devices.folders):
			return True
		else:
			errorDict = indigo.Dict()
			errorDict["folderID"] = "This field should contain a folder ID"
			errorDict["showAlertText"] = "Folder not found with ID: {} \n\nEnsure you have used the ID, not the name of the folder.\n\nRight-click the folder you want to use and use 'Copy ID' to obtain the correct ID.".format(fid)
			return (False, valuesDict, errorDict)


	def closedPrefsConfigUi(self, valuesDict, userCancelled):
		# Since the dialog closed we want to set the debug flag - if you don't directly use
		# a plugin's properties (and for debugLog we don't) you'll want to translate it to
		# the appropriate stuff here.
		if not userCancelled:
			self.debug = valuesDict.get("showDebugInfo", False)
			if self.debug:
				indigo.server.log("Debug logging enabled")
			else:
				indigo.server.log("Debug logging disabled")
			self.rateLimit = int(valuesDict.get("rateLimit", 30))
			self.debugLog(self.sense.authenticate(str(valuesDict['username']), str(valuesDict['password']), self.rateLimit))
			self.doSolar = bool(valuesDict.get("solarEnabled", False))
			self.folderID = valuesDict.get("folderID", "")

			self.createCore()

			if (self.dontStart == False):
				self.getDevices()

	def createCore(self):
		try:
			self.debugLog("CreateCore")
			dev = indigo.device.create(indigo.kProtocol.Plugin,"Active Total","Active Total",deviceTypeId="sensedevice",folder=int(self.folderID))
			newStateList = [
				{'key':'id', 'value':'core'},
				{'key':'power', 'value':'0', 'uiValue':'0 w'}
				]
			dev.updateStatesOnServer(newStateList)
			#dev.updateStateOnServer(key='id', value='core')
			#dev.updateStateOnServer(key='power', value="0", uiValue="0 w")
			dev.updateStateImageOnServer(indigo.kStateImageSel.PowerOff)
			dev.stateListOrDisplayStateIdChanged()

			#Add it to self.devIDs
			devID = dev.id
			sID = "core"
			self.devIDs.append(sID)
			self.sidFromDev[int(devID)] = sID
			self.devFromSid[sID] = devID
		except ValueError as e:
			self.errorLog("Could not create Core device.")
			pass

	########################################
	def startup(self):
		self.debugLog(u"startup called")
		self.debugLog("Plugin version: {}".format(self.version))
		#self.debugLog(u"Creating senseable")
		self.sense = sense_energy.Senseable()
		self.debugLog(u"Authenticating...")
		self.debugLog(self.sense.authenticate(str(self.pluginPrefs['username']), str(self.pluginPrefs['password']), self.rateLimit))
		#for dev in indigo.devices.iter("self"):
			#indigo.device.delete(dev)

	def shutdown(self):
		self.debugLog(u"shutdown called")

	def deviceStartComm(self, dev):
		#self.debugLog("deviceStartComm called")
		dev.stateListOrDisplayStateIdChanged()
		#self.debugLog(dev)
		if (dev.deviceTypeId == "sensedevice"):
			devID = dev.id
			dName = dev.name
			sID = dev.states['id']
			if (sID != ""): #The state doesn't exist when the device is first created, so can't populate self.devIDs at this point
				self.devIDs.append(sID)
				self.sidFromDev[int(devID)] = sID
				self.devFromSid[sID] = devID
			#self.debugLog("Added device {} ({})".format(sID,dName)
			#self.debugLog(dev.states)
			#self.debugLog(str(self.devIDs))

	def deviceStopComm(self, dev):
		#self.debugLog("deviceStopComm called")
		if (dev.deviceTypeId == "sensedevice"):
			devID = dev.id
			sID = dev.states['id']
			dName = dev.name
			try:
				self.devIDs.remove(sID)
			except:
				pass
			self.sidFromDev.pop(int(devID),None)
			self.devFromSid.pop(sID,None)
			#self.debugLog("Removed device {} ({})".format(sID,dName))

	def getDevices(self):
		#self.debugLog("IDs: {}".format(self.devIDs))
		self.debugLog(u"Getting realtime()")
		try:
			#self.debugLog(u"132")
			self.sense.update_realtime()
			#self.debugLog(u"134")
			for i in self.sense._realtime['devices']:
				#self.debugLog(i)
				rtid = i['id'] #Get ID from RealTime devices
				self.rt[rtid] = int(i['w']) #Get power from RealTime devices
			#self.debugLog(u"138")
		except SenseAPITimeoutException as e:
			self.errorLog(e)
			return
		self.sense.update_trend_data()
		active = self.sense.active_power
		daily = self.sense.daily_usage
		self.debugLog("Active: {}w".format(active))
		self.debugLog("Daily: {}kw".format(daily))
		try:
			indigo.devices[self.devFromSid['core']].updateStateOnServer(key='power', value=str(int(active)), uiValue=str("{} w".format(int(active))))
			indigo.devices[self.devFromSid['core']].updateStateImageOnServer(indigo.kStateImageSel.PowerOn)
		except KeyError as e:
			self.debugLog("No Core device found - Attempting to recreate.")
			self.debugLog("Global Active and Daily stats will update on next refresh.")
			self.debugLog(e)
			self.createCore()

		lastUpdateTS = self.sense.getRealtimeCall()
		lastUpdate = datetime.fromtimestamp(lastUpdateTS).strftime("%Y-%m-%d %H:%M:%S.%f")
		self.debugLog("CSV Output: {},{}".format(lastUpdate,int(active)))
		csv_file = open(self.csvActive, 'a+')
		csv_file.write('{0},{1}\n'.format(lastUpdate, int(active)))
		csv_file.close()

		if (self.doSolar):
			self.debugLog("Active Solar {}w:".format(self.sense.active_solar_power))
			self.debugLog("Daily Solar: {}kw".format(self.sense.daily_production))

		for d in self.sense.get_discovered_device_data():
			sID = d['id']
			if ((not self.doSolar) and (sID == "solar")):
				#self.debugLog("Solar disabled: skipping")
				continue
			dName = d['name']
			dRevoked = False
			if ('tags' in d) and ('Revoked' in d['tags']):
				if (d['tags']['Revoked'] == 'true'):
					dRevoked = True
			if ('tags' in d) and ('UserDeleted' in d['tags']):
				if (d['tags']['UserDeleted'] == 'true'):
					dRevoked = True

			if ('tags' in d) and ('MergedDevices' in d['tags']):
				mergedDevices = d['tags']['MergedDevices'].split(',')
				for md in mergedDevices:
					if (md in self.devIDs):
						self.debugLog(u"Deleting merged device: {}".format(indigo.devices[self.devFromSid[md]].name))
						indigo.device.delete(self.devFromSid[md])

			if (dRevoked):
				if (sID in self.devIDs):
					#indigo.device.delete(self.devFromSid[sID])
					indigo.device.enable(self.devFromSid[sID], value=False)
			else:
				if (sID in self.devIDs):
					#self.debugLog("sID {} is in self.devIDs".format(sID))
					dev = indigo.devices[self.devFromSid[sID]]
					devOldName = dev.name
					#self.debugLog("sID {} has old name {}".format(sID,devOldName))
					#self.debugLog("sID {} has new name {}".format(sID,dName))
					if (dev.name != dName):
						dev.name = dName
						try:
							dev.replaceOnServer()
						except ValueError as e:
							if (str(e) == "NameNotUniqueError"):
								self.debugLog("Trying to rename {} to {}".format(devOldName,dName))
								self.debugLog("Failed to rename - duplicate device found - please ensure Sense devices are all uniquely named")
							else:
								self.errorLog(e)
					if (str(sID) in self.rt.keys()): #If the device is currently "On" (ie appearing in Realtime on Sense dashboard)
						dev.updateStateOnServer(key='power', value=str(self.rt[sID]), uiValue=str("{} w".format(self.rt[sID])))
						dev.updateStateImageOnServer(indigo.kStateImageSel.PowerOn)
					else:
						dev.updateStateOnServer(key='power', value="0", uiValue="0 w")
						dev.updateStateImageOnServer(indigo.kStateImageSel.PowerOff)
					#dev.stateListOrDisplayStateIdChanged()
				else:
					#self.debugLog("sID {} is NOT in self.devIDs".format(sID))
					self.debugLog("CREATING: {} ({})".format(dName,sID))
					#self.debugLog(d)
					try:
						dev = indigo.device.create(indigo.kProtocol.Plugin,dName,dName,deviceTypeId="sensedevice",folder=int(self.folderID))
						newStateList = [
							{'key':'id', 'value':str(sID)},
							{'key':'power', 'value':'0', 'uiValue':'0 w'}
							]
						dev.updateStatesOnServer(newStateList)
						#dev.updateStateOnServer(key='id', value=str(sID))
						#dev.updateStateOnServer(key='power', value="0", uiValue="0 w")
						dev.updateStateImageOnServer(indigo.kStateImageSel.PowerOff)
						dev.stateListOrDisplayStateIdChanged()

						#Add it to self.devIDs
						devID = dev.id
						self.devIDs.append(sID)
						self.sidFromDev[int(devID)] = sID
						self.devFromSid[sID] = devID
					except ValueError as e:
						if (str(e) == "NameNotUniqueError"):
							self.debugLog("Duplicate device found - please ensure Sense devices are all uniquely named")
						else:
							self.errorLog(e)
					#dev.stateListOrDisplayStateIdChanged()
		self.rt = None
		self.rt = dict()
		#self.debugLog("")

	def runConcurrentThread(self):
		try:
			while True:

				if (self.dontStart):
					self.sleep(10) #Wait for initialisation to finish
					self.dontStart = False

				self.getDevices()
				#self.debugLog(self.sense.getRealtimeCall())
				self.sleep(int(self.rateLimit))
		except self.StopThread:
			pass