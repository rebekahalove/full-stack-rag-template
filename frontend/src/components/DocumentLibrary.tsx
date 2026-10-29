import type { DocumentRecord } from "../api/types";

interface DocumentLibraryProps {
  documents: DocumentRecord[];
  selectedId: string | null;
  loading: boolean;
  error: string | null;
  deletingId: string | null;
  onSelect: (document: DocumentRecord) => void;
  onDelete: (document: DocumentRecord) => void;
  onRetry: () => void;
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function DocumentLibrary({
  documents,
  selectedId,
  loading,
  error,
  deletingId,
  onSelect,
  onDelete,
  onRetry,
}: DocumentLibraryProps) {
  return (
    <section className="panel library-panel" aria-labelledby="library-title">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Your sources</p>
          <h2 id="library-title">Document library</h2>
        </div>
        <span className="count-badge" aria-label={`${documents.length} documents`}>{documents.length}</span>
      </div>

      {loading && <p className="empty-state" role="status">Loading documents…</p>}
      {error && (
        <div className="message error-message" role="alert">
          <p>{error}</p>
          <button className="text-button" type="button" onClick={onRetry}>Try again</button>
        </div>
      )}
      {!loading && !error && documents.length === 0 && (
        <p className="empty-state">Your uploaded documents will appear here.</p>
      )}
      <ul className="document-list">
        {documents.map((document) => {
          const isSelected = document.id === selectedId;
          return (
            <li key={document.id} className={`document-row${isSelected ? " selected" : ""}`}>
              <button
                className="document-select"
                type="button"
                onClick={() => onSelect(document)}
                aria-pressed={isSelected}
              >
                <span className="file-mark" aria-hidden="true">{document.original_filename.split(".").pop()?.toUpperCase()}</span>
                <span className="document-copy">
                  <span className="document-name">{document.original_filename}</span>
                  <span className="document-meta">
                    {formatBytes(document.byte_size)} · {document.chunk_count} chunks
                  </span>
                  <span className={`status status-${document.status}`}>{document.status}</span>
                  {document.error_message && <span className="document-error">{document.error_message}</span>}
                </span>
              </button>
              <button
                className="icon-button danger"
                type="button"
                aria-label={`Delete ${document.original_filename}`}
                title={`Delete ${document.original_filename}`}
                disabled={deletingId === document.id}
                onClick={() => onDelete(document)}
              >
                {deletingId === document.id ? "…" : "×"}
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
