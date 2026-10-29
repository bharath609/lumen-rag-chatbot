import { useState } from 'react'
import { appUrl, supabase } from './supabase'
import './styles.css'

export default function AuthView({ onSignedIn, setupError }) {
  const [mode, setMode] = useState('signin')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState(setupError || '')

  async function submit(event) {
    event.preventDefault()
    if (!supabase || busy) return
    setBusy(true)
    setError('')
    setMessage('')
    try {
      if (mode === 'forgot') {
        const { error: resetError } = await supabase.auth.resetPasswordForEmail(email, { redirectTo: appUrl })
        if (resetError) throw resetError
        setMessage('If an account exists for that email, a password reset link is on its way.')
      } else if (mode === 'signup') {
        const { data, error: signupError } = await supabase.auth.signUp({ email, password, options: { emailRedirectTo: appUrl } })
        if (signupError) throw signupError
        if (data.session) onSignedIn?.(data.session)
        else setMessage('Check your email to confirm your account, then return here to sign in.')
      } else {
        const { data, error: signinError } = await supabase.auth.signInWithPassword({ email, password })
        if (signinError) throw signinError
        if (data.session) onSignedIn?.(data.session)
      }
    } catch (authError) {
      setError(authError.message || 'Authentication failed. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  const title = mode === 'signup' ? 'Create your private workspace' : mode === 'forgot' ? 'Reset your password' : 'Welcome back to Lumora'
  const submitLabel = mode === 'signup' ? 'Create account' : mode === 'forgot' ? 'Send reset link' : 'Sign in'

  return <main className="auth-shell">
    <section className="auth-card">
      <div className="auth-mark">✦</div>
      <span className="eyebrow">Private document intelligence</span>
      <h1>{title}</h1>
      <p className="auth-subtitle">Your documents stay in your account and are never mixed with another user’s library.</p>
      <form onSubmit={submit} className="auth-form">
        <label>Email<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required autoComplete="email" /></label>
        {mode !== 'forgot' && <label>Password<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} required minLength={6} autoComplete={mode === 'signup' ? 'new-password' : 'current-password'} /></label>}
        {error && <p className="auth-error" role="alert">{error}</p>}
        {message && <p className="auth-message" role="status">{message}</p>}
        <button className="auth-submit" type="submit" disabled={busy || !supabase}>{busy ? 'Please wait…' : submitLabel}</button>
      </form>
      <div className="auth-links">
        {mode === 'signin' && <button type="button" onClick={() => { setMode('forgot'); setError(''); setMessage('') }}>Forgot password?</button>}
        {mode !== 'signin' && <button type="button" onClick={() => { setMode('signin'); setError(''); setMessage('') }}>Back to sign in</button>}
        {mode === 'signin' && <button type="button" onClick={() => { setMode('signup'); setError(''); setMessage('') }}>Create an account</button>}
      </div>
    </section>
  </main>
}
