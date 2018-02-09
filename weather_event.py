#!/usr/bin/env python

from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from enum import IntEnum
try:
	import configparser
except ImportError:
	import ConfigParser as configparser
import math
import numpy
# import sys
import time
import traceback


class LOG_LEVEL(IntEnum):
	NONE = 0
	ERROR = 1
	INFO = 2
	DEBUG = 3


########
# Functions
########
def AltitudeOffset(Altitude):
	# p = 101325 (1 - 2.25577 10-5 h)5.25588
	# Pressure at Altitude
	p2 = 2.25577 * math.pow(10, -5)
	p1 = 1 - (p2 * Altitude)
	p = 101325 * math.pow(p1, 5.25588)
	# Pressure at Sea Level
	s = 101325 * math.pow(1, 5.25588)
	return (s - p) / 100


def BootMessage(msg):
	print msg
	if config.getboolean('Output', 'ADA_LCD'):
		try:
			AdaLcd.clear()
			AdaLcd.set_color(0.5, 0.5, 0.5)
			msg = FormatDisplay(msg, config.getint('Adafruit_LCD', 'LCD_WIDTH'), config.getint('Adafruit_LCD', 'LCD_HEIGHT'))
			AdaLcd.message(msg)
		except:
			print "Could not write to LCD"


def DewPoint(RH, TempC):
	Log(LOG_LEVEL.INFO, "DewPoint: Calculating for RH:{0:.1f} and Temp: {1:.1f}".format(RH, TempC))
	# Paroscientific constants (0 <> 60 degc, 0 <> 100% RH)
	# a = 6.105
	b = 17.271
	c = 237.7
	gamma = numpy.log(RH/100.0) + (b * TempC / (c + TempC))
	dp = (c * gamma) / (b - gamma)
	Log(LOG_LEVEL.INFO, "DewPoint is {0:.1f}".format(dp))
	return dp


def EnOceanSensors(eoCommunicator):
	Log(LOG_LEVEL.DEBUG, "EnOceanSensors: Begin")
	try:
		Log(LOG_LEVEL.DEBUG, "EnOceanSensors: Alive: " + str(eoCommunicator.is_alive()))
	except Exception:
		Log(LOG_LEVEL.ERROR, "EnOceanSensors: Error in communications" + traceback.format_exc())
	if not eoCommunicator.is_alive():
		try:
			eoCommunicator.stop()
		except Exception:
			Log(LOG_LEVEL.ERROR, "EnOceanSensors: Error stopping communications" + traceback.format_exc())
		try:
			eoCommunicator = eoSerialCommunicator(port=config.get('EnOcean', 'PORT'))
			eoCommunicator.start()
			Log(LOG_LEVEL.INFO, "EnOceanSensors: Re-opened communications on port " + config.get('EnOcean', 'PORT'))
		except Exception:
			Log(LOG_LEVEL.ERROR, "EnOceanSensors: Error in communications" + traceback.format_exc())
	while eoCommunicator.is_alive():
		try:
			# Loop to empty the queue...
			Log(LOG_LEVEL.DEBUG, "EnOceanSensors: Receive Loop")
			packet = eoCommunicator.receive.get(block=False)
			Log(LOG_LEVEL.DEBUG, "EnOceanSensors: Packet received")
			if packet.packet_type == EOPACKET.RADIO and packet.rorg == EORORG.BS4:
				# parse packet with given FUNC and TYPE
				for k in packet.parse_eep(0x02, 0x05):
					temp = packet.parsed[k]['value']
					transmitter_id = packet.sender_hex
					transmitter_name = MapSensor(transmitter_id)
					Log(LOG_LEVEL.INFO, "EnOceanSensors: {0}({1}): {2:0.1f}".format(transmitter_name, transmitter_id, temp))
					for x in xrange(config.getint('EnOcean', 'ANTI_SMOOTHING')):
						Smoothing(transmitter_name, temp)
		except queue.Empty:
			return
		except Exception:
			Log(LOG_LEVEL.ERROR, "EnOceanSensors: Error in communications" + traceback.format_exc())


def Flush(ds, dstatus):
	Log(LOG_LEVEL.DEBUG, "Flush: ds")
	ds.flush()
	Log(LOG_LEVEL.DEBUG, "Flush: Write dstatus")
	try:
		dstatus.set('last update', 'logged', datetime.utcnow().isoformat(' '))
		dstatus.set('fixed', 'fixed block', str(readings))
	except:
		Log(LOG_LEVEL.ERROR, "Flush: Error setting status" + traceback.format_exc())
	Log(LOG_LEVEL.DEBUG, "Flush: dstatus")
	try:
		dstatus.flush()
	except:
		Log(LOG_LEVEL.ERROR, "Flush: error in flush" + traceback.format_exc())
	Log(LOG_LEVEL.DEBUG, "Flush: Complete")


