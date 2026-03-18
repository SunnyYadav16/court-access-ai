import { ScreenId } from "@/lib/constants"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import useAuthStore from "@/store/authStore"

interface Props { onNav: (s: ScreenId) => void }

const services = [
  {
    icon: "📄",
    title: "Document Translation",
    who: "For the public",
    desc: "Upload legal court documents and receive accurate translations in Spanish or Portuguese, powered by AI and reviewed for legal terminology.",
  },
  {
    icon: "🎙",
    title: "Real-Time Interpretation",
    who: "For court officials",
    desc: "Enable live bidirectional speech interpretation during court proceedings, with automatic legal term correction and session transcripts.",
  },
  {
    icon: "🏛",
    title: "Government Forms",
    who: "For everyone",
    desc: "Browse and download pre-translated Massachusetts court forms in Spanish and Portuguese, regularly updated and verified by interpreters.",
  },
]

const features = [
  { icon: "🌐", label: "Spanish & Portuguese" },
  { icon: "⚡", label: "Real-Time AI Processing" },
  { icon: "📋", label: "45+ Court Forms" },
  { icon: "🔒", label: "Secure & Private" },
]

/**
 * Renders the landing screen with hero content, feature pills, service cards, and authentication CTAs.
 *
 * @param onNav - Navigation callback (kept for API compatibility; not used by this component)
 * @returns The rendered landing screen element
 */
