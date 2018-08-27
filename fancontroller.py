#! /usr/bin/python3 -B

import argparse
import durations
import logging
import os
import platform
import select
import socket
import subprocess
import sys
import threading
import time
import traceback
import yaml

# https://www.kernel.org/doc/Documentation/hwmon/sysfs-interface
class FanController():

	class PlatformError(BaseException):
		pass

	class NameReusage(BaseException):
		pass

	class IncompleteConfiguration(BaseException):
		pass

	class ApplicationDetecter():
		def __init__(self, executable = None, argv = None, duration = 5):
			self.__executable = executable
			self.__argv = argv
			self.__duration = duration
			self.__lastOccurance = 0

	class RingBuffer():
		def __init__(self, time):
			self.__list = []
			if not type(time) == int:
				raise ValueError("time has to be an integer")
			self.__time = time

		def __add__(self, value):
			self.addValue(value)
			return self

		def __repr__(self):
			return "RingBuffer len {} data ".format(self.__time) + str(self.__list)

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

	class CounterWithNotifier():
		def __init__(self, notificationObject, counter):
			self.__counter = counter
			self.__lock = threading.Lock()
			self.__notificationObject = notificationObject

		def decrease(self):
			with self.__lock:
				if self.__counter > 0:
					self.__counter -= 1
					if self.__counter == 0:
						self.__notificationObject.acquire()
						self.__notificationObject.notify_all()
						self.__notificationObject.release()


	class Fan():
		def __init__(self, device, name = None, pwm = False, enable = 1, loudThreshold = 180, maxRot = 1500, minPwm = 80):
			if name == None:
				self.__name = os.path.basename(device)
			else:
				self.__name = name
			self.__device = device
			self.__isPwm = pwm
			self.__minPwm = minPwm
			self.__logging = logging.getLogger(name)
			# enable tells if the fan is controlled by the micro controller or the software. They're mutually exclusive.
			self.__enable = enable
			self.__setEnable()
			self.__loudThreshold = loudThreshold
			self.__maxRot = maxRot

		def __repr__(self):
			return "device {} name {} pwm {} enable {} loudThreshold {} maxRot {}".format(self.__device, self.__name, self.__isPwm, self.__enable,
				self.__loudThreshold, self.__maxRot)

		def __setEnable(self):
			with open(self.__generateControlFilePath() + "_enable", "w") as f:
				f.write(str(self.__enable))

		def isControlled(self):
			return self.__enable == 2

		def isPwm(self):
			return self.__isPwm

		def setPwm(self, pwm):
			self.__logging.debug("Setting pwm value {} on {}".format(pwm, self.__generateControlFilePath()))
			with open(self.__generateControlFilePath(), "w") as f:
				f.write(str(pwm))

		def __generatePathPrefix(self):
			return self.__device

		def __generateControlFilePath(self):	
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
			self.__logging.debug("Setting rot value {} on {}".format(rot, self.getName()))
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
			self.__logging.info("Detecting maximum fan speed")
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
						self.__logging.info("Detected maximum fan speed of {}".format(maxRot))
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

		def getName(self):
			return self.__name

		def getMinRot(self):
			return self.__minRot

		def getMaxRot(self):
			return self.__maxRot

	class TemperatureSensor():
		def __init__(self, device, divisor = 10000, name = None, beep = False, crit_beep = False, crit = 90, smart = False, tempId = 194,
			min = 20, max = 40, logLevel=logging.INFO):
			if name == None:
				self.__name = os.path.basename(prefixPath)
			else:
				self.__name = name
			self.__device = device
			self.__divisor = divisor
			self.__beep = beep
			self.__crit = crit
			self.__smart = smart
			self.__tempId = tempId
			self.__min = min
			self.__max = max
			self.__name = name
			self.__logLevel = logLevel
			if self.__smart:
				self.__logging = logging.getLogger("HDD-{}".format(name))
			else:
				self.__logging = logging.getLogger("TEMP-{}".format(name))
			self.__logging.setLevel(self.__logLevel)

		def __generateSensorPath(self):
			return self.__device

		def isAlarmed(self):
			with open(self.__generateSensorPath()) + "_alarm" as f:
				return bool(int(f.readline()))
		def isCritical(self):
			temp = self.getTemperature()
			if temp != None:
				return temp > self.getCriticalTemperature() 
			return True
			
		def getCriticalTemperature(self):
			with open(self.__generateSensorPath() + "_crit") as f:
				return int(f.readline(), 10)/self.__divisor

		def getTemperature(self):
			self.__logging.info("Getting temperature from {}".format(self.getName()))
			if self.__smart:
				"""
				block device has to be smart capable and able to return temperature
				returns temperature in degrees celsius (°C) or None, if it failed
				"""
				try:
					proc = subprocess.run(["/usr/bin/smartctl" , "-a", "{}".format(self.__device)], stdout=subprocess.PIPE)
					lines = proc.stdout.splitlines()
					for line in lines:
						if b'Temperature_Celsius' in line:
							self.__logging.debug("Got temperature output line {}".format(line))
							splits = line.split()
							# try to get the temperature the easy way
							normal = str(splits[-1].split(b'(')[0])
							reverse = None
							# search backwards through the list and check if any split has just a
							# number in it and is in the latter half of the last
							for index in range(len(splits),int(len(splits)/2), -1):
								data = splits[index-1].decode("utf-8")
								if data.isnumeric():
									reverse = data
									break
							if normal.isnumeric():
								return int(normal, 10)
							else:
								return int(reverse, 10)
					self.__logging.error("Could not get temperature from {}".format(self.getName()))
					return None
				except Exception as e:
					self.__logging.error("Failed to get temperatue value: {}".format(traceback.format_exc()))
					return None
			else:
				try:
					with open(self.__generateSensorPath() + "_input", "r") as f:
						return int(f.readline().strip())/self.__divisor
				except Exception as e:
					self.__logging.error("Failed to get temperatue value: {}".format(traceback.format_exc()))
					return None	

		def getUpperTemperatureBound(self):
			return self.__upperTemperatureBound

		def getLowerTemperatureBound(self):
			return self.__lowerTemperatureBound

		def getName(self):

			return self.__name

	# completely wrap the temperature Sensor (FanController.TemperatueSensor class)
	# and add the getWeight() method
	class ControlledSensor(TemperatureSensor):
		def __init__(self, sensor, weight):
