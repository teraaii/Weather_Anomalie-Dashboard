import datetime as datetime_
import math
import sys
from pathlib import Path
import requests
from PyQt5.QtWidgets import (QApplication, QLabel, QVBoxLayout, QWidget,
                             QLineEdit, QPushButton, QFrame, QListWidget,
                             QListWidgetItem, QScrollArea)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import (
    QColor,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPen,
    QMovie,
)

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

            self.succeeded.emit({
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
            })
        except Exception as error:
            self.failed.emit(str(error))

class WeatherDashboard(QWidget):
    def __init__(self):
        super().__init__()
        self.clock_label = OutlinedLabel(parent=self)
        self.city_label = OutlinedLabel("Enter City Name: ", self)
        self.city_input = QLineEdit(self)
        self.get_weather_button = QPushButton("Get Weather", self)
        self.temperature_label = OutlinedLabel("Temperature: ", self)
        self.emoji_label = QLabel("", self)
        self.description_label = QLabel("Description: ", self)
        self.conditions_label = QLabel("", self)
        self.comparison_label = QLabel("", self)
        self.anomaly_label = QLabel("", self)
        self.location_timezone_offset = None
        self.is_daytime = True
        self.is_raining = False
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
        content_layout = QVBoxLayout(content_widget)
        content_layout.addWidget(self.clock_label)
        content_layout.addWidget(self.city_label)
        content_layout.addWidget(self.city_input)
        content_layout.addWidget(self.get_weather_button, alignment=Qt.AlignCenter)
        content_layout.addWidget(self.temperature_label)
        content_layout.addWidget(self.emoji_label)
        content_layout.addWidget(self.description_label)
        content_layout.addWidget(self.conditions_label)
        content_layout.addWidget(self.comparison_label)
        content_layout.addWidget(self.anomaly_label)

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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.scroll_area)

        # Hide weather results until a valid city is searched
        self.temperature_label.setVisible(False)
        self.conditions_label.setVisible(False)
        self.description_label.setVisible(False)
        self.comparison_label.setVisible(False)
        self.anomaly_label.setVisible(False)

        self.city_label.setAlignment(Qt.AlignCenter)
        self.clock_label.setAlignment(Qt.AlignCenter)
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
        
    def get_weather(self):
        api_key = "c25190393fbf204deb1a06c4200d29c4"
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
        self.get_weather_button.setText("Get Weather")

    def display_weather_result(self, result):
        self.location_timezone_offset = result["timezone_offset"]
        self.update_clock()
        self.apply_theme(result["is_daytime"], result["weather_id"])
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
            f"Dew point: {historical_dew_point_text}"
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

    def apply_theme(self, is_daytime, weather_id=None):
        self.is_daytime = is_daytime
        if weather_id is not None and 200 <= weather_id < 233:
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
        self.active_background = self.condition_backgrounds.get(background_name)
        for name, movie in self.condition_backgrounds.items():
            if name != background_name and movie.state() == QMovie.Running:
                movie.stop()
        if (
            self.active_background is not None
            and self.active_background.isValid()
            and self.active_background.state() != QMovie.Running
        ):
            self.active_background.start()

        overlay_alpha = 55 if self.is_raining else (25 if is_daytime else 105)
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

        highlight_day_text = (
            is_daytime and weather_id is not None and 800 <= weather_id <= 804
        )
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
            QLabel#clock_label {{
                font-size: 16px;
            }}
            QLineEdit {{
                background-color: {input_background};
                border: 2px solid {border};
                border-radius: 4px;
                padding: 12px;
                color: {foreground};
            }}
            QPushButton {{
                background-color: {accent};
                border: none;
                border-radius: 3px;
                color: white;
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
                font-size: 100px;
            }}
            QLabel#comparison_label, QLabel#anomaly_label {{
                background-color: {panel};
                border-radius: 6px;
                font-size: 11px;
                padding: 10px;
            }}
        """)
        self.city_label.setStyleSheet(f"color: {city_label_color};")
        self.temperature_label.setStyleSheet(f"color: {temperature_color};")
        self.clock_label.setStyleSheet(
            f"color: {date_color}; font-weight: {date_weight};"
        )
        outline_color = "#ffffff" if highlight_day_text else None
        self.city_label.set_outline_colors(city_label_color, outline_color)
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
        self.description_label.setText(f"Error: {message}")

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
        forecast_text = (
            f"TODAY'S FORECAST   High: {daily_high:.1f}°F   Low: {daily_low:.1f}°F"
            if daily_low is not None and daily_high is not None
            else "TODAY'S FORECAST   High and low unavailable"
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
