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
import sys
import time

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
	p2 = 2.25577 * math.pow(10,-5)
	p1 = 1 - (p2 * Altitude)
	p = 101325 * math.pow (p1,5.25588)
	# Pressure at Sea Level
	s = 101325 * math.pow (1,5.25588)
	return (s - p) / 100

def DewPoint(RH,TempC):
	Log(LOG_LEVEL.INFO,"DewPoint: Calculating for RH:{0:.1f} and Temp: {1:.1f}".format(RH,TempC))
	# Paroscientific constants (0 <> 60 degc, 0 <> 100% RH)
	a = 6.105
	b = 17.271
	c = 237.7
	gamma = numpy.log(RH/100.0) + (b * TempC / (c + TempC))
	dp = (c * gamma) / (b - gamma)
	Log(LOG_LEVEL.INFO,"DewPoint is {0:.1f}".format(dp))
	return dp

def EnOceanSensors():
	while eoCommunicator.is_alive():
		try:
			# Loop to empty the queue...
			packet = eoCommunicator.receive.get(block=False)
			if packet.type == EOPACKET.RADIO and packet.rorg == EORORG.BS4:
				# parse packet with given FUNC and TYPE
				for k in packet.parse_eep(0x02, 0x05):
					temp = packet.parsed[k]['value']
					transmitter_id = packet.sender_hex
					transmitter_name = MapSensor(transmitter_id)
					Log(LOG_LEVEL.INFO,"EnOceanSensors: {0}({1}): {2:0.1f}".format(transmitter_name, transmitter_id, temp))
					Smoothing(transmitter_name, temp)
		except queue.Empty:
			return
		except Exception:
			import traceback
			traceback.print_exc(file=sys.stdout)

def Flush(ds,dstatus):
	Log(LOG_LEVEL.DEBUG,"Flush: ds")
	ds.flush()
	Log(LOG_LEVEL.DEBUG,"Flush: Write dstatus")
	try:
		dstatus.set('last update', 'logged', datetime.utcnow().isoformat(' '))
		dstatus.set('fixed', 'fixed block', str(readings))
	except:
		Log(LOG_LEVEL.ERROR,"Flush: Error setting status")
	Log(LOG_LEVEL.DEBUG,"Flush: dstatus")
	try:
		dstatus.flush()
	except:
		Log(LOG_LEVEL.ERROR,"Flush: error in flush")
	Log(LOG_LEVEL.DEBUG,"Flush: Complete")

def ForecastRefresh():
	Log(LOG_LEVEL.DEBUG,"ForecastRefresh: start")
	global forecast
	forecast_file = config.get('ForecastFile','FILE')
	try:
		with open(forecast_file) as f:
			forecast = f.read()
	except:
		forecast = ""
	Log(LOG_LEVEL.INFO,"ForecastRefresh: \"%s\"" % forecast)
	Log(LOG_LEVEL.DEBUG,"ForecastRefresh: Complete")

def FormatDisplay(input,max_length):
    input_len = len(input)
    if (input_len < max_length):
        return input
    else:
        words = input.split()
        display = ""
        length = 0
        for word in words:
            len_word = len(word)
            if (length + len_word) < max_length:
                display = display + word + " "
                length = length + len_word + 1
            else:
                display = display + "\n" + word + " "
                length = len_word + 1
        return display

def Log(level,message):
	# None, Error, Info, Debug
	# 0     1      2     3
	if config.getint('General','LOG_LEVEL') >= level:
		print message

def MapSensor(sensor_id):
	sid = sensor_id.replace(':','')
	try:
		return config.get('EnOcean',sid)
	except:
		return sensor_id

def MqClose():
    Log(LOG_LEVEL.DEBUG,"MqClose: Stopping loop")
    mqtt_client.loop_stop()
    Log(LOG_LEVEL.DEBUG,"MqClose: Disconnecting")
    mqtt_client.disconnect()
    Log(LOG_LEVEL.DEBUG,"MqClose: Complete")

