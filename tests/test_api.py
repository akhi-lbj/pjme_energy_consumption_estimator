from fastapi.testclient import TestClient
from src.main import app

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