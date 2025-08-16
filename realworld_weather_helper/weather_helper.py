#!/usr/bin/env python3

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, date
from typing import Dict, List, Optional, Tuple

import requests


APP_NAME = "realworld_weather_helper"
CONFIG_FILENAME = "config.json"


@dataclass
class Coordinates:
    latitude: float
    longitude: float


@dataclass
class Location:
    name: str
    coordinates: Coordinates


class ConfigManager:
    def __init__(self) -> None:
        self.config_dir = self._get_config_dir()
        self.config_path = os.path.join(self.config_dir, CONFIG_FILENAME)

    def _get_config_dir(self) -> str:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        if xdg:
            path = os.path.join(xdg, APP_NAME)
        else:
            path = os.path.join(os.path.expanduser("~"), ".config", APP_NAME)
        os.makedirs(path, exist_ok=True)
        return path

    def save_default_location(self, location: Location) -> None:
        payload = {
            "name": location.name,
            "latitude": location.coordinates.latitude,
            "longitude": location.coordinates.longitude,
        }
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def load_default_location(self) -> Optional[Location]:
        if not os.path.exists(self.config_path):
            return None
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return Location(
                name=data.get("name", "Saved Location"),
                coordinates=Coordinates(
                    latitude=float(data["latitude"]),
                    longitude=float(data["longitude"]),
                ),
            )
        except Exception:
            return None


