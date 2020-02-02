#!/bin/sh
apt-get -y install python3-pip python3-dev build-essential python3-smbus git python3-numpy libatlas-base-dev
pip3 install APScheduler
pip3 install numpy
pip3 install pyusb
pip3 install RPi.GPIO
# Optional
pip3 install enocean
pip3 install paho-mqtt
git clone https://github.com/adafruit/Adafruit_Python_CharLCD.git
cd Adafruit_Python_CharLCD && python3 setup.py install
cd ..
#git clone https://github.com/adafruit/Adafruit_Python_BME280.git
#git clone https://github.com/kipe/enocean.git
git clone https://github.com/THP-JOE/Python_SI1145.git
cd Python_SI1145 && python3 setup.py install
cd ..
