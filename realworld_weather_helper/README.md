Real-World Weather Helper (Python CLI)

A tiny real-world Python project that:
- Looks up your location (city name or coordinates)
- Fetches weather and UV data from Open-Meteo (no API key required)
- Gives practical advice (carry umbrella, sunscreen)
- Saves a default location for quick use

Setup

1) Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2) Install dependencies

```bash
pip install -r requirements.txt
```

Usage

- Save your default location (city name):
```bash
python weather_helper.py setup --location "San Francisco"
```

- Or set by coordinates:
```bash
python weather_helper.py setup --lat 37.7749 --lon -122.4194
```

- Show current conditions:
```bash
python weather_helper.py now
```

- Show today's summary and advice:
```bash
python weather_helper.py today
```

- Show only alerts/advice (umbrella, sunscreen, air quality):
```bash
python weather_helper.py alert
```

- Override the saved location on the fly:
```bash
python weather_helper.py today --location "Tokyo"
```

Notes

- Uses Open-Meteo Weather, Air Quality, and Geocoding APIs (no API key needed).
- Config is stored under XDG config (e.g., ~/.config/realworld_weather_helper/config.json).