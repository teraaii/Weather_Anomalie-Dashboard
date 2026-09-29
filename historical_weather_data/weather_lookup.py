import datetime as datetime_
import sys
from pathlib import Path
import requests
from PyQt5.QtWidgets import (QApplication, QLabel, QVBoxLayout, QWidget,
                             QLineEdit, QPushButton, QFrame, QListWidget, QListWidgetItem)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPixmap

from historical_weather_comparison import get_hourly_comparison


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
            description = data["weather"][0]["description"].capitalize()
            weather_id = data["weather"][0]["id"]

            local_datetime = datetime_.datetime.fromtimestamp(
                data["dt"], datetime_.timezone.utc
            ) + datetime_.timedelta(seconds=data["timezone"])
            is_daytime = data["sys"]["sunrise"] <= data["dt"] < data["sys"]["sunset"]
            comparison = get_hourly_comparison(
                data["coord"]["lat"],
                data["coord"]["lon"],
                local_datetime,
            )

            self.succeeded.emit({
                "temperature": temperature,
                "wind_speed": wind_speed,
                "description": description,
                "weather_id": weather_id,
                "local_datetime": local_datetime,
                "is_daytime": is_daytime,
                "comparison": comparison,
            })
        except Exception as error:
            self.failed.emit(str(error))

