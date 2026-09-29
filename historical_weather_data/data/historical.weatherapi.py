import openmeteo_requests

import numpy as np
import pandas as pd
import requests_cache
from retry_requests import retry

# Setup the Open-Meteo API client with cache and retry on error
cache_session = requests_cache.CachedSession('.cache', expire_after = 3600)
retry_session = retry(cache_session, retries = 5, backoff_factor = 0.2)
openmeteo = openmeteo_requests.Client(session = retry_session)


def values_as_numpy(variable):
	"""Return a weather variable's values as a NumPy array.

	Support both PascalCase and snake_case Open-Meteo SDK method names.
	"""
	for name in ("ValuesAsNumpy", "values_as_numpy", "Values", "values"):
		method = getattr(variable, name, None)
		if callable(method):
			return np.asarray(method())
	raise TypeError("Weather variable has no callable values method")

def get_daily_reading(url, date, base_params):
	params = {
		**base_params,
		"start_date": date.strftime("%Y-%m-%d"),
		"end_date": date.strftime("%Y-%m-%d"),
	}
	response = openmeteo.weather_api(url, params=params)[0]
	daily = response.Daily()
	temperature = values_as_numpy(daily.Variables(0))[0]
	wind_speed = values_as_numpy(daily.Variables(1))[0]
	return temperature, wind_speed


base_params = {
	"latitude": 39.1493,
	"longitude": -76.7752,
	"daily": ["temperature_2m_mean", "wind_speed_10m_mean"],
	"models": "ncep_hrrr_conus",
	"timezone": "auto",
	"temperature_unit": "fahrenheit",
	"wind_speed_unit": "mph",
}
current_date = pd.Timestamp.now(tz="America/New_York").normalize() - pd.Timedelta(days=1)
historical_date = current_date - pd.DateOffset(years=1)

current_temperature, current_wind = get_daily_reading(
	"https://api.open-meteo.com/v1/forecast",
	current_date,
	base_params,
)
historical_temperature, historical_wind = get_daily_reading(
	"https://historical-forecast-api.open-meteo.com/v1/forecast",
	historical_date,
	base_params,
)

print("CURRENT WEATHER")
print(current_date.strftime("%B %d, %Y"))
print(f"\nTemperature: {current_temperature:.0f}°F")
print(f"Wind: {current_wind:.0f} mph")

print(f"\n\n{historical_date.year} HISTORICAL COMPARISON")
print(historical_date.strftime("%B %d, %Y"))
print(f"\nTemperature: {historical_temperature:.0f}°F")
print(f"Wind: {historical_wind:.0f} mph")

print("\n\nANOMALY")
print(f"Temperature: {current_temperature - historical_temperature:+.0f}°F")
print(f"Wind: {current_wind - historical_wind:+.0f} mph")

