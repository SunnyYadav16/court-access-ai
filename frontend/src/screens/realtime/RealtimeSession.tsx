import { ScreenId, SCREENS } from "@/lib/constants"
import ScreenLabel from "@/components/shared/ScreenLabel"

interface Props { onNav: (s: ScreenId) => void }

const transcript = [
  { speaker: "Judge", text: "Good morning. We are here for the arraignment of case number 2026-CR-001234.", time: "9:15:02", isTranslation: false },
  { speaker: "AI → Spanish", text: "Buenos días. Estamos aquí para la lectura de cargos del caso número 2026-CR-001234.", time: "9:15:04", isTranslation: true },
  { speaker: "Defense", text: "Good morning, Your Honor. My client is present and ready to proceed.", time: "9:15:12", isTranslation: false },
  { speaker: "AI → Spanish", text: "Buenos días, Su Señoría. Mi cliente está presente y listo para proceder.", time: "9:15:14", isTranslation: true },
  { speaker: "Defendant", text: "No entiendo lo que está pasando. ¿Puedo hablar?", time: "9:15:28", isTranslation: false },
  { speaker: "AI → English", text: "I don't understand what is happening. Can I speak?", time: "9:15:30", isTranslation: true },
  { speaker: "Judge", text: "The defendant may address the court through their attorney.", time: "9:15:38", isTranslation: false },
  { speaker: "AI → Spanish", text: "El acusado puede dirigirse al tribunal a través de su abogado.", time: "9:15:40", isTranslation: true },
]

const sessionInfo = [
  ["Docket", "2026-CR-001234"],
  ["Court", "Boston Municipal"],
  ["Courtroom", "3"],
  ["Language", "English ↔ Spanish"],
  ["Started", "9:15:02 AM"],
]

const modelPipeline = [
  { name: "Silero VAD v4", color: "#16a34a" },
  { name: "Faster-Whisper V3", color: "#16a34a" },
  { name: "NLLB-200 1.3B", color: "#16a34a" },
  { name: "Piper TTS (es)", color: "#16a34a" },
  { name: "Llama 4 (Vertex AI)", color: "#d97706" },
]

const stats = [
  ["Utterances", "24"],
  ["Avg ASR Conf.", "0.94"],
  ["Avg NMT Conf.", "0.91"],
  ["Llama Corrections", "2"],
]

