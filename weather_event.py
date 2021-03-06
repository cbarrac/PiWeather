#!/usr/bin/env python
"""Read in and display environmental sensors."""
import ast
from datetime import datetime
try:
    import configparser
except ImportError:
    import configparser as configparser
import logging
import math
from multiprocessing import Lock
import time
import numpy
from apscheduler.schedulers.background import BackgroundScheduler
from usb.core import find as finddev


# Global Variables
AdaScreenNumber = 0
config = configparser.ConfigParser()
data = {}
forecast_bom_today = ""
forecast_bom_tomorrow = ""
forecast_bom_dayafter = ""
forecast_file_today = ""
forecast_toggle = 0
global_init = True
logging.basicConfig()
log = logging.getLogger("weather_event")
mutex = Lock()
readings = {}


########
# Functions
########
def AltitudeOffset(Altitude):
    """Calculate the pressure offset, based upon current altitude."""
    # p = 101325 (1 - 2.25577 10-5 h)5.25588
    # Pressure at Altitude
    p2 = 2.25577 * math.pow(10, -5)
    p1 = 1 - (p2 * Altitude)
    p = 101325 * math.pow(p1, 5.25588)
    # Pressure at Sea Level
    s = 101325 * math.pow(1, 5.25588)
    return (s - p) / 100


def BootMessage(msg):
    """Output messages to the LCD screen on boot-up."""
    print(msg)
    log.info(msg)
    if config.getboolean('Output', 'ADA_LCD'):
        try:
            AdaLcd.clear()
            AdaLcd.color = [128,128,128]
            msg = FormatDisplay(msg, config.getint('Adafruit_LCD', 'LCD_WIDTH'), config.getint('Adafruit_LCD', 'LCD_HEIGHT'))
            AdaLcd.message = msg
        except (NameError):
            log.debug("LCD not initialised")
        except Exception as e:
            print("Could not write to LCD")
            print(e);


def DewPoint(RH, TempC):
    """Calculate the Dew Point for a given temperature and relative humidity."""
    log.info("DewPoint: Calculating for RH:{0:.1f} and Temp: {1:.1f}".format(RH, TempC))
    # Paroscientific constants (0 <> 60 degc, 0 <> 100% RH)
    # a = 6.105
    b = 17.271
    c = 237.7
    gamma = numpy.log(RH/100.0) + (b * TempC / (c + TempC))
    dp = (c * gamma) / (b - gamma)
    log.info("DewPoint is {0:.1f}".format(dp))
    return dp


def EnOceanSensors(eoComms):
    """Read temperature from EnOcean wireless sensors."""
    log.debug("EnOceanSensors: Begin")
    with mutex:
        try:
            log.debug("EnOceanSensors: Alive: %s", str(eoComms.is_alive()))
        except Exception:
            log.exception("EnOceanSensors: Error in communications")
        if not eoComms.is_alive():
            try:
                eoComms.stop()
                time.sleep(10)
            except Exception:
                log.exception("EnOceanSensors: Error stopping communications")
            try:
                dev = finddev(idVendor=0x0403, idProduct=0x6001)
                dev.reset()
                time.sleep(10)
            except Exception:
                log.exception("EnOceanSensors: Error reseting device")
            try:
                eoComms = eoSerialCommunicator(port=config.get('EnOcean', 'PORT'))
                eoComms.start()
                log.info("EnOceanSensors: Re-opened communications on port %s", config.get('EnOcean', 'PORT'))
            except Exception:
                log.exception("EnOceanSensors: Error in communications")
        while eoComms.is_alive():
            try:
                # Loop to empty the queue...
                log.debug("EnOceanSensors: Receive Loop")
                packet = eoComms.receive.get(block=False)
                log.debug("EnOceanSensors: Packet received")
                if packet.packet_type == EOPACKET.RADIO and packet.rorg == EORORG.BS4:
                    # parse packet with given FUNC and TYPE
                    # func="0x02" description="Temperature Sensors"
                    # type="0x05" description="Temperature Sensor Range 0degC to +40degC"
                    for k in packet.parse_eep(0x02, 0x05):
                        temp = packet.parsed[k]['value']
                        transmitter_id = packet.sender_hex
                        transmitter_name = MapSensor(transmitter_id)
                        log.info("EnOceanSensors: {0}({1}): {2:0.1f}".format(transmitter_name, transmitter_id, temp))
                        for _ in range(config.getint('EnOcean', 'ANTI_SMOOTHING')):
                            Smoothing(transmitter_name, temp)
            except queue.Empty:
                return
            except Exception:
                log.exception("EnOceanSensors: Error in communications")


def Flush(datastore, datastatus):
    """Write out the pywws data store."""
    log.debug("Flush: datastore")
    datastore.flush()
    log.debug("Flush: Write dstatus")
    try:
        datastatus.set('last update', 'logged', datetime.utcnow().isoformat(' '))
        datastatus.set('fixed', 'fixed block', str(readings))
    except Exception:
        log.exception("Flush: Error setting status")
    log.debug("Flush: dstatus")
    try:
        datastatus.flush()
    except Exception:
        log.exception("Flush: error in flush")
    log.debug("Flush: Complete")


