from pydantic_core.core_schema import json_schema
from pydantic import BaseModel, Field, ConfigDict

class EnergyPredictionRequest(BaseModel):
    hour: int=Field(...,ge=0, le=23, description="Hour of the day (0-23)")
    dayofweek: int = Field(...,ge=0, le=6, description="Day of the week (0-6)")
    quarter: int=Field(...,ge=1, le=4, description="Quarter of the year (1-4)")
    month: int=Field(...,ge=1, le=12, description="Month of the year (1-12)")
    year: int = Field(..., description="Calendar year (e.g., 2026)")
    dayofyear: int=Field(...,ge=1, le=366, description="Day of the year (1-366)")
    is_weekend: int=Field(...,ge=0,le=1,description="1 if weekend else 0")

    lag_1_hour: float = Field(..., description="Energy consumption 1 hour before (KWH)")
    lag_24_hours: float= Field(..., description="Energy consumption 24 hours before (KWH)")
    lag_7_days: float= Field(..., description="Energy consumption 7 days before (KWH)")
    
    rolling_mean_24h: float=Field(..., description="Rolling mean energy consumption over last 24 hours (KWH)")
    rolling_mean_7d: float=Field(..., description="Rolling mean energy consumption over last 7 days (KWH)")

    # Modern Pydantic V2 Config Layout
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
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
        }
    )