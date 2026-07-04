"use client";

export default function ConfirmDeleteModal({
  title,
  message,
  deleteLabel = "Delete",
  archiveLabel = "Archive",
  onCancel,
  onDelete,
  onArchive,
  busy = false,
  error = "",
}: {
  title: string;
  message: string;
  deleteLabel?: string;
  archiveLabel?: string;
  onCancel: () => void;
  onDelete: () => void;
  onArchive?: () => void;
  busy?: boolean;
  error?: string;
}) {
  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>{title}</h2>
          <button className="modal-close" onClick={onCancel} aria-label="Close">
            ×
          </button>
        </div>
        <div className="modal-body">
          <p className="page-subtitle" style={{ margin: 0 }}>
            {message}
          </p>
          {error && (
            <div className="alert alert-error" style={{ marginTop: "0.75rem" }}>
              {error}
            </div>
          )}
        </div>
        <div className="modal-footer">
          <button className="btn btn-secondary" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          {onArchive && (
            <button className="btn btn-secondary" onClick={onArchive} disabled={busy}>
              {archiveLabel}
            </button>
          )}
          <button className="btn btn-danger" onClick={onDelete} disabled={busy}>
            {busy ? "Deleting…" : deleteLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
