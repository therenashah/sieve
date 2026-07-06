"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError, login } from "@/lib/api";
import { setToken } from "@/lib/auth";
import SieveLogo from "@/components/SieveLogo";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const { token } = await login(email.trim(), password);
      setToken(token);
      router.push("/jobs");
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 401
          ? "Invalid email or password."
          : "Couldn't reach the server. Is the API running?"
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="login-shell">
      <section className="login-hero">
        <div className="login-hero-content">
          <div className="brand-mark">
            <span className="brand-mark-glyph">
              <SieveLogo size={20} />
            </span>
            <span>sieve</span>
          </div>
          <h1>Screen candidates with evidence, not guesswork.</h1>
          <p>
            AI-assisted resume screening and interview agent built for recruiter teams that need
            explainable, consistent shortlists at scale.
          </p>
          <ul className="login-hero-points">
            <li>Mandatory conditions are gated before any score is shown</li>
            <li>One rubric per job, applied consistently to every candidate</li>
            <li>Full audit trail from job description to offer</li>
          </ul>
        </div>
      </section>
      <section className="login-panel">
        <form className="login-card" onSubmit={handleSubmit}>
          <h2>Recruiter sign in</h2>
          <p className="login-card-subtitle">Sign in to manage job postings and candidates.</p>
          <label className="field">
            <span>Work email</span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@seclore.com"
              required
              autoFocus
            />
          </label>
          <label className="field">
            <span>Password</span>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </label>
          {error && <div className="alert alert-error">{error}</div>}
          <button className="btn btn-primary btn-block" type="submit" disabled={loading}>
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </section>
    </main>
  );
}
