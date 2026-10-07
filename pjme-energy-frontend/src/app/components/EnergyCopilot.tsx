"use client";

import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

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
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 sm:p-7 flex flex-col h-full min-h-[580px] xl:min-h-[640px] shadow-2xl text-white">
            <div className="border-b border-slate-800 pb-4 mb-4">
                <h3 className="text-2xl font-bold text-emerald-400 flex items-center gap-2.5">
                    <span>⚡</span> AWS Bedrock Grid Co-Pilot
                </h3>
                <p className="text-sm text-slate-300 mt-1">Context-aware grid operational intelligence</p>
            </div>

            <div className="flex-1 overflow-y-auto space-y-4 mb-4 pr-1">
                {messages.map((msg, idx) => (
                    <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                        {msg.role === 'user' ? (
                            <div className="max-w-[85%] rounded-xl px-4 py-3 text-base whitespace-pre-wrap bg-emerald-600 text-white shadow-md font-medium">
                                {msg.text}
                            </div>
                        ) : (
                            <div className="max-w-[95%] rounded-xl px-5 py-4 text-base bg-slate-800/90 text-slate-100 border border-slate-700/70 shadow-lg leading-relaxed">
                                <ReactMarkdown
                                    remarkPlugins={[remarkGfm]}
                                    components={{
                                        p: ({ node, ...props }) => <p className="mb-2.5 last:mb-0 leading-relaxed text-slate-200 text-base" {...props} />,
                                        strong: ({ node, ...props }) => <strong className="font-bold text-emerald-300 text-base" {...props} />,
                                        em: ({ node, ...props }) => <em className="italic text-emerald-200" {...props} />,
                                        ul: ({ node, ...props }) => <ul className="list-disc list-inside space-y-1.5 my-2.5 text-slate-200 text-base" {...props} />,
                                        ol: ({ node, ...props }) => <ol className="list-decimal list-inside space-y-1.5 my-2.5 text-slate-200 text-base" {...props} />,
                                        li: ({ node, ...props }) => <li className="text-slate-200 leading-relaxed text-base" {...props} />,
                                        table: ({ node, ...props }) => (
                                            <div className="overflow-x-auto my-3 border border-slate-700 rounded-lg shadow-sm">
                                                <table className="min-w-full divide-y divide-slate-700 text-sm text-left" {...props} />
                                            </div>
                                        ),
                                        thead: ({ node, ...props }) => <thead className="bg-slate-950/90 text-emerald-400 font-semibold" {...props} />,
                                        tbody: ({ node, ...props }) => <tbody className="divide-y divide-slate-700/60 bg-slate-800/40" {...props} />,
                                        tr: ({ node, ...props }) => <tr className="hover:bg-slate-700/30 transition-colors" {...props} />,
                                        th: ({ node, ...props }) => <th className="px-3.5 py-2.5 font-semibold uppercase tracking-wider" {...props} />,
                                        td: ({ node, ...props }) => <td className="px-3.5 py-2.5 text-slate-300" {...props} />,
                                        code: ({ node, className, children, ...props }) => (
                                            <code className="bg-slate-950 border border-slate-800 px-2 py-0.5 rounded text-sm font-mono text-emerald-300" {...props}>
                                                {children}
                                            </code>
                                        ),
                                        blockquote: ({ node, ...props }) => (
                                            <blockquote className="border-l-4 border-emerald-500 pl-4 my-2.5 italic text-slate-300 bg-slate-950/60 py-2 rounded-r-lg text-sm sm:text-base" {...props} />
                                        ),
                                        h1: ({ node, ...props }) => <h1 className="text-lg font-bold text-emerald-400 my-2" {...props} />,
                                        h2: ({ node, ...props }) => <h2 className="text-base font-bold text-emerald-400 my-2" {...props} />,
                                        h3: ({ node, ...props }) => <h3 className="text-sm font-bold text-emerald-300 my-1.5 uppercase tracking-wider" {...props} />,
                                    }}
                                >
                                    {msg.text}
                                </ReactMarkdown>
                            </div>
                        )}
                    </div>
                ))}
                {loading && (
                    <div className="flex justify-start">
                        <div className="bg-slate-800 text-slate-300 text-sm rounded-xl px-4 py-3 border border-slate-700/80 animate-pulse flex items-center gap-2">
                            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping"></span>
                            Co-pilot is parsing grid state vectors...
                        </div>
                    </div>
                )}
            </div>

            <form onSubmit={handleSendMessage} className="flex gap-3 pt-2">
                <input
                    type="text"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    placeholder="Ask about peak times, load changes..."
                    className="flex-1 bg-slate-950 border border-slate-700/80 rounded-xl px-4 py-3.5 text-base text-white focus:outline-none focus:ring-2 focus:ring-emerald-500 placeholder-slate-400"
                    disabled={loading}
                />
                <button
                    type="submit"
                    className="bg-emerald-500 hover:bg-emerald-400 text-slate-950 text-base font-bold px-6 py-3.5 rounded-xl transition-all shadow-md active:scale-95 disabled:opacity-50 cursor-pointer"
                    disabled={loading}
                >
                    Send
                </button>
            </form>
        </div>
    );
}