import { useEffect, useState } from 'react'
import { appUrl, supabase } from './supabase'
import './styles.css'

function GoogleMark() {
  return <svg aria-hidden="true" width="18" height="18" viewBox="0 0 48 48">
    <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.8 2.4 30.3 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.9 6.1C12.4 13.3 17.7 9.5 24 9.5z" />
    <path fill="#4285F4" d="M46.1 24.6c0-1.6-.1-3.1-.4-4.6H24v9.1h12.4c-.5 2.9-2.2 5.3-4.6 6.9l7.6 5.9c4.4-4.1 6.7-10.1 6.7-17.3z" />
    <path fill="#FBBC05" d="M10.5 28.7c-.5-1.5-.8-3.1-.8-4.7s.3-3.2.8-4.7l-7.9-6.1C1 16.6 0 20.2 0 24s1 7.4 2.6 10.8l7.9-6.1z" />
    <path fill="#34A853" d="M24 48c6.3 0 11.6-2.1 15.4-5.6l-7.6-5.9c-2.1 1.4-4.8 2.3-7.8 2.3-6.3 0-11.6-3.8-13.5-9.1l-7.9 6.1C6.5 42.6 14.6 48 24 48z" />
  </svg>
}

export default function AuthView({ onSignedIn, setupError }) {
  const [mode, setMode] = useState('signin')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState(setupError || '')

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const oauthError = params.get('error_description') || params.get('error')
    if (oauthError) setError(decodeURIComponent(oauthError.replace(/\+/g, ' ')))
  }, [])

  async function signInWithGoogle() {
    if (!supabase || busy) return
    setBusy(true)
    setError('')
    setMessage('')
    try {
      const { error: oauthError } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: {
          redirectTo: appUrl,
          queryParams: { prompt: 'select_account' },
        },
      })
      if (oauthError) throw oauthError
      // A successful call redirects the browser to Google, so busy stays true.
    } catch (authError) {
      const detail = authError.message || ''
      setError(/provider is not enabled|unsupported provider/i.test(detail)
        ? 'Google sign-in is not enabled for this project yet. Enable the Google provider in Supabase → Authentication → Providers.'
        : detail || 'Could not start Google sign-in. Please try again.')
      setBusy(false)
    }
  }

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
        else setMessage('Account created. Open the confirmation link on this same device and browser, then sign in. Or use “Continue with Google” to skip email confirmation.')
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
      {mode !== 'forgot' && <>
        <button className="auth-google" type="button" onClick={signInWithGoogle} disabled={busy || !supabase}><GoogleMark /> Continue with Google</button>
        <div className="auth-divider"><span>or use email</span></div>
      </>}
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
