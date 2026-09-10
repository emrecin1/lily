import { useState } from 'react'
import Sidebar from './components/Sidebar'
import Signals from './pages/Signals'
import Settings from './pages/Settings'

export default function App() {
  const [page, setPage] = useState('signals')

  return (
    <div className="flex min-h-screen bg-[#0b1020] font-sans">
      <Sidebar page={page} onNavigate={setPage} />
      <main className="flex-1 px-4 py-6 md:px-8 md:py-8 max-w-6xl">
        {page === 'signals' && <Signals />}
        {page === 'settings' && <Settings />}
      </main>
    </div>
  )
}