export default function LandingScreen({ onNav: _onNav }: Props) {
  const openAuthModal = useAuthStore((s) => s.openAuthModal);

  return (
    <div className="min-h-screen" style={{ background: "#F6F7F9", fontFamily: "'Segoe UI', sans-serif" }}>

      {/* Top Nav */}
      <nav className="px-8 py-4 flex items-center justify-between"
        style={{ background: "#fff", borderBottom: "1px solid #E2E6EC" }}>
        <div className="flex items-center gap-2">
          <span className="text-2xl">⚖</span>
          <span className="text-lg font-bold tracking-wide"
            style={{ fontFamily: "Palatino, Georgia, serif", color: "#0B1D3A" }}>
            CourtAccess AI
          </span>
          <span className="text-[10px] font-semibold px-2 py-0.5 rounded ml-1"
            style={{ background: "#F5EDE0", color: "#C8963E" }}>
            BETA
          </span>
        </div>
        <Button
          onClick={() => openAuthModal("login")}
          className="cursor-pointer transition-all"
          style={{
            background: "#C8963E",
            color: "#fff",
            border: "none",
            fontWeight: 600
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = "#B8852E";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = "#C8963E";
          }}>
          Sign In
        </Button>
      </nav>

      {/* Hero */}
      <div className="max-w-3xl mx-auto px-6 py-20 text-center">
        <div className="text-5xl mb-6">⚖</div>
        <h1 className="text-4xl font-bold mb-4 leading-tight"
          style={{ fontFamily: "Palatino, Georgia, serif", color: "#0B1D3A" }}>
          AI-Powered Legal Translation<br />and Interpretation
        </h1>
        <p className="text-base leading-relaxed mb-8 max-w-xl mx-auto"
          style={{ color: "#4A5568" }}>
          CourtAccess AI bridges language barriers in the courtroom — providing
          real-time interpretation, document translation, and access to pre-translated
          court forms for Spanish and Portuguese speakers.
        </p>

        {/* Feature pills */}
        <div className="flex flex-wrap justify-center gap-3 mb-10">
          {features.map((f, i) => (
            <div key={i} className="flex items-center gap-2 px-4 py-2 rounded-full text-sm font-medium"
              style={{ background: "#fff", border: "1px solid #E2E6EC", color: "#1A2332" }}>
              <span>{f.icon}</span>
              <span>{f.label}</span>
            </div>
          ))}
        </div>

        <Button
          onClick={() => openAuthModal("login")}
          className="cursor-pointer px-8 py-3 text-base h-auto transition-all shadow-md"
          style={{
            background: "#C8963E",
            color: "#fff",
            fontWeight: 600,
            border: "none"
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = "#B8852E";
            e.currentTarget.style.transform = "translateY(-1px)";
            e.currentTarget.style.boxShadow = "0 8px 16px rgba(200, 150, 62, 0.3)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = "#C8963E";
            e.currentTarget.style.transform = "translateY(0)";
            e.currentTarget.style.boxShadow = "0 4px 6px rgba(0, 0, 0, 0.1)";
          }}>
          Sign In to Use Services
        </Button>
        <p className="text-xs mt-3" style={{ color: "#8494A7" }}>
          Don't have an account?{" "}
          <button
            onClick={() => openAuthModal("signup")}
            className="font-semibold cursor-pointer"
            style={{ color: "#2563eb", background: "none", border: "none" }}>
            Create one for free
          </button>
        </p>
      </div>

      {/* About */}
      <div className="max-w-3xl mx-auto px-6 pb-16">
        <div className="rounded-xl p-8 text-center mb-16"
          style={{ background: "#fff", border: "1px solid #E2E6EC" }}>
          <h2 className="text-2xl font-bold mb-3"
            style={{ fontFamily: "Palatino, Georgia, serif", color: "#0B1D3A" }}>
            What is CourtAccess AI?
          </h2>
          <p className="text-sm leading-relaxed max-w-xl mx-auto" style={{ color: "#4A5568" }}>
            CourtAccess AI is a language access system built for the justice system.
            It uses a multi-model AI pipeline — combining speech recognition, neural
            machine translation, OCR, and large language models — to make legal
            proceedings and documents accessible to non-English speakers in real time.
          </p>
        </div>

        {/* Services */}
        <h2 className="text-2xl font-bold text-center mb-8"
          style={{ fontFamily: "Palatino, Georgia, serif", color: "#0B1D3A" }}>
          What We Offer
        </h2>
        <div className="grid grid-cols-3 gap-4 mb-10">
          {services.map((s, i) => (
            <Card key={i} className="border shadow-sm">
              <CardContent className="p-6">
                <div className="w-12 h-12 rounded-lg flex items-center justify-center text-2xl mb-4"
                  style={{ background: "#F5EDE0" }}>
                  {s.icon}
                </div>
                <div className="text-[10px] font-semibold uppercase tracking-wider mb-1"
                  style={{ color: "#C8963E" }}>
                  {s.who}
                </div>
                <h3 className="text-sm font-bold mb-2" style={{ color: "#0B1D3A" }}>
                  {s.title}
                </h3>
                <p className="text-xs leading-relaxed" style={{ color: "#4A5568" }}>
                  {s.desc}
                </p>
              </CardContent>
            </Card>
          ))}
        </div>

        {/* Bottom CTA */}
        <div className="rounded-xl p-8 text-center"
          style={{ background: "#0B1D3A" }}>
          <h3 className="text-xl font-bold text-white mb-2"
            style={{ fontFamily: "Palatino, Georgia, serif" }}>
            Ready to get started?
          </h3>
          <p className="text-sm mb-5" style={{ color: "rgba(255,255,255,0.6)" }}>
            Sign in to access translation and interpretation services.
          </p>
          <Button
            onClick={() => openAuthModal("login")}
            className="cursor-pointer px-8 transition-all"
            style={{
              background: "#C8963E",
              color: "#fff",
              border: "none",
              fontWeight: 600
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = "#B8852E";
              e.currentTarget.style.transform = "translateY(-1px)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = "#C8963E";
              e.currentTarget.style.transform = "translateY(0)";
            }}>
            Sign In to Use Services
          </Button>
        </div>
      </div>

      {/* Minimal footer */}
      <div className="text-center py-6 text-xs" style={{ color: "#8494A7", borderTop: "1px solid #E2E6EC" }}>
        © 2026 CourtAccess AI · All translations are AI-generated and not official legal records
      </div>
    </div>
  )
}
