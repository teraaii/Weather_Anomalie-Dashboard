import datetime as datetime_
import html
import json
import math
import sys
from pathlib import Path
import requests
from PyQt5.QtWidgets import (QApplication, QLabel, QVBoxLayout, QWidget,
                             QLineEdit, QPushButton, QFrame, QListWidget,
                             QListWidgetItem, QScrollArea, QSpacerItem,
                             QSizePolicy, QTabWidget)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QUrl
from PyQt5.QtGui import (
    QColor,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPen,
    QMovie,
)
from PyQt5.QtWebEngineWidgets import QWebEngineView

from historical_weather_comparison import (
    get_daily_temperature_range,
    get_hourly_comparison,
)


def dew_point_fahrenheit(temperature_fahrenheit, relative_humidity):
    if relative_humidity <= 0:
        return None

    temperature_celsius = (temperature_fahrenheit - 32) * 5 / 9
    gamma = math.log(relative_humidity / 100) + (
        17.625 * temperature_celsius / (243.04 + temperature_celsius)
    )
    dew_point_celsius = 243.04 * gamma / (17.625 - gamma)
    return dew_point_celsius * 9 / 5 + 32


def get_weather_map_data(latitude, longitude, current_conditions):
    is_conus = 24.0 <= latitude <= 50.0 and -126.0 <= longitude <= -66.0
    models = (
        ["ncep_hrrr_conus", "ncep_nam_conus", "ncep_gfs_global"]
        if is_conus
        else ["ncep_gfs_global"]
    )
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "models": ",".join(models),
        "current": (
            "rain,showers,precipitation,weather_code,wind_speed_10m,is_day,"
            "relative_humidity_2m,temperature_2m"
        ),
        "daily": [
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
            "weather_code",
        ],
        "timezone": "auto",
        "forecast_days": 7,
        "wind_speed_unit": "mph",
        "temperature_unit": "fahrenheit",
        "precipitation_unit": "inch",
    }
    response = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params=params,
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    current = payload.get("current") or {}
    daily = payload.get("daily") or {}

    def current_value(field, fallback):
        value = current.get(field)
        return fallback if value is None else value

    daily_forecast = []
    for index, forecast_date in enumerate(daily.get("time", [])):
        selected = None
        for model in models:
            def daily_value(variable):
                for key in (f"{variable}_{model}", variable):
                    values = daily.get(key)
                    if values is not None and index < len(values):
                        return values[index]
                return None

            high = daily_value("temperature_2m_max")
            low = daily_value("temperature_2m_min")
            if high is not None or low is not None:
                selected = {
                    "date": forecast_date,
                    "high": high,
                    "low": low,
                    "precipitation": daily_value("precipitation_sum"),
                    "weather_code": daily_value("weather_code"),
                    "model": model.replace("ncep_", "").replace("_conus", "").replace("_global", "").upper(),
                }
                break
        if selected is not None:
            daily_forecast.append(selected)

    try:
        radar_response = requests.get(
            "https://api.rainviewer.com/public/weather-maps.json",
            timeout=10,
        )
        radar_response.raise_for_status()
        radar_metadata = radar_response.json()
        radar = radar_metadata.get("radar", {})
        radar_frames = radar.get("past", []) + radar.get("nowcast", [])
        radar_data = {
            "host": radar_metadata.get("host", "https://tilecache.rainviewer.com"),
            "frames": radar_frames,
        }
    except requests.RequestException:
        radar_data = {"host": "https://tilecache.rainviewer.com", "frames": []}

    return {
        "latitude": payload.get("latitude", latitude),
        "longitude": payload.get("longitude", longitude),
        "timezone": payload.get("timezone", "Local time"),
        "models": models,
        "current": {
            "temperature": current_value(
                "temperature_2m", current_conditions["temperature"]
            ),
            "humidity": current_value(
                "relative_humidity_2m", current_conditions["humidity"]
            ),
            "wind_speed": current_value(
                "wind_speed_10m", current_conditions["wind_speed"]
            ),
            "precipitation": current.get("precipitation"),
            "rain": current.get("rain"),
            "showers": current.get("showers"),
            "weather_code": current.get("weather_code"),
            "description": current_conditions["description"],
        },
        "daily": daily_forecast,
        "radar": radar_data,
    }


class OutlinedLabel(QLabel):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.text_color = QColor("#18342d")
        self.outline_color = None

    def set_outline_colors(self, text_color, outline_color=None):
        self.text_color = QColor(text_color)
        self.outline_color = QColor(outline_color) if outline_color else None
        self.update()

    def paintEvent(self, event):
        if self.outline_color is None or not self.text():
            super().paintEvent(event)
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        font = self.font()
        painter.setFont(font)
        metrics = QFontMetricsF(font)
        content_rect = self.contentsRect()
        text_width = metrics.horizontalAdvance(self.text())
        alignment = self.alignment()
        if alignment & Qt.AlignRight:
            x_position = content_rect.right() - text_width + 1
        elif alignment & Qt.AlignHCenter:
            x_position = content_rect.left() + (content_rect.width() - text_width) / 2
        else:
            x_position = content_rect.left()
        baseline = (
            content_rect.top()
            + (content_rect.height() - metrics.height()) / 2
            + metrics.ascent()
        )

        text_path = QPainterPath()
        text_path.addText(x_position, baseline, font, self.text())
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(self.outline_color, 1.0))
        painter.drawPath(text_path)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.text_color)
        painter.drawPath(text_path)


