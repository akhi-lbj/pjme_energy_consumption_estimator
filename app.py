from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field
from typing import Any
from mangum import Mangum
import joblib
import pandas as pd
import os
import logging
import watchtower
import boto3
import urllib.request
import json
import datetime
import re

# 1. Logging and Monitoring Configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pjme-serverless-service")

try:
    cw_client = boto3.client('logs', region_name='ap-south-1')
    logger.addHandler(watchtower.CloudWatchLogHandler(
        log_group_name="PJME_Inference_Pipeline",
        log_stream_name="Serverless_Lambda_Logs",
        boto3_client=cw_client
    ))
except Exception as e:
    logger.warning(f"CloudWatch binding skipped for local runtime context: {e}")

# Initialize Bedrock Runtime client in ap-south-1
try:
    bedrock_client = boto3.client("bedrock-runtime", region_name="ap-south-1")
except Exception as e:
    logger.warning(f"Bedrock runtime binding skipped: {e}")

# Bedrock Model Identifier (OpenAI GPT-OSS 20B with native autonomous tool calling)
BEDROCK_MODEL_ID = "openai.gpt-oss-20b-1:0"

# Initialize LangChain ChatBedrockConverse client (AWS Bedrock Converse API integration)
try:
    from langchain_aws import ChatBedrockConverse
    from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
    from langchain_core.tools import tool
    llm = ChatBedrockConverse(
        model=BEDROCK_MODEL_ID,
        region_name="ap-south-1",
        temperature=0.2,
        max_tokens=2048
    )
    logger.info("LangChain ChatBedrockConverse successfully initialized for openai.gpt-oss-20b-1:0")
except Exception as e:
    logger.warning(f"LangChain ChatBedrockConverse binding fallback: {e}")
    llm = None


# 2. Meteorological Tools (Live & Historical Archive APIs)
def get_live_weather(lat: float = 39.95, lon: float = -75.16) -> dict:
    """
    Fetches real-time live meteorological telemetry for grid coordinates (default: PJM East / Philadelphia, PA).
    API: Open-Meteo High-Resolution Meteorological API (open-access, zero-key, high-availability).
    Purpose: Correlates forecasted heatwaves or cold snaps directly with electricity demand spikes.
    """
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}&"
            f"current=temperature_2m,relative_humidity_2m,apparent_temperature,wind_speed_10m"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "PJME-Energy-Forecaster/1.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            raw_data = json.loads(resp.read().decode("utf-8"))

        current = raw_data.get("current", {})
        temp_c = current.get("temperature_2m", 20.0)
        feels_c = current.get("apparent_temperature", temp_c)
        temp_f = round(temp_c * 9 / 5 + 32, 1)
        feels_f = round(feels_c * 9 / 5 + 32, 1)
        humidity = current.get("relative_humidity_2m", 50)
        wind_kmh = current.get("wind_speed_10m", 10.0)

        return {
            "status": "success",
            "region": "PJM East (Live Current Telemetry)",
            "latitude": lat,
            "longitude": lon,
            "temperature_celsius": temp_c,
            "temperature_fahrenheit": temp_f,
            "feels_like_celsius": feels_c,
            "feels_like_fahrenheit": feels_f,
            "relative_humidity_percent": humidity,
            "wind_speed_kmh": wind_kmh
        }
    except Exception as e:
        logger.warning(f"Live weather lookup fallback triggered: {e}")
        return {
            "status": "fallback",
            "region": "PJM East Regional Grid Estimate",
            "latitude": lat,
            "longitude": lon,
            "temperature_celsius": 20.5,
            "temperature_fahrenheit": 68.9,
            "feels_like_celsius": 20.5,
            "feels_like_fahrenheit": 68.9,
            "relative_humidity_percent": 50.0,
            "wind_speed_kmh": 12.0
        }


