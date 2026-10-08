from fastapi.testclient import TestClient
from src.main import app
from app import get_live_weather, get_historical_weather

def test_predict_success():
    # 'with' forces FastAPI to trigger the lifespan startup logic cleanly before testing
    with TestClient(app) as client:
        payload = {
            "hour": 18,
            "dayofweek": 0,
            "quarter": 1,
            "month": 1,
            "year": 2016,
            "dayofyear": 4,
            "is_weekend": 0,
            "lag_1_hour": 31200.0,
            "lag_24_hours": 29800.0,
            "lag_7_days": 32100.0,
            "rolling_mean_24h": 30500.0,
            "rolling_mean_7d": 31000.0
        }
        
        response = client.post("/predict", json=payload)
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "success"
        assert "prediction_mw" in data
        assert data["unit"] == "Megawatts (MW)"

def test_predict_missing_field():
    with TestClient(app) as client:
        incomplete_payload = {
            "hour": 18,
            "dayofweek": 0
        }
        
        response = client.post("/predict", json=incomplete_payload)
        assert response.status_code == 422

def test_live_weather_tool():
    weather = get_live_weather(39.95, -75.16)
    assert weather["status"] in ("success", "fallback")
    assert "temperature_celsius" in weather
    assert "temperature_fahrenheit" in weather
    assert "relative_humidity_percent" in weather

def test_historical_weather_tool():
    weather = get_historical_weather(date_str="2016-01-04", hour=18, lat=39.95, lon=-75.16)
    assert weather["status"] in ("success", "fallback")
    assert "temperature_celsius" in weather
    assert "temperature_fahrenheit" in weather
    assert "target_date" in weather

from unittest.mock import patch

def test_copilot_direct_response():
    from app import app as serverless_app
    mock_resp = {
        "stopReason": "end_turn",
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"text": "Hello, Power Grid! Operational recommendation: monitor load."}]
            }
        }
    }
    with patch("app.bedrock_client.converse", return_value=mock_resp):
        with TestClient(serverless_app) as client:
            payload = {
                "chat_history": [{"role": "user", "text": "Say hello in 3 words."}],
                "current_prediction": 25000.0,
                "hour": 14,
                "dayofweek": 2,
                "quarter": 1,
                "month": 1,
                "year": 2016,
                "dayofyear": 4,
                "is_weekend": 0,
                "lag_1_hour": 24000.0,
                "lag_24_hours": 24500.0,
                "lag_7_days": 23900.0,
                "rolling_mean_24h": 24200.0,
                "rolling_mean_7d": 24100.0
            }
            response = client.post("/copilot", json=payload)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert "Hello, Power Grid!" in data["response"]
            assert data["tool_calls"] == []

def test_copilot_tool_call():
    from app import app as serverless_app
    turn1_resp = {
        "stopReason": "tool_use",
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "toolUse": {
                            "toolUseId": "tu_1",
                            "name": "get_live_weather",
                            "input": {"lat": 39.95, "lon": -75.16}
                        }
                    }
                ]
            }
        }
    }
    turn2_resp = {
        "stopReason": "end_turn",
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"text": "Weather telemetry integrated. Load looks stable."}]
            }
        }
    }
    with patch("app.bedrock_client.converse", side_effect=[turn1_resp, turn2_resp]):
        with TestClient(serverless_app) as client:
            payload = {
                "chat_history": [{"role": "user", "text": "Check live weather."}],
                "current_prediction": 25000.0,
                "hour": 14,
                "dayofweek": 2,
                "quarter": 1,
                "month": 1,
                "year": 2016,
                "dayofyear": 4,
                "is_weekend": 0,
                "lag_1_hour": 24000.0,
                "lag_24_hours": 24500.0,
                "lag_7_days": 23900.0,
                "rolling_mean_24h": 24200.0,
                "rolling_mean_7d": 24100.0
            }
            response = client.post("/copilot", json=payload)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert len(data["tool_calls"]) == 1
            assert data["tool_calls"][0]["name"] == "get_live_weather"
            assert data["response"] == "Weather telemetry integrated. Load looks stable."

def test_copilot_empty_history():
    from app import app as serverless_app
    with TestClient(serverless_app) as client:
        payload = {
            "chat_history": [],
            "current_prediction": 25000.0,
            "hour": 14,
            "dayofweek": 2,
            "quarter": 1,
            "month": 1,
            "year": 2016,
            "dayofyear": 4,
            "is_weekend": 0,
            "lag_1_hour": 24000.0,
            "lag_24_hours": 24500.0,
            "lag_7_days": 23900.0,
            "rolling_mean_24h": 24200.0,
            "rolling_mean_7d": 24100.0,
            "stream": False
        }
        response = client.post("/copilot", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"