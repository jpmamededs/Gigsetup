import { useEffect, useState } from 'react'
import toast, { Toaster } from 'react-hot-toast'
import { CirclePlay, CircleStop } from 'lucide-react'
import { VscVscode } from 'react-icons/vsc'
import { SiClaude, SiCursor } from 'react-icons/si'

export default function App() {
  const [ready, setReady] = useState(false)
  const [running, setRunning] = useState(false)

  useEffect(() => {
    const onReady = async () => {
      await refreshState()
      setReady(true)
    }

    window.addEventListener('pywebviewready', onReady)
    const t = setTimeout(onReady, 300)

    return () => {
      window.removeEventListener('pywebviewready', onReady)
      clearTimeout(t)
    }
  }, [])

  useEffect(() => {
    if (!ready) return

    const timer = setInterval(async () => {
      await refreshState()
    }, 1200)

    return () => clearInterval(timer)
  }, [ready])

  async function callApi(method, ...args) {
    if (!window.pywebview?.api?.[method]) {
      throw new Error('Python API is not available.')
    }
    return window.pywebview.api[method](...args)
  }

  async function refreshState() {
    try {
      const state = await callApi('get_state')
      if (state?.ok) {
        setRunning(Boolean(state.running))
      }
    } catch {
      // Ignore while bootstrap not completed.
    }
  }

  function showToast(message, ok = true) {
    if (ok) {
      toast.success(message)
      return
    }
    toast.error(message)
  }

  async function onStart() {
    await callApi('update_config', {
      serverMode: 'streamable-http',
      host: '127.0.0.1',
      port: '8000',
      apiKey: ''
    })
    const payload = await callApi('start_server')
    showToast(payload?.ok ? 'Server is running.' : 'Could not start the server.', Boolean(payload?.ok))
    await refreshState()
  }

  async function onStop() {
    const payload = await callApi('stop_server')
    showToast(payload?.ok ? 'Server stopped.' : 'Server is not running.', Boolean(payload?.ok))
    await refreshState()
  }

  async function onToggleServer() {
    if (running) {
      await onStop()
      return
    }
    await onStart()
  }

  async function connectClient(clientName) {
    const payload = await callApi('connect_client', clientName)
    showToast(payload?.ok ? `${clientName} connected.` : `Could not connect ${clientName}.`, Boolean(payload?.ok))
  }

  const endpointPreview = 'http://127.0.0.1:8000/mcp'

  return (
    <div className="min-h-screen bg-[#000000] text-zinc-100">
      <Toaster
        position="top-right"
        toastOptions={{
          style: {
            background: '#0f0f0f',
            color: '#f4f4f5',
            borderRadius: '12px',
            border: 'none'
          }
        }}
      />
      <main className="mx-auto w-full max-w-[920px] px-5 py-10 md:px-8">
        <section className="simple-panel">
          <div className="mb-7">
            <img src="./assets/gigsetup-white-full.svg" alt="Gig Setup" className="brand-logo" />
          </div>

          <h1 className="text-3xl font-semibold leading-tight text-zinc-100 md:text-4xl">Music organizer</h1>
          <p className="subtitle mt-3 text-lg text-zinc-400">Click Start to turn on your local helper.</p>

          <div className="mt-6 flex flex-wrap items-center gap-3">
            <button className={`btn-site ${running ? 'btn-site-danger' : 'btn-site-primary'}`} onClick={onToggleServer}>
              {running ? <CircleStop size={18} /> : <CirclePlay size={18} />}
              <span>{running ? 'Stop' : 'Start'}</span>
            </button>
            <StatusBadge ready={ready} running={running} />
          </div>

          <div className="mt-6 rounded-xl bg-zinc-900 px-4 py-3 text-sm text-zinc-400">
            <p className="subtitle">Local server address:</p>
            <p className="mt-1 font-mono text-zinc-200">{endpointPreview}</p>
          </div>

          {running && (
            <div className="mt-8">
              <h2 className="site-title">Connect now</h2>
              <p className="subtitle mt-2 text-sm text-zinc-400">Choose where you want to use it:</p>

              <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
                <button className="client-btn" onClick={() => connectClient('vscode')}>
                  <VscVscode size={18} />
                  <span>VS Code</span>
                </button>

                <button className="client-btn" onClick={() => connectClient('cursor')}>
                  <SiCursor size={18} />
                  <span>Cursor</span>
                </button>

                <button className="client-btn" onClick={() => connectClient('claude')}>
                  <SiClaude size={18} />
                  <span>Claude</span>
                </button>
              </div>
            </div>
          )}
        </section>
      </main>
    </div>
  )
}

function StatusBadge({ ready, running }) {
  if (!ready) {
    return <span className="status-site bg-zinc-800 text-zinc-300">Connecting...</span>
  }
  if (running) {
    return <span className="status-site bg-zinc-800 text-emerald-300">Running</span>
  }
  return <span className="status-site bg-zinc-800 text-zinc-400">Stopped</span>
}
