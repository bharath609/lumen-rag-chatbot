import { useEffect, useMemo, useState } from 'react'
import { clearLibrary, getHealth, getLibrary, sendChat, uploadDocuments } from './api'
import './styles.css'

const ACCEPTED_FORMATS = '.pdf,.txt,.md,.mdx,.rst,.log,.tex,.xml,.yaml,.yml,.ini,.toml,.cfg,.conf,.sql,.py,.js,.jsx,.ts,.tsx,.java,.c,.h,.cpp,.hpp,.cs,.go,.rs,.rb,.php,.swift,.kt,.kts,.sh,.bash,.ps1,.bat,.cmd,.css,.scss,.sass,.less,.svg,.docx,.pptx,.xlsx,.xlsm,.xls,.csv,.tsv,.html,.htm,.json,.jsonl'
const ACCEPTED_LABEL = 'PDF, DOCX, PPTX, XLS/XLSX, TXT/MD, CSV, HTML, JSON, code'

const DEMO_DOCUMENTS = [
  { source: '2025-product-brief.pdf', type: 'pdf', size: 2840000, chunk_count: 38, page_count: 12, created_at: '2025-02-14T10:00:00Z' },
  { source: 'brand-voice.md', type: 'md', size: 18400, chunk_count: 9, page_count: null, created_at: '2025-02-12T10:00:00Z' },
  { source: 'customer-research.csv', type: 'csv', size: 94200, chunk_count: 24, page_count: null, created_at: '2025-02-08T10:00:00Z' },
]

const DEMO_CITATIONS = [
  { index: 1, source: '2025-product-brief.pdf', page: 4, score: 0.94, text: 'Lumen brings retrieval, grounding, and citation into one focused workspace. The first release prioritizes fast document discovery and transparent answers.' },
  { index: 2, source: 'brand-voice.md', page: null, section: 'Principles', score: 0.87, text: 'Write with clarity and warmth. Show the source behind an answer so readers can move from insight back to evidence.' },
]

const STARTERS = [
  { label: 'Synthesize the product brief', hint: 'Key priorities, condensed with citations', prompt: 'What are the main priorities in the product brief?', icon: 'doc' },
  { label: 'Find the voice principles', hint: 'Tone rules grounded in your sources', prompt: 'What are the core brand voice principles?', icon: 'chat' },
  { label: 'Compare the research', hint: 'Recurring themes across documents', prompt: 'What themes show up in the customer research?', icon: 'bolt' },
]

function friendlyError(message) {
  const text = String(message || 'The retrieval service could not answer. Try again.')
  if (/11434|ollama|llm offline/i.test(text)) {
    return {
      title: 'Answer engine offline',
      body: 'Your documents are indexed, but the local answer engine (Ollama) is not running. Start it with `ollama serve`, pull the model with `ollama pull llama3.2:3b`, then ask again.',
    }
  }
  if (/no documents|not found in documents/i.test(text)) {
    return { title: 'Nothing relevant found', body: 'Try rephrasing, or upload the document that contains the answer first.' }
  }
  return { title: 'Could not answer', body: text.length > 220 ? `${text.slice(0, 220)}…` : text }
}