class WeatherWorker(QThread):
    succeeded = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, city, api_key):
        super().__init__()
        self.city = city
        self.api_key = api_key

    def run(self):
        try:
            url = f"https://api.openweathermap.org/data/2.5/weather?q={self.city}&appid={self.api_key}"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            temperature = (data["main"]["temp"] - 273.15) * 9 / 5 + 32
            wind_speed = data["wind"]["speed"] * 2.237
            humidity = data["main"]["humidity"]
            description = data["weather"][0]["description"].capitalize()
            weather_id = data["weather"][0]["id"]
            latitude = data["coord"]["lat"]
            longitude = data["coord"]["lon"]

            local_datetime = datetime_.datetime.fromtimestamp(
                data["dt"], datetime_.timezone.utc
            ) + datetime_.timedelta(seconds=data["timezone"])
            is_daytime = data["sys"]["sunrise"] <= data["dt"] < data["sys"]["sunset"]
            comparison = get_hourly_comparison(
                latitude,
                longitude,
                local_datetime,
            )
            try:
                daily_low, daily_high = get_daily_temperature_range(
                    latitude, longitude
                )
            except Exception:
                daily_low = daily_high = None
            try:
                map_data = get_weather_map_data(
                    latitude,
                    longitude,
                    {
                        "temperature": temperature,
                        "humidity": humidity,
                        "wind_speed": wind_speed,
                        "description": description,
                    },
                )
            except Exception:
                map_data = {
                    "latitude": latitude,
                    "longitude": longitude,
                    "timezone": "Local time",
                    "models": [],
                    "current": {
                        "temperature": temperature,
                        "humidity": humidity,
                        "wind_speed": wind_speed,
                        "precipitation": None,
                        "rain": None,
                        "showers": None,
                        "weather_code": None,
                        "description": description,
                    },
                    "daily": [],
                    "error": "Forecast map data is temporarily unavailable.",
                }

            self.succeeded.emit({
                "city": self.city,
                "temperature": temperature,
                "daily_low": daily_low,
                "daily_high": daily_high,
                "wind_speed": wind_speed,
                "humidity": humidity,
                "description": description,
                "weather_id": weather_id,
                "local_datetime": local_datetime,
                "timezone_offset": data["timezone"],
                "is_daytime": is_daytime,
                "comparison": comparison,
                "map_data": map_data,
            })
        except requests.HTTPError as error:
            status_code = error.response.status_code if error.response else None
            self.failed.emit(f"HTTP {status_code}" if status_code else str(error))
        except Exception as error:
            self.failed.emit(str(error))


class DeviationChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.temperature_deviation = None
        self.humidity_deviation = None
        self.foreground_color = QColor("#18342d")
        self.secondary_color = QColor("#52675f")
        self.setObjectName("deviation_chart")
        self.setMinimumHeight(132)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_theme_colors(self, foreground, secondary):
        self.foreground_color = QColor(foreground)
        self.secondary_color = QColor(secondary)
        self.update()

    def set_deviations(self, temperature, humidity):
        self.temperature_deviation = temperature
        self.humidity_deviation = humidity
        self.update()

    def clear(self):
        self.temperature_deviation = None
        self.humidity_deviation = None
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.temperature_deviation is None or self.humidity_deviation is None:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setFont(self.font())
        painter.setPen(self.foreground_color)
        painter.drawText(14, 20, "DEVIATION FROM SAME HOUR LAST YEAR")

        plot_left = 142
        plot_right = max(plot_left + 120, self.width() - 100)
        center_x = (plot_left + plot_right) / 2
        half_width = (plot_right - plot_left) / 2 - 5
        rows = (
            (55, "Temperature", self.temperature_deviation, 5, "°F"),
            (99, "Humidity", self.humidity_deviation, 10, " pp"),
        )

        for center_y, label, value, scale_step, unit in rows:
            painter.setPen(self.foreground_color)
            painter.drawText(14, center_y + 4, label)

            track = QColor(self.secondary_color)
            track.setAlpha(90)
            painter.setPen(Qt.NoPen)
            painter.setBrush(track)
            painter.drawRoundedRect(
                int(plot_left), center_y - 6, int(plot_right - plot_left), 12, 4, 4
            )

            painter.setPen(self.secondary_color)
            painter.drawLine(int(center_x), center_y - 10, int(center_x), center_y + 10)

            scale = max(scale_step, math.ceil(abs(value) / scale_step) * scale_step)
            bar_width = min(abs(value) / scale, 1.0) * half_width
            if value != 0:
                bar_color = QColor("#c62828" if value > 0 else "#2e7d32")
                painter.setBrush(bar_color)
                painter.drawRoundedRect(
                    int(center_x if value > 0 else center_x - bar_width),
                    center_y - 5,
                    max(2, int(bar_width)),
                    10,
                    3,
                    3,
                )

            painter.setPen(self.foreground_color)
            value_text = f"{value:+.1f}{unit}"
            painter.drawText(plot_right + 10, center_y + 4, value_text)


