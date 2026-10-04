import { useEffect, useRef, useState } from 'react'
import { Activity, ArrowRight, Check, ChevronRight, Clipboard,
  Cpu, FileCode2, FileText, FolderUp, LoaderCircle, Play, Radio, RefreshCw,
  Terminal, Unplug, X } from './icons'

type EvidenceFile = { name: string; content: string }
type Example = { id: string; title: string; category: string; description: string; text: string }
type Diagnosis = {
  summary: string; severity: string; confidence: string; confidence_reason: string;
  evidence: string[]; root_causes: { cause: string; reason: string }[];
  recommended_fix: string[]; commands: { command: string; purpose: string }[];
  explanation: string; additional_information_needed: string[];
}
type Result = { diagnosis: Diagnosis; findings: { code: string; title: string; source: string }[];
  engine: string; model: string | null; notice: string | null; elapsed_ms: number; status: 'healthy' | 'problem' | 'insufficient' }
type Health = { available: boolean; installed: boolean; reachable: boolean; model_available: boolean;
  platform: string; model: string; message: string }
type Execution = { sequence: number; command: string; output: string; exit_code: number | null;
  state: 'running' | 'finished' | 'cancelled'; cwd: string; environment: Record<string, string> }
type HistoryItem = Result & { id: string; created_at: string; category: string }
type Workspace = { revision: number; analyzing: boolean; terminal: { connected: boolean; shell: string;
  cwd: string; execution: Execution | null }; latest: Result | null; history: HistoryItem[] }

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch('/api' + path, init)
  if (!response.ok) {
    let message = `Server returned ${response.status}`
    try {
      const error = await response.json()
      message = typeof error.detail === 'string' ? error.detail : error.detail?.[0]?.msg || message
    } catch { /* A reverse proxy may return HTML. */ }
    throw new Error(message)
  }
  return response.json()
}

function CopyButton({ text }: { text: string }) {
  const [state, setState] = useState('idle')
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  useEffect(() => () => clearTimeout(timer.current), [])
  return <button className="copy" aria-label={`Copy ${text}`} onClick={async () => {
    try { await navigator.clipboard.writeText(text); setState('copied') }
    catch { setState('failed') }
    clearTimeout(timer.current)
    timer.current = setTimeout(() => setState('idle'), 2200)
  }}>{state === 'copied' ? <Check size={15} /> : <Clipboard size={15} />}
    {state === 'copied' ? 'Copied' : state === 'failed' ? 'Select to copy' : 'Copy'}</button>
}