def get_historical_weather(
    year: int = 2016,
    month: int = 1,
    dayofyear: int = 4,
    hour: int = 18,
    date_str: str = None,
    lat: float = 39.95,
    lon: float = -75.16
) -> dict:
    """
    Parses historical meteorological archive data directly from user-entered input matrix columns:
    year, month, dayofyear, and hour.
    API: Open-Meteo Historical Weather Archive API (1940-present, open-access, zero-key).
    """
    if not date_str:
        try:
            target_date = datetime.date(year, 1, 1) + datetime.timedelta(days=max(0, dayofyear - 1))
            date_str = target_date.strftime("%Y-%m-%d")
        except Exception:
            date_str = f"{year:04d}-{max(1, min(12, month)):02d}-01"

    safe_hour = max(0, min(23, hour))

    try:
        url = (
            f"https://archive-api.open-meteo.com/v1/archive?"
            f"latitude={lat}&longitude={lon}&start_date={date_str}&end_date={date_str}&"
            f"hourly=temperature_2m,relative_humidity_2m,apparent_temperature,wind_speed_10m"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "PJME-Energy-Forecaster/1.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            raw_data = json.loads(resp.read().decode("utf-8"))

        hourly = raw_data.get("hourly", {})
        temps = hourly.get("temperature_2m", [])
        feels = hourly.get("apparent_temperature", [])
        humidities = hourly.get("relative_humidity_2m", [])
        winds = hourly.get("wind_speed_10m", [])

        temp_c = temps[safe_hour] if len(temps) > safe_hour else 1.0
        feels_c = feels[safe_hour] if len(feels) > safe_hour else temp_c
        temp_f = round(temp_c * 9 / 5 + 32, 1)
        feels_f = round(feels_c * 9 / 5 + 32, 1)
        humidity = humidities[safe_hour] if len(humidities) > safe_hour else 35
        wind_kmh = winds[safe_hour] if len(winds) > safe_hour else 15.0

        if temp_c <= 0:
            thermal_regime = "Freezing Winter Load Spike"
        elif temp_c < 12:
            thermal_regime = "Cold Space-Heating Demand"
        elif temp_c < 24:
            thermal_regime = "Mild / Baseline Load"
        else:
            thermal_regime = "Warm Air Conditioning Cooling Surge"

        return {
            "status": "success",
            "region": "PJM East (Historical Weather Archive)",
            "parsed_from_input_columns": {
                "year": year,
                "month": month,
                "dayofyear": dayofyear,
                "hour": safe_hour
            },
            "derived_calendar_timestamp": f"{date_str} {safe_hour:02d}:00:00",
            "target_date": date_str,
            "target_hour": f"{safe_hour}:00",
            "temperature_celsius": temp_c,
            "temperature_fahrenheit": temp_f,
            "feels_like_celsius": feels_c,
            "feels_like_fahrenheit": feels_f,
            "relative_humidity_percent": humidity,
            "wind_speed_kmh": wind_kmh,
            "thermal_regime": thermal_regime
        }
    except Exception as e:
        logger.warning(f"Historical weather lookup fallback triggered: {e}")
        return {
            "status": "fallback",
            "region": "PJM East (Historical Baseline Estimate)",
            "parsed_from_input_columns": {
                "year": year,
                "month": month,
                "dayofyear": dayofyear,
                "hour": safe_hour
            },
            "derived_calendar_timestamp": f"{date_str} {safe_hour:02d}:00:00",
            "target_date": date_str,
            "target_hour": f"{hour}:00",
            "temperature_celsius": 1.0,
            "temperature_fahrenheit": 33.8,
            "feels_like_celsius": 1.0,
            "feels_like_fahrenheit": 33.8,
            "relative_humidity_percent": 34.0,
            "wind_speed_kmh": 15.0,
            "thermal_regime": "Cold Space-Heating Demand"
        }


def get_forecast_weather(
    date_str: str = None,
    hour: int = 12,
    days: int = 1,
    lat: float = 39.95,
    lon: float = -75.16
) -> dict:
    """
    Fetches forward-looking hourly meteorological forecast data (up to 16 days ahead)
    using the Open-Meteo High-Resolution Forecast API (open-access, zero-key, high-availability).
    Enables forward day-ahead dispatch planning and weather-load correlation.
    """
    if not date_str:
        target_dt = datetime.date.today() + datetime.timedelta(days=1)
        date_str = target_dt.strftime("%Y-%m-%d")

    safe_hour = max(0, min(23, hour))
    safe_days = max(1, min(16, days))

    try:
        start_dt = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        end_dt = start_dt + datetime.timedelta(days=safe_days - 1)
        end_date_str = end_dt.strftime("%Y-%m-%d")
    except Exception:
        end_date_str = date_str

    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}&start_date={date_str}&end_date={end_date_str}&"
            f"hourly=temperature_2m,relative_humidity_2m,apparent_temperature,wind_speed_10m,precipitation_probability"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "PJME-Energy-Forecaster/1.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            raw_data = json.loads(resp.read().decode("utf-8"))

        hourly = raw_data.get("hourly", {})
        temps = hourly.get("temperature_2m", [])
        feels = hourly.get("apparent_temperature", [])
        humidities = hourly.get("relative_humidity_2m", [])
        winds = hourly.get("wind_speed_10m", [])
        precips = hourly.get("precipitation_probability", [])

        temp_c = temps[safe_hour] if len(temps) > safe_hour else 18.0
        feels_c = feels[safe_hour] if len(feels) > safe_hour else temp_c
        temp_f = round(temp_c * 9 / 5 + 32, 1)
        feels_f = round(feels_c * 9 / 5 + 32, 1)
        humidity = humidities[safe_hour] if len(humidities) > safe_hour else 50
        wind_kmh = winds[safe_hour] if len(winds) > safe_hour else 12.0
        precip_prob = precips[safe_hour] if len(precips) > safe_hour else 0

        if temp_c <= 0:
            thermal_regime = "Freezing Winter Load Spike"
        elif temp_c < 12:
            thermal_regime = "Cold Space-Heating Demand"
        elif temp_c < 24:
            thermal_regime = "Mild / Baseline Load"
        else:
            thermal_regime = "Warm Air Conditioning Cooling Surge"

        day_temps = temps[:24] if temps else [temp_c]

        return {
            "status": "success",
            "region": "PJM East (Hourly Meteorological Forecast)",
            "target_date": date_str,
            "target_hour": f"{safe_hour:02d}:00",
            "forecast_days": safe_days,
            "temperature_celsius": temp_c,
            "temperature_fahrenheit": temp_f,
            "feels_like_celsius": feels_c,
            "feels_like_fahrenheit": feels_f,
            "relative_humidity_percent": humidity,
            "wind_speed_kmh": wind_kmh,
            "precipitation_probability_percent": precip_prob,
            "thermal_regime": thermal_regime,
            "daily_min_celsius": min(day_temps),
            "daily_max_celsius": max(day_temps),
            "daily_min_fahrenheit": round(min(day_temps) * 9 / 5 + 32, 1),
            "daily_max_fahrenheit": round(max(day_temps) * 9 / 5 + 32, 1),
        }
    except Exception as e:
        logger.warning(f"Weather forecast lookup fallback triggered: {e}")
        return {
            "status": "fallback",
            "region": "PJM East (Forecast Baseline Estimate)",
            "target_date": date_str,
            "target_hour": f"{safe_hour:02d}:00",
            "forecast_days": safe_days,
            "temperature_celsius": 18.0,
            "temperature_fahrenheit": 64.4,
            "feels_like_celsius": 18.0,
            "feels_like_fahrenheit": 64.4,
            "relative_humidity_percent": 50.0,
            "wind_speed_kmh": 12.0,
            "precipitation_probability_percent": 15,
            "thermal_regime": "Mild / Baseline Load",
            "daily_min_celsius": 14.0,
            "daily_max_celsius": 22.0,
            "daily_min_fahrenheit": 57.2,
            "daily_max_fahrenheit": 71.6,
        }


