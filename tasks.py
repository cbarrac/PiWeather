#!/usr/bin/env python
from pywws import DataStore
from pywws import Process
from pywws import Tasks
import os
import sys

try:
	data_dir = sys.argv[1]
except:
	data_dir = "/apps/weather/weather_data/"

# open configuration files
params = DataStore.params(data_dir)
status = DataStore.status(data_dir)
# open data file stores
raw_data = DataStore.data_store(data_dir)
calib_data = DataStore.calib_store(data_dir)
hourly_data = DataStore.hourly_store(data_dir)
daily_data = DataStore.daily_store(data_dir)
monthly_data = DataStore.monthly_store(data_dir)
# Process data
Process.Process(params,raw_data, calib_data, hourly_data, daily_data, monthly_data)
# Do tasks (calculate aggregates, populate templates, draw graphs)
Tasks.RegularTasks(params, status, raw_data, calib_data, hourly_data, daily_data, monthly_data).do_tasks()
