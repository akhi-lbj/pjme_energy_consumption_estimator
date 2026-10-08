"use client";

import React, { useState, useRef, useEffect } from 'react';
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

interface ToolCall {
    name: string;
    input: Record<string, any>;
    output: Record<string, any>;
}

interface Message {
    role: 'user' | 'assistant';
    text: string;
    tool_calls?: ToolCall[];
}

function ToolCallsBadge({ toolCalls }: { toolCalls?: ToolCall[] }) {
    const [expanded, setExpanded] = useState(false);

    if (!toolCalls || toolCalls.length === 0) return null;

    return (
        <div className="mt-3 pt-2.5 border-t border-slate-700/60">
            <button
                type="button"
                onClick={() => setExpanded(!expanded)}
                className="flex items-center gap-2 px-2.5 py-1 rounded-md text-xs font-mono font-medium text-emerald-400 bg-slate-900/90 hover:bg-slate-950 border border-emerald-500/30 hover:border-emerald-500/70 transition-all cursor-pointer shadow-sm group select-none"
            >
                <span className="flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
                    <span>🛠️ Tool Calls ({toolCalls.length})</span>
                </span>
                <span className="text-[10px] text-slate-400 group-hover:text-emerald-300">
                    {expanded ? '▲ Hide' : '▼ View Invocation'}
                </span>
            </button>

            {expanded && (
                <div className="mt-2.5 space-y-2">
                    {toolCalls.map((tc, idx) => (
                        <div key={idx} className="bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-xs font-mono space-y-2 shadow-inner">
                            <div className="flex items-center justify-between text-emerald-300 font-semibold border-b border-slate-800/80 pb-1">
                                <span className="flex items-center gap-1.5">
                                    <span className="text-emerald-400">⚡</span>
                                    <span>{tc.name}()</span>
                                </span>
                                <span className="text-[10px] text-slate-500 uppercase tracking-wider">Invocation #{idx + 1}</span>
                            </div>
                            
                            <div>
                                <span className="text-slate-400 text-[10px] uppercase font-semibold tracking-wider block mb-1">
                                    Tool Input Parameters:
                                </span>
                                <pre className="bg-slate-900 text-slate-300 p-2 rounded border border-slate-800 overflow-x-auto text-[11px] leading-tight">
                                    {JSON.stringify(tc.input, null, 2)}
                                </pre>
                            </div>

                            <div>
                                <span className="text-emerald-400 text-[10px] uppercase font-semibold tracking-wider block mb-1">
                                    Tool Output / Telemetry:
                                </span>
                                <pre className="bg-slate-900 text-emerald-300 p-2 rounded border border-slate-800 overflow-x-auto text-[11px] leading-tight">
                                    {JSON.stringify(tc.output, null, 2)}
                                </pre>
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}

export default function EnergyCopilot({ currentMetrics }: { currentMetrics: MetricProps }) {
    const [messages, setMessages] = useState<Message[]>([
        { role: 'assistant', text: "Hello! I'm your Grid Agent. Ask me anything about the current demand forecast, weather correlations, or load trends." }
    ]);
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const prevPredictionRef = useRef<number | undefined>(undefined);

    const activeDateStr = `${currentMetrics.year}-${String(currentMetrics.month).padStart(2, '0')} (Day ${currentMetrics.dayofyear}) @ ${currentMetrics.hour}:00`;

    // Automatically detect when a new forecast job is generated on the dashboard
    useEffect(() => {
        if (
            currentMetrics.prediction_mw !== undefined &&
            currentMetrics.prediction_mw !== prevPredictionRef.current
        ) {
            prevPredictionRef.current = currentMetrics.prediction_mw;
            setMessages(prev => [
                ...prev,
                {
                    role: 'assistant',
                    text: `⚡ **New Forecast Job Loaded:** **${currentMetrics.prediction_mw?.toLocaleString()} MW** for **${activeDateStr}**.\n\nActive telemetry updated. What would you like to examine regarding this forecast?`
                }
            ]);
        }
    }, [currentMetrics.prediction_mw, currentMetrics.year, currentMetrics.month, currentMetrics.dayofyear, currentMetrics.hour, activeDateStr]);

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages, loading]);

    const handleClearChat = () => {
        setMessages([
            { role: 'assistant', text: `Hello! I'm your Grid Agent. Ready to analyze active forecast (${currentMetrics.prediction_mw ? `${currentMetrics.prediction_mw.toLocaleString()} MW` : 'Configure metrics on the left'}).` }
        ]);
    };

    const handleQuickPrompt = (promptText: string) => {
        setInput(promptText);
    };

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
                    chat_history: nextMessages.map(m => ({
                        role: m.role,
                        text: m.text || ''
                    })),
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
                setMessages(prev => [...prev, { 
                    role: 'assistant', 
                    text: data.response,
                    tool_calls: data.tool_calls || []
                }]);
            } else {
                const errorMsg = typeof data?.detail === 'string'
                    ? data.detail
                    : Array.isArray(data?.detail)
                        ? data.detail.map((d: any) => d.msg || JSON.stringify(d)).join(', ')
                        : data?.message || data?.Message || "Temporary grid service glitch. Please resend your query.";
                setMessages(prev => [...prev, { role: 'assistant', text: `Glitch: ${errorMsg}` }]);
            }
        } catch (error) {
            setMessages(prev => [...prev, { role: 'assistant', text: "Failed to communicate with the grid intelligence engine. Please retry." }]);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 sm:p-7 flex flex-col h-[640px] xl:h-[760px] max-h-[640px] xl:max-h-[760px] shadow-2xl text-white">
            <div className="flex-shrink-0 border-b border-slate-800 pb-3 mb-3">
                <div className="flex items-center justify-between">
                    <h3 className="text-2xl font-bold text-emerald-400 flex items-center gap-2.5">
                        <span>⚡</span> Grid Agent
                    </h3>
                    <button
                        type="button"
                        onClick={handleClearChat}
                        className="text-xs font-mono text-slate-400 hover:text-emerald-300 border border-slate-700/60 hover:border-emerald-500/50 px-2.5 py-1 rounded-md transition-all cursor-pointer bg-slate-950/60"
                        title="Reset conversation session for active forecast"
                    >
                        🔄 New Session
                    </button>
                </div>
                <p className="text-xs text-slate-400 mt-1">Autonomous grid intelligence & weather analytics</p>

                {/* Active Forecast Target Strip */}
                <div className="flex items-center justify-between bg-slate-950/90 border border-slate-800 rounded-lg px-3 py-1.5 mt-2.5 text-xs font-mono">
                    <span className="text-slate-400">Active Target: <strong className="text-emerald-300 font-semibold">{activeDateStr}</strong></span>
                    {currentMetrics.prediction_mw ? (
                        <span className="text-emerald-400 font-bold bg-emerald-950/80 border border-emerald-800/60 px-2 py-0.5 rounded shadow-sm">
                            ⚡ {currentMetrics.prediction_mw.toLocaleString()} MW
                        </span>
                    ) : (
                        <span className="text-slate-500 italic">Awaiting forecast run</span>
                    )}
                </div>
            </div>

            <div className="flex-1 min-h-0 overflow-y-auto space-y-4 mb-4 pr-2 agent-scrollbar">
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

                                {/* Interactive Tool Calls Component */}
                                <ToolCallsBadge toolCalls={msg.tool_calls} />
                            </div>
                        )}
                    </div>
                ))}
                {loading && (
                    <div className="flex justify-start">
                        <div className="bg-slate-800 text-slate-300 text-sm rounded-xl px-4 py-3 border border-slate-700/80 animate-pulse flex items-center gap-2">
                            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping"></span>
                            Grid Agent is analyzing telemetry & meteorological vectors...
                        </div>
                    </div>
                )}
                <div ref={messagesEndRef} />
            </div>

            {/* Quick Action Suggestion Pills */}
            <div className="flex items-center gap-2 overflow-x-auto pb-2 text-xs font-mono select-none">
                <button
                    type="button"
                    onClick={() => handleQuickPrompt(`Examine active forecast findings (${currentMetrics.prediction_mw ? `${currentMetrics.prediction_mw.toLocaleString()} MW` : 'current load'}) and grid status.`)}
                    className="whitespace-nowrap px-2.5 py-1 rounded-full bg-slate-800 hover:bg-slate-700 text-emerald-300 border border-slate-700 hover:border-emerald-500/50 transition-all cursor-pointer text-[11px]"
                >
                    📊 Examine Findings
                </button>
                <button
                    type="button"
                    onClick={() => handleQuickPrompt("What is the meteorological weather impact on this forecast load?")}
                    className="whitespace-nowrap px-2.5 py-1 rounded-full bg-slate-800 hover:bg-slate-700 text-emerald-300 border border-slate-700 hover:border-emerald-500/50 transition-all cursor-pointer text-[11px]"
                >
                    🌡️ Weather Impact
                </button>
                <button
                    type="button"
                    onClick={() => handleQuickPrompt("Simulate contingency scenario if temperature rises by 5 degrees and we curtail 500 MW.")}
                    className="whitespace-nowrap px-2.5 py-1 rounded-full bg-slate-800 hover:bg-slate-700 text-emerald-300 border border-slate-700 hover:border-emerald-500/50 transition-all cursor-pointer text-[11px]"
                >
                    ⚡ What-If Scenario
                </button>
            </div>

            <form onSubmit={handleSendMessage} className="flex-shrink-0 flex gap-3 pt-1">
                <input
                    type="text"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    placeholder="Ask Grid Agent about peak times, load changes, weather impacts..."
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