def MqInit():
    global mqtt_client
    mqtt_client.connect(config.get('MQTT','SERVER'), config.getint('MQTT','PORT'), config.getint('MQTT','TIMEOUT'))
    Log(LOG_LEVEL.DEBUG,"MqInit: Starting loop")
    mqtt_client.loop_start()

def MqSendMultiple():
	Log(LOG_LEVEL.DEBUG,"MqSendMultiple: Build Message")
	msgs = []
	for reading in readings:
		mq_path = config.get('MQTT','PREFIX') + reading
		value = readings[reading][0]
		msg = {'topic':mq_path,'payload':value}
		Log(LOG_LEVEL.DEBUG,"MqSendMultiple: Payload Element {0}".format(msg))
		msgs.append(msg)
	Log(LOG_LEVEL.DEBUG,"MqSendMultiple: Sending multiple")
	try:
		publish.multiple(msgs,hostname=config.get('MQTT','SERVER'),port=config.getint('MQTT','PORT'),client_id=config.get('MQTT','CLIENTID'))
	except:
		Log(LOG_LEVEL.ERROR,"Error sending MQTT message")
	Log(LOG_LEVEL.DEBUG,"MqSendMultiple: Complete")

def MqSendSingle(variable,value):
    mq_path = config.get('MQTT','PREFIX') + variable
    Log(LOG_LEVEL.DEBUG,"MqSendSingle: Sending {0} = {1:0.1f}".format(mq_path,value))
    mqtt_client.publish(mq_path, value)

def ReadConfig():
	global config
	config.read(CONFIG_FILE)

def RelToAbsHumidity(relativeHumidity, temperature):
	absoluteHumidity = 6.112 * math.exp((17.67 * temperature)/(temperature+243.5)) * relativeHumidity * 2.1674 / (273.15+temperature)
	return absoluteHumidity

def Sample():
	Log(LOG_LEVEL.DEBUG,"Sample: read")
	global readings
	if config.getboolean('Sensors','BME280'):
		# !Make sure to read temperature first!
		# !The library sets OverSampling and waits for valid values _only_ in the read_raw_temperature function!
		try:
			Smoothing('temp_in', (BmeSensor.read_temperature() + config.getfloat('Calibration','BME280_TEMP_IN')))
			# Note: read_pressure returns Pa, divide by 100 for hectopascals (hPa)
			Smoothing('abs_pressure', ((BmeSensor.read_pressure()/100.0) + config.get('Calibration','ALTITUDE_PRESSURE_OFFSET',1) + config.getfloat('Calibration','BME280_PRESSURE')))
			Smoothing('hum_in', (BmeSensor.read_humidity() + config.getfloat('Calibration','BME280_HUM_IN')))
		except:
			Log(LOG_LEVEL.ERROR,"Error reading BME280")

	if config.getboolean('Sensors','BMP085'):
		try:
			Smoothing('temp_in', (BmpSensor.read_temperature() + config.getfloat('Calibration','BMP085_TEMP_IN')))
			# Note: read_pressure returns Pa, divide by 100 for hectopascals (hPa)
			Smoothing('abs_pressure', ((BmpSensor.read_pressure()/100.0) + config.getfloat('Calibration','BMP085_PRESSURE')))
		except:
			Log(LOG_LEVEL.ERROR,"Error reading BMP085")
	if config.getboolean('Sensors','SENSEHAT'):
		try:
			Smoothing('abs_pressure', (PiSenseHat.get_pressure() + config.get('Calibration','ALTITUDE_PRESSURE_OFFSET',1) + config.getfloat('Calibration','SENSEHAT_PRESSURE')))
			Smoothing('hum_in', (PiSenseHat.get_humidity() + config.getfloat('Calibration','SENSEHAT_HUM_IN')))
			Smoothing('temp_in', (PiSenseHat.get_temperature_from_pressure() + config.getfloat('Calibration','SENSEHAT_TEMP_IN')))
		except:
			Log(LOG_LEVEL.ERROR,"Error reading SENSEHAT")
	if config.getboolean('Sensors','SI1145'):
		try:
			Smoothing('illuminance', ((SiSensor.readVisible() + config.getfloat('Calibration','SI1145_VISIBLE')) / config.getfloat('Calibration','SI1145_VISIBLE_RESPONSE')))
			Smoothing('ir', ((SiSensor.readIR() + config.getfloat('Calibration','SI1145_IR')) / config.getfloat('Calibration','SI1145_IR_RESPONSE')))
			Smoothing('uv', (((SiSensor.readUV()/100.0) + config.getfloat('Calibration','SI1145_UV')) / config.getfloat('Calibration','SI1145_UV_RESPONSE')))
		except:
			Log(LOG_LEVEL.ERROR,"Error reading SI1145")
	if config.getboolean('Sensors','BME280') or config.getboolean('Sensors','BMP085') or config.getboolean('Sensors','SENSEHAT'):
		try:
			Smoothing('dew_point_in',DewPoint(readings['hum_in'][0],readings['temp_in'][0]))
		except:
			Log(LOG_LEVEL.ERROR,"Error calculating Dew Point")
	Log(LOG_LEVEL.DEBUG,"Sample: Complete")

