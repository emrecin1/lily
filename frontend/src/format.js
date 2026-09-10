export function fmtMoney(v) {
  if (v === null || v === undefined) return '—'
  return `$${Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 })}`
}

export function fmtPct(v) {
  if (v === null || v === undefined) return '—'
  return `${(Number(v) * 100).toFixed(2)}%`
}

export function fmtTime(v) {
  if (!v) return '—'
  return String(v).replace('T', ' ').slice(0, 19)
}