def extract_text_from_content(content) -> str:
    """Extracts clean markdown text from LangChain content block structures."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_blocks = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text" and "text" in block:
                    text_blocks.append(block["text"])
                elif "text" in block and block.get("type") != "reasoning_content":
                    text_blocks.append(block["text"])
            elif isinstance(block, str):
                text_blocks.append(block)
        return "\n".join(text_blocks).strip()
    return str(content)


# Autonomous Bedrock & LangChain Tools Registration
BEDROCK_TOOLS_CONFIG = {
    "tools": [
        {
            "toolSpec": {
                "name": "get_forecast_weather",
                "description": "Fetches forward-looking hourly meteorological forecast data (up to 16 days ahead) for PJM East (or specified coordinates) using Open-Meteo High-Resolution Forecast API. Used for upcoming dates, tomorrow's conditions, and day-ahead load projection correlations.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "date_str": {"type": "string", "description": "Target future forecast date (YYYY-MM-DD). Defaults to tomorrow if omitted."},
                            "hour": {"type": "integer", "description": "Operating hour of the day (0-23) for hourly weather resolution."},
                            "days": {"type": "integer", "description": "Number of forecast days forward (1-16, default: 1)."},
                            "lat": {"type": "number", "description": "Latitude (default: 39.95 for Philadelphia / PJM East)."},
                            "lon": {"type": "number", "description": "Longitude (default: -75.16 for Philadelphia / PJM East)."}
                        }
                    }
                }
            }
        },
        {
            "toolSpec": {
                "name": "get_historical_weather",
                "description": "Fetches historical meteorological archive data for a specific calendar date and operating hour in PJM East.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "year": {"type": "integer", "description": "Calendar year, e.g. 2016"},
                            "month": {"type": "integer", "description": "Month of the year (1-12)"},
                            "dayofyear": {"type": "integer", "description": "Day of the year (1-366)"},
                            "hour": {"type": "integer", "description": "Operating hour (0-23)"},
                            "date_str": {"type": "string", "description": "Optional YYYY-MM-DD date string"},
                            "lat": {"type": "number", "description": "Latitude (default: 39.95)"},
                            "lon": {"type": "number", "description": "Longitude (default: -75.16)"}
                        }
                    }
                }
            }
        },
        {
            "toolSpec": {
                "name": "get_live_weather",
                "description": "Fetches real-time live meteorological telemetry for grid coordinates (default: PJM East / Philadelphia, PA).",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "lat": {"type": "number", "description": "Latitude (default: 39.95)"},
                            "lon": {"type": "number", "description": "Longitude (default: -75.16)"}
                        }
                    }
                }
            }
        }
    ]
}

COPILOT_TOOL_FUNCTIONS = {
    "get_forecast_weather": get_forecast_weather,
    "forecast": get_forecast_weather,
    "Forecast": get_forecast_weather,
    "forecast_weather": get_forecast_weather,
    "get_historical_weather": get_historical_weather,
    "get_live_weather": get_live_weather,
}

try:
    COPILOT_TOOLS = [
        tool(get_forecast_weather),
        tool(get_historical_weather),
        tool(get_live_weather)
    ]
    COPILOT_TOOLS_MAP = {t.name: t for t in COPILOT_TOOLS}
except Exception as e:
    COPILOT_TOOLS = []
    COPILOT_TOOLS_MAP = {}


# 3. Initialize FastAPI App
app = FastAPI(title="PJME Serverless Energy API")

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    custom_messages = []
    for err in exc.errors():
        loc = err.get("loc", [])
        field = loc[-1] if loc else "field"
        if field == "hour":
            custom_messages.append("Hour: enter between 0 and 23")
        elif field == "dayofweek":
            custom_messages.append("Day of week: enter between 0 (Monday) and 6 (Sunday)")
        elif field == "quarter":
            custom_messages.append("Quarter: enter between 1 and 4")
        elif field == "month":
            custom_messages.append("Month: enter between 1 and 12")
        elif field == "dayofyear":
            custom_messages.append("Day of year: enter between 1 and 366")
        elif field == "is_weekend":
            custom_messages.append("Is weekend: enter 0 (weekday) or 1 (weekend)")
        else:
            custom_messages.append(f"{field}: {err.get('msg')}")

    return JSONResponse(
        status_code=422,
        content={"status": "error", "message": " | ".join(custom_messages), "detail": custom_messages}
    )

MODEL_PATH = os.path.join(os.path.dirname(__file__), "models/best_model.pkl")
model = joblib.load(MODEL_PATH) if os.path.exists(MODEL_PATH) else None


# 4. Data Validation Schemas (Pydantic)
class EnergyPredictionRequest(BaseModel):
    hour: int = Field(..., ge=0, le=23, description="Hour of the day (0-23)")
    dayofweek: int = Field(..., ge=0, le=6, description="Day of the week (0-6)")
    quarter: int = Field(..., ge=1, le=4, description="Quarter of the year (1-4)")
    month: int = Field(..., ge=1, le=12, description="Month of the year (1-12)")
    year: int = Field(..., description="Calendar year (e.g., 2016)")
    dayofyear: int = Field(..., ge=1, le=366, description="Day of the year (1-366)")
    is_weekend: int = Field(..., ge=0, le=1, description="1 if weekend else 0")

    lag_1_hour: float = Field(..., description="Energy consumption 1 hour before (KWH)")
    lag_24_hours: float = Field(..., description="Energy consumption 24 hours before (KWH)")
    lag_7_days: float = Field(..., description="Energy consumption 7 days before (KWH)")
    
    rolling_mean_24h: float = Field(..., description="Rolling mean energy consumption over last 24 hours (KWH)")
    rolling_mean_7d: float = Field(..., description="Rolling mean energy consumption over last 7 days (KWH)")

class CopilotRequest(BaseModel):
    chat_history: list[dict[str, Any]]
    current_prediction: float
    hour: int
    dayofweek: int
    quarter: int
    month: int
    year: int
    dayofyear: int
    is_weekend: int
    lag_1_hour: float
    lag_24_hours: float
    lag_7_days: float
    rolling_mean_24h: float
    rolling_mean_7d: float
    stream: bool = False


# 5. API Endpoints
@app.get("/")
def read_root():
    return {
        "service": "PJME Grid Load Forecasting Service",
        "status": "healthy",
        "model_loaded": model is not None,
        "region": "ap-south-1"
    }

@app.get("/weather")
def weather_endpoint(lat: float = 39.95, lon: float = -75.16):
    """Direct endpoint to verify get_live_weather tool telemetry."""
    return get_live_weather(lat, lon)

@app.get("/weather/historical")
def historical_weather_endpoint(year: int = 2016, month: int = 1, dayofyear: int = 4, hour: int = 18, lat: float = 39.95, lon: float = -75.16):
    """Direct endpoint to verify get_historical_weather tool telemetry parsed from columns."""
    return get_historical_weather(year=year, month=month, dayofyear=dayofyear, hour=hour, lat=lat, lon=lon)

@app.get("/weather/forecast")
def forecast_weather_endpoint(date_str: str = None, hour: int = 12, days: int = 1, lat: float = 39.95, lon: float = -75.16):
    """Direct endpoint to verify get_forecast_weather tool telemetry."""
    return get_forecast_weather(date_str=date_str, hour=hour, days=days, lat=lat, lon=lon)

@app.post("/predict")
def predict_energy(payload: EnergyPredictionRequest, request: Request):
    try:
        input_data = payload.model_dump()
        FEATURES = ['hour', 'dayofweek', 'quarter', 'month', 'year', 'dayofyear', 
                    'is_weekend', 'lag_1_hour', 'lag_24_hours', 'lag_7_days', 
                    'rolling_mean_24h', 'rolling_mean_7d']
                    
        input_df = pd.DataFrame([input_data])[FEATURES]
        prediction = model.predict(input_df)[0]

        # Log telemetry directly into CloudWatch
        logger.info(f"LAMBDA_INFERENCE_SUCCESS | Predicted_Load: {round(float(prediction), 2)} MW")

        return {
            "prediction_mw": round(float(prediction), 2),
            "status": "success"
        }
    except Exception as e:
        logger.error(f"LAMBDA_INFERENCE_CRASH | Error: {str(e)}")
        return {"status": "error", "message": str(e)}


def build_bedrock_messages(chat_history: list[dict[str, Any]], active_forecast_block: str) -> list[dict[str, Any]]:
    """Sanitizes and normalizes conversation turns for AWS Bedrock Converse alternating roles."""
    raw_messages = []
    for msg in chat_history:
        role = msg.get("role")
        text = (msg.get("text") or msg.get("content") or "").strip()
        if not text or role not in ("user", "assistant"):
            continue
        raw_messages.append({"role": role, "text": text})

    # Bedrock requires conversations to start with a user message
    while raw_messages and raw_messages[0]["role"] != "user":
        raw_messages.pop(0)

    if not raw_messages:
        return []

    # Merge consecutive turns of identical roles (prevents Bedrock turn validation exceptions)
    consolidated = []
    for m in raw_messages:
        if consolidated and consolidated[-1]["role"] == m["role"]:
            consolidated[-1]["text"] += "\n\n" + m["text"]
        else:
            consolidated.append(dict(m))

    # Ensure the final turn is a user prompt
    if consolidated[-1]["role"] != "user":
        consolidated.append({"role": "user", "text": "Analyze active forecast telemetry."})

    # Prepend active forecast context block to the latest human query
    consolidated[-1]["text"] = f"{active_forecast_block}\nOperator Query: {consolidated[-1]['text']}"

    return [
        {"role": m["role"], "content": [{"text": m["text"]}]}
        for m in consolidated
    ]


@app.post("/copilot")
def energy_copilot(data: CopilotRequest):
    # Dynamically derive calendar date from active user input columns
    try:
        target_date = datetime.date(data.year, 1, 1) + datetime.timedelta(days=max(0, data.dayofyear - 1))
        date_str = target_date.strftime("%Y-%m-%d")
    except Exception:
        date_str = f"{data.year:04d}-{max(1, min(12, data.month)):02d}-01"

    active_date_meta = {
        "year": data.year,
        "month": data.month,
        "dayofyear": data.dayofyear,
        "hour": data.hour,
        "date_str": date_str,
    }

    system_prompt = f"""You are an expert Power Grid AI Agent analyzing regional energy load metrics for PJM East (PJME).

