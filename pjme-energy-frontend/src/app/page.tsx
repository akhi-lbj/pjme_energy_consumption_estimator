'use client';

import { useState } from 'react';
import EnergyCopilot from './components/EnergyCopilot';

// Helper to format Date as YYYY-MM-DD
const formatDateToISO = (d: Date): string => {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
};

// Next day (tomorrow) limit
const getTomorrowDate = (): Date => {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return d;
};

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

  const [calendarDate, setCalendarDate] = useState<string>('2016-01-04');
  const [prediction, setPrediction] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const maxCalendarDateStr = formatDateToISO(getTomorrowDate());

  // Function to calculate all 7 calendar telemetry metrics from a Date object & hour
  const deriveCalendarMetrics = (dateObj: Date, hourVal?: number) => {
    const year = dateObj.getFullYear();
    const month = dateObj.getMonth() + 1;
    const quarter = Math.floor((month - 1) / 3) + 1;

    // JavaScript: 0 = Sunday, 1 = Monday, ..., 6 = Saturday
    // Python/Pandas: 0 = Monday, ..., 6 = Sunday
    const jsDay = dateObj.getDay();
    const dayofweek = (jsDay + 6) % 7;
    const is_weekend = dayofweek === 5 || dayofweek === 6 ? 1 : 0;

    // Day of Year (1 - 366)
    const startOfYear = new Date(year, 0, 1);
    const diffMs = dateObj.getTime() - startOfYear.getTime();
    const dayofyear = Math.floor(diffMs / (1000 * 60 * 60 * 24)) + 1;

    const hour = hourVal !== undefined ? hourVal : dateObj.getHours();

    return {
      hour,
      dayofweek,
      quarter,
      month,
      year,
      dayofyear,
      is_weekend,
    };
  };

  // Auto-generate buttons handler: fills only the 7 calendar fields; leaves lag/rolling means untouched
  const handleAutoGenerate = (target: 'today' | 'tomorrow' | 'benchmark') => {
    setError('');
    if (target === 'benchmark') {
      const benchmarkDate = new Date(2016, 0, 4);
      setCalendarDate('2016-01-04');
      setFormData(prev => ({
        ...prev,
        ...deriveCalendarMetrics(benchmarkDate, 18),
      }));
      return;
    }

    const targetDate = target === 'today' ? new Date() : getTomorrowDate();
    const isoStr = formatDateToISO(targetDate);
    setCalendarDate(isoStr);

    setFormData(prev => ({
      ...prev,
      ...deriveCalendarMetrics(targetDate),
    }));
  };

  // Interactive calendar date picker resolver
  const handleCalendarDateChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    if (!val) return;

    const parts = val.split('-').map(Number);
    if (parts.length !== 3) return;

    const selectedDate = new Date(parts[0], parts[1] - 1, parts[2]);
    const tomorrowLimit = getTomorrowDate();
    tomorrowLimit.setHours(23, 59, 59, 999);

    if (selectedDate.getTime() > tomorrowLimit.getTime()) {
      setError(`Forecast Horizon Notice: Predictions are supported up to today and the next day (${maxCalendarDateStr}) only.`);
      return;
    }

    setError('');
    setCalendarDate(val);
    setFormData(prev => ({
      ...prev,
      ...deriveCalendarMetrics(selectedDate, prev.hour),
    }));
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setError('');
    setFormData(prev => ({
      ...prev,
      [name]: parseFloat(value) || 0,
    }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setPrediction(null);

    // 1. Client-Side Strict Validation Checks
    const h = Number(formData.hour);
    if (isNaN(h) || h < 0 || h > 23 || !Number.isInteger(h)) {
      setError('Hour: enter between 0 and 23.');
      return;
    }

    const dow = Number(formData.dayofweek);
    if (isNaN(dow) || dow < 0 || dow > 6 || !Number.isInteger(dow)) {
      setError('Day of week: enter between 0 (Monday) and 6 (Sunday).');
      return;
    }

    const q = Number(formData.quarter);
    if (isNaN(q) || q < 1 || q > 4 || !Number.isInteger(q)) {
      setError('Quarter: enter between 1 and 4.');
      return;
    }

    const m = Number(formData.month);
    if (isNaN(m) || m < 1 || m > 12 || !Number.isInteger(m)) {
      setError('Month: enter between 1 and 12.');
      return;
    }

    const doy = Number(formData.dayofyear);
    if (isNaN(doy) || doy < 1 || doy > 366 || !Number.isInteger(doy)) {
      setError('Day of year: enter between 1 and 366.');
      return;
    }

    const iw = Number(formData.is_weekend);
    if (isNaN(iw) || (iw !== 0 && iw !== 1)) {
      setError('Is weekend: enter 0 (weekday) or 1 (weekend).');
      return;
    }

    // 2. Calendar Horizon Check (Up to today and next day only)
    try {
      const derivedDate = new Date(formData.year, 0, 1);
      derivedDate.setDate(derivedDate.getDate() + (formData.dayofyear - 1));
      const tomorrowLimit = getTomorrowDate();
      tomorrowLimit.setHours(23, 59, 59, 999);

      if (derivedDate.getTime() > tomorrowLimit.getTime()) {
        setError(`Forecast Horizon Exceeded: Target date (${derivedDate.toLocaleDateString()}) is beyond tomorrow. Predictions are allowed up to today and next day only.`);
        return;
      }
    } catch {
      // Ignore date calculation errors
    }

    setLoading(true);

    // Pull backend endpoint dynamic path from Amplify environment variables
    const apiBaseUrl = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

    try {
      const response = await fetch(`${apiBaseUrl}/predict`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => null);
        if (errData?.detail) {
          if (Array.isArray(errData.detail)) {
            const formatted = errData.detail.map((d: any) => {
              if (typeof d === 'string') return d;
              const field = Array.isArray(d.loc) ? d.loc[d.loc.length - 1] : '';
              if (field === 'hour') return 'Hour: enter between 0 and 23';
              if (field === 'dayofweek') return 'Day of week: enter between 0 (Monday) and 6 (Sunday)';
              if (field === 'quarter') return 'Quarter: enter between 1 and 4';
              if (field === 'month') return 'Month: enter between 1 and 12';
              if (field === 'dayofyear') return 'Day of year: enter between 1 and 366';
              if (field === 'is_weekend') return 'Is weekend: enter 0 (weekday) or 1 (weekend)';
              return d.msg || JSON.stringify(d);
            }).join(' | ');
            throw new Error(formatted);
          } else if (typeof errData.detail === 'string') {
            throw new Error(errData.detail);
          }
        }
        throw new Error(errData?.message || `Server returned error status: ${response.status}`);
      }

      const data = await response.json();
      if (data.status === 'success') {
        setPrediction(data.prediction_mw);
      } else {
        throw new Error(data.message || 'Inference step failed on backend.');
      }
    } catch (err: any) {
      setError(err.message || 'Connection to API failed.');
    } finally {
      setLoading(false);
    }
  };

  // Formatted day of week name helper
  const dayNames = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
  const activeDayName = dayNames[formData.dayofweek] || 'Day';

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
                <div className="border-b border-slate-800 pb-4 mb-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div>
                    <h2 className="text-2xl font-bold text-slate-100 flex items-center gap-2">
                      <span>🎛️</span> Input Metric Matrix
                    </h2>
                    <p className="text-sm text-slate-400 mt-1">Configure telemetry variables and operational lags</p>
                  </div>

                  {/* Auto-Generate Sample Buttons on the Right */}
                  <div className="flex flex-wrap items-center gap-2 self-start sm:self-auto">
                    <button
                      type="button"
                      onClick={() => handleAutoGenerate('today')}
                      className="px-2.5 py-1.5 rounded-lg text-xs font-mono font-semibold bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-300 border border-emerald-500/30 transition-all flex items-center gap-1.5 active:scale-95 cursor-pointer shadow-sm"
                      title="Auto-fill calendar fields for Current Time (Today)"
                    >
                      <span>⚡</span> Today (Now)
                    </button>
                    <button
                      type="button"
                      onClick={() => handleAutoGenerate('tomorrow')}
                      className="px-2.5 py-1.5 rounded-lg text-xs font-mono font-semibold bg-cyan-500/15 hover:bg-cyan-500/25 text-cyan-300 border border-cyan-500/30 transition-all flex items-center gap-1.5 active:scale-95 cursor-pointer shadow-sm"
                      title="Auto-fill calendar fields for Tomorrow (Next Day)"
                    >
                      <span>⏩</span> Next Day
                    </button>
                    <button
                      type="button"
                      onClick={() => handleAutoGenerate('benchmark')}
                      className="px-2 py-1.5 rounded-lg text-xs font-mono text-slate-400 hover:text-slate-200 bg-slate-800/80 hover:bg-slate-700/80 border border-slate-700/80 transition-all flex items-center gap-1 active:scale-95 cursor-pointer"
                      title="Reset to 2016 Archive Benchmark"
                    >
                      <span>🏛️</span> 2016
                    </button>
                  </div>
                </div>

                {/* Calendar Resolver Toolbar */}
                <div className="bg-slate-950/90 border border-slate-800/90 rounded-xl p-3 mb-5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs">
                  <div className="flex items-center gap-2.5">
                    <span className="text-emerald-400 font-bold text-sm">📅</span>
                    <span className="font-semibold text-slate-300 font-mono">Calendar Resolver:</span>
                    <input
                      type="date"
                      value={calendarDate}
                      max={maxCalendarDateStr}
                      onChange={handleCalendarDateChange}
                      className="bg-slate-900 border border-slate-700/80 rounded-md px-2.5 py-1 text-emerald-300 font-mono text-xs focus:outline-none focus:ring-1 focus:ring-emerald-500 cursor-pointer"
                    />
                  </div>
                  <div className="text-[11px] font-mono text-slate-400 flex items-center gap-1.5">
                    <span className="text-slate-500">Auto-Resolved:</span>
                    <span className="text-emerald-300 font-semibold bg-emerald-950/70 border border-emerald-800/50 px-2 py-0.5 rounded">
                      {activeDayName} &bull; Day {formData.dayofyear} &bull; Q{formData.quarter} &bull; {formData.is_weekend === 1 ? 'Weekend' : 'Weekday'}
                    </span>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4 sm:gap-5">
                  {Object.keys(formData).map((key) => {
                    const isCalendarField = ['hour', 'dayofweek', 'quarter', 'month', 'year', 'dayofyear', 'is_weekend'].includes(key);
                    return (
                      <div key={key} className="flex flex-col">
                        <div className="flex items-center justify-between mb-1.5">
                          <label className="text-xs sm:text-sm font-mono font-semibold text-slate-300 uppercase tracking-wider">
                            {key.replace(/_/g, ' ')}
                          </label>
                          {isCalendarField && (
                            <span className="text-[10px] font-mono text-emerald-400/80 bg-emerald-950/50 border border-emerald-900/60 px-1.5 py-0.2 rounded">
                              auto
                            </span>
                          )}
                        </div>
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
                    );
                  })}
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
                {prediction !== null && !error && (
                  <div className="w-full">
                    <div className="text-5xl sm:text-6xl xl:text-7xl font-black text-emerald-400 font-mono tracking-tight drop-shadow-[0_0_24px_rgba(52,211,153,0.35)] break-words">
                      {prediction.toLocaleString()}
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
                  <div className="w-full bg-red-950/90 border-2 border-red-600/80 p-5 rounded-2xl shadow-2xl text-left space-y-2.5 animate-in fade-in duration-200">
                    <div className="flex items-center gap-2 text-red-400 font-bold text-base">
                      <span className="text-xl">⚠️</span>
                      <span>Validation Notice</span>
                    </div>
                    <div className="text-red-200 text-sm font-mono leading-relaxed bg-red-900/40 p-3 rounded-lg border border-red-800/60">
                      {error}
                    </div>
                    <p className="text-xs text-red-300/80 font-sans pt-1">
                      Please adjust the input metric values on the left and re-generate.
                    </p>
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