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


# 2. Live Weather Tool (Open-Meteo API for PJM East Region)
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
            "region": "PJM East (Philadelphia Metropolitan Zone)",
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
    year: int = Field(..., description="Calendar year (e.g., 2026)")
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
    # Fetch live meteorological telemetry for PJM East (Tool: get_live_weather)
    weather = get_live_weather()

    # System prompt provides rich operational and meteorological context for the LLM
    system_prompt = f"""
    You are an expert Power Grid AI Co-Pilot analyzing regional energy load metrics for PJM East (PJME).
    
    Live Grid Telemetry:
    - Current Machine Learning Demand Forecast: {data.current_prediction:.2f} MW
    - Operating Hour: {data.hour}:00
    - Day of Week index: {data.dayofweek} (0=Monday, 6=Sunday)
    - Quarter: {data.quarter}
    - Month of Year: {data.month}
    - Calendar Year: {data.year}
    - Day of Year: {data.dayofyear}
    - Is Weekend: {'Yes' if data.is_weekend == 1 else 'No'}
    - Lag Load (1 Hour Ago): {data.lag_1_hour:.2f} MW
    - Lag Load (24 Hours Ago): {data.lag_24_hours:.2f} MW
    - Lag Load (7 Days Ago): {data.lag_7_days:.2f} MW
    - Rolling Mean (24 Hours): {data.rolling_mean_24h:.2f} MW
    - Rolling Mean (7 Days): {data.rolling_mean_7d:.2f} MW

    Live Meteorological Telemetry (Tool: get_live_weather):
    - Substation Region: {weather['region']} (Lat: {weather['latitude']}, Lon: {weather['longitude']})
    - Real-Time Ambient Temperature: {weather['temperature_celsius']}°C ({weather['temperature_fahrenheit']}°F)
    - Heat Index / Feels Like: {weather['feels_like_celsius']}°C ({weather['feels_like_fahrenheit']}°F)
    - Relative Humidity: {weather['relative_humidity_percent']}%
    - Wind Speed: {weather['wind_speed_kmh']} km/h
    
    Operational Guidelines:
    - Correlate meteorological conditions with grid load:
      * High temperatures (>30°C / 86°F) drive heavy air conditioning cooling load surges.
      * Extreme cold (<5°C / 41°F) drives severe resistive and heat-pump heating spikes.
      * High humidity amplifies perceived heat index and cooling compressor duty cycles.
    - Provide concise, technically rigorous grid operational insights responding directly to the user's query.
    - Contextualize the live numbers, weather readings, and historical lags naturally.
    - Use clean Markdown formatting: bold highlights (**keyword**), bullet points, and Markdown tables when comparing metrics or scenarios.
    - Always finish your answer with a complete thought and a bolded actionable operational recommendation. Never trail off or leave thoughts incomplete.
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

        # Invocation using Google Gemma 3 12B in ap-south-1
        response = bedrock_client.converse(
            modelId="google.gemma-3-12b-it",
            messages=bedrock_messages,
            system=[{"text": system_prompt}],
            inferenceConfig={"maxTokens": 1024, "temperature": 0.3}
        )
        
        stop_reason = response.get("stopReason", "end_turn")
        ai_response = response["output"]["message"]["content"][0]["text"]
        logger.info(f"LAMBDA_COPILOT_SUCCESS | Bedrock responded | stopReason={stop_reason}")

        # Active tool call telemetry for frontend inspector
        tool_calls = [
            {
                "name": "get_live_weather",
                "input": {
                    "latitude": weather.get("latitude", 39.95),
                    "longitude": weather.get("longitude", -75.16)
                },
                "output": weather
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