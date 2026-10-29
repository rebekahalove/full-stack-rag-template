import { useCallback, useEffect, useState } from "react";
import { deleteDocument, listDocuments } from "./api/client";
import type { DocumentRecord } from "./api/types";
import { DocumentLibrary } from "./components/DocumentLibrary";
import { QuestionWorkspace } from "./components/QuestionWorkspace";
import { UploadPanel } from "./components/UploadPanel";
import { frontendConfig } from "./config";

export default function App() {
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deletedDocument, setDeletedDocument] = useState<DocumentRecord | null>(null);

  const loadDocuments = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const records = await listDocuments();
      setDocuments(records);
      setSelectedId((current) => current && records.some((item) => item.id === current) ? current : null);
    } catch (caught) {
      setLoadError(caught instanceof Error ? caught.message : "Documents could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadDocuments();
  }, [loadDocuments]);

  function onUploaded(document: DocumentRecord) {
    setDeletedDocument(null);
    setDocuments((current) => [document, ...current.filter((item) => item.id !== document.id)]);
    setSelectedId(document.id);
  }

  async function onDelete(document: DocumentRecord) {
    if (!window.confirm(`Delete “${document.original_filename}” and its indexed content?`)) return;
    setDeletingId(document.id);
    setLoadError(null);
    try {
      await deleteDocument(document.id);
      setDocuments((current) => current.filter((item) => item.id !== document.id));
      setSelectedId((current) => current === document.id ? null : current);
      setDeletedDocument(document);
    } catch (caught) {
      setLoadError(caught instanceof Error ? caught.message : "The document could not be deleted.");
    } finally {
      setDeletingId(null);
    }
  }

  const selectedDocument = documents.find((document) => document.id === selectedId) ?? null;

  return (
    <div className="app-shell">
      <header className="site-header">
        <a className="brand" href="/" aria-label={`${frontendConfig.appName} home`}>
          <span className="brand-mark" aria-hidden="true">{frontendConfig.appMark}</span>
          <span>{frontendConfig.appName}</span>
        </a>
        <p>{frontendConfig.appTagline}</p>
      </header>
      <div className="app-layout">
        <aside className="sidebar">
          <UploadPanel
            onUploaded={onUploaded}
            onUploadFailed={loadDocuments}
            deletedDocument={deletedDocument}
          />
          <DocumentLibrary
            documents={documents}
            selectedId={selectedId}
            loading={loading}
            error={loadError}
            deletingId={deletingId}
            onSelect={(document) => setSelectedId(document.id)}
            onDelete={(document) => void onDelete(document)}
            onRetry={() => void loadDocuments()}
          />
        </aside>
        <QuestionWorkspace document={selectedDocument} />
      </div>
      <footer>Private by design · Your documents remain in your local environment</footer>
    </div>
  );
}