function Icon({ name, size = 22 }) {
  const paths = {
    search: <><circle cx="11" cy="11" r="6.5" /><path d="m16 16 5 5" /></>,
    plus: <><path d="M12 5v14M5 12h14" /></>,
    upload: <><path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5" /><path d="M5 15.5v2.8A1.7 1.7 0 0 0 6.7 20h10.6a1.7 1.7 0 0 0 1.7-1.7v-2.8" /></>,
    trash: <><path d="M4 7h16M10 11v5m4-5v5" /><path d="m6 7 1 13h10l1-13M9 7V4h6v3" /></>,
    send: <><path d="m21 3-8.8 18-2.7-7.5L2 10.8 21 3Z" /><path d="M9.5 13.5 21 3" /></>,
    file: <><path d="M6 3.5h7l5 5V20a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4.5a1 1 0 0 1 1-1Z" /><path d="M13 3.5V9h5M8 13h8M8 17h6" /></>,
    chevron: <path d="m7 9 5 5 5-5" />,
    spark: <><path d="m12 3 1.2 5.8L19 10l-5.8 1.2L12 17l-1.2-5.8L5 10l5.8-1.2L12 3Z" /><path d="m19 16 .5 2.5L22 19l-2.5.5L19 22l-.5-2.5L16 19l2.5-.5L19 16Z" /></>,
    book: <><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v16H6.5A2.5 2.5 0 0 0 4 21.5v-16Z" /><path d="M4 5.5v16M8 7h8M8 11h8" /></>,
    menu: <><path d="M4 7h16M4 12h16M4 17h16" /></>,
    alert: <><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5v5.5" /><circle cx="12" cy="16.4" r="0.4" /></>,
    check: <><path d="m4.5 12.5 5 5 10-11" /></>,
    doc: <><path d="M6 3.5h7l5 5V20a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4.5a1 1 0 0 1 1-1Z" /><path d="M13 3.5V9h5" /><path d="M9 13.5h6M9 17h4" /></>,
    chat: <><path d="M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v7a2.5 2.5 0 0 1-2.5 2.5H9l-5 4v-11Z" /><path d="M8.5 9.5h7M8.5 12.5h4.5" /></>,
    bolt: <><path d="M13 2 4.5 13.5H11L10 22l8.5-11.5H12L13 2Z" /></>,
    shield: <><path d="M12 3 5 5.8v5.4c0 4.4 2.9 7.6 7 9.8 4.1-2.2 7-5.4 7-9.8V5.8L12 3Z" /><path d="m9 11.5 2.2 2.2L15.5 9.5" /></>,
  }
  return <svg aria-hidden="true" className="icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">{paths[name] || paths.spark}</svg>
}

function formatBytes(bytes = 0) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function fileType(source = '') {
  const parts = source.split('.')
  return parts.length > 1 ? parts.pop().toLowerCase() : 'file'
}

function normalizeDocument(document) {
  return { ...document, source: document.source || document.name || 'Untitled document', type: document.type || fileType(document.source || document.name), chunk_count: document.chunk_count ?? document.chunks ?? 0 }
}

function demoResponse(question) {
  const lower = question.toLowerCase()
  let answer = 'The indexed materials emphasize a simple loop: retrieve the most relevant passages, ground the response in those passages, and make the evidence easy to inspect. The product brief frames this as a transparent way to move from a question to a confident next step.'
  if (lower.includes('voice') || lower.includes('principle')) answer = 'The brand voice is clear, warm, and evidence-led. It recommends short, direct language and asks readers to show the source behind an answer so anyone can move from an insight back to its evidence.'
  if (lower.includes('research') || lower.includes('theme')) answer = 'The customer research points to three recurring themes: people want faster discovery across a growing document set, more confidence in generated summaries, and an easy path back to the exact passage that supports a claim.'
  return { answer, citations: DEMO_CITATIONS, metrics: { retrieved: 6, retrieved_chunks: 6, used: 2, used_chunks: 2, top_score: 0.94, context_chars: 428, llm_called: true } }
}

function Logo() {
  return <div className="logo-wrap" aria-label="Lumen home"><span className="logo-badge"><Icon name="spark" size={24} /></span><span className="wordmark-block"><span className="wordmark">lumen</span><span className="wordmark-sub">Document intelligence</span></span></div>
}

function FileIcon({ type }) {
  return <span className={`file-icon file-${type}`}><Icon name="file" size={22} /><em>{type === 'file' ? 'FILE' : type.slice(0, 4).toUpperCase()}</em></span>
}

function CitationCard({ citation }) {
  const location = citation.page ? `Page ${citation.page}` : citation.section || 'Document'
  const score = citation.score == null ? '—' : `${Math.round(Number(citation.score) * 100)}%`
  return <details className="citation-card">
    <summary><span className="citation-index">[{citation.index}]</span><FileIcon type={fileType(citation.source)} /><span className="citation-source">{citation.source}</span><span className="citation-location">{location}</span><span className="citation-score">{score}</span><Icon name="chevron" size={20} /></summary>
    <div className="citation-excerpt"><span>GROUNDED EXCERPT</span><p>{citation.text || citation.excerpt || 'No excerpt supplied.'}</p></div>
  </details>
}