def ForecastBoM():
    """Obtain weather predictions from the Bureau of Meteorology."""
    log.debug("ForecastBoM: start")
    FORECAST_BASE_URL = config.get('BoM', 'FORECAST_BASE_URL')
    FORECAST_STATE_ID = config.get('BoM', 'FORECAST_STATE_ID')
    FORECAST_AAC = config.get('BoM', 'FORECAST_AAC')
    Forecast_URL = FORECAST_BASE_URL + FORECAST_STATE_ID + '.xml'
    log.debug("ForecastBoM: Connecting to %s", Forecast_URL)
    global forecast_bom_today
    global forecast_bom_tomorrow
    global forecast_bom_dayafter
    try:
        response = urllib.request.urlopen(Forecast_URL, timeout=180)
        ForecastXML = response.read()
    except Exception:
        log.exception("ForecastBoM: Error downloading forecast file:")
        return (forecast_bom_today, forecast_bom_tomorrow, forecast_bom_dayafter)
    try:
        ForecastTree = ElementTree.fromstring(ForecastXML)
    except Exception:
        log.exception("ForecastBoM: Error parsing forecast file:")
        return (forecast_bom_today, forecast_bom_tomorrow, forecast_bom_dayafter)
    # Today
    try:
        xmlDay = ForecastTree.find("./forecast/area[@aac='" + FORECAST_AAC + "']/forecast-period[@index='0']")
    except Exception:
        log.exception("ForecastBoM: Error finding area element for today:")
    try:
        max_temp = xmlDay.find("*[@type='air_temperature_maximum']").text
        StorePoint('BoM', 'FORECAST_CHANNEL_TODAY_MAX', max_temp)
    except Exception:
        log.exception("ForecastBoM: Error finding forecast element:")
        max_temp = "?"
    try:
        forecast_text = xmlDay.find("*[@type='precis']").text
    except Exception:
        log.exception("ForecastBoM: Error finding forecast element:")
        forecast_text = "?"
    try:
        rain_chance = xmlDay.find("*[@type='probability_of_precipitation']").text
        if rain_chance[-1] == '%':
            rain_chance = rain_chance[:-1]
        StorePoint('BoM', 'FORECAST_CHANNEL_TODAY_RAIN', rain_chance)
    except Exception:
        log.exception("ForecastBoM: Error finding forecast element:")
        rain_chance = "?"
    forecast_bom_today = "Max {0} {1}% {2}".format(max_temp, rain_chance, forecast_text)
    log.info("ForecastBoM: Today: %s", forecast_bom_today)
    StorePoint('BoM', 'FORECAST_CHANNEL_TODAY', forecast_bom_today)
    # Tomorrow
    try:
        xmlDay = ForecastTree.find("./forecast/area[@aac='" + FORECAST_AAC + "']/forecast-period[@index='1']")
    except Exception:
        log.exception("ForecastBoM: Error finding area element for tomorrow:")
    try:
        min_temp = xmlDay.find("*[@type='air_temperature_minimum']").text
        StorePoint('BoM', 'FORECAST_CHANNEL_TOMORROW_MIN', min_temp)
    except Exception:
        min_temp = "?"
    try:
        max_temp = xmlDay.find("*[@type='air_temperature_maximum']").text
        StorePoint('BoM', 'FORECAST_CHANNEL_TOMORROW_MAX', max_temp)
    except Exception:
        max_temp = "?"
    try:
        forecast_text = xmlDay.find("*[@type='precis']").text
    except Exception:
        forecast_text = "?"
    try:
        rain_chance = xmlDay.find("*[@type='probability_of_precipitation']").text
        if rain_chance[-1] == '%':
            rain_chance = rain_chance[:-1]
        StorePoint('BoM', 'FORECAST_CHANNEL_TOMORROW_RAIN', rain_chance)
    except Exception:
        rain_chance = "?"
    forecast_bom_tomorrow = "{0}-{1} {2}% {3}".format(min_temp, max_temp, rain_chance, forecast_text)
    log.info("ForecastBoM: Tomorrow: %s", forecast_bom_tomorrow)
    StorePoint('BoM', 'FORECAST_CHANNEL_TOMORROW', forecast_bom_tomorrow)
    # Day after tomorrow
    try:
        xmlDay = ForecastTree.find("./forecast/area[@aac='" + FORECAST_AAC + "']/forecast-period[@index='2']")
    except Exception:
        log.exception("ForecastBoM: Error finding area element for day after tomorrow:")
    try:
        min_temp = xmlDay.find("*[@type='air_temperature_minimum']").text
        StorePoint('BoM', 'FORECAST_CHANNEL_DAYAFTER_MIN', min_temp)
    except Exception:
        min_temp = "?"
    try:
        max_temp = xmlDay.find("*[@type='air_temperature_maximum']").text
        StorePoint('BoM', 'FORECAST_CHANNEL_DAYAFTER_MAX', max_temp)
    except Exception:
        max_temp = "?"
    try:
        forecast_text = xmlDay.find("*[@type='precis']").text
    except Exception:
        forecast_text = "?"
    try:
        rain_chance = xmlDay.find("*[@type='probability_of_precipitation']").text
        if rain_chance[-1] == '%':
            rain_chance = rain_chance[:-1]
        StorePoint('BoM', 'FORECAST_CHANNEL_DAYAFTER_RAIN', rain_chance)
    except Exception:
        rain_chance = "?"
    forecast_bom_dayafter = "{0}-{1} {2}% {3}".format(min_temp, max_temp, rain_chance, forecast_text)
    log.info("ForecastBoM: Day After Tomorrow: %s", forecast_bom_dayafter)
    StorePoint('BoM', 'FORECAST_CHANNEL_DAYAFTER', forecast_bom_dayafter)
    return (forecast_bom_today, forecast_bom_tomorrow, forecast_bom_dayafter)