def ForecastBoM():
	Log(LOG_LEVEL.DEBUG, "ForecastBoM: start")
	FORECAST_BASE_URL = config.get('BoM', 'FORECAST_BASE_URL')
	FORECAST_STATE_ID = config.get('BoM', 'FORECAST_STATE_ID')
	FORECAST_AAC = config.get('BoM', 'FORECAST_AAC')
	Forecast_URL = FORECAST_BASE_URL + FORECAST_STATE_ID + '.xml'
	Log(LOG_LEVEL.DEBUG, "ForecastBoM: Connecting to " + Forecast_URL)
	global forecast_bom_today
	global forecast_bom_tomorrow
	global forecast_bom_dayafter
	try:
		response = urllib2.urlopen(Forecast_URL)
		ForecastXML = response.read()
	except:
		Log(LOG_LEVEL.ERROR, "ForecastBoM: Error downloading forecast file:" + traceback.format_exc())
		return
	try:
		ForecastTree = ElementTree.fromstring(ForecastXML)
	except:
		Log(LOG_LEVEL.ERROR, "ForecastBoM: Error parsing forecast file:" + traceback.format_exc())
		return
	try:
		Forecasts = ForecastTree.find('forecast')
	except:
		Log(LOG_LEVEL.ERROR, "ForecastBoM: Error finding forecast element:" + traceback.format_exc())
		return
	for area in Forecasts:
		if area.attrib['aac'] == FORECAST_AAC:
			# Today
			try:
				max_temp = area._children[0].find("*[@type='air_temperature_maximum']").text
			except:
				max_temp = "?"
			try:
				forecast_text = area._children[0].find("*[@type='precis']").text
			except:
				forecast_text = "?"
			try:
				rain_chance = area._children[0].find("*[@type='probability_of_precipitation']").text
			except:
				rain_chance = "?"
			forecast_bom_today = "Max {0} {1} {2}".format(max_temp, rain_chance, forecast_text)
			Log(LOG_LEVEL.INFO, "ForecastBoM: Today:" + forecast_bom_today)
			try:
				channel = config.get('BoM', 'FORECAST_CHANNEL_TODAY')
				if readings.get(channel, None) is None:
					readings[channel] = [0]
				readings[channel][0] = forecast_bom_today
			except:
				Log(LOG_LEVEL.ERROR, "ForecastBoM: Could not populate today forecast to memory store" + traceback.format_exc())
			# Tomorrow
			try:
				min_temp = area._children[1].find("*[@type='air_temperature_minimum']").text
			except:
				min_temp = "?"
			try:
				max_temp = area._children[1].find("*[@type='air_temperature_maximum']").text
			except:
				max_temp = "?"
			try:
				forecast_text = area._children[1].find("*[@type='precis']").text
			except:
				forecast_text = "?"
			try:
				rain_chance = area._children[1].find("*[@type='probability_of_precipitation']").text
			except:
				rain_chance = "?"
			forecast_bom_tomorrow = "{0}-{1} {2} {3}".format(min_temp, max_temp, rain_chance, forecast_text)
			Log(LOG_LEVEL.INFO, "ForecastBoM: Tomorrow:" + forecast_bom_tomorrow)
			try:
				channel = config.get('BoM', 'FORECAST_CHANNEL_TOMORROW')
				if readings.get(channel, None) is None:
					readings[channel] = [0]
				readings[channel][0] = forecast_bom_tomorrow
			except:
				Log(LOG_LEVEL.ERROR, "ForecastBoM: Could not populate tomorrow forecast to memory store" + traceback.format_exc())
			# Day after tomorrow
			try:
				min_temp = area._children[2].find("*[@type='air_temperature_minimum']").text
			except:
				min_temp = "?"
			try:
				max_temp = area._children[2].find("*[@type='air_temperature_maximum']").text
			except:
				max_temp = "?"
			try:
				forecast_text = area._children[2].find("*[@type='precis']").text
			except:
				forecast_text = "?"
			try:
				rain_chance = area._children[2].find("*[@type='probability_of_precipitation']").text
			except:
				rain_chance = "?"
			forecast_bom_dayafter = "{0}-{1} {2} {3}".format(min_temp, max_temp, rain_chance, forecast_text)
			Log(LOG_LEVEL.INFO, "ForecastBoM: Day After Tomorrow:" + forecast_bom_dayafter)
			try:
				channel = config.get('BoM', 'FORECAST_CHANNEL_DAYAFTER')
				if readings.get(channel, None) is None:
					readings[channel] = [0]
				readings[channel][0] = forecast_bom_dayafter
			except:
				Log(LOG_LEVEL.ERROR, "ForecastBoM: Could not populate day after tomorrow forecast to memory store" + traceback.format_exc())
			return (forecast_bom_today, forecast_bom_tomorrow, forecast_bom_dayafter)


