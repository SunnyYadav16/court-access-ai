/**
 * screens/home/HomeOfficial.tsx
 *
 * Court Official home dashboard — renders INSIDE AppShell.
 * Dark-themed bento grid layout with sessions table.
 *
 * Preserved logic: useAuth, toast from sessionStorage, recent sessions data.
 */

import { useEffect, useState } from "react"
import { ScreenId, SCREENS } from "@/lib/constants"
import { useAuth } from "@/hooks/useAuth"
import { getFirstName } from "@/lib/utils"

interface Props { onNav: (s: ScreenId) => void }

// TODO: Replace with sessionsApi call
const recentSessions = [
  { id: "#JS-22904", type: "Oral Testimony", typeIcon: "record_voice_over", lang: "Spanish › English", time: "10:45 AM", dur: "42m 12s", status: "VERIFIED" },
  { id: "#JS-22899", type: "Evidence Upload", typeIcon: "description", lang: "French › English", time: "09:12 AM", dur: "—", status: "VERIFIED" },
  { id: "#JS-22872", type: "Sentencing Session", typeIcon: "gavel", lang: "Mandarin › English", time: "Yesterday", dur: "1h 05m", status: "VERIFIED" },
  { id: "#JS-22861", type: "Deposition", typeIcon: "record_voice_over", lang: "Arabic › English", time: "Yesterday", dur: "28m 45s", status: "VERIFIED" },
]