#			self.__class__ = type(sensor.__class__.__name__,
#				(self.__class__, sensor.__class__),
#				{})
			self.__dict__ = sensor.__dict__
			self.__weight = weight

		def getWeight(self):
			return self.__weight

	class ControlledFan(Fan):
		def __init__(self, fan, points):
#			self.__class__ = type(fan.__class__.__name__,
#				(self.__class__, fan.__class__),
#				{})
			self.__dict__ = fan.__dict__
			self.__points = points

		def getPoints(self):
			return self.__points

	class CurvePoint():
		def __init__(self, temp, pwm):
			self.__temp = temp
			self.__pwm = pwm

		def getPwm(self):
			return self.__pwm

		def getTemp(self):
			return self.__temp

	class Controller():
		"""
		maxTemp is in degrees celsius
		@arg tempStop int is the temperature at which the fans are stopped.
			if it is zero, it is disabled.
		"""
		def __init__(self, name, verbosityLevel = logging.INFO, inputs=[], outputs=[], envTemp = None, maxTemp=90, timeDuration = 5, tempStop=40, fluctuationThreshold = 5):
			self.__name = name
			self.__logging = logging.getLogger("Controller-{}".format(name))
			self.__logging.setLevel(verbosityLevel)
			self.__inputs = {}
			self.__outputs = {}
			self.__lastEffectiveTemperatureChange = 0
			self.__tempStop = tempStop
			self.__envTemp = envTemp
			self.__fluctuationThreshold = fluctuationThreshold

			success = True
			for sensor in inputs:
				if type(sensor) not in (FanController.ControlledSensor, FanController.ApplicationDetecter):
					self.__logging.error("Input {} has to be of type TemperatureSensor or ApplicationDetecter.".format(sensor))
					success = False
				else:
					self.__inputs[sensor.getName()] = sensor
			if not success:
				raise ValueError("One or more sensors are not of the correct type.")
			success = True
			for fan in outputs:
				if type(fan) not in (FanController.Fan, FanController.ControlledFan):
					self.__logging.error("Output {} has to be of type Fan.".format(fan))
					sucess = False
				else:
					self.__outputs[fan.getName()] = fan
			if not success:
				raise ValueError("One or more outputs are not of the correct type.")

			self.__ringBuffer = FanController.RingBuffer(timeDuration)

		def iterate(self):
			try:
				self.__ringBuffer += self.getWeightedTemperature()
				for sensorName, sensor in self.__inputs.items():
					if sensor.isCritical():
						self.__logging.warn("Sensor {} is critical at {}".format(sensorName, sensor.getTemperature()))
						self.__setMaximum()
						return
				self.actOnTempChanged()
			except:
				pass

		def __setMaximum(self):
			for fan in self.__outputs.values():
				if fan.isPwm():
					fan.setPwm(255)
				else:
					fan.setRot(fan.getMaxRot())

		def __increaseFanSpeed(self, value=5):
			# increase the speed of all fans by value percent (if not pwm) or value/255 (if it is pwm).
			for name, fan in self.__outputs.items():
				if type(fan) == FanController.ControlledSensor:
					self.followCurve(fan)
				else:
					if fan.isPwm():
						pwmValue = fan.getPwm()
						newValue = pwmValue + value
						if newValue > 255:
							self.__logging.debug("Setting pwm value {} on {}".format(255, fan.getName()))
							fan.setPwm(255)
						else:
							self.__logging.debug("Setting pwm value {} on {}".format(newValue, fan.getName()))
							fan.setPwm(newValue)
					else:
						rotValue = fan.getRot()
						newValue = rotValue + fan.getMaxRot()*0.05
						if newValue > fan.getMaxRot():
							self.__logging.debug("Setting pwm value {} on {}".format(fan.getMaxRot(), fan.getName()))
							fan.setRot(fan.getMaxRot())
						else:
							self.__logging.debug("Setting pwm value {} on {}".format(newValue, fan.getName()))						
							fan.setRot(newValue)

		def __decreaseFanSpeed(self, value=5):
			# increase the speed of all fans by value percent (if not pwm) or value/255 (if it is pwm).
			for name, fan in self.__outputs.items():
				if fan.isPwm():
					pwmValue = fan.getPwm()
					newValue = pwmValue - value
					if newValue < fan.getMinPwm():
						newPwm = fan.getMinPwm()
						self.__logging.debug("Setting pwm value {} on {}".format(newPwm, fan.getName()))
						fan.setPwm(fan.getMinPwm())
					else:
						self.__logging.debug("Setting pwm value {} on {}".format(newValue, fan.getName()))
						fan.setPwm(newValue)
				else:
					rotValue = fan.getRot()
					newValue = rotValue - fan.getMaxRot()*0.05
					if newValue < fan.getMinRot():
						self.__logging.debug("Setting rot value {} on {}".format(newValue, fan.getName()))
						fan.setRot(fan.getMinRot())
					else:
						self.__logging.debug("Setting rot value {} on {}".format(newValue, fan.getName()))
						fan.setRot(newValue)

		def __getLastEffectiveTemperatureChange(self):
			return self.__lastEffectiveTemperatureChange

		def __setLastEffectiveTemperatureChange(self, value):
			self.__lastEffectiveTemperatureChange = value

		def __getEnvironmentTemperature(self):
			return self.__envTemp.getTemperature()

		def __getFluctuationThreshold(self):
			return self.__fluctuationThreshold

		def actOnTempChanged(self):
			try:
				# the function checks if the temperature fluctuated more than a certain threshold since the last fan speed change
				oldWeightedTemperature = self.__ringBuffer.getValue()
				newWeightedTemperature = self.getWeightedTemperature()
				self.__ringBuffer += newWeightedTemperature
				if self.__getLastEffectiveTemperatureChange() - newWeightedTemperature > self.__getFluctuationThreshold():
					self.__increaseFanSpeed()
					self.__setLastEffectiveTemperatureChange(newWeightedTemperature)
				elif newWeightedTemperature - self.__getLastEffectiveTemperatureChange() > self.__getFluctuationThreshold():
					self.__decreaseFanSpeed()
					self.__setLastEffectiveTemperatureChange(newWeightedTemperature)
			except Exception as e:
				self.__logging.error("Could not change fan speed due to exception {}".format(traceback.format_exc()))

		def getWeightedTemperature(self):
			sumTotal = 0
			sumOfWeights = 0
			sumOfTemps = 0
			for inputDevice in self.__inputs.values():
				weight = inputDevice.getWeight()
				temp = inputDevice.getTemperature()
				self.__logging.debug("Calculating with temp {} and weight {}".format(temp, weight))
				if temp != None:
					sumOfWeights += weight
					sumOfTemps += temp*weight
				result = sumOfTemps/sumOfWeights
				self.__logging.debug("Calculated weighted temperature of {}".format(result))
			return result

		def anyInputCritical(self):
			for inputDevice in self.__inputs.values():
				if inputDevice.isCritical():
					return True
			return False

		def setPwm(self, pwm):
			for fan in self.__outputs.values():
				fans.setPwm(pwm)

		def detectMaxRots(self):
			def checkRot(fan, counterObject):
				fan.detectMaxRot()
				counterObject.decrease()

			threads = []
			notifier = threading.Condition()
			value = FanControl.CounterWithNotifier(notifier, len(self.__fans))
			for fan in self.__fans:
				threads.append(threading.Thread(target=checkRot, args=(value)))
			notifier.acquire()
			notifier.wait()
			notifier.release()

		def getName(self):
			return self.__name

		def followCurve(self, fan):
			def scale(temp, thisPoint, nextPoint):
				thisPointTemp = thisPoint.getTemp()
				thisPointPwm = thisPoint.getPwm()
				tempScale = (nextPoint.getTemp() - thisPointTemp)/(thisPointTemp-temp)
				pwm = (thisPointPwm - nextPoint.getPwm())*tempScale + thisPointPwm
				return pwm

			# follow the curve points and scale the outputs correspondingly
			temp = self.getWeightedTemperature()
			# figure out between which points this is 
			points = fan.getPoints()
			pointLen = len(points)
			for index in range(0, pointLen-2):
				thisPoint = points[index]
				nextPoint = points[index+1]
				if temp > thisPoint.getTemp() and temp < nextPoint.getTemp():
					# the temperature is between the two curve points, now scale the pwm output according to the temperature
					fan.setPwm(scale(temp, thisPoint, nextPoint))
					return
			# get the last point, then scale to pwm value 255 with far temp point being the lowest critical temperature of all sensors
			lastPoint = points[-1]
			# get the lowest critical temperature 
			# initialize it with the maximum word size (highest value an integer in Python 3 can hold)
			lowestCrit = sys.maxsize
			for sensor in self.__inputs:
				criticalTemperature = sensor.getCriticalTemperature()
				if criticalTemperature < lowestCrit:
					lowestCrit = criticalTemperature

			pseudoPoint = Controller.CurvePoint(lowestCrit, 255)
			fan.setPwm(scale(temp, lastPoint, pseudoPoint))
			return 

	class Main():
		class Waker():
			def __init__(self, sock, interval):
				self.socket = sock
				self.interval = interval
				self.__logging = logging.getLogger("Waker")
				self.__logging.setLevel(logging.DEBUG)

			def Main(self):
				self.__logging.debug("Entered Main function")
				while True:
					self.socket.sendall(b'a')
					time.sleep(self.interval)

		def __init__(self, configFile="/etc/fancontroller.yml", verbosityLevel=logging.INFO):
			if platform.system() != "Linux":
				raise PlatformError("FanController is only designed to be run on Linux! It can not work on any other platform")

			self.__logging = logging.getLogger(__file__)
			self.__logging.setLevel(verbosityLevel)
			self.__configFile = configFile

			self.__threads = {}

		def __parseConfigFile(self):
			# expects a yaml file
			contents = yaml.load(open(self.__configFile, "r"))
			self.__settings = self.__configureSettings(contents["settings"])
			fans = contents["fans"]
			controllers = contents["controllers"]
			sensors = contents["sensors"]

			self.__sensors = self.__configureSensors(sensors)
			self.__fans = self.__configureFans(fans)
			self.__controllers = self.__configureControllers(self.__settings, controllers, self.__fans, self.__sensors)


		def __configureSettings(self, settings):
			newSettings = {
				"controlDelay" : 5,
				"averagintTime" : 5,
				"pollingTime" : 1
			}
			for key, value in settings.items():
				asTime = False
				for substring in ["delay", "time"]:
					if substring in key.lower():
						asTime = True
						# parse as duration, then transform to durations
						newSettings[key] = durations.Duration(str(value)).to_seconds()
						break
				if not asTime:
					newSettings[key] = value
			return newSettings


		def __configureSensors(self, sensors):
			configuredSensors = {}
			defaults = {
				"divisor" : 10000,
				"beep" : 0,
				"crit" : 90,
				"smart" : False,
				"max" : 30,
				"max" : 40,
			}
			required = ["name", "device", ]
			success = True
			for sensor in sensors:
				valueDict = {}
				valueDict.update(defaults)
				valueDict.update(sensor)
				if valueDict["name"] in sensors:
					success = False
					self.__logging.error("The name {} for sensors is already in use.".format(valueDict["name"]))
				for req in required:
					if req not in valueDict:
						success = False
						self.__logging.error("A sensor does not have the required field {}".format(req))
				newSensor = FanController.TemperatureSensor(**valueDict)
				configuredSensors[newSensor.getName()] = newSensor

			if not success:
				raise FanController.NameReusage("Aborting the program, because names were reused.")
				
			return configuredSensors

		def __configureFans(self, fans):
			configuredFans = {}
			defaults = {
				"pwm" : False
			}

			required = ["name", "device"]
			success = True
			for fan in fans:
				valueDict = {}
				valueDict.update(defaults)
				valueDict.update(fan)
				if valueDict["name"] in configuredFans:
					success = False
					self.__logging.error("The name {} for fans is already in use.".format(valueDict["name"]))
				for req in required:
					if req not in valueDict:
						success = False
						self.__logging.error("A fan does not have the required field {}".format(req))
				newFan = FanController.Fan(**valueDict)
				configuredFans[newFan.getName()] = newFan

			if not success:
				raise FanController.NameReusage("Aborting the program, because names were reused.")
				
			return configuredFans

		def __configureControllers(self, settings, controllers, fans, sensors):
			configuredControllers = {}
			success = True
			for controller in controllers:
				kwargs = {
				"inputs" : [],
				"outputs" : []
				}
				required = ["name", "inputs", "outputs" ]
				for key, value in controller.items():
					if key == "inputs":
						for sensor in value:
							configuredSensor = sensors.get(sensor["name"])
							if configuredSensor == None:
								self.__logging.error("The input {} is used, but not defined.".format(sensor["name"]))
							else:
								controlledSensor = FanController.ControlledSensor(configuredSensor, sensor.get("weight", 1))
								kwargs["inputs"].append(controlledSensor)
					elif key == "outputs":
						for fan in value:
							configuredFan = fans.get(fan["name"])
							if configuredFan == None:
								self.__logging.error("The input {} is used, but not defined.".format(fan["name"]))
							else:
								if "curve" in fan:
									points = []
									for point in fan["curve"]:
										points.append(FanController.CurvePoint(point["temp"], point["pwm"]))
									# order by temp
									points.sort(key=lambda point: point.getTemp())
									kwargs["outputs"].append(FanController.ControlledFan(configuredFan, points))
								else:
									kwargs["outputs"].append(configuredFan)
					elif key == "name":
						kwargs[key] = value
				newController = FanController.Controller(**kwargs)
				configuredControllers[newController.getName()] = newController

			if not success:
				raise IncompleteConfiguration("Aborting the program, because some used objects were not defined in the configuration file.")
			return configuredControllers

		def __getSetting(self, value):
			return self.__settings.get(value)

		def __runOneController(self, counter, controller):
			controller.iterate()
			counter.decrease()

		def __runAllControllers(self):
			self.__logging.debug("Running all controllers")
			counter = FanController.CounterWithNotifier(self.__endOfLoopWaiterObject, len(self.__controllers))
			for controllerName, controller in self.__controllers.items():
				newThread = threading.Thread(target=self.__runOneController, args=(counter, controller))
				newThread.start()
				self.__logging.debug("Started thread for {}".format(controllerName))
				self.__threads[newThread.ident] = newThread

		def __filterRunningThreads(self):
			self.__threads.clear()
			for thread in threading.enumerate():
				self.__threads[thread.ident] = thread
			
		def busyLoop(self):
			self.__logging.debug("Entered busyLoop method.")
			pollingObject = select.poll()
			localSocket, remoteSocket = socket.socketpair(type=socket.SOCK_DGRAM)
			pollingObject.register(localSocket, select.POLLIN)
			wakerObject = FanController.Main.Waker(remoteSocket, self.__getSetting("pollingTime"))
			wakerThread = threading.Thread(target=wakerObject.Main)
			wakerThread.start()
			wakerThreadSockets = { localSocket.fileno() : localSocket }
			self.__endOfLoopWaiterObject = threading.Condition()
			while True:
				self.__logging.debug("Loop iteration.")
				fdStructures = pollingObject.poll()
				for fd, flags in fdStructures:
					if fd in wakerThreadSockets:
						self.__logging.debug("Got message from waker thread.")
						if flags & select.POLLIN:
							self.__logging.debug("Got pollin for wakerThreadSocket {}".format(fd))
							self.__runAllControllers()
							localSocket.recvmsg(9000)
				self.__logging.debug("End of an iteration of the busyLoop")
				self.__endOfLoopWaiterObject.acquire()
				self.__endOfLoopWaiterObject.wait()
				self.__endOfLoopWaiterObject.release()
				self.__logging.debug("Synchronized threads")
				self.__filterRunningThreads()

			for thread in self.__threads.value():
				self.__threads.pop(thread.ident)
				del(thread)

		def run(self):
			self.__logging.debug("Entered Main.run.")
			self.__parseConfigFile()
			self.busyLoop()


	# method of the FanController class
	def run(self):
		parser = argparse.ArgumentParser(description="Fan controller")
		parser.add_argument("-c",
			"--config",
			nargs="?",
			dest="configFile",
			help="path to the configuration file",
			default="/etc/fan-controller.yml")

		parser.add_argument("-v",
			"--verbosity",
			nargs="?",
			dest="verbosity",
			help="The verbosity level",
			type=int,
			default=logging.INFO)

		args = parser.parse_args()

		logging.basicConfig(
			level=args.verbosity,
			datefmt="%H:%M:%S",
			stream=sys.stdout
			)

		main = FanController.Main(args.configFile, args.verbosity)

		main.run()
		

if __name__ == '__main__':
	controller = FanController()
	controller.run()