function ReportText({ text }: { text: string }) {
  return <>{text.split(/(`[^`]+`)/g).map((part, index) => part.startsWith('`') && part.endsWith('`') ? <code key={index}>{part.slice(1,-1)}</code> : part)}</>
}

function RobotMark() {
  return <svg className="robot-mark" viewBox="0 0 40 40" aria-hidden="true">
    <path d="M20 7v5"/><circle cx="20" cy="5" r="1.5"/>
    <path d="M8 12h24v21H8z"/><path className="robot-screen" d="M11 16h18v10H11z"/>
    <path className="robot-eyes" d="M14 21h4m5 0h4"/><path d="M17 29h6"/>
  </svg>
}

function Signal({ state }: { state: string }) {
  const trace = state === 'problem' ? 'M0 12h12l4-4 4 9 4-14 5 12 4-3h31' :
    state === 'checking' ? 'M0 12h15l5-4 5 8 5-11 5 7h29' : 'M0 12h20l3-2 3 4 3-2h35'
  return <svg className={`diagnostic-signal ${state}`} viewBox="0 0 64 24" aria-hidden="true"><path d={trace}/></svg>
}

export default function App() {
  const [tab, setTab] = useState<'terminal' | 'files' | 'examples'>('terminal')
  const [text, setText] = useState('')
  const [files, setFiles] = useState<EvidenceFile[]>([])
  const [examples, setExamples] = useState<Example[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [backendReady, setBackendReady] = useState(false)
  const [mode, setMode] = useState<'auto' | 'rules'>('auto')
  const [result, setResult] = useState<Result | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [dragging, setDragging] = useState(false)
  const [setup, setSetup] = useState(false)
  const [stale, setStale] = useState(false)
  const [workspace, setWorkspace] = useState<Workspace | null>(null)
  const [terminalHelp, setTerminalHelp] = useState(false)
  const [viewingHistory, setViewingHistory] = useState<string | null>(null)
  const [nav, setNav] = useState('Diagnose')
  const [composerOpen, setComposerOpen] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const latestId = useRef<string | null>(null)
  const examplesLoaded = useRef(false)
  const lastSequence = useRef<number | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const lineNumbersRef = useRef<HTMLDivElement>(null)
  const resultRef = useRef<HTMLDivElement>(null)
  const total = text.length + files.reduce((n, f) => n + f.content.length, 0)

  async function refresh() {
    try {
      const data = await api<{ ai: Health }>('/health')
      setHealth(data.ai); setBackendReady(true)
      if (!examplesLoaded.current) {
        api<Example[]>('/examples').then(items => {
          setExamples(items); examplesLoaded.current = true
          setError(current => current.startsWith('Cannot load examples.') ? '' : current)
        }).catch(() => { /* Retry after the backend reconnects. */ })
      }
    } catch { setHealth(null); setBackendReady(false) }
  }
  useEffect(() => {
    refresh()
    const interval = setInterval(refresh, 10000)
    return () => clearInterval(interval)
  }, [])

  useEffect(() => {
    let active = true
    async function pollWorkspace() {
      try {
        const state = await api<Workspace>('/workspace')
        if (!active) return
        setWorkspace(state)
        if (!state.latest && !state.history.length && latestId.current) {
          latestId.current = null
          setResult(null); setViewingHistory(null)
        }
        const sequence = state.terminal.execution?.sequence ?? null
        if (sequence !== lastSequence.current) {
          lastSequence.current = sequence
          setSelected(null); setViewingHistory(null); setStale(false)
          if (!state.latest) setResult(null)
        }
        const id = state.history[0]?.id ?? null
        if (id !== latestId.current && state.latest) {
          latestId.current = id
          setResult(state.latest); setViewingHistory(null); setStale(false)
        }
      } catch { /* Connection state is reported by the health check. */ }
    }
    pollWorkspace()
    const interval = setInterval(pollWorkspace, 2000)
    return () => { active = false; clearInterval(interval) }
  }, [])

  useEffect(() => {
    if (!setup) return
    const before = document.activeElement as HTMLElement | null
    const modal = document.querySelector('.setup-modal') as HTMLElement
    const controls = () => Array.from(modal.querySelectorAll<HTMLElement>('button, a[href]'))
    controls()[0]?.focus()
    function keydown(event: KeyboardEvent) {
      if (event.key === 'Escape') setSetup(false)
      if (event.key === 'Tab') {
        const items = controls()
        if (event.shiftKey && document.activeElement === items[0]) { event.preventDefault(); items.at(-1)?.focus() }
        if (!event.shiftKey && document.activeElement === items.at(-1)) { event.preventDefault(); items[0]?.focus() }
      }
    }
    document.addEventListener('keydown', keydown)
    return () => { document.removeEventListener('keydown', keydown); before?.focus() }
  }, [setup])

  function edited() { setStale(true); setSelected(null) }

  async function addFiles(incoming: FileList | File[]) {
    setError('')
    const accepted: EvidenceFile[] = []
    try {
      if (files.length + incoming.length > 8) throw new Error('You can attach up to 8 files.')
      for (const file of Array.from(incoming)) {
        if (!/\.(txt|log|ya?ml|py|cpp|hpp)$/i.test(file.name)) throw new Error(`${file.name}: unsupported file type.`)
        if (file.size > 128000) throw new Error(`${file.name}: file is too large.`)
        const content = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer())
        if (content.includes('\0')) throw new Error(`${file.name}: binary files are not supported.`)
        if (content.length > 32000) throw new Error(`${file.name}: limit is 32,000 characters per file.`)
        accepted.push({ name: file.name, content })
      }
      if (total + accepted.reduce((n, f) => n + f.content.length, 0) > 60000)
        throw new Error('Combined evidence exceeds 60,000 characters.')
      setFiles([...files, ...accepted]); edited()
    } catch (e) { setError(e instanceof Error ? e.message : 'Unable to read files. Use UTF-8 text files.') }
    if (inputRef.current) inputRef.current.value = ''
  }

  async function analyze(example?: Example) {
    if (busy) return
    setError(''); setBusy(true); setResult(null); setStale(false)
    if (example) {
      setText(example.text); setFiles([]); setSelected(example.id); setTab('terminal'); setComposerOpen(false)
    }
    try {
      const data = example ? await api<Result>(`/examples/${example.id}/diagnose?mode=${mode}`, {method:'POST'}) :
        await api<Result>('/diagnose', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, files, mode }) })
      setResult(data); setNav('Diagnose')
      setViewingHistory(null)
      setTimeout(() => resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 100)
    } catch (e) { setError(e instanceof Error ? e.message : 'Unable to diagnose. Check the backend connection.') }
    finally { setBusy(false); refresh() }
  }

  async function inspectTerminal() {
    if (busy || workspace?.analyzing) return
    setNav('Diagnose'); setBusy(true); setResult(null); setError(''); setSelected(null); setViewingHistory(null); setStale(false)
    try { setResult(await api<Result>(`/terminal/diagnose?mode=${mode}`, {method:'POST'})) }
    catch(e) { setError(e instanceof Error ? e.message : 'Cannot inspect the terminal.') }
    finally { setBusy(false) }
  }

  const diagnosis = result?.diagnosis
  const headline = diagnosis?.summary.replace(/^✓\s*/, '').split(/(?<=[.!?])\s+(?=[A-Z])/)[0] || ''
  const execution = workspace?.terminal.execution
  const analyzing = busy || !!workspace?.analyzing
  const signalState = analyzing ? 'checking' : result?.status || 'idle'
  const motion = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'
  function navigate(section: string) {
    setNav(section)
    if (section === 'Settings') { setSetup(true); return }
    if (section === 'Examples') { setTab('examples'); setComposerOpen(true) }
    if (section === 'History') setHistoryOpen(true)
    if (section === 'Terminal') setTerminalHelp(!workspace?.terminal.connected)
    const anchor = section === 'Terminal' ? '.session-panel' : section === 'Examples' ? '.input-disclosure' : section === 'History' ? '.recent-diagnostics' : '.results'
    requestAnimationFrame(() => document.querySelector(anchor)?.scrollIntoView({behavior:motion, block:'start'}))
  }
  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="#" onClick={e => {e.preventDefault(); navigate('Diagnose')}}><RobotMark/><span>RoboDoctor<small>PYTHON / ROS2</small></span></a>
      <nav aria-label="Workspace">
        {([['Diagnose', Activity], ['Terminal', Terminal], ['Examples', FileCode2], ['History', Clipboard], ['Settings', Cpu]] as const).map(([label, Icon]) =>
          <button key={label} className={`nav-item ${nav === label ? 'active' : ''}`} aria-current={nav === label ? 'page' : undefined} onClick={() => navigate(label)}><Icon size={16}/><span>{label}</span></button>)}
      </nav>
      <div className="sidebar-bottom"><span className="tiny-dot"/> Local workspace <span>v1.0</span></div>
    </aside>
    <div className="main-shell">
      <header className="topbar"><span className="workspace-label">WORKSPACE <span>/</span> Python + ROS2</span>
        <div className="connection-indicators">
          <button className={`status ${health?.available ? 'ready' : 'unavailable'}`} aria-label={`Gemma: ${health?.available ? 'connected' : backendReady ? 'setup needed' : 'backend offline'}`} title={`${health?.model || 'gemma3:4b'} · Ollama · ${health?.message || 'Backend offline'}`} onClick={() => setSetup(true)}><span className="tiny-dot"/>Gemma</button>
          <button className={`status ${workspace?.terminal.connected ? 'ready' : ''}`} title={workspace?.terminal.connected ? execution?.state === 'running' ? 'Terminal running' : 'Terminal connected' : 'Terminal disconnected — open it from the desktop icon'} aria-label={`Terminal: ${workspace?.terminal.connected ? 'connected' : 'disconnected'}`} onClick={() => {navigate('Terminal'); setTerminalHelp(!terminalHelp)}}><span className={`tiny-dot ${execution?.state === 'running' ? 'listening' : ''}`}/>Terminal{execution?.state === 'running' && <small>listening</small>}</button>
        </div>
      </header>
      <main>
        {!backendReady && <div className="connection-note" role="status">Backend unavailable. <button onClick={refresh}>Retry</button></div>}
        {!health?.available && backendReady && <div className="connection-note"><span>{health?.installed ? health.reachable ? 'Gemma model is missing.' : 'Ollama is not running.' : 'Ollama is not installed.'} Rules remain available.</span><button onClick={() => setSetup(true)}>Setup <ArrowRight size={13}/></button></div>}
        {error && <div role="alert" className="error"><Unplug size={16}/>{error}</div>}
        <div ref={resultRef} className="results" data-state={signalState}>
          <div className="results-title"><h1>{viewingHistory ? 'Past diagnosis' : 'Latest diagnosis'}</h1><div><span className="engine-label">{result?.engine === 'local-ai' ? result.model : result?.engine === 'rules' ? 'Rules' : result?.engine === 'observed' ? 'From terminal' : analyzing ? 'Reading output' : 'Ready'}</span><Signal state={signalState}/></div></div>
          {!diagnosis ? <section className="empty-result"><Radio size={19}/><div><h2>{analyzing ? 'Analyzing terminal…' : execution ? 'Recent output is ready.' : 'Ready when you are.'}</h2><p>{analyzing ? 'Checking the supplied output. This may take a moment.' : execution ? 'Inspect the latest run to see what happened.' : 'Run a command in the managed terminal, or add evidence below.'}</p>{!analyzing && <button className="text-button" onClick={() => {setComposerOpen(true); requestAnimationFrame(() => document.querySelector('.input-disclosure')?.scrollIntoView({behavior:motion}))}}>Add evidence <ArrowRight size={13}/></button>}</div></section> : <>
            {selected && <div className="example-badge">Example / {examples.find(e => e.id === selected)?.title}</div>}
            {stale && <div className="notice">Evidence changed. Inspect again to update this report.</div>}
            <section className={`diagnosis-card ${result?.status === 'healthy' ? 'healthy-card' : ''}`}>
              <span className="diagnosis-kicker">{result?.status === 'healthy' ? <><Check size={17}/> Successful run</> : result?.status === 'problem' ? <><Activity size={17}/> Needs attention</> : 'Needs context'}</span>
              <h2><ReportText text={headline}/></h2>
              {result?.status === 'healthy' ? <p>The latest command completed without a detected error.</p> : <details className="confidence"><summary>Confidence: {diagnosis.confidence}<ChevronRight size={11}/></summary>{headline !== diagnosis.summary && <p><ReportText text={diagnosis.summary}/></p>}<p>{diagnosis.confidence_reason}</p></details>}
              {result?.notice && result.status !== 'healthy' && <details className="engine-note"><summary>Rules-only report <span>Details</span></summary><p>{result.notice}</p><button className="text-button" onClick={() => setSetup(true)}>Model setup</button></details>}
            </section>
            {result?.status !== 'healthy' && <div className="diagnosis-details" key={viewingHistory || latestId.current || diagnosis.summary}>
              <details className="report-disclosure"><summary><span>Evidence</span><small>Quoted / {diagnosis.evidence.length} {diagnosis.evidence.length === 1 ? 'line' : 'lines'}</small><ChevronRight size={14}/></summary><div className="report-body"><div className="evidence-lines">{diagnosis.evidence.length ? diagnosis.evidence.map((line, i) => <pre key={i}><span>{String(i+1).padStart(2,'0')}</span>{line}</pre>) : <p>No supporting failure lines found.</p>}</div>{result?.findings.map((finding,i) => <p className="finding" key={i}>{finding.title}<small>{finding.source}</small></p>)}</div></details>
              <details className="report-disclosure"><summary><span>Likely cause</span><small>To verify</small><ChevronRight size={14}/></summary><div className="report-body">{diagnosis.root_causes.length ? diagnosis.root_causes.map((cause,i) => <div className="root-cause" key={i}><strong><ReportText text={cause.cause}/></strong><p><ReportText text={cause.reason}/></p></div>) : <p>More evidence is needed.</p>}</div></details>
              <details className="report-disclosure fix-disclosure" open><summary><span>{result?.status === 'insufficient' ? 'Next step' : 'Fix'}</span><small>{result?.status === 'insufficient' ? 'More context needed' : 'Review before applying'}</small><ChevronRight size={14}/></summary><div className="report-body"><ol className="fix-list">{diagnosis.recommended_fix.map((fix,i) => <li key={i}><ReportText text={fix}/></li>)}</ol>{!diagnosis.recommended_fix.length && <p>Gather the missing evidence before choosing a fix.</p>}
                {diagnosis.commands.length > 0 && <details className="command-disclosure"><summary>Try this <span>{diagnosis.commands.length} {diagnosis.commands.length === 1 ? 'suggestion' : 'suggestions'}</span><ChevronRight size={12}/></summary><p className="command-note">Copy to inspect. Commands are never run automatically.</p>{diagnosis.commands.map((command,i) => <div className="command-row" key={i}><div><code><span>$ </span>{command.command}</code><p>{command.purpose}</p></div><CopyButton text={command.command}/></div>)}</details>}
              </div></details>
              <details className="report-disclosure"><summary><span>Why it happened</span><ChevronRight size={14}/></summary><div className="report-body"><p><ReportText text={diagnosis.explanation}/></p></div></details>
              <details className="report-disclosure"><summary><span>What to check next</span><ChevronRight size={14}/></summary><div className="report-body">{diagnosis.additional_information_needed.length ? <ul className="next-info">{diagnosis.additional_information_needed.map((info,i) => <li key={i}>{info}</li>)}</ul> : <p>Use the suggested commands to verify the cause.</p>}<button className="text-button" onClick={() => {setText(''); setFiles([]); setResult(null); setSelected(null); setTab('terminal'); setComposerOpen(true)}}><RefreshCw size={13}/> New diagnosis</button></div></details>
            </div>}
          </>}
        </div>
        <section className="session-panel">
          <div className="session-heading"><h2><Terminal size={15}/> Recent output</h2><div><span className={`session-state ${execution?.state === 'running' ? 'listening' : ''}`}>{execution ? execution.state === 'running' ? 'Running' : execution.state === 'cancelled' ? 'Stopped' : `Exit ${execution.exit_code}` : workspace?.terminal.connected ? 'Connected' : 'No session'}</span><button className="primary" disabled={analyzing || !execution || execution.state === 'running'} onClick={inspectTerminal}>{analyzing ? <LoaderCircle className="spin" size={13}/> : <Activity size={13}/>}Inspect</button></div></div>
          {terminalHelp && <p className="terminal-help">Right-click the desktop robot → Open managed terminal. Run a command, then double-click the robot to inspect it.</p>}
          {execution ? <><div className="execution-line"><code>$ {execution.command}</code></div><pre className="output-preview">{execution.output.split('\n').filter(line => line.trim()).slice(-3).join('\n') || '(No output)'}</pre><details className="captured-output"><summary>View full output <ChevronRight size={11}/></summary><pre>{execution.output || '(No output)'}</pre><small>{execution.cwd}</small></details></> : <p className="session-empty">No captured output yet. Open the terminal from the desktop icon.</p>}
        </section>
        <details className="recent-diagnostics" open={historyOpen} onToggle={event => setHistoryOpen(event.currentTarget.open)}><summary><span>History</span><small>{workspace?.history.length || 0} recent reports</small><ChevronRight size={14}/></summary>{workspace?.history.length ? <div className="history-list">{workspace.history.map(item => <button key={item.id} className={viewingHistory === item.id ? 'chosen' : ''} onClick={() => {setResult(item); setViewingHistory(item.id); setSelected(null); setNav('Diagnose'); resultRef.current?.scrollIntoView({behavior:motion})}}><span className={`history-dot ${item.status}`}/><span><strong>{item.diagnosis.summary}</strong><small>{item.category} / {item.engine === 'local-ai' ? item.model : item.engine === 'observed' ? 'From terminal' : 'Rules'}</small></span><time>{new Date(item.created_at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}</time><ChevronRight size={13}/></button>)}</div> : <p className="session-empty">No reports in this session. History resets when the backend restarts.</p>}</details>
        <details className="input-disclosure" open={composerOpen} onToggle={event => setComposerOpen(event.currentTarget.open)}><summary><span>Add evidence</span><small>Paste / files / examples</small><ChevronRight size={14}/></summary><section className="input-panel">
          <div className="tabs" role="tablist" aria-label="Evidence input mode">{([['terminal',Terminal,'Paste'],['files',FolderUp,'Files'],['examples',FileCode2,'Examples']] as const).map(([key,Icon,label]) => <button key={key} id={`tab-${key}`} role="tab" aria-selected={tab===key} aria-controls="evidence-panel" disabled={busy} className={tab===key ? 'selected' : ''} onClick={() => setTab(key)}><Icon size={14}/>{label}</button>)}</div>
          <div id="evidence-panel" role="tabpanel" aria-labelledby={`tab-${tab}`}>
            {tab==='terminal' && <><div className="editor-bar"><span>terminal / evidence</span><span>PLAIN TEXT</span></div><div className="editor"><div className="line-numbers" ref={lineNumbersRef} aria-hidden="true">{Array.from({length:Math.max(10,text.split('\n').length)},(_,i) => <span key={i}>{i+1}</span>)}</div><textarea aria-label="Terminal evidence" disabled={busy} spellCheck={false} wrap="off" maxLength={60000} value={text} onScroll={e => {if(lineNumbersRef.current) lineNumbersRef.current.scrollTop=e.currentTarget.scrollTop}} onChange={e => {setText(e.target.value); edited()}} placeholder={'$ python robot.py\nTraceback (most recent call last):\n...\n\nPaste the command and its output.'}/></div></>}
            {tab==='files' && <div className="file-content"><button className={`dropzone ${dragging ? 'dragging' : ''}`} disabled={busy} onClick={() => inputRef.current?.click()} onDragOver={e => {e.preventDefault(); setDragging(true)}} onDragLeave={() => setDragging(false)} onDrop={e => {e.preventDefault(); setDragging(false); if(!busy) addFiles(e.dataTransfer.files)}}><FolderUp size={22}/><strong>Drop text files or browse</strong><small>.txt .log .yaml .yml .py .cpp .hpp</small><small>8 files / 32k characters each / UTF-8</small></button><p className="file-note">Files are read as text, never executed.</p></div>}
            {tab==='examples' && <div className="example-list">{examples.map(example => <button className="example-row" key={example.id} disabled={busy} onClick={() => analyze(example)}><FileCode2 size={16}/><span><strong>{example.title}</strong><small>{example.description}</small></span><Play size={13}/></button>)}{!examples.length && <p>Start the backend to load examples.</p>}</div>}
          </div>
          <input ref={inputRef} type="file" hidden multiple accept=".txt,.log,.yaml,.yml,.py,.cpp,.hpp" onChange={e => e.target.files && addFiles(e.target.files)}/>
          {files.length>0 && <div className="attachments">{files.map((file,index) => <div key={`${file.name}-${index}`}><FileText size={13}/><span>{file.name}</span><small>{file.content.length.toLocaleString()} chars</small><button disabled={busy} aria-label={`Remove ${file.name}`} onClick={() => {setFiles(files.filter((_,i) => i!==index)); edited()}}><X size={13}/></button></div>)}</div>}
          <div className="editor-footer"><span>Local evidence</span><span>{total.toLocaleString()} / 60,000 chars</span></div>
          <div className="action-bar"><label>Engine<select aria-label="Analysis engine" disabled={busy} value={mode} onChange={e => setMode(e.target.value as 'auto'|'rules')}><option value="auto">Gemma + rules</option><option value="rules">Rules only</option></select></label><button className="primary" disabled={busy || !backendReady || total===0 || total>60000} onClick={() => analyze()}>{busy ? <LoaderCircle className="spin" size={14}/> : <Activity size={14}/>} {busy ? 'Analyzing…' : 'Inspect evidence'}</button></div>
          {busy && <div className="working" role="status">Checking the supplied evidence…</div>}
          <details className="hint-tools"><summary>Need an example?</summary><div><button className="text-button" disabled={busy || !examples.length || !backendReady} onClick={() => analyze(examples[0])}>Inspect /cmd_vel example <ArrowRight size={13}/></button><p>Include the command, output, and expected behavior.</p><div className="tip-command"><code>ros2 node list</code><CopyButton text="ros2 node list"/></div><div className="tip-command"><code>ros2 topic list -t</code><CopyButton text="ros2 topic list -t"/></div></div></details>
        </section></details>
        <footer><span><strong>RoboDoctor</strong><span className="footer-credit">Made by Shreyansh Chauhan</span></span><span>v1.0</span></footer>
      </main>
    </div>
    {setup && <div className="modal-backdrop" onClick={() => setSetup(false)}><section className="setup-modal panel" role="dialog" aria-modal="true" aria-labelledby="setup-title" onClick={e => e.stopPropagation()}><button className="modal-close" aria-label="Close model setup" onClick={() => setSetup(false)}><X size={20} /></button><span className="setup-icon"><Cpu size={24} /></span><h2 id="setup-title">Connect Gemma locally</h2><p>{health?.message || 'Start the RoboDoctor backend.'}</p><div className="setup-checks"><span>{health?.installed ? '✓' : '○'} Ollama found</span><span>{health?.reachable ? '✓' : '○'} API reachable</span><span>{health?.model_available ? '✓' : '○'} Model available</span></div><p>Install Ollama using the official option for your platform:</p><a href="https://ollama.com/download/windows" target="_blank" rel="noreferrer">Windows download</a><div className="setup-command"><code>irm https://ollama.com/install.ps1 | iex</code><CopyButton text="irm https://ollama.com/install.ps1 | iex" /></div><a href="https://ollama.com/download/linux" target="_blank" rel="noreferrer">Ubuntu / Linux download</a><div className="setup-command"><code>curl -fsSL https://ollama.com/install.sh | sh</code><CopyButton text="curl -fsSL https://ollama.com/install.sh | sh" /></div><p>After installing, run:</p><div className="setup-command"><code>ollama run {health?.model || 'gemma3:4b'}</code><CopyButton text={`ollama run ${health?.model || 'gemma3:4b'}`} /></div><p>The first run explicitly downloads the model (Gemma 3 4B is about 3.3 GB). RoboDoctor never runs these setup commands or downloads weights for you. If the API remains offline, start Ollama or run <code>ollama serve</code>.</p><p>The connection is checked automatically. Change MODEL_NAME in .env and restart the backend to select another downloaded local model.</p><button className="primary" onClick={() => refresh()}><RefreshCw size={15} /> Check connection</button></section></div>}
  </div>
}
