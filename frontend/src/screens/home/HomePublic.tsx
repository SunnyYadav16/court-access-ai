/**
 * screens/home/HomePublic.tsx
 *
 * Public user home dashboard — renders INSIDE AppShell.
 * Dark-themed, matching the new design system.
 *
 * Preserved logic: useAuth for user greeting, onNav for navigation.
 */

import { ScreenId, SCREENS } from "@/lib/constants"
import { useAuth } from "@/hooks/useAuth"
import { getFirstName } from "@/lib/utils"

interface Props { onNav: (s: ScreenId) => void }

const features = [
  {
    icon: "upload_file",
    title: "Upload Document",
    desc: "Securely process subpoenas, contracts, or court orders for instant multi-language analysis.",
    cta: "Start Upload",
    screen: SCREENS.DOC_UPLOAD,
  },
  {
    icon: "account_balance",
    title: "Government Forms",
    desc: "Assisted walkthroughs for federal and state filings with real-time legal term clarification.",
    cta: "Browse Forms",
    screen: SCREENS.FORMS_LIBRARY,
  },
  {
    icon: "history_edu",
    title: "My Translations",
    desc: "Access your secure archive of processed documents and verified digital transcripts.",
    cta: "View Archive",
    screen: SCREENS.DOC_HISTORY,
  },
]

export default function HomePublic({ onNav }: Props) {
  const { backendUser } = useAuth()
  const firstName = getFirstName(backendUser?.name, backendUser?.email)

  return (
    <div className="px-6 lg:px-8 py-8 max-w-7xl mx-auto space-y-10">

      {/* Welcome Banner */}
      <section className="relative overflow-hidden rounded-xl p-8 lg:p-12 bg-gradient-to-br from-primary-container to-surface-container-lowest">
        <div className="absolute top-0 right-0 w-1/2 h-full opacity-10 pointer-events-none">
          <div className="w-full h-full bg-[radial-gradient(circle_at_center,_var(--tw-gradient-stops))] from-secondary via-transparent to-transparent" />
        </div>
        <div className="relative z-10">
          <h1 className="font-headline text-5xl lg:text-7xl text-white mb-4 tracking-tight">
            Welcome, {firstName}
          </h1>
          <div className="inline-flex items-center gap-2 px-3 py-1 bg-primary-fixed/10 border border-primary-fixed/20 rounded-full">
            <span className="w-2 h-2 rounded-full bg-primary shadow-[0_0_8px_rgba(186,200,220,0.5)]" />
            <span className="text-xs font-label uppercase tracking-widest text-primary-fixed">
              Public User
            </span>
          </div>
          <p className="mt-6 text-on-surface-variant max-w-xl text-lg leading-relaxed">
            Access accurate legal document translations and government form assistance,
            powered by AI built for the court system.
          </p>
        </div>
      </section>

      {/* Feature Cards */}
      <section>
        <h2 className="font-headline text-3xl text-on-surface mb-8">Document Translation</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {features.map((f) => (
            <div
              key={f.title}
              role="button"
              tabIndex={0}
              onClick={() => onNav(f.screen)}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onNav(f.screen) } }}
              className="group relative bg-surface-container-low p-8 rounded-xl transition-all duration-300 hover:bg-surface-container-high cursor-pointer"
            >
              <div className="mb-6 w-14 h-14 rounded-lg bg-primary-container flex items-center justify-center text-secondary transition-transform group-hover:scale-110">
                <span className="material-symbols-outlined text-3xl">{f.icon}</span>
              </div>
              <h3 className="text-xl font-headline text-white mb-3">{f.title}</h3>
              <p className="text-on-surface-variant text-sm mb-6 leading-relaxed">{f.desc}</p>
              <div className="flex items-center text-secondary font-label text-sm font-medium">
                {f.cta}
                <span className="material-symbols-outlined ml-2 text-base transition-transform group-hover:translate-x-1">
                  chevron_right
                </span>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Important Notice */}
      <section>
        <div className="bg-secondary-container/5 border border-secondary-fixed/20 rounded-xl p-6 flex flex-col md:flex-row items-start gap-6">
          <div className="bg-secondary-container p-3 rounded-lg">
            <span className="material-symbols-outlined text-on-secondary-container text-2xl">error</span>
          </div>
          <div>
            <h4 className="text-secondary font-label text-sm font-bold uppercase tracking-widest mb-2">
              Important Notice
            </h4>
            <p className="text-on-surface-variant text-sm leading-relaxed max-w-4xl">
              This service uses AI to assist in document processing and translation.
              CourtAccess AI does not provide formal legal advice. Please consult with a qualified attorney
              for specific legal guidance. Automated translations should be verified by a certified human
              translator for official court proceedings.
            </p>
          </div>
        </div>
      </section>
    </div>
  )
}
