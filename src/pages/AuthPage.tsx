import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { useAuth } from "../auth/useAuth";
import { Brand } from "../components/Brand";

function getErrorMessage(error: unknown) {
  if (error instanceof ApiError && typeof error.data === "object" && error.data !== null) {
    const data = error.data as Record<string, unknown>;
    if (typeof data.detail === "string") return data.detail;
    const messages = Object.values(data).flatMap((value) =>
      Array.isArray(value) ? value.map(String) : [],
    );
    if (messages.length) return messages.join(" ");
  }
  return error instanceof Error ? error.message : "We couldn't complete your request. Please try again.";
}

export function AuthPage({ mode }: { mode: "login" | "register" }) {
  const { user, loading, signIn, signUp } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const isRegister = mode === "register";

  if (!loading && user) return <Navigate to="/app" replace />;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      setError("Enter a valid email address.");
      return;
    }
    if (password.length < 8) {
      setError("Your password must be at least 8 characters.");
      return;
    }
    if (isRegister && password !== confirmation) {
      setError("Your passwords do not match.");
      return;
    }
    setSubmitting(true);
    try {
      if (isRegister) await signUp(email.trim(), password);
      else await signIn(email.trim(), password);
      navigate("/app", { replace: true });
    } catch (submitError) {
      setError(getErrorMessage(submitError));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-page">
      <header className="auth-header"><Brand /><Link className="text-link" to="/">Back to home <span aria-hidden="true">↗</span></Link></header>
      <div className="auth-layout">
        <section className="auth-aside">
          <span className="eyebrow"><span className="eyebrow-dot" /> YOUR NEXT IDEA STARTS HERE</span>
          <h1>{isRegister ? <>Give your<br /><em>ideas a home.</em></> : <>Welcome<br /><em>back.</em></>}</h1>
          <p>{isRegister ? "Create a space for the problems you care about and the engineering work that follows." : "Pick up where your curiosity left off. Your projects are waiting."}</p>
          <div className="auth-aside-note"><span className="note-line" /> Clear thinking. Better building.</div>
        </section>
        <section className="auth-card">
          <span className="eyebrow">{isRegister ? "CREATE AN ACCOUNT" : "YOUR WORKSPACE AWAITS"}</span>
          <h2>{isRegister ? "Get started" : "Sign in"}</h2>
          <p className="auth-card-copy">{isRegister ? "One account, a fresh space for every idea." : "Enter your details to continue to ProjectForge."}</p>
          <form className="auth-form" onSubmit={handleSubmit} noValidate>
            <label htmlFor="email">Email address</label>
            <input id="email" type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com" />
            <div className="label-row"><label htmlFor="password">Password</label>{!isRegister && <span className="field-hint">At least 8 characters</span>}</div>
            <input id="password" type="password" autoComplete={isRegister ? "new-password" : "current-password"} minLength={8} required value={password} onChange={(event) => setPassword(event.target.value)} placeholder="••••••••••" />
            {isRegister && <>
              <label htmlFor="password-confirmation">Confirm password</label>
              <input id="password-confirmation" type="password" autoComplete="new-password" minLength={8} required value={confirmation} onChange={(event) => setConfirmation(event.target.value)} placeholder="Enter your password again" />
            </>}
            {error && <p className="form-error" role="alert">{error}</p>}
            <button className="button button-primary auth-submit" type="submit" disabled={submitting || loading}>
              {submitting ? "Please wait..." : isRegister ? "Create account" : "Sign in"} <span aria-hidden="true">↗</span>
            </button>
          </form>
          <p className="auth-switch">
            {isRegister ? "Already have an account?" : "New to ProjectForge?"}{" "}
            <Link to={isRegister ? "/login" : "/register"}>{isRegister ? "Sign in" : "Create an account"}</Link>
          </p>
        </section>
      </div>
      <footer className="auth-footer">Your work belongs to you. Every workspace is private to your account.</footer>
    </main>
  );
}
