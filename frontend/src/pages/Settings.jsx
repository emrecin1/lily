import { useEffect, useState } from 'react'

const API = ''

const DEFAULT_SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT']

const PARAMS = [
  { key: 'ema_fast', label: 'EMA (hızlı)', type: 'number', step: '1', hint: 'Hızlı hareketli ortalama penceresi' },
  { key: 'ema_slow', label: 'EMA (yavaş)', type: 'number', step: '1', hint: 'Yavaş hareketli ortalama penceresi' },
  { key: 'rsi_buy_max', label: 'RSI alım üst sınırı', type: 'number', step: '0.5', hint: 'Bu RSI değerinin altında AL' },
  { key: 'rsi_sell_max', label: 'RSI satım üst sınırı', type: 'number', step: '0.5', hint: 'Bu RSI değerinin üstünde SAT' },
  { key: 'accuracy_horizon', label: 'Doğruluk ufku (mum)', type: 'number', step: '1', hint: 'Sinyal doğruluğu kaç mum sonrasına bakılarak ölçülür' },
  { key: 'accuracy_min_move_pct', label: 'Doğruluk eşiği (yükseliş %)', type: 'number', step: '0.001', hint: 'AL sonrası fiyatın en az bu kadar yükselmesi gerekir' },
]

function Field({ label, hint, value, onChange }) {
  return (
    <label className="block">
      <span className="text-sm font-medium text-slate-300">{label}</span>
      <input
        type="number"
        step="any"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1.5 w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
      />
      {hint && <span className="mt-1 block text-[11px] text-slate-500">{hint}</span>}
    </label>
  )
}

export default function Settings() {
  const [settings, setSettings] = useState(null)
  const [selected, setSelected] = useState([])
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    ;(async () => {
      const r = await fetch(`${API}/api/settings`)
      const s = await r.json()
      setSettings(s)
      setSelected(s.symbols || [])
    })()
  }, [])

  if (!settings) {
    return <div className="text-slate-400">Yükleniyor…</div>
  }

  function set(key, val) {
    setSettings({ ...settings, [key]: val })
    setSaved(false)
  }

  function toggleCoin(sym) {
    setSelected((prev) =>
      prev.includes(sym) ? prev.filter((s) => s !== sym) : [...prev, sym]
    )
    setSaved(false)
  }

  async function save() {
    setSaving(true)
    try {
      const r = await fetch(`${API}/api/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...settings, symbols: selected }),
      })
      const s = await r.json()
      setSettings(s)
      setSelected(s.symbols)
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    } finally {
      setSaving(false)
    }
  }

  const allSymbols = Array.from(new Set([...DEFAULT_SYMBOLS, ...selected]))

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Ayarlar</h1>
        <p className="text-sm text-slate-400 mt-0.5">İzlenecek coinleri ve kural parametrelerini ayarla.</p>
      </div>

      <section className="rounded-2xl border border-white/10 bg-white/[0.03] p-5">
        <h2 className="text-sm font-semibold text-white mb-3">Coin Seçimi</h2>
        <div className="grid grid-cols-2 gap-2">
          {allSymbols.map((sym) => {
            const on = selected.includes(sym)
            return (
              <button
                key={sym}
                onClick={() => toggleCoin(sym)}
                className={`flex items-center justify-between rounded-xl border px-3 py-2.5 text-sm font-medium transition-colors
                  ${on
                    ? 'border-indigo-500/50 bg-indigo-500/15 text-indigo-200'
                    : 'border-white/10 bg-white/5 text-slate-400 hover:border-white/20'}`}
              >
                {sym}
                <span
                  className={`w-4 h-4 rounded-full ring-2 flex items-center justify-center text-[10px]
                    ${on ? 'ring-indigo-400 bg-indigo-500 text-white' : 'ring-white/20'}`}
                >
                  {on ? '✓' : ''}
                </span>
              </button>
            )
          })}
        </div>
        {selected.length === 0 && (
          <p className="mt-2 text-xs text-rose-400">En az bir coin seçilmelidir.</p>
        )}
      </section>

      <section className="rounded-2xl border border-white/10 bg-white/[0.03] p-5">
        <h2 className="text-sm font-semibold text-white mb-4">Sinyal Parametreleri</h2>
        <div className="grid grid-cols-2 gap-4">
          {PARAMS.map((p) => (
            <Field
              key={p.key}
              label={p.label}
              hint={p.hint}
              value={settings[p.key]}
              onChange={(v) => set(p.key, v)}
            />
          ))}
        </div>
      </section>

      <div className="flex items-center gap-3">
        <button
          onClick={save}
          disabled={saving || selected.length === 0}
          className="px-5 py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-sm font-semibold transition-colors"
        >
          {saving ? 'Kaydediliyor…' : 'Kaydet'}
        </button>
        {saved && <span className="text-sm text-emerald-400">Kaydedildi ✓</span>}
      </div>
    </div>
  )
}
