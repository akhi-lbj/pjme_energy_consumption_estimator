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

# NEW: Initialize Bedrock Runtime client in ap-south-1
try:
    bedrock_client = boto3.client("bedrock-runtime", region_name="ap-south-1")
except Exception as e:
    logger.warning(f"Bedrock runtime binding skipped: {e}")


# 2. Initialize FastAPI App
app = FastAPI(title="PJME Serverless Energy API")

# (Optional CORS middleware setup left commented as per your original file structure)
# app.add_middleware(
#    CORSMiddleware,
#    allow_origins=["*"], 
#    allow_credentials=True,
#    allow_methods=["*"],
#    allow_headers=["*"],)

MODEL_PATH = os.path.join(os.path.dirname(__file__), "models/best_model.pkl")
model = joblib.load(MODEL_PATH) if os.path.exists(MODEL_PATH) else None


# 3. Data Validation Schemas (Pydantic)
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

# NEW: Copilot request data schema
class CopilotRequest(BaseModel):
    chat_history: list[dict[str, str]]  # Passing the continuous React state array
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

# 4. API Endpoints
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


# NEW: Version 4 AI Copilot Endpoint using Amazon Bedrock Cross-Region Profiles
@app.post("/copilot")
async def energy_copilot(data: CopilotRequest):
    # System prompt provides rich operational context for the LLM
    system_prompt = f"""
    You are an expert Power Grid AI Co-Pilot analyzing regional energy load metrics.
    The current live system metrics from the dashboard are:
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
    
    Guidelines:
    - Provide concise, technically rigorous grid operational insights responding directly to the user's query.
    - Contextualize the live numbers and historical lags naturally.
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

        # Cross-region inference profile ID for Claude / Gemma called from ap-south-1
        response = bedrock_client.converse(
            modelId="google.gemma-3-4b-it",
            messages=bedrock_messages,
            system=[{"text": system_prompt}],
            inferenceConfig={"maxTokens": 1024, "temperature": 0.3}
        )
        
        stop_reason = response.get("stopReason", "end_turn")
        ai_response = response["output"]["message"]["content"][0]["text"]
        logger.info(f"LAMBDA_COPILOT_SUCCESS | Bedrock responded | stopReason={stop_reason}")
        return {"response": ai_response, "status": "success"}
        
    except Exception as e:
        logger.error(f"LAMBDA_COPILOT_CRASH | Error: {str(e)}")
        return {"status": "error", "message": f"Co-Pilot operational glitch: {str(e)}"}


# 5. THE SERVERLESS BRIDGE HANDLER
handler = Mangum(app)