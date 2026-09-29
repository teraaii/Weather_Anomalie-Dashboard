import numpy as np
import openmeteo_requests
import pandas as pd
import requests_cache
from retry_requests import retry


cache_session = requests_cache.CachedSession(".cache", expire_after=3600)
retry_session = retry(cache_session, retries=5, backoff_factor=0.2)
openmeteo = openmeteo_requests.Client(session=retry_session)


def _historical_hourly_reading(latitude, longitude, date, hour):
	params = {
		"latitude": latitude,
		"longitude": longitude,
		"start_date": date.strftime("%Y-%m-%d"),
		"end_date": date.strftime("%Y-%m-%d"),
		"hourly": ["temperature_2m", "wind_speed_10m", "relative_humidity_2m"],
		"daily": ["temperature_2m_max", "temperature_2m_min"],
		"timezone": "auto",
		"temperature_unit": "fahrenheit",
		"wind_speed_unit": "mph",
	}
	response = openmeteo.weather_api(
		"https://historical-forecast-api.open-meteo.com/v1/forecast",
		params=params,
	)[0]
	hourly = response.Hourly()
	timezone = response.Timezone().decode()
	times = pd.date_range(
		start=pd.to_datetime(hourly.Time(), unit="s", utc=True),
		end=pd.to_datetime(hourly.TimeEnd(), unit="s", utc=True),
		freq=pd.Timedelta(seconds=hourly.Interval()),
		inclusive="left",
	).tz_convert(timezone)
	matching_indices = [
		index for index, timestamp in enumerate(times)
		if timestamp.date() == date and timestamp.hour == hour
	]
	if not matching_indices:
		raise ValueError(f"No historical reading found for {date} at {hour:02d}:00 {timezone}")
	index = matching_indices[0]
	temperature = np.asarray(hourly.Variables(0).ValuesAsNumpy())[index]
	wind_speed = np.asarray(hourly.Variables(1).ValuesAsNumpy())[index]
	relative_humidity = np.asarray(hourly.Variables(2).ValuesAsNumpy())[index]
	daily = response.Daily()
	daily_high = np.asarray(daily.Variables(0).ValuesAsNumpy())[0]
	daily_low = np.asarray(daily.Variables(1).ValuesAsNumpy())[0]
	return (
		float(temperature),
		float(wind_speed),
		float(relative_humidity),
		float(daily_low),
		float(daily_high),
		timezone,
	)


def get_hourly_comparison(latitude, longitude, current_datetime):
	"""Compare with historical weather for the same local date and hour last year."""
	current_datetime = pd.Timestamp(current_datetime)
	current_date = current_datetime.date()
	historical_date = (current_datetime - pd.DateOffset(years=1)).date()
	hour = current_datetime.hour
	(
		historical_temperature,
		historical_wind,
		historical_relative_humidity,
		historical_daily_low,
		historical_daily_high,
		timezone,
	) = _historical_hourly_reading(
		latitude,
		longitude,
		historical_date,
		hour,
	)

	return {
		"current_date": current_date,
		"historical_date": historical_date,
		"hour": hour,
		"timezone": timezone,
		"historical_temperature": historical_temperature,
		"historical_wind": historical_wind,
		"historical_relative_humidity": historical_relative_humidity,
		"historical_daily_low": historical_daily_low,
		"historical_daily_high": historical_daily_high,
	}


def get_daily_temperature_range(latitude, longitude):
	params = {
		"latitude": latitude,
		"longitude": longitude,
		"daily": ["temperature_2m_max", "temperature_2m_min"],
		"forecast_days": 1,
		"timezone": "auto",
		"temperature_unit": "fahrenheit",
	}
	response = openmeteo.weather_api(
		"https://api.open-meteo.com/v1/forecast",
		params=params,
	)[0]
	daily = response.Daily()
	high = np.asarray(daily.Variables(0).ValuesAsNumpy())[0]
	low = np.asarray(daily.Variables(1).ValuesAsNumpy())[0]
	return float(low), float(high)