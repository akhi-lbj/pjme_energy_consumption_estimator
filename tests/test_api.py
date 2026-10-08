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

def test_copilot_streaming_sse():
    from app import app as serverless_app
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
            "rolling_mean_7d": 24100.0,
            "stream": True
        }
        with client.stream("POST", "/copilot", json=payload) as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")
            lines = [line for line in response.iter_lines() if line]
            assert any("data: " in line for line in lines)
            assert any('"type": "done"' in line for line in lines)

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