#!/usr/bin/env python

from sense_hat import SenseHat
from datetime import datetime
from pywws import DataStore
import time

# CONFIG
ROTATION = 0
SCROLL = 0.09
FG = [128,128,0]
BG = [0,0,64]
FG_NIGHT = [50,50,0]
BG_NIGHT = [0,0,0]
DAWN = 6
DUSK = 19
SAMPLE_RATE = 30
SLEEP = 12
STORAGE = "/opt/weather/"
SYNC_RATE = 5

sense = SenseHat()
sense.clear()
# Screen upside down
sense.set_rotation(ROTATION)

# Warm up sensors
sense.get_temperature()
sense.get_pressure()
sense.get_humidity()
print "Waiting for sensors to settle"
time.sleep(SLEEP/2)

# Clean exit
import atexit
@atexit.register
def goodbye():
	print "You are now leaving the Python sector."
	ds.flush()
	dstatus.flush()
	sense.clear()

# pywws data
ds = DataStore.data_store(STORAGE)
dstatus = DataStore.status(STORAGE)
sync_counter = 0
while True:
	utcdate = datetime.utcnow()
	localdate = datetime.now()
	hour = localdate.hour
	# Sample from sensors
	# t = sense.get_temperature_from_humidity()
	t = sense.get_temperature_from_pressure()
	p = sense.get_pressure()
	h = sense.get_humidity()
	t = round(t,1)
	p = round(p,1)
	h = round(h,1)
	msg = "Temp: %s Press: %s Hum: %s" % (t,p,h)
	print "%s Temp: %s Press: %s Hum: %s" % (time.ctime(),t,p,h)

	data = {}
	data['abs_pressure'] = int(p)
	data['delay'] = int(SAMPLE_RATE)
	data['hum_in'] = int(h)
	data['hum_out'] = None
	data['illuminance'] = None
	data['rain'] = 0
	data['status'] = 0
	data['temp_in'] = float(t)
	data['temp_out'] = None
	data['uv'] = None
	data['wind_ave'] = None
	data['wind_dir'] = None
	data['wind_gust'] = None
	ds[utcdate] = data

	if hour > DAWN and hour < DUSK:
		sense.low_light = False
		sense.show_message(msg, scroll_speed=SCROLL, text_colour=FG, back_colour=BG)
	else:
		sense.low_light = True
		sense.show_message(msg, scroll_speed=SCROLL, text_colour=FG_NIGHT, back_colour=BG_NIGHT)
	sync_counter += 1
	if sync_counter >= SYNC_RATE:
		ds.flush()
		dstatus.set('last update', 'logged', utcdate.isoformat(' '))
		dstatus.set('fixed', 'fixed block', data)
		dstatus.flush()
		sync_counter = 0
	time.sleep(SLEEP)
