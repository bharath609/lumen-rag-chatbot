import { useEffect, useRef, useState } from 'react'
import { clearLibrary, getHealth, getLibrary, sendChat, uploadDocuments } from './api'
import AuthView from './AuthView'
import { supabase, supabaseConfigured } from './supabase'
import './styles.css'

const ACCEPTED_FORMATS = '.pdf,.txt,.md,.mdx,.rst,.log,.tex,.xml,.yaml,.yml,.ini,.toml,.cfg,.conf,.sql,.py,.js,.jsx,.ts,.tsx,.java,.c,.h,.cpp,.hpp,.cs,.go,.rs,.rb,.php,.swift,.kt,.kts,.sh,.bash,.ps1,.bat,.cmd,.css,.scss,.sass,.less,.svg,.docx,.pptx,.xlsx,.xlsm,.xls,.csv,.tsv,.html,.htm,.json,.jsonl'
const ACCEPTED_LABEL = 'PDF, DOCX, PPTX, XLS/XLSX, TXT/MD, CSV, HTML, JSON, code'

const DEMO_DOCUMENTS = [
  { source: '2025-product-brief.pdf', type: 'pdf', size: 2840000, chunk_count: 38, page_count: 12, created_at: '2025-02-14T10:00:00Z' },
  { source: 'brand-voice.md', type: 'md', size: 18400, chunk_count: 9, page_count: null, created_at: '2025-02-12T10:00:00Z' },
  { source: 'customer-research.csv', type: 'csv', size: 94200, chunk_count: 24, page_count: null, created_at: '2025-02-08T10:00:00Z' },
]

const DEMO_CITATIONS = [
  { index: 1, source: '2025-product-brief.pdf', page: 4, score: 0.94, text: 'Lumora brings retrieval, grounding, and citation into one focused workspace. The first release prioritizes fast document discovery and transparent answers.' },
  { index: 2, source: 'brand-voice.md', page: null, section: 'Principles', score: 0.87, text: 'Write with clarity and warmth. Show the source behind an answer so readers can move from insight back to evidence.' },
]

const STARTERS = [
  { label: 'Synthesize the product brief', hint: 'Key priorities, condensed with citations', prompt: 'What are the main priorities in the product brief?', icon: 'doc' },
  { label: 'Find the voice principles', hint: 'Tone rules grounded in your sources', prompt: 'What are the core brand voice principles?', icon: 'chat' },
  { label: 'Compare the research', hint: 'Recurring themes across documents', prompt: 'What themes show up in the customer research?', icon: 'bolt' },
]

function buildStarters(documents, isDemo, activeDocument) {
  if (isDemo) return STARTERS
  if (activeDocument) {
    return [
      { label: `Summarize ${activeDocument}`, hint: 'The document’s key points, with citations', prompt: `Summarize ${activeDocument} and cite the passages you used.`, icon: 'doc' },
      { label: 'Pull out the key facts', hint: 'Figures, dates and definitions in this document', prompt: `What are the most important facts, figures and definitions in ${activeDocument}?`, icon: 'bolt' },
      { label: 'What does this document cover?', hint: 'A quick map of this source', prompt: `What topics does ${activeDocument} cover?`, icon: 'chat' },
    ]
  }
  const first = documents[0]?.source
  return [
    { label: first ? `Summarize ${first}` : 'Summarize my documents', hint: 'The key points, with citations', prompt: first ? `Summarize ${first} and cite the passages you used.` : 'Summarize my documents and cite the passages you used.', icon: 'doc' },
    { label: 'Pull out the key facts', hint: 'Figures, dates and definitions', prompt: 'What are the most important facts, figures and definitions in my documents?', icon: 'bolt' },
    { label: 'What do these documents cover?', hint: 'A quick map of your library', prompt: 'What topics do my documents cover?', icon: 'chat' },
  ]
}

const nowLabel = () => new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
const EMPTY_MESSAGES = []

const THREADS_STORAGE_PREFIX = 'lumora.threads.v1.'
const MAX_SAVED_THREADS = 60
const MAX_MESSAGES_PER_THREAD = 120