def ForecastFile():
    """Read in weather forecasts from the filesystem."""
    log.debug("ForecastFile: start")
    global forecast_file_today
    forecast_filename = config.get('ForecastFile', 'FILE')
    try:
        with open(forecast_filename) as foreFile:
            forecast_file_today = foreFile.read()
    except Exception:
        log.exception("ForecastFile: Error reading forecast from file")
    StorePoint('ForecastFile', 'FORECAST_CHANNEL', forecast_file_today)
    log.info("ForecastFile: \"%s\"", forecast_file_today)
    log.debug("ForecastFile: Complete")


def FormatDisplay(input_text, max_length, max_height):
    """Format the supplied string, to fit the (LCD) display."""
    input_len = len(input_text)
    if input_len < max_length:
        return input_text
    words = input_text.split()
    display = ""
    length = 0
    height = 1
    for word in words:
        len_word = len(word)
        if (length + len_word) <= max_length:
            display = display + word + " "
            length = length + len_word + 1
        elif height == max_height:
            trunc = max_length - length
            display = display + word[0:trunc]
            return display
        else:
            display = display + "\n" + word + " "
            length = len_word + 1
            height = height + 1
    return display


def MapSensor(sensor_id):
    """Map a Sensor ID to its location."""
    sid = sensor_id.replace(':', '')
    try:
        return config.get('EnOcean', sid)
    except Exception:
        return sensor_id


def MqSendMultiple():
    """Send multiple bits of data to the MQTT server."""
    log.debug("MqSendMultiple: Build Message")
    msgs = []
    for reading in readings:
        mq_path = config.get('MQTT', 'PREFIX') + reading
        value = readings[reading][0]
        msg = {'topic': mq_path, 'payload': value}
        log.debug("MqSendMultiple: Payload Element %s", msg)
        msgs.append(msg)
    log.debug("MqSendMultiple: Sending multiple")
    try:
        publish.multiple(msgs, hostname=config.get('MQTT', 'SERVER'), port=config.getint('MQTT', 'PORT'), client_id=config.get('MQTT', 'CLIENTID'))
    except Exception:
        log.exception("Error sending MQTT message")
    log.debug("MqSendMultiple: Complete")


def on_mqtt_connect(mqttc, userdata, flags, rc):
    """Connect handler for MQTT Client - subscribe to topics."""
    log.info("MqttClient: Connect")
    topics = ast.literal_eval(config.get('HOMIE_INPUT', 'TOPICS'))
    for val in topics:
        log.debug("Subscribing to topic : " + val)
        mqttc.subscribe(val, 0)


def on_mqtt_message(mqttc, userdata, msg):
    """Event handler for receipt of an MQTT message."""
    log.debug(msg.topic + " " + str(msg.payload))
    topicParts = re.split('/', msg.topic)
    devicemap = ast.literal_eval(config.get('HOMIE_INPUT', 'DEVICES'))
    if topicParts[1] in devicemap:
        deviceID = devicemap[topicParts[1]]
        log.debug("Device: " + str(deviceID))
        for _ in range(config.getint('HOMIE_INPUT', 'ANTI_SMOOTHING')):
            Smoothing(deviceID, float(msg.payload))


def ReadConfig():
    """Read configuration from disk."""
    print("Reading configuration")
    global config
    lconfig = configparser.ConfigParser()
    lconfig.read(CONFIG_FILE)
    try:
        lconfig.getfloat('Calibration', 'ALTITUDE_PRESSURE_OFFSET')
    except Exception:
        PressureOffset = AltitudeOffset(lconfig.getint('Calibration', 'ALTITUDE'))
        log.info("Altitude Calibration calculated at '{0}'".format(PressureOffset))
        lconfig.set('Calibration', 'ALTITUDE_PRESSURE_OFFSET', str(PressureOffset))
    config = lconfig


def RelToAbsHumidity(relativeHumidity, temperature):
    """Convert Relative Humidity to Absolute Humidity, for a given temperature."""
    absoluteHumidity = 6.112 * math.exp((17.67 * temperature)/(temperature+243.5)) * relativeHumidity * 2.1674 / (273.15+temperature)
    return absoluteHumidity


