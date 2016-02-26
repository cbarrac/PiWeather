#!/usr/bin/env python

from datetime import datetime
from pywws import DataStore
import math
import numpy
import sys
import time
from apscheduler.schedulers.background import BackgroundScheduler

########
# CONFIG
########
DEBUG = 0
BRUTAL_VIEW = True
# Output directory for pywws
STORAGE = "/opt/weather/"
FORECAST_FILE = "minforecast.txt"
# Optional Sensors
BMP085 = False
BME280 = True
PISENSE = False
SI1145 = True
# Optional Output
ADA_LCD = True
CONSOLE_OUTPUT = True
PISENSE_DISPLAY = False
MQTT_PUBLISH = True
# Adafruit LCD
ADA_LCD_WIDTH = 16
# SenseHat Display
ROTATION = 90
SCROLL = 0.09
DAWN = 6
DUSK = 19
COLOUR_BG = True
# Colours
FG = [196,196,0]
BG = [0,0,64]
FG_NIGHT = [8,8,0]
BG_NIGHT = [0,0,0]
COLOUR_COLD = [0,16,32]
COLOUR_MID = [0,48,0]
COLOUR_HOT = [48,0,0]
COLOUR_COLD_NIGHT = [0,0,7]
COLOUR_MID_NIGHT = [0,7,0]
COLOUR_HOT_NIGHT = [7,0,0]
# Comfort Levels (Indoor Temp)
COMFORT_LOW = 22
COMFORT_HIGH = 28
# Calibration
# - Altitude above sea level, in metres
CALIB_ALTITUDE=195
CALIB_BMP085_PRESSURE=0
CALIB_BMP085_TEMP_IN=0
CALIB_BME280_PRESSURE=0
CALIB_BME280_TEMP_IN=0
CALIB_BME280_HUM_IN=0
CALIB_PISENSE_HUM_IN=0
CALIB_PISENSE_PRESSURE=18.5
CALIB_PISENSE_TEMP_IN=-2.4
CALIB_PISENSE_TEMP_OUT=-3.2
# https://www.adafruit.com/datasheets/Si1145-46-47.pdf
# Apparently all come with +256 offset
CALIB_SI1145_VISIBLE=-256
# Sunlight = 0.282; 2500K Incandescent = 0.319; "Cool white" flourescent = 0.146
# At gain 0, in High Signal Range mode "High Signal Range (Gain divided by 14.5)"
CALIB_SI1145_VISIBLE_RESPONSE=(0.282 / 14.5)
# Apparently all come with +256 offset
CALIB_SI1145_IR=-256
# Sunlight = 2.44; 2500K Incandescent=8.46; "Cool white" flourescent=0.71
# At gain 0, in High Signal Range mode "High Signal Range (Gain divided by 14.5)"
CALIB_SI1145_IR_RESPONSE=(2.44 / 14.5)
CALIB_SI1145_UV=0
# Estimated transmission of current glass covering
CALIB_SI1145_UV_RESPONSE=0.55
# Event Periods / Timers
ADALCD_OUTPUT_RATE = 15
CONSOLE_OUTPUT_RATE = 60
FLUSH_RATE = 180
FORECAST_REFRESH_RATE = 300
MQTT_OUTPUT_RATE = 60
SAMPLE_RATE = 10
SENSEHAT_OUTPUT_RATE = 30
STORE_RATE = 60
# Smoothing over ... values
SMOOTHING = 30
# Magic Values (used for 'empty')
MININT = -(sys.maxsize - 1)
# MQ Connectivity
MQTT_SERVER = "hab1.internal"
MQTT_PORT = 1883
MQTT_CLIENTID = "piweather"
MQTT_PREFIX = "/sensors/"

########
# Optional
########
if ADA_LCD:
	import Adafruit_CharLCD
	AdaLcd = Adafruit_CharLCD.Adafruit_CharLCDPlate()
if BME280:
	from Adafruit_BME280 import *
	BmeSensor = BME280(mode=BME280_OSAMPLE_8)
if BMP085:
	import Adafruit_BMP.BMP085 as BMP085
	BmpSensor = BMP085.BMP085()
