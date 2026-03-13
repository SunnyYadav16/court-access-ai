export default function ScreenLabel({ name }: { name: string }) {
  return (
    <div className="fixed bottom-3 left-1/2 -translate-x-1/2 z-50 px-4 py-1.5 rounded-full text-[11px] font-semibold tracking-wide shadow-lg"
      style={{ background: "#0B1D3A", color: "#C8963E" }}>
      {name}
    </div>
  )
}
