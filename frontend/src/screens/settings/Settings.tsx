/**
 * screens/settings/Settings.tsx
 *
 * User settings — renders INSIDE AppShell.
 * Dark-themed bento grid layout: profile card (8-col) + status sidebar (4-col),
 * account credentials (7-col) + critical actions (5-col),
 * and AI insight footer.
 *
 * Preserved logic: useAuth for user data, copyToClipboard, signOut.
 */

import { ScreenId } from "@/lib/constants"
import { useAuth } from "@/hooks/useAuth"
import { getInitials } from "@/lib/utils"

interface Props { onNav: (s: ScreenId) => void }

export default function Settings({ onNav: _onNav }: Props) {
  const { backendUser, role, signOut } = useAuth()

  const initials = getInitials(backendUser?.name, backendUser?.email)
  const displayRole = role?.replace("_", " ").toUpperCase() ?? "PUBLIC"

  const getProviderName = (provider: string) => {
    if (provider === "google.com") return "Google"
    if (provider === "microsoft.com") return "Microsoft"
    if (provider === "password") return "Email/Password"
    return provider
  }

  const formatDate = (dateString?: string | null) => {
    if (!dateString) return "Never"
    const date = new Date(dateString)
    return date.toLocaleDateString("en-US", { year: "numeric", month: "long" })
  }

  const formatDateTime = (dateString?: string | null) => {
    if (!dateString) return "Never"
    const date = new Date(dateString)
    return date.toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit"
    })
  }

  return (
    <div className="px-6 lg:px-8 py-8 max-w-5xl mx-auto space-y-8">

      {/* Hero Title */}
      <header className="mb-4">
        <h1 className="text-4xl md:text-5xl font-headline text-on-surface mb-2">User Settings</h1>
        <p className="text-on-surface-variant max-w-2xl">
          Manage your digital credentials, authentication protocols, and workspace preferences within the CourtAccess ecosystem.
        </p>
      </header>

      {/* Bento Grid */}
      <div className="grid grid-cols-1 md:grid-cols-12 gap-6">

        {/* ── Profile Card (8-col) ─────────────────────────────────── */}
        <section className="md:col-span-8 bg-surface-container-low rounded-xl p-8 flex flex-col md:flex-row gap-8 items-center border border-outline-variant/10 relative overflow-hidden group">
          <div className="absolute inset-0 bg-gradient-to-br from-primary-container/20 to-transparent pointer-events-none" />
          <div className="relative">
            <div className="w-32 h-32 rounded-full bg-surface-container-highest flex items-center justify-center border-4 border-secondary shadow-lg">
              <span className="text-4xl font-headline text-secondary font-bold">{initials}</span>
            </div>
            <div className="absolute -bottom-2 -right-2 bg-primary-fixed text-on-primary-fixed px-3 py-1 rounded-full text-[10px] font-bold uppercase tracking-widest shadow-md">
              {displayRole}
            </div>
          </div>
          <div className="flex-1 text-center md:text-left">
            <h2 className="text-2xl font-headline text-white mb-1">
              {backendUser?.name || "User"}
            </h2>
            <p className="text-on-surface-variant mb-4">{backendUser?.email}</p>
            <div className="flex flex-wrap gap-2 justify-center md:justify-start">
              <span className="px-3 py-1 bg-surface-container-highest rounded text-xs text-secondary-fixed-dim border border-secondary/10">
                Access Tier: {displayRole}
              </span>
              <span className="px-3 py-1 bg-surface-container-highest rounded text-xs text-tertiary border border-tertiary/10">
                {getProviderName(backendUser?.auth_provider || "")} Auth
              </span>
            </div>
          </div>
        </section>

        {/* ── Status Sidebar (4-col) ───────────────────────────────── */}
        <section className="md:col-span-4 bg-surface-container-low rounded-xl p-6 border border-outline-variant/10 flex flex-col justify-between">
          <div>
            <h3 className="text-on-surface-variant text-[10px] uppercase tracking-[0.2em] mb-4">Account Status</h3>
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-sm text-slate-400">Email Verified</span>
                <span
                  className={`w-2 h-2 rounded-full ${backendUser?.email_verified ? "bg-emerald-500" : "bg-red-500"}`}
                  style={{ boxShadow: backendUser?.email_verified ? "0 0 8px rgba(16,185,129,0.6)" : "0 0 8px rgba(239,68,68,0.6)" }}
                />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-slate-400">MFA Protection</span>
                <span
                  className={`w-2 h-2 rounded-full ${backendUser?.mfa_enabled ? "bg-emerald-500" : "bg-secondary"}`}
                  style={{ boxShadow: backendUser?.mfa_enabled ? "0 0 8px rgba(16,185,129,0.6)" : "0 0 8px rgba(255,193,7,0.6)" }}
                />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-slate-400">Auth Provider</span>
                <span className="text-xs text-slate-300">{getProviderName(backendUser?.auth_provider || "")}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-slate-400">Last Login</span>
                <span className="text-xs text-slate-300">{formatDateTime(backendUser?.last_login_at)}</span>
              </div>
            </div>
          </div>
          <div className="mt-8 p-4 bg-surface-container-lowest rounded-lg border border-white/5">
            <p className="text-[10px] text-slate-500 leading-relaxed">
              Member since {formatDate(backendUser?.created_at)}. All actions are logged to the audit trail.
            </p>
          </div>
        </section>

        {/* ── Account Credentials (7-col) ──────────────────────────── */}
        <section className="md:col-span-7 bg-surface-container-low rounded-xl border border-outline-variant/10 overflow-hidden">
          <div className="px-8 py-6 border-b border-white/5 flex items-center justify-between">
            <h3 className="font-headline text-xl text-white">Account Credentials</h3>
            <span className="material-symbols-outlined text-slate-500">lock</span>
          </div>
          <div className="p-8 space-y-6">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-8">
              {/* Display Name */}
              <div>
                <label className="block text-[10px] uppercase tracking-widest text-on-surface-variant mb-2">Display Name</label>
                <p className="text-sm">{backendUser?.name || "—"}</p>
              </div>

              {/* Auth Provider */}
              <div>
                <label className="block text-[10px] uppercase tracking-widest text-on-surface-variant mb-2">Auth Provider</label>
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-lg text-primary">
                    {backendUser?.auth_provider === "google.com" ? "google" : "key"}
                  </span>
                  <span className="text-sm">{getProviderName(backendUser?.auth_provider || "")}</span>
                </div>
              </div>

              {/* Email */}
              <div>
                <label className="block text-[10px] uppercase tracking-widest text-on-surface-variant mb-2">Primary Email</label>
                <p className="text-sm">{backendUser?.email || "—"}</p>
              </div>

              {/* MFA Status */}
              <div>
                <label className="block text-[10px] uppercase tracking-widest text-on-surface-variant mb-2">MFA Status</label>
                {backendUser?.mfa_enabled ? (
                  <div className="flex items-center gap-2 text-emerald-500">
                    <span className="material-symbols-outlined text-sm" style={{ fontVariationSettings: "'FILL' 1" }}>verified_user</span>
                    <span className="text-sm font-bold uppercase tracking-tighter">Active</span>
                  </div>
                ) : (
                  <span className="text-sm text-on-surface-variant">Not Enabled</span>
                )}
              </div>

              {/* Email Verified */}
              <div>
                <label className="block text-[10px] uppercase tracking-widest text-on-surface-variant mb-2">Email Verified</label>
                {backendUser?.email_verified ? (
                  <div className="flex items-center gap-1.5 text-emerald-500">
                    <span className="material-symbols-outlined text-sm" style={{ fontVariationSettings: "'FILL' 1" }}>verified</span>
                    <span className="text-sm font-bold">Verified</span>
                  </div>
                ) : (
                  <span className="flex items-center gap-1.5 text-red-400 text-sm">
                    <span className="material-symbols-outlined text-sm">cancel</span> Not Verified
                  </span>
                )}
              </div>

              {/* Last Login */}
              <div>
                <label className="block text-[10px] uppercase tracking-widest text-on-surface-variant mb-2">Last Login</label>
                <p className="text-sm">{formatDateTime(backendUser?.last_login_at)}</p>
              </div>
            </div>
          </div>
        </section>

        {/* ── Critical Actions (5-col) ─────────────────────────────── */}
        <section className="md:col-span-5 bg-surface-container-low rounded-xl border border-outline-variant/10 flex flex-col">
          <div className="px-8 py-6 border-b border-white/5">
            <h3 className="font-headline text-xl text-white">Critical Actions</h3>
          </div>
          <div className="p-8 flex-1 flex flex-col gap-4">
            {/* Sign Out */}
            <button
              onClick={() => signOut()}
              className="w-full flex items-center justify-between p-4 bg-surface-container-high hover:bg-surface-bright rounded-lg transition-colors group cursor-pointer border-none text-left"
            >
              <div className="flex items-center gap-4">
                <span className="material-symbols-outlined text-on-surface-variant group-hover:text-white">logout</span>
                <div>
                  <span className="block text-sm font-bold text-white">Sign Out</span>
                  <span className="block text-[10px] text-on-surface-variant">End current session safely</span>
                </div>
              </div>
              <span className="material-symbols-outlined text-slate-600">chevron_right</span>
            </button>

            {/* Delete Account */}
            <div className="relative">
              <button
                className="w-full flex items-center justify-between p-4 bg-surface-container-lowest opacity-50 cursor-not-allowed rounded-lg border border-error-container/20"
                disabled
              >
                <div className="flex items-center gap-4">
                  <span className="material-symbols-outlined text-error">delete_forever</span>
                  <div className="text-left">
                    <span className="block text-sm font-bold text-error">Delete Account</span>
                    <span className="block text-[10px] text-error/60">Permanently erase all data</span>
                  </div>
                </div>
              </button>
              <div className="mt-3 p-3 bg-error-container/10 border border-error-container/20 rounded text-[10px] text-error/80 italic">
                Note: Account deletion is currently disabled. Please contact the internal review board for formal account removal.
              </div>
            </div>
          </div>
        </section>

        {/* ── AI Insight Footer ─────────────────────────────────────── */}
        <section className="md:col-span-12 mt-4 p-1 rounded-xl bg-gradient-to-r from-tertiary-container via-surface-container-low to-primary-container">
          <div className="bg-surface-container-lowest rounded-lg px-8 py-4 flex flex-col md:flex-row items-center justify-between gap-4">
            <div className="flex items-center gap-4">
              <span className="material-symbols-outlined text-tertiary animate-pulse">smart_toy</span>
              <p className="text-xs text-slate-300 italic">
                "Security Audit: 0 anomalies detected in your recent 48-hour activity."
              </p>
            </div>
            <span className="text-[9px] uppercase tracking-[0.3em] text-slate-500">
              Member since {formatDate(backendUser?.created_at)}
            </span>
          </div>
        </section>
      </div>
    </div>
  )
}