function LibrarySidebar({ documents, chunks, status, onUpload, onClear, isUploading, mobileOpen, setMobileOpen }) {
  const [dragging, setDragging] = useState(false)
  const handleFiles = (fileList) => {
    const files = Array.from(fileList || [])
    if (files.length) onUpload(files)
    setDragging(false)
  }
  return <aside className={`library-sidebar ${mobileOpen ? 'sidebar-open' : ''}`} aria-label="Document library">
    <div className="sidebar-top"><Logo /><button className="icon-button mobile-close" type="button" onClick={() => setMobileOpen(false)} aria-label="Close library"><span aria-hidden="true">×</span></button></div>
    <div className={`connection-badge ${status === 'connected' ? 'is-connected' : status === 'demo' ? 'is-demo' : 'is-checking'}`}><span className="connection-dot" /><span>{status === 'connected' ? 'API connected' : status === 'demo' ? 'Local demo mode' : 'Checking API'}</span><span className="badge-pulse">{status === 'connected' ? 'LIVE' : status === 'demo' ? 'DEMO' : 'WAIT'}</span></div>
    <div className="library-heading"><div><span className="eyebrow">Workspace</span><h1>Library</h1></div><span className="library-count">{documents.length}</span></div>
    <div className="library-stats"><div><strong>{documents.length}</strong><span>documents</span></div><div><strong>{chunks}</strong><span>chunks indexed</span></div></div>
    <label className={`dropzone ${dragging ? 'is-dragging' : ''} ${isUploading ? 'is-uploading' : ''}`} onDragEnter={(event) => { event.preventDefault(); setDragging(true) }} onDragOver={(event) => event.preventDefault()} onDragLeave={() => setDragging(false)} onDrop={(event) => { event.preventDefault(); handleFiles(event.dataTransfer.files) }}>
      <input type="file" multiple accept={ACCEPTED_FORMATS} onChange={(event) => handleFiles(event.target.files)} disabled={isUploading} />
      <span className="dropzone-icon"><Icon name={isUploading ? 'spark' : 'upload'} size={26} /></span><strong>{isUploading ? 'Indexing documents…' : 'Drop files to index'}</strong><span>{isUploading ? 'Building searchable chunks' : 'or browse from your device'}</span><small>{ACCEPTED_LABEL}</small>
    </label>
    <div className="documents-header"><span>Indexed documents</span><span className="document-rule" /></div>
    <div className="document-list">{documents.length ? documents.map((document) => <div className="document-row" key={`${document.source}-${document.updated_at || document.created_at || ''}`}><FileIcon type={fileType(document.source)} /><div className="document-info"><strong title={document.source}>{document.source}</strong><span>{document.chunk_count || 0} chunks <i>·</i> {formatBytes(document.size)}</span></div><span className="indexed-dot" title="Indexed" /></div>) : <div className="empty-library"><Icon name="book" size={26} /><p>Your library is ready for its first source.</p></div>}</div>
    <button className="clear-button" type="button" onClick={onClear} disabled={!documents.length}><Icon name="trash" size={20} /> Clear library</button>
    <div className="sidebar-footer"><span>LOCAL-FIRST INTELLIGENCE</span><span className="footer-line" /><span>v1.0</span></div>
  </aside>
}

function Welcome({ onPrompt, docCount }) {
  return <div className="welcome-state">
    <div className="welcome-hero">
      <div className="welcome-orbit"><span /><span /><span /><Icon name="spark" size={36} /></div>
      <div className="welcome-copy"><span className="eyebrow eyebrow-pill"><Icon name="shield" size={18} /> Grounded answers only</span><h2>Ask your library<br /><em>what it knows.</em></h2><p>Lumen retrieves the right passages, grounds every response in your sources, and keeps the trail visible.</p></div>
    </div>
    <div className="welcome-stats">
      <div><Icon name="doc" size={24} /><div><strong>{docCount}</strong><span>documents indexed</span></div></div>
      <div><Icon name="check" size={24} /><div><strong>Cited</strong><span>every answer links evidence</span></div></div>
      <div><Icon name="bolt" size={24} /><div><strong>Local-first</strong><span>embeddings stay on device</span></div></div>
    </div>
    <div className="starter-grid">{STARTERS.map((starter, index) => <button key={starter.label} type="button" onClick={() => onPrompt(starter.prompt)}><span className="starter-icon"><Icon name={starter.icon} size={26} /></span><span className="starter-num">0{index + 1}</span><strong>{starter.label}</strong><small>{starter.hint}</small><i aria-hidden="true">↗</i></button>)}</div>
  </div>
}

