/**
 * screens/realtime/RealtimeSetup.tsx
 *
 * Realtime session setup — renders INSIDE AppShell.
 * Dark-themed 2-column layout: form card (8-col) + sidebar info (4-col).
 *
 * Preserved logic: realtimeApi.createRoom(), realtimeStore state,
 * form validation, consent checkbox, navigation to lobby.
 */

import { useState } from "react"
import { ScreenId, SCREENS } from "@/lib/constants"
import useRealtimeStore from "@/store/realtimeStore"
import { realtimeApi } from "@/services/api"
import { useAuth } from "@/hooks/useAuth"
import { getFirstName } from "@/lib/utils"

// ── Constants ─────────────────────────────────────────────────────────────────

const PARTNER_LANGUAGES = [
  { value: "es", label: "Spanish (Español)" },
  { value: "pt", label: "Portuguese (Português)" },
] as const

type PartnerLang = "es" | "pt"

const COURT_DIVISIONS = [
  "Boston Municipal Court",
  "Worcester District Court",
  "Suffolk Superior Court",
  "Springfield District Court",
  "Cambridge District Court",
  "Middlesex Superior Court",
]

const COURTROOMS = [
  "Courtroom 1",
  "Courtroom 3",
  "Courtroom 5A",
  "Courtroom 7",
  "Courtroom 12",
  "Courtroom 14B",
]

// ── Component ─────────────────────────────────────────────────────────────────

interface Props { onNav: (s: ScreenId) => void }

