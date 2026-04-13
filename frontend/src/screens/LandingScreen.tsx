/**
 * screens/LandingScreen.tsx
 *
 * Public landing page for unauthenticated users.
 * Renders OUTSIDE AppShell — has its own inline nav and footer.
 * Migrated from the `landing_page/code.html` design mockup.
 *
 * Preserved logic:
 *   - openAuthModal("login") for sign-in buttons
 *   - openAuthModal("signup") for "Create one for free" link
 */

import type { ScreenId } from "@/lib/constants"
import useAuthStore from "@/store/authStore"

interface Props {
  onNav: (s: ScreenId) => void
}

// ── Service card data ──────────────────────────────────────────────────────

const services = [
  {
    icon: "description",
    title: "Document Translation",
    who: "For the public",
    desc: "Instant, accurate translation of legal notices, evidence, and filings. Optimized for the public to understand complex legal jargon.",
  },
  {
    icon: "mic",
    title: "Real-Time Interpretation",
    who: "For court officials",
    desc: "Low-latency audio-to-text and text-to-speech interpretation designed for active courtroom dialogue and legal counsel.",
  },
  {
    icon: "account_balance",
    title: "Government Forms",
    who: "For everyone",
    desc: "Guided assistance for completing court-mandated documentation with automated multilingual validation.",
  },
]

// ── Feature pill data ──────────────────────────────────────────────────────

const features = [
  { icon: "language", emoji: "🌐", label: "Spanish & Portuguese" },
  { icon: "bolt", emoji: "⚡", label: "Real-Time AI Processing" },
  { icon: "assignment", emoji: "📋", label: "45+ Court Forms" },
  { icon: "lock", emoji: "🔒", label: "Secure & Private" },
]

// ── Component ──────────────────────────────────────────────────────────────