def Smoothing(channel, value):
	Log(LOG_LEVEL.DEBUG,"Smoothing: Begin")
	if global_init:
		Log(LOG_LEVEL.DEBUG,"Init Mode: returning with no storage")
		return
	average = 0
	global readings
	if readings.get(channel,None) is None:
		Log(LOG_LEVEL.DEBUG,"Init %s" % channel)
		readings[channel] = [config.getint('General','MININT') for x in xrange(config.getint('General','SMOOTHING')+1)]
	for i in range(1,(config.getint('General','SMOOTHING'))):
		if readings[channel][i+1] == config.getint('General','MININT'):
			readings[channel][i+1] = value
		readings[channel][i] = readings[channel][i+1]
		average += readings[channel][i]
	readings[channel][config.getint('General','SMOOTHING')] = value
	average += value
	average = average / config.getint('General','SMOOTHING')
	readings[channel][0] = average
	Log(LOG_LEVEL.DEBUG,"Smoothing: Readings[%s]: %s" % (channel, readings[channel]))
	Log(LOG_LEVEL.DEBUG,"Smoothing: Complete")

def Store(ds):
	Log(LOG_LEVEL.DEBUG,"Store: Write to data")
	global data
	data = {}
	try:
		data['abs_pressure'] = int(readings['abs_pressure'][0])
	except:
		data['abs_pressure'] = None
	data['delay'] = int(0)
	try:
		data['hum_in'] = int(readings['hum_in'][0])
	except:
		data['hum_in'] = None
	try:
		data['hum_out'] = int(readings['hum_out'][0])
	except:
		data['hum_out'] = None
	try:
		data['illuminance'] = float(readings['illuminance'][0])
	except:
		data['illuminance'] = None
	try:
		data['rain'] = float(readings['rain'][0])
	except:
		data['rain'] = 0
	data['status'] = 0
	try:
		data['temp_in'] = float(readings['temp_in'][0])
	except:
		data['temp_in'] = None
	try:
		data['temp_out'] = float(readings['temp_out'][0])
	except:
		data['temp_out'] = None
	try:
		data['uv'] = int(readings['uv'][0])
	except:
		data['uv'] = None
	try:
		data['wind_ave'] = float(readings['wind_ave'][0])
	except:
		data['wind_ave'] = None
	try:
		data['wind_dir'] = int(readings['wind_dir'][0])
	except:
		data['wind_dir'] = None
	try:
		data['wind_gust'] = float(readings['wind_gust'][0])
	except:
		data['wind_gust'] = None
	Log(LOG_LEVEL.DEBUG,"Store: Write to ds")
	try:
		ds[datetime.utcnow()] = data
	except:
		Log(LOG_LEVEL.ERROR,"Store: Error pushing data")
	Log(LOG_LEVEL.DEBUG,"Store: Complete")