def ForecastFile():
	Log(LOG_LEVEL.DEBUG, "ForecastFile: start")
	global forecast_file_today
	forecast_filename = config.get('ForecastFile', 'FILE')
	try:
		with open(forecast_filename) as f:
			forecast_file_today = f.read()
	except:
		Log(LOG_LEVEL.ERROR, "ForecastFile: Error reading forecast from file" + traceback.format_exc())
	try:
		channel = config.get('ForecastFile', 'FORECAST_CHANNEL')
		if readings.get(channel, None) is None:
			readings[channel] = [0]
		readings[channel][0] = forecast_file_today
	except:
		Log(LOG_LEVEL.ERROR, "ForecastFile: Could not populate forecast to memory store" + traceback.format_exc())
	Log(LOG_LEVEL.INFO, "ForecastFile: \"%s\"" % forecast_file_today)
	Log(LOG_LEVEL.DEBUG, "ForecastFile: Complete")


def FormatDisplay(input, max_length, max_height):
	input_len = len(input)
	if (input_len < max_length):
		return input
	else:
		words = input.split()
		display = ""
		length = 0
		height = 1
		for word in words:
			len_word = len(word)
			if (length + len_word) <= max_length:
				display = display + word + " "
				length = length + len_word + 1
			elif (height == max_height):
				trunc = max_length - length
				display = display + word[0:trunc]
				return display
			else:
				display = display + "\n" + word + " "
				length = len_word + 1
				height = height + 1
		return display


def Log(level, message):
	# None, Error, Info, Debug
	# 0     1      2     3
	if config.getint('General', 'LOG_LEVEL') >= level:
		print message


def MapSensor(sensor_id):
	sid = sensor_id.replace(':', '')
	try:
		return config.get('EnOcean', sid)
	except:
		return sensor_id


def MqClose():
	global mqtt_client
	Log(LOG_LEVEL.DEBUG, "MqClose: Stopping loop")
	mqtt_client.loop_stop()
	Log(LOG_LEVEL.DEBUG, "MqClose: Disconnecting")
	mqtt_client.disconnect()
	Log(LOG_LEVEL.DEBUG, "MqClose: Complete")


def MqInit():
	global mqtt_client
	mqtt_client.connect(config.get('MQTT', 'SERVER'), config.getint('MQTT', 'PORT'), config.getint('MQTT', 'TIMEOUT'))
	Log(LOG_LEVEL.DEBUG, "MqInit: Starting loop")
	mqtt_client.loop_start()


def MqSendMultiple():
	Log(LOG_LEVEL.DEBUG, "MqSendMultiple: Build Message")
	msgs = []
	for reading in readings:
		mq_path = config.get('MQTT', 'PREFIX') + reading
		value = readings[reading][0]
		msg = {'topic': mq_path, 'payload': value}
		Log(LOG_LEVEL.DEBUG, "MqSendMultiple: Payload Element {0}".format(msg))
		msgs.append(msg)
	Log(LOG_LEVEL.DEBUG, "MqSendMultiple: Sending multiple")
	try:
		publish.multiple(msgs, hostname=config.get('MQTT', 'SERVER'), port=config.getint('MQTT', 'PORT'), client_id=config.get('MQTT', 'CLIENTID'))
	except:
		Log(LOG_LEVEL.ERROR, "Error sending MQTT message" + traceback.format_exc())
	Log(LOG_LEVEL.DEBUG, "MqSendMultiple: Complete")


def MqSendSingle(variable, value):
	mq_path = config.get('MQTT', 'PREFIX') + variable
	Log(LOG_LEVEL.DEBUG, "MqSendSingle: Sending {0} = {1:0.1f}".format(mq_path, value))
	mqtt_client.publish(mq_path, value)


def ReadConfig():
	global config
	lconfig = configparser.ConfigParser()
	lconfig.read(CONFIG_FILE)
	try:
		lconfig.get('Calibration', 'ALTITUDE_PRESSURE_OFFSET', 1)
	except:
		PressureOffset = AltitudeOffset(lconfig.getint('Calibration', 'ALTITUDE'))
		lconfig.set('Calibration', 'ALTITUDE_PRESSURE_OFFSET', PressureOffset)
	config = lconfig


def RelToAbsHumidity(relativeHumidity, temperature):
	absoluteHumidity = 6.112 * math.exp((17.67 * temperature)/(temperature+243.5)) * relativeHumidity * 2.1674 / (273.15+temperature)
	return absoluteHumidity


