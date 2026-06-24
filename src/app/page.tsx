'use client';

import { useState } from 'react';

export default function EnergyDashboard() {
  // 1. Core input matrix state mapping perfectly to our backend schema parameters
  const [formData, setFormData] = useState({
    hour: 18,
    dayofweek: 0,
    quarter: 1,
    month: 1,
    year: 2016,
    dayofyear: 4,
    is_weekend: 0,
    lag_1_hour: 31200.0,
    lag_24_hours: 29800.0,
    lag_7_days: 32100.0,
    rolling_mean_24h: 30500.0,
    rolling_mean_7d: 31000.0,
  });

  const [prediction, setPrediction] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: parseFloat(value) || 0,
    }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    setPrediction(null);

    // Pull backend endpoint dynamic path from Amplify system environment variables
    const apiBaseUrl = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

    try {
      const response = await fetch(`${apiBaseUrl}/predict`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
      });

      if (!response.ok) {
        throw new Error(`Server returned error status: ${response.status}`);
      }

      const data = await response.json();
      if (data.status === 'success') {
        setPrediction(data.prediction_mw);
      } else {
        throw new Error('Inference step failed on backend.');
      }
    } catch (err: any) {
      setError(err.message || 'Connection to API failed.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-gray-900 text-gray-100 p-8">
      <div className="max-w-4xl mx-auto">
        <header className="mb-8 border-b border-gray-800 pb-4">
          <h1 className="text-3xl font-bold text-emerald-400">PJME Grid Load Forecasting Service</h1>
          <p className="text-gray-400 mt-2">AWS Hosted UI Client for tracking real-world energy distribution patterns.</p>
        </header>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
          {/* Input Form Fields */}
          <form onSubmit={handleSubmit} className="md:col-span-2 bg-gray-800 p-6 rounded-xl shadow-lg space-y-4">
            <h2 className="text-xl font-semibold text-gray-200 mb-4">Input Metric Matrix</h2>
            <div className="grid grid-cols-2 gap-4">
              {Object.keys(formData).map((key) => (
                <div key={key} className="flex flex-col">
                  <label className="text-xs text-gray-400 font-mono mb-1 uppercase tracking-wider">
                    {key.replace(/_/g, ' ')}
                  </label>
                  <input
                    type="number"
                    name={key}
                    value={formData[key as keyof typeof formData]}
                    onChange={handleChange}
                    className="bg-gray-700 border border-gray-600 rounded p-2 text-white focus:outline-none focus:border-emerald-500 font-mono"
                    step="any"
                    required
                  />
                </div>
              ))}
            </div>
            <button
              type="submit"
              disabled={loading}
              className="w-full bg-emerald-500 hover:bg-emerald-600 text-gray-900 font-bold py-3 px-4 rounded-lg transition-colors mt-6 disabled:opacity-50"
            >
              {loading ? 'Running Engine Inference...' : 'Generate Demand Forecast'}
            </button>
          </form>

          {/* Metrics Output Display panel */}
          <div className="bg-gray-800 p-6 rounded-xl shadow-lg flex flex-col justify-between border border-gray-700">
            <div>
              <h2 className="text-xl font-semibold text-gray-200 mb-4">Inference Output</h2>
              <p className="text-xs text-gray-400 leading-relaxed">
                Submitting this form dispatches the token array payload to our decoupled API cloud host tier.
              </p>
            </div>

            <div className="my-8 text-center">
              {prediction !== null && (
                <div>
                  <div className="text-5xl font-black text-emerald-400 font-mono">{prediction}</div>
                  <div className="text-sm uppercase tracking-widest text-gray-400 mt-1">Megawatts (MW)</div>
                </div>
              )}
              {loading && <div className="text-xl text-gray-400 animate-pulse font-mono">Computing...</div>}
              {error && <div className="text-red-400 bg-red-950/50 p-3 rounded text-sm font-mono border border-red-900">{error}</div>}
              {!prediction && !loading && !error && <div className="text-gray-500 italic">Awaiting pipeline telemetry execution payload...</div>}
            </div>

            <div className="border-t border-gray-700 pt-4 text-xs text-center text-gray-500 font-mono">
              Status: AWS Amplify Active Target
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}