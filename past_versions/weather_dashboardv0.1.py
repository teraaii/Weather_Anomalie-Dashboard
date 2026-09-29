import sys
import requests
from PyQt5.QtWidgets import (QApplication, QLabel, QVBoxLayout, QWidget,
                             QLineEdit, QPushButton, QFrame)
from PyQt5.QtCore import Qt

class WeatherDashboard(QWidget):
    def __init__(self):
        super().__init__()
        self.city_label = QLabel("Enter City Name: ", self)
        self.city_input = QLineEdit(self)
        self.get_weather_button = QPushButton("Get Weather", self)
        self.temperature_label = QLabel("Temperature: ", self)
        self.emoji_label = QLabel("", self)
        self.description_label = QLabel("Description: ", self)
        self.wind_speed_label = QLabel("Wind Speed: ", self)
        self.init_ui()

    def init_ui(self): #CSS Inputs
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("Weather Dashboard")
        self.setMinimumWidth(420)
        layout = QVBoxLayout()
        layout.addWidget(self.city_label)
        layout.addWidget(self.city_input)
        layout.addWidget(self.get_weather_button, alignment=Qt.AlignCenter)
        layout.addWidget(self.temperature_label)
        layout.addWidget(self.emoji_label)
        layout.addWidget(self.description_label)
        layout.addWidget(self.wind_speed_label)

        self.setLayout(layout)
        
        self.city_label.setAlignment(Qt.AlignCenter)
        self.city_input.setAlignment(Qt.AlignCenter)
        self.temperature_label.setAlignment(Qt.AlignCenter)
        self.emoji_label.setAlignment(Qt.AlignCenter)
        self.description_label.setAlignment(Qt.AlignCenter)
        self.wind_speed_label.setAlignment(Qt.AlignCenter)

        self.city_label.setObjectName("city_label")
        self.city_input.setObjectName("city_input")
        self.get_weather_button.setObjectName("get_weather_button")
        self.temperature_label.setObjectName("temperature_label")
        self.emoji_label.setObjectName("emoji_label")
        self.description_label.setObjectName("description_label")
        self.wind_speed_label.setObjectName("wind_speed_label")
        
        self.setStyleSheet("""
            QLabel, QPushButton, QLineEdit {
                font-family: Arial;
            }
            QWidget {
            background: transparent;
            }

            QFrame {
           background-color: rgba(255, 255, 255, 0);
            border-radius: 25px;
            }
            QLabel#city_label {
                font-size: 40px;
            }
            QLineEdit {
                padding: 12px;
                border: 3px solid #aaaaaa;
                border-radius: 4px;
            }
            QPushButton {
                padding: 12px 24px;
                color: white;
                background-color: #e550eb;
                border: none;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #6250eb;
            }
            QLabel#temperature_label, QLabel#description_label {
                font-size: 25px;
            }
            QLabel#emoji_label {
                font-size: 60px;
            }
            QLabel#wind_speed_label {
                font-size: 15px;
            }
        """)
        
        self.get_weather_button.clicked.connect(self.get_weather)
        
    def get_weather(self):
        api_key = "c25190393fbf204deb1a06c4200d29c4"
        city = self.city_input.text().strip()

        if not city:
            self.display_error("Please enter a city name.")
            return

        url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}"
        try:
            response = requests.get(url, timeout=10)
            data = response.json()
        except (requests.RequestException, ValueError) as error:
            self.display_error(f"Unable to retrieve weather: {error}")
            return

        if response.ok and data.get("cod") == 200:
            temperature = (data["main"]["temp"] - 273.15) * 9/5 + 32 # Convert Kelvin to Fahrenheit
            wind_speed = data["wind"]["speed"] * 2.237 # Convert m/s to mph
            description = data["weather"][0]["description"].capitalize()
            weather_id = data["weather"][0]["id"]
            self.display_weather(temperature, description,
                                 wind_speed,
                                 self.get_weather_emoji(weather_id))
        else:
            self.display_error(data.get("message", "City not found."))

    
    def display_error(self, message):
        self.temperature_label.setText("Temperature: ")
        self.emoji_label.setText("⚠️")
        self.description_label.setText(f"Error: {message}")
   
    def display_weather(self, temperature, description, wind_speed, emoji):
        self.temperature_label.setText(f"Temperature: {temperature:.1f}°F")
        self.emoji_label.setText(emoji)
        self.description_label.setText(f"Description: {description}")
        self.wind_speed_label.setText(f"Wind Speed: {wind_speed:.1f} mph")

    @staticmethod #establishing the weather emoji based on the weather ID from the API
    def get_weather_emoji(weather_id):

        if 200 <= weather_id <= 232:
            return "⛈"
        elif 300 <= weather_id <= 321:
            return "🌦"
        elif 500 <= weather_id <= 531:
            return "🌧"
        elif 600 <= weather_id <= 622:
            return "❄"
        elif 701 <= weather_id <= 741:
            return "🌫"
        elif weather_id == 762:
            return "🌋"
        elif weather_id == 771:
            return "💨"
        elif weather_id == 781:
            return "🌪"
        elif weather_id == 800:
            return "☀"
        elif 801 <= weather_id <= 804:
            return "☁"
        else:
            return ""

        
        
        
if __name__ == "__main__":
    app = QApplication(sys.argv)
    dashboard = WeatherDashboard()
    dashboard.show()
    sys.exit(app.exec_())       