def Sample():
	Log(LOG_LEVEL.DEBUG, "Sample: read")
	global readings
	if config.getboolean('Sensors', 'BME280'):
		# !Make sure to read temperature first!
		# !The library sets OverSampling and waits for valid values _only_ in the read_raw_temperature function!
		try:
			Smoothing(config.get('BME280', 'TEMPERATURE_CHANNEL'), (BmeSensor.read_temperature() + config.getfloat('Calibration', 'BME280_TEMP_IN')))
			# Note: read_pressure returns Pa, divide by 100 for hectopascals (hPa)
			Smoothing(config.get('BME280', 'PRESSURE_CHANNEL'), ((BmeSensor.read_pressure()/100.0) + config.get('Calibration', 'ALTITUDE_PRESSURE_OFFSET', 1) + config.getfloat('Calibration', 'BME280_PRESSURE')))
			Smoothing(config.get('BME280', 'HUMIDITY_CHANNEL'), (BmeSensor.read_humidity() + config.getfloat('Calibration', 'BME280_HUM_IN')))
		except:
			Log(LOG_LEVEL.ERROR, "Error reading BME280: " + traceback.format_exc())

	if config.getboolean('Sensors', 'BMP085'):
		try:
			Smoothing(config.get('BMP085', 'TEMPERATURE_CHANNEL'), (BmpSensor.read_temperature() + config.getfloat('Calibration', 'BMP085_TEMP_IN')))
			# Note: read_pressure returns Pa, divide by 100 for hectopascals (hPa)
			Smoothing(config.get('BME280', 'PRESSURE_CHANNEL'), ((BmpSensor.read_pressure()/100.0) + config.getfloat('Calibration', 'BMP085_PRESSURE')))
		except:
			Log(LOG_LEVEL.ERROR, "Error reading BMP085" + traceback.format_exc())
	if config.getboolean('Sensors', 'SENSEHAT'):
		try:
			Smoothing(config.get('SENSEHAT', 'PRESSURE_CHANNEL'), (PiSenseHat.get_pressure() + config.get('Calibration', 'ALTITUDE_PRESSURE_OFFSET', 1) + config.getfloat('Calibration', 'SENSEHAT_PRESSURE')))
			Smoothing(config.get('SENSEHAT', 'HUMIDITY_CHANNEL'), (PiSenseHat.get_humidity() + config.getfloat('Calibration', 'SENSEHAT_HUM_IN')))
			Smoothing(config.get('SENSEHAT', 'TEMPERATURE_CHANNEL'), (PiSenseHat.get_temperature_from_pressure() + config.getfloat('Calibration', 'SENSEHAT_TEMP_IN')))
		except:
			Log(LOG_LEVEL.ERROR, "Error reading SENSEHAT" + traceback.format_exc())
	if config.getboolean('Sensors', 'SI1145'):
		try:
			Smoothing(config.get('SI1145', 'VISIBLE_CHANNEL'), ((SiSensor.readVisible() + config.getfloat('Calibration', 'SI1145_VISIBLE')) / config.getfloat('Calibration', 'SI1145_VISIBLE_RESPONSE')))
			Smoothing(config.get('SI1145', 'IR_CHANNEL'), ((SiSensor.readIR() + config.getfloat('Calibration', 'SI1145_IR')) / config.getfloat('Calibration', 'SI1145_IR_RESPONSE')))
			Smoothing(config.get('SI1145', 'UV_CHANNEL'), (((SiSensor.readUV()/100.0) + config.getfloat('Calibration', 'SI1145_UV')) / config.getfloat('Calibration', 'SI1145_UV_RESPONSE')))
		except:
			Log(LOG_LEVEL.ERROR, "Error reading SI1145" + traceback.format_exc())
	if config.getboolean('Sensors', 'DEWPOINT_CALC') and not global_init:
		try:
			Smoothing(config.get('DewPoint', 'DEWPOINT_CHANNEL'), DewPoint(readings[config.get('DewPoint', 'HUMIDITY_CHANNEL')][0], readings[config.get('DewPoint', 'TEMPERATURE_CHANNEL')][0]))
		except:
			Log(LOG_LEVEL.ERROR, "Error calculating Dew Point" + traceback.format_exc())
	Log(LOG_LEVEL.DEBUG, "Sample: Complete")


