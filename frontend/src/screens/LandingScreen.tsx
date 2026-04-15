/**
 * screens/LandingScreen.tsx
 *
 * Redesigned public landing page for CourtAccess AI.
 * Renders OUTSIDE AppShell — has its own nav and footer.
 *
 * Features:
 *   - Framer Motion staggered hero entrance
 *   - Live pipeline dashboard simulation (auto-cycling states)
 *   - Animated translation flow section
 *   - YouTube embed placeholder (swap VIDEO_ID when ready)
 *   - Cleaner Tailwind structure using design system tokens
 *
 * Preserved logic:
 *   - openAuthModal("login") / openAuthModal("signup")
 */

import { useEffect, useRef, useState } from "react"
import {
  motion,
  useInView,
  AnimatePresence,
} from "framer-motion"
import type { ScreenId } from "@/lib/constants"
import useAuthStore from "@/store/authStore"

// ─────────────────────────────────────────────────────────────────────────────
// Types & Constants
// ─────────────────────────────────────────────────────────────────────────────

interface Props {
  onNav: (s: ScreenId) => void
}

type PipelineStepStatus = "done" | "running" | "queued"

interface PipelineStep {
  id: string
  label: string
  sublabel: string
  status: PipelineStepStatus
  isAI?: boolean
}

// The five pipeline steps — no model names, just what each step *does*
const PIPELINE_STEPS_BASE: PipelineStep[] = [
  { id: "vad",     label: "Voice Detection",       sublabel: "Listening for speech…",           status: "queued" },
  { id: "asr",     label: "Speech to Text",         sublabel: "Converting audio to words…",      status: "queued" },
  { id: "mt",      label: "AI Translation",          sublabel: "Translating ES → EN…",            status: "queued" },
  { id: "legal",   label: "Legal Accuracy Review",  sublabel: "Checking legal terminology…",     status: "queued", isAI: true },
  { id: "tts",     label: "Audio Output",           sublabel: "Generating spoken translation…",  status: "queued" },
]

// What each step shows when it's the "running" step
const RUNNING_SUBLABELS: Record<string, string> = {
  vad:   "Voice activity detected",
  asr:   "Transcribing audio stream…",
  mt:    "ES → EN in progress…",
  legal: "AI reviewing legal context…",
  tts:   "Rendering audio output…",
}

// Services the platform offers
const SERVICES = [
  {
    icon: "description",
    title: "Translate Legal Documents",
    who: "For the public",
    desc: "Upload a court notice, evidence file, or legal filing and get an accurate translation in seconds — written in plain language you can actually understand.",
    sample: { es: "¿Desea apelar esta decisión?", en: "Do you wish to appeal this decision?" },
  },
  {
    icon: "mic",
    title: "Live Courtroom Interpretation",
    who: "For court staff & officials",
    desc: "Speak in one language and hear the translation instantly. Designed for live hearings, depositions, and legal consultations where every second counts.",
    sample: { es: "El testigo prestó juramento", en: "The witness was sworn in" },
  },
  {
    icon: "account_balance",
    title: "Complete Court Forms",
    who: "For everyone",
    desc: "Browse 45+ official Massachusetts court forms, available in Spanish and Portuguese. Fill them out with guided multilingual assistance.",
    sample: { es: "Solicitud de divorcio", en: "Petition for Divorce" },
  },
]

// How it works — the animated flow steps
const HOW_IT_WORKS = [
  { step: "01", icon: "upload_file",       title: "Upload or Speak",         desc: "Submit a document or start speaking in Spanish or Portuguese." },
  { step: "02", icon: "translate",         title: "AI Translates Instantly",  desc: "Our system converts your content to English with legal accuracy." },
  { step: "03", icon: "verified_user",     title: "Legal Review",             desc: "An AI layer checks the translation for legal accuracy and terminology." },
  { step: "04", icon: "download_done",     title: "Read or Listen",           desc: "Get your result as text, audio, or a downloadable translated document." },
]

// ─────────────────────────────────────────────────────────────────────────────
// Animation Variants
// ─────────────────────────────────────────────────────────────────────────────

const staggerContainer = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.12 } },
}

const staggerItem = {
  hidden: { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.55, ease: [0.22, 1, 0.36, 1] as const } },
}

