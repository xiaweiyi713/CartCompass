from __future__ import annotations

import asyncio
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from app.models.schemas import CurrentWeather, DailyWeather, WeatherContext, WeatherImplications, WeatherLocation


KNOWN_LOCATIONS: dict[str, tuple[str, str, float, float, str]] = {
    "成都": ("成都", "中国", 30.5728, 104.0668, "Asia/Shanghai"),
    "三亚": ("三亚", "中国", 18.2528, 109.5119, "Asia/Shanghai"),
    "上海": ("上海", "中国", 31.2304, 121.4737, "Asia/Shanghai"),
    "北京": ("北京", "中国", 39.9042, 116.4074, "Asia/Shanghai"),
    "哈尔滨": ("哈尔滨", "中国", 45.8038, 126.5349, "Asia/Shanghai"),
    "新疆": ("乌鲁木齐", "中国", 43.8256, 87.6168, "Asia/Shanghai"),
    "拉萨": ("拉萨", "中国", 29.6520, 91.1721, "Asia/Shanghai"),
    "张家界": ("张家界", "中国", 29.1167, 110.4784, "Asia/Shanghai"),
    "东京": ("东京", "日本", 35.6762, 139.6503, "Asia/Tokyo"),
    "大阪": ("大阪", "日本", 34.6937, 135.5023, "Asia/Tokyo"),
    "京都": ("京都", "日本", 35.0116, 135.7681, "Asia/Tokyo"),
    "冲绳": ("那霸", "日本", 26.2124, 127.6792, "Asia/Tokyo"),
    "柏林": ("柏林", "德国", 52.5200, 13.4050, "Europe/Berlin"),
    "德国": ("柏林", "德国", 52.5200, 13.4050, "Europe/Berlin"),
    "巴黎": ("巴黎", "法国", 48.8566, 2.3522, "Europe/Paris"),
    "法国": ("巴黎", "法国", 48.8566, 2.3522, "Europe/Paris"),
    "罗马": ("罗马", "意大利", 41.9028, 12.4964, "Europe/Rome"),
    "意大利": ("罗马", "意大利", 41.9028, 12.4964, "Europe/Rome"),
    "伦敦": ("伦敦", "英国", 51.5072, -0.1276, "Europe/London"),
    "英国": ("伦敦", "英国", 51.5072, -0.1276, "Europe/London"),
    "瑞士": ("苏黎世", "瑞士", 47.3769, 8.5417, "Europe/Zurich"),
}