def Smoothing(channel, value):
	Log(LOG_LEVEL.DEBUG, "Smoothing: " + channel)
	if global_init:
		Log(LOG_LEVEL.DEBUG, "Init Mode: returning with no storage")
		return
	average = 0
	global readings
	if readings.get(channel, None) is None:
		Log(LOG_LEVEL.DEBUG, "Init %s" % channel)
		readings[channel] = [config.getint('General', 'MININT') for x in xrange(config.getint('General', 'SMOOTHING')+1)]
	for i in range(1, (config.getint('General', 'SMOOTHING'))):
		if readings[channel][i+1] == config.getint('General', 'MININT'):
			readings[channel][i+1] = value
		readings[channel][i] = readings[channel][i+1]
		average += readings[channel][i]
	readings[channel][config.getint('General', 'SMOOTHING')] = value
	average += value
	average = average / config.getint('General', 'SMOOTHING')
	readings[channel][0] = average
	# Log(LOG_LEVEL.DEBUG,"Smoothing: Readings[%s]: %s" % (channel, readings[channel]))
	# Log(LOG_LEVEL.DEBUG,"Smoothing: Complete")


def Store(ds):
	Log(LOG_LEVEL.DEBUG, "Store: Write to data")
	global data
	data = {}
	try:
		data['abs_pressure'] = int(readings[config.get('PYWWS', 'ABS_PRESSURE_CHANNEL')][0])
	except:
		data['abs_pressure'] = None
	data['delay'] = int(0)
	try:
		data['hum_in'] = int(readings[config.get('PYWWS', 'HUM_IN_CHANNEL')][0])
	except:
		data['hum_in'] = None
	try:
		data['hum_out'] = int(readings[config.get('PYWWS', 'HUM_OUT_CHANNEL')][0])
	except:
		data['hum_out'] = None
	try:
		data['illuminance'] = float(readings[config.get('PYWWS', 'ILLUMINANCE_CHANNEL')][0])
	except:
		data['illuminance'] = None
	try:
		data['rain'] = float(readings[config.get('PYWWS', 'RAIN_CHANNEL')][0])
	except:
		data['rain'] = 0
	data['status'] = 0
	try:
		data['temp_in'] = float(readings[config.get('PYWWS', 'TEMP_IN_CHANNEL')][0])
	except:
		data['temp_in'] = None
	try:
		data['temp_out'] = float(readings[config.get('PYWWS', 'TEMP_OUT_CHANNEL')][0])
	except:
		data['temp_out'] = None
	try:
		data['uv'] = int(readings[config.get('PYWWS', 'UV_CHANNEL')][0])
	except:
		data['uv'] = None
	try:
		data['wind_ave'] = float(readings[config.get('PYWWS', 'WIND_AVE_CHANNEL')][0])
	except:
		data['wind_ave'] = None
	try:
		data['wind_dir'] = int(readings[config.get('PYWWS', 'WIND_DIR_CHANNEL')][0])
	except:
		data['wind_dir'] = None
	try:
		data['wind_gust'] = float(readings[config.get('PYWWS', 'WIND_GUST_CHANNEL')][0])
	except:
		data['wind_gust'] = None
	Log(LOG_LEVEL.DEBUG, "Store: Write to ds")
	try:
		ds[datetime.utcnow()] = data
	except:
		Log(LOG_LEVEL.ERROR, "Store: Error pushing data" + traceback.format_exc())
	Log(LOG_LEVEL.DEBUG, "Store: Complete")


