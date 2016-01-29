#!/usr/bin/env python
from sense_hat import SenseHat
import time

sense = SenseHat()

try:
	while True:
		orientation = sense.get_orientation_degrees()
		print "Yaw: %s \tPitch: %s \tRoll: %s" % (orientation['yaw'],orientation['pitch'],orientation['roll'])
                time.sleep(1)
except (KeyboardInterrupt, SystemExit):
	print "Bye!"
