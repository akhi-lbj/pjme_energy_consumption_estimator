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
def historical_weather_endpoint(year: int = 2016, month: int = 1, dayofyear: int = 4, hour: int = 18, lat: float = 39.95, lon: float = -75.16):
    """Direct endpoint to verify get_historical_weather tool telemetry parsed from columns."""
    return get_historical_weather(year=year, month=month, dayofyear=dayofyear, hour=hour, lat=lat, lon=lon)

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
    # Dynamically derive calendar date from active user input columns
    try:
        target_date = datetime.date(data.year, 1, 1) + datetime.timedelta(days=max(0, data.dayofyear - 1))
        date_str = target_date.strftime("%Y-%m-%d")
    except Exception:
        date_str = f"{data.year:04d}-{max(1, min(12, data.month)):02d}-01"

    # Automatically execute both live and historical weather tools using user input columns
    live_weather = get_live_weather()
    historical_weather = get_historical_weather(
        year=data.year,
        month=data.month,
        dayofyear=data.dayofyear,
        hour=data.hour,
        date_str=date_str
    )

    # System prompt provides rich operational and dual-meteorological context for the LLM
    system_prompt = f"""
    You are an expert Power Grid AI Co-Pilot analyzing regional energy load metrics for PJM East (PJME).
    
    1. Input Metric Matrix (Parsed from Active Dashboard Columns):
    - Calendar Year: {data.year}
    - Month of Year: {data.month}
    - Day of Year: {data.dayofyear} (Parsed Calendar Date: {date_str})
    - Operating Hour: {data.hour}:00
    - Day of Week Index: {data.dayofweek} (0=Monday, 6=Sunday)
    - Quarter: {data.quarter}
    - Is Weekend: {'Yes' if data.is_weekend == 1 else 'No'}
    - Machine Learning Forecast: {data.current_prediction:.2f} MW
    - Historical Lags: 1h ago: {data.lag_1_hour:.2f} MW | 24h ago: {data.lag_24_hours:.2f} MW | 7d ago: {data.lag_7_days:.2f} MW
    - Statistical Trends: Rolling 24h: {data.rolling_mean_24h:.2f} MW | Rolling 7d: {data.rolling_mean_7d:.2f} MW

    2. Historical Meteorological Context (Parsed from Columns -> Tool: get_historical_weather):
    - Target Timestamp: {historical_weather['derived_calendar_timestamp']}
    - Historical Ambient Temperature: {historical_weather['temperature_celsius']}°C ({historical_weather['temperature_fahrenheit']}°F)
    - Historical Feels Like: {historical_weather['feels_like_celsius']}°C ({historical_weather['feels_like_fahrenheit']}°F)
    - Historical Relative Humidity: {historical_weather['relative_humidity_percent']}%
    - Historical Wind Speed: {historical_weather['wind_speed_kmh']} km/h
    - Historical Thermal Regime: {historical_weather['thermal_regime']}

    3. Real-Time Live Meteorological Telemetry (Tool: get_live_weather):
    - Current Ambient Temperature: {live_weather['temperature_celsius']}°C ({live_weather['temperature_fahrenheit']}°F)
    - Current Heat Index / Feels Like: {live_weather['feels_like_celsius']}°C ({live_weather['feels_like_fahrenheit']}°F)
    - Current Relative Humidity: {live_weather['relative_humidity_percent']}%
    - Current Wind Speed: {live_weather['wind_speed_kmh']} km/h

    CRITICAL RESPONSE INSTRUCTIONS:
    - State clearly how you parsed the historical datetime ({date_str} at {data.hour}:00) directly from the user's input columns (Year: {data.year}, Month: {data.month}, Day of Year: {data.dayofyear}, Hour: {data.hour}).
    - Compare Historical Weather vs Live Weather in a clean Markdown table.
    - Explain the thermal variance: how the historical temperature on that date drove heating/cooling vs what live weather demands today.
    - DO NOT generate tool code, pseudo-code, or claim you are 'about to retrieve data' (all data is already retrieved above).
    - MANDATORY FINISH: You MUST ALWAYS finish your response with a complete, fully formed bold header:
      **Actionable Operational Recommendation:**
      followed by specific dispatch instructions (MW curtailment, ramping, or reserve margin).
      NEVER stop mid-sentence or leave thoughts incomplete.
    """
    
    try:
        # Format incoming history for Bedrock converse API
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
            
        while bedrock_messages and bedrock_messages[0]["role"] == "assistant":
            bedrock_messages.pop(0)
            
        if not bedrock_messages:
            return {"status": "error", "message": "No valid messages in chat history."}

        # Invocation using Google Gemma 3 12B in ap-south-1 with 2048 token limit
        response = bedrock_client.converse(
            modelId="google.gemma-3-12b-it",
            messages=bedrock_messages,
            system=[{"text": system_prompt}],
            inferenceConfig={"maxTokens": 2048, "temperature": 0.3}
        )
        
        stop_reason = response.get("stopReason", "end_turn")
        ai_response = response["output"]["message"]["content"][0]["text"]
        logger.info(f"LAMBDA_COPILOT_SUCCESS | Bedrock responded | stopReason={stop_reason}")

        # Active tool call telemetry for frontend inspector (displaying user-parsed column values)
        tool_calls = [
            {
                "name": "get_live_weather",
                "input": {
                    "monitored_region": "PJM East (Philadelphia Centroid)",
                    "latitude": 39.95,
                    "longitude": -75.16
                },
                "output": live_weather
            },
            {
                "name": "get_historical_weather",
                "input": {
                    "parsed_from_user_columns": {
                        "year": data.year,
                        "month": data.month,
                        "dayofyear": data.dayofyear,
                        "hour": data.hour
                    },
                    "derived_target_date": date_str,
                    "target_hour": f"{data.hour}:00",
                    "latitude": 39.95,
                    "longitude": -75.16
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