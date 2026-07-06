"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { search } from "@/lib/api";
import type { SearchResult } from "@/lib/api";
import { clearToken } from "@/lib/auth";
import SieveLogo from "./SieveLogo";

export default function Navbar({ title }: { title?: string }) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult | null>(null);
  const [open, setOpen] = useState(false);

  function handleLogout() {
    clearToken();
    router.replace("/");
  }

  async function handleChange(value: string) {
    setQuery(value);
    if (!value.trim()) {
      setResults(null);
      setOpen(false);
      return;
    }
    try {
      const res = await search(value.trim());
      setResults(res);
      setOpen(true);
    } catch {
      // Search is a convenience — fail silently rather than showing an error banner.
    }
  }

  function goToJob(id: number) {
    setOpen(false);
    setQuery("");
    router.push(`/jobs/${id}`);
  }

  function goToCandidate(jobId: number, id: number) {
    setOpen(false);
    setQuery("");
    router.push(`/jobs/${jobId}/candidates/${id}`);
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (results?.jobs.length) goToJob(results.jobs[0].id);
    else if (results?.candidates.length) goToCandidate(results.candidates[0].job_id, results.candidates[0].id);
  }

  const hasResults = !!results && (results.jobs.length > 0 || results.candidates.length > 0);

  return (
    <header className="navbar">
      <div className="navbar-inner">
        <div className="navbar-brand" onClick={() => router.push("/jobs")}>
          <span className="navbar-mark">
            <SieveLogo size={16} />
          </span>
          <span className="navbar-word">sieve</span>
        </div>
        {title && <div className="navbar-title">{title}</div>}

        <form className="navbar-search" onSubmit={handleSubmit}>
          <span className="navbar-search-icon">🔍</span>
          <input
            type="text"
            value={query}
            onChange={(e) => handleChange(e.target.value)}
            onFocus={() => query.trim() && setOpen(true)}
            onBlur={() => setTimeout(() => setOpen(false), 150)}
            placeholder="Search for a candidate or a posting"
          />
          {open && query.trim() && (
            <div className="navbar-search-results">
              {!results && <div className="navbar-search-empty">Searching…</div>}
              {results && !hasResults && <div className="navbar-search-empty">No matches</div>}
              {results?.jobs.map((j) => (
                <button type="button" key={`job-${j.id}`} onMouseDown={() => goToJob(j.id)}>
                  <span className="badge badge-neutral">Job</span> {j.title}
                </button>
              ))}
              {results?.candidates.map((c) => (
                <button type="button" key={`cand-${c.id}`} onMouseDown={() => goToCandidate(c.job_id, c.id)}>
                  <span className="badge badge-neutral">Candidate</span> {c.name}
                  {c.external_id ? ` (${c.external_id})` : ""}
                </button>
              ))}
            </div>
          )}
        </form>

        <button className="btn btn-ghost" onClick={handleLogout}>
          Log out
        </button>
      </div>
    </header>
  );
}