function Message({ message }) {
  const isUser = message.role === 'user'
  return <article className={`message ${isUser ? 'message-user' : 'message-assistant'}`}><div className="message-meta"><span className={`avatar ${isUser ? 'avatar-user' : 'avatar-assistant'}`}>{isUser ? 'YOU' : 'LU'}</span><strong>{isUser ? 'You' : 'Lumen'}</strong><span className="message-time">{message.time || 'now'}</span>{message.demo && <span className="demo-answer-label">DEMO ANSWER</span>}</div><div className="message-body">{message.content.split('\n').map((line, index) => <p key={`${line}-${index}`}>{line || '\u00a0'}</p>)}</div>{!isUser && message.citations?.length > 0 && <div className="evidence-block"><div className="evidence-heading"><span><span className="evidence-bar" />Grounded evidence</span><span>{message.citations.length} sources</span></div><div className="citation-list">{message.citations.map((citation, index) => <CitationCard citation={{ ...citation, index: citation.index || index + 1 }} key={`${citation.source}-${citation.page || citation.section || index}`} />)}</div>{message.metrics && <div className="metrics-row"><span><b>{message.metrics.used_chunks ?? message.metrics.used ?? 0}</b> chunks used</span><span><b>{message.metrics.top_score == null ? '—' : `${Math.round(Number(message.metrics.top_score) * 100)}%`}</b> top score</span><span><b>{message.metrics.context_chars ?? 0}</b> context chars</span></div>}</div>}</article>
}