def WriteAdaLcd():
	global AdaScreenNumber
	try:
		if AdaScreenNumber == 0:
			msg = "{0:0.1f}C {1:0.0f}% UV:{2:0.1f}\n{3:0.1f}hPa".format(readings['temp_in'][0],readings['hum_in'][0],readings['uv'][0],readings['abs_pressure'][0])
			AdaScreenNumber = 1
		elif AdaScreenNumber == 1:
			msg = FormatDisplay(forecast, config.getint('Adafruit_LCD','LCD_WIDTH'))
			AdaScreenNumber = 0
		else:
			msg = "No message"
			AdaScreenNumber = 0
	except:
		Log(LOG_LEVEL.ERROR,"WriteAdaLcd: Error creating message")
		msg = "Data Error"
	try:
		AdaLcd.clear()
	except:
		Log(LOG_LEVEL.ERROR,"WriteAdaLcd: Error clearing LCD")
	try:
		uv = readings['uv'][0]
		if uv < 3.0:
			# Low
			AdaLcd.set_color(0.3,1.0,0.3)	#rgb(64,255,64)
		elif uv < 6.0:
			# Moderate
			AdaLcd.set_color(1.0,1.0,0.3)	#rgb(255,255,64)
		elif uv < 6.0:
			# High
			AdaLcd.set_color(1.0,0.5,0.3)	#rgb(255,128,64)
		elif uv < 11.0:
			# Very High
			AdaLcd.set_color(1.0,0.3,0.3)	#rgb(255,64,64)
		else:
			# Extreme
			AdaLcd.set_color(1.0,0.3,1.0)	#rgb(255,64,255)
	except:
		Log(LOG_LEVEL.ERROR,"WriteAdaLcd: Error setting backlight")
	try:
		AdaLcd.message(msg)
	except:
		Log(LOG_LEVEL.ERROR,"WriteAdaLcd: Error writing message")

def WriteConsole():
	Log(LOG_LEVEL.DEBUG,"WriteConsole: start")
	print time.ctime(),
	if config.getboolean('Output','BRUTAL_VIEW'):
		for reading in readings:
			value = readings[reading][0]
			print "{0}: {1:.1f}".format(reading,value),
	else:
		try:
			print "TempIn: {0:0.1f}".format(readings['temp_in'][0]),
		except:
			print "TempIn: x",
		try:
			print "TempOut: {0:0.1f}".format(readings['temp_out'][0]),
		except:
			print "TempOut: x",
		try:
			print "HumIn: {0:0.0f}%".format(readings['hum_in'][0]),
		except:
			print "HumIn: x",
		try:
			print "HumOut: {0:0.0f}%".format(readings['hum_out'][0]),
		except:
			print "HumOut: x",
		try:
			print "Press: {0:0.0f}hPa".format(readings['abs_pressure'][0]),
		except:
			print "Press: x",
		try:
			print "Illum: {0:0.1f}".format(readings['illuminance'][0]),
		except:
			print "Illum: x",
		try:
			print "IRLx: {0:0.1f}".format(readings['ir'][0]),
		except:
			print "IRLx: x",
		try:
			print "UV: {0:0.1f}".format(readings['uv'][0]),
		except:
			print "UV: x",
	try:
		print "Forecast: %s" % forecast,
	except:
		print "Forecast: x",
	print
	Log(LOG_LEVEL.DEBUG,"WriteConsole: Complete")

