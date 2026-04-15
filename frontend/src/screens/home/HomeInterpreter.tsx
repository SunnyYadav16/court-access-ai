/**
 * screens/home/HomeInterpreter.tsx
 *
 * Interpreter home dashboard — renders INSIDE AppShell.
 * Dark-themed with live session card, translation review queue, and upcoming proceedings.
 *
 * Preserved logic: useAuth for user greeting, onNav for navigation.
 */

import { ScreenId, SCREENS } from "@/lib/constants"
import { useAuth } from "@/hooks/useAuth"
import { getFirstName } from "@/lib/utils"

interface Props { onNav: (s: ScreenId) => void }

const upcomingProceedings = [
  {
    time: "14:30",
    tz: "PM EST",
    title: "Civil Arbitration: Martinez v. Logistics Global",
    detail: "Mode: Consecutive • Legal Area: Maritime Law",
    aiAssisted: true,
  },
  {
    time: "16:00",
    tz: "PM EST",
    title: "Criminal Arraignment: Case #449-B",
    detail: "Mode: Simultaneous • Legal Area: Federal Criminal",
    aiAssisted: false,
  },
]

export default function HomeInterpreter({ onNav }: Props) {
  const { backendUser } = useAuth()
  const firstName = getFirstName(backendUser?.name, backendUser?.email)

  return (
    <div className="px-6 lg:px-8 py-8 max-w-7xl mx-auto space-y-10">

      {/* Welcome Banner */}
      <section className="max-w-6xl mx-auto">
        <div className="relative overflow-hidden rounded-xl bg-gradient-to-br from-primary-container to-surface-container-lowest p-10 shadow-2xl border border-white/5">
          <div className="relative z-10">
            <span className="bg-secondary text-on-secondary px-3 py-1 rounded-md text-xs font-bold uppercase tracking-wider mb-4 inline-block">
              Interpreter Role
            </span>
            <h1 className="font-headline text-5xl md:text-6xl text-on-surface mb-4 leading-tight">
              Welcome back,<br />
              <span className="text-secondary italic">{firstName}</span>
            </h1>
            <p className="text-on-surface-variant max-w-2xl text-lg font-body leading-relaxed">
              You have 3 scheduled court sessions and 12 pending transcriptions requiring formal certification.
              Your current accuracy rating remains at <span className="text-tertiary">99.8%</span>.
            </p>
          </div>
          <div className="absolute right-0 top-0 w-1/3 h-full opacity-10 pointer-events-none">
            <div className="w-full h-full bg-gradient-to-l from-secondary/20 to-transparent" />
          </div>
        </div>
      </section>

      {/* Feature Cards */}
      <section className="max-w-6xl mx-auto grid grid-cols-1 md:grid-cols-12 gap-8">

        {/* Join Real-Time Session */}
        <div
          role="button"
          tabIndex={0}
          onClick={() => onNav(SCREENS.REALTIME_SETUP)}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onNav(SCREENS.REALTIME_SETUP) } }}
          className="md:col-span-7 group cursor-pointer"
        >
          <div className="bg-surface-container-low h-full rounded-xl p-8 flex flex-col justify-between hover:bg-surface-container border border-transparent hover:border-secondary/20 transition-all duration-300 shadow-xl overflow-hidden relative">
            <div className="relative z-10">
              <div className="flex justify-between items-start mb-12">
                <div className="bg-secondary-container/20 p-4 rounded-xl">
                  <span className="material-symbols-outlined text-secondary text-4xl">video_chat</span>
                </div>
                <span className="flex items-center gap-2 bg-error-container/40 text-error px-3 py-1 rounded-full text-xs animate-pulse">
                  <span className="w-2 h-2 rounded-full bg-error" />
                  LIVE NOW
                </span>
              </div>
              <h3 className="font-headline text-3xl mb-4 text-on-surface">Join Real-Time Session</h3>
              <p className="text-on-surface-variant font-body mb-8 max-w-md">
                Provide live interpretation for active court cases. Real-time multi-language translation is ready.
              </p>
            </div>
            <div className="relative z-10 flex items-center gap-4">
              <span className="bg-secondary text-on-secondary px-8 py-3 rounded-md font-bold text-sm inline-flex items-center gap-2">
                Connect Terminal
                <span className="material-symbols-outlined text-sm">arrow_forward</span>
              </span>
              <span className="text-xs text-on-surface-variant italic">Latency: 14ms (Optimal)</span>
            </div>
            <div className="absolute inset-0 bg-gradient-to-tr from-secondary/5 to-transparent opacity-30 pointer-events-none" />
          </div>
        </div>

        {/* Translation Review */}
        <div
          role="button"
          tabIndex={0}
          onClick={() => onNav(SCREENS.INTERPRETER_REVIEW)}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onNav(SCREENS.INTERPRETER_REVIEW) } }}
          className="md:col-span-5 group cursor-pointer"
        >
          <div className="bg-primary-container h-full rounded-xl p-8 flex flex-col justify-between hover:bg-surface-container-high transition-all duration-300 shadow-xl relative overflow-hidden">
            <div className="relative z-10">
              <div className="bg-tertiary/10 w-fit p-4 rounded-xl mb-12">
                <span className="material-symbols-outlined text-tertiary text-4xl">verified_user</span>
              </div>
              <h3 className="font-headline text-3xl mb-4 text-on-surface">Translation Review</h3>
              <p className="text-on-surface-variant font-body mb-8">
                Review 4 pending AI-assisted translations for correctness and legal accuracy.
              </p>
            </div>
            <div className="relative z-10">
              <div className="flex -space-x-3 mb-6">
                {["ES", "FR", "RU"].map((lang) => (
                  <div key={lang} className="w-10 h-10 rounded-full border-2 border-primary-container bg-slate-600 flex items-center justify-center text-[10px] font-bold text-on-surface">
                    {lang}
                  </div>
                ))}
              </div>
              <span className="text-secondary border border-secondary/20 px-6 py-3 rounded-md font-bold text-sm inline-block">
                Open Queue
              </span>
            </div>
            <div className="absolute -right-4 -bottom-4 opacity-10">
              <span className="material-symbols-outlined text-[160px]" style={{ fontVariationSettings: "'FILL' 1" }}>translate</span>
            </div>
          </div>
        </div>
      </section>

      {/* Upcoming Proceedings */}
      <section className="max-w-6xl mx-auto">
        <h4 className="font-headline text-2xl mb-6 px-2 text-on-surface">Upcoming Proceedings</h4>
        <div className="flex flex-col gap-4">
          {upcomingProceedings.map((proc, i) => (
            <div key={i} className="bg-surface-container-low p-6 rounded-xl flex flex-wrap md:flex-nowrap items-center justify-between gap-6 hover:bg-surface-container-high transition-colors border border-white/5">
              <div className="flex items-center gap-6">
                <div className="text-center min-w-[60px]">
                  <p className={`font-bold text-xl leading-none ${i === 0 ? "text-secondary" : "text-on-surface-variant"}`}>
                    {proc.time}
                  </p>
                  <p className="text-[10px] text-slate-500 uppercase tracking-tighter">{proc.tz}</p>
                </div>
                <div className={`h-10 w-[2px] hidden md:block ${i === 0 ? "bg-secondary/30" : "bg-slate-800"}`} />
                <div>
                  <p className="font-bold text-on-surface">{proc.title}</p>
                  <p className="text-xs text-on-surface-variant">{proc.detail}</p>
                </div>
              </div>
              <div className="flex items-center gap-8">
                <div className="flex items-center gap-2">
                  <span className={`material-symbols-outlined text-sm ${proc.aiAssisted ? "text-tertiary" : "text-slate-500"}`}>
                    {proc.aiAssisted ? "auto_awesome" : "person"}
                  </span>
                  <span className={`text-xs font-label ${proc.aiAssisted ? "text-tertiary" : "text-slate-500"}`}>
                    {proc.aiAssisted ? "AI Assisted" : "Human Only"}
                  </span>
                </div>
                <button className="bg-surface-container-highest px-4 py-2 rounded-md text-xs font-bold hover:text-secondary transition-colors border-none cursor-pointer text-on-surface">
                  View Brief
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* FAB */}
      <button
        onClick={() => onNav(SCREENS.REALTIME_SETUP)}
        className="fixed bottom-8 right-8 bg-secondary text-on-secondary h-16 w-16 rounded-full shadow-2xl flex items-center justify-center hover:scale-105 transition-transform active:scale-95 z-50 border-none cursor-pointer"
      >
        <span className="material-symbols-outlined text-3xl" style={{ fontVariationSettings: "'FILL' 1" }}>add</span>
      </button>
    </div>
  )
}