1. Regional Grid Context (Parsed from Active Dashboard Columns):
- Calendar Year: {data.year}
- Month of Year: {data.month}
- Day of Year: {data.dayofyear} (Parsed Calendar Date: {date_str})
- Operating Hour: {data.hour}:00
- Day of Week Index: {data.dayofweek} (0=Monday, 6=Sunday)
- Quarter: {data.quarter}
- Is Weekend: {'Yes' if data.is_weekend == 1 else 'No'}
- Machine Learning Demand Forecast: {data.current_prediction:.2f} MW
- Historical Lags: 1h ago: {data.lag_1_hour:.2f} MW | 24h ago: {data.lag_24_hours:.2f} MW | 7d ago: {data.lag_7_days:.2f} MW
- Statistical Trends: Rolling 24h: {data.rolling_mean_24h:.2f} MW | Rolling 7d: {data.rolling_mean_7d:.2f} MW

2. Autonomous Tool Directives:
- You have access to three meteorological telemetry tools:
  * get_forecast_weather: forward-looking hourly weather forecast telemetry (up to 16 days ahead) for upcoming dates, tomorrow's conditions, or day-ahead dispatch planning.
  * get_live_weather: real-time live grid weather telemetry for current conditions.
  * get_historical_weather: historical archive weather telemetry corresponding to past dataset benchmark dates.
