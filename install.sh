#!/bin/sh
apt-get -y install python-pip python-dev build-essential python-smbus git python-numpy
pip install APScheduler
pip install numpy
pip install pyusb
# Optional
pip install enocean
pip install paho-mqtt
git clone https://github.com/adafruit/Adafruit_Python_CharLCD.git
cd Adafruit_Python_CharLCD && python setup.py install
cd ..
#git clone https://github.com/adafruit/Adafruit_Python_BME280.git
#git clone https://github.com/kipe/enocean.git
git clone https://github.com/THP-JOE/Python_SI1145.git
cd Python_SI1145 && python setup.py install
cd ..