if MQTT_PUBLISH:
	import paho.mqtt.publish as publish
if PISENSE or PISENSE_DISPLAY:
	from sense_hat import SenseHat
	PiSense = SenseHat()
if SI1145:
	import SI1145.SI1145 as SI1145
	SiSensor = SI1145.SI1145()

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

def Debug(message):
	if DEBUG == 1:
		print message

def DewPoint(RH,TempC):
	Debug("DewPoint: Calculating for RH:{0:.1f} and Temp: {1:.1f}".format(RH,TempC))
	# Paroscientific constants (0 <> 60 degc, 0 <> 100% RH)
	a = 6.105
	b = 17.271
	c = 237.7
	gamma = numpy.log(RH/100.0) + (b * TempC / (c + TempC))
	dp = (c * gamma) / (b - gamma)
	Debug("DewPoint is {0:.1f}".format(dp))
	return dp

def Flush(ds,dstatus):
	Debug("Flush: ds")
	ds.flush()
	Debug("Flush: Write dstatus")
	try:
		dstatus.set('last update', 'logged', datetime.utcnow().isoformat(' '))
		dstatus.set('fixed', 'fixed block', str(readings))
	except:
		Debug("Flush: Error setting status")
	Debug("Flush: dstatus")
	try:
		dstatus.flush()
	except:
		Debug("Flush: error in flush")
	Debug("Flush: Complete")

def ForecastRefresh():
	Debug("ForecastRefresh: start")
	if FORECAST_REFRESH_RATE == 0:
		return
	global forecast
	forecast_file = STORAGE + FORECAST_FILE
	try:
		with open(forecast_file) as f:
			forecast = f.read()
	except:
		forecast = ""
	Debug("ForecastRefresh: \"%s\"" % forecast)
	Debug("ForecastRefresh: Complete")

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

def MqClose():
    Debug("MqClose: Stopping loop")
    mqtt_client.loop_stop()
    Debug("MqClose: Disconnecting")
    mqtt_client.disconnect()
    Debug("MqClose: Complete")

def MqInit():
    global mqtt_client
    mqtt_client.connect(MQTT_SERVER, MQTT_PORT, 60)
    Debug("MqInit: Starting loop")
    mqtt_client.loop_start()

def MqSendMultiple():
	Debug("MqSendMultiple: Build Message")
	msgs = []
	for reading in readings:
		mq_path = MQTT_PREFIX + reading
		value = readings[reading][0]
		msg = {'topic':mq_path,'payload':value}
		Debug("MqSendMultiple: Payload Element {0}".format(msg))
		msgs.append(msg)
	Debug("MqSendMultiple: Sending multiple")
	try:
		publish.multiple(msgs,hostname=MQTT_SERVER,port=MQTT_PORT,client_id=MQTT_CLIENTID)
	except:
		Debug("Error sending MQTT message")
	Debug("MqSendMultiple: Complete")

def MqSendSingle(variable,value):
    mq_path = MQTT_PREFIX + variable
    Debug("MqSendSingle: Sending {0} = {1:0.1f}".format(mq_path,value))
    mqtt_client.publish(mq_path, value)

def RelToAbsHumidity(relativeHumidity, temperature):
	absoluteHumidity = 6.112 * math.exp((17.67 * temperature)/(temperature+243.5)) * relativeHumidity * 2.1674 / (273.15+temperature)
	return absoluteHumidity

