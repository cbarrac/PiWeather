#!/usr/bin/env python

from datetime import datetime
from pywws import DataStore
import sys
import time
from apscheduler.schedulers.background import BackgroundScheduler

########
# CONFIG
########
DEBUG = 0
# Output directory for pywws
STORAGE = "/opt/weather/"
FORECAST_FILE = "minforecast.txt"
# Optional Sensors
BMP085 = False
BME280 = True
PISENSE = False
SI1145 = True
# Optional Display
PISENSE_DISPLAY = False
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
CALIB_SI1145_VISIBLE=0
# Sunlight = 0.282; 2500K Incandescent = 0.319; "Cool white" flourescent = 0.146
CALIB_SI1145_VISIBLE_RESPONSE=0.282
CALIB_SI1145_IR=0
# Sunlight = 2.44; 2500K Incandescent=8.46; "Cool white" flourescent=0.71
CALIB_SI1145_IR_RESPONSE=2.44
CALIB_SI1145_UV=0
# Event Periods
SAMPLE_RATE = 10
STORE_RATE = 60
FLUSH_RATE = 180
FORECAST_REFRESH_RATE = 300
CONSOLE_OUTPUT_RATE = 60
SENSEHAT_OUTPUT_RATE = 30
SMOOTHING = 6
# Magic Values (used for 'empty')
MININT = -(sys.maxsize - 1)

########
# Optional
########
if BME280:
	from Adafruit_BME280 import *
	BmeSensor = BME280(mode=BME280_OSAMPLE_8)
if BMP085:
	import Adafruit_BMP.BMP085 as BMP085
	BmpSensor = BMP085.BMP085()
if PISENSE or PISENSE_DISPLAY:
	from sense_hat import SenseHat
	PiSense = SenseHat()
if SI1145:
	import SI1145.SI1145 as SI1145
	SiSensor = SI1145.SI1145()

########
# Functions
########
def Debug(message):
	if DEBUG == 1:
		print message

def Flush(ds,dstatus):
	Debug("Flush: ds")
	ds.flush()
	Debug("Flush: Write dstatus")
	dstatus.set('last update', 'logged', datetime.utcnow().isoformat(' '))
	dstatus.set('fixed', 'fixed block', str(readings))
	Debug("Flush: dstatus")
	dstatus.flush()
	Debug("Flush: complete")

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
	Debug("ForecastRefresh: complete")

def RelToAbsHumidity(relativeHumidity, temperature):
	absoluteHumidity = 6.112 * math.exp((17.67 * temperature)/(temperature+243.5)) * relativeHumidity * 2.1674 / (273.15+temperature)
	return absoluteHumidity

def Sample():
	Debug("Sample: read")
	global readings
	if BME280:
		# !Make sure to read temperature first!
		# !The library sets OverSampling and waits for valid values _only_ in the read_raw_temperature function!
		Smoothing('temp_in', (BmeSensor.read_temperature() + CALIB_BME280_TEMP_IN))
		# Note: read_pressure returns Pa, divide by 100 for hectopascals (hPa)
		Smoothing('abs_pressure', ((BmeSensor.read_pressure()/100) + CALIB_BME280_PRESSURE))
		Smoothing('hum_in', (BmeSensor.read_humidity() + CALIB_BME280_HUM_IN))
	if BMP085:
		Smoothing('temp_in', (BmpSensor.read_temperature() + CALIB_BMP085_TEMP_IN))
		# Note: read_pressure returns Pa, divide by 100 for hectopascals (hPa)
		Smoothing('abs_pressure', ((BmpSensor.read_pressure()/100) + CALIB_BMP085_PRESSURE))
	if PISENSE:
		Smoothing('abs_pressure', (PiSense.get_pressure() + CALIB_PISENSE_PRESSURE))
		Smoothing('hum_in', (PiSense.get_humidity() + CALIB_PISENSE_HUM_IN))
		Smoothing('temp_in', (PiSense.get_temperature_from_pressure() + CALIB_PISENSE_TEMP_IN))
		#Smoothing('temp_out', (PiSense.get_temperature_from_humidity() + CALIB_PISENSE_TEMP_OUT))
	if SI1145:
		Smoothing('illuminance', ((SiSensor.readVisible() / CALIB_SI1145_VISIBLE_RESPONSE) + CALIB_SI1145_VISIBLE))
		Smoothing('ir', ((SiSensor.readIR() / CALIB_SI1145_IR_RESPONSE) + CALIB_SI1145_IR))
		Smoothing('uv', ((SiSensor.readUV()/100) + CALIB_SI1145_UV))
	Debug("Sample: complete")

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
	Debug("Smoothing: complete")

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
	ds[datetime.utcnow()] = data
	Debug("Store: complete")

def WriteConsole():
	Debug("WriteConsole: start")
	print time.ctime(),
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
	Debug("WriteConsole: complete")

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
	Debug("WriteSenseHat: complete")




########
# Main
########
# Global Variables
data = {}
forecast = ""
forecast_toggle = 0
global_init=True
readings = {}
# pywws data
ds = DataStore.data_store(STORAGE)
dstatus = DataStore.status(STORAGE)
if PISENSE_DISPLAY:
	# Set up display
	PiSense.clear()
	PiSense.set_rotation(ROTATION)
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
scheduler.add_job(WriteConsole, 'interval', seconds=CONSOLE_OUTPUT_RATE, id='Console')
if PISENSE_DISPLAY:
	scheduler.add_job(WriteSenseHat, 'interval', seconds=SENSEHAT_OUTPUT_RATE, id='SenseHat')
scheduler.start()
WriteConsole()
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
	if PISENSE or PISENSE_DISPLAY:
		PiSense.clear()
	print "Goodbye"