export default function HomeOfficial({ onNav }: Props) {
  const { backendUser } = useAuth()
  const firstName = getFirstName(backendUser?.name, backendUser?.email)

  const [toast, setToast] = useState<string | null>(null)
  useEffect(() => {
    const msg = sessionStorage.getItem("pending_toast")
    if (!msg) return
    sessionStorage.removeItem("pending_toast")
    setToast(msg)
    const timerId: number = window.setTimeout(() => setToast(null), 4_000)
    return () => window.clearTimeout(timerId)
  }, [])

  return (
    <div className="px-6 lg:px-8 py-8 max-w-7xl mx-auto space-y-8">

      {/* Toast */}
      {toast && (
        <div className="flex justify-center">
          <div className="bg-surface-container-high border-l-4 border-secondary px-6 py-3 flex items-center gap-3 shadow-lg rounded-lg">
            <span className="material-symbols-outlined text-secondary" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
            <span className="text-on-surface font-medium">{toast}</span>
            <button
              onClick={() => setToast(null)}
              className="material-symbols-outlined text-on-surface-variant ml-4 text-sm bg-transparent border-none cursor-pointer"
            >
              close
            </button>
          </div>
        </div>
      )}

      {/* Welcome Banner */}
      <section className="max-w-6xl mx-auto">
        <div className="relative overflow-hidden rounded-xl bg-gradient-to-br from-primary-container to-surface-container-lowest p-10 shadow-2xl border border-white/5">
          <div className="flex flex-col md:flex-row justify-between items-start gap-6 relative z-10">
            <div>
              <span className="bg-secondary text-on-secondary px-3 py-1 rounded-md text-xs font-bold uppercase tracking-wider mb-4 inline-block">
                Court Official
              </span>
              <h1 className="font-headline text-5xl md:text-6xl text-on-surface mb-4 leading-tight">
                Welcome back,<br />
                <span className="text-secondary italic">{firstName}</span>
              </h1>
              <p className="text-on-surface-variant text-sm font-body uppercase tracking-widest">
                Official Access
              </p>
            </div>
            <div className="text-right hidden md:block">
              <p className="text-on-surface-variant font-medium text-sm mb-1 uppercase tracking-wider">
                Current Jurisdiction
              </p>
              <p className="text-secondary text-2xl font-headline">Central District Chambers</p>
            </div>
          </div>
          <div className="absolute top-0 right-0 w-64 h-64 bg-secondary/5 blur-[100px] rounded-full -translate-y-1/2 translate-x-1/2" />
        </div>
      </section>

      {/* Bento Feature Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">

        {/* Start Interpretation */}
        <div
          role="button"
          tabIndex={0}
          onClick={() => onNav(SCREENS.REALTIME_SETUP)}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onNav(SCREENS.REALTIME_SETUP) } }}
          className="md:col-span-2 group bg-surface-container-low p-8 rounded-xl border border-outline-variant/10 hover:border-secondary/30 transition-all cursor-pointer shadow-xl relative overflow-hidden"
        >
          <div className="absolute top-6 right-6 flex items-center gap-2 bg-error-container/20 px-3 py-1 rounded-full border border-error-container/50 animate-pulse">
            <div className="w-2 h-2 rounded-full bg-error" />
            <span className="text-error text-xs font-bold tracking-tighter">LIVE</span>
          </div>
          <span className="material-symbols-outlined text-4xl text-secondary mb-6 block">interpreter_mode</span>
          <h3 className="text-2xl font-headline mb-3 text-on-surface">Start Interpretation Session</h3>
          <p className="text-on-surface-variant text-sm mb-6 max-w-sm">
            Initiate secure, high-fidelity real-time audio translation for live court proceedings with neural verification.
          </p>
          <div className="flex items-center text-secondary font-bold text-sm group-hover:translate-x-2 transition-transform uppercase tracking-wider">
            Begin Session <span className="material-symbols-outlined ml-2">arrow_forward</span>
          </div>
        </div>

        {/* My Translations */}
        <div
          role="button"
          tabIndex={0}
          onClick={() => onNav(SCREENS.DOC_HISTORY)}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onNav(SCREENS.DOC_HISTORY) } }}
          className="md:col-span-2 bg-surface-container-low p-8 rounded-xl border border-outline-variant/10 hover:border-secondary/30 transition-all cursor-pointer shadow-xl flex items-center justify-between group overflow-hidden"
        >
          <div className="max-w-[70%]">
            <span className="material-symbols-outlined text-4xl text-secondary mb-6 block">translate</span>
            <h3 className="text-2xl font-headline mb-2 text-on-surface">My Translations</h3>
            <p className="text-on-surface-variant text-sm">
              Review, edit, and certify recently processed multilingual documents and transcripts.
            </p>
          </div>
          <div className="h-full flex items-center opacity-20 group-hover:opacity-40 transition-opacity">
            <span className="material-symbols-outlined text-9xl">article</span>
          </div>
        </div>

        {/* Upload Document */}
        <div
          role="button"
          tabIndex={0}
          onClick={() => onNav(SCREENS.DOC_UPLOAD)}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onNav(SCREENS.DOC_UPLOAD) } }}
          className="md:col-span-2 bg-surface-container-low p-6 rounded-xl border border-outline-variant/10 hover:border-secondary/30 transition-all cursor-pointer shadow-lg group"
        >
          <span className="material-symbols-outlined text-3xl text-secondary mb-4 block">upload_file</span>
          <h3 className="text-xl font-headline text-on-surface mb-2">Upload Document</h3>
          <p className="text-on-surface-variant text-sm">Upload a legal PDF for AI-powered translation.</p>
        </div>

        {/* Government Forms */}
        <div
          role="button"
          tabIndex={0}
          onClick={() => onNav(SCREENS.FORMS_LIBRARY)}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onNav(SCREENS.FORMS_LIBRARY) } }}
          className="md:col-span-2 bg-surface-container-low p-6 rounded-xl border border-outline-variant/10 hover:border-secondary/30 transition-all cursor-pointer shadow-lg group"
        >
          <span className="material-symbols-outlined text-3xl text-secondary mb-4 block">account_balance</span>
          <h3 className="text-xl font-headline text-on-surface mb-2">Government Forms</h3>
          <p className="text-on-surface-variant text-sm">Browse pre-translated Massachusetts court forms.</p>
        </div>

        {/* System Verification */}
        <div className="md:col-span-4 bg-primary-container p-8 rounded-xl border border-outline-variant/10 shadow-xl flex items-center gap-6">
          <div className="p-4 rounded-full bg-secondary/10">
            <span className="material-symbols-outlined text-secondary text-3xl">verified_user</span>
          </div>
          <div>
            <h4 className="text-on-primary font-bold text-lg">System Verification Active</h4>
            <p className="text-on-primary-container text-xs">
              Neural engines running at 99.8% precision for English-Spanish-Mandarin pairs.
            </p>
          </div>
        </div>
      </div>

      {/* Recent Sessions Table */}
      <section className="bg-surface-container-low rounded-xl shadow-2xl overflow-hidden">
        <div className="px-8 py-6 flex justify-between items-center">
          <h2 className="text-2xl font-headline text-on-surface">Recent Sessions</h2>
          <button
            onClick={() => onNav(SCREENS.DOC_HISTORY)}
            className="text-secondary text-sm font-bold flex items-center hover:underline uppercase tracking-wider bg-transparent border-none cursor-pointer"
          >
            View All <span className="material-symbols-outlined ml-1 text-sm">open_in_new</span>
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-surface-container-high/50 text-on-surface-variant uppercase text-[10px] tracking-widest font-bold">
                <th className="px-8 py-4">Session ID</th>
                <th className="px-8 py-4">Type</th>
                <th className="px-8 py-4">Language</th>
                <th className="px-8 py-4">Time</th>
                <th className="px-8 py-4">Duration</th>
                <th className="px-8 py-4 text-right">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant/10">
              {recentSessions.map((s) => (
                <tr key={s.id} className="hover:bg-surface-container-highest/30 transition-colors">
                  <td className="px-8 py-5 font-mono text-xs text-secondary">{s.id}</td>
                  <td className="px-8 py-5">
                    <div className="flex items-center gap-2">
                      <span className="material-symbols-outlined text-sm text-on-tertiary-container">{s.typeIcon}</span>
                      <span className="text-on-surface text-sm">{s.type}</span>
                    </div>
                  </td>
                  <td className="px-8 py-5 text-on-surface-variant text-sm">{s.lang}</td>
                  <td className="px-8 py-5 text-on-surface-variant text-sm">{s.time}</td>
                  <td className="px-8 py-5 text-on-surface-variant text-sm">{s.dur}</td>
                  <td className="px-8 py-5 text-right">
                    <span className="px-3 py-1 rounded-full bg-primary-container text-primary text-[10px] font-bold">
                      {s.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* FAB */}
      <button
        onClick={() => onNav(SCREENS.REALTIME_SETUP)}
        className="fixed bottom-8 right-8 bg-[#FFD700] text-[#0D1B2A] w-16 h-16 rounded-full shadow-[0px_12px_32px_rgba(0,0,0,0.4)] flex items-center justify-center hover:scale-105 transition-transform group z-50 border-none cursor-pointer"
      >
        <span className="material-symbols-outlined text-3xl">mic</span>
        <span className="absolute right-20 bg-surface-container-highest text-on-surface px-4 py-2 rounded-lg text-sm font-bold opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none shadow-xl">
          Start Recording
        </span>
      </button>
    </div>
  )
}