def Sample():
	Debug("Sample: read")
	global readings
	if BME280:
		# !Make sure to read temperature first!
		# !The library sets OverSampling and waits for valid values _only_ in the read_raw_temperature function!
		try:
			Smoothing('temp_in', (BmeSensor.read_temperature() + CALIB_BME280_TEMP_IN))
			# Note: read_pressure returns Pa, divide by 100 for hectopascals (hPa)
			Smoothing('abs_pressure', ((BmeSensor.read_pressure()/100) + CALIB_ALTITUDE_PRESSURE_OFFSET + CALIB_BME280_PRESSURE))
			Smoothing('hum_in', (BmeSensor.read_humidity() + CALIB_BME280_HUM_IN))
		except:
			Debug("Error reading BME280")
	if BMP085:
		try:
			Smoothing('temp_in', (BmpSensor.read_temperature() + CALIB_BMP085_TEMP_IN))
			# Note: read_pressure returns Pa, divide by 100 for hectopascals (hPa)
			Smoothing('abs_pressure', ((BmpSensor.read_pressure()/100) + CALIB_BMP085_PRESSURE))
		except:
			Debug("Error reading BMP085")
	if PISENSE:
		try:
			Smoothing('abs_pressure', (PiSense.get_pressure() + CALIB_PISENSE_PRESSURE))
			Smoothing('hum_in', (PiSense.get_humidity() + CALIB_PISENSE_HUM_IN))
			Smoothing('temp_in', (PiSense.get_temperature_from_pressure() + CALIB_PISENSE_TEMP_IN))
			#Smoothing('temp_out', (PiSense.get_temperature_from_humidity() + CALIB_PISENSE_TEMP_OUT))
		except:
			Debug("Error reading PISENSE")
	if SI1145:
		try:
			Smoothing('illuminance', ((SiSensor.readVisible() + CALIB_SI1145_VISIBLE) / CALIB_SI1145_VISIBLE_RESPONSE))
			Smoothing('ir', ((SiSensor.readIR() + CALIB_SI1145_IR) / CALIB_SI1145_IR_RESPONSE))
			Smoothing('uv', (((SiSensor.readUV()/100.0) + CALIB_SI1145_UV) / CALIB_SI1145_UV_RESPONSE))
		except:
			Debug("Error reading SI1145")
	if BME280 or BMP085 or PISENSE:
		try:
			Smoothing('dew_point_in',DewPoint(readings['hum_in'][0],readings['temp_in'][0]))
		except:
			Debug("Error calculating Dew Point")
	Debug("Sample: Complete")

def Smoothing(channel, value):
	Debug("Smoothing: Begin")
	if global_init:
		Debug("Init Mode: returning with no storage")
		return
	average = 0
	global readings
	if readings.get(channel,None) is None:
		Debug("Init %s" % channel)
		readings[channel] = [MININT for x in xrange(SMOOTHING+1)]
	for i in range(1,(SMOOTHING)):
		if readings[channel][i+1] == MININT:
			readings[channel][i+1] = value
		readings[channel][i] = readings[channel][i+1]
		average += readings[channel][i]
	readings[channel][SMOOTHING] = value
	average += value
	average = average / SMOOTHING
	readings[channel][0] = average
	Debug("Smoothing: Readings[%s]: %s" % (channel, readings[channel]))
	Debug("Smoothing: Complete")

def Store(ds):
	Debug("Store: Write to data")
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
	Debug("Store: Write to ds")
	try:
		ds[datetime.utcnow()] = data
	except:
		Debug("Store: Error pushing data")
	Debug("Store: Complete")

def WriteAdaLcd():
	global AdaScreenNumber
	try:
		if AdaScreenNumber == 0:
			msg = "{0:0.1f}C {1:0.0f}% UV:{2:0.1f}\n{3:0.1f}hPa".format(readings['temp_in'][0],readings['hum_in'][0],readings['uv'][0],readings['abs_pressure'][0])
			AdaScreenNumber = 1
		elif AdaScreenNumber == 1:
			msg = FormatDisplay(forecast, ADA_LCD_WIDTH)
			AdaScreenNumber = 0
		else:
			msg = "No message"
			AdaScreenNumber = 0
	except:
		Debug("WriteAdaLcd: Error creating message")
		msg = "Data Error"
	try:
		AdaLcd.clear()
	except:
		Debug("WriteAdaLcd: Error clearing LCD")
	try:
		uv = readings['uv'][0]
		if uv < 3.0:
			# Low
			AdaLcd.set_color(0.0,1.0,0.0)	#rgb(0,255,0)
		elif uv < 6.0:
			# Moderate
			AdaLcd.set_color(1.0,1.0,0.0)	#rgb(255,255,0)
		elif uv < 6.0:
			# High
			AdaLcd.set_color(1.0,0.5,0.0)	#rgb(255,128,0)
		elif uv < 11.0:
			# Very High
			AdaLcd.set_color(1.0,0.0,0.0)	#rgb(255,0,0)
		else:
			# Extreme
			AdaLcd.set_color(1.0,0.0,1.0)	#rgb(255,0,255)
	except:
		Debug("WriteAdaLcd: Error setting backlight")
	try:
		AdaLcd.message(msg)
	except:
		Debug("WriteAdaLcd: Error writing message")