def WriteAdaLcd():
	global AdaScreenNumber
	msg_success = False
	while (not msg_success):
		try:
			if AdaScreenNumber == 0:
				AdaScreenNumber += 1
				msg = "{0:0.1f}C {1:0.0f}% UV{2:0.1f}\n{3:0.1f}hPa".format(readings[config.get('PYWWS', 'TEMP_IN_CHANNEL')][0], readings[config.get('PYWWS', 'HUM_IN_CHANNEL')][0], readings[config.get('PYWWS', 'UV_CHANNEL')][0], readings[config.get('PYWWS', 'ABS_PRESSURE_CHANNEL')][0])
				msg_success = True
			elif AdaScreenNumber == 1:
				AdaScreenNumber += 1
				if config.getboolean('Sensors', 'FORECAST_FILE'):
					msg = FormatDisplay("Z:" + forecast_file_today, config.getint('Adafruit_LCD', 'LCD_WIDTH'), config.getint('Adafruit_LCD', 'LCD_HEIGHT'))
					msg_success = True
			elif AdaScreenNumber == 2:
				AdaScreenNumber += 1
				msg = FormatDisplay("BoM:" + forecast_bom_today, config.getint('Adafruit_LCD', 'LCD_WIDTH'), config.getint('Adafruit_LCD', 'LCD_HEIGHT'))
				msg_success = True
			elif AdaScreenNumber == 3:
				AdaScreenNumber += 1
				msg = FormatDisplay("Tmw:" + forecast_bom_tomorrow, config.getint('Adafruit_LCD', 'LCD_WIDTH'), config.getint('Adafruit_LCD', 'LCD_HEIGHT'))
				msg_success = True
			elif AdaScreenNumber == 4:
				AdaScreenNumber += 1
				msg = FormatDisplay("Nxt:" + forecast_bom_dayafter, config.getint('Adafruit_LCD', 'LCD_WIDTH'), config.getint('Adafruit_LCD', 'LCD_HEIGHT'))
				msg_success = True
			else:
				AdaScreenNumber = 0
		except:
			Log(LOG_LEVEL.ERROR, "WriteAdaLcd: Error creating message" + traceback.format_exc())
			msg = "Data Error"
	try:
		AdaLcd.clear()
	except:
		Log(LOG_LEVEL.ERROR, "WriteAdaLcd: Error clearing LCD" + traceback.format_exc())
	try:
		uv = readings[config.get('Adafruit_LCD', 'UV_CHANNEL')][0]
		if uv < 3.0:
			# Low
			AdaLcd.set_color(0.0, 1.0, 0.0)  # rgb(0,255,0)
		elif uv < 6.0:
			# Moderate
			AdaLcd.set_color(1.0, 1.0, 0.2)  # rgb(255,255,64)
		elif uv < 6.0:
			# High
			AdaLcd.set_color(1.0, 0.5, 0.2)  # rgb(255,128,64)
		elif uv < 11.0:
			# Very High
			AdaLcd.set_color(1.0, 0.2, 0.2)  # rgb(255,64,64)
		else:
			# Extreme
			AdaLcd.set_color(1.0, 0.2, 1.0)  # rgb(255,64,255)
	except:
		Log(LOG_LEVEL.ERROR, "WriteAdaLcd: Error setting backlight" + traceback.format_exc())
	try:
		AdaLcd.message(msg)
	except:
		Log(LOG_LEVEL.ERROR, "WriteAdaLcd: Error writing message" + traceback.format_exc())


def WriteConsole():
	Log(LOG_LEVEL.DEBUG, "WriteConsole: start")
	print time.ctime(),
	if config.getboolean('Output', 'BRUTAL_VIEW'):
		for reading in readings:
			value = readings[reading][0]
			try:
				print "{0}: {1:.1f}".format(reading, value),
			except:
				print "{0}: {1}".format(reading, value),
	else:
		try:
			print "TempIn: {0:0.1f}".format(readings[config.get('PYWWS', 'TEMP_IN_CHANNEL')][0]),
		except:
			print "TempIn: x",
		try:
			print "TempOut: {0:0.1f}".format(readings[config.get('PYWWS', 'TEMP_OUT_CHANNEL')][0]),
		except:
			print "TempOut: x",
		try:
			print "HumIn: {0:0.0f}%".format(readings[config.get('PYWWS', 'HUM_IN_CHANNEL')][0]),
		except:
			print "HumIn: x",
		try:
			print "HumOut: {0:0.0f}%".format(readings[config.get('PYWWS', 'HUM_OUT_CHANNEL')][0]),
		except:
			print "HumOut: x",
		try:
			print "Press: {0:0.0f}hPa".format(readings[config.get('PYWWS', 'ABS_PRESSURE_CHANNEL')][0]),
		except:
			print "Press: x",
		try:
			print "Illum: {0:0.1f}".format(readings[config.get('PYWWS', 'ILLUMINANCE_CHANNEL')][0]),
		except:
			print "Illum: x",
		try:
			print "IRLx: {0:0.1f}".format(readings[config.get('PYWWS', 'IR_CHANNEL')][0]),
		except:
			print "IRLx: x",
		try:
			print "UV: {0:0.1f}".format(readings[config.get('PYWWS', 'UV_CHANNEL')][0]),
		except:
			print "UV: x",
		try:
			print "Forecast: %s" % forecast_file_today,
		except:
			print "Forecast: x",
	print
	Log(LOG_LEVEL.DEBUG, "WriteConsole: Complete")