export default function RealtimeSession({ onNav }: Props) {
  return (
    <div className="min-h-screen flex flex-col" style={{ background: "#0D1B2A", color: "#fff" }}>

      {/* Header */}
      <div className="px-6 py-2.5 flex items-center justify-between"
        style={{ background: "rgba(0,0,0,0.3)", borderBottom: "1px solid rgba(255,255,255,0.08)" }}>
        <div className="flex items-center gap-3">
          <span className="font-bold tracking-wide" style={{ fontFamily: "Palatino, Georgia, serif" }}>
            ⚖ CourtAccess AI
          </span>
          <span className="text-[10px] font-semibold px-2 py-0.5 rounded"
            style={{ background: "rgba(239,68,68,0.15)", color: "#ef4444" }}>
            ● LIVE
          </span>
        </div>
        <div className="flex items-center gap-4 text-xs">
          <span style={{ color: "rgba(255,255,255,0.5)" }}>
            Session S-20260222-003 · 12:42 elapsed
          </span>
          <button
            onClick={() => onNav(SCREENS.HOME_OFFICIAL)}
            className="px-4 py-1.5 rounded text-xs font-semibold cursor-pointer"
            style={{ background: "#7f1d1d", color: "#fca5a5", border: "none" }}>
            End Session
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="flex flex-1 overflow-hidden">

        {/* Left: Transcript */}
        <div className="flex-1 flex flex-col">
          <div className="px-5 py-3 flex justify-between items-center text-xs"
            style={{ borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
            <span className="font-semibold">Live Transcript</span>
            <span style={{ color: "rgba(255,255,255,0.4)" }}>English ↔ Spanish</span>
          </div>

          <div className="flex-1 overflow-y-auto px-5 py-3 flex flex-col gap-3">
            {transcript.map((t, i) => (
              <div key={i} className="px-3 py-2 rounded-md"
                style={{
                  background: t.isTranslation ? "rgba(200,150,62,0.08)" : "rgba(255,255,255,0.03)",
                  borderLeft: `3px solid ${t.isTranslation ? "#C8963E" : "rgba(255,255,255,0.15)"}`,
                }}>
                <div className="flex justify-between mb-1">
                  <span className="text-[11px] font-semibold"
                    style={{ color: t.isTranslation ? "#C8963E" : "rgba(255,255,255,0.6)" }}>
                    {t.speaker}
                  </span>
                  <span className="text-[10px]" style={{ color: "rgba(255,255,255,0.3)" }}>
                    {t.time}
                  </span>
                </div>
                <p className="text-sm leading-relaxed m-0"
                  style={{ color: t.isTranslation ? "rgba(255,255,255,0.85)" : "rgba(255,255,255,0.7)" }}>
                  {t.text}
                </p>
              </div>
            ))}

            {/* Llama correction */}
            <div className="px-3 py-2 rounded-md"
              style={{ background: "rgba(37,99,235,0.1)", border: "1px solid rgba(37,99,235,0.2)" }}>
              <div className="text-[11px] font-semibold mb-1" style={{ color: "#60a5fa" }}>
                ⚡ Llama Legal Review — Correction
              </div>
              <p className="text-xs leading-relaxed m-0" style={{ color: "rgba(255,255,255,0.7)" }}>
                "arraignment" → corrected from{" "}
                <s style={{ color: "rgba(255,255,255,0.4)" }}>comparecencia</s> to{" "}
                <strong style={{ color: "#C8963E" }}>lectura de cargos</strong>
              </p>
            </div>
          </div>

          {/* Audio bar */}
          <div className="px-5 py-4 flex items-center gap-4"
            style={{ borderTop: "1px solid rgba(255,255,255,0.06)" }}>
            <div className="w-10 h-10 rounded-full flex items-center justify-center text-base flex-shrink-0"
              style={{ background: "rgba(239,68,68,0.15)", border: "2px solid #ef4444" }}>
              🎙
            </div>
            <div className="flex-1">
              <div className="flex gap-0.5 h-6 items-center mb-1">
                {Array.from({ length: 40 }, (_, i) => (
                  <div key={i} className="w-1 rounded-sm"
                    style={{
                      background: i % 3 === 0 ? "#ef4444" : "rgba(255,255,255,0.15)",
                      height: `${20 + Math.sin(i) * 15}px`,
                    }} />
                ))}
              </div>
              <div className="text-[10px]" style={{ color: "rgba(255,255,255,0.4)" }}>
                Listening · Silero VAD active · Faster-Whisper processing
              </div>
            </div>
            <div className="text-right">
              <div className="text-[11px]" style={{ color: "rgba(255,255,255,0.5)" }}>Confidence</div>
              <div className="text-lg font-bold" style={{ color: "#16a34a" }}>94%</div>
            </div>
          </div>
        </div>

        {/* Right: Info panel */}
        <div className="w-64 flex flex-col gap-5 p-4 text-xs overflow-y-auto"
          style={{ borderLeft: "1px solid rgba(255,255,255,0.06)" }}>

          {/* Session info */}
          <div>
            <div className="text-[11px] uppercase tracking-wider mb-2"
              style={{ color: "rgba(255,255,255,0.4)" }}>Session Info</div>
            {sessionInfo.map(([k, v]) => (
              <div key={k} className="flex justify-between py-1"
                style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                <span style={{ color: "rgba(255,255,255,0.4)" }}>{k}</span>
                <span style={{ color: "rgba(255,255,255,0.8)" }}>{v}</span>
              </div>
            ))}
          </div>

          {/* Model pipeline */}
          <div>
            <div className="text-[11px] uppercase tracking-wider mb-2"
              style={{ color: "rgba(255,255,255,0.4)" }}>Model Pipeline</div>
            {modelPipeline.map((m) => (
              <div key={m.name} className="flex items-center gap-2 py-1">
                <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: m.color }} />
                <span style={{ color: "rgba(255,255,255,0.7)" }}>{m.name}</span>
              </div>
            ))}
          </div>

          {/* Stats */}
          <div>
            <div className="text-[11px] uppercase tracking-wider mb-2"
              style={{ color: "rgba(255,255,255,0.4)" }}>Stats</div>
            {stats.map(([k, v]) => (
              <div key={k} className="flex justify-between py-1">
                <span style={{ color: "rgba(255,255,255,0.4)" }}>{k}</span>
                <span className="font-semibold" style={{ color: "rgba(255,255,255,0.8)" }}>{v}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
      <ScreenLabel name="REAL-TIME SESSION — LIVE TRANSLATION" />
    </div>
  )
}
