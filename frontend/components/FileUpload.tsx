"use client";

import { useRef, useState } from "react";

type Status = "idle" | "uploading" | "done" | "error";

export default function FileUpload({
  accept,
  label,
  hint,
  onUpload,
  disabled,
}: {
  accept: string;
  label: string;
  hint?: string;
  onUpload: (file: File) => Promise<void>;
  disabled?: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [fileName, setFileName] = useState("");
  const [error, setError] = useState("");

  async function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setFileName(file.name);
    setStatus("uploading");
    setError("");
    try {
      await onUpload(file);
      setStatus("done");
    } catch (err) {
      setStatus("error");
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  return (
    <div className="file-upload">
      <button
        type="button"
        className="file-upload-trigger"
        onClick={() => inputRef.current?.click()}
        disabled={disabled || status === "uploading"}
      >
        <span className="file-upload-icon">{status === "uploading" ? "⟳" : status === "done" ? "✓" : "⇧"}</span>
        <span>
          <strong>{label}</strong>
          {hint && <div className="file-upload-hint">{hint}</div>}
        </span>
      </button>
      {fileName && <div className="file-upload-name">{fileName}</div>}
      {status === "uploading" && <div className="file-upload-status">Uploading &amp; processing…</div>}
      {status === "error" && <div className="file-upload-status file-upload-status-error">{error}</div>}
      <input ref={inputRef} type="file" accept={accept} onChange={handleChange} hidden disabled={disabled} />
    </div>
  );
}