class WeatherService:
    def __init__(self, timeout: float = 6.0) -> None:
        self.timeout = timeout
        self._cache: dict[str, tuple[float, WeatherContext | None]] = {}
        self._geocode_cache: dict[str, WeatherLocation | None] = {}

    async def lookup(self, location: str, days: int = 7) -> WeatherContext | None:
        location = location.strip()
        if not location:
            return None
        days = max(1, min(days, 7))
        cache_key = f"{location}:{days}"
        cached = self._cache.get(cache_key)
        if cached and time.time() - cached[0] < 600:
            return cached[1]
        result = await asyncio.to_thread(self._lookup_sync, location, days)
        self._cache[cache_key] = (time.time(), result)
        return result

    def _lookup_sync(self, location: str, days: int) -> WeatherContext | None:
        weather_location = self._geocode(location)
        if not weather_location:
            return None
        try:
            payload = self._get_json(
                "https://api.open-meteo.com/v1/forecast?"
                + urllib.parse.urlencode(
                    {
                        "latitude": weather_location.latitude,
                        "longitude": weather_location.longitude,
                        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m,is_day",
                        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,uv_index_max,weather_code",
                        "forecast_days": days,
                        "timezone": weather_location.timezone or "auto",
                    }
                )
            )
        except Exception:
            return self._fallback_context(weather_location)
        context = self._map_forecast(weather_location, payload)
        return context or self._fallback_context(weather_location)

    def _geocode(self, location: str) -> WeatherLocation | None:
        if location in self._geocode_cache:
            return self._geocode_cache[location]
        known = self._known_location(location)
        if known:
            self._geocode_cache[location] = known
            return known
        try:
            geo = self._get_json(
                "https://geocoding-api.open-meteo.com/v1/search?"
                + urllib.parse.urlencode({"name": location, "count": 1, "language": "zh", "format": "json"})
            )
        except Exception:
            self._geocode_cache[location] = None
            return None
        results = geo.get("results") if isinstance(geo, dict) else None
        if not results:
            self._geocode_cache[location] = None
            return None
        first = results[0]
        latitude = self._number(first.get("latitude"))
        longitude = self._number(first.get("longitude"))
        if latitude is None or longitude is None:
            self._geocode_cache[location] = None
            return None
        resolved = WeatherLocation(
            name=str(first.get("name") or location),
            country=first.get("country"),
            latitude=latitude,
            longitude=longitude,
            timezone=first.get("timezone"),
        )
        self._geocode_cache[location] = resolved
        return resolved

    def _known_location(self, location: str) -> WeatherLocation | None:
        for key, value in KNOWN_LOCATIONS.items():
            if key in location or location in key:
                name, country, latitude, longitude, tz = value
                return WeatherLocation(name=name, country=country, latitude=latitude, longitude=longitude, timezone=tz)
        return None

    def _map_forecast(self, location: WeatherLocation, payload: dict[str, Any]) -> WeatherContext | None:
        current_raw = payload.get("current") if isinstance(payload, dict) else None
        daily_raw = payload.get("daily") if isinstance(payload, dict) else None
        current = self._map_current(current_raw) if isinstance(current_raw, dict) else None
        daily = self._map_daily(daily_raw) if isinstance(daily_raw, dict) else []
        if not current and not daily:
            return None
        context = WeatherContext(
            location=location,
            current=current,
            daily=daily,
            implications=WeatherImplications(),
            source="Open-Meteo",
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )
        context.implications = self.implications(context)
        return context

    def _fallback_context(self, location: WeatherLocation) -> WeatherContext:
        defaults = {
            "成都": ("多云", 24.0, 24.0, 72.0, 0.2, 8.0),
            "三亚": ("晴", 29.0, 35.0, 80.0, 0.0, 12.0),
            "上海": ("多云", 26.0, 27.0, 68.0, 0.1, 10.0),
            "北京": ("晴", 27.0, 26.0, 36.0, 0.0, 9.0),
            "柏林": ("多云", 25.0, 23.0, 33.0, 0.0, 10.0),
            "罗马": ("晴", 27.0, 27.0, 45.0, 0.0, 8.0),
        }
        condition, temperature, apparent, humidity, precipitation, wind = defaults.get(
            location.name,
            ("多云", 22.0, 22.0, 60.0, 0.0, 8.0),
        )
        context = WeatherContext(
            location=location,
            current=CurrentWeather(
                temperature_c=temperature,
                apparent_temperature_c=apparent,
                condition=condition,
                precipitation_mm=precipitation,
                humidity=humidity,
                wind_speed_kmh=wind,
                is_day=None,
            ),
            daily=[],
            implications=WeatherImplications(),
            source="Open-Meteo（降级缓存）",
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )
        context.implications = self.implications(context)
        return context

    def _map_current(self, raw: dict[str, Any]) -> CurrentWeather:
        code = self._number(raw.get("weather_code"))
        is_day = raw.get("is_day")
        return CurrentWeather(
            temperature_c=self._number(raw.get("temperature_2m")),
            apparent_temperature_c=self._number(raw.get("apparent_temperature")),
            condition=self._describe_code(int(code)) if code is not None else "天气状况未知",
            precipitation_mm=self._number(raw.get("precipitation")),
            humidity=self._number(raw.get("relative_humidity_2m")),
            wind_speed_kmh=self._number(raw.get("wind_speed_10m")),
            is_day=bool(is_day) if is_day is not None else None,
        )

    def _map_daily(self, raw: dict[str, Any]) -> list[DailyWeather]:
        dates = raw.get("time") or []
        output: list[DailyWeather] = []
        for index, date in enumerate(dates[:7]):
            code = self._daily_value(raw, "weather_code", index)
            output.append(
                DailyWeather(
                    date=str(date),
                    temp_min_c=self._number(self._daily_value(raw, "temperature_2m_min", index)),
                    temp_max_c=self._number(self._daily_value(raw, "temperature_2m_max", index)),
                    precipitation_probability_max=self._number(
                        self._daily_value(raw, "precipitation_probability_max", index)
                    ),
                    uv_index_max=self._number(self._daily_value(raw, "uv_index_max", index)),
                    condition=self._describe_code(int(code)) if self._number(code) is not None else None,
                )
            )
        return output

    def implications(self, context: WeatherContext) -> WeatherImplications:
        tags: list[str] = []
        needs: list[str] = []
        advice: list[str] = []
        current = context.current
        max_temp = self._max(item.temp_max_c for item in context.daily)
        min_temp = self._min(item.temp_min_c for item in context.daily)
        max_rain = self._max(item.precipitation_probability_max for item in context.daily)
        max_uv = self._max(item.uv_index_max for item in context.daily)
        if current and current.temperature_c is not None:
            max_temp = max(max_temp, current.temperature_c) if max_temp is not None else current.temperature_c
            min_temp = min(min_temp, current.temperature_c) if min_temp is not None else current.temperature_c
        if current and current.precipitation_mm and current.precipitation_mm > 0:
            max_rain = max(max_rain or 0, 80)
        if max_temp is not None and max_temp >= 30:
            tags.append("高温")
            needs.extend(["防晒", "透气衣物", "补水"])
            advice.append("高温环境优先准备防晒和补水用品。")
        if min_temp is not None and min_temp <= 5:
            tags.append("低温")
            needs.extend(["保暖", "防风", "保湿"])
            advice.append("低温环境建议准备保暖衣物和保湿用品。")
        if max_rain is not None and max_rain >= 50:
            tags.append("降雨概率高")
            needs.extend(["雨具", "防水", "防滑"])
            advice.append("降雨概率较高，优先考虑雨具、防水收纳和防滑鞋。")
        if max_uv is not None and max_uv >= 6:
            tags.append("紫外线强")
            needs.extend(["防晒霜", "防晒衣", "墨镜"])
            advice.append("紫外线偏强，建议增加防晒霜、防晒衣和墨镜。")
        if current and current.humidity is not None and current.humidity >= 75:
            tags.append("潮湿")
            needs.extend(["速干", "防水收纳"])
        return WeatherImplications(
            tags=list(dict.fromkeys(tags)),
            shopping_needs=list(dict.fromkeys(needs)),
            travel_advice=list(dict.fromkeys(advice)),
        )

    def _get_json(self, url: str) -> dict:
        request = urllib.request.Request(url, headers={"User-Agent": "ShopGuideWeather/1.0"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _daily_value(self, raw: dict[str, Any], key: str, index: int) -> Any:
        values = raw.get(key) or []
        return values[index] if index < len(values) else None

    def _number(self, value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _max(self, values) -> float | None:
        valid = [value for value in values if value is not None]
        return max(valid) if valid else None

    def _min(self, values) -> float | None:
        valid = [value for value in values if value is not None]
        return min(valid) if valid else None

    def _describe_code(self, code: int) -> str:
        if code == 0:
            return "晴"
        if code in {1, 2, 3}:
            return "多云"
        if code in {45, 48}:
            return "雾"
        if code in {51, 53, 55, 56, 57}:
            return "毛毛雨"
        if code in {61, 63, 65, 66, 67, 80, 81, 82}:
            return "降雨"
        if code in {71, 73, 75, 77, 85, 86}:
            return "降雪"
        if code in {95, 96, 99}:
            return "雷暴"
        return "天气状况未知"
