/**
 * screens/admin/InterpreterReview.tsx
 *
 * Translation review queue — renders INSIDE AppShell.
 * Dark-themed with side-by-side original/translation panels,
 * corrections textarea, action buttons, and contextual stats.
 *
 * Static mock — no backend integration yet.
 */

import { ScreenId } from "@/lib/constants"

interface Props { onNav: (s: ScreenId) => void }

export default function InterpreterReview({ onNav: _onNav }: Props) {
  return (
    <div className="px-6 lg:px-8 py-8 max-w-6xl mx-auto space-y-8">

      {/* Header */}
      <header className="space-y-4">
        <div className="flex items-center gap-3">
          <span className="bg-secondary text-on-secondary px-3 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider">
            Interpreter Role
          </span>
          <span className="px-2 py-1 bg-primary-container text-on-primary-container text-[10px] font-bold tracking-widest uppercase rounded">
            Priority Review
          </span>
          <span className="text-tertiary font-medium text-sm flex items-center gap-1">
            <span className="material-symbols-outlined text-xs" style={{ fontVariationSettings: "'FILL' 1" }}>bolt</span>
            AI Analysis Active
          </span>
        </div>
        <div className="flex flex-col md:flex-row justify-between items-start md:items-end gap-4">
          <div>
            <h1 className="font-headline text-4xl text-on-surface mb-2">Translation Review Queue</h1>
            <p className="text-on-surface-variant max-w-2xl">
              Audit pending AI-assisted transcripts and legal documents for linguistic precision and legal preservation.
            </p>
          </div>
        </div>
      </header>

      {/* Metadata bar */}
      <div className="flex items-center justify-between px-4 py-3 bg-surface-container rounded-lg border border-outline-variant/5">
        <div className="flex items-center gap-4">
          <span className="material-symbols-outlined text-secondary">description</span>
          <div>
            <p className="text-xs font-bold text-on-surface">Order_of_Remand_CR2024.pdf</p>
            <p className="text-[10px] text-outline uppercase tracking-wider">Court Order • PDF Document</p>
          </div>
        </div>
        <span className="text-[10px] uppercase tracking-tighter text-outline hidden sm:inline">
          Document ID: #CR-2024-0082
        </span>
      </div>

      {/* Side-by-side panels */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Original */}
        <div className="flex flex-col gap-4">
          <div className="flex items-center justify-between px-4">
            <span className="font-headline italic text-lg text-primary">Original Text (English)</span>
            <span className="flex items-center gap-1 text-[10px] uppercase text-outline">
              <span className="w-1.5 h-1.5 rounded-full bg-primary" />
              Source
            </span>
          </div>
          <div className="bg-surface-container-low p-8 rounded-xl min-h-[400px] border border-outline-variant/10 leading-relaxed text-on-surface shadow-inner">
            <p className="mb-6 font-semibold">IT IS HEREBY ORDERED:</p>
            <p className="mb-4">
              1. The defendant shall be remanded to the custody of the Sheriff pending the outcome of the
              preliminary hearing scheduled for November 14th.
            </p>
            <p className="mb-4">
              2. Bail is set at $250,000.00, to be posted in cash or by corporate surety bond.
            </p>
            <p className="mb-4">
              3. The defendant is prohibited from contacting the victim, either directly or through a third
              party, while this order remains in effect.
            </p>
            <p className="mb-4 italic">
              Failure to comply with these conditions may result in immediate revocation of release status
              and additional criminal charges.
            </p>
          </div>
        </div>

        {/* Translation */}
        <div className="flex flex-col gap-4">
          <div className="flex items-center justify-between px-4">
            <span className="font-headline italic text-lg text-secondary">AI Translation (Spanish)</span>
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-secondary animate-pulse" />
              <span className="text-[10px] uppercase tracking-tighter text-on-surface-variant font-bold">
                Certification Active
              </span>
            </div>
          </div>
          <div className="bg-surface-container-high p-8 rounded-xl min-h-[400px] border border-secondary/20 leading-relaxed text-on-surface relative overflow-hidden"
               style={{ boxShadow: "0px 12px 32px rgba(0, 0, 0, 0.4)" }}
          >
            <div className="absolute top-0 right-0 p-4 opacity-10">
              <span className="material-symbols-outlined text-6xl">gavel</span>
            </div>
            <p className="mb-6 font-semibold">POR LA PRESENTE SE ORDENA:</p>
            <p className="mb-4">
              1. El acusado será{" "}
              <span className="bg-secondary-container/20 border-b border-secondary-container text-secondary font-medium px-0.5 rounded-t-sm">
                puesto bajo custodia
              </span>{" "}
              del Sheriff a la espera del resultado de la audiencia preliminar programada para el 14 de noviembre.
            </p>
            <p className="mb-4">
              2. La fianza se fija en $250,000.00, a ser depositada en efectivo o mediante{" "}
              <span className="bg-secondary-container/20 border-b border-secondary-container text-secondary font-medium px-0.5 rounded-t-sm">
                fianza de una compañía de seguros
              </span>.
            </p>
            <p className="mb-4">
              3. Se prohíbe al acusado ponerse en contacto con la víctima, ya sea directamente o a través de un
              tercero, mientras esta orden permanezca{" "}
              <span className="bg-secondary-container/20 border-b border-secondary-container text-secondary font-medium px-0.5 rounded-t-sm">
                vigente
              </span>.
            </p>
            <p className="mb-4 italic">
              El incumplimiento de estas condiciones puede dar lugar a la{" "}
              <span className="bg-secondary-container/20 border-b border-secondary-container text-secondary font-medium px-0.5 rounded-t-sm">
                revocación inmediata
              </span>{" "}
              del estatus de libertad y cargos penales adicionales.
            </p>
          </div>
        </div>
      </div>

      {/* Corrections & Actions */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-end">
        <div className="lg:col-span-7 flex flex-col gap-3">
          <label htmlFor="corrections-notes" className="font-sans text-xs uppercase tracking-widest text-outline ml-1">
            Manual Corrections / Translator Notes
          </label>
          <div className="relative group">
            <textarea
              id="corrections-notes"
              className="w-full bg-surface-container-highest border-none rounded-xl p-4 text-on-surface placeholder:text-outline/50 focus:ring-2 focus:ring-secondary/50 min-h-[100px] resize-y transition-all duration-300 outline-none"
              placeholder="e.g., 'Update clause 2 to use specific jurisdictional terminology for surety.'"
            />
            <div className="absolute bottom-3 right-3 text-[10px] text-outline pointer-events-none group-focus-within:opacity-100 opacity-40 transition-opacity">
              CMD + Enter to quick-submit
            </div>
          </div>
        </div>
        <div className="lg:col-span-5 flex flex-col gap-3">
          <button
            className="w-full h-12 bg-secondary text-on-secondary font-bold rounded-lg flex items-center justify-center gap-2 hover:brightness-110 active:scale-[0.98] transition-all cursor-pointer border-none"
            style={{ boxShadow: "0px 12px 32px rgba(0, 0, 0, 0.4)" }}
          >
            <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 1" }}>verified_user</span>
            Approve & Certify Translation
          </button>
          <button className="w-full h-12 bg-surface-container-low text-secondary border border-secondary/20 font-bold rounded-lg flex items-center justify-center gap-2 hover:bg-secondary/5 active:scale-[0.98] transition-all cursor-pointer">
            <span className="material-symbols-outlined">edit_note</span>
            Submit Manual Corrections
          </button>
        </div>
      </div>

      {/* Contextual Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-surface-container-low p-5 rounded-lg border-l-4 border-tertiary flex items-center gap-4">
          <div className="w-10 h-10 rounded-full bg-tertiary-container flex items-center justify-center">
            <span className="material-symbols-outlined text-tertiary">psychology</span>
          </div>
          <div>
            <p className="text-[10px] uppercase text-outline tracking-wider">AI Confidence Score</p>
            <p className="text-xl font-bold text-on-surface">
              98.4% <span className="text-xs font-normal text-tertiary">High</span>
            </p>
          </div>
        </div>
        <div className="bg-surface-container-low p-5 rounded-lg border-l-4 border-secondary flex items-center gap-4">
          <div className="w-10 h-10 rounded-full bg-secondary-container/10 flex items-center justify-center">
            <span className="material-symbols-outlined text-secondary">gavel</span>
          </div>
          <div>
            <p className="text-[10px] uppercase text-outline tracking-wider">Legal Terms Flagged</p>
            <p className="text-xl font-bold text-on-surface">4 Matches</p>
          </div>
        </div>
        <div className="bg-surface-container-low p-5 rounded-lg border-l-4 border-primary flex items-center gap-4">
          <div className="w-10 h-10 rounded-full bg-primary-container flex items-center justify-center">
            <span className="material-symbols-outlined text-primary">timer</span>
          </div>
          <div>
            <p className="text-[10px] uppercase text-outline tracking-wider">Queue Position</p>
            <p className="text-xl font-bold text-on-surface">
              1 / 12 <span className="text-xs font-normal text-primary">Pending</span>
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
