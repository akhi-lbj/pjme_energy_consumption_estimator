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


def simulate_what_if_scenario(
    temp_delta_f: float = 0.0,
    industrial_curtailment_mw: float = 0.0,
    baseline_prediction_mw: float = 30000.0,
    operating_generation_capacity_mw: float = 35000.0
) -> dict:
    """
    Simulates power grid contingency scenarios by evaluating temperature variations (temp_delta_f)
    and industrial load curtailment (industrial_curtailment_mw) against baseline forecast and generation capacity.
    """
    thermal_load_impact_mw = round(baseline_prediction_mw * (temp_delta_f * 0.018), 2)
    curtailment_mw = round(float(industrial_curtailment_mw), 2)
    adjusted_prediction_mw = round(baseline_prediction_mw + thermal_load_impact_mw - curtailment_mw, 2)
    
    contingency_reserve_mw = round(operating_generation_capacity_mw - adjusted_prediction_mw, 2)
    reserve_margin_pct = round((contingency_reserve_mw / operating_generation_capacity_mw) * 100, 2)
    
    if reserve_margin_pct < 10.0:
        grid_status = "CRITICAL - Immediate Peaker Activation Required"
    elif reserve_margin_pct < 15.0:
        grid_status = "STRESSED - Spinning Reserve Alert"
    else:
        grid_status = "NOMINAL - Operating Reserve Margin Adequate"

    return {
        "status": "success",
        "simulation_parameters": {
            "temperature_delta_fahrenheit": temp_delta_f,
            "industrial_curtailment_mw": curtailment_mw,
            "baseline_forecast_mw": baseline_prediction_mw,
            "operating_generation_capacity_mw": operating_generation_capacity_mw
        },
        "projected_metrics": {
            "thermal_load_impact_mw": thermal_load_impact_mw,
            "curtailment_reduction_mw": curtailment_mw,
            "simulated_demand_mw": adjusted_prediction_mw,
            "contingency_reserve_mw": contingency_reserve_mw,
            "reserve_margin_percent": reserve_margin_pct,
            "grid_reliability_status": grid_status
        }
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


# Autonomous LangChain Tools Registration
try:
    COPILOT_TOOLS = [
        tool(get_historical_weather),
        tool(get_live_weather),
        tool(simulate_what_if_scenario)
    ]
    COPILOT_TOOLS_MAP = {t.name: t for t in COPILOT_TOOLS}
except Exception as e:
    COPILOT_TOOLS = []
    COPILOT_TOOLS_MAP = {}


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


@app.post("/simulate")
def simulate_endpoint(
    temp_delta_f: float = 0.0,
    industrial_curtailment_mw: float = 0.0,
    baseline_prediction_mw: float = 30000.0,
    operating_generation_capacity_mw: float = 35000.0
):
    """Direct API endpoint for power grid contingency scenario simulations."""
    return simulate_what_if_scenario(
        temp_delta_f=temp_delta_f,
        industrial_curtailment_mw=industrial_curtailment_mw,
        baseline_prediction_mw=baseline_prediction_mw,
        operating_generation_capacity_mw=operating_generation_capacity_mw
    )


@app.post("/copilot")
async def energy_copilot(data: CopilotRequest):
    # Dynamically derive calendar date from active user input columns
    try:
        target_date = datetime.date(data.year, 1, 1) + datetime.timedelta(days=max(0, data.dayofyear - 1))
        date_str = target_date.strftime("%Y-%m-%d")
    except Exception:
        date_str = f"{data.year:04d}-{max(1, min(12, data.month)):02d}-01"

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
- You have access to tools for historical weather telemetry (get_historical_weather), live weather telemetry (get_live_weather), and what-if grid contingency simulation (simulate_what_if_scenario).
- Autonomously select and execute only the tools necessary to fulfill the operator's prompt.
- If the operator instructs not to use live weather, or only to provide historical data, respect their directive and invoke only the appropriate tool.
- If the user asks for what-if scenarios (e.g., temperature deviations, industrial load curtailment), invoke simulate_what_if_scenario.
- If no external data or simulation is needed, do not call any tools and respond directly.

3. Presentation & Recommendation Standards:
- Present numerical comparisons and weather telemetry in clean, structured Markdown tables.
- Analyze the operational implications (e.g. heating/cooling degree days, thermal regime, peaking reserves).
- MANDATORY FINISH: You MUST ALWAYS conclude your response with a bold header:
  **Actionable Operational Recommendation:**
  followed by concrete dispatch actions (MW curtailment, ramping, or reserve margin adjustments).
"""

    try:
        # Build LangChain message chain
        langchain_messages = [SystemMessage(content=system_prompt)]
        for msg in data.chat_history:
            role = msg.get("role")
            text = msg.get("text") or msg.get("content") or ""
            if not text or role not in ("user", "assistant"):
                continue
            if role == "user":
                langchain_messages.append(HumanMessage(content=text))
            elif role == "assistant":
                langchain_messages.append(AIMessage(content=text))

        # Bedrock Converse requires conversations to lead with human/user messages
        while len(langchain_messages) > 1 and isinstance(langchain_messages[1], AIMessage):
            langchain_messages.pop(1)

        if not any(isinstance(m, HumanMessage) for m in langchain_messages):
            return {"status": "error", "message": "No valid messages in chat history."}

        executed_tool_calls = []
        ai_response = ""

        # Primary Engine: LangChain with BedrockConverse autonomous tool routing
        if llm is not None and COPILOT_TOOLS:
            llm_with_tools = llm.bind_tools(COPILOT_TOOLS)
            current_messages = list(langchain_messages)
            max_turns = 3

            while max_turns > 0:
                max_turns -= 1
                ai_msg = llm_with_tools.invoke(current_messages)

                if not ai_msg.tool_calls:
                    ai_response = extract_text_from_content(ai_msg.content)
                    break

                current_messages.append(ai_msg)
                tool_messages = []
                for tc in ai_msg.tool_calls:
                    t_name = tc.get("name")
                    t_args = tc.get("args") or {}

                    # Inject defaults if omitted by model
                    if t_name == "get_historical_weather":
                        t_args.setdefault("year", data.year)
                        t_args.setdefault("month", data.month)
                        t_args.setdefault("dayofyear", data.dayofyear)
                        t_args.setdefault("hour", data.hour)
                    elif t_name == "simulate_what_if_scenario":
                        t_args.setdefault("baseline_prediction_mw", data.current_prediction)

                    fn = COPILOT_TOOLS_MAP.get(t_name)
                    if fn:
                        try:
                            output = fn.invoke(t_args)
                        except Exception as te:
                            output = {"status": "error", "message": str(te)}
                    else:
                        output = {"status": "error", "message": f"Tool '{t_name}' not found."}

                    executed_tool_calls.append({
                        "name": t_name,
                        "input": t_args,
                        "output": output
                    })
                    tool_messages.append(ToolMessage(content=json.dumps(output), tool_call_id=tc["id"]))

                current_messages.extend(tool_messages)
            else:
                ai_response = extract_text_from_content(ai_msg.content)

            logger.info(f"LAMBDA_COPILOT_SUCCESS | Autonomous tool execution completed ({len(executed_tool_calls)} tools invoked)")

        else:
            # Fallback to direct boto3 converse if LangChain instance is unavailable
            bedrock_messages = [
                {"role": "user" if isinstance(m, HumanMessage) else "assistant",
                 "content": [{"text": str(m.content)}]}
                for m in langchain_messages if not isinstance(m, SystemMessage)
            ]
            boto_resp = bedrock_client.converse(
                modelId=BEDROCK_MODEL_ID,
                messages=bedrock_messages,
                system=[{"text": system_prompt}],
                inferenceConfig={"maxTokens": 2048, "temperature": 0.2}
            )
            ai_response = boto_resp["output"]["message"]["content"][0]["text"]
            logger.info("LAMBDA_COPILOT_SUCCESS | Direct Bedrock Converse responded")

        return {
            "response": ai_response,
            "status": "success",
            "tool_calls": executed_tool_calls
        }

    except Exception as e:
        logger.error(f"LAMBDA_COPILOT_CRASH | Error: {str(e)}")
        return {"status": "error", "message": f"Co-Pilot operational glitch: {str(e)}"}


# 6. THE SERVERLESS BRIDGE HANDLER
handler = Mangum(app)