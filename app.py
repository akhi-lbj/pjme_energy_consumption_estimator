from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
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


# 2. Meteorological Tools (Open-Meteo Live & Historical Archive APIs)
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


def get_historical_weather(date_str: str = "2016-01-04", hour: int = 18, lat: float = 39.95, lon: float = -75.16) -> dict:
    """
    Fetches historical meteorological archive data for a specific date and hour (default: PJM East / Philadelphia, PA).
    API: Open-Meteo Historical Weather Archive API (1940-present, open-access, zero-key).
    Purpose: Compares historical temperature baselines against current weather to identify temperature-driven anomalies.
    """
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

        safe_hour = max(0, min(23, hour))
        temp_c = temps[safe_hour] if len(temps) > safe_hour else 1.0
        feels_c = feels[safe_hour] if len(feels) > safe_hour else temp_c
        temp_f = round(temp_c * 9 / 5 + 32, 1)
        feels_f = round(feels_c * 9 / 5 + 32, 1)
        humidity = humidities[safe_hour] if len(humidities) > safe_hour else 35
        wind_kmh = winds[safe_hour] if len(winds) > safe_hour else 15.0

        return {
            "status": "success",
            "region": "PJM East (Historical Weather Archive)",
            "target_date": date_str,
            "target_hour": f"{safe_hour}:00",
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
        logger.warning(f"Historical weather lookup fallback triggered: {e}")
        return {
            "status": "fallback",
            "region": "PJM East (Historical Baseline Estimate)",
            "target_date": date_str,
            "target_hour": f"{hour}:00",
            "latitude": lat,
            "longitude": lon,
            "temperature_celsius": 1.0,
            "temperature_fahrenheit": 33.8,
            "feels_like_celsius": 1.0,
            "feels_like_fahrenheit": 33.8,
            "relative_humidity_percent": 34.0,
            "wind_speed_kmh": 15.0
        }


# 3. Initialize FastAPI App
app = FastAPI(title="PJME Serverless Energy API")

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
    chat_history: list[dict[str, str]]
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
def historical_weather_endpoint(date: str = "2016-01-04", hour: int = 18, lat: float = 39.95, lon: float = -75.16):
    """Direct endpoint to verify get_historical_weather tool telemetry."""
    return get_historical_weather(date_str=date, hour=hour, lat=lat, lon=lon)

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


@app.post("/copilot")
async def energy_copilot(data: CopilotRequest):
    # Derive calendar date string from target telemetry matrix
    try:
        target_date = datetime.date(data.year, 1, 1) + datetime.timedelta(days=max(0, data.dayofyear - 1))
        date_str = target_date.strftime("%Y-%m-%d")
    except Exception:
        date_str = "2016-01-04"

    # Automatically execute both live and historical weather tools
    live_weather = get_live_weather()
    historical_weather = get_historical_weather(date_str=date_str, hour=data.hour)

    # System prompt provides rich operational and dual-meteorological context for the LLM
    system_prompt = f"""
    You are an expert Power Grid AI Co-Pilot analyzing regional energy load metrics for PJM East (PJME).
    
    Live Grid Telemetry:
    - Current Machine Learning Demand Forecast: {data.current_prediction:.2f} MW
    - Operating Hour: {data.hour}:00
    - Historical Target Date: {date_str} (Day of Year: {data.dayofyear}, Day of Week Index: {data.dayofweek}, Quarter: {data.quarter}, Month: {data.month})
    - Is Weekend: {'Yes' if data.is_weekend == 1 else 'No'}
    - Lag Load (1 Hour Ago): {data.lag_1_hour:.2f} MW
    - Lag Load (24 Hours Ago): {data.lag_24_hours:.2f} MW
    - Lag Load (7 Days Ago): {data.lag_7_days:.2f} MW
    - Rolling Mean (24 Hours): {data.rolling_mean_24h:.2f} MW
    - Rolling Mean (7 Days): {data.rolling_mean_7d:.2f} MW

    Meteorological Telemetry (Tools Executed Automatically):
    1. Historical Weather on Target Date ({date_str} at {data.hour}:00 via Tool: get_historical_weather):
       - Ambient Temperature: {historical_weather['temperature_celsius']}°C ({historical_weather['temperature_fahrenheit']}°F)
       - Feels Like: {historical_weather['feels_like_celsius']}°C ({historical_weather['feels_like_fahrenheit']}°F)
       - Relative Humidity: {historical_weather['relative_humidity_percent']}%
       - Wind Speed: {historical_weather['wind_speed_kmh']} km/h

    2. Real-Time Live Weather in PJM East Today (via Tool: get_live_weather):
       - Ambient Temperature: {live_weather['temperature_celsius']}°C ({live_weather['temperature_fahrenheit']}°F)
       - Heat Index / Feels Like: {live_weather['feels_like_celsius']}°C ({live_weather['feels_like_fahrenheit']}°F)
       - Relative Humidity: {live_weather['relative_humidity_percent']}%
       - Wind Speed: {live_weather['wind_speed_kmh']} km/h
    
    Operational Guidelines:
    - Synthesize all grid telemetry, historical weather, and live weather into a cohesive, professional analysis.
    - DO NOT output pseudo-code or state that you are retrieving tool data (the tools have already executed and their readings are provided above).
    - Compare historical weather vs live weather to explain the thermal driver behind current demand:
      * Cold winter conditions (<5°C / 41°F) create heavy heating load.
      * High summer heat (>30°C / 86°F) create severe air conditioning cooling spikes.
      * Large temperature differences explain why load might diverge from historical baselines.
    - Include a clean Markdown comparison table comparing Historical vs Current conditions.
    - MANDATORY REQUIREMENT: You MUST ALWAYS finish your response with a complete, fully formed '**Actionable Operational Recommendation:**' including specific Megawatt (MW) dispatch guidance (e.g. ramp up/down generation, dispatch peakers, or activate demand response). Never stop mid-thought or leave sentences incomplete.
    """
    
    try:
        # Format the incoming history into the structure Bedrock's converse API expects
        bedrock_messages = []
        for msg in data.chat_history:
            role = msg.get("role")
            text = msg.get("text") or msg.get("content") or ""
            if not text or role not in ("user", "assistant"):
                continue
            bedrock_messages.append({
                "role": role,
                "content": [{"text": text}]
            })
            
        # Bedrock converse API requires the first message to be from the 'user'
        while bedrock_messages and bedrock_messages[0]["role"] == "assistant":
            bedrock_messages.pop(0)
            
        if not bedrock_messages:
            return {"status": "error", "message": "No valid messages in chat history."}

        # Invocation using Google Gemma 3 12B in ap-south-1 with expanded maxTokens
        response = bedrock_client.converse(
            modelId="google.gemma-3-12b-it",
            messages=bedrock_messages,
            system=[{"text": system_prompt}],
            inferenceConfig={"maxTokens": 2048, "temperature": 0.3}
        )
        
        stop_reason = response.get("stopReason", "end_turn")
        ai_response = response["output"]["message"]["content"][0]["text"]
        logger.info(f"LAMBDA_COPILOT_SUCCESS | Bedrock responded | stopReason={stop_reason}")

        # Active tool call telemetry for frontend inspector (both live & historical)
        tool_calls = [
            {
                "name": "get_live_weather",
                "input": {
                    "latitude": live_weather.get("latitude", 39.95),
                    "longitude": live_weather.get("longitude", -75.16)
                },
                "output": live_weather
            },
            {
                "name": "get_historical_weather",
                "input": {
                    "date": date_str,
                    "hour": data.hour,
                    "latitude": historical_weather.get("latitude", 39.95),
                    "longitude": historical_weather.get("longitude", -75.16)
                },
                "output": historical_weather
            }
        ]

        return {
            "response": ai_response,
            "status": "success",
            "tool_calls": tool_calls
        }
        
    except Exception as e:
        logger.error(f"LAMBDA_COPILOT_CRASH | Error: {str(e)}")
        return {"status": "error", "message": f"Co-Pilot operational glitch: {str(e)}"}


# 6. THE SERVERLESS BRIDGE HANDLER
handler = Mangum(app)