- Autonomously select and execute only the tools necessary to fulfill the operator's prompt.
- If the operator asks about tomorrow, future weather, or day-ahead projections, invoke get_forecast_weather.
- If the operator instructs not to use live weather, or only to provide historical data, respect their directive and invoke only the appropriate tool.
- If no external meteorological data is needed, do not call any tools and respond directly.

3. Presentation & Recommendation Standards:
- Present numerical comparisons and weather telemetry in clean, structured Markdown tables.
- Analyze the operational implications (e.g. heating/cooling degree days, thermal regime, peaking reserves).
- MANDATORY FINISH: You MUST ALWAYS conclude your response with a bold header:
  **Actionable Operational Recommendation:**
  followed by concrete dispatch actions (MW curtailment, ramping, or reserve margin adjustments).
"""

    active_forecast_block = (
        f"[ACTIVE FORECAST JOB TELEMETRY]:\n"
        f"- Target Calendar Date: {date_str} (Year: {data.year}, Month: {data.month}, Day of Year: {data.dayofyear})\n"
        f"- Target Operating Hour: {data.hour:02d}:00\n"
        f"- Machine Learning Demand Forecast: {data.current_prediction:.2f} MW\n"
        f"- Day of Week Index: {data.dayofweek} (Weekend: {'Yes' if data.is_weekend == 1 else 'No'})\n"
        f"- Historical Lags: 1h ago: {data.lag_1_hour:.2f} MW | 24h ago: {data.lag_24_hours:.2f} MW | 7d ago: {data.lag_7_days:.2f} MW\n"
        f"- Trends: Rolling 24h: {data.rolling_mean_24h:.2f} MW | Rolling 7d: {data.rolling_mean_7d:.2f} MW\n"
        f"NOTE: The operator is analyzing THIS active forecast job. Disregard any prior dates or numbers from earlier conversation turns.\n"
    )

    bedrock_messages = build_bedrock_messages(data.chat_history, active_forecast_block)
    if not bedrock_messages:
        return {"status": "error", "message": "No valid messages in chat history."}

    max_turns = 4
    current_messages = list(bedrock_messages)
    executed_tool_calls = []
    ai_response = ""

    try:
        while max_turns > 0:
            max_turns -= 1
            resp = bedrock_client.converse(
                modelId=BEDROCK_MODEL_ID,
                messages=current_messages,
                system=[{"text": system_prompt}],
                toolConfig=BEDROCK_TOOLS_CONFIG,
                inferenceConfig={"maxTokens": 2048, "temperature": 0.2}
            )

            stop_reason = resp.get("stopReason")
            output_msg = resp.get("output", {}).get("message", {})
            content_blocks = output_msg.get("content", [])

            if stop_reason == "tool_use":
                current_messages.append({"role": "assistant", "content": content_blocks})
                tool_results = []
                for blk in content_blocks:
                    if "toolUse" in blk:
                        tu = blk["toolUse"]
                        tu_id = tu.get("toolUseId")
                        t_name = tu.get("name")
                        t_args = tu.get("input") or {}

                        if t_name == "get_historical_weather":
                            t_args.setdefault("year", active_date_meta.get("year"))
                            t_args.setdefault("month", active_date_meta.get("month"))
                            t_args.setdefault("dayofyear", active_date_meta.get("dayofyear"))
                            t_args.setdefault("hour", active_date_meta.get("hour"))
                            t_args.setdefault("date_str", active_date_meta.get("date_str"))
                        elif t_name in ("get_forecast_weather", "forecast", "Forecast", "forecast_weather"):
                            t_args.setdefault("hour", active_date_meta.get("hour", 12))

                        fn = COPILOT_TOOL_FUNCTIONS.get(t_name)
                        if fn:
                            try:
                                output = fn(**t_args)
                            except Exception as te:
                                output = {"status": "error", "message": str(te)}
                        else:
                            output = {"status": "error", "message": f"Tool '{t_name}' not found."}

                        executed_tool_calls.append({
                            "name": t_name,
                            "input": t_args,
                            "output": output
                        })

                        tool_results.append({
                            "toolResult": {
                                "toolUseId": tu_id,
                                "content": [{"json": output}],
                                "status": "success" if output.get("status") != "error" else "error"
                            }
                        })

                current_messages.append({"role": "user", "content": tool_results})
            else:
                for blk in content_blocks:
                    if "text" in blk:
                        ai_response += blk["text"]
                break

        logger.info(f"LAMBDA_COPILOT_SUCCESS | Agent completed ({len(executed_tool_calls)} tools invoked)")

        return {
            "response": ai_response,
            "status": "success",
            "tool_calls": executed_tool_calls
        }

    except Exception as e:
        logger.error(f"LAMBDA_COPILOT_CRASH | {e}")
        return {"status": "error", "message": f"Grid Copilot operational glitch: {str(e)}"}


# 6. THE SERVERLESS BRIDGE HANDLER
handler = Mangum(app)