def WriteSenseHat():
	Log(LOG_LEVEL.DEBUG, "WriteSenseHat: start")
	global forecast_toggle
	if config.getint('Rates', 'FORECAST_REFRESH_RATE') > 0 and forecast_toggle == 1 and forecast_file_today:
		forecast_toggle = 0
		msg = forecast_file_today
	else:
		forecast_toggle = 1
		try:
			msg = "Ti:{0:0.1f} To:{1:0.1f} P:{2:0.0f} H:{3:0.0f}%".format(readings[config.get('PYWWS', 'TEMP_IN_CHANNEL')][0], readings[config.get('PYWWS', 'TEMP_OUT_CHANNEL')][0], readings[config.get('PYWWS', 'ABS_PRESSURE_CHANNEL')][0], readings[config.get('PYWWS', 'HUM_IN_CHANNEL')][0])
		except:
			msg = "Awaiting data"
	hour = datetime.now().hour
	if hour > config.getint('General', 'DAWN') and hour < config.getint('General', 'DUSK'):
		PiSenseHat.low_light = False
		Foreground = config.get('SenseHat', 'FG')
		if config.getboolean('SenseHat', 'COLOUR_BG'):
			Background = config.get('SenseHat', 'COLOUR_MID')
			if readings['temp_in'][0] <= config.get('SenseHat', 'COMFORT_LOW'):
				Background = config.get('SenseHat', 'COLOUR_COLD')
			elif readings['temp_in'][0] > config.get('SenseHat', 'COMFORT_HIGH'):
				Background = config.get('SenseHat', 'COLOUR_HOT')
		else:
			Background = config.get('SenseHat', 'BG')
	else:
		PiSenseHat.low_light = True
		Foreground = config.get('SenseHat', 'FG_NIGHT')
		if config.getboolean('SenseHat', 'COLOUR_BG'):
			Background = config.get('SenseHat', 'COLOUR_MID_NIGHT')
			if readings['temp_in'][0] < config.get('SenseHat', 'COMFORT_LOW'):
				Background = config.get('SenseHat', 'COLOUR_COLD_NIGHT')
			if readings['temp_in'][0] > config.get('SenseHat', 'COMFORT_HIGH'):
				Background = config.get('SenseHat', 'COLOUR_HOT_NIGHT')
		else:
			Background = config.get('SenseHat', 'BG_NIGHT')
	PiSenseHat.show_message(msg, scroll_speed=config.get('SenseHat', 'SCROLL'), text_colour=Foreground, back_colour=Background)
	PiSenseHat.clear()
	Log(LOG_LEVEL.DEBUG, "WriteSenseHat: Complete")


########
# CONFIG
########
CONFIG_FILE = 'PiWeather.ini'
ReadConfig()

########
# Optional
########
if config.getboolean('Output', 'ADA_LCD'):
	import Adafruit_CharLCD
	AdaLcd = Adafruit_CharLCD.Adafruit_CharLCDPlate()
	BootMessage("PiWeather Starting")
if config.getboolean('Sensors', 'BME280'):
	import Adafruit_BME280
	BmeSensor = Adafruit_BME280.BME280(mode=Adafruit_BME280.BME280_OSAMPLE_8)
if config.getboolean('Sensors', 'BMP085'):
	import Adafruit_BMP.BMP085
	BmpSensor = Adafruit_BMP.BMP085()
if config.getboolean('Sensors', 'ENOCEAN'):
	from enocean.communicators.serialcommunicator import SerialCommunicator as eoSerialCommunicator
	from enocean.protocol.constants import PACKET as EOPACKET, RORG as EORORG
	import enocean.utils
	if config.getint('General', 'LOG_LEVEL') >= LOG_LEVEL.DEBUG:
		from enocean.consolelogger import init_logging
	try:
		import queue
	except ImportError:
		import Queue as queue
if config.getboolean('Sensors', 'FORECAST_BOM'):
	import urllib2
	import xml.etree.ElementTree as ElementTree
if config.getboolean('Output', 'MQTT_PUBLISH'):
	import paho.mqtt.publish as publish
if config.getboolean('Output', 'PYWWS_PUBLISH'):
	from pywws import DataStore
if config.getboolean('Sensors', 'SENSEHAT') or config.getboolean('Output', 'SENSEHAT_DISPLAY'):
	from sense_hat import SenseHat
	PiSenseHat = SenseHat()
if config.getboolean('Sensors', 'SI1145'):
	import SI1145.SI1145 as SI1145
	SiSensor = SI1145.SI1145()

########
# Main
########
# Global Variables
AdaScreenNumber = 0
data = {}
forecast_bom_today = ""
forecast_bom_tomorrow = ""
forecast_bom_dayafter = ""
forecast_file_today = ""
forecast_toggle = 0
global_init = True
readings = {}
# pywws data
if config.getboolean('Output', 'PYWWS_PUBLISH'):
	ds = DataStore.data_store(config.get('PYWWS', 'STORAGE'))
	dstatus = DataStore.status(config.get('PYWWS', 'STORAGE'))
if config.getboolean('Output', 'SENSEHAT_DISPLAY'):
	# Set up display
	PiSenseHat.clear()
	PiSenseHat.set_rotation(config.get('SenseHat', 'ROTATION'))