function App() {
  const [status, setStatus] = useState('checking')
  const [documents, setDocuments] = useState([])
  const [chunks, setChunks] = useState(0)
  const [messages, setMessages] = useState([])
  const [question, setQuestion] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isUploading, setIsUploading] = useState(false)
  const [error, setError] = useState('')
  const [mobileOpen, setMobileOpen] = useState(false)

  const isDemo = status === 'demo'
  const hasMessages = messages.length > 0
  const history = useMemo(() => messages.map((message) => ({ role: message.role, content: message.content })), [messages])

  const applyLibrary = (payload) => {
    const nextDocuments = (payload?.documents || []).map(normalizeDocument)
    setDocuments(nextDocuments)
    setChunks(payload?.chunks ?? nextDocuments.reduce((sum, document) => sum + Number(document.chunk_count || 0), 0))
  }

  useEffect(() => {
    let mounted = true
    Promise.all([getHealth(), getLibrary()]).then(([health, library]) => {
      if (!mounted) return
      setStatus('connected')
      applyLibrary(library)
      setChunks(health.chunks ?? library.chunks ?? 0)
    }).catch(() => {
      if (!mounted) return
      setStatus('demo')
      applyLibrary({ documents: DEMO_DOCUMENTS, chunks: 71 })
    })
    return () => { mounted = false }
  }, [])

  async function handleUpload(files) {
    setError('')
    setIsUploading(true)
    try {
      if (isDemo) {
        await new Promise((resolve) => setTimeout(resolve, 650))
        const additions = files.map((file) => normalizeDocument({ source: file.name, type: fileType(file.name), size: file.size, chunk_count: Math.max(3, Math.ceil(file.size / 7200)), created_at: new Date().toISOString() }))
        const next = [...documents.filter((document) => !additions.some((item) => item.source === document.source)), ...additions]
        applyLibrary({ documents: next, chunks: next.reduce((sum, document) => sum + Number(document.chunk_count || 0), 0) })
      } else {
        await uploadDocuments(files)
        applyLibrary(await getLibrary())
      }
    } catch (uploadError) {
      setError(uploadError.message || 'Could not index those documents.')
    } finally {
      setIsUploading(false)
    }
  }

  async function handleClear() {
    if (!documents.length || !window.confirm('Clear every indexed document from this library?')) return
    setError('')
    try {
      if (isDemo) {
        setDocuments([])
        setChunks(0)
      } else applyLibrary(await clearLibrary())
    } catch (clearError) {
      setError(clearError.message || 'Could not clear the library.')
    }
  }

  async function ask(nextQuestion = question) {
    const trimmed = nextQuestion.trim()
    if (!trimmed || isLoading) return
    setQuestion('')
    setError('')
    const userMessage = { role: 'user', content: trimmed, time: 'now' }
    setMessages((current) => [...current, userMessage])
    setIsLoading(true)
    try {
      const response = isDemo ? await new Promise((resolve) => setTimeout(() => resolve(demoResponse(trimmed)), 750)) : await sendChat(trimmed, [...history, { role: 'user', content: trimmed }])
      setMessages((current) => [...current, { role: 'assistant', content: response.answer || 'I could not generate an answer.', citations: response.citations || response.sources || [], metrics: response.metrics || {}, demo: isDemo, time: 'now' }])
    } catch (chatError) {
      setError(chatError.message || 'The retrieval service could not answer. Try again.')
    } finally {
      setIsLoading(false)
    }
  }

  function handleComposerKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      ask()
    }
  }

  return <div className="app-shell">
    <LibrarySidebar documents={documents} chunks={chunks} status={status} onUpload={handleUpload} onClear={handleClear} isUploading={isUploading} mobileOpen={mobileOpen} setMobileOpen={setMobileOpen} />
    <main className="chat-workspace">
      <header className="topbar"><button className="icon-button mobile-menu" type="button" onClick={() => setMobileOpen(true)} aria-label="Open document library"><Icon name="menu" size={26} /></button><div className="breadcrumb"><span className="crumb-badge"><Icon name="spark" size={20} /></span><span>Workspace</span><b>/</b><strong>Ask Lumen</strong></div><div className="topbar-right"><span className={`retrieval-label ${isDemo ? 'is-warn' : ''}`}><span className="mini-pulse" />{isDemo ? 'Demo mode — API offline' : 'Retrieval ready'}</span><button type="button" className="new-chat" onClick={() => { setMessages([]); setError('') }}><Icon name="plus" size={20} /> New thread</button></div></header>
      <div className="chat-content">
        <section className={`thread ${hasMessages ? 'has-messages' : ''}`} aria-label="Chat thread">
          {!hasMessages && status !== 'checking' && <Welcome onPrompt={(prompt) => ask(prompt)} docCount={documents.length} />}
          {status === 'checking' && <div className="checking-state"><span className="loader-ring" /><p>Connecting to your retrieval index…</p></div>}
          {messages.map((message, index) => <Message message={message} key={`${message.role}-${index}`} />)}
          {isLoading && <div className="message message-assistant loading-message"><div className="message-meta"><span className="avatar avatar-assistant">LU</span><strong>Lumen</strong><span className="message-time">retrieving</span></div><div className="loading-bubble"><span /><span /><span /><em>Finding grounded passages…</em></div></div>}
        </section>
        <div className="composer-area"><div className="composer-context"><span><Icon name="book" size={20} /> Searching {documents.length} {documents.length === 1 ? 'document' : 'documents'}</span><span className="context-divider" /><span><Icon name="check" size={18} /> Answers cite your sources</span></div>{error && (() => { const friendly = friendlyError(error); return <div className="error-state" role="alert"><span className="error-icon"><Icon name="alert" size={26} /></span><div className="error-copy"><strong>{friendly.title}</strong><p>{friendly.body}</p></div><button type="button" onClick={() => setError('')} aria-label="Dismiss error">×</button></div> })()}<form className="composer" onSubmit={(event) => { event.preventDefault(); ask() }}><textarea value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={handleComposerKeyDown} placeholder="Ask anything about your library…" aria-label="Ask a question about your documents" rows="1" disabled={status === 'checking'} /><div className="composer-footer"><label className="attach-button" title="Upload documents"><input type="file" multiple accept={ACCEPTED_FORMATS} onChange={(event) => { if (event.target.files?.length) handleUpload(Array.from(event.target.files)) }} /><Icon name="plus" size={22} /><span>Source</span></label><span className="keyboard-hint"><kbd>shift</kbd> + <kbd>enter</kbd> for a new line</span><button className="send-button" type="submit" disabled={!question.trim() || isLoading || status === 'checking'} aria-label="Send question"><Icon name="send" size={24} /></button></div></form><p className="composer-note">Lumen can make mistakes. Verify important details against the cited passages.</p></div>
      </div>
    </main>
  </div>
}

export default App
