'use client';

import { useState } from 'react';
import EnergyCopilot from './components/EnergyCopilot';

export default function EnergyDashboard() {
  // 1. Core input matrix state mapping perfectly to backend schema parameters
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
    <main className="min-h-screen bg-slate-950 text-slate-100 p-6 sm:p-10 lg:p-12">
      <div className="max-w-[1600px] mx-auto">
        <header className="mb-10 border-b border-slate-800 pb-6 flex flex-col md:flex-row md:items-end md:justify-between gap-4">
          <div>
            <h1 className="text-4xl sm:text-5xl font-extrabold text-emerald-400 tracking-tight">
              PJME Grid Load Forecasting Service
            </h1>
            <p className="text-base sm:text-lg text-slate-300 mt-2 font-medium">
              AWS Hosted UI Client for tracking real-world energy distribution patterns.
            </p>
          </div>
          <div className="flex items-center gap-2.5 text-xs sm:text-sm font-mono text-emerald-400 bg-emerald-950/70 border border-emerald-800/80 px-4 py-2.5 rounded-full w-fit shadow-inner">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse"></span>
            System Online &bull; AWS Lambda / Grid Agent
          </div>
        </header>

        <div className="grid grid-cols-1 xl:grid-cols-12 gap-8 items-start">
          
          {/* Left Column: Input Form (5 cols on XL) */}
          <div className="xl:col-span-5 flex flex-col">
            <form onSubmit={handleSubmit} className="bg-slate-900 border border-slate-800 p-7 sm:p-8 rounded-2xl shadow-2xl flex flex-col justify-between h-full xl:min-h-[760px] space-y-6">
              <div>
                <div className="border-b border-slate-800 pb-4 mb-6">
                  <h2 className="text-2xl font-bold text-slate-100">Input Metric Matrix</h2>
                  <p className="text-sm text-slate-400 mt-1">Configure telemetry variables and operational lags</p>
                </div>

                <div className="grid grid-cols-2 gap-4 sm:gap-5">
                  {Object.keys(formData).map((key) => (
                    <div key={key} className="flex flex-col">
                      <label className="text-xs sm:text-sm font-mono font-semibold text-slate-300 mb-1.5 uppercase tracking-wider">
                        {key.replace(/_/g, ' ')}
                      </label>
                      <input
                        type="number"
                        name={key}
                        value={formData[key as keyof typeof formData]}
                        onChange={handleChange}
                        className="bg-slate-950 border border-slate-700/80 rounded-lg p-3 text-base text-white focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-transparent font-mono transition-all"
                        step="any"
                        required
                      />
                    </div>
                  ))}
                </div>
              </div>

              <button
                type="submit"
                disabled={loading}
                className="w-full bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold py-4 px-6 rounded-xl transition-all duration-200 mt-4 disabled:opacity-50 text-lg shadow-lg shadow-emerald-500/20 active:scale-[0.99] cursor-pointer"
              >
                {loading ? 'Running Engine Inference...' : 'Generate Demand Forecast'}
              </button>
            </form>
          </div>

          {/* Middle Column: Inference Output (3 cols on XL) */}
          <div className="xl:col-span-3 flex flex-col">
            <div className="bg-slate-900 border border-slate-800 p-7 sm:p-8 rounded-2xl shadow-2xl flex flex-col justify-between h-full min-h-[580px] xl:h-[760px] xl:max-h-[760px]">
              <div>
                <h2 className="text-2xl font-bold text-slate-100 mb-2">Inference Output</h2>
                <p className="text-sm text-slate-300 leading-relaxed">
                  Submitting this form dispatches the token array payload to our decoupled API cloud host tier.
                </p>
              </div>

              <div className="my-10 text-center flex flex-col items-center justify-center">
                {prediction !== null && (
                  <div className="w-full">
                    <div className="text-5xl sm:text-6xl xl:text-7xl font-black text-emerald-400 font-mono tracking-tight drop-shadow-[0_0_24px_rgba(52,211,153,0.35)] break-words">
                      {prediction}
                    </div>
                    <div className="text-sm sm:text-base uppercase tracking-widest text-slate-300 font-semibold mt-3">
                      Megawatts (MW)
                    </div>
                  </div>
                )}
                {loading && (
                  <div className="text-2xl text-emerald-400 animate-pulse font-mono flex items-center gap-3">
                    <span className="w-3 h-3 rounded-full bg-emerald-400 animate-ping"></span>
                    Computing...
                  </div>
                )}
                {error && (
                  <div className="text-red-300 bg-red-950/70 p-4 rounded-xl text-sm font-mono border border-red-800">
                    {error}
                  </div>
                )}
                {!prediction && !loading && !error && (
                  <div className="text-slate-400 text-base italic px-4">
                    Awaiting pipeline telemetry execution payload...
                  </div>
                )}
              </div>

              <div className="border-t border-slate-800 pt-4 text-xs sm:text-sm text-center text-slate-400 font-mono">
                Status: AWS Amplify Active Target
              </div>
            </div>
          </div>

          {/* Right Column: Grid Agent (4 cols on XL) */}
          <div className="xl:col-span-4 flex flex-col min-h-0">
            <EnergyCopilot 
              currentMetrics={{
                ...formData,
                prediction_mw: prediction ?? undefined
              }} 
            />
          </div>

        </div>
      </div>
    </main>
  );
}