class WeatherDashboard(QWidget):
    def __init__(self):
        super().__init__()
        self.clock_label = OutlinedLabel(parent=self)
        self.result_city_label = OutlinedLabel("", self)
        self.city_label = OutlinedLabel("Enter City Name: ", self)
        self.city_input = QLineEdit(self)
        self.get_weather_button = QPushButton("Get Weather", self)
        self.temperature_label = OutlinedLabel("Temperature: ", self)
        self.emoji_label = QLabel("", self)
        self.description_label = QLabel("Description: ", self)
        self.conditions_label = QLabel("", self)
        self.comparison_label = QLabel("", self)
        self.anomaly_label = QLabel("", self)
        self.deviation_chart = DeviationChart(self)
        self.footer_label = QLabel("All Weather Starts Here", self)
        self.footer_name_label = QLabel("By Tayler B. Hillian", self)
        self.location_timezone_offset = None
        self.has_weather_result = False
        self.is_daytime = True
        self.is_raining = False
        self.landing_background = QMovie(
            str(Path(__file__).with_name("landingpage.gif"))
        )
        self.landing_background.setCacheMode(QMovie.CacheAll)
        self.landing_background.frameChanged.connect(self.update)
        self.condition_backgrounds = {}
        conditions_gif_dir = Path(__file__).parent / "conditions_gifs"
        for gif_path in sorted(conditions_gif_dir.glob("*.gif")):
            movie = QMovie(str(gif_path))
            movie.setCacheMode(QMovie.CacheAll)
            movie.frameChanged.connect(self.update)
            self.condition_backgrounds[gif_path.name] = movie
        self.active_background = None
        self.background_overlay = QColor(8, 16, 34, 0)
        self.init_ui()

    def init_ui(self):
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setWindowTitle("Weather Dashboard")
        self.setObjectName("WeatherDashboard")
        self.setFixedSize(780, 820)
        content_widget = QWidget(self)
        content_widget.setObjectName("WeatherContent")
        content_widget.setAttribute(Qt.WA_TranslucentBackground)
        content_widget.setAutoFillBackground(False)
        self.content_layout = QVBoxLayout(content_widget)
        content_layout = self.content_layout
        content_layout.addWidget(self.clock_label)
        content_layout.addWidget(self.result_city_label)
        self.landing_search_spacer = QSpacerItem(
            0, 195, QSizePolicy.Minimum, QSizePolicy.Fixed
        )
        content_layout.addItem(self.landing_search_spacer)
        content_layout.addWidget(self.city_label)
        content_layout.addWidget(self.city_input)
        content_layout.addWidget(self.get_weather_button, alignment=Qt.AlignCenter)
        content_layout.addWidget(self.temperature_label)
        content_layout.addWidget(self.emoji_label)
        content_layout.addWidget(self.description_label)
        content_layout.addWidget(self.conditions_label)
        content_layout.addWidget(self.comparison_label)
        content_layout.addWidget(self.anomaly_label)
        content_layout.addWidget(self.deviation_chart)
        self.bottom_page_spacer = QSpacerItem(
            0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding
        )
        content_layout.addItem(self.bottom_page_spacer)
        content_layout.addWidget(self.footer_label)
        content_layout.addWidget(self.footer_name_label)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setObjectName("WeatherScrollArea")
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea QWidget#WeatherContent { background: transparent; }"
        )
        self.scroll_area.viewport().setAttribute(Qt.WA_TranslucentBackground)
        self.scroll_area.viewport().setAutoFillBackground(False)
        self.scroll_area.setWidget(content_widget)

        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("WeatherTabs")
        self.weather_tab = QWidget(self.tabs)
        weather_tab_layout = QVBoxLayout(self.weather_tab)
        weather_tab_layout.setContentsMargins(0, 0, 0, 0)
        weather_tab_layout.addWidget(self.scroll_area)
        self.tabs.addTab(self.weather_tab, "Weather")

        self.map_tab = QWidget(self.tabs)
        map_tab_layout = QVBoxLayout(self.map_tab)
        map_tab_layout.setContentsMargins(0, 0, 0, 0)
        self.weather_map_view = QWebEngineView(self.map_tab)
        self.weather_map_view.setHtml(
            """<!doctype html><html><head><meta charset="utf-8">
            <style>
                html, body { height: 100%; margin: 0; }
                body { display: grid; place-items: center; background: #edf3ef;
                       color: #52675f; font: 16px Arial, sans-serif; }
                p { padding: 24px; text-align: center; }
            </style></head><body><p>Search a city on the Weather tab to load its map.</p>
            </body></html>"""
        )
        map_tab_layout.addWidget(self.weather_map_view)
        self.tabs.addTab(self.map_tab, "Weather Map")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tabs)

        self.setStyleSheet(self.styleSheet() + """
            QTabWidget#WeatherTabs::pane {
                border: none;
                background: transparent;
            }
            QTabWidget#WeatherTabs QTabBar::tab {
                padding: 8px 16px;
                color: #52675f;
                background: #f7faf4;
            }
            QTabWidget#WeatherTabs QTabBar::tab:selected {
                color: white;
                background: #27685f;
            }
        """)

        # Hide weather results until a valid city is searched
        self.result_city_label.setVisible(False)
        self.temperature_label.setVisible(False)
        self.conditions_label.setVisible(False)
        self.description_label.setVisible(False)
        self.comparison_label.setVisible(False)
        self.anomaly_label.setVisible(False)
        self.deviation_chart.setVisible(False)

        self.city_label.setAlignment(Qt.AlignCenter)
        self.footer_label.setAlignment(Qt.AlignCenter)
        self.footer_name_label.setAlignment(Qt.AlignCenter)
        self.result_city_label.setAlignment(Qt.AlignCenter)
        self.clock_label.setAlignment(Qt.AlignCenter)
        self.description_label.setWordWrap(True)
        self.city_input.setAlignment(Qt.AlignCenter)
        self.temperature_label.setAlignment(Qt.AlignCenter)
        self.emoji_label.setAlignment(Qt.AlignCenter)
        self.description_label.setAlignment(Qt.AlignCenter)
        self.conditions_label.setAlignment(Qt.AlignCenter)
        self.comparison_label.setAlignment(Qt.AlignCenter)
        self.anomaly_label.setAlignment(Qt.AlignCenter)
        self.conditions_label.setWordWrap(True)
        self.comparison_label.setWordWrap(True)
        self.anomaly_label.setWordWrap(True)

        self.city_label.setObjectName("city_label")
        self.footer_label.setObjectName("footer_label")
        self.footer_name_label.setObjectName("footer_name_label")
        self.result_city_label.setObjectName("result_city_label")
        self.clock_label.setObjectName("clock_label")
        self.city_input.setObjectName("city_input")
        self.get_weather_button.setObjectName("get_weather_button")
        self.temperature_label.setObjectName("temperature_label")
        self.emoji_label.setObjectName("emoji_label")
        self.description_label.setObjectName("description_label")
        self.conditions_label.setObjectName("conditions_label")
        self.comparison_label.setObjectName("comparison_label")
        self.anomaly_label.setObjectName("anomaly_label")
        
        self.apply_theme(is_daytime=True)
        
        self.get_weather_button.clicked.connect(self.get_weather)
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self.update_clock)
        self.clock_timer.start(1000)
        self.update_clock()

    def update_clock(self):
        if self.location_timezone_offset is None:
            current_time = datetime_.datetime.now()
        else:
            current_time = datetime_.datetime.now(datetime_.timezone.utc) + datetime_.timedelta(
                seconds=self.location_timezone_offset
            )
        self.clock_label.setText(current_time.strftime("%A, %B %d | %I:%M:%S %p"))

    def paintEvent(self, event):
        super().paintEvent(event)
        background_movie = self.active_background
        if background_movie is None or not background_movie.isValid():
            return

        current_frame = background_movie.currentPixmap()
        if current_frame.isNull():
            return

        scaled_background = current_frame.scaled(
            self.size(),
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )
        offset_x = (self.width() - scaled_background.width()) // 2
        offset_y = (self.height() - scaled_background.height()) // 2
        painter = QPainter(self)
        painter.drawPixmap(offset_x, offset_y, scaled_background)
        painter.fillRect(self.rect(), self.background_overlay)

    def update_weather_map(self, map_data):
        map_json = json.dumps(map_data, ensure_ascii=False).replace("</", "<\\/")
        map_html = """<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
html, body, #map { height: 100%; width: 100%; margin: 0; }
body { font: 13px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
#panel { position: absolute; z-index: 500; top: 12px; left: 58px; width: 300px;
    max-height: calc(100% - 36px); overflow: auto; padding: 14px;
    border-radius: 8px; background: rgba(255,255,255,.95); color: #18342d;
    box-shadow: 0 2px 12px rgba(20,45,40,.18); }
#place { margin: 0 0 4px; font-size: 20px; }
#current { color: #52675f; line-height: 1.5; }
#warning { color: #8a5a00; }
#radar-controls { display: flex; align-items: center; gap: 8px; margin-top: 10px; }
#radar-slider { flex: 1; min-width: 0; accent-color: #218581; }
#radar-time { color: #52675f; font-size: 11px; white-space: nowrap; }
#radar-play { border: 0; border-radius: 4px; padding: 6px 10px;
    background: #27685f; color: white; cursor: pointer; }
#forecast { display: grid; gap: 7px; margin-top: 12px; }
.day { display: grid; grid-template-columns: 62px 1fr; gap: 3px 8px;
    padding: 8px; background: #f1f6f2; border-radius: 5px; }
.day strong { grid-row: span 2; align-self: center; }
.model { color: #687d75; font-size: 11px; }
@media (max-width: 560px) {
    #panel { left: 52px; right: 8px; width: auto; }
}
</style></head><body><div id="map"></div>
<section id="panel"><h1 id="place"></h1><div id="current"></div>
<div id="radar-controls" hidden>
    <button id="radar-play" type="button">Play radar</button>
    <input id="radar-slider" type="range" min="0" max="0" value="0" aria-label="Radar time">
    <time id="radar-time"></time>
</div>
<div id="warning"></div><div id="forecast"></div></section>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const data = __MAP_DATA__;
const current = data.current || {};
const map = L.map("map").setView([data.latitude, data.longitude], 9);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution: "&copy; OpenStreetMap contributors"
}).addTo(map);
document.getElementById("place").textContent = data.location_name + " forecast";
const precipitation = Number(current.precipitation || current.rain || current.showers || 0);
const marker = L.circleMarker([data.latitude, data.longitude], {
    radius: 12, color: precipitation > 0 ? "#168bc4" : "#218581",
    weight: 2, fillColor: precipitation > 0 ? "#43b5e5" : "#63b7a2", fillOpacity: .8
}).addTo(map);
const popup = document.createElement("div");
const popupTitle = document.createElement("strong");
popupTitle.textContent = data.location_name;
popup.appendChild(popupTitle);
const popupDetails = document.createElement("div");
popupDetails.textContent = `${current.temperature}°F · RH ${current.humidity}% · Wind ${current.wind_speed} mph`;
popup.appendChild(popupDetails);
marker.bindPopup(popup);
document.getElementById("current").textContent =
    `${current.description} · ${current.temperature}°F · RH ${current.humidity}% · ` +
    `Wind ${current.wind_speed} mph` +
    (current.precipitation == null ? "" : ` · Precip ${current.precipitation.toFixed(2)} in`);
document.getElementById("warning").textContent = data.error || "";
const radar = data.radar || {};
const radarFrames = radar.frames || [];
const radarControls = document.getElementById("radar-controls");
if (radar.host && radarFrames.length) {
    const radarSlider = document.getElementById("radar-slider");
    const radarTime = document.getElementById("radar-time");
    const radarPlay = document.getElementById("radar-play");
    radarControls.hidden = false;
    radarSlider.max = String(radarFrames.length - 1);
    let radarIndex = radarFrames.length - 1;
    let radarTimer = null;
    const radarTileUrl = frame =>
        `${radar.host}${frame.path}/256/{z}/{x}/{y}/2/1_1.png`;
    const radarLayer = L.tileLayer(radarTileUrl(radarFrames[radarIndex]), {
        opacity: 0.68,
        maxNativeZoom: 7,
        maxZoom: 18,
        attribution: "Radar &copy; RainViewer"
    }).addTo(map);
    const showRadarFrame = index => {
        radarIndex = Math.max(0, Math.min(radarFrames.length - 1, index));
        const frame = radarFrames[radarIndex];
        radarLayer.setUrl(radarTileUrl(frame));
        radarSlider.value = String(radarIndex);
        radarTime.textContent = new Date(frame.time * 1000).toLocaleTimeString([], {
            hour: "2-digit", minute: "2-digit"
        });
    };
    radarSlider.addEventListener("input", () => showRadarFrame(Number(radarSlider.value)));
    radarPlay.addEventListener("click", () => {
        if (radarTimer) {
            clearInterval(radarTimer);
            radarTimer = null;
            radarPlay.textContent = "Play radar";
            return;
        }
        radarPlay.textContent = "Pause radar";
        radarTimer = setInterval(() => {
            showRadarFrame((radarIndex + 1) % radarFrames.length);
        }, 700);
    });
    showRadarFrame(radarIndex);
} else {
    radarControls.hidden = true;
    const radarNotice = document.createElement("div");
    radarNotice.className = "model";
    radarNotice.textContent = "Live radar frames are currently unavailable.";
    document.getElementById("panel").insertBefore(radarNotice, document.getElementById("forecast"));
}
const weatherNames = {0:"Clear",1:"Mostly clear",2:"Partly cloudy",3:"Overcast",
    45:"Fog",48:"Rime fog",51:"Light drizzle",53:"Drizzle",55:"Heavy drizzle",
    61:"Light rain",63:"Rain",65:"Heavy rain",71:"Light snow",73:"Snow",
    75:"Heavy snow",80:"Rain showers",81:"Showers",82:"Heavy showers",
    95:"Thunderstorm",96:"Thunderstorm with hail",99:"Thunderstorm with hail"};
const forecast = document.getElementById("forecast");
for (const day of (data.daily || [])) {
    const card = document.createElement("div");
    card.className = "day";
    const date = document.createElement("strong");
    date.textContent = day.date.slice(5);
    const summary = document.createElement("span");
    summary.textContent = `${weatherNames[day.weather_code] || "Forecast"} · ` +
        `High ${day.high == null ? "--" : day.high}°F / ` +
        `Low ${day.low == null ? "--" : day.low}°F · ` +
        `${day.precipitation == null ? "--" : day.precipitation.toFixed(2)} in`;
    const model = document.createElement("span");
    model.className = "model";
    model.textContent = day.model + " model";
    card.append(date, summary, model);
    forecast.appendChild(card);
}
if (!forecast.children.length && !data.error) {
    document.getElementById("warning").textContent = "Daily model forecast unavailable.";
}
</script></body></html>""".replace("__MAP_DATA__", map_json)
        self.weather_map_view.setHtml(
            map_html,
            QUrl("https://unpkg.com/leaflet@1.9.4/"),
        )
        
    def get_weather(self):
        if self.has_weather_result:
            self.return_to_search()
            return

        api_key = "your_key_here"
        city = self.city_input.text().strip()

        if not city:
            self.display_error("Please enter a city name.")
            return

        for label in (
            self.temperature_label,
            self.emoji_label,
            self.conditions_label,
            self.comparison_label,
            self.anomaly_label,
            self.deviation_chart,
        ):
            label.setVisible(False)
        self.description_label.setText("Loading current weather and comparison...")
        self.description_label.setVisible(True)
        self.get_weather_button.setEnabled(False)
        self.get_weather_button.setText("Loading...")

        self.worker = WeatherWorker(city, api_key)
        self.worker.succeeded.connect(self.display_weather_result)
        self.worker.failed.connect(self.display_error)
        self.worker.finished.connect(self.finish_weather_request)
        self.worker.start()

    def finish_weather_request(self):
        self.get_weather_button.setEnabled(True)
        self.get_weather_button.setText(
            "Get More Weather" if self.has_weather_result else "Get Weather"
        )

    def display_weather_result(self, result):
        self.has_weather_result = True
        self.landing_search_spacer.changeSize(
            0, 0, QSizePolicy.Minimum, QSizePolicy.Fixed
        )
        self.bottom_page_spacer.changeSize(
            0, 0, QSizePolicy.Minimum, QSizePolicy.Fixed
        )
        self.content_layout.invalidate()
        self.result_city_label.setText(result["city"])
        self.result_city_label.setVisible(True)
        self.footer_label.setVisible(False)
        self.city_label.setVisible(False)
        self.city_input.setVisible(False)
        self.get_weather_button.setText("Get More Weather")
        self.location_timezone_offset = result["timezone_offset"]
        self.update_clock()
        self.apply_theme(result["is_daytime"], result["weather_id"])
        self.update_weather_map(result["map_data"])
        current_dew_point = dew_point_fahrenheit(
            result["temperature"], result["humidity"]
        )
        self.display_weather(
            result["temperature"],
            result["description"],
            result["wind_speed"],
            result["humidity"],
            current_dew_point,
            result["daily_low"],
            result["daily_high"],
            self.get_weather_emoji(result["weather_id"], result["is_daytime"]),
            result["local_datetime"].strftime("%B %d, %Y at %I:%M %p"),
        )

        comparison = result["comparison"]
        historical_dew_point = dew_point_fahrenheit(
            comparison["historical_temperature"],
            comparison["historical_relative_humidity"],
        )
        historical_dew_point_text = (
            f"{historical_dew_point:.1f}°F" if historical_dew_point is not None else "N/A"
        )
        self.comparison_label.setText(
            "HISTORICAL WEATHER\n"
            f"{comparison['historical_date']:%B %d, %Y} at "
            f"{comparison['hour']:02d}:00 ({comparison['timezone']})\n"
            f"Temperature: {comparison['historical_temperature']:.0f}°F  |  "
            f"Wind: {comparison['historical_wind']:.0f} mph\n"
            f"RH: {comparison['historical_relative_humidity']:.0f}%  |  "
            f"Dew point: {historical_dew_point_text}\n"
            f"Daily low: {comparison['historical_daily_low']:.1f}°F  |  "
            f"Daily high: {comparison['historical_daily_high']:.1f}°F"
        )
        self.comparison_label.setVisible(True)
        temperature_deviation = (
            result["temperature"] - comparison["historical_temperature"]
        )
        wind_deviation = result["wind_speed"] - comparison["historical_wind"]
        humidity_deviation = (
            result["humidity"] - comparison["historical_relative_humidity"]
        )

        def deviation_color(value):
            if value > 0:
                return "#c62828"
            if value < 0:
                return "#2e7d32"
            return "#555555"

        temperature_color = deviation_color(temperature_deviation)
        wind_color = deviation_color(wind_deviation)
        humidity_color = deviation_color(humidity_deviation)
        self.anomaly_label.setText(
            "HOURLY DEVIATION (vs same local hour last year)<br>"
            f"Temperature: <span style='color: {temperature_color}; font-weight: 600'>"
            f"{temperature_deviation:+.0f}°F</span><br>"
            f"Wind: <span style='color: {wind_color}; font-weight: 600'>"
            f"{wind_deviation:+.0f} mph</span><br>"
            f"Humidity: <span style='color: {humidity_color}; font-weight: 600'>"
            f"{humidity_deviation:+.0f} pp</span>"
        )
        self.anomaly_label.setTextFormat(Qt.RichText)
        self.anomaly_label.setVisible(True)
        self.deviation_chart.set_deviations(
            temperature_deviation,
            humidity_deviation,
        )
        self.deviation_chart.setVisible(True)

    def return_to_search(self):
        self.has_weather_result = False
        self.landing_search_spacer.changeSize(
            0, 195, QSizePolicy.Minimum, QSizePolicy.Fixed
        )
        self.bottom_page_spacer.changeSize(
            0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding
        )
        self.content_layout.invalidate()
        self.location_timezone_offset = None
        self.update_clock()
        self.apply_theme(is_daytime=True)
        self.result_city_label.clear()
        self.result_city_label.setVisible(False)
        self.footer_label.setVisible(True)
        self.city_label.setVisible(True)
        self.city_input.clear()
        self.city_input.setVisible(True)
        self.deviation_chart.clear()
        for label in (
            self.temperature_label,
            self.emoji_label,
            self.description_label,
            self.conditions_label,
            self.comparison_label,
            self.anomaly_label,
        ):
            label.clear()
            label.setVisible(False)
        self.deviation_chart.setVisible(False)
        self.get_weather_button.setText("Get Weather")
        self.city_input.setFocus()

    def apply_theme(self, is_daytime, weather_id=None):
        self.is_daytime = is_daytime
        if not self.has_weather_result and weather_id is None:
            background_name = "landingpage.gif"
        elif weather_id is not None and 200 <= weather_id < 233:
            background_name = (
                "thunderstorm.gif" if is_daytime else "night_thunderstorm.gif"
            )
        elif weather_id is not None and (
            300 <= weather_id < 322 or 500 <= weather_id < 532
        ):
            background_name = "(Both)animated-looping-rain.gif"
        elif weather_id == 800:
            background_name = "sunny.gif" if is_daytime else "night_clearsky.gif"
            if is_daytime and not self.condition_backgrounds[background_name].isValid():
                background_name = "clearsky.gif"
        elif weather_id == 801:
            background_name = "partlysunny.gif" if is_daytime else "night_partlycloudy.gif"
        elif weather_id in (802, 803):
            background_name = "partlycloudy.gif" if is_daytime else "night_partlycloudy.gif"
        elif weather_id == 804:
            background_name = "partlycloudy.gif" if is_daytime else "night_overcast.gif"
        elif not is_daytime:
            background_name = "night_overcast.gif"
        else:
            background_name = None

        self.is_raining = background_name == "(Both)animated-looping-rain.gif"
        self.active_background = (
            self.landing_background
            if background_name == "landingpage.gif"
            else self.condition_backgrounds.get(background_name)
        )
        if (
            background_name != "landingpage.gif"
            and self.landing_background.state() == QMovie.Running
        ):
            self.landing_background.stop()
        for name, movie in self.condition_backgrounds.items():
            if name != background_name and movie.state() == QMovie.Running:
                movie.stop()
        if (
            self.active_background is not None
            and self.active_background.isValid()
            and self.active_background.state() != QMovie.Running
        ):
            self.active_background.start()

        overlay_alpha = (
            0
            if background_name == "landingpage.gif"
            else 55 if self.is_raining else (25 if is_daytime else 105)
        )
        self.background_overlay = QColor(8, 16, 34, overlay_alpha)

        if self.is_raining:
            background = "transparent"
            foreground = "#f4f7f2"
            secondary = "#d7e2df"
            input_background = "rgba(13, 25, 45, 220)"
            border = "#8ba6a0"
            panel = "rgba(13, 25, 45, 220)"
            accent = "#27685f"
            hover = "#1d554e"
        elif is_daytime:
            background = "#e9f1e8"
            foreground = "#18342d"
            secondary = "#52675f"
            input_background = "#fffdfa"
            border = "#8da89a"
            panel = "#f7faf4"
            accent = "#27685f"
            hover = "#1d554e"
        else:
            background = "transparent"
            foreground = "#e9f2ed"
            secondary = "#bac8c4"
            input_background = "#1c333b"
            border = "#53716f"
            panel = "rgba(13, 25, 45, 210)"
            accent = "#347b70"
            hover = "#438c7f"

        self.deviation_chart.set_theme_colors(foreground, secondary)

        is_landing_page = background_name == "landingpage.gif"
        button_text_color = "#e7d4fa" if is_landing_page else "white"
        input_text_color = "#000000" if is_landing_page else foreground
        if is_landing_page:
            foreground = "#e7d4fa"
            secondary = "#e7d4fa"

        highlight_day_text = (
            is_daytime and weather_id is not None and 800 <= weather_id <= 804
        )
        clock_font_size = 16 if self.has_weather_result else 28
        temperature_color = foreground
        date_color = secondary
        city_label_color = foreground
        date_weight = 400
        if highlight_day_text:
            temperature_color = "#218581"
            date_color = "#218581"
            city_label_color = "#218581"
            date_weight = 600

        self.setStyleSheet(f"""
            QWidget#WeatherDashboard {{
                background-color: {background};
                color: {foreground};
            }}
            QLabel, QPushButton, QLineEdit {{
                color: {foreground};
                font-family: Arial;
            }}
            QLabel#city_label {{
                font-size: 30px;
            }}
            QLabel#result_city_label {{
                font-size: 24px;
                font-weight: 600;
            }}
            QLabel#footer_label {{
                color: {secondary};
                font-size: 12px;
                font-style: italic;
                padding: 8px 0 0 0;
            }}
            QLabel#footer_name_label {{
                color: {secondary};
                font-size: 11px;
                padding: 0 0 8px 0;
            }}
            QLabel#clock_label {{
                font-size: {clock_font_size}px;
            }}
            QLineEdit {{
                background-color: {input_background};
                border: 2px solid {border};
                border-radius: 4px;
                padding: 12px;
                color: {input_text_color};
            }}
            QPushButton {{
                background-color: {accent};
                border: none;
                border-radius: 3px;
                color: {button_text_color};
                padding: 12px 24px;
            }}
            QPushButton:hover {{
                background-color: {hover};
            }}
            QLabel#temperature_label, QLabel#description_label {{
                font-size: 15px;
            }}
            QLabel#temperature_label {{
                font-size: 40px;
                font-weight: 700;
            }}
            QLabel#conditions_label, QLabel#description_label {{
                background-color: {panel};
                border-radius: 6px;
                font-size: 13px;
                padding: 10px;
            }}
            QLabel#emoji_label {{
                font-family: 'Apple Color Emoji';
                font-size: 120px;
            }}
            QLabel#comparison_label, QLabel#anomaly_label {{
                background-color: {panel};
                border-radius: 6px;
                font-size: 11px;
                padding: 10px;
            }}
            QWidget#deviation_chart {{
                background-color: {panel};
                border-radius: 6px;
            }}
        """)
        self.city_label.setStyleSheet(f"color: {city_label_color};")
        self.result_city_label.setStyleSheet(f"color: {city_label_color};")
        self.temperature_label.setStyleSheet(f"color: {temperature_color};")
        self.clock_label.setStyleSheet(
            f"color: {date_color}; font-weight: {date_weight}; "
            f"font-size: {clock_font_size}px;"
        )
        outline_color = "#ffffff" if highlight_day_text else None
        self.city_label.set_outline_colors(city_label_color, outline_color)
        self.result_city_label.set_outline_colors(city_label_color, outline_color)
        self.temperature_label.set_outline_colors(temperature_color, outline_color)
        self.clock_label.set_outline_colors(date_color, outline_color)
        self.update()

    def get_weather_emoji(self, weather_id, is_daytime):
        if weather_id in range(200, 233):
            return "⛈️"
        if weather_id in range(300, 322):
            return "🌦️"
        if weather_id in range(500, 532):
            return "🌧️"
        if weather_id in range(600, 623):
            return "❄️"
        if weather_id in range(700, 782):
            return "🌫️"
        if weather_id == 800:
            return "☀️" if is_daytime else "🌕"
        if weather_id == 801:
            return "🌤️" if is_daytime else "🌙☁️"
        if weather_id == 802:
            return "⛅" if is_daytime else "☁️🌙"
        if weather_id in range(803, 805):
            return "☁️"
        return "🌤️" if is_daytime else "🌙"

    def display_error(self, message):
        self.temperature_label.clear()
        self.conditions_label.clear()
        self.temperature_label.setVisible(False)
        self.conditions_label.setVisible(False)
        self.emoji_label.setVisible(True)
        self.comparison_label.clear()
        self.anomaly_label.clear()
        self.comparison_label.setVisible(False)
        self.anomaly_label.setVisible(False)
        self.description_label.setVisible(True)

        self.emoji_label.setText("⚠️")
        http_code = next(
            (
                code
                for code in ("404", "500", "502", "503", "504")
                if message == f"HTTP {code}"
                or message.startswith(f"{code} Client Error")
                or message.startswith(f"{code} Server Error")
            ),
            None,
        )
        if http_code == "404":
            error_text = (
                "404 - Location Not Found\n"
                "Confirm the city name, ZIP code, or geographic coordinates are accurate."
            )
        elif http_code in {"500", "502", "503", "504"}:
            error_text = (
                f"{http_code} - Weather Service Temporarily Unavailable\n"
                "OpenWeather is having trouble processing this request. "
                "Please retry after a brief delay."
            )
        else:
            error_text = f"Error: {message}"
        self.description_label.setText(error_text)

    def display_weather(
        self, temperature, description, wind_speed, humidity, dew_point,
        daily_low, daily_high, emoji, current_date
    ):
        self.temperature_label.setVisible(True)
        self.emoji_label.setVisible(True)
        self.conditions_label.setVisible(True)
        self.description_label.setVisible(True)

        self.temperature_label.setText(f"{temperature:.1f}°F")
        self.emoji_label.setText(emoji)
        if daily_low is not None and daily_high is not None:
            daily_low = min(daily_low, temperature)
            daily_high = max(daily_high, temperature)

        forecast_text = (
            f"TODAY'S RANGE   High: {daily_high:.1f}°F   Low: {daily_low:.1f}°F"
            if daily_low is not None and daily_high is not None
            else "TODAY'S RANGE   High and low unavailable"
        )
        dew_point_text = f"{dew_point:.1f}°F" if dew_point is not None else "N/A"
        self.conditions_label.setText(
            f"{forecast_text}\n"
            f"Dew point: {dew_point_text}   |   RH: {humidity}%   |   "
            f"Wind: {wind_speed:.1f} mph"
        )
        self.description_label.setText(f"DESCRIPTION\n{description}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    dashboard = WeatherDashboard()
    dashboard.show()
    sys.exit(app.exec_())