def WriteConsole():
	Debug("WriteConsole: start")
	print time.ctime(),
	if BRUTAL_VIEW:
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
	Debug("WriteConsole: Complete")

def WriteSenseHat():
	Debug("WriteSenseHat: start")
	global forecast_toggle
	if FORECAST_REFRESH_RATE > 0 and forecast_toggle == 1 and forecast:
		forecast_toggle = 0
		msg = forecast
	else:
		forecast_toggle = 1
		try:
			msg = "Ti:{0:0.1f} To:{1:0.1f} P:{2:0.0f} H:{3:0.0f}%".format(readings['temp_in'][0],readings['temp_out'][0],readings['abs_pressure'][0],readings['hum_in'][0])
		except:
			msg = "Awaiting data"
	hour = datetime.now().hour
	if hour > DAWN and hour < DUSK:
		PiSense.low_light = False
		Foreground = FG
		if COLOUR_BG:
			Background = COLOUR_MID
			if readings['temp_in'][0] <=COMFORT_LOW:
				Background = COLOUR_COLD
			elif readings['temp_in'][0] > COMFORT_HIGH:
				Background = COLOUR_HOT
		else:
			Background = BG
	else:
		PiSense.low_light = True
		Foreground = FG_NIGHT
		if COLOUR_BG:
			Background = COLOUR_MID_NIGHT
			if readings['temp_in'][0] < COMFORT_LOW:
				Background = COLOUR_COLD_NIGHT
			if readings['temp_in'][0] > COMFORT_HIGH:
				Background = COLOUR_HOT_NIGHT
		else:
			Background = BG_NIGHT
	PiSense.show_message(msg, scroll_speed=SCROLL, text_colour=Foreground, back_colour=Background)
	PiSense.clear()
	Debug("WriteSenseHat: Complete")




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
ds = DataStore.data_store(STORAGE)
dstatus = DataStore.status(STORAGE)
if ADA_LCD:
	AdaLcd.clear()
if PISENSE_DISPLAY:
	# Set up display
	PiSense.clear()
	PiSense.set_rotation(ROTATION)
CALIB_ALTITUDE_PRESSURE_OFFSET = AltitudeOffset(CALIB_ALTITUDE)
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
scheduler.add_job(Sample, 'interval', seconds=SAMPLE_RATE, id='Sample')
scheduler.add_job(Store, 'interval', seconds=STORE_RATE, id='Store', args=[ds])
scheduler.add_job(Flush, 'interval', seconds=FLUSH_RATE, id='Flush', args=[ds,dstatus])
scheduler.add_job(ForecastRefresh, 'interval', seconds=FORECAST_REFRESH_RATE, id='Forecast')
if ADA_LCD:
	scheduler.add_job(WriteAdaLcd, 'interval', seconds=ADALCD_OUTPUT_RATE, id='AdaLcd')
if CONSOLE_OUTPUT:
	scheduler.add_job(WriteConsole, 'interval', seconds=CONSOLE_OUTPUT_RATE, id='Console')
if MQTT_PUBLISH:
	scheduler.add_job(MqSendMultiple,'interval',seconds=MQTT_OUTPUT_RATE,id='MQTT')
if PISENSE_DISPLAY:
	scheduler.add_job(WriteSenseHat, 'interval', seconds=SENSEHAT_OUTPUT_RATE, id='SenseHat')

scheduler.start()
if ADA_LCD:
	WriteAdaLcd()
if CONSOLE_OUTPUT:
	WriteConsole()
if MQTT_PUBLISH:
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
	print "Flushing data"
	ds.flush()
	dstatus.flush()
	if ADA_LCD:
		AdaLcd.clear()
	if PISENSE or PISENSE_DISPLAY:
		PiSense.clear()
	print "Goodbye"
