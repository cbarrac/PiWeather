#!/usr/bin/env python

from sense_hat import SenseHat
import time

# CONFIG
ROTATION = 180
SCROLL = 0.09
FG = [128,128,0]
BG = [0,0,32]
SAMPLE_RATE = 5

sense = SenseHat()
# Screen upside down
sense.set_rotation(ROTATION)

import atexit

@atexit.register
def goodbye():
	print "You are now leaving the Python sector."
	ds.flush()
	sense.clear()

while True:
	# Sample from sensors
	t1 = sense.get_temperature_from_humidity()
	t2 = sense.get_temperature_from_pressure()
	p = sense.get_pressure()
	h = sense.get_humidity()
	t = ( t1 + t2 ) / 2
	t1 = round(t1,1)
	t2 = round(t2,1)
	t = round(t,1)
	p = round(p,1)
	h = round(h,1)
	msg = "Temp1: %s Temp2: %s Press: %s Hum: %s%%" % (t1,t2,p,h)
	print "%s Temp1: %s Temp2: %s TempAve: %s Press: %s Hum: %s%%" % (time.ctime(),t1,t2,t,p,h)
#	sense.show_message(msg, scroll_speed=SCROLL, text_colour=FG, back_colour=BG)
	time.sleep(SAMPLE_RATE)
