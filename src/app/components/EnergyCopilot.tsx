"use client";

import React, { useState } from 'react';

interface MetricProps {
    prediction_mw?: number;   // The output model prediction from Lambda
    hour: number;             // Hour of the day (0-23)
    dayofweek: number;        // Day of the week (0-6)
    quarter: number;          // Quarter of the year (1-4)
    month: number;            // Month of the year (1-12)
    year: number;             // Calendar year (e.g., 2026)
    dayofyear: number;        // Day of the year (1-366)
    is_weekend: number;       // 1 if weekend, else 0

    // The historical time-series indicators
    lag_1_hour: number;       // Energy load 1 hour before
    lag_24_hours: number;     // Energy load 24 hours before
    lag_7_days: number;       // Energy load 7 days before

    // The smoothed statistical trend metrics
    rolling_mean_24h: number; // Moving average over the last 24 hours
    rolling_mean_7d: number;  // Moving average over the last 7 days
}

interface Message {
    role: 'user' | 'assistant';
    text: string;
}

export default function EnergyCopilot({ currentMetrics }: { currentMetrics: MetricProps }) {
    const [messages, setMessages] = useState<Message[]>([
        { role: 'assistant', text: "Hello! I'm your grid AI Co-Pilot. Ask me anything about the current demand forecast or load trends." }
    ]);
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);

    const handleSendMessage = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!input.trim() || loading) return;

        const userMsg = input;
        setInput('');
        setMessages(prev => [...prev, { role: 'user', text: userMsg }]);
        setLoading(true);

        try {
            const baseUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
            const nextMessages = [...messages, { role: 'user', text: userMsg }];

            const response = await fetch(`${baseUrl}/copilot`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    chat_history: nextMessages,
                    current_prediction: currentMetrics.prediction_mw || 0,
                    hour: currentMetrics.hour,
                    dayofweek: currentMetrics.dayofweek,
                    quarter: currentMetrics.quarter,
                    month: currentMetrics.month,
                    year: currentMetrics.year,
                    dayofyear: currentMetrics.dayofyear,
                    is_weekend: currentMetrics.is_weekend,
                    lag_1_hour: currentMetrics.lag_1_hour,
                    lag_24_hours: currentMetrics.lag_24_hours,
                    lag_7_days: currentMetrics.lag_7_days,
                    rolling_mean_24h: currentMetrics.rolling_mean_24h,
                    rolling_mean_7d: currentMetrics.rolling_mean_7d,
                }),
            });

            const data = await response.json();

            if (data.status === 'success') {
                setMessages(prev => [...prev, { role: 'assistant', text: data.response }]);
            } else {
                setMessages(prev => [...prev, { role: 'assistant', text: `Glitch: ${data.message}` }]);
            }
        } catch (error) {
            setMessages(prev => [...prev, { role: 'assistant', text: "Failed to communicate with the grid intelligence engine." }]);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col h-[500px] shadow-2xl text-white">
            <div className="border-b border-slate-800 pb-2 mb-4">
                <h3 className="text-lg font-bold text-emerald-400 flex items-center gap-2">
                    <span>⚡</span> AWS Bedrock Grid Co-Pilot
                </h3>
                <p className="text-xs text-slate-400">Context-aware grid operational intelligence</p>
            </div>

            <div className="flex-1 overflow-y-auto space-y-3 mb-4 pr-1">
                {messages.map((msg, idx) => (
                    <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                        <div className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${msg.role === 'user' ? 'bg-emerald-600 text-white' : 'bg-slate-800 text-slate-200'
                            }`}>
                            {msg.text}
                        </div>
                    </div>
                ))}
                {loading && (
                    <div className="flex justify-start">
                        <div className="bg-slate-800 text-slate-400 text-xs rounded-lg px-3 py-2 animate-pulse">
                            Co-pilot is parsing grid state vectors...
                        </div>
                    </div>
                )}
            </div>

            <form onSubmit={handleSendMessage} className="flex gap-2">
                <input
                    type="text"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    placeholder="Ask about peak times, load changes..."
                    className="flex-1 bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-emerald-500"
                    disabled={loading}
                />
                <button
                    type="submit"
                    className="bg-emerald-500 hover:bg-emerald-600 text-slate-950 text-sm font-semibold px-4 py-2 rounded-lg transition-colors disabled:opacity-50"
                    disabled={loading}
                >
                    Send
                </button>
            </form>
        </div>
    );
}