import json
import logging
import os
import urllib.request, urllib.error, urllib.parse
import xml.etree.ElementTree as ElementTree

logging.basicConfig()
log = logging.getLogger("piweather-bom")
log.setLevel(os.getenv("LOG_LEVEL", "ERROR"))

def handle(req):
    """handle a request to the function
    Args:
        req (str): request body
    """
    req=ForecastBoM()
    logging.shutdown()
    return req

def ForecastBoM():
    """Obtain weather predictions from the Bureau of Meteorology."""
    log.debug("ForecastBoM: start")
    forecast_bom_today = ""
    forecast_bom_tomorrow = ""
    forecast_bom_dayafter = ""
    FORECAST_BASE_URL = os.getenv("FORECAST_BASE_URL", "ftp://ftp.bom.gov.au/anon/gen/fwo/")
    log.debug("ForecastBoM: Base URL %s", FORECAST_BASE_URL)
    FORECAST_STATE_ID = os.getenv("FORECAST_STATE_ID", "IDV10753")
    log.debug("ForecastBoM: State %s", FORECAST_STATE_ID)
    FORECAST_AAC = os.getenv("FORECAST_AAC", "VIC_PT042")
    log.debug("ForecastBoM: Area %s", FORECAST_AAC)
    Forecast_URL = FORECAST_BASE_URL + FORECAST_STATE_ID + '.xml'
    log.debug("ForecastBoM: Connecting to %s", Forecast_URL)
    try:
        response = urllib.request.urlopen(Forecast_URL, timeout=180)
        ForecastXML = response.read()
    except Exception:
        log.exception("ForecastBoM: Error downloading forecast file:")
        return ("ForecastBoM: Error downloading forecast file")
    try:
        ForecastTree = ElementTree.fromstring(ForecastXML)
    except Exception:
        log.exception("ForecastBoM: Error parsing forecast file:")
        return ("ForecastBoM: Error parsing forecast file:")
    # Today
    try:
        xmlDay = ForecastTree.find("./forecast/area[@aac='" + FORECAST_AAC + "']/forecast-period[@index='0']")
    except Exception:
        log.exception("ForecastBoM: Error finding area element for today:")
    try:
        max_temp = xmlDay.find("*[@type='air_temperature_maximum']").text
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
    except Exception:
        log.exception("ForecastBoM: Error finding forecast element:")
        rain_chance = "?"
    summary = "Max {0} {1}% {2}".format(max_temp, rain_chance, forecast_text)
    forecast_bom_today = { 'max_temp': max_temp, 'rain_chance': rain_chance, 'forecast_text': forecast_text, 'summary': summary}
    log.info("ForecastBoM: Today: %s", forecast_bom_today)
    # Tomorrow
    try:
        xmlDay = ForecastTree.find("./forecast/area[@aac='" + FORECAST_AAC + "']/forecast-period[@index='1']")
    except Exception:
        log.exception("ForecastBoM: Error finding area element for tomorrow:")
    try:
        min_temp = xmlDay.find("*[@type='air_temperature_minimum']").text
    except Exception:
        min_temp = "?"
    try:
        max_temp = xmlDay.find("*[@type='air_temperature_maximum']").text
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
    except Exception:
        rain_chance = "?"
    summary = "{0}-{1} {2}% {3}".format(min_temp, max_temp, rain_chance, forecast_text)
    forecast_bom_tomorrow = { 'min_temp': min_temp, 'max_temp': max_temp, 'rain_chance': rain_chance, 'forecast_text': forecast_text, 'summary': summary}
    log.info("ForecastBoM: Tomorrow: %s", forecast_bom_tomorrow)
    # Day after tomorrow
    try:
        xmlDay = ForecastTree.find("./forecast/area[@aac='" + FORECAST_AAC + "']/forecast-period[@index='2']")
    except Exception:
        log.exception("ForecastBoM: Error finding area element for day after tomorrow:")
    try:
        min_temp = xmlDay.find("*[@type='air_temperature_minimum']").text
    except Exception:
        min_temp = "?"
    try:
        max_temp = xmlDay.find("*[@type='air_temperature_maximum']").text
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
    except Exception:
        rain_chance = "?"
    summary = "{0}-{1} {2}% {3}".format(min_temp, max_temp, rain_chance, forecast_text)
    forecast_bom_dayafter = { 'min_temp': min_temp, 'max_temp': max_temp, 'rain_chance': rain_chance, 'forecast_text': forecast_text, 'summary': summary}
    log.info("ForecastBoM: Day After Tomorrow: %s", forecast_bom_dayafter)
    forecast_json = {
        'today': forecast_bom_today,
        'tomorrow': forecast_bom_tomorrow,
        'dayafter': forecast_bom_dayafter
    }
    return (json.dumps(forecast_json))