if config.getboolean('Sensors', 'ENOCEAN'):
	if config.getint('General', 'LOG_LEVEL') >= LOG_LEVEL.DEBUG:
		init_logging()
	eoCommunicator = eoSerialCommunicator(port=config.get('EnOcean', 'PORT'))
	eoCommunicator.start()
	Log(LOG_LEVEL.INFO, "EnOceanSensors: Base ID: " + enocean.utils.to_hex_string(eoCommunicator.base_id) + " on port: " + config.get('EnOcean', 'PORT'))
# Warm up sensors
BootMessage("Waiting for sensors to settle")
for i in range(1, 6):
	Sample()
	time.sleep(1)
global_init = False
if config.getboolean('Sensors', 'FORECAST_BOM'):
	try:
		ForecastBoM()
	except Exception:
		Log(LOG_LEVEL.ERROR, "ForecastBoM: Error in initial call" + traceback.format_exc())
if config.getboolean('Sensors', 'FORECAST_FILE'):
	try:
		ForecastFile()
	except Exception:
		Log(LOG_LEVEL.ERROR, "ForecastBoM: Error in initial call" + traceback.format_exc())
Sample()
BootMessage("Scheduling events...")
scheduler = BackgroundScheduler()
scheduler.add_job(ReadConfig, 'interval', seconds=config.getint('Rates', 'CONFIG_REFRESH_RATE'), id='ReadConfig')
scheduler.add_job(Sample, 'interval', seconds=config.getint('Rates', 'SAMPLE_RATE'), id='Sample')
if config.getboolean('Sensors', 'ENOCEAN'):
	scheduler.add_job(EnOceanSensors, 'interval', args=[eoCommunicator], seconds=config.getint('Rates', 'ENOCEAN_RATE'), id='EnOcean')
if config.getboolean('Sensors', 'FORECAST_BOM'):
	scheduler.add_job(ForecastBoM, 'interval', seconds=config.getint('Rates', 'FORECASTBOM_REFRESH_RATE'), id='ForecastBoM')
if config.getboolean('Sensors', 'FORECAST_FILE'):
	scheduler.add_job(ForecastFile, 'interval', seconds=config.getint('Rates', 'FORECASTFILE_REFRESH_RATE'), id='ForecastFile')
if config.getboolean('Output', 'ADA_LCD'):
	scheduler.add_job(WriteAdaLcd, 'interval', seconds=config.getint('Rates', 'ADALCD_OUTPUT_RATE'), id='AdaLcd')
if config.getboolean('Output', 'CONSOLE_OUTPUT'):
	scheduler.add_job(WriteConsole, 'interval', seconds=config.getint('Rates', 'CONSOLE_OUTPUT_RATE'), id='Console')
if config.getboolean('Output', 'MQTT_PUBLISH'):
	scheduler.add_job(MqSendMultiple, 'interval', seconds=config.getint('Rates', 'MQTT_OUTPUT_RATE'), id='MQTT')
if config.getboolean('Output', 'PYWWS_PUBLISH'):
	scheduler.add_job(Store, 'interval', seconds=config.getint('Rates', 'STORE_RATE'), id='Store', args=[ds])
	scheduler.add_job(Flush, 'interval', seconds=config.getint('Rates', 'FLUSH_RATE'), id='Flush', args=[ds, dstatus])
if config.getboolean('Output', 'SENSEHAT_DISPLAY'):
	scheduler.add_job(WriteSenseHat, 'interval', seconds=config.getint('Rates', 'SENSEHAT_OUTPUT_RATE'), id='SenseHat')

scheduler.start()
if config.getboolean('Output', 'ADA_LCD'):
	WriteAdaLcd()
if config.getboolean('Output', 'CONSOLE_OUTPUT'):
	WriteConsole()
if config.getboolean('Output', 'MQTT_PUBLISH'):
	MqSendMultiple()
BootMessage("Entering event loop")

try:
	# This is here to simulate application activity (which keeps the main thread alive).
	while True:
		time.sleep(1)
except (KeyboardInterrupt, SystemExit):
	# Not strictly necessary if daemonic mode is enabled but should be done if possible
	BootMessage("Shutting down scheduler")
	scheduler.shutdown()
	if config.getboolean('Output', 'PYWWS_PUBLISH'):
		print "Flushing data"
		ds.flush()
		dstatus.flush()
	if config.getboolean('Output', 'ADA_LCD'):
		AdaLcd.clear()
	if config.getboolean('Output', 'SENSEHAT_DISPLAY'):
		PiSenseHat.clear()
	if config.getboolean('Sensors', 'ENOCEAN'):
		if eoCommunicator.is_alive():
			eoCommunicator.stop()
	BootMessage("Goodbye")
