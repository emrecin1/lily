import { useState } from 'react'

const NAV = [
  { key: 'signals', label: 'Sinyaller', icon: 'signal' },
  { key: 'settings', label: 'Ayarlar', icon: 'settings' },
]

const ICONS = {
  signal: (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="1.8"
      viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round"
        d="M3.75 13.5l2.982-2.982a.75.75 0 011.06 0l4.2 4.2a.75.75 0 001.06 0l3.103-3.103m-12.405 10.533h18m-3.75-2.25L6.75 8.25"
      />
    </svg>
  ),
  settings: (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="1.8"
      viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round"
        d="M10.343 3.94c.09-.542.56-.94 1.11-.94h1.093c.55 0 1.02.398 1.11.94l.149.894c.07.424.384.764.78.93.398.164.855.142 1.205-.108l.737-.527a1.125 1.125 0 011.45.12l.773.774c.39.389.44 1.002.12 1.45l-.527.737c-.25.35-.272.806-.107 1.204.165.397.505.71.93.78l.893.15c.543.09.94.56.94 1.109v1.094c0 .55-.397 1.02-.94 1.11l-.893.149c-.425.07-.765.383-.93.78-.165.398-.143.854.107 1.204l.527.738c.32.447.269 1.06-.12 1.45l-.774.773a1.125 1.125 0 01-1.449.12l-.738-.527c-.35-.25-.806-.272-1.203-.107-.397.165-.71.505-.781.929l-.149.894c-.09.542-.56.94-1.11.94h-1.094c-.55 0-1.019-.398-1.11-.94l-.148-.894c-.071-.424-.384-.764-.781-.93-.398-.164-.854-.142-1.204.108l-.738.527c-.447.32-1.06.269-1.45-.12l-.773-.774a1.125 1.125 0 01-.12-1.45l.527-.737c.25-.35.273-.806.108-1.204-.165-.397-.505-.71-.93-.78l-.894-.15c-.542-.09-.94-.56-.94-1.109v-1.094c0-.55.398-1.02.94-1.11l.894-.149c.424-.07.765-.383.93-.78.165-.398.143-.854-.108-1.204l-.526-.738a1.125 1.125 0 01.12-1.45l.773-.773a1.125 1.125 0 011.45-.12l.737.527c.35.25.807.272 1.204.107.397-.165.71-.505.78-.929l.15-.894z"
      />
      <path strokeLinecap="round" strokeLinejoin="round"
        d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  ),
}

export default function Sidebar({ page, onNavigate }) {
  const [open, setOpen] = useState(false)

  const link = (nav) => {
    const active = page === nav.key
    return (
      <button
        key={nav.key}
        onClick={() => { onNavigate(nav.key); setOpen(false) }}
        className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-colors
          ${active ? 'bg-indigo-500/15 text-indigo-300' : 'text-slate-400 hover:text-slate-200 hover:bg-white/5'}`}
      >
        <span className={`${active ? 'text-indigo-400' : 'text-slate-500'}`}>{ICONS[nav.icon]}</span>
        {nav.label}
      </button>
    )
  }

  return (
    <>
      {/* Mobile top bar */}
      <div className="md:hidden flex items-center justify-between px-4 py-3 border-b border-white/10 bg-[#0e1526] sticky top-0 z-40">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-indigo-500 to-emerald-500 flex items-center justify-center text-white font-bold text-sm">B</div>
          <span className="font-semibold text-white">Signal Bot</span>
        </div>
        <button onClick={() => setOpen(!open)} className="text-slate-300 p-1.5 rounded-lg hover:bg-white/5">
          <svg className="w-6 h-6" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24">
            {open ? (
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            ) : (
              <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
            )}
          </svg>
        </button>
      </div>

      {/* Slide-over for mobile */}
      {open && (
        <div className="md:hidden fixed inset-0 z-50">
          <div className="absolute inset-0 bg-black/60" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-0 bottom-0 w-64 bg-[#0e1526] border-r border-white/10 p-4">
            <div className="text-lg font-bold text-white mb-6 flex items-center gap-2">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500 to-emerald-500 flex items-center justify-center text-white font-bold">B</div>
              Signal Bot
            </div>
            <nav className="space-y-1">{NAV.map(link)}</nav>
          </div>
        </div>
      )}

      {/* Desktop sidebar */}
      <aside className="hidden md:flex flex-col w-64 shrink-0 border-r border-white/10 bg-[#0e1526] h-screen sticky top-0">
        <div className="px-5 py-6 text-lg font-bold text-white flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500 to-emerald-500 flex items-center justify-center text-white font-bold">B</div>
          <span>Signal Bot</span>
        </div>
        <nav className="px-3 space-y-1">{NAV.map(link)}</nav>
        <div className="mt-auto px-5 py-4 text-[11px] text-slate-500 leading-relaxed">
          Sadece sinyal üretimi.<br />Gerçek alım/satım yapılmaz.
        </div>
      </aside>
    </>
  )
}
