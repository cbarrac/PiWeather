# Raspberry Pi SenseHat + pywws
Read Temperature/Pressure/Humidity from a Raspberry Pi SenseHat

Write the data to a pywws DataStore

Process the data with pywws...

## Warning
I've stopped work on this project, as the readings I'm getting from the SenseHat seem way out. The Temperature inputs are impacted significantly by heat coming from the Raspberry Pi. Double-stacking the headers, using a heat-shield, turning off the display, moving USB wifi away on a cable... none of them work. Humidity is also very bad - 69% when it's raining?! (Government weather station just down the road said > 90%)

## Reading data
*Basic*: use `weather.py` - single-threaded, variable timing, not recommended

*Advanced*: use `weather_event.py` - multi-threaded, better timing, recommended

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
All the configuration is in the variables at the top of the file.

Look at the `# Event Periods` section for timing (in seconds)

`SMOOTHING` defines the size of the sliding window - used to average out readings

`ROTATION` defines which way the Hat is siting. GPIO pins in top left corner == 0,
USB ports top == 90 et cetera

_Daytime_ is considered any hour between `DAWN` and `DUSK`, outside this period
the `..._NIGHT` values are used for the SenseHat display.

A _comfortable_ temperature is considered any `temp_in` (Indoors) temperature between `COMFORT_LOW` and `COMFORT_HIGH`, and thus corresponds to a SenseHat background of `COLOUR_MID`, `COLOUR_COLD` and `COLOUR_HOT` are used either side of this comfort zone.

Note: `SCROLL` (scroll rate) - higher values == slower
