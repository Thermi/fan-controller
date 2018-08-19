#! /usr/bin/python3 -B

import logging
import os
import platform
import subprocess
import threading
import traceback
import yaml

# https://www.kernel.org/doc/Documentation/hwmon/sysfs-interface
class FanController():

	class Fan():
		def __init__(self, prefix, name=os.path.basename(prefix), isPwm=False, enable=1, loudThreshold=180, maxRot=1500):
			self.__directory = directory
			self.__prefix = prefix
			self.__isPwm = isPwm
			self.__logging = logging.getLogger(name)
			# enable tells if the fan is controlled by the micro controller or the software. They're mutually exclusive.
			self.__enable = enable
			self.__loudThreshold = loudThreshold
			self.__maxRot = maxRot

		def isControlled(self):
			return self.__enable == 2

		def isPwm(self):
			return self.__isPwm

		def setPwm(self, pwm):
			with open(self.__generateControlFilePath(), "w") as f:
				f.write(pwm)

		def __generatePathPrefix(self):
			return self.__directory + self.__prefix

		def __generateControlFilePath(self)
			if self.isPwm():
				return self.__generatePathPrefix()
			else:
				return self.__generatePathPrefix() + "_input"

		def pwmToRot(self, pwmValue):
			return (pwmValue/255)*self.__maxRot

		def rotToPwm(self, rot):
			return (rot/self.__maxRot)*255

		def readRot(self):
			with open(self.__generateControlFilePath(), "r") as f:
				if self.isPwm():
					return self.pwmToRot(int(f.readline().strip()))
				else:
					return int(f.readline().strip())
		def getPwm(self):
			with open(self.__generateControlFilePath(), "r") as f:
				return int(f.readline().strip())

		def readRotAlreadyOpen(self, fanRotStream):
			fanRotStream.seek(0,0)
			return fanRotStream.readline()
		
		def setRot(self, rot):
			with open(self.__generateControlFilePath(), "w") as f:
				f.write(rot)

		def detectMaxRot(self, fan):
			"""
			This method spins up the particular fan to max speed and returns it, after fluctuations receeded
			"""
			maxRot = 0
			# the time the function waits for fluctuations , after the 
			waitPeriod = 10
			waitedPeriod = 0
			waited = 0
			with open(fan, "w") as f:
				f.write("255")

			while True:
				rot = self.readRot(fan)
				if rot > maxRot:
					maxRot = rot
				if waited == 1:
					waited = 0
					waitedPeriod += 1
					if waitedPeriod >= waitPeriod:
						self.__maxRot =  maxRot
						return
				if not rot > maxRot:
					waited = 1
				time.sleep(1)

		def getLoudThreshold(self):
			return self.__loudThreshold

		def getMinPwm(self):
			return self.__minPwm

		def setScaledOutput(self, scale):
			if self.isPwm():
				self.setPwm((255-self.getMinPwm())*scale+self.getMinPwn())
			else:
				self.getMaxRot()-self.getMinPwm()

	class TemperatureSensor():
		def __init__(self, prefixPath, divisor, name=os.path.basename(prefixPath),
			smart=False, tempId=194, lowerBound=20, upperBound=40, loglevel=logging.INFO):
			self.prefixPath = prefixPath
			self.__divisor = divisor
			self.__smart = smart
			self.__tempId = tempId
			self.__lowerBound = lowerBound
			self.__upperBound = upperBound
			self.__name = name
			self.__loglevel = loglevel
			if self.__smart:
				self.__logging = logging.getLogger("HDD-{}".format(name))
			else:
				self.__logging = logging.getLogger("TEMP-{}".format(name))
			self.__logging.setLevel(self.__logLevel)

		def __generateSensorPath(self):
			return self.__prefixPath

		def isAlarmed(self):
			with open(self.__generateSensorPath) + "_alarm" as f:
				return bool(int(f.readline()))
		def isCritical(self):
			return self.getTemp() > self.getCrit() 

		def getCrit(self):
			with open(self.__generateSensorPath() + "_crit") as f:
				return int(f.readline(), 10)/self.__divisor

		def getTemp(self):
			if smart:
				"""
				block device has to be smart capable and able to return temperature
				returns temperature in degrees celsius (°C) or None, if it failed
				"""
				try:
					proc = subprocess.run(["/usr/bin/smartctl" , "-a", "/dev/{}".format(blockDeviceName)], stdout=subprocess.PIPE)
					lines = proc.stdout.splitlines()
					for line in lines:
						if b'Temperature_Celsius' in line:
							return int(str(line.split()[-1].split(b'(')[0], "utf-8"))
					return None
				except Exception as e:
					self.__logging.error("Failed to get temperatue value: {}".format(traceback.format_exc()))
					return None
			else:
				try:
					with open(self.__generateSensorFilePath(), "r") as f:
						return int(f.readline().strip())self.__divisor
				except Exception as e:
					self.__logging.error("Failed to get temperatue value: {}".format(traceback.format_exc()))
					return None	

		def getUpperTemperatureBound(self):
			return self.__upperTemperatureBound

		def getLowerTemperatureBound(self):
			return self.__lowerTemperatureBound

	class PlatformError(BaseException)
		pass

	class applicationDetecter():
		"""
		This class represents a 
		"""
		def __init__(self, exec=None, argv=None, duration=5):
			pass

	class ringBuffer():
		def __init__(self, time):
			self.__list = []
			if not type(time) == int:
				raise ValueError("time has to be an integer")
			self.__time = time

		def __add__(self, value):
			self.addValue(value)
			return self

		def __repr__(self):
			return "ringBuffer len {} data ".format(self.__time) + str(self.__list)

		def addValue(self, value):
			if len(self.__list) < self.__time:
				self.__list.insert(0, value)
			else:
				self.__list.pop()
				self.__list.insert(0, value)

		def getValue(self):
			return self.__list[len(self.__list)-1]

		def getTime(self):
			return self.__time

	class Controller():
		def __init__(self, inputs=[], outputs=[], timeDuration = 5):
			for sensor in inputs:
				if type(sensor) not in (TemperatureSensor, applicationDetecter)
			self.__ringBuffer = ringBuffer(timeDuration)

		def iterate(self):
			self.__ringBuffer += self.getWeightedTemperature()
			if self.__checkTempRises():
				self.__increaseFanSpeed()

			for sensor in self.__sensors:
				if sensor.isCritical():
					self.__setMaximum()
					return
			scale = self.__getTempScale()
			self.setFans(scale)

		def checkTempRises():
			weightedTemperature = self.getWeightedTemperature()
			self.__ringBuffer += weightedTemperature

		def getWeightedTemperature(self):
			sumTotal = 0
			sumOfWeights = 0
			sumOfTemps = 0
			for inputDevice in self.__inputs:
				weight = inputDevice.getWeight()
				sumOfWeights += weight
				sumOfTemps += inputDevice.getTemperature()*weight
			return sumOfTemps/sumOfWeights

		def anyInputCritical(self):
			for inputDevice in self.__inputs:
				if inputDevice.isCritical():
					return True
			return False

		def scaleOutputs(self):
			scalePart = 0
			#  TODO: scale output corresponding to the weighted temperature

		def setFans(self, scale):
			for output in self.__outputs:
				output.setScaledOutput(scale)

		def detectMaxRots(self):
			def checkRot(fan, counterObject):
				fan.detectMaxRot()
				counterObject.decValue()

			class Counter():
				def __init__(self, value)
					self.value = value
					self.lock = threading.RLock()
					self.condition = threading.Condition()

				def getCondition(self):
					return self.conditon

				def decValue(self):
					self.lock.acquire()
					self.value -= 1
					if self.value == 0:
						self.condition.notify_all()
					self.lock.release()

			threads = []
			value = Counter(len(self.__fans))
			for fan in self.__fans:
				threads.append(threading.Thread(target=checkRot, args=(value)))
			value.getCondition.wait()

	class Main():
		def __init__(self, configFile="/etc/fancontroller.yml"):
			if platform.system() != "Linux":
				raise PlatformError("FanController is only designed to be run on Linux! It can not work on any other platform")

			self.__logging = logging.getLogger(__name__)
			self.__logging.setLevel(logging.DEBUG)
			self.__configFile = configFile

		def __parseConfigFile(self)
			# expects a yaml file
			contents = yaml.load(self.__configFile)
			settings = contents["contents"]
			fans = contents["fans"]
			controllers = contents["controllers"]
			sensors = contents["sensors"]
			self.__configureSensors(sensors)

		def __configureSensors(self):
			for sensor in self.__sensors:
				newSensor = 
				for key, value in sensor.items():

if __name__ == '__main__':
	controller = FanController()
	controller.run()

