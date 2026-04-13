/**
 * screens/home/HomeAdmin.tsx
 *
 * Admin home dashboard — renders INSIDE AppShell.
 * Dark-themed bento grid with monitoring, user management, form management,
 * translation node, upload zone, and recent archives.
 *
 * Preserved logic: useAuth for user greeting, onNav for navigation.
 */

import { ScreenId, SCREENS } from "@/lib/constants"
import { useAuth } from "@/hooks/useAuth"
import { getFirstName } from "@/lib/utils"

interface Props { onNav: (s: ScreenId) => void }

export default function HomeAdmin({ onNav }: Props) {
  const { backendUser } = useAuth()
  const firstName = getFirstName(backendUser?.name, backendUser?.email)

  return (
    <div className="px-6 lg:px-8 py-8 max-w-7xl mx-auto space-y-8">

      {/* Welcome Banner */}
      <section className="relative overflow-hidden rounded-xl bg-gradient-to-r from-[#0D1B2A] to-[#1B263B] p-8 shadow-2xl">
        <div className="relative z-10">
          <div className="flex items-center gap-3 mb-2">
            <span className="px-3 py-1 bg-primary-fixed text-on-primary-fixed text-[10px] font-bold tracking-widest uppercase rounded">
              System Administrator
            </span>
            <span className="text-slate-400 text-xs">• Session Active</span>
          </div>
          <h1 className="text-4xl text-white font-headline mb-2">
            Welcome back, {firstName}.
          </h1>
          <p className="text-slate-400 max-w-2xl font-body">
            The ecosystem is currently operating within optimal parameters. All administrative modules are synchronized.
          </p>
        </div>
        <div className="absolute right-0 top-0 h-full w-1/3 opacity-20 pointer-events-none">
          <div className="absolute inset-0 bg-gradient-to-l from-secondary to-transparent" />
        </div>
      </section>

      {/* Bento Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">

        {/* Monitoring Dashboard (Large) */}
        <div
          role="button"
          tabIndex={0}
          onClick={() => onNav(SCREENS.ADMIN_DASHBOARD)}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onNav(SCREENS.ADMIN_DASHBOARD) } }}
          className="lg:col-span-2 lg:row-span-2 bg-surface-container-low rounded-xl p-8 flex flex-col justify-between group cursor-pointer transition-all hover:bg-surface-container-high relative overflow-hidden shadow-lg border border-white/5"
        >
          <div>
            <div className="flex justify-between items-start mb-6">
              <span className="material-symbols-outlined text-[#FFD700] text-4xl">monitoring</span>
              <span className="px-2 py-1 bg-green-900/30 text-green-400 text-[10px] font-bold rounded">
                LIVE SYSTEM HEALTH
              </span>
            </div>
            <h3 className="text-2xl text-white font-headline mb-4">Monitoring Dashboard</h3>
            <p className="text-slate-400 font-body mb-8 max-w-md">
              Real-time oversight of system latency, user traffic, and cryptographic verification logs.
              Current server load is 22%.
            </p>
            {/* Faux Data Visualization */}
            <div className="flex gap-2 items-end h-24">
              {[40, 65, 55, 90, 70, 80].map((h, i) => (
                <div
                  key={i}
                  className={`w-1/6 rounded-t-sm transition-all ${i === 3 ? "bg-[#FFD700]" : "bg-secondary/20 group-hover:bg-secondary/40"}`}
                  style={{ height: `${h}%` }}
                />
              ))}
            </div>
          </div>
          <div className="mt-8 flex justify-between items-center">
            <span className="text-sm font-label text-slate-500">Last scanned: 2 mins ago</span>
            <span className="text-[#FFD700] text-sm font-bold flex items-center gap-1 group-hover:translate-x-2 transition-transform">
              Full Report <span className="material-symbols-outlined text-sm">arrow_forward</span>
            </span>
          </div>
          <div className="absolute -right-24 -bottom-24 w-64 h-64 bg-[#FFD700]/5 rounded-full blur-3xl" />
        </div>

        {/* User Management */}
        <div
          role="button"
          tabIndex={0}
          onClick={() => onNav(SCREENS.ADMIN_USERS)}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onNav(SCREENS.ADMIN_USERS) } }}
          className="bg-surface-container-low rounded-xl p-6 hover:bg-surface-container-high transition-all border border-white/5 flex flex-col justify-between cursor-pointer"
        >
          <div>
            <span className="material-symbols-outlined text-tertiary mb-4 block">manage_accounts</span>
            <h3 className="text-xl text-white font-headline mb-2">User Management</h3>
            <p className="text-slate-500 text-sm font-body">
              Provision credentials and define hierarchical permissions.
            </p>
          </div>
          <div className="mt-6 flex -space-x-2">
            {["JD", "MR", "+12"].map((label, i) => (
              <div
                key={i}
                className={`w-8 h-8 rounded-full border-2 border-surface-container-low flex items-center justify-center text-[10px] font-bold ${
                  i < 2 ? "bg-slate-600 text-on-surface" : "bg-[#1B263B] text-[#FFD700]"
                }`}
              >
                {label}
              </div>
            ))}
          </div>
        </div>

        {/* Form Management */}
        <div
          role="button"
          tabIndex={0}
          onClick={() => onNav(SCREENS.ADMIN_FORMS)}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onNav(SCREENS.ADMIN_FORMS) } }}
          className="bg-surface-container-low rounded-xl p-6 hover:bg-surface-container-high transition-all border border-white/5 flex flex-col justify-between cursor-pointer"
        >
          <div>
            <span className="material-symbols-outlined text-secondary mb-4 block">edit_note</span>
            <h3 className="text-xl text-white font-headline mb-2">Form Management</h3>
            <p className="text-slate-500 text-sm font-body">
              Update dynamic legal templates and verify automated form logic.
            </p>
          </div>
          <div className="mt-6 pt-4 border-t border-white/5 text-xs text-slate-400">
            4 Drafts pending approval
          </div>
        </div>

        {/* Real-Time Translation Node */}
        <div
          role="button"
          tabIndex={0}
          onClick={() => onNav(SCREENS.REALTIME_SETUP)}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onNav(SCREENS.REALTIME_SETUP) } }}
          className="bg-gradient-to-br from-tertiary-container/40 to-surface-container-low rounded-xl p-6 backdrop-blur-md border border-tertiary/10 flex flex-col justify-between relative cursor-pointer"
        >
          <div className="absolute top-0 right-0 p-4">
            <span className="flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-error opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-error" />
            </span>
          </div>
          <div>
            <span className="material-symbols-outlined text-tertiary mb-4 block">translate</span>
            <h3 className="text-xl text-white font-headline mb-2">Translation Node</h3>
            <p className="text-slate-500 text-sm font-body">
              Neural engine monitoring for live sessions. Streams: 4.
            </p>
          </div>
          <div className="mt-6">
            <div className="bg-black/20 rounded p-2 text-[10px] font-mono text-tertiary">
              [ENG] &gt;&gt; [SPA] Accuracy: 99.2%
            </div>
          </div>
        </div>

        {/* Quick Upload */}
        <div
          role="button"
          tabIndex={0}
          onClick={() => onNav(SCREENS.DOC_UPLOAD)}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onNav(SCREENS.DOC_UPLOAD) } }}
          className="bg-surface-container-low rounded-xl p-6 hover:bg-surface-container-high transition-all border-2 border-dashed border-slate-700 flex flex-col justify-between cursor-pointer"
        >
          <div className="flex flex-col items-center justify-center h-full text-center py-4">
            <span className="material-symbols-outlined text-slate-500 text-4xl mb-4">cloud_upload</span>
            <h3 className="text-lg text-white font-headline mb-1">Quick Upload</h3>
            <p className="text-slate-500 text-xs font-body mb-4">Secure drag & drop vaulting</p>
            <span className="px-4 py-2 bg-slate-800 text-slate-300 rounded text-xs">
              Select Files
            </span>
          </div>
        </div>

        {/* Recent Archives */}
        <div
          role="button"
          tabIndex={0}
          onClick={() => onNav(SCREENS.DOC_HISTORY)}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onNav(SCREENS.DOC_HISTORY) } }}
          className="bg-surface-container-low rounded-xl p-6 hover:bg-surface-container-high transition-all border border-white/5 flex flex-col justify-between cursor-pointer"
        >
          <div>
            <span className="material-symbols-outlined text-[#FFD700] mb-4 block">history_edu</span>
            <h3 className="text-xl text-white font-headline mb-2">Recent Archives</h3>
            <p className="text-slate-500 text-sm font-body">
              Access recently verified transcriptions and certified documents.
            </p>
          </div>
          <div className="mt-6 flex gap-2 items-center">
            <span className="w-full h-1.5 bg-[#FFD700]/20 rounded-full overflow-hidden">
              <span className="block h-full w-[85%] bg-[#FFD700]" />
            </span>
            <span className="text-[10px] text-[#FFD700] font-bold">85%</span>
          </div>
        </div>
      </div>

      {/* Footer */}
      <footer className="flex flex-col md:flex-row justify-between items-center pt-8 border-t border-white/5 text-slate-600 text-xs gap-4">
        <div className="flex gap-6">
          <span>© 2026 CourtAccess AI. All Rights Reserved.</span>
          <span className="hover:text-white transition-colors cursor-pointer">Privacy Policy</span>
          <span className="hover:text-white transition-colors cursor-pointer">Audit Logs</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-green-500" />
          <span>All Systems Operational (Node: US-EAST-1)</span>
        </div>
      </footer>
    </div>
  )
}
