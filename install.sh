#!/bin/sh
apt-get install python3 python3-pip python3-venv
# Fulfil requirements for numpy
apt-get install libatlas-base-dev
#Recommended (for i2cdetect - `/usr/sbin/i2cdetect -y 1`):
#apt-get install i2c-tools

# Enable I2C on RPi
echo “dtparam i2c_arm=on” >> /boot/config.txt
echo "i2c_dev" >> /etc/modules-load.d/modules.conf ; echo "i2c_bcm2708" >> /etc/modules-load.d/modules.conf

cd /opt
# Grab source
git clone https://github.com/cbarrac/PiWeather.git
# Create Virtual Environment
python3 -m venv PiWeather
cd PiWeather
source bin/activate
# Install packages
pip3 install -r requirements.txt

# Install service
#sudo cp weather_event.service /etc/systemd/system/
# Enable at startup
#sudo systemctl enable weather_event