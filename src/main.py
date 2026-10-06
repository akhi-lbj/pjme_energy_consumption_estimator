from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
import joblib
import pandas as pd
import os
from src.schemas import EnergyPredictionRequest

# 1. Define the exact path to your saved model artifact
MODEL_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "../models/best_model.pkl"))

# Global dictionary/holder to keep state clean across async lifespans
ml_models = {}

# 2. Define the modern Lifespan Context Manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    # This runs exactly when the server starts up
    print(f"Loading model artifact from: {MODEL_PATH}")
    if os.path.exists(MODEL_PATH):
        ml_models["rf_model"] = joblib.load(MODEL_PATH)
        print("Model successfully loaded into memory!")
    else:
        raise FileNotFoundError(f"Could not locate model pickle file at {MODEL_PATH}")
    
    yield  # The application runs handles requests while sitting right here
    
    # This runs when the server completely shuts down
    ml_models.clear()
    print("Model memory cleared cleanly.")

# 3. Pass the lifespan handler directly into your application instance
app = FastAPI(
    title="PJME Energy Consumption Forecasting API",
    description="Production API serving Random Forest predictions for regional grid loads.",
    version="1.0.0",
    lifespan=lifespan
)

@app.get("/")
def read_root():
    return {
        "status": "healthy",
        "model_loaded": "rf_model" in ml_models,
        "message": "Welcome to the PJME Energy Forecasting Service."
    }

@app.post("/predict")
def predict_energy(payload: EnergyPredictionRequest):
    # Reference our global lifespan model cache
    if "rf_model" not in ml_models:
        raise HTTPException(status_code=503, detail="Model is not initialized or loaded yet.")
    
    try:
        input_data = payload.model_dump()
        
        # Enforce exact training column order
        FEATURES = ['hour', 'dayofweek', 'quarter', 'month', 'year', 'dayofyear', 
                    'is_weekend', 'lag_1_hour', 'lag_24_hours', 'lag_7_days', 
                    'rolling_mean_24h', 'rolling_mean_7d']
                    
        input_df = pd.DataFrame([input_data])[FEATURES]
        
        prediction = ml_models["rf_model"].predict(input_df)[0]
        
        return {
            "prediction_mw": round(float(prediction), 2),
            "unit": "Megawatts (MW)",
            "status": "success"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Inference Engine Error: {str(e)}")