def Sample():
    """Read all the configured (local) sensor inputs."""
    log.debug("Sample: read")
    global readings
    if config.getboolean('Sensors', 'BME280'):
        # !Make sure to read temperature first!
        # !The library sets OverSampling and waits for valid values _only_ in the read_raw_temperature function!
        try:
            Smoothing(config.get('BME280', 'TEMPERATURE_CHANNEL'), (BmeSensor.temperature + config.getfloat('Calibration', 'BME280_TEMP_IN')))
            # Note: pressure now reads hectopascals (hPa) directly
            Smoothing(config.get('BME280', 'PRESSURE_CHANNEL'), (BmeSensor.pressure + config.getfloat('Calibration', 'ALTITUDE_PRESSURE_OFFSET') + config.getfloat('Calibration', 'BME280_PRESSURE')))
            Smoothing(config.get('BME280', 'HUMIDITY_CHANNEL'), (BmeSensor.humidity + config.getfloat('Calibration', 'BME280_HUM_IN')))
        except Exception:
            log.exception("Error reading BME280: ")

    if config.getboolean('Sensors', 'BMP085'):
        try:
            Smoothing(config.get('BMP085', 'TEMPERATURE_CHANNEL'), (BmpSensor.read_temperature() + config.getfloat('Calibration', 'BMP085_TEMP_IN')))
            # Note: read_pressure returns Pa, divide by 100 for hectopascals (hPa)
            Smoothing(config.get('BME280', 'PRESSURE_CHANNEL'), ((BmpSensor.read_pressure()/100.0) + config.getfloat('Calibration', 'BMP085_PRESSURE')))
        except Exception:
            log.exception("Error reading BMP085")
    if config.getboolean('Sensors', 'SENSEHAT'):
        try:
            Smoothing(config.get('SENSEHAT', 'PRESSURE_CHANNEL'), (PiSenseHat.get_pressure() + config.getfloat('Calibration', 'ALTITUDE_PRESSURE_OFFSET') + config.getfloat('Calibration', 'SENSEHAT_PRESSURE')))
            Smoothing(config.get('SENSEHAT', 'HUMIDITY_CHANNEL'), (PiSenseHat.get_humidity() + config.getfloat('Calibration', 'SENSEHAT_HUM_IN')))
            Smoothing(config.get('SENSEHAT', 'TEMPERATURE_CHANNEL'), (PiSenseHat.get_temperature_from_pressure() + config.getfloat('Calibration', 'SENSEHAT_TEMP_IN')))
        except Exception:
            log.exception("Error reading SENSEHAT")
    if config.getboolean('Sensors', 'SI1145'):
        try:
            Smoothing(config.get('SI1145', 'VISIBLE_CHANNEL'), ((SiSensor.readVisible() + config.getfloat('Calibration', 'SI1145_VISIBLE')) / config.getfloat('Calibration', 'SI1145_VISIBLE_RESPONSE')))
            Smoothing(config.get('SI1145', 'IR_CHANNEL'), ((SiSensor.readIR() + config.getfloat('Calibration', 'SI1145_IR')) / config.getfloat('Calibration', 'SI1145_IR_RESPONSE')))
            Smoothing(config.get('SI1145', 'UV_CHANNEL'), (((SiSensor.readUV()/100.0) + config.getfloat('Calibration', 'SI1145_UV')) / config.getfloat('Calibration', 'SI1145_UV_RESPONSE')))
        except Exception:
            log.exception("Error reading SI1145")
    if config.getboolean('Sensors', 'DEWPOINT_CALC') and not global_init:
        try:
            Smoothing(config.get('DewPoint', 'DEWPOINT_CHANNEL'), DewPoint(readings[config.get('DewPoint', 'HUMIDITY_CHANNEL')][0], readings[config.get('DewPoint', 'TEMPERATURE_CHANNEL')][0]))
        except Exception:
            log.exception("Error calculating Dew Point")
    log.debug("Sample: Complete")


def Smoothing(channel, value):
    """Apply smoothing (averaging) to the supplied data."""
    log.debug("Smoothing: %s", channel)
    if global_init:
        log.debug("Init Mode: returning with no storage")
        return
    average = 0
    global readings
    if readings.get(channel, None) is None:
        log.debug("Init %s", channel)
        readings[channel] = [config.getint('General', 'MININT') for _ in range(config.getint('General', 'SMOOTHING')+1)]
    for i in range(1, (config.getint('General', 'SMOOTHING'))):
        if readings[channel][i+1] == config.getint('General', 'MININT'):
            readings[channel][i+1] = value
        readings[channel][i] = readings[channel][i+1]
        average += readings[channel][i]
    readings[channel][config.getint('General', 'SMOOTHING')] = value
    average += value
    average = average / config.getint('General', 'SMOOTHING')
    readings[channel][0] = average


def Store(datastore):
    """Output data to the pywws store."""
    log.debug("Store: Write to data")
    global data
    data = {}
    try:
        data['abs_pressure'] = int(readings[config.get('PYWWS', 'ABS_PRESSURE_CHANNEL')][0])
    except Exception:
        data['abs_pressure'] = None
    data['delay'] = int(0)
    try:
        data['hum_in'] = int(readings[config.get('PYWWS', 'HUM_IN_CHANNEL')][0])
    except Exception:
        data['hum_in'] = None
    try:
        data['hum_out'] = int(readings[config.get('PYWWS', 'HUM_OUT_CHANNEL')][0])
    except Exception:
        data['hum_out'] = None
    try:
        data['illuminance'] = float(readings[config.get('PYWWS', 'ILLUMINANCE_CHANNEL')][0])
    except Exception:
        data['illuminance'] = None
    try:
        data['rain'] = float(readings[config.get('PYWWS', 'RAIN_CHANNEL')][0])
    except Exception:
        data['rain'] = 0
    data['status'] = 0
    try:
        data['temp_in'] = float(readings[config.get('PYWWS', 'TEMP_IN_CHANNEL')][0])
    except Exception:
        data['temp_in'] = None
    try:
        data['temp_out'] = float(readings[config.get('PYWWS', 'TEMP_OUT_CHANNEL')][0])
    except Exception:
        data['temp_out'] = None
    try:
        data['uv'] = int(readings[config.get('PYWWS', 'UV_CHANNEL')][0])
    except Exception:
        data['uv'] = None
    try:
        data['wind_ave'] = float(readings[config.get('PYWWS', 'WIND_AVE_CHANNEL')][0])
    except Exception:
        data['wind_ave'] = None
    try:
        data['wind_dir'] = int(readings[config.get('PYWWS', 'WIND_DIR_CHANNEL')][0])
    except Exception:
        data['wind_dir'] = None
    try:
        data['wind_gust'] = float(readings[config.get('PYWWS', 'WIND_GUST_CHANNEL')][0])
    except Exception:
        data['wind_gust'] = None
    log.debug("Store: Write to datastore")
    try:
        datastore[datetime.utcnow()] = data
    except Exception:
        log.exception("Store: Error pushing data")
    log.debug("Store: Complete")


