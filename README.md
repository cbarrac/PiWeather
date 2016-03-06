# Raspberry Pi SenseHat + pywws
Read Temperature/Pressure/Humidity from a Raspberry Pi [SenseHat](https://www.raspberrypi.org/products/sense-hat/)

Write the data to a [pywws](https://github.com/jim-easterbrook/pywws) DataStore

Process the data with pywws...

Read the forecast back from pywws

Read the forecast from Australia's BoM

Output to MQTT (Useful for things like OpenHAB integration)

Output to a local LCD display

## Warning
I've stopped work on the PiSense parts of this project, as the readings I'm getting from the SenseHat seem way out. The Temperature inputs are impacted significantly by heat coming from the Raspberry Pi. Double-stacking the headers, using a heat-shield, turning off the display, moving USB wifi away on a cable... none of them work. Relative Humidity is also very bad - 69% when it's raining?! (Government weather station just down the road said > 90%)

## Sensors
* Raspberry Pi SenseHat - not recommended
* Adafruit BME280 - Temperature, Pressure, Humidity
* Adafruit SI1124 - Light, UV
* Adafruit BMP085 - Temperature, Pressure
* EnOcean - Only Temperature sensors are decoded at the moment.

## Displays
* Adafruit 16x2 RGB LCD Display (on an Adafruit Pi Plate - providing an i2c interface)
* Raspberry Pi SenseHat

## Reading data
Use `weather_event.py` - multi-threaded, better timing, recommended

## Timing
`weather_event.py` uses APScheduler to handle threading and timing. Each
section of code runs on a separate timer/thread:
* Sample: Read SenseHat, send to a smoothing function
* Store: Send data to pywws's DataStore
* Flush: Tell pywws's DataStore to write to disk
* ForecastRefresh: Grab the latest forecast from pywws, for display on the Hat
* WriteConsole: Output Temperature/Pressure/Humidity to stdout/console
* WriteSenseHat: Output Temperature/Pressure/Humidity to the Hat

## Configuration
All the configuration is in the `PiWeather.ini` file. A sample called
`PiWeather.ini-example` is included. Copy and edit as appropriate.
Configuration is reloaded on a timer (See the `Rates` section of the config
file)

Look at the `Rates` section for timing (in seconds)

`SMOOTHING` defines the size of the sliding window - used to average out readings

### Sense Hat
`ROTATION` defines which way the SenseHat is siting. GPIO pins in top left corner == 0,
USB ports top == 90 et cetera

_Daytime_ is considered any hour between `DAWN` and `DUSK`, outside this period
the `..._NIGHT` values are used for the SenseHat display.

A _comfortable_ temperature is considered any `temp_in` (Indoors) temperature between `COMFORT_LOW` and `COMFORT_HIGH`, and thus corresponds to a SenseHat background of `COLOUR_MID`, `COLOUR_COLD` and `COLOUR_HOT` are used either side of this comfort zone.

Note: `SCROLL` (scroll rate) - higher values == slower

### EnOcean
Channel names for recording the data (e.g. for pushing to MQTT) are stored in
the configuration file. Each sensor has an entry with its hexadecimal address
and a name. e.g. `01812345 = room1`, would mean an sensor with address
`01:81:23:45` would be stored as `room1`

### BoM
Find your state [here](http://www.bom.gov.au/info/precis_forecasts.shtml), it will look something like `IDV10753`
Have a look inside the XML, and find your nearest BoM forecast area, it will look something like `VIC_PT042`
