#!/bin/sh
apt-get -y install python-pip python-dev build-essential python-smbus git python-numpy
pip install --upgrade APScheduler
pip install --upgrade enum-compat
pip install --upgrade numpy
pip install --upgrade RPi.GPIO
# Optional
pip install --upgrade enocean
pip install --upgrade paho-mqtt
cd Adafruit_Python_GPIO && git pull && python setup.py install
cd ..
cd Adafruit_Python_CharLCD && git pull && python setup.py install
cd ..
cd Python_SI1145 && git pull && python setup.py install
cd ..