def StorePoint(category, channel, value):
    try:
        channel = config.get(category, channel)
        if readings.get(channel, None) is None:
            readings[channel] = [0]
        readings[channel][0] = value
    except Exception:
        log.exception("Could not store reading: {0} - {1}: {2}".format(category, channel, value))

def WriteAdaLcd():
    """Write out status to the Ada LCD screen."""
    global AdaScreenNumber
    msg_success = False
    while not msg_success:
        try:
            if AdaScreenNumber == 0:
                AdaScreenNumber += 1
                if config.getboolean('Sensors', 'SI1145'):
                    msg = "{0:0.1f}C {1:0.0f}% UV{2:0.1f}\n{3:0.1f}hPa".format(readings[config.get('PYWWS', 'TEMP_IN_CHANNEL')][0], readings[config.get('PYWWS', 'HUM_IN_CHANNEL')][0], readings[config.get('PYWWS', 'UV_CHANNEL')][0], readings[config.get('PYWWS', 'ABS_PRESSURE_CHANNEL')][0])
                else:
                    msg = "T:{0:0.1f}C Hum:{1:0.0f}%\nPress:{2:0.1f}hPa".format(readings[config.get('PYWWS', 'TEMP_IN_CHANNEL')][0], readings[config.get('PYWWS', 'HUM_IN_CHANNEL')][0], readings[config.get('PYWWS', 'ABS_PRESSURE_CHANNEL')][0])
                msg_success = True
            elif AdaScreenNumber == 1:
                AdaScreenNumber += 1
                if config.getboolean('Sensors', 'FORECAST_FILE'):
                    msg = FormatDisplay("Z:" + forecast_file_today, config.getint('Adafruit_LCD', 'LCD_WIDTH'), config.getint('Adafruit_LCD', 'LCD_HEIGHT'))
                    msg_success = True
            elif AdaScreenNumber == 2:
                AdaScreenNumber += 1
                msg = FormatDisplay("BoM:" + forecast_bom_today, config.getint('Adafruit_LCD', 'LCD_WIDTH'), config.getint('Adafruit_LCD', 'LCD_HEIGHT'))
                msg_success = True
            elif AdaScreenNumber == 3:
                AdaScreenNumber += 1
                msg = FormatDisplay("Tmw:" + forecast_bom_tomorrow, config.getint('Adafruit_LCD', 'LCD_WIDTH'), config.getint('Adafruit_LCD', 'LCD_HEIGHT'))
                msg_success = True
            elif AdaScreenNumber == 4:
                AdaScreenNumber += 1
                msg = FormatDisplay("Nxt:" + forecast_bom_dayafter, config.getint('Adafruit_LCD', 'LCD_WIDTH'), config.getint('Adafruit_LCD', 'LCD_HEIGHT'))
                msg_success = True
            # ----------------
            elif AdaScreenNumber == 5:
                AdaScreenNumber += 1
                if readings.get('temperature/computer_room', None) is None:
                    t_computer_room = "?"
                else:
                    t_computer_room = "{0:0.1f}".format(readings['temperature/computer_room'][0])
                if readings.get('temperature/c_bedroom', None) is None:
                    t_c_bedroom = "?"
                else:
                    t_c_bedroom = "{0:0.1f}".format(readings['temperature/c_bedroom'][0])
                if readings.get('temperature/outside', None) is None:
                    t_outside = "?"
                else:
                    t_outside = "{0:0.1f}".format(readings['temperature/outside'][0])
                if readings.get('temperature/m_bedroom', None) is None:
                    t_m_bedroom = "?"
                else:
                    t_m_bedroom = "{0:0.1f}".format(readings['temperature/m_bedroom'][0])

                msg = FormatDisplay("U:" + t_computer_room + " C:" + t_c_bedroom + " O:" + t_outside + " M:" + t_m_bedroom, config.getint('Adafruit_LCD', 'LCD_WIDTH'), config.getint('Adafruit_LCD', 'LCD_HEIGHT'))
                msg_success = True
            # ----------------
            elif AdaScreenNumber == 6:
                AdaScreenNumber += 1
                if readings.get('power/battery_power', None) is None:
                    p_power_battery = "?"
                else:
                    p_power_battery = "{0:0.0f}".format(readings['power/battery_power'][0])
                if readings.get('power/battery_charge', None) is None:
                    p_charge_battery = "?"
                else:
                    p_charge_battery = "{0:0.0f}".format(readings['power/battery_charge'][0])
                if readings.get('power/solar_power', None) is None:
                    p_power_solar = "?"
                else:
                    p_power_solar = "{0:0.0f}".format(readings['power/solar_power'][0])
                if readings.get('power/house_power', None) is None:
                    p_power_house = "?"
                else:
                    p_power_house = "{0:0.0f}".format(readings['power/house_power'][0])
                msg = FormatDisplay("B:" + p_power_battery + "W " + p_charge_battery + "% S:" + p_power_solar + "W L:" + p_power_house + "W", config.getint('Adafruit_LCD', 'LCD_WIDTH'), config.getint('Adafruit_LCD', 'LCD_HEIGHT'))
                msg_success = True
            # ----------------
            else:
                AdaScreenNumber = 0
        except Exception:
            log.exception("WriteAdaLcd: Error creating message")
            msg = "Data Error"
    try:
        AdaLcd.clear()
    except Exception:
        log.exception("WriteAdaLcd: Error clearing LCD")
    if config.getboolean('Sensors', 'SI1145'):
        try:
            uv = readings[config.get('Adafruit_LCD', 'UV_CHANNEL')][0]
            if uv < 3.0:
                # Low
                AdaLcd.color = [0, 255, 0]
            elif uv < 6.0:
                # Moderate
                AdaLcd.color = [255,255,64]
            elif uv < 8.0:
                # High
                AdaLcd.color = [255,128,64]
            elif uv < 11.0:
                # Very High
                AdaLcd.color = [255,64,64]
            else:
                # Extreme
                AdaLcd.color = [255,64,255]
        except Exception:
            log.exception("WriteAdaLcd: Error setting backlight")
    try:
        AdaLcd.message = msg
    except Exception:
        log.exception("WriteAdaLcd: Error writing message")