def WriteSenseHat():
	Log(LOG_LEVEL.DEBUG,"WriteSenseHat: start")
	global forecast_toggle
	if config.getint('Rates','FORECAST_REFRESH_RATE') > 0 and forecast_toggle == 1 and forecast:
		forecast_toggle = 0
		msg = forecast
	else:
		forecast_toggle = 1
		try:
			msg = "Ti:{0:0.1f} To:{1:0.1f} P:{2:0.0f} H:{3:0.0f}%".format(readings['temp_in'][0],readings['temp_out'][0],readings['abs_pressure'][0],readings['hum_in'][0])
		except:
			msg = "Awaiting data"
	hour = datetime.now().hour
	if hour > config.getint('General','DAWN') and hour < config.getint('General','DUSK'):
		PiSenseHat.low_light = False
		Foreground = config.get('SenseHat','FG')
		if config.getboolean('SenseHat','COLOUR_BG'):
			Background = config.get('SenseHat','COLOUR_MID')
			if readings['temp_in'][0] <= config.get('SenseHat','COMFORT_LOW'):
				Background = config.get('SenseHat','COLOUR_COLD')
			elif readings['temp_in'][0] > config.get('SenseHat','COMFORT_HIGH'):
				Background = config.get('SenseHat','COLOUR_HOT')
		else:
			Background = config.get('SenseHat','BG')
	else:
		PiSenseHat.low_light = True
		Foreground = config.get('SenseHat','FG_NIGHT')
		if config.getboolean('SenseHat','COLOUR_BG'):
			Background = config.get('SenseHat','COLOUR_MID_NIGHT')
			if readings['temp_in'][0] < config.get('SenseHat','COMFORT_LOW'):
				Background = config.get('SenseHat','COLOUR_COLD_NIGHT')
			if readings['temp_in'][0] > config.get('SenseHat','COMFORT_HIGH'):
				Background = config.get('SenseHat','COLOUR_HOT_NIGHT')
		else:
			Background = config.get('SenseHat','BG_NIGHT')
	PiSenseHat.show_message(msg, scroll_speed=config.get('SenseHat','SCROLL'), text_colour=Foreground, back_colour=Background)
	PiSenseHat.clear()
	Log(LOG_LEVEL.DEBUG,"WriteSenseHat: Complete")


########
# CONFIG
########
config = configparser.ConfigParser()
CONFIG_FILE = 'PiWeather.ini'
ReadConfig()

########
# Optional
########
if config.getboolean('Output','ADA_LCD'):
	import Adafruit_CharLCD
	AdaLcd = Adafruit_CharLCD.Adafruit_CharLCDPlate()
if config.getboolean('Sensors','BME280'):
	from Adafruit_BME280 import *
	BmeSensor = BME280(mode=BME280_OSAMPLE_8)
if config.getboolean('Sensors','BMP085'):
	import Adafruit_BMP.BMP085 as BMP085
	BmpSensor = BMP085.BMP085()
if config.getboolean('Sensors','ENOCEAN'):
	from enocean.communicators.serialcommunicator import SerialCommunicator as eoSerialCommunicator
	from enocean.protocol.constants import PACKET as EOPACKET, RORG as EORORG
	try:
		import queue
	except ImportError:
		import Queue as queue
if config.getboolean('Output','MQTT_PUBLISH'):
	import paho.mqtt.publish as publish
if config.getboolean('Output','PYWWS_PUBLISH'):
	from pywws import DataStore
if config.getboolean('Sensors','SENSEHAT') or config.getboolean('Output','SENSEHAT_DISPLAY'):
	from sense_hat import SenseHat
	PiSenseHat = SenseHat()
if config.getboolean('Sensors','SI1145'):
	import SI1145.SI1145 as SI1145
	SiSensor = SI1145.SI1145()

########
# Main
########
# Global Variables
AdaScreenNumber = 0
data = {}
forecast = ""
forecast_toggle = 0
global_init=True
readings = {}
# pywws data
if config.getboolean('Output','PYWWS_PUBLISH'):
	ds = DataStore.data_store(config.get('PYWWS','STORAGE'))
	dstatus = DataStore.status(config.get('PYWWS','STORAGE'))
if config.getboolean('Output','ADA_LCD'):
	AdaLcd.clear()
if config.getboolean('Output','SENSEHAT_DISPLAY'):
	# Set up display
	PiSenseHat.clear()
	PiSenseHat.set_rotation(config.get('SenseHat','ROTATION'))
