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
		
		self.rateLimit = pluginPrefs.get("rateLimit", 30)
		self.doSolar = bool(pluginPrefs.get("solarEnabled", False))
		self.folderID = pluginPrefs.get("folderID", None)

		self.devIDs = list()
		
		self.sidFromDev = dict()
		self.devFromSid = dict()

		self.rt  = dict()
		
		self.dontStart = True
		
		self.csvPath = "{}/Preferences/Plugins/{}".format(indigo.server.getInstallFolderPath(), self.pluginId)
		
		self.csvActive = "{}/Preferences/Plugins/{}/activeLog.csv".format(indigo.server.getInstallFolderPath(), self.pluginId)
		self.csvDaily = "{}/Preferences/Plugins/{}/dailyLog.csv".format(indigo.server.getInstallFolderPath(), self.pluginId)
		
		if not os.path.exists(self.csvPath):
			os.mkdir(self.csvPath)
			csv_file = open(self.csvActive, 'w+')
			csv_file.write("Timestamp,power\n")
			csv_file.close()

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
			
			try:
				dev = indigo.device.create(indigo.kProtocol.Plugin,"Active Total","Active Total",deviceTypeId="sensedevice",folder=int(self.folderID))
				dev.updateStateOnServer(key='id', value='core')
				dev.updateStateOnServer(key='power', value="0", uiValue="0 w")
				dev.stateListOrDisplayStateIdChanged()
			except ValueError as e:
				pass
			

	########################################
	def startup(self):
		self.debugLog(u"startup called")
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
			sID = dev.states['id']
			dName = dev.name
			self.devIDs.append(sID)
			self.sidFromDev[int(devID)] = sID
			self.devFromSid[sID] = devID
			#self.debugLog("Added device {} ({})".format(sID,dName))
			
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
		#self.debugLog(u"Getting realtime()")
		try:
			self.sense.update_realtime()
			for i in self.sense._realtime['devices']:
				rtid = i['id']
				self.rt[rtid] = int(i['w'])
		except SenseAPITimeoutException as e:
			self.errorLog(e)
		self.sense.update_trend_data()
		active = self.sense.active_power
		daily = self.sense.daily_usage
		self.debugLog("Active: {}w".format(active))
		self.debugLog("Daily: {}kw".format(daily))
		indigo.devices[self.devFromSid['core']].updateStateOnServer(key='power', value=str(int(active)), uiValue=str("{} w".format(int(active))))
		indigo.devices[self.devFromSid['core']].updateStateImageOnServer(indigo.kStateImageSel.PowerOn)

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

			if (dRevoked):
				if (sID in self.devIDs):
					indigo.device.delete(self.devFromSid[sID])
			else:
				if (sID in self.devIDs):
					dev = indigo.devices[self.devFromSid[sID]]
					if (dev.name != dName):
						dev.name = dName
						dev.replaceOnServer()
					if (str(sID) in self.rt.keys()):
						dev.updateStateOnServer(key='power', value=str(self.rt[sID]), uiValue=str("{} w".format(self.rt[sID])))
						dev.updateStateImageOnServer(indigo.kStateImageSel.PowerOn)
					else:
						dev.updateStateOnServer(key='power', value="0", uiValue="0 w")
						dev.updateStateImageOnServer(indigo.kStateImageSel.PowerOff)
					#dev.stateListOrDisplayStateIdChanged()
				else:
					self.debugLog("CREATED: {}".format(dName))
					try:
						dev = indigo.device.create(indigo.kProtocol.Plugin,dName,dName,deviceTypeId="sensedevice",folder=int(self.folderID))
						dev.updateStateOnServer(key='id', value=str(sID))
						dev.updateStateOnServer(key='power', value="0", uiValue="0 w")
						dev.stateListOrDisplayStateIdChanged()
					except ValueError as e:
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