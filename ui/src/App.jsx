import { useEffect, useState } from 'react'
import toast, { Toaster } from 'react-hot-toast'
import { CirclePlay, CircleStop, Cable, Network } from 'lucide-react'
import { VscVscode } from 'react-icons/vsc'
import { SiClaude, SiCursor } from 'react-icons/si'
import { Badge, Box, Button, Container, Flex, Grid, Heading, RadioCards, Separator, Text, TextField, Theme } from '@radix-ui/themes'

export default function App() {
  const [ready, setReady] = useState(false)
  const [running, setRunning] = useState(false)
  const [config, setConfig] = useState({
    serverName: 'dj-music-metadata',
    serverMode: 'stdio',
    host: '127.0.0.1',
    port: '8000',
    apiKey: ''
  })

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
        if (state.config) {
          setConfig((prev) => ({ ...prev, ...state.config }))
        }
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

  async function saveConfig() {
    const payload = await callApi('update_config', config)
    if (!payload?.ok) {
      showToast(payload?.message || 'Invalid configuration.', false)
      return false
    }
    return true
  }

  async function onStart() {
    const ok = await saveConfig()
    if (!ok) return

    if (config.serverMode === 'stdio') {
      showToast('In stdio mode, no manual start is required. Connect directly in your client.')
      return
    }

    const payload = await callApi('start_server')
    showToast(payload?.ok ? 'Server is running.' : payload?.message || 'Could not start the server.', Boolean(payload?.ok))
    await refreshState()
  }

  async function onStop() {
    if (config.serverMode === 'stdio') {
      showToast('In stdio mode, the client manages the process lifecycle.')
      return
    }

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
    const ok = await saveConfig()
    if (!ok) return

    const payload = await callApi('connect_client', clientName)
    showToast(
      payload?.ok ? `${clientName} connected.` : payload?.message || `Could not connect ${clientName}.`,
      Boolean(payload?.ok)
    )
    await refreshState()
  }

  const isHttp = config.serverMode === 'streamable-http'

  return (
    <Theme appearance="dark" accentColor="cyan" grayColor="sand" radius="large" scaling="100%">
      <Toaster
        position="top-right"
        toastOptions={{
          style: {
            background: '#0b0b0b',
            color: '#f3fbff',
            borderRadius: '12px',
            border: '1px solid #2a2a2a'
          }
        }}
      />
      <Container size="3" px="4" py="4" className="app-root">
        <Box className="flat-layout">
          <Flex direction="column" gap="4">
            <Flex align="center" justify="between" wrap="wrap" gap="3">
              <Box>
                <img src="./assets/gigsetup-white-full.svg" alt="Gig Setup" className="brand-logo" />
                <Heading size="8" mt="4">MCP Control Center</Heading>
                <Text size="3" color="gray">One-click local MCP setup for VS Code, Cursor, and Claude.</Text>
              </Box>
            </Flex>

            <Separator size="4" />

            <Grid columns={{ initial: '1', md: '2' }} gap="4">
              <Box>
                <Text size="2" weight="medium" mb="2" as="div">Server name</Text>
                <TextField.Root
                  value={config.serverName}
                  onChange={(e) => setConfig((prev) => ({ ...prev, serverName: e.target.value }))}
                  placeholder="dj-music-metadata"
                />
              </Box>

              <Box>
                <Text size="2" weight="medium" mb="2" as="div">Transport mode</Text>
                <RadioCards.Root
                  columns={{ initial: '1', sm: '2' }}
                  value={config.serverMode}
                  onValueChange={(value) => setConfig((prev) => ({ ...prev, serverMode: value }))}
                >
                  <RadioCards.Item value="stdio">
                    <Flex align="center" gap="2">
                      <Cable size={16} />
                      <Text size="2">stdio (default)</Text>
                    </Flex>
                  </RadioCards.Item>
                  <RadioCards.Item value="streamable-http">
                    <Flex align="center" gap="2">
                      <Network size={16} />
                      <Text size="2">streamable-http</Text>
                    </Flex>
                  </RadioCards.Item>
                </RadioCards.Root>
              </Box>

              <Box>
                <Text size="2" weight="medium" mb="2" as="div">Host</Text>
                <TextField.Root
                  value={config.host}
                  onChange={(e) => setConfig((prev) => ({ ...prev, host: e.target.value }))}
                  placeholder="127.0.0.1"
                  disabled={!isHttp}
                />
              </Box>

              <Box>
                <Text size="2" weight="medium" mb="2" as="div">Port</Text>
                <TextField.Root
                  value={config.port}
                  onChange={(e) => setConfig((prev) => ({ ...prev, port: e.target.value }))}
                  placeholder="8000"
                  disabled={!isHttp}
                />
              </Box>
            </Grid>

            <Flex align="center" gap="3" wrap="wrap">
              <Button size="3" onClick={onToggleServer} color={running ? 'ruby' : 'cyan'}>
                {running ? <CircleStop size={18} /> : <CirclePlay size={18} />}
                {isHttp ? (running ? 'Stop server' : 'Start server') : 'Check stdio mode'}
              </Button>
              <StatusBadge ready={ready} running={running} mode={config.serverMode} />
            </Flex>

            {(running || !isHttp) && (
              <>
                <Separator size="4" />
                <Text size="3" weight="medium">Connect client</Text>
                <Grid columns={{ initial: '1', sm: '3' }} gap="3">
                  <Button className="client-btn" size="3" variant="soft" onClick={() => connectClient('vscode')}>
                    <VscVscode size={18} /> VS Code
                  </Button>
                  <Button className="client-btn" size="3" variant="soft" onClick={() => connectClient('cursor')}>
                    <SiCursor size={18} /> Cursor
                  </Button>
                  <Button className="client-btn" size="3" variant="soft" onClick={() => connectClient('claude')}>
                    <SiClaude size={18} /> Claude
                  </Button>
                </Grid>
              </>
            )}
          </Flex>
        </Box>
      </Container>
    </Theme>
  )
}

function StatusBadge({ ready, running, mode }) {
  if (!ready) {
    return <Badge color="gray" variant="soft" size="3">Connecting...</Badge>
  }
  if (mode === 'stdio') {
    return <Badge color="amber" variant="soft" size="3">Managed by client</Badge>
  }
  if (running) {
    return <Badge color="green" variant="soft" size="3">Running</Badge>
  }
  return <Badge color="gray" variant="soft" size="3">Stopped</Badge>
}