class GeoCoder:
    GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"

    def lookup(self, name: str) -> Location:
        params = {
            "name": name,
            "count": 1,
            "language": "en",
            "format": "json",
        }
        response = requests.get(self.GEOCODE_URL, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        results = data.get("results", [])
        if not results:
            raise ValueError(f"Location not found: {name}")
        first = results[0]
        display_name_parts = [
            part
            for part in [
                first.get("name"),
                first.get("admin1"),
                first.get("country")
            ]
            if part
        ]
        display_name = ", ".join(display_name_parts)
        return Location(
            name=display_name,
            coordinates=Coordinates(
                latitude=float(first["latitude"]),
                longitude=float(first["longitude"]),
            ),
        )


class WeatherClient:
    WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
    AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

    def fetch_weather(self, coords: Coordinates) -> Dict:
        params = {
            "latitude": coords.latitude,
            "longitude": coords.longitude,
            "current": ",".join([
                "temperature_2m",
                "apparent_temperature",
                "is_day",
                "precipitation",
                "weather_code",
                "uv_index",
            ]),
            "hourly": ",".join([
                "uv_index",
                "precipitation_probability",
                "precipitation",
                "temperature_2m",
                "wind_speed_10m",
            ]),
            "daily": ",".join([
                "temperature_2m_max",
                "temperature_2m_min",
                "uv_index_max",
                "precipitation_sum",
            ]),
            "timezone": "auto",
        }
        response = requests.get(self.WEATHER_URL, params=params, timeout=20)
        response.raise_for_status()
        return response.json()

    def fetch_air_quality(self, coords: Coordinates) -> Optional[Dict]:
        params = {
            "latitude": coords.latitude,
            "longitude": coords.longitude,
            "hourly": "us_aqi",
            "timezone": "auto",
        }
        try:
            response = requests.get(self.AIR_QUALITY_URL, params=params, timeout=20)
            response.raise_for_status()
            return response.json()
        except Exception:
            return None


def _parse_iso_datetime(value: str) -> datetime:
    # Open-Meteo returns ISO 8601 strings; we treat them as naive local times per the API timezone
    return datetime.fromisoformat(value)


def _get_today_indices(hourly_times: List[str]) -> List[int]:
    if not hourly_times:
        return []
    first_dt = _parse_iso_datetime(hourly_times[0])
    today_date = first_dt.date()
    indices: List[int] = []
    for idx, t in enumerate(hourly_times):
        try:
            dt = _parse_iso_datetime(t)
        except Exception:
            continue
        if dt.date() == today_date:
            indices.append(idx)
    return indices


def analyze_today(weather: Dict, air: Optional[Dict]) -> Dict:
    current = weather.get("current", {})
    hourly = weather.get("hourly", {})
    daily = weather.get("daily", {})

    # Daily aggregates
    t_max = _safe_get_index(daily.get("temperature_2m_max", []), 0)
    t_min = _safe_get_index(daily.get("temperature_2m_min", []), 0)
    uv_max = _safe_get_index(daily.get("uv_index_max", []), 0)
    precip_sum = _safe_get_index(daily.get("precipitation_sum", []), 0)

    # Hourly today stats
    hourly_times: List[str] = hourly.get("time", [])
    today_idxs = _get_today_indices(hourly_times)

    prob_list = [
        _safe_get_index(hourly.get("precipitation_probability", []), i)
        for i in today_idxs
    ]
    max_precip_prob = max([p for p in prob_list if p is not None], default=None)

    wind_list = [
        _safe_get_index(hourly.get("wind_speed_10m", []), i)
        for i in today_idxs
    ]
    max_wind = max([w for w in wind_list if w is not None], default=None)

    # Air quality
    aqi_max = None
    if air and air.get("hourly"):
        air_times: List[str] = air["hourly"].get("time", [])
        air_idxs = _get_today_indices(air_times)
        aqi_list = [
            _safe_get_index(air["hourly"].get("us_aqi", []), i)
            for i in air_idxs
        ]
        aqi_max = max([a for a in aqi_list if a is not None], default=None)

    advice: List[str] = []
    if max_precip_prob is not None and max_precip_prob >= 50:
        advice.append("Carry an umbrella (rain likely)")
    elif precip_sum is not None and precip_sum >= 1.0:
        advice.append("Carry an umbrella (rain expected)")

    if uv_max is not None and uv_max >= 6:
        advice.append("Use sunscreen and sunglasses (high UV)")
    elif uv_max is not None and uv_max >= 3:
        advice.append("Consider sunscreen (moderate UV)")

    if max_wind is not None and max_wind >= 35:
        advice.append("Secure loose items (windy conditions)")

    if aqi_max is not None:
        if aqi_max >= 151:
            advice.append("Unhealthy air quality: limit outdoor activity")
        elif aqi_max >= 101:
            advice.append("Sensitive groups: consider limiting outdoor activity")

    return {
        "temperature_max": t_max,
        "temperature_min": t_min,
        "uv_index_max": uv_max,
        "precipitation_sum": precip_sum,
        "max_precip_probability": max_precip_prob,
        "max_wind_speed": max_wind,
        "max_us_aqi": aqi_max,
        "advice": advice,
        "current": current,
    }


def _safe_get_index(seq: List, idx: int) -> Optional[float]:
    try:
        val = seq[idx]
        if val is None:
            return None
        return float(val)
    except Exception:
        return None


def print_now(location: Location, analysis: Dict) -> None:
    current = analysis.get("current", {})
    print(f"Location: {location.name}")
    print("Now:")
    temp = current.get("temperature_2m")
    feels = current.get("apparent_temperature")
    uv = current.get("uv_index")
    precip = current.get("precipitation")
    parts: List[str] = []
    if temp is not None:
        parts.append(f"{temp}°C")
    if feels is not None:
        parts.append(f"feels {feels}°C")
    if uv is not None:
        parts.append(f"UV {uv}")
    if precip is not None:
        parts.append(f"precip {precip} mm")
    print("  " + ", ".join(parts))


def print_today(location: Location, analysis: Dict) -> None:
    print(f"Location: {location.name}")
    print("Today:")
    tmin = analysis.get("temperature_min")
    tmax = analysis.get("temperature_max")
    uvmax = analysis.get("uv_index_max")
    psum = analysis.get("precipitation_sum")
    pprob = analysis.get("max_precip_probability")
    aqi = analysis.get("max_us_aqi")

    lines: List[str] = []
    if tmin is not None and tmax is not None:
        lines.append(f"Temp {tmin}°C → {tmax}°C")
    if uvmax is not None:
        lines.append(f"UV max {int(uvmax)}")
    if psum is not None:
        lines.append(f"Precip {psum} mm")
    if pprob is not None:
        lines.append(f"Rain probability peak {int(pprob)}%")
    if aqi is not None:
        lines.append(f"US AQI max {int(aqi)}")

    if lines:
        print("  " + ", ".join(lines))

    advice: List[str] = analysis.get("advice", [])
    if advice:
        print("Advice:")
        for item in advice:
            print(f"  - {item}")


def print_alerts(analysis: Dict) -> None:
    advice: List[str] = analysis.get("advice", [])
    if not advice:
        print("No alerts. You're good to go!")
        return
    for item in advice:
        print(f"- {item}")


def resolve_location(args: argparse.Namespace, config: ConfigManager, geocoder: GeoCoder) -> Location:
    # CLI override by coordinates
    if getattr(args, "lat", None) is not None and getattr(args, "lon", None) is not None:
        return Location(
            name=f"{args.lat}, {args.lon}",
            coordinates=Coordinates(latitude=float(args.lat), longitude=float(args.lon)),
        )

    # CLI override by name
    if getattr(args, "location", None):
        return geocoder.lookup(args.location)

    # Config
    saved = config.load_default_location()
    if saved:
        return saved

    raise SystemExit("No location set. Run: python weather_helper.py setup --location \"Your City\"")


def command_setup(args: argparse.Namespace, config: ConfigManager, geocoder: GeoCoder) -> None:
    if args.location:
        loc = geocoder.lookup(args.location)
    elif args.lat is not None and args.lon is not None:
        loc = Location(
            name=f"{args.lat}, {args.lon}",
            coordinates=Coordinates(latitude=float(args.lat), longitude=float(args.lon)),
        )
    else:
        raise SystemExit("Provide --location or both --lat and --lon")

    config.save_default_location(loc)
    print(f"Saved default location: {loc.name} ({loc.coordinates.latitude}, {loc.coordinates.longitude})")


def command_now(args: argparse.Namespace, config: ConfigManager) -> None:
    geocoder = GeoCoder()
    loc = resolve_location(args, config, geocoder)
    client = WeatherClient()
    weather = client.fetch_weather(loc.coordinates)
    air = client.fetch_air_quality(loc.coordinates)
    analysis = analyze_today(weather, air)
    print_now(loc, analysis)


def command_today(args: argparse.Namespace, config: ConfigManager) -> None:
    geocoder = GeoCoder()
    loc = resolve_location(args, config, geocoder)
    client = WeatherClient()
    weather = client.fetch_weather(loc.coordinates)
    air = client.fetch_air_quality(loc.coordinates)
    analysis = analyze_today(weather, air)
    print_today(loc, analysis)


def command_alert(args: argparse.Namespace, config: ConfigManager) -> None:
    geocoder = GeoCoder()
    loc = resolve_location(args, config, geocoder)
    client = WeatherClient()
    weather = client.fetch_weather(loc.coordinates)
    air = client.fetch_air_quality(loc.coordinates)
    analysis = analyze_today(weather, air)
    print_alerts(analysis)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Real-world Weather Helper: weather, UV, and practical advice",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # setup
    p_setup = sub.add_parser("setup", help="Save default location")
    p_setup.add_argument("--location", type=str, help="City name, e.g. 'Paris'", default=None)
    p_setup.add_argument("--lat", type=float, help="Latitude", default=None)
    p_setup.add_argument("--lon", type=float, help="Longitude", default=None)
    p_setup.set_defaults(func="setup")

    # now
    p_now = sub.add_parser("now", help="Show current conditions")
    p_now.add_argument("--location", type=str, help="City name override", default=None)
    p_now.add_argument("--lat", type=float, help="Latitude override", default=None)
    p_now.add_argument("--lon", type=float, help="Longitude override", default=None)
    p_now.set_defaults(func="now")

    # today
    p_today = sub.add_parser("today", help="Show today's summary and advice")
    p_today.add_argument("--location", type=str, help="City name override", default=None)
    p_today.add_argument("--lat", type=float, help="Latitude override", default=None)
    p_today.add_argument("--lon", type=float, help="Longitude override", default=None)
    p_today.set_defaults(func="today")

    # alert
    p_alert = sub.add_parser("alert", help="Show only alerts/advice")
    p_alert.add_argument("--location", type=str, help="City name override", default=None)
    p_alert.add_argument("--lat", type=float, help="Latitude override", default=None)
    p_alert.add_argument("--lon", type=float, help="Longitude override", default=None)
    p_alert.set_defaults(func="alert")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = ConfigManager()

    try:
        if args.func == "setup":
            command_setup(args, config, GeoCoder())
        elif args.func == "now":
            command_now(args, config)
        elif args.func == "today":
            command_today(args, config)
        elif args.func == "alert":
            command_alert(args, config)
        else:
            parser.print_help()
            return 2
        return 0
    except requests.HTTPError as http_err:
        print(f"HTTP error: {http_err}")
        return 1
    except Exception as exc:
        print(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())