def WriteConsole():
    """Write out readings to the console."""
    log.debug("WriteConsole: start")
    print((time.ctime()), end=' ')
    if config.getboolean('Output', 'BRUTAL_VIEW'):
        for reading in readings:
            value = readings[reading][0]
            try:
                print(("{0}: {1:0.1f}".format(reading, value)), end=' ')
            except Exception:
                print(("{0}: {1}".format(reading, value)), end=' ')
    else:
        try:
            print(("TempIn: {0:0.1f}".format(readings[config.get('PYWWS', 'TEMP_IN_CHANNEL')][0])), end=' ')
        except Exception:
            print(("TempIn: x"), end=' ')
        try:
            print(("TempOut: {0:0.1f}".format(readings[config.get('PYWWS', 'TEMP_OUT_CHANNEL')][0])), end=' ')
        except Exception:
            print(("TempOut: x"), end=' ')
        try:
            print(("HumIn: {0:0.0f}%".format(readings[config.get('PYWWS', 'HUM_IN_CHANNEL')][0])), end=' ')
        except Exception:
            print(("HumIn: x"), end=' ')
        try:
            print(("HumOut: {0:0.0f}%".format(readings[config.get('PYWWS', 'HUM_OUT_CHANNEL')][0])), end=' ')
        except Exception:
            print(("HumOut: x"), end=' ')
        try:
            print(("Press: {0:0.0f}hPa".format(readings[config.get('PYWWS', 'ABS_PRESSURE_CHANNEL')][0])), end=' ')
        except Exception:
            print(("Press: x"), end=' ')
        try:
            print(("Illum: {0:0.1f}".format(readings[config.get('PYWWS', 'ILLUMINANCE_CHANNEL')][0])), end=' ')
        except Exception:
            print(("Illum: x"), end=' ')
        try:
            print(("IRLx: {0:0.1f}".format(readings[config.get('PYWWS', 'IR_CHANNEL')][0])), end=' ')
        except Exception:
            print(("IRLx: x"), end=' ')
        try:
            print(("UV: {0:0.1f}".format(readings[config.get('PYWWS', 'UV_CHANNEL')][0])), end=' ')
        except Exception:
            print(("UV: x"), end=' ')
        try:
            print(("Forecast: %s" % forecast_file_today), end=' ')
        except Exception:
            print(("Forecast: x"), end=' ')
    print()
    log.debug("WriteConsole: Complete")


def WriteSenseHat():
    """Write out status to a Pi Sense Hat."""
    log.debug("WriteSenseHat: start")
    global forecast_toggle
    if config.getint('Rates', 'FORECAST_REFRESH_RATE') > 0 and forecast_toggle == 1 and forecast_file_today:
        forecast_toggle = 0
        msg = forecast_file_today
    else:
        forecast_toggle = 1
        try:
            msg = "Ti:{0:0.1f} To:{1:0.1f} P:{2:0.0f} H:{3:0.0f}%".format(readings[config.get('PYWWS', 'TEMP_IN_CHANNEL')][0], readings[config.get('PYWWS', 'TEMP_OUT_CHANNEL')][0], readings[config.get('PYWWS', 'ABS_PRESSURE_CHANNEL')][0], readings[config.get('PYWWS', 'HUM_IN_CHANNEL')][0])
        except Exception:
            msg = "Awaiting data"
    hour = datetime.now().hour
    if hour > config.getint('General', 'DAWN') and hour < config.getint('General', 'DUSK'):
        PiSenseHat.low_light = False
        Foreground = config.get('SenseHat', 'FG')
        if config.getboolean('SenseHat', 'COLOUR_BG'):
            Background = config.get('SenseHat', 'COLOUR_MID')
            if readings['temp_in'][0] <= config.get('SenseHat', 'COMFORT_LOW'):
                Background = config.get('SenseHat', 'COLOUR_COLD')
            elif readings['temp_in'][0] > config.get('SenseHat', 'COMFORT_HIGH'):
                Background = config.get('SenseHat', 'COLOUR_HOT')
        else:
            Background = config.get('SenseHat', 'BG')
    else:
        PiSenseHat.low_light = True
        Foreground = config.get('SenseHat', 'FG_NIGHT')
        if config.getboolean('SenseHat', 'COLOUR_BG'):
            Background = config.get('SenseHat', 'COLOUR_MID_NIGHT')
            if readings['temp_in'][0] < config.get('SenseHat', 'COMFORT_LOW'):
                Background = config.get('SenseHat', 'COLOUR_COLD_NIGHT')
            if readings['temp_in'][0] > config.get('SenseHat', 'COMFORT_HIGH'):
                Background = config.get('SenseHat', 'COLOUR_HOT_NIGHT')
        else:
            Background = config.get('SenseHat', 'BG_NIGHT')
    PiSenseHat.show_message(msg, scroll_speed=config.get('SenseHat', 'SCROLL'), text_colour=Foreground, back_colour=Background)
    PiSenseHat.clear()
    log.debug("WriteSenseHat: Complete")