class WeatherDashboard(QWidget):
    def __init__(self):
        super().__init__()
        self.clock_label = QLabel(self)
        self.city_label = QLabel("Enter City Name: ", self)
        self.city_input = QLineEdit(self)
        self.get_weather_button = QPushButton("Get Weather", self)
        self.temperature_label = QLabel("Temperature: ", self)
        self.emoji_label = QLabel("", self)
        self.description_label = QLabel("Description: ", self)
        self.wind_speed_label = QLabel("Wind Speed: ", self)
        self.comparison_label = QLabel("", self)
        self.anomaly_label = QLabel("", self)
        self.is_daytime = True
        self.night_background = QPixmap(str(
            Path(__file__).with_name("starry-night-sky-background-illustration_53876-150103.jpg")
        ))
        self.init_ui()

    def init_ui(self):
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setWindowTitle("Weather Dashboard")
        self.setObjectName("WeatherDashboard")
        self.setMinimumWidth(420)
        layout = QVBoxLayout()
        layout.addWidget(self.clock_label)
        layout.addWidget(self.city_label)
        layout.addWidget(self.city_input)
        layout.addWidget(self.get_weather_button, alignment=Qt.AlignCenter)
        layout.addWidget(self.temperature_label)
        layout.addWidget(self.emoji_label)
        layout.addWidget(self.description_label)
        layout.addWidget(self.wind_speed_label)
        layout.addWidget(self.comparison_label)
        layout.addWidget(self.anomaly_label)

        self.setLayout(layout)

        # Hide weather results until a valid city is searched
        self.temperature_label.setVisible(False)
        self.wind_speed_label.setVisible(False)
        self.description_label.setVisible(False)
        self.comparison_label.setVisible(False)
        self.anomaly_label.setVisible(False)

        self.city_label.setAlignment(Qt.AlignCenter)
        self.clock_label.setAlignment(Qt.AlignCenter)
        self.city_input.setAlignment(Qt.AlignCenter)
        self.temperature_label.setAlignment(Qt.AlignCenter)
        self.emoji_label.setAlignment(Qt.AlignCenter)
        self.description_label.setAlignment(Qt.AlignCenter)
        self.wind_speed_label.setAlignment(Qt.AlignCenter)
        self.comparison_label.setAlignment(Qt.AlignCenter)
        self.anomaly_label.setAlignment(Qt.AlignCenter)
        self.comparison_label.setWordWrap(True)
        self.anomaly_label.setWordWrap(True)

        self.city_label.setObjectName("city_label")
        self.clock_label.setObjectName("clock_label")
        self.city_input.setObjectName("city_input")
        self.get_weather_button.setObjectName("get_weather_button")
        self.temperature_label.setObjectName("temperature_label")
        self.emoji_label.setObjectName("emoji_label")
        self.description_label.setObjectName("description_label")
        self.wind_speed_label.setObjectName("wind_speed_label")
        self.comparison_label.setObjectName("comparison_label")
        self.anomaly_label.setObjectName("anomaly_label")
        
        self.apply_theme(is_daytime=True)
        
        self.get_weather_button.clicked.connect(self.get_weather)
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self.update_clock)
        self.clock_timer.start(1000)
        self.update_clock()

    def update_clock(self):
        current_time = datetime_.datetime.now()
        self.clock_label.setText(current_time.strftime("%A, %B %d | %I:%M:%S %p"))

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.is_daytime or self.night_background.isNull():
            return

        scaled_background = self.night_background.scaled(
            self.size(),
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )
        offset_x = (self.width() - scaled_background.width()) // 2
        offset_y = (self.height() - scaled_background.height()) // 2
        painter = QPainter(self)
        painter.drawPixmap(offset_x, offset_y, scaled_background)
        painter.fillRect(self.rect(), QColor(8, 16, 34, 105))
        
    def get_weather(self):
        api_key = "c25190393fbf204deb1a06c4200d29c4"
        city = self.city_input.text().strip()

        if not city:
            self.display_error("Please enter a city name.")
            return

        for label in (
            self.temperature_label,
            self.emoji_label,
            self.wind_speed_label,
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
        self.apply_theme(result["is_daytime"])
        self.display_weather(
            result["temperature"],
            result["description"],
            result["wind_speed"],
            self.get_weather_emoji(result["weather_id"], result["is_daytime"]),
            result["local_datetime"].strftime("%B %d, %Y at %I:%M %p"),
        )

        comparison = result["comparison"]
        self.comparison_label.setText(
            "HISTORICAL WEATHER (SAME LOCAL HOUR)\n"
            f"{comparison['historical_date']:%B %d, %Y} at "
            f"{comparison['hour']:02d}:00 ({comparison['timezone']}): "
            f"{comparison['historical_temperature']:.0f}°F, "
            f"{comparison['historical_wind']:.0f} mph"
        )
        self.comparison_label.setVisible(True)
        temperature_deviation = (
            result["temperature"] - comparison["historical_temperature"]
        )
        wind_deviation = result["wind_speed"] - comparison["historical_wind"]

        def deviation_color(value):
            if value > 0:
                return "#c62828"
            if value < 0:
                return "#2e7d32"
            return "#555555"

        temperature_color = deviation_color(temperature_deviation)
        wind_color = deviation_color(wind_deviation)
        self.anomaly_label.setText(
            "HOURLY DEVIATION (vs same local hour last year)<br>"
            f"Temperature: <span style='color: {temperature_color}; font-weight: 600'>"
            f"{temperature_deviation:+.0f}°F</span><br>"
            f"Wind: <span style='color: {wind_color}; font-weight: 600'>"
            f"{wind_deviation:+.0f} mph</span>"
        )
        self.anomaly_label.setTextFormat(Qt.RichText)
        self.anomaly_label.setVisible(True)

    def apply_theme(self, is_daytime):
        self.is_daytime = is_daytime
        if is_daytime:
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
                color: {secondary};
                font-size: 16px;
            }}
            QLineEdit {{
                background-color: {input_background};
                border: 2px solid {border};
                border-radius: 4px;
                padding: 12px;
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
            QLabel#emoji_label {{
                font-family: 'Apple Color Emoji';
                font-size: 100px;
            }}
            QLabel#wind_speed_label {{
                font-size: 15px;
            }}
            QLabel#comparison_label, QLabel#anomaly_label {{
                background-color: {panel};
                border-radius: 6px;
                font-size: 11px;
                padding: 10px;
            }}
        """)
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
        self.wind_speed_label.clear()
        self.temperature_label.setVisible(False)
        self.wind_speed_label.setVisible(False)
        self.emoji_label.setVisible(True)
        self.comparison_label.clear()
        self.anomaly_label.clear()
        self.comparison_label.setVisible(False)
        self.anomaly_label.setVisible(False)
        self.description_label.setVisible(True)

        self.emoji_label.setText("⚠️")
        self.description_label.setText(f"Error: {message}")

    def display_weather(self, temperature, description, wind_speed, emoji, current_date):
        self.temperature_label.setVisible(True)
        self.emoji_label.setVisible(True)
        self.wind_speed_label.setVisible(True)
        self.description_label.setVisible(True)

        self.temperature_label.setText(
            f"CURRENT WEATHER\n{current_date}\n\nTemperature: {temperature:.1f}°F"
        )
        self.emoji_label.setText(emoji)
        self.description_label.setText(f"Description: {description}")
        self.wind_speed_label.setText(f"Wind: {wind_speed:.1f} mph")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    dashboard = WeatherDashboard()
    dashboard.show()
    sys.exit(app.exec_())