export default function LandingScreen({ onNav: _onNav }: Props) {
  const openAuthModal = useAuthStore((s) => s.openAuthModal)

  return (
    <div className="min-h-screen text-on-surface font-body selection:bg-secondary-container selection:text-on-secondary-container relative">

      {/* Fixed background overlay with justice statue */}
      <div className="page-bg-overlay" />

      {/* ── Top Nav Bar ────────────────────────────────────────────── */}
      <nav className="fixed top-0 left-0 w-full z-50 flex justify-between items-center px-6 h-14 bg-[#0D1B2A]/90 backdrop-blur-md shadow-xl shadow-black/40">
        <div className="flex items-center gap-4">
          <span className="font-headline text-xl font-semibold text-white tracking-tight">
            CourtAccess AI
          </span>
          <span className="bg-secondary-container text-on-secondary-container px-2 py-0.5 rounded-lg text-[10px] font-bold tracking-widest uppercase">
            BETA
          </span>
        </div>
        <div className="flex items-center gap-6">
          <button
            onClick={() => openAuthModal("login")}
            className="bg-secondary-fixed-dim text-on-secondary-fixed px-5 py-1.5 rounded-lg font-medium text-sm hover:brightness-110 transition-all active:scale-95 cursor-pointer"
          >
            Sign In
          </button>
        </div>
      </nav>

      <main className="pt-14 relative z-10">

        {/* ── Hero Section ──────────────────────────────────────────── */}
        <section className="relative min-h-[870px] flex flex-col items-center justify-center text-center px-6 overflow-hidden">
          {/* Local decorative background enhancements */}
          <div className="absolute top-1/4 left-1/2 -translate-x-1/2 w-[800px] h-[400px] bg-secondary-fixed-dim/5 blur-[120px] rounded-full z-[-1]" />

          <div className="max-w-4xl mx-auto space-y-8">
            {/* Gavel icon */}
            <div className="inline-flex items-center justify-center p-4 rounded-full bg-surface-container-highest/60 backdrop-blur-sm border border-outline-variant/15 text-secondary shadow-2xl">
              <span
                className="material-symbols-outlined text-5xl"
                style={{ fontVariationSettings: "'FILL' 0" }}
              >
                gavel
              </span>
            </div>

            {/* Headline */}
            <h1 className="text-5xl md:text-7xl font-bold text-on-surface tracking-tight leading-[1.1] font-headline">
              AI-Powered Legal Translation <br />
              <span className="text-secondary italic font-normal">&amp; Interpretation</span>
            </h1>

            {/* Subhead */}
            <p className="text-lg md:text-xl text-on-surface-variant max-w-2xl mx-auto leading-relaxed">
              Democratizing justice through linguistic precision. Our platform
              provides high-fidelity, legally-aware translation tools to ensure
              every voice is heard in the courtroom, regardless of language.
            </p>

            {/* Feature pills */}
            <div className="flex flex-wrap justify-center gap-3 mt-8">
              {features.map((f) => (
                <span
                  key={f.label}
                  className="px-4 py-2 rounded-full bg-surface-container-low/40 backdrop-blur-sm border border-outline-variant/15 text-sm font-medium flex items-center gap-2"
                >
                  <span className="material-symbols-outlined text-primary text-lg">
                    {f.icon}
                  </span>
                  {f.emoji} {f.label}
                </span>
              ))}
            </div>

            {/* CTA */}
            <div className="flex flex-col items-center gap-4 pt-6">
              <button
                onClick={() => openAuthModal("login")}
                className="bg-secondary-fixed-dim text-on-secondary-fixed px-8 py-4 rounded-lg font-bold text-lg shadow-lg shadow-secondary-fixed-dim/20 hover:brightness-110 transition-all active:scale-95 cursor-pointer"
              >
                Sign In to Use Services
              </button>
              <button
                onClick={() => openAuthModal("signup")}
                className="text-on-surface-variant hover:text-secondary text-sm transition-colors cursor-pointer bg-transparent border-none"
              >
                Don&apos;t have an account?{" "}
                <span className="underline underline-offset-4 decoration-secondary/30">
                  Create one for free
                </span>
              </button>
            </div>
          </div>
        </section>

        {/* ── About Section ─────────────────────────────────────────── */}
        <section className="max-w-7xl mx-auto px-6 py-24">
          <div className="grid grid-cols-1 gap-16 items-center max-w-3xl mx-auto text-center">
            <div className="space-y-6">
              <h2 className="text-4xl font-bold text-on-surface font-headline">
                What is CourtAccess AI?
              </h2>
              <div className="p-8 rounded-xl glass-panel border border-outline-variant/15">
                <p className="text-on-surface-variant leading-relaxed text-lg">
                  CourtAccess AI is a specialized legal intelligence platform
                  built to bridge the communication gap in the judicial system.
                  By combining neural machine translation with a deep
                  understanding of legal terminology and courtroom protocol, we
                  provide tools that are more accurate than general-purpose AI.
                </p>
                <ul className="mt-6 space-y-4 flex flex-col items-center">
                  <li className="flex gap-4 items-start">
                    <span className="material-symbols-outlined text-secondary">
                      verified
                    </span>
                    <span className="text-on-surface font-medium">
                      Verified Legal Terminology Database
                    </span>
                  </li>
                  <li className="flex gap-4 items-start">
                    <span className="material-symbols-outlined text-secondary">
                      verified
                    </span>
                    <span className="text-on-surface font-medium">
                      Compliance with Judicial Privacy Standards
                    </span>
                  </li>
                </ul>
              </div>
            </div>
          </div>
        </section>

        {/* ── Services Grid ─────────────────────────────────────────── */}
        <section className="bg-surface-container-lowest/30 backdrop-blur-sm py-24 px-6">
          <div className="max-w-7xl mx-auto">
            <div className="mb-16">
              <h2 className="text-3xl font-bold text-on-surface font-headline">
                Precision Services
              </h2>
              <p className="text-on-surface-variant mt-2">
                Tailored solutions for every member of the judicial process.
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
              {services.map((s) => (
                <div
                  key={s.title}
                  className="group bg-surface-container-low/60 backdrop-blur-md p-8 rounded-xl border border-outline-variant/10 hover:border-secondary/30 transition-all flex flex-col"
                >
                  <div className="w-12 h-12 rounded-lg bg-primary-container flex items-center justify-center text-secondary mb-6">
                    <span className="material-symbols-outlined">{s.icon}</span>
                  </div>
                  <h3 className="text-2xl font-bold mb-4 font-headline">{s.title}</h3>
                  <p className="text-on-surface-variant mb-8 flex-grow">{s.desc}</p>
                  <span className="text-secondary text-sm font-bold tracking-widest uppercase">
                    {s.who}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ── Bottom CTA Bar ────────────────────────────────────────── */}
        <section className="max-w-5xl mx-auto my-24 px-6">
          <div className="bg-primary-container/80 backdrop-blur-lg rounded-2xl p-10 flex flex-col md:flex-row items-center justify-between gap-8 border border-outline-variant/15 shadow-2xl">
            <div className="text-center md:text-left">
              <h2 className="text-3xl font-bold text-white font-headline">
                Ready to get started?
              </h2>
              <p className="text-primary mt-1">
                Access the next generation of legal accessibility today.
              </p>
            </div>
            <button
              onClick={() => openAuthModal("login")}
              className="bg-secondary-fixed-dim text-on-secondary-fixed px-10 py-4 rounded-lg font-bold text-lg hover:brightness-110 transition-all active:scale-95 whitespace-nowrap cursor-pointer"
            >
              Sign In
            </button>
          </div>
        </section>
      </main>

      {/* ── Footer ──────────────────────────────────────────────────── */}
      <footer className="bg-surface-container-lowest/80 backdrop-blur-md border-t border-outline-variant/10 py-12 px-6 relative z-10">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row justify-between items-center gap-8">
          <div className="text-on-surface-variant text-sm font-medium">
            © 2026 CourtAccess AI. All rights reserved.
          </div>
          <div className="text-center md:text-right max-w-md">
            <p className="text-[10px] uppercase tracking-widest text-on-surface-variant/60 leading-relaxed">
              AI Disclaimer: This tool is for linguistic assistance only and
              does not constitute legal advice. Users should verify all
              translations with certified court interpreters for official record.
            </p>
          </div>
        </div>
      </footer>
    </div>
  )
}