########
# CONFIG
########
CONFIG_FILE = 'PiWeather.ini'
ReadConfig()

########
# Optional
########
log.setLevel(config.getint('General', 'LOG_LEVEL'))
BootMessage("PiWeather Starting")
BootMessage("Outputs:")
if config.getboolean('Output', 'ADA_LCD'):
    BootMessage("...Adafruit LCD")
    try:
        import board
        import busio
        import adafruit_character_lcd.character_lcd_rgb_i2c as Adafruit_CharLCD
        i2c = busio.I2C(board.SCL, board.SDA)
        AdaLcd = Adafruit_CharLCD.Character_LCD_RGB_I2C(i2c, config.getint('Adafruit_LCD', 'LCD_WIDTH'), config.getint('Adafruit_LCD', 'LCD_HEIGHT'))
    except Exception as e:
        log.error("Loading Adafruit LCD.", e)
if config.getboolean('Output', 'MQTT_PUBLISH'):
    BootMessage("...MQTT")
    try:
        import paho.mqtt.publish as publish
    except Exception as e:
        log.error("Loading MQTT output.", e)
if config.getboolean('Output', 'PYWWS_PUBLISH'):
    BootMessage("...PyWWS")
    try:
        from pywws import DataStore
    except Exception as e:
        log.error("Loading PyWWS.", e)
if config.getboolean('Sensors', 'SENSEHAT') or config.getboolean('Output', 'SENSEHAT_DISPLAY'):
    BootMessage("...SenseHat")
    try:
        from sense_hat import SenseHat
        PiSenseHat = SenseHat()
    except Exception as e:
        log.error("Loading PyWWS.", e)

BootMessage("Inputs:")
if config.getboolean('Sensors', 'BME280'):
    BootMessage("...BME280")
    try:
        import board
        import busio
        import adafruit_bme280
        i2c = busio.I2C(board.SCL, board.SDA)
        BmeSensor = adafruit_bme280.Adafruit_BME280_I2C(i2c)
    except Exception as e:
        log.error("Loading BME280.", e)
if config.getboolean('Sensors', 'BMP085'):
    BootMessage("...BMP085")
    try:
        import Adafruit_BMP.BMP085
        BmpSensor = Adafruit_BMP.BMP085()
    except Exception as e:
        log.error("Loading BME280.", e)
if config.getboolean('Sensors', 'ENOCEAN'):
    BootMessage("...EnOcean")
    try:
        from enocean.communicators.serialcommunicator import SerialCommunicator as eoSerialCommunicator
        import enocean.protocol.packet
        from enocean.protocol.constants import PACKET as EOPACKET, RORG as EORORG
        import enocean.utils
        from enocean.consolelogger import init_logging
    except Exception as e:
        log.error("Loading EnOcean.", e)
    try:
        import queue
    except ImportError:
        import queue as queue
if config.getboolean('Sensors', 'FORECAST_BOM'):
    BootMessage("...ForecastBoM")
    try:
        import urllib.request, urllib.error, urllib.parse
        import xml.etree.ElementTree as ElementTree
    except Exception as e:
        log.error("Loading ForecastBoM.", e)
if config.getboolean('Sensors', 'HOMIE'):
    BootMessage("...MQTT")
    try:
        import paho.mqtt.client as mqtt
        import re
    except Exception as e:
        log.error("Loading MQTT Input.", e)
if config.getboolean('Sensors', 'SI1145'):
    BootMessage("...SI1145")
    try:
        import SI1145.SI1145 as SI1145
        SiSensor = SI1145.SI1145()
    except Exception as e:
        log.error("Loading MQTT Input.", e)

########
# Main
########
# pywws data
if config.getboolean('Output', 'PYWWS_PUBLISH'):
    ds = DataStore.data_store(config.get('PYWWS', 'STORAGE'))
    dstatus = DataStore.status(config.get('PYWWS', 'STORAGE'))
if config.getboolean('Output', 'SENSEHAT_DISPLAY'):
    # Set up display
    PiSenseHat.clear()
    PiSenseHat.set_rotation(config.get('SenseHat', 'ROTATION'))