try:
	config.get('Calibration','ALTITUDE_PRESSURE_OFFSET',1)
except:
	PressureOffset = AltitudeOffset(config.getint('Calibration','ALTITUDE'))
	Log(LOG_LEVEL.INFO,"PressureOffset: {}".format(PressureOffset))
	config.set('Calibration','ALTITUDE_PRESSURE_OFFSET', PressureOffset)
if config.getboolean('Sensors','ENOCEAN'):
	eoCommunicator = eoSerialCommunicator(port=config.get('EnOcean','PORT'))
	eoCommunicator.start()
# Warm up sensors
print "Waiting for sensors to settle"
for i in range(1,6):
	Sample()
	time.sleep(1)
global_init=False
ForecastRefresh()
Sample()
print "Scheduling events..."
scheduler = BackgroundScheduler()
scheduler.add_job(ReadConfig, 'interval', seconds=config.getint('Rates', 'CONFIG_REFRESH_RATE'), id='ReadConfig')
scheduler.add_job(Sample, 'interval', seconds=config.getint('Rates','SAMPLE_RATE'), id='Sample')
if config.getboolean('Sensors','ENOCEAN'):
	scheduler.add_job(EnOceanSensors, 'interval', seconds=config.getint('Rates','ENOCEAN_RATE'), id='EnOcean')
if config.getboolean('Sensors','FORECAST_FILE'):
	scheduler.add_job(ForecastRefresh, 'interval', seconds=config.getint('Rates','FORECASTFILE_REFRESH_RATE'), id='Forecast')
if config.getboolean('Output','ADA_LCD'):
	scheduler.add_job(WriteAdaLcd, 'interval', seconds=config.getint('Rates','ADALCD_OUTPUT_RATE'), id='AdaLcd')
if config.getboolean('Output','CONSOLE_OUTPUT'):
	scheduler.add_job(WriteConsole, 'interval', seconds=config.getint('Rates','CONSOLE_OUTPUT_RATE'), id='Console')
if config.getboolean('Output','MQTT_PUBLISH'):
	scheduler.add_job(MqSendMultiple,'interval',seconds=config.getint('Rates','MQTT_OUTPUT_RATE'),id='MQTT')
if config.getboolean('Output','PYWWS_PUBLISH'):
	scheduler.add_job(Store, 'interval', seconds=config.getint('Rates','STORE_RATE'), id='Store', args=[ds])
	scheduler.add_job(Flush, 'interval', seconds=config.getint('Rates','FLUSH_RATE'), id='Flush', args=[ds,dstatus])
if config.getboolean('Output','SENSEHAT_DISPLAY'):
	scheduler.add_job(WriteSenseHat, 'interval', seconds=config.getint('Rates','SENSEHAT_OUTPUT_RATE'), id='SenseHat')

scheduler.start()
if config.getboolean('Output','ADA_LCD'):
	WriteAdaLcd()
if config.getboolean('Output','CONSOLE_OUTPUT'):
	WriteConsole()
if config.getboolean('Output','MQTT_PUBLISH'):
	MqSendMultiple()
print "Entering event loop"

try:
	# This is here to simulate application activity (which keeps the main thread alive).
	while True:
		time.sleep(1)
except (KeyboardInterrupt, SystemExit):
	# Not strictly necessary if daemonic mode is enabled but should be done if possible
	print "Shutting down scheduler"
	scheduler.shutdown()
	if config.getboolean('Output','PYWWS_PUBLISH'):
		print "Flushing data"
		ds.flush()
		dstatus.flush()
	if config.getboolean('Output','ADA_LCD'):
		AdaLcd.clear()
	if config.getboolean('Output','SENSEHAT_DISPLAY'):
		PiSenseHat.clear()
	if config.getboolean('Sensors','ENOCEAN'):
		if eoCommunicator.is_alive():
			eoCommunicator.stop()
	print "Goodbye"
