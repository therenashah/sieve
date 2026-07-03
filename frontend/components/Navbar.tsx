"use client";

import { useRouter } from "next/navigation";

import { clearToken } from "@/lib/auth";

export default function Navbar({ title }: { title?: string }) {
  const router = useRouter();

  function handleLogout() {
    clearToken();
    router.replace("/");
  }

  return (
    <header className="navbar">
      <div className="navbar-inner">
        <div className="navbar-brand" onClick={() => router.push("/jobs")}>
          <span className="navbar-mark">S</span>
          <span className="navbar-word">sieve</span>
        </div>
        {title && <div className="navbar-title">{title}</div>}
        <button className="btn btn-ghost" onClick={handleLogout}>
          Log out
        </button>
      </div>
    </header>
  );
}