export default function RealtimeSetup({ onNav }: Props) {
  const { backendUser } = useAuth()
  const officialName = getFirstName(backendUser?.name, backendUser?.email)

  // Store
  const setMyName    = useRealtimeStore((s) => s.setMyName)
  const setMyLanguage = useRealtimeStore((s) => s.setMyLanguage)
  const setCourtInfo = useRealtimeStore((s) => s.setCourtInfo)
  const setLobbyInfo = useRealtimeStore((s) => s.setLobbyInfo)

  // Form state
  const [partnerLang, setPartnerLang] = useState<PartnerLang>("es")
  const [division, setDivision]       = useState(COURT_DIVISIONS[0])
  const [courtroom, setCourtroom]     = useState(COURTROOMS[0])
  const [docket, setDocket]           = useState("")
  const [partnerName, setPartnerName] = useState("")
  const [consent, setConsent]         = useState(false)

  // Submission state
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState<string | null>(null)

  // ── Submit ───────────────────────────────────────────────────────────────────

  async function handleSubmit() {
    if (!partnerName.trim()) {
      setError("Please enter the LEP individual's name.")
      return
    }
    if (!consent) {
      setError("Both parties must be informed before starting the session.")
      return
    }

    setError(null)
    setLoading(true)

    try {
      const res = await realtimeApi.createRoom({
        target_language: partnerLang,
        court_division: division,
        courtroom,
        case_docket: docket.trim() || null,
        partner_name: partnerName.trim(),
        consent_acknowledged: true,
      })

      setMyName(backendUser?.name ?? officialName)
      setMyLanguage("en")
      setCourtInfo(division, courtroom, docket.trim())
      setLobbyInfo(res.session_id, res.room_code, res.join_url, res.room_code_expires_at, partnerName.trim(), partnerLang)

      onNav(SCREENS.REALTIME_LOBBY)
    } catch (err: unknown) {
      const msg =
        err instanceof Error
          ? err.message
          : "Failed to create room. Please try again."
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  // ── Shared input classes ─────────────────────────────────────────────────────

  const inputCls = "w-full bg-surface-container-highest border-none rounded-lg p-3 text-white focus:ring-2 focus:ring-amber-500 transition-all placeholder:text-slate-600 outline-none"
  const selectCls = "w-full bg-surface-container-highest border-none rounded-lg p-3 text-white focus:ring-2 focus:ring-amber-500 transition-all appearance-none outline-none"

  // ── Render ────────────────────────────────────────────────────────────────────

  return (
    <div className="px-6 lg:px-10 py-8 max-w-4xl mx-auto space-y-8">

      {/* Header */}
      <header className="mb-4">
        <h1 className="text-4xl font-headline font-bold text-white mb-2">Realtime Session Setup</h1>
        <p className="text-on-surface-variant text-lg">
          Configure the digital infrastructure for upcoming proceedings.
        </p>
      </header>

      {/* Error banner */}
      {error && (
        <div className="rounded-lg px-4 py-3 text-sm bg-red-950 border border-red-900 text-red-300">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-12 gap-8">

        {/* ── Session Configuration Card (8-col) ─────────────────────── */}
        <section className="md:col-span-8 bg-surface-container-low rounded-xl p-8 shadow-xl space-y-8">

          {/* Notice bar */}
          <div className="flex items-center gap-4 bg-primary-container/40 p-4 rounded-lg border border-primary-container/60">
            <span className="material-symbols-outlined text-primary">info</span>
            <p className="text-primary text-sm font-medium">
              Microphone required for both participants. Court official (you) will speak English.
            </p>
          </div>

          {/* Row: Name + Language */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <label htmlFor="partner-name" className="block text-xs font-bold uppercase tracking-widest text-on-surface-variant mb-2">
                LEP Individual's Name <span className="text-red-400">*</span>
              </label>
              <input
                id="partner-name"
                type="text"
                value={partnerName}
                onChange={(e) => setPartnerName(e.target.value)}
                placeholder="Full Legal Name"
                maxLength={100}
                disabled={loading}
                className={inputCls}
              />
            </div>
            <div>
              <label htmlFor="partner-language" className="block text-xs font-bold uppercase tracking-widest text-on-surface-variant mb-2">
                Primary Language <span className="text-red-400">*</span>
              </label>
              <select
                id="partner-language"
                value={partnerLang}
                onChange={(e) => setPartnerLang(e.target.value as PartnerLang)}
                className={selectCls}
              >
                {PARTNER_LANGUAGES.map((l) => (
                  <option key={l.value} value={l.value}>{l.label}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Row: Division + Courtroom */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <label htmlFor="court-division" className="block text-xs font-bold uppercase tracking-widest text-on-surface-variant mb-2">
                Court Division <span className="text-red-400">*</span>
              </label>
              <select
                id="court-division"
                value={division}
                onChange={(e) => setDivision(e.target.value)}
                className={selectCls}
              >
                {COURT_DIVISIONS.map((d) => (
                  <option key={d} value={d}>{d}</option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="courtroom-select" className="block text-xs font-bold uppercase tracking-widest text-on-surface-variant mb-2">
                Courtroom <span className="text-red-400">*</span>
              </label>
              <select
                id="courtroom-select"
                value={courtroom}
                onChange={(e) => setCourtroom(e.target.value)}
                className={selectCls}
              >
                {COURTROOMS.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Case Docket */}
          <div>
            <label htmlFor="case-docket" className="block text-xs font-bold uppercase tracking-widest text-on-surface-variant mb-2">
              Case Docket (Optional)
            </label>
            <input
              id="case-docket"
              type="text"
              value={docket}
              onChange={(e) => setDocket(e.target.value)}
              placeholder="e.g. 2026-CR-001234"
              maxLength={50}
              disabled={loading}
              className={inputCls}
            />
          </div>

          {/* Consent */}
          <div className="flex items-start gap-3 pt-4 border-t border-white/5">
            <input
              id="consent-checkbox"
              type="checkbox"
              className="mt-1 bg-surface-container-highest border-none rounded text-amber-500 focus:ring-amber-500 cursor-pointer"
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
              disabled={loading}
            />
            <label htmlFor="consent-checkbox" className="text-sm text-on-surface-variant leading-relaxed cursor-pointer">
              Both parties informed of digital transcription and translation assistance.
              Recorded session will be securely stored in accordance with district protocol.
            </label>
          </div>

          {/* Submit */}
          <button
            className="w-full py-4 bg-amber-500 text-on-secondary font-bold text-lg rounded-lg shadow-lg shadow-amber-500/20 active:scale-[0.98] transition-all flex items-center justify-center gap-3 cursor-pointer disabled:opacity-50 border-none"
            onClick={handleSubmit}
            disabled={loading}
          >
            <span className="material-symbols-outlined">bolt</span>
            {loading ? "Creating session…" : "Create Session"}
          </button>
        </section>

        {/* ── Sidebar (4-col) ─────────────────────────────────────────── */}
        <aside className="md:col-span-4 space-y-6">
          {/* Integrity Guard */}
          <div className="bg-surface-container-low p-6 rounded-xl border-l-4 border-amber-500/30">
            <h4 className="font-headline text-xl text-white mb-4">Integrity Guard</h4>
            <div className="flex items-center gap-3 mb-4">
              <div className="w-8 h-8 rounded-full bg-primary-container flex items-center justify-center text-primary">
                <span className="material-symbols-outlined text-sm" style={{ fontVariationSettings: "'FILL' 1" }}>lock</span>
              </div>
              <p className="text-xs font-medium text-slate-300">End-to-end encrypted session</p>
            </div>
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-full bg-primary-container flex items-center justify-center text-primary">
                <span className="material-symbols-outlined text-sm" style={{ fontVariationSettings: "'FILL' 1" }}>verified_user</span>
              </div>
              <p className="text-xs font-medium text-slate-300">AI-verified legal translation</p>
            </div>
          </div>

          {/* Decorative quote card */}
          <div className="bg-surface-container-lowest overflow-hidden rounded-xl h-64 relative group">
            <div className="absolute inset-0 bg-gradient-to-t from-[#0D1B2A] to-transparent" />
            <div className="absolute inset-0 bg-primary-container/30" />
            <div className="absolute inset-0 flex flex-col justify-end p-6">
              <p className="text-amber-400 font-headline italic text-lg">"Justice delayed is justice denied."</p>
              <p className="text-slate-400 text-xs mt-2">— William E. Gladstone</p>
            </div>
          </div>
        </aside>
      </div>
    </div>
  )
}