function newThreadId() {
  return `thread_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

function makeThreadTitle(text) {
  const title = String(text || '').trim().replace(/\s+/g, ' ')
  return title.length > 90 ? `${title.slice(0, 87)}…` : title || 'Saved chat'
}

function formatThreadTime(value) {
  const date = new Date(Number(value))
  if (Number.isNaN(date.getTime())) return ''
  const now = new Date()
  if (date.toDateString() === now.toDateString()) return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

function cleanThread(value) {
  if (!value || typeof value !== 'object') return null
  const messages = (Array.isArray(value.messages) ? value.messages : [])
    .filter((message) => message && typeof message.content === 'string' && (message.role === 'user' || message.role === 'assistant'))
    .slice(-MAX_MESSAGES_PER_THREAD)
    .map((message) => ({
      role: message.role,
      content: message.content,
      time: typeof message.time === 'string' ? message.time : '',
      citations: Array.isArray(message.citations) ? message.citations : [],
      metrics: message.metrics && typeof message.metrics === 'object' ? message.metrics : {},
      demo: Boolean(message.demo),
    }))
  if (!messages.length) return null
  const createdAt = Number(value.createdAt) || Date.now()
  return {
    id: typeof value.id === 'string' && value.id ? value.id : newThreadId(),
    documentSource: typeof value.documentSource === 'string' && value.documentSource ? value.documentSource : null,
    title: makeThreadTitle(value.title || messages.find((message) => message.role === 'user')?.content || 'Saved chat'),
    createdAt,
    updatedAt: Number(value.updatedAt) || createdAt,
    messages,
  }
}

function readThreadStore(userId) {
  if (!userId || typeof window === 'undefined') return { threads: [], activeThreadId: null, activeDocument: null }
  try {
    const raw = window.localStorage.getItem(`${THREADS_STORAGE_PREFIX}${userId}`)
    if (!raw) return { threads: [], activeThreadId: null, activeDocument: null }
    const parsed = JSON.parse(raw)
    const saved = Array.isArray(parsed) ? parsed : parsed?.threads
    const threads = (Array.isArray(saved) ? saved : [])
      .map(cleanThread)
      .filter(Boolean)
      .sort((a, b) => b.updatedAt - a.updatedAt)
      .slice(0, MAX_SAVED_THREADS)
    const activeThread = threads.find((thread) => thread.id === parsed?.activeThreadId) || null
    return {
      threads,
      activeThreadId: activeThread?.id || null,
      activeDocument: activeThread ? activeThread.documentSource : (typeof parsed?.activeDocument === 'string' ? parsed.activeDocument : null),
    }
  } catch {
    return { threads: [], activeThreadId: null, activeDocument: null }
  }
}

function writeThreadStore(userId, threads, activeThreadId, activeDocument) {
  if (!userId || typeof window === 'undefined') return
  try {
    const trimmed = [...threads]
      .sort((a, b) => b.updatedAt - a.updatedAt)
      .slice(0, MAX_SAVED_THREADS)
      .map((thread) => ({ ...thread, messages: thread.messages.slice(-MAX_MESSAGES_PER_THREAD) }))
    window.localStorage.setItem(`${THREADS_STORAGE_PREFIX}${userId}`, JSON.stringify({
      version: 1,
      threads: trimmed,
      activeThreadId,
      activeDocument,
    }))
  } catch {
    // Saved chats are a convenience; a full or blocked storage should not break chat.
  }
}

function openCitation(anchor) {
  const el = document.getElementById(anchor)
  if (!el) return
  el.open = true
  el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
}

function inlineText(text, onCite, key) {
  return text.split(/(\*\*[^*]+\*\*|\[\d+\])/g).map((part, i) => {
    if (/^\*\*[^*]+\*\*$/.test(part)) return <strong key={`${key}-${i}`}>{part.slice(2, -2)}</strong>
    const match = part.match(/^\[(\d+)\]$/)
    if (match) return <button type="button" className="cite-chip" key={`${key}-${i}`} onClick={() => onCite(match[1])} aria-label={`Show source ${match[1]}`}>{match[1]}</button>
    return part
  })
}

function AnswerText({ text, onCite }) {
  const blocks = []
  let list = null
  text.split('\n').forEach((raw) => {
    const line = raw.trim()
    const item = line.match(/^(?:[-*\u2022]|\d+[.)])\s+(.*)$/)
    if (item) {
      if (!list) { list = []; blocks.push({ list }) }
      list.push(item[1])
      return
    }
    list = null
    if (line) blocks.push({ p: line })
  })
  return blocks.map((block, i) => block.list
    ? <ul key={i}>{block.list.map((li, j) => <li key={j}>{inlineText(li, onCite, `${i}-${j}`)}</li>)}</ul>
    : <p key={i}>{inlineText(block.p, onCite, i)}</p>)
}

function friendlyError(message) {
  const text = String(message || 'The retrieval service could not answer. Try again.')
  if (/gemini api.*(?:503|temporarily unavailable)|temporarily unavailable.*gemini/i.test(text)) {
    return {
      title: 'Gemini is temporarily busy',
      body: 'Google’s answer service is temporarily overloaded. Lumora retries automatically and can use a fallback model; wait a few seconds and try again.',
    }
  }
  if (/11434|ollama|llm offline/i.test(text)) {
    return {
      title: 'Answer engine offline',
      body: 'Your documents are indexed, but the local answer engine (Ollama) is not running. Start it with `ollama serve`, pull the model with `ollama pull llama3.2:3b`, then ask again.',
    }
  }
  if (/no documents|not found in documents/i.test(text)) {
    return { title: 'Nothing relevant found', body: 'Try rephrasing, or upload the document that contains the answer first.' }
  }
  if (/^Indexed \d+ of \d+ file/i.test(text)) {
    return { title: 'Some documents were not indexed', body: text }
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
  return { ...document, source: document.source || document.name || 'Untitled document', type: document.type || fileType(document.source || document.name), size: document.size ?? document.doc_bytes ?? 0, chunk_count: document.chunk_count ?? document.chunks ?? 0 }
}

function demoResponse(question) {
  const lower = question.toLowerCase()
  let answer = 'The indexed materials emphasize a simple loop: retrieve the most relevant passages, ground the response in those passages, and make the evidence easy to inspect. The product brief frames this as a transparent way to move from a question to a confident next step.'
  if (lower.includes('voice') || lower.includes('principle')) answer = 'The brand voice is clear, warm, and evidence-led. It recommends short, direct language and asks readers to show the source behind an answer so anyone can move from an insight back to its evidence.'
  if (lower.includes('research') || lower.includes('theme')) answer = 'The customer research points to three recurring themes: people want faster discovery across a growing document set, more confidence in generated summaries, and an easy path back to the exact passage that supports a claim.'
  return { answer, citations: DEMO_CITATIONS, metrics: { retrieved: 6, retrieved_chunks: 6, used: 2, used_chunks: 2, top_score: 0.94, context_chars: 428, llm_called: true } }
}

function Logo() {
  return <div className="logo-wrap" aria-label="Lumora home"><span className="logo-badge"><Icon name="spark" size={24} /></span><span className="wordmark-block"><span className="wordmark">lumora</span><span className="wordmark-sub">Document intelligence</span></span></div>
}

function FileIcon({ type }) {
  return <span className={`file-icon file-${type}`}><Icon name="file" size={22} /><em>{type === 'file' ? 'FILE' : type.slice(0, 4).toUpperCase()}</em></span>
}

function CitationCard({ citation, anchor }) {
  const location = citation.page ? `Page ${citation.page}` : citation.section || 'Document'
  const score = citation.score == null ? '—' : `${Math.round(Number(citation.score) * 100)}%`
  return <details className="citation-card" id={anchor}>
    <summary><span className="citation-index">[{citation.index}]</span><FileIcon type={fileType(citation.source)} /><span className="citation-source">{citation.source}</span><span className="citation-location">{location}</span><span className="citation-score">{score}</span><Icon name="chevron" size={20} /></summary>
    <div className="citation-excerpt"><span>GROUNDED EXCERPT</span><p>{citation.text || citation.excerpt || 'No excerpt supplied.'}</p></div>
  </details>
}

function LibrarySidebar({ documents, chunks, threads, activeDocument, activeThreadId, onSelectDocument, onSelectThread, onNewThread, onUpload, onClear, isUploading, mobileOpen, setMobileOpen }) {
  const [dragging, setDragging] = useState(false)
  const handleFiles = (fileList) => {
    const files = Array.from(fileList || [])
    if (files.length) onUpload(files)
    setDragging(false)
  }
  const threadsFor = (source) => threads
    .filter((thread) => (thread.documentSource || null) === source)
    .sort((a, b) => b.updatedAt - a.updatedAt)
  const libraryThreads = threadsFor(null)

  const threadList = (source, savedThreads) => {
    if (activeDocument !== source || !savedThreads.length) return null
    return <div className="doc-chats">
      <div className="doc-chats-head"><span>Saved chats</span><button type="button" onClick={onNewThread}>+ New</button></div>
      {activeThreadId === null && <div className="doc-chat is-active"><span className="doc-chat-title">New chat</span><span className="doc-chat-meta">Start typing below</span></div>}
      {savedThreads.map((thread) => <button type="button" className={`doc-chat ${thread.id === activeThreadId ? 'is-active' : ''}`} onClick={() => onSelectThread(thread.id)} key={thread.id}>
        <span className="doc-chat-title" title={thread.title}>{thread.title}</span>
        <span className="doc-chat-meta">{formatThreadTime(thread.updatedAt)} · {thread.messages.length} {thread.messages.length === 1 ? 'message' : 'messages'}</span>
      </button>)}
    </div>
  }

  return <aside className={`library-sidebar ${mobileOpen ? 'sidebar-open' : ''}`} aria-label="Document library">
    <div className="sidebar-top"><Logo /><button className="icon-button mobile-close" type="button" onClick={() => setMobileOpen(false)} aria-label="Close library"><span aria-hidden="true">×</span></button></div>
    <div className="library-heading"><div><span className="eyebrow">Workspace</span><h1>Library</h1></div><span className="library-count">{documents.length}</span></div>
    <div className="library-stats"><div><strong>{documents.length}</strong><span>documents</span></div><div><strong>{chunks}</strong><span>chunks indexed</span></div></div>
    <label className={`dropzone ${dragging ? 'is-dragging' : ''} ${isUploading ? 'is-uploading' : ''}`} onDragEnter={(event) => { event.preventDefault(); setDragging(true) }} onDragOver={(event) => event.preventDefault()} onDragLeave={() => setDragging(false)} onDrop={(event) => { event.preventDefault(); handleFiles(event.dataTransfer.files) }}>
      <input type="file" multiple accept={ACCEPTED_FORMATS} onChange={(event) => handleFiles(event.target.files)} disabled={isUploading} />
      <span className="dropzone-icon"><Icon name={isUploading ? 'spark' : 'upload'} size={26} /></span><strong>{isUploading ? 'Indexing documents…' : 'Drop files to index'}</strong><span>{isUploading ? 'Building searchable chunks' : 'or browse from your device'}</span><small>{ACCEPTED_LABEL}</small>
    </label>
    <div className="documents-header"><span>Chats by document</span><span className="document-rule" /></div>
    <div className="document-list">
      <div className={`document-entry ${activeDocument === null ? 'is-open' : ''}`}>
        <button type="button" className={`document-row all-docs-row ${activeDocument === null ? 'is-active' : ''}`} onClick={() => onSelectDocument(null)}>
          <span className="all-docs-icon"><Icon name="book" size={18} /></span>
          <div className="document-info"><strong>All documents</strong><span>{documents.length} {documents.length === 1 ? 'source' : 'sources'}{libraryThreads.length ? ` · ${libraryThreads.length} ${libraryThreads.length === 1 ? 'chat' : 'chats'}` : ''}</span></div>
          <Icon name="chevron" size={16} />
        </button>
        {threadList(null, libraryThreads)}
      </div>
      {documents.length ? documents.map((document) => {
        const docThreads = threadsFor(document.source)
        const selected = activeDocument === document.source
        return <div className={`document-entry ${selected ? 'is-open' : ''}`} key={`${document.source}-${document.updated_at || document.created_at || ''}`}>
          <button type="button" className={`document-row ${selected ? 'is-active' : ''}`} onClick={() => onSelectDocument(document.source)}>
            <FileIcon type={fileType(document.source)} />
            <div className="document-info"><strong title={document.source}>{document.source}</strong><span>{document.chunk_count || 0} chunks <i>·</i> {formatBytes(document.size)}{docThreads.length ? <> <i>·</i> {docThreads.length} {docThreads.length === 1 ? 'chat' : 'chats'}</> : null}</span></div>
            <Icon name="chevron" size={16} />
          </button>
          {threadList(document.source, docThreads)}
        </div>
      }) : <div className="empty-library"><Icon name="book" size={26} /><p>Your library is ready for its first source.</p></div>}
    </div>
    <button className="clear-button" type="button" onClick={onClear} disabled={!documents.length}><Icon name="trash" size={20} /> Clear library</button>
    <div className="sidebar-footer"><span>GROUNDED · CITED</span><span className="footer-line" /><span>v1.0</span></div>
  </aside>
}

function Welcome({ onPrompt, docCount, starters, activeDocument }) {
  return <div className="welcome-state">
    <div className="welcome-hero">
      <div className="welcome-orbit"><span /><span /><span /><Icon name="spark" size={36} /></div>
      <div className="welcome-copy"><span className="eyebrow eyebrow-pill"><Icon name="shield" size={18} /> Grounded answers only</span><h2>{activeDocument ? <>Ask this document<br /><em>what it knows.</em></> : <>Ask your library<br /><em>what it knows.</em></>}</h2><p>{activeDocument ? `This thread searches only ${activeDocument}. Your earlier chats about it stay in the sidebar.` : 'Lumora retrieves the right passages, grounds every response in your sources, and keeps the trail visible.'}</p></div>
    </div>
    <div className="welcome-stats">
      <div><Icon name="doc" size={24} /><div><strong>{docCount}</strong><span>{activeDocument ? 'document in this chat' : 'documents indexed'}</span></div></div>
      <div><Icon name="check" size={24} /><div><strong>Cited</strong><span>every answer links evidence</span></div></div>
      <div><Icon name="bolt" size={24} /><div><strong>Your index</strong><span>built only from your files</span></div></div>
    </div>
    <div className="starter-grid">{starters.map((starter, index) => <button key={starter.label} type="button" onClick={() => onPrompt(starter.prompt)}><span className="starter-icon"><Icon name={starter.icon} size={26} /></span><span className="starter-num">0{index + 1}</span><strong>{starter.label}</strong><small>{starter.hint}</small><i aria-hidden="true">↗</i></button>)}</div>
  </div>
}

function matchLevel(score) {
  const s = Number(score)
  if (score == null || !Number.isFinite(s)) return { label: 'Unscored', tone: 'none' }
  if (s >= 0.6) return { label: 'Strong match', tone: 'high' }
  if (s >= 0.4) return { label: 'Good match', tone: 'mid' }
  return { label: 'Partial match', tone: 'low' }
}

function EvidencePanel({ message, activeCite }) {
  useEffect(() => {
    if (activeCite) document.getElementById(`ep-${activeCite}`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [activeCite, message])
  const citations = message?.citations || []
  if (!citations.length) {
    return <aside className="evidence-panel" aria-label="Evidence">
      <div className="ep-head"><div><span className="eyebrow">Inspector</span><h2>Evidence</h2></div></div>
      <div className="ep-empty">
        <span className="ep-empty-icon"><Icon name="shield" size={26} /></span>
        <strong>Every answer shows its sources</strong>
        <p>Ask a question, then select a citation to read the exact passage behind it.</p>
        <ol className="ep-steps">
          <li><b>1</b><div><strong>Retrieve</strong><span>Find the passages closest to your question</span></div></li>
          <li><b>2</b><div><strong>Filter</strong><span>Drop weak matches, or say "not found"</span></div></li>
          <li><b>3</b><div><strong>Cite</strong><span>Write the answer and link each claim</span></div></li>
        </ol>
      </div>
    </aside>
  }
  const metrics = message.metrics || {}
  const level = matchLevel(metrics.top_score)
  return <aside className="evidence-panel" aria-label="Evidence">
    <div className="ep-head"><div><span className="eyebrow">Inspector</span><h2>Evidence</h2></div><span className={`match-pill tone-${level.tone}`}>{level.label}</span></div>
    <div className="ep-list">{citations.map((citation, index) => {
      const n = citation.index || index + 1
      const pct = citation.score == null ? null : Math.round(Number(citation.score) * 100)
      return <article className={`ep-card ${String(n) === String(activeCite) ? 'is-active' : ''}`} id={`ep-${n}`} key={`${citation.source}-${n}`}>
        <header><span className="citation-index">[{n}]</span><strong title={citation.source}>{citation.source}</strong></header>
        <div className="ep-meta"><span>{citation.page ? `Page ${citation.page}` : citation.section || 'Document'}</span>{pct != null && <span>{pct}% match</span>}</div>
        {pct != null && <div className="ep-meter" role="img" aria-label={`${pct}% match`}><span style={{ width: `${Math.max(4, Math.min(100, pct))}%` }} /></div>}
        <p>{citation.text || citation.excerpt || 'No excerpt supplied.'}</p>
      </article>
    })}</div>
    <div className="ep-foot"><span><b>{metrics.retrieved_chunks ?? metrics.retrieved ?? 0}</b> retrieved</span><span><b>{metrics.used_chunks ?? metrics.used ?? 0}</b> used</span><span><b>{metrics.context_chars ?? 0}</b> chars</span></div>
  </aside>
}

function Message({ message, id, focused, onFocus }) {
  const isUser = message.role === 'user'
  const level = matchLevel(message.metrics?.top_score)
  return <article className={`message ${isUser ? 'message-user' : 'message-assistant'} ${focused ? 'is-focused' : ''}`}><div className="message-meta"><span className={`avatar ${isUser ? 'avatar-user' : 'avatar-assistant'}`}>{isUser ? 'YOU' : 'LM'}</span><strong>{isUser ? 'You' : 'Lumora'}</strong><span className="message-time">{message.time || 'now'}</span>{message.demo && <span className="demo-answer-label">DEMO ANSWER</span>}</div><div className="message-body">{isUser ? message.content.split('\n').map((line, index) => <p key={`${line}-${index}`}>{line || '\u00a0'}</p>) : <AnswerText text={message.content} onCite={(n) => { onFocus?.(id, n); openCitation(`cite-${id}-${n}`) }} />}</div>{!isUser && message.citations?.length > 0 && <div className="answer-foot"><span className={`match-pill tone-${level.tone}`}>{level.label}</span><button type="button" className="inspect-btn" onClick={() => onFocus?.(id, null)}>Inspect {message.citations.length} {message.citations.length === 1 ? 'source' : 'sources'}<Icon name="chevron" size={16} /></button></div>}{!isUser && message.citations?.length > 0 && <div className="evidence-block"><div className="evidence-heading"><span><span className="evidence-bar" />Grounded evidence</span><span>{message.citations.length} sources</span></div><div className="citation-list">{message.citations.map((citation, index) => <CitationCard anchor={`cite-${id}-${citation.index || index + 1}`} citation={{ ...citation, index: citation.index || index + 1 }} key={`${citation.source}-${citation.page || citation.section || index}`} />)}</div>{message.metrics && <div className="metrics-row"><span><b>{message.metrics.used_chunks ?? message.metrics.used ?? 0}</b> chunks used</span><span><b>{message.metrics.top_score == null ? '—' : `${Math.round(Number(message.metrics.top_score) * 100)}%`}</b> top score</span><span><b>{message.metrics.context_chars ?? 0}</b> context chars</span></div>}</div>}</article>
}

function App() {
  const [session, setSession] = useState(null)
  const [authReady, setAuthReady] = useState(!supabaseConfigured)
  const [status, setStatus] = useState('checking')
  const [documents, setDocuments] = useState([])
  const [chunks, setChunks] = useState(0)
  const [threads, setThreads] = useState([])
  const [activeThreadId, setActiveThreadId] = useState(null)
  const [activeDocument, setActiveDocument] = useState(null)
  const [historyUserId, setHistoryUserId] = useState('')
  const [question, setQuestion] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isUploading, setIsUploading] = useState(false)
  const [error, setError] = useState('')
  const [mobileOpen, setMobileOpen] = useState(false)
  const endRef = useRef(null)
  const taRef = useRef(null)
  const [focus, setFocus] = useState({ index: null, cite: null })

  const isDemo = false
  const userId = session?.user?.id || ''
  const accessToken = session?.access_token || ''
  const activeThread = threads.find((thread) => thread.id === activeThreadId) || null
  const messages = activeThread?.messages || EMPTY_MESSAGES
  const hasMessages = messages.length > 0
  const evidenceMessage = focus.index != null ? messages[focus.index] : [...messages].reverse().find((item) => item.role === 'assistant' && item.citations?.length)

  const applyLibrary = (payload) => {
    const nextDocuments = (payload?.documents || []).map(normalizeDocument)
    setDocuments(nextDocuments)
    setChunks(payload?.chunks ?? nextDocuments.reduce((sum, document) => sum + Number(document.chunk_count || 0), 0))
  }

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [messages, isLoading])
  useEffect(() => { if (!question && taRef.current) taRef.current.style.height = 'auto' }, [question])

  useEffect(() => {
    if (!supabase) return undefined
    let mounted = true
    supabase.auth.getSession().then(({ data }) => {
      if (mounted) {
        setSession(data.session)
        setAuthReady(true)
      }
    })
    const { data: listener } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      if (mounted) setSession(nextSession)
    })
    return () => {
      mounted = false
      listener.subscription.unsubscribe()
    }
  }, [])

  useEffect(() => {
    const id = session?.user?.id || ''
    if (!id) {
      setThreads([])
      setActiveThreadId(null)
      setActiveDocument(null)
      setHistoryUserId('')
      return
    }
    const saved = readThreadStore(id)
    setThreads(saved.threads)
    setActiveThreadId(saved.activeThreadId)
    setActiveDocument(saved.activeDocument)
    setHistoryUserId(id)
  }, [session?.user?.id])

  useEffect(() => {
    if (!userId || historyUserId !== userId) return
    writeThreadStore(userId, threads, activeThreadId, activeDocument)
  }, [threads, activeThreadId, activeDocument, userId, historyUserId])

  useEffect(() => {
    if (!session) return undefined
    let mounted = true
    setStatus('checking')
    Promise.all([getHealth(), getLibrary(accessToken)]).then(([health, library]) => {
      if (!mounted) return
      setStatus('connected')
      applyLibrary(library)
       setChunks(library.chunks ?? health.chunks ?? 0)
    }).catch((loadError) => {
      if (!mounted) return
      setStatus('error')
      setError(loadError.message || 'Could not connect to your private library.')
    })
    return () => { mounted = false }
  }, [session, accessToken])

  function selectDocument(source) {
    setError('')
    setFocus({ index: null, cite: null })
    setActiveDocument(source)
    const recent = threads
      .filter((thread) => (thread.documentSource || null) === source)
      .sort((a, b) => b.updatedAt - a.updatedAt)[0]
    setActiveThreadId(recent?.id || null)
    setMobileOpen(false)
  }

  function openThread(threadId) {
    const thread = threads.find((item) => item.id === threadId)
    if (!thread) return
    setActiveThreadId(thread.id)
    setActiveDocument(thread.documentSource || null)
    setError('')
    setFocus({ index: null, cite: null })
    setMobileOpen(false)
  }

  function startNewThread() {
    setActiveThreadId(null)
    setError('')
    setFocus({ index: null, cite: null })
    setMobileOpen(false)
  }

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
        const seen = new Set()
        const failures = []
        let indexed = 0
        for (const file of files) {
          if (seen.has(file.name)) {
            failures.push({ source: file.name, error: 'Duplicate filename in this upload; rename it and try again.' })
            continue
          }
          seen.add(file.name)
          try {
            const result = await uploadDocuments([file], accessToken)
            indexed += Number(result?.indexed ?? 0)
            if (result?.errors?.length) failures.push(...result.errors)
          } catch (fileError) {
            failures.push({ source: file.name, error: fileError.message || 'Upload failed.' })
          }
          try { applyLibrary(await getLibrary(accessToken)) } catch { /* keep indexing the rest */ }
        }
        if (failures.length) {
          const detail = failures.map((item) => `${item.source}: ${item.error}`).join(' | ')
          setError(`Indexed ${indexed} of ${files.length} file(s). ${detail}`)
        }
      }
    } catch (uploadError) {
      setError(uploadError.message || 'Could not index those documents.')
    } finally {
      setIsUploading(false)
    }
  }

  async function handleClear() {
    if (!documents.length || !window.confirm('Clear every indexed document and its saved chats?')) return
    setError('')
    try {
      if (isDemo) {
        setDocuments([])
        setChunks(0)
      } else applyLibrary(await clearLibrary(accessToken))
      setThreads([])
      setActiveThreadId(null)
      setActiveDocument(null)
    } catch (clearError) {
      setError(clearError.message || 'Could not clear the library.')
    }
  }

  async function ask(nextQuestion = question) {
    const trimmed = nextQuestion.trim()
    if (!trimmed || isLoading) return
    setQuestion('')
    setError('')
    const now = Date.now()
    const userMessage = { role: 'user', content: trimmed, time: nowLabel() }
    const existing = activeThread
    const baseMessages = existing?.messages || EMPTY_MESSAGES
    const threadDocument = existing ? existing.documentSource : (activeDocument || null)
    const historyPayload = [...baseMessages, userMessage].map((message) => ({ role: message.role, content: message.content }))
    let threadId = existing?.id || ''

    if (existing) {
      setThreads((current) => current.map((thread) => thread.id === existing.id ? { ...thread, messages: [...thread.messages, userMessage], updatedAt: now } : thread))
    } else {
      threadId = newThreadId()
      setThreads((current) => [{
        id: threadId,
        documentSource: threadDocument,
        title: makeThreadTitle(trimmed),
        createdAt: now,
        updatedAt: now,
        messages: [userMessage],
      }, ...current])
      setActiveThreadId(threadId)
    }

    setIsLoading(true)
    try {
      const response = await sendChat(trimmed, historyPayload, threadDocument ? [threadDocument] : null, accessToken)
      const assistantMessage = { role: 'assistant', content: response.answer || 'I could not generate an answer.', citations: response.citations || response.sources || [], metrics: response.metrics || {}, demo: isDemo, time: nowLabel() }
      setThreads((current) => current.map((thread) => thread.id === threadId ? { ...thread, messages: [...thread.messages, assistantMessage], updatedAt: Date.now() } : thread))
      setFocus({ index: null, cite: null })
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

  if (!authReady) return <div className="checking-state"><span className="loader-ring" /><p>Checking your session…</p></div>
  if (!supabaseConfigured) return <AuthView setupError="Authentication is not configured. Add the Supabase frontend variables before using Lumora." />
  if (!session) return <AuthView />
  if (historyUserId !== userId) return <div className="checking-state"><span className="loader-ring" /><p>Loading your saved chats…</p></div>

  return <div className="app-shell">
    <LibrarySidebar documents={documents} chunks={chunks} threads={threads} activeDocument={activeDocument} activeThreadId={activeThreadId} onSelectDocument={selectDocument} onSelectThread={openThread} onNewThread={startNewThread} onUpload={handleUpload} onClear={handleClear} isUploading={isUploading} mobileOpen={mobileOpen} setMobileOpen={setMobileOpen} />
    <main className="chat-workspace">
      <header className="topbar"><button className="icon-button mobile-menu" type="button" onClick={() => setMobileOpen(true)} aria-label="Open document library"><Icon name="menu" size={26} /></button><div className="breadcrumb"><span className="crumb-badge"><Icon name="spark" size={20} /></span><span>Workspace</span><b>/</b><strong title={activeDocument || 'All documents'}>{activeDocument || 'All documents'}</strong></div><div className="topbar-right"><span className={`retrieval-label ${isDemo ? 'is-warn' : ''}`}><span className="mini-pulse" />{isDemo ? 'Demo mode — API offline' : 'Private workspace'}</span><span className="account-email" title={session.user?.email}>{session.user?.email}</span><button type="button" className="new-chat" onClick={startNewThread}><Icon name="plus" size={20} /> New thread</button><button type="button" className="signout-button" onClick={() => supabase.auth.signOut()}>Sign out</button></div></header>
      <div className="chat-content">
        <section className={`thread ${hasMessages ? 'has-messages' : ''}`} role="log" aria-label="Chat thread">
          {!hasMessages && status !== 'checking' && <Welcome onPrompt={(prompt) => ask(prompt)} docCount={activeDocument ? 1 : documents.length} starters={buildStarters(documents, isDemo, activeDocument)} activeDocument={activeDocument} />}
          {status === 'checking' && <div className="checking-state"><span className="loader-ring" /><p>Connecting to your retrieval index…</p></div>}
          {messages.map((message, index) => <Message message={message} id={index} focused={message === evidenceMessage} onFocus={(i, c) => setFocus({ index: i, cite: c })} key={`${activeThreadId || 'draft'}-${message.role}-${index}`} />)}
          {isLoading && <div className="message message-assistant loading-message"><div className="message-meta"><span className="avatar avatar-assistant">LM</span><strong>Lumora</strong><span className="message-time">retrieving</span></div><div className="loading-bubble"><span /><span /><span /><em>Finding grounded passages…</em></div></div>}
          <div ref={endRef} className="thread-end" />
        </section>
        <div className="composer-area"><div className="composer-context"><span title={activeDocument || 'All documents'}><Icon name="book" size={20} /> {activeDocument ? `Searching ${activeDocument}` : `Searching ${documents.length} ${documents.length === 1 ? 'document' : 'documents'}`}</span><span className="context-divider" /><span><Icon name="check" size={18} /> Answers cite your sources</span></div>{error && (() => { const friendly = friendlyError(error); return <div className="error-state" role="alert"><span className="error-icon"><Icon name="alert" size={26} /></span><div className="error-copy"><strong>{friendly.title}</strong><p>{friendly.body}</p></div><button type="button" onClick={() => setError('')} aria-label="Dismiss error">×</button></div> })()}<form className="composer" onSubmit={(event) => { event.preventDefault(); ask() }}><textarea ref={taRef} value={question} onChange={(event) => { setQuestion(event.target.value); event.target.style.height = 'auto'; event.target.style.height = `${Math.min(event.target.scrollHeight, 168)}px` }} onKeyDown={handleComposerKeyDown} placeholder={activeDocument ? `Ask about ${activeDocument}…` : 'Ask anything about your library…'} aria-label="Ask a question about your documents" rows="1" disabled={status === 'checking'} /><div className="composer-footer"><label className="attach-button" title="Upload documents"><input type="file" multiple accept={ACCEPTED_FORMATS} onChange={(event) => { if (event.target.files?.length) handleUpload(Array.from(event.target.files)) }} /><Icon name="plus" size={22} /><span>Source</span></label><span className="keyboard-hint"><kbd>shift</kbd> + <kbd>enter</kbd> for a new line</span><button className="send-button" type="submit" disabled={!question.trim() || isLoading || status === 'checking'} aria-label="Send question"><Icon name="send" size={24} /></button></div></form><p className="composer-note">Lumora can make mistakes. Verify important details against the cited passages.</p></div>
      </div>
    </main>
    <EvidencePanel message={evidenceMessage} activeCite={focus.cite} />
  </div>
}

export default App
