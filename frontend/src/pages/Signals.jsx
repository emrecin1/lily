import { useCallback, useEffect, useRef, useState } from 'react'
import { SignalBadge, Accuracy } from '../components/ui'
import { fmtMoney, fmtTime } from '../format'

const API = ''

export default function Signals() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [live, setLive] = useState(false)
  const wsRef = useRef(null)

  const refresh = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/signals`)
      setData(await r.json())
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${protocol}://${window.location.host}/ws/signals`)
    ws.onopen = () => setLive(true)
    ws.onclose = () => setLive(false)
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data)
      if (msg.type === 'signals_updated' || msg.type === 'signals_snapshot') {
        if (msg.data) setData(msg.data)
        else refresh()
      }
    }
    wsRef.current = ws
    return () => ws.close()
  }, [refresh])

  async function runScan() {
    setScanning(true)
    try {
      await fetch(`${API}/api/signals/run`, { method: 'POST' })
      await refresh()
    } finally {
      setScanning(false)
    }
  }

  const coins = data?.coins || []
  const generatedAt = data?.generated_at

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">Sinyaller</h1>
          <p className="text-sm text-slate-400 mt-0.5">
            {generatedAt ? `Son üretim: ${fmtTime(generatedAt)}` : 'Henüz sinyal üretilmedi'}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className={`flex items-center gap-1.5 text-xs font-medium ${live ? 'text-emerald-400' : 'text-slate-500'}`}>
            <span className={`w-2 h-2 rounded-full ${live ? 'bg-emerald-400 animate-pulse' : 'bg-slate-600'}`} />
            {live ? 'Canlı bağlantı' : 'Bağlantı yok'}
          </span>
          <button
            onClick={runScan}
            disabled={scanning}
            className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm font-semibold transition-colors"
          >
            {scanning ? 'Taranıyor…' : 'Şimdi Tara'}
          </button>
        </div>
      </div>

      {loading ? (
        <div className="grid md:grid-cols-2 gap-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-40 rounded-2xl bg-white/5 animate-pulse" />
          ))}
        </div>
      ) : coins.length === 0 ? (
        <div className="rounded-2xl border border-white/10 bg-white/5 p-10 text-center text-slate-400">
          Sinyal yok. Üstteki <b>Şimdi Tara</b> butonuna bas veya Ayarlar'dan coin seç.
        </div>
      ) : (
        <div className="grid md:grid-cols-2 gap-4">
          {coins.map((c) => <CoinCard key={c.symbol} coin={c} />)}
        </div>
      )}
    </div>
  )
}

function CoinCard({ coin }) {
  const [showAll, setShowAll] = useState(false)
  const records = coin?.records || []
  // latest non-HOLD first, then everything else
  const latest = records[records.length - 1]
  const shown = showAll ? records : records.slice(-12)

  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-5 hover:border-white/20 transition-colors">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-slate-700 to-slate-900 ring-1 ring-white/10 flex items-center justify-center font-bold text-white">
            {coin.symbol.slice(0, 3)}
          </div>
          <div>
            <div className="font-semibold text-white">{coin.symbol}</div>
            <div className="text-xs text-slate-500">{coin.num_signals} sinyal · {coin.num_al} AL</div>
          </div>
        </div>
        <Accuracy value={coin.accuracy} evaluated={coin.evaluated} />
      </div>

      {latest && (
        <div className="rounded-xl bg-white/5 p-3 flex items-center justify-between mb-3">
          <div>
            <div className="text-xs text-slate-400">Son sinyal</div>
            <div className="text-sm font-semibold text-white">{fmtTime(latest.timestamp)}</div>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-sm font-medium text-slate-300">{fmtMoney(latest.price)}</span>
            <SignalBadge action={latest.action} />
          </div>
        </div>
      )}

      <div className="max-h-48 overflow-y-auto rounded-lg border border-white/5">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-[#0e1526]">
            <tr className="text-slate-500">
              <th className="text-left px-3 py-2 font-medium">Zaman</th>
              <th className="text-left px-3 py-2 font-medium">Fiyat</th>
              <th className="text-left px-3 py-2 font-medium">RSI</th>
              <th className="text-left px-3 py-2 font-medium">Sinyal</th>
              <th className="text-left px-3 py-2 font-medium">Sonuç</th>
            </tr>
          </thead>
          <tbody className="text-slate-300">
            {shown.map((r, i) => (
              <tr key={i} className="border-t border-white/5 hover:bg-white/5">
                <td className="px-3 py-1.5 whitespace-nowrap text-slate-400">{fmtTime(r.timestamp)}</td>
                <td className="px-3 py-1.5">{fmtMoney(r.price)}</td>
                <td className="px-3 py-1.5">{r.rsi !== null && r.rsi !== undefined ? r.rsi.toFixed(1) : '—'}</td>
                <td className="px-3 py-1.5"><SignalBadge action={r.action} /></td>
                <td className="px-3 py-1.5">
                  {r.outcome === 'hit' && <span className="text-emerald-400 font-semibold">✓</span>}
                  {r.outcome === 'miss' && <span className="text-rose-400 font-semibold">✗</span>}
                  {!r.outcome && <span className="text-slate-600">—</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {!showAll && records.length > 12 && (
        <button
          onClick={() => setShowAll(true)}
          className="mt-3 text-xs text-indigo-400 hover:text-indigo-300"
        >
          {records.length} sinyalin tümünü göster
        </button>
      )}
      {showAll && (
        <button
          onClick={() => setShowAll(false)}
          className="mt-3 text-xs text-indigo-400 hover:text-indigo-300"
        >
          Daralt
        </button>
      )}
    </div>
  )
}