if config.getboolean('Sensors', 'ENOCEAN'):
    init_logging(level=config.getint('General', 'LOG_LEVEL'))
    eoCommunicator = eoSerialCommunicator(port=config.get('EnOcean', 'PORT'))
    eoCommunicator.start()
    log.info("EnOceanSensors: Base ID: " + enocean.utils.to_hex_string(eoCommunicator.base_id) + " on port: " + config.get('EnOcean', 'PORT'))
# Warm up sensors
BootMessage("Waiting for sensors to settle")
for j in range(1, 6):
    Sample()
    time.sleep(1)
global_init = False
if config.getboolean('Sensors', 'FORECAST_BOM'):
    try:
        BootMessage("Waiting for BoM")
        ForecastBoM()
    except Exception:
        log.exception("ForecastBoM: Error in initial call")
if config.getboolean('Sensors', 'FORECAST_FILE'):
    try:
        BootMessage("Waiting for File")
        ForecastFile()
    except Exception:
        log.exception("ForecastBoM: Error in initial call")
if config.getboolean('Sensors', 'HOMIE'):
    BootMessage("Waiting for Homie")
    mqttc = mqtt.Client()
    mqttc.on_message = on_mqtt_message
    mqttc.on_connect = on_mqtt_connect
    mqttc.reconnect_delay_set(min_delay=1, max_delay=120)
    mqttc.connect_async(config.get('HOMIE_INPUT', 'HOST'), port=config.getint('HOMIE_INPUT', 'PORT'), keepalive=config.getint('HOMIE_INPUT', 'TIMEOUT'))
BootMessage("Waiting for Samples")
Sample()
BootMessage("Scheduling events...")
scheduler = BackgroundScheduler()
scheduler.add_job(ReadConfig, 'interval', seconds=config.getint('Rates', 'CONFIG_REFRESH_RATE'), id='ReadConfig', max_instances=1, coalesce=True)
scheduler.add_job(Sample, 'interval', seconds=config.getint('Rates', 'SAMPLE_RATE'), id='Sample', max_instances=1, coalesce=True)
if config.getboolean('Sensors', 'ENOCEAN'):
    scheduler.add_job(EnOceanSensors, 'interval', args=[eoCommunicator], seconds=config.getint('Rates', 'ENOCEAN_RATE'), id='EnOcean', max_instances=1, coalesce=True)
if config.getboolean('Sensors', 'FORECAST_BOM'):
    scheduler.add_job(ForecastBoM, 'interval', seconds=config.getint('Rates', 'FORECASTBOM_REFRESH_RATE'), id='ForecastBoM', max_instances=1, coalesce=True)
if config.getboolean('Sensors', 'FORECAST_FILE'):
    scheduler.add_job(ForecastFile, 'interval', seconds=config.getint('Rates', 'FORECASTFILE_REFRESH_RATE'), id='ForecastFile', max_instances=1, coalesce=True)
if config.getboolean('Output', 'ADA_LCD'):
    scheduler.add_job(WriteAdaLcd, 'interval', seconds=config.getint('Rates', 'ADALCD_OUTPUT_RATE'), id='AdaLcd', max_instances=1, coalesce=True)
if config.getboolean('Output', 'CONSOLE_OUTPUT'):
    scheduler.add_job(WriteConsole, 'interval', seconds=config.getint('Rates', 'CONSOLE_OUTPUT_RATE'), id='Console', max_instances=1, coalesce=True)
if config.getboolean('Output', 'MQTT_PUBLISH'):
    scheduler.add_job(MqSendMultiple, 'interval', seconds=config.getint('Rates', 'MQTT_OUTPUT_RATE'), id='MQTT', max_instances=1, coalesce=True)
if config.getboolean('Output', 'PYWWS_PUBLISH'):
    scheduler.add_job(Store, 'interval', seconds=config.getint('Rates', 'STORE_RATE'), id='Store', args=[ds], max_instances=1, coalesce=True)
    scheduler.add_job(Flush, 'interval', seconds=config.getint('Rates', 'FLUSH_RATE'), id='Flush', args=[ds, dstatus], max_instances=1, coalesce=True)
if config.getboolean('Output', 'SENSEHAT_DISPLAY'):
    scheduler.add_job(WriteSenseHat, 'interval', seconds=config.getint('Rates', 'SENSEHAT_OUTPUT_RATE'), id='SenseHat', max_instances=1, coalesce=True)

scheduler.start()
if config.getboolean('Output', 'CONSOLE_OUTPUT'):
    WriteConsole()
if config.getboolean('Output', 'MQTT_PUBLISH'):
    MqSendMultiple()
BootMessage("Entering event loop")

try:
    # This is here to simulate application activity (which keeps the main thread alive).
    while True:
        if config.getboolean('Sensors', 'HOMIE'):
            mqttc.loop_forever()
        else:
            time.sleep(1)
except (KeyboardInterrupt, SystemExit):
    # Not strictly necessary if daemonic mode is enabled but should be done if possible
    BootMessage("Shutting down scheduler")
    scheduler.shutdown()
    if config.getboolean('Output', 'PYWWS_PUBLISH'):
        print("Flushing data")
        ds.flush()
        dstatus.flush()
    if config.getboolean('Output', 'SENSEHAT_DISPLAY'):
        PiSenseHat.clear()
    if config.getboolean('Sensors', 'ENOCEAN') and eoCommunicator.is_alive():
        eoCommunicator.stop()
    BootMessage("Goodbye")
    if config.getboolean('Output', 'ADA_LCD'):
        AdaLcd.color = [0, 0, 0]
    logging.shutdown()
