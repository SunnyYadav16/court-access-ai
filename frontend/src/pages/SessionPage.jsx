/**
 * pages/SessionPage.jsx
 *
 * Active real-time interpretation session.
 * Connects to WebSocket, shows live transcript, allows ending the session.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { sessionsApi } from "@/services/api";
import { useWebSocket } from "@/hooks/useWebSocket";

function WSStatusBadge({ status }) {
    const map = {
        idle: { cls: "badge--muted", label: "Idle" },
        connecting: { cls: "badge--warn", label: "Connecting…" },
        reconnecting: { cls: "badge--warn", label: "Reconnecting…" },
        connected: { cls: "badge--accent", label: "Live" },
        disconnected: { cls: "badge--muted", label: "Disconnected" },
        error: { cls: "badge--danger", label: "Error" },
    };
    const { cls, label } = map[status] ?? map.idle;
    return (
        <span className={`badge ${cls}`} style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem" }}>
            {status === "connected" && <span className="status-dot status-dot--active" />}
            {label}
        </span>
    );
}

export default function SessionPage() {
    const { id } = useParams();
    const navigate = useNavigate();
    const transcriptRef = useRef(null);
    const [segments, setSegments] = useState([]);
    const [wsError, setWsError] = useState(null);
    const [isEnding, setIsEnding] = useState(false);

    // Poll session metadata
    const { data: session } = useQuery({
        queryKey: ["session", id],
        queryFn: () => sessionsApi.get(id),
        refetchInterval: 10_000,
    });

    const onTranscript = useCallback((seg) => {
        setSegments((prev) => {
            // Replace interim segment or append final
            if (seg.is_interim) {
                const last = prev[prev.length - 1];
                if (last?.is_interim) return [...prev.slice(0, -1), seg];
            }
            return [...prev, seg];
        });
    }, []);

    const onError = useCallback((err) => setWsError(err?.message ?? "WebSocket error"), []);

    const { status: wsStatus, send, disconnect } = useWebSocket(id, { onTranscript, onError });

    // Auto-scroll transcript
    useEffect(() => {
        transcriptRef.current?.scrollTo({ top: transcriptRef.current.scrollHeight, behavior: "smooth" });
    }, [segments]);

    const handleEnd = async () => {
        setIsEnding(true);
        disconnect();
        try {
            await sessionsApi.end(id);
        } finally {
            navigate("/dashboard");
        }
    };

    // Ping to keep connection alive
    useEffect(() => {
        if (wsStatus !== "connected") return;
        const t = setInterval(() => send("ping"), 20_000);
        return () => clearInterval(t);
    }, [wsStatus, send]);

    return (
        <div className="page">
            <div className="container container--narrow">
                {/* Header */}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "var(--space-5)" }}>
                    <div>
                        <h1 style={{ fontFamily: "var(--font-heading)", fontSize: "1.5rem", fontWeight: 700, marginBottom: "var(--space-1)" }}>
                            Session <code style={{ fontSize: "0.85em", color: "var(--color-primary-light)" }}>{id?.slice(0, 8)}</code>
                        </h1>
                        <div style={{ display: "flex", gap: "var(--space-3)", alignItems: "center" }}>
                            <WSStatusBadge status={wsStatus} />
                            {session && (
                                <span style={{ color: "var(--color-text-muted)", fontSize: "0.875rem" }}>
                                    {session.source_language?.toUpperCase()} → {session.target_language?.toUpperCase()}
                                </span>
                            )}
                        </div>
                    </div>
                    <button
                        id="btn-end-session"
                        className="btn btn-danger btn--sm"
                        onClick={handleEnd}
                        disabled={isEnding}
                    >
                        {isEnding ? "Ending…" : "End Session"}
                    </button>
                </div>

                {wsError && <div className="alert alert--error" style={{ marginBottom: "var(--space-4)" }}>{wsError}</div>}

                {/* Transcript */}
                <div className="transcript-box" ref={transcriptRef} aria-live="polite" aria-atomic="false">
                    {segments.length === 0 ? (
                        <div style={{ color: "var(--color-text-faint)", textAlign: "center", margin: "auto" }}>
                            {wsStatus === "connected"
                                ? "Start speaking — transcript will appear here."
                                : "Waiting for connection…"}
                        </div>
                    ) : (
                        segments.map((seg, i) => (
                            <div key={seg.segment_id ?? i} className={`transcript-segment${seg.is_interim ? " transcript-segment--interim" : ""}`}>
                                <span className="transcript-segment__speaker">{seg.speaker ?? "Speaker"}</span>
                                <span className="transcript-segment__original">{seg.original_text}</span>
                                {seg.translated_text && (
                                    <span className="transcript-segment__translated">{seg.translated_text}</span>
                                )}
                            </div>
                        ))
                    )}
                </div>

                <p style={{ marginTop: "var(--space-3)", color: "var(--color-text-faint)", fontSize: "0.8125rem", textAlign: "center" }}>
                    {segments.filter((s) => !s.is_interim).length} finalised segment(s)
                </p>
            </div>
        </div>
    );
}