// ─────────────────────────────────────────────────────────────────────────────
// Sub-components
// ─────────────────────────────────────────────────────────────────────────────

/** Pulsing live indicator dot */
function LiveDot({ className = "" }: { className?: string }) {
  return (
    <span className={`relative flex h-2 w-2 ${className}`}>
      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-secondary opacity-75" />
      <span className="relative inline-flex rounded-full h-2 w-2 bg-secondary" />
    </span>
  )
}

/** AI purple badge */
function AIBadge() {
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-tertiary-container/60 border border-tertiary/20 text-[10px] font-semibold tracking-wide text-on-tertiary-container">
      <span className="material-symbols-outlined text-[11px]">auto_awesome</span>
      AI-Verified
    </span>
  )
}

/** Single pipeline step row */
function PipelineStepRow({ step }: { step: PipelineStep }) {
  const isRunning = step.status === "running"
  const isDone    = step.status === "done"

  return (
    <motion.div
      layout
      animate={
        isRunning
          ? { borderColor: "rgba(200,150,62,0.35)", backgroundColor: "rgba(200,150,62,0.07)" }
          : isDone
          ? { borderColor: "rgba(74,222,128,0.22)", backgroundColor: "rgba(74,222,128,0.06)" }
          : { borderColor: "rgba(255,255,255,0.06)", backgroundColor: "rgba(255,255,255,0.02)" }
      }
      transition={{ duration: 0.4 }}
      className="flex items-center gap-3 px-3 py-2.5 rounded-lg border"
    >
      {/* Status icon */}
      <div
        className={`w-6 h-6 rounded-md flex items-center justify-center flex-shrink-0 text-[11px] font-bold transition-all duration-300 ${
          isDone    ? "bg-green-500/20 text-green-400" :
          isRunning ? (step.isAI ? "bg-tertiary-container text-on-tertiary-container" : "bg-secondary-container/30 text-secondary") :
                      "bg-white/5 text-on-surface-variant"
        }`}
      >
        {isDone ? (
          <span className="material-symbols-outlined text-[14px]">check</span>
        ) : isRunning ? (
          step.isAI
            ? <span className="material-symbols-outlined text-[14px]">auto_awesome</span>
            : <motion.span
                animate={{ rotate: 360 }}
                transition={{ repeat: Infinity, duration: 1.2, ease: "linear" }}
                className="material-symbols-outlined text-[14px] block"
              >sync</motion.span>
        ) : (
          <span className="w-1.5 h-1.5 rounded-full bg-on-surface-variant/30" />
        )}
      </div>

      {/* Labels */}
      <div className="flex-1 min-w-0">
        <div className={`text-[11px] font-semibold leading-tight ${isDone ? "text-green-400" : isRunning ? "text-on-surface" : "text-on-surface-variant"}`}>
          {step.label}
          {step.isAI && isRunning && <span className="ml-1.5"><AIBadge /></span>}
        </div>
        <div className="text-[10px] text-on-surface-variant/70 mt-0.5 truncate">{step.sublabel}</div>
      </div>

      {/* Badge */}
      <span
        className={`text-[9px] font-bold px-2 py-0.5 rounded-full tracking-wide flex-shrink-0 ${
          isDone    ? "bg-green-500/15 text-green-400" :
          isRunning ? (step.isAI ? "bg-tertiary-container/50 text-on-tertiary-container" : "bg-secondary-container/30 text-secondary") :
                      "bg-white/5 text-on-surface-variant/50"
        }`}
      >
        {isDone ? "DONE" : isRunning ? (step.isAI ? "AI" : "LIVE") : "—"}
      </span>
    </motion.div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Live Dashboard Simulation hook
// ─────────────────────────────────────────────────────────────────────────────

function usePipelineSimulation() {
  const [steps, setSteps] = useState<PipelineStep[]>(() =>
    PIPELINE_STEPS_BASE.map((s) => ({ ...s, status: "queued" }))
  )
  const [cycleCount, setCycleCount] = useState(0)
  const [inputText, setInputText] = useState("¿Desea apelar esta decisión judicial?")

  const INPUT_SAMPLES = [
    "¿Desea apelar esta decisión judicial?",
    "El testigo prestó juramento ante el juez.",
    "Solicitud de custodia temporal de menores.",
    "Moção de habeas corpus apresentada ao tribunal.",
    "O réu compareceu perante o tribunal superior.",
  ]

  useEffect(() => {
    let currentStep = 0
    const timeouts: ReturnType<typeof setTimeout>[] = []

    const resetAndRun = () => {
      setCycleCount((c) => c + 1)
      setInputText(INPUT_SAMPLES[cycleCount % INPUT_SAMPLES.length])
      setSteps(PIPELINE_STEPS_BASE.map((s) => ({ ...s, status: "queued" })))
      currentStep = 0
      scheduleNext()
    }

    const scheduleNext = () => {
      if (currentStep >= PIPELINE_STEPS_BASE.length) {
        // Pause at "all done" then restart
        timeouts.push(setTimeout(resetAndRun, 2800))
        return
      }

      const idx = currentStep

      // Mark current as running
      timeouts.push(
        setTimeout(() => {
          setSteps((prev) =>
            prev.map((s, i) => ({
              ...s,
              status: i === idx ? "running" : i < idx ? "done" : "queued",
              sublabel:
                i === idx ? RUNNING_SUBLABELS[s.id] : PIPELINE_STEPS_BASE[i].sublabel,
            }))
          )
        }, 0)
      )

      // Advance after a delay (longer for AI step)
      const delay = PIPELINE_STEPS_BASE[idx].isAI ? 2200 : 1400

      timeouts.push(
        setTimeout(() => {
          setSteps((prev) =>
            prev.map((s, i) => ({
              ...s,
              status: i <= idx ? "done" : "queued",
              sublabel: i <= idx
                ? (i === idx ? getCompletedSublabel(s.id) : PIPELINE_STEPS_BASE[i].sublabel)
                : PIPELINE_STEPS_BASE[i].sublabel,
            }))
          )
          currentStep++
          scheduleNext()
        }, delay)
      )
    }

    scheduleNext()

    return () => timeouts.forEach(clearTimeout)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cycleCount])

  return { steps, inputText }
}

function getCompletedSublabel(id: string): string {
  const map: Record<string, string> = {
    vad:   "Speech confirmed",
    asr:   "Transcript ready",
    mt:    "Translation complete",
    legal: "Legal terms verified",
    tts:   "Audio generated",
  }
  return map[id] ?? ""
}

// ─────────────────────────────────────────────────────────────────────────────
// Section: Scroll-triggered wrapper
// ─────────────────────────────────────────────────────────────────────────────

function ScrollSection({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const inView = useInView(ref, { once: true, margin: "-80px 0px" })

  return (
    <motion.div
      ref={ref}
      variants={staggerContainer}
      initial="hidden"
      animate={inView ? "visible" : "hidden"}
      className={className}
    >
      {children}
    </motion.div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Main Component
// ─────────────────────────────────────────────────────────────────────────────

export default function LandingScreen({ onNav: _onNav }: Props) {
  const openAuthModal = useAuthStore((s) => s.openAuthModal)
  const { steps, inputText } = usePipelineSimulation()

  return (
    <div className="min-h-screen bg-surface text-on-surface font-body selection:bg-secondary-container selection:text-on-secondary-container">

      {/* Justice statue background overlay */}
      <div className="page-bg-overlay" />

      {/* ── Nav ─────────────────────────────────────────────────────── */}
      <nav className="fixed top-0 left-0 w-full z-50 h-14 flex items-center justify-between px-6 bg-primary-container/95 backdrop-blur-md border-b border-outline-variant/10 shadow-lg shadow-black/30">
        <div className="flex items-center gap-3">
          <span className="font-headline text-xl font-semibold text-on-surface tracking-tight">
            CourtAccess AI
          </span>
          <span className="text-[9px] font-bold tracking-[1.2px] uppercase bg-secondary-container/30 text-secondary px-2 py-0.5 rounded">
            BETA
          </span>
        </div>

        <div className="flex items-center gap-3">
          {/* Ghost Sign In */}
          <button
            onClick={() => openAuthModal("login")}
            className="px-5 py-2 rounded-lg text-sm font-semibold text-secondary border border-secondary/30 hover:bg-secondary/10 transition-all active:scale-95 cursor-pointer"
          >
            Sign In
          </button>
          {/* Primary Get Started */}
          <button
            onClick={() => openAuthModal("signup")}
            className="px-5 py-2 rounded-lg text-sm font-bold bg-secondary text-on-secondary hover:brightness-110 transition-all active:scale-95 shadow-md shadow-secondary/20 cursor-pointer"
          >
            Get Started Free
          </button>
        </div>
      </nav>

      <main className="pt-14 relative z-10">

        {/* ── Hero ─────────────────────────────────────────────────── */}
        <section className="relative min-h-[92vh] flex items-center px-6 py-20 overflow-hidden">
          {/* Ambient glow blobs */}
          <div className="absolute top-1/3 left-1/4 w-96 h-96 bg-secondary/5 blur-[120px] rounded-full pointer-events-none" />
          <div className="absolute bottom-1/4 right-1/4 w-80 h-80 bg-tertiary/5 blur-[100px] rounded-full pointer-events-none" />

          <div className="max-w-7xl mx-auto w-full grid grid-cols-1 lg:grid-cols-2 gap-16 items-center">

            {/* Left: Copy */}
            <motion.div
              initial="hidden"
              animate="visible"
              variants={staggerContainer}
              className="flex flex-col gap-8"
            >
              {/* Live badge */}
              <motion.div variants={staggerItem}>
                <span className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full border border-secondary/20 bg-secondary-container/15 text-secondary text-[11px] font-semibold tracking-wide">
                  <LiveDot />
                  Massachusetts Trial Court · Language Access
                </span>
              </motion.div>

              {/* Headline */}
              <motion.div variants={staggerItem}>
                <h1 className="font-headline text-5xl md:text-6xl font-bold leading-[1.1] tracking-tight text-on-surface">
                  Your court documents,{" "}
                  <span className="text-secondary italic font-normal">
                    translated instantly.
                  </span>
                </h1>
              </motion.div>

              {/* Subheadline — plain language */}
              <motion.div variants={staggerItem}>
                <p className="text-lg text-on-surface-variant leading-relaxed max-w-lg">
                  CourtAccess AI helps people who speak Spanish or Portuguese navigate
                  the Massachusetts court system — by translating legal documents, interpreting
                  live courtroom speech, and making court forms accessible in your language.
                </p>
              </motion.div>

              {/* Feature chips */}
              <motion.div variants={staggerItem} className="flex flex-wrap gap-2">
                {[
                  { icon: "language",    label: "Spanish & Portuguese" },
                  { icon: "bolt",        label: "Real-Time AI"         },
                  { icon: "assignment",  label: "45+ Court Forms"      },
                  { icon: "lock",        label: "Secure & Private"     },
                ].map((f) => (
                  <span
                    key={f.label}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-surface-container-low/50 border border-outline-variant/15 text-sm text-on-surface-variant"
                  >
                    <span className="material-symbols-outlined text-secondary text-[16px]">{f.icon}</span>
                    {f.label}
                  </span>
                ))}
              </motion.div>

              {/* CTAs — clear hierarchy */}
              <motion.div variants={staggerItem} className="flex flex-col sm:flex-row gap-3 pt-2">
                <button
                  onClick={() => openAuthModal("signup")}
                  className="bg-secondary text-on-secondary px-8 py-4 rounded-xl font-bold text-base shadow-lg shadow-secondary/25 hover:brightness-110 transition-all active:scale-95 cursor-pointer"
                >
                  Create a Free Account
                </button>
                <button
                  onClick={() => openAuthModal("login")}
                  className="px-8 py-4 rounded-xl font-semibold text-base text-on-surface-variant border border-outline-variant/30 hover:border-secondary/30 hover:text-secondary transition-all active:scale-95 cursor-pointer bg-transparent"
                >
                  Sign In →
                </button>
              </motion.div>

              <motion.p variants={staggerItem} className="text-xs text-on-surface-variant/50">
                No credit card required. Free to use for public users.
              </motion.p>
            </motion.div>

            {/* Right: Live Pipeline Dashboard */}
            <motion.div
              initial={{ opacity: 0, x: 40 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.75, delay: 0.3, ease: [0.22, 1, 0.36, 1] }}
              className="relative"
            >
              {/* Glass panel */}
              <div className="bg-surface-container-highest/40 backdrop-blur-xl rounded-2xl border border-outline-variant/15 shadow-2xl shadow-black/40 overflow-hidden">

                {/* Panel header */}
                <div className="flex items-center justify-between px-4 py-3 border-b border-outline-variant/10 bg-surface-container-low/30">
                  <div className="flex items-center gap-2">
                    {/* Traffic lights */}
                    <span className="w-2.5 h-2.5 rounded-full bg-red-500/60" />
                    <span className="w-2.5 h-2.5 rounded-full bg-yellow-500/60" />
                    <span className="w-2.5 h-2.5 rounded-full bg-green-500/60" />
                  </div>
                  <div className="flex items-center gap-2 text-[10px] font-semibold text-on-surface-variant/70 tracking-wide uppercase">
                    <LiveDot />
                    Live Processing
                  </div>
                  <div className="w-14" /> {/* spacer */}
                </div>

                <div className="p-5 flex flex-col gap-4">

                  {/* Input display */}
                  <div className="bg-surface-container-low/50 rounded-lg px-4 py-3 border border-outline-variant/10 flex items-center gap-3">
                    <span className="material-symbols-outlined text-secondary text-lg flex-shrink-0">mic</span>
                    <AnimatePresence mode="wait">
                      <motion.span
                        key={inputText}
                        initial={{ opacity: 0, y: 6 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -6 }}
                        transition={{ duration: 0.35 }}
                        className="text-sm text-on-surface-variant italic flex-1 truncate"
                      >
                        {inputText}
                      </motion.span>
                    </AnimatePresence>
                    <span className="text-[10px] font-bold bg-secondary-container/30 text-secondary px-2 py-0.5 rounded flex-shrink-0">
                      ES → EN
                    </span>
                  </div>

                  {/* Pipeline steps */}
                  <div className="flex flex-col gap-1.5">
                    {steps.map((step) => (
                      <PipelineStepRow key={step.id} step={step} />
                    ))}
                  </div>

                  {/* Output preview — shown when all done */}
                  <AnimatePresence>
                    {steps.every((s) => s.status === "done") && (
                      <motion.div
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: "auto" }}
                        exit={{ opacity: 0, height: 0 }}
                        transition={{ duration: 0.4 }}
                        className="bg-tertiary-container/20 border border-tertiary/15 rounded-lg px-4 py-3 flex items-start gap-3"
                      >
                        <span className="material-symbols-outlined text-on-tertiary-container text-lg mt-0.5 flex-shrink-0">check_circle</span>
                        <div>
                          <div className="text-[10px] font-bold text-on-tertiary-container/70 uppercase tracking-wide mb-1">
                            Translation Ready
                          </div>
                          <div className="text-sm text-on-surface font-medium">
                            "Do you wish to appeal this judicial decision?"
                          </div>
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>

                </div>
              </div>

              {/* Floating accent card */}
              <motion.div
                animate={{ y: [0, -6, 0] }}
                transition={{ repeat: Infinity, duration: 4, ease: "easeInOut" }}
                className="absolute -bottom-5 -left-6 bg-surface-container-highest/80 backdrop-blur-lg border border-outline-variant/15 rounded-xl px-4 py-3 shadow-xl shadow-black/30 flex items-center gap-3"
              >
                <div className="w-8 h-8 rounded-lg bg-secondary-container/30 flex items-center justify-center flex-shrink-0">
                  <span className="material-symbols-outlined text-secondary text-[18px]">translate</span>
                </div>
                <div>
                  <div className="text-[10px] text-on-surface-variant/60 uppercase tracking-wide font-semibold">Supported</div>
                  <div className="text-sm font-semibold text-on-surface">Spanish · Portuguese</div>
                </div>
              </motion.div>
            </motion.div>

          </div>
        </section>

        {/* ── How It Works (Animated Flow) ─────────────────────────── */}
        <section className="py-28 px-6 bg-surface-container-lowest/40 backdrop-blur-sm">
          <ScrollSection className="max-w-7xl mx-auto">
            <motion.div variants={staggerItem} className="text-center mb-16">
              <p className="text-secondary text-sm font-bold tracking-widest uppercase mb-3">How It Works</p>
              <h2 className="font-headline text-4xl md:text-5xl font-bold text-on-surface">
                From your language to the courtroom,
                <br />
                <span className="text-secondary italic font-normal">in four steps.</span>
              </h2>
            </motion.div>

            <div className="grid grid-cols-1 md:grid-cols-4 gap-6 relative">
              {/* Connecting line (desktop) */}
              <div className="hidden md:block absolute top-10 left-[12.5%] right-[12.5%] h-px bg-gradient-to-r from-transparent via-secondary/30 to-transparent" />

              {HOW_IT_WORKS.map((step, i) => (
                <motion.div
                  key={step.step}
                  variants={staggerItem}
                  className="flex flex-col items-center text-center gap-4 relative"
                >
                  {/* Icon circle */}
                  <div className="relative z-10 w-20 h-20 rounded-full bg-surface-container-highest border border-outline-variant/15 flex items-center justify-center shadow-xl shadow-black/20">
                    <span className="material-symbols-outlined text-secondary text-3xl">{step.icon}</span>
                    <span className="absolute -top-1.5 -right-1.5 w-6 h-6 rounded-full bg-secondary text-on-secondary text-[10px] font-bold flex items-center justify-center shadow-md">
                      {i + 1}
                    </span>
                  </div>
                  <div>
                    <h3 className="font-headline text-lg font-bold text-on-surface mb-2">{step.title}</h3>
                    <p className="text-sm text-on-surface-variant leading-relaxed">{step.desc}</p>
                  </div>
                </motion.div>
              ))}
            </div>
          </ScrollSection>
        </section>

        {/* ── Services ─────────────────────────────────────────────── */}
        <section className="py-28 px-6">
          <ScrollSection className="max-w-7xl mx-auto">
            <motion.div variants={staggerItem} className="mb-14">
              <p className="text-secondary text-sm font-bold tracking-widest uppercase mb-3">What You Can Do</p>
              <h2 className="font-headline text-4xl md:text-5xl font-bold text-on-surface">
                Three tools. One platform.
              </h2>
              <p className="text-on-surface-variant mt-3 text-lg max-w-xl">
                Whether you're a resident, an attorney, or a court official — we have a tool built for you.
              </p>
            </motion.div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              {SERVICES.map((svc) => (
                <motion.div
                  key={svc.title}
                  variants={staggerItem}
                  whileHover={{ y: -4, transition: { duration: 0.2 } }}
                  className="group bg-surface-container-low/60 backdrop-blur-md rounded-2xl border border-outline-variant/10 hover:border-secondary/25 transition-colors p-8 flex flex-col gap-5"
                >
                  {/* Icon */}
                  <div className="w-12 h-12 rounded-xl bg-secondary-container/20 border border-secondary/15 flex items-center justify-center">
                    <span className="material-symbols-outlined text-secondary text-2xl">{svc.icon}</span>
                  </div>

                  {/* Who badge */}
                  <span className="text-[10px] font-bold tracking-widest uppercase text-secondary/80">{svc.who}</span>

                  <div>
                    <h3 className="font-headline text-2xl font-bold text-on-surface mb-3">{svc.title}</h3>
                    <p className="text-sm text-on-surface-variant leading-relaxed">{svc.desc}</p>
                  </div>

                  {/* Live translation sample */}
                  <div className="mt-auto bg-surface-container-highest/50 rounded-xl p-4 border border-outline-variant/10 space-y-2">
                    <div className="flex items-center gap-2 text-xs">
                      <span className="w-5 h-5 rounded-md bg-tertiary-container/50 flex items-center justify-center text-[10px] font-bold text-on-tertiary-container flex-shrink-0">ES</span>
                      <span className="text-on-surface-variant italic">{svc.sample.es}</span>
                    </div>
                    <div className="flex items-center gap-2 text-xs">
                      <span className="w-5 h-5 rounded-md bg-secondary-container/30 flex items-center justify-center text-[9px] font-bold text-secondary flex-shrink-0">EN</span>
                      <span className="text-on-surface font-medium">{svc.sample.en}</span>
                    </div>
                  </div>
                </motion.div>
              ))}
            </div>
          </ScrollSection>
        </section>

        {/* ── About ────────────────────────────────────────────────── */}
        <section className="py-28 px-6 bg-surface-container-lowest/40">
          <ScrollSection className="max-w-5xl mx-auto">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-14 items-center">
              <motion.div variants={staggerItem}>
                <p className="text-secondary text-sm font-bold tracking-widest uppercase mb-3">About the Platform</p>
                <h2 className="font-headline text-4xl font-bold text-on-surface mb-6 leading-tight">
                  Built specifically for Massachusetts courts.
                </h2>
                <p className="text-on-surface-variant leading-relaxed mb-8">
                  General translation tools weren't designed for legal settings. Court documents use
                  specific terminology that matters enormously — a mistranslation can affect someone's
                  rights. CourtAccess AI is trained on legal language and verified for courtroom use.
                </p>
                <button
                  onClick={() => openAuthModal("signup")}
                  className="inline-flex items-center gap-2 bg-secondary text-on-secondary px-7 py-3.5 rounded-xl font-bold text-sm hover:brightness-110 transition-all active:scale-95 cursor-pointer shadow-lg shadow-secondary/20"
                >
                  Start for Free
                  <span className="material-symbols-outlined text-lg">arrow_forward</span>
                </button>
              </motion.div>

              <motion.div variants={staggerItem} className="flex flex-col gap-4">
                {[
                  { icon: "verified",       title: "Legal Terminology Verified",         desc: "Every translation is checked against a verified legal terminology database." },
                  { icon: "shield_locked",  title: "Court Privacy Standards",            desc: "Your documents are handled under strict judicial data privacy requirements." },
                  { icon: "speed",          title: "Fast Enough for Live Hearings",      desc: "Audio interpretation works in real time — under one second of delay." },
                ].map((item) => (
                  <div key={item.title} className="flex items-start gap-4 p-5 rounded-xl bg-surface-container-low/50 border border-outline-variant/10">
                    <div className="w-10 h-10 rounded-lg bg-secondary-container/20 flex items-center justify-center flex-shrink-0 mt-0.5">
                      <span className="material-symbols-outlined text-secondary text-xl">{item.icon}</span>
                    </div>
                    <div>
                      <div className="font-semibold text-on-surface text-sm mb-1">{item.title}</div>
                      <div className="text-xs text-on-surface-variant leading-relaxed">{item.desc}</div>
                    </div>
                  </div>
                ))}
              </motion.div>
            </div>
          </ScrollSection>
        </section>

        {/* ── Bottom CTA ───────────────────────────────────────────── */}
        <section className="py-24 px-6">
          <ScrollSection>
            <motion.div
              variants={staggerItem}
              className="max-w-4xl mx-auto bg-primary-container/80 backdrop-blur-lg rounded-3xl p-12 border border-outline-variant/15 shadow-2xl flex flex-col md:flex-row items-center justify-between gap-8 text-center md:text-left"
            >
              <div>
                <h2 className="font-headline text-3xl md:text-4xl font-bold text-on-surface mb-3">
                  Ready to get started?
                </h2>
                <p className="text-on-surface-variant text-lg max-w-md">
                  Join residents, attorneys, and court officials across Massachusetts using CourtAccess AI.
                </p>
              </div>
              <div className="flex flex-col gap-3 flex-shrink-0">
                <button
                  onClick={() => openAuthModal("signup")}
                  className="bg-secondary text-on-secondary px-10 py-4 rounded-xl font-bold text-base hover:brightness-110 transition-all active:scale-95 whitespace-nowrap cursor-pointer shadow-lg shadow-secondary/20"
                >
                  Create a Free Account
                </button>
                <button
                  onClick={() => openAuthModal("login")}
                  className="px-10 py-4 rounded-xl font-semibold text-sm text-on-surface-variant border border-outline-variant/30 hover:border-secondary/30 hover:text-secondary transition-all cursor-pointer bg-transparent"
                >
                  Already have an account? Sign In
                </button>
              </div>
            </motion.div>
          </ScrollSection>
        </section>

      </main>

      {/* ── Footer ───────────────────────────────────────────────── */}
      <footer className="bg-surface-container-lowest/80 backdrop-blur-md border-t border-outline-variant/10 py-10 px-6">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row justify-between items-center gap-6">
          <div>
            <div className="font-headline text-lg font-semibold text-on-surface mb-1">CourtAccess AI</div>
            <div className="text-xs text-on-surface-variant/60">© 2026 CourtAccess AI. All rights reserved.</div>
          </div>
          <p className="text-[10px] uppercase tracking-widest text-on-surface-variant/40 leading-relaxed text-center md:text-right max-w-sm">
            AI Disclaimer: This tool provides translation assistance only and does not constitute
            legal advice. Always verify translations with a certified court interpreter for
            official proceedings.
          </p>
        </div>
      </footer>

    </div>
  )
}
