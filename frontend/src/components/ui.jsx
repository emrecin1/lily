export function SignalBadge({ action }) {
  const styles = {
    AL: 'bg-emerald-500/15 text-emerald-400 ring-emerald-500/30',
    SAT: 'bg-rose-500/15 text-rose-400 ring-rose-500/30',
    HOLD: 'bg-slate-500/15 text-slate-400 ring-slate-500/30',
  }
  const label = { AL: 'AL', SAT: 'SAT', HOLD: 'BEKLE' }
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-bold ring-1 ${styles[action] || styles.HOLD}`}>
      {label[action] || 'BEKLE'}
    </span>
  )
}

export function Accuracy({ value, evaluated }) {
  if (value === null || value === undefined) {
    return (
      <span className="text-xs font-semibold text-slate-500">
        Doğruluk —<span className="text-slate-600"> (değerlendirilmedi)</span>
      </span>
    )
  }
  const pct = value * 100
  const color = pct >= 55 ? 'text-emerald-400' : pct >= 45 ? 'text-amber-400' : 'text-rose-400'
  return (
    <div>
      <span className={`text-sm font-bold ${color}`}>{pct.toFixed(1)}%</span>
      <span className="ml-1 text-[11px] text-slate-500">doğruluk · {evaluated} AL değerlendirildi</span>
    </div>
  )
}
