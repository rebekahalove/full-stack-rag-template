import { useEffect, useRef, useState } from "react";
import { uploadDocument } from "../api/client";
import type { DocumentRecord } from "../api/types";
import { frontendConfig } from "../config";

const MAX_BYTES = frontendConfig.maxUploadSizeMb * 1024 * 1024;
const ALLOWED_EXTENSIONS = frontendConfig.allowedUploadExtensions;
const EXTENSION_LABELS: Record<string, string> = { ".md": "Markdown" };
const FILE_TYPE_NAMES = ALLOWED_EXTENSIONS.map(
  (value) => EXTENSION_LABELS[value] ?? value.slice(1).toUpperCase(),
);
const FILE_TYPE_LABEL =
  FILE_TYPE_NAMES.length > 1
    ? `${FILE_TYPE_NAMES.slice(0, -1).join(", ")}, or ${FILE_TYPE_NAMES.at(-1)}`
    : FILE_TYPE_NAMES[0];

function validateFile(file: File): string | null {
  const extension = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
  if (!ALLOWED_EXTENSIONS.includes(extension)) return `Choose a ${FILE_TYPE_LABEL} file.`;
  if (file.size === 0) return "The selected file is empty.";
  if (file.size > MAX_BYTES) {
    return `The selected file is larger than ${frontendConfig.maxUploadSizeMb} MB.`;
  }
  return null;
}

interface UploadPanelProps {
  onUploaded: (document: DocumentRecord) => void;
  onUploadFailed: () => void | Promise<void>;
  deletedDocument: DocumentRecord | null;
}

export function UploadPanel({ onUploaded, onUploadFailed, deletedDocument }: UploadPanelProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const handledDeletionId = useRef<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<number | null>(null);

  useEffect(() => {
    if (!deletedDocument || handledDeletionId.current === deletedDocument.id) return;
    handledDeletionId.current = deletedDocument.id;
    if (file?.name !== deletedDocument.original_filename) return;
    setFile(null);
    setError(null);
    setProgress(null);
    if (inputRef.current) inputRef.current.value = "";
  }, [deletedDocument, file?.name]);

  function chooseFile(nextFile: File | undefined) {
    if (!nextFile) return;
    const validationError = validateFile(nextFile);
    setError(validationError);
    setFile(validationError ? null : nextFile);
  }

  async function submit() {
    if (!file) return;
    setError(null);
    setProgress(0);
    try {
      const document = await uploadDocument(file, setProgress);
      onUploaded(document);
      setFile(null);
      if (inputRef.current) inputRef.current.value = "";
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The document could not be uploaded.");
      await onUploadFailed();
    } finally {
      setProgress(null);
    }
  }

  return (
    <section className="panel upload-panel" aria-labelledby="upload-title">
      <div>
        <p className="eyebrow">Build your library</p>
        <h2 id="upload-title">Upload a document</h2>
        <p className="muted">
          {FILE_TYPE_LABEL} · up to {frontendConfig.maxUploadSizeMb} MB
        </p>
      </div>
      <label
        className={`drop-zone${file ? " has-file" : ""}`}
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault();
          chooseFile(event.dataTransfer.files[0]);
        }}
      >
        <span className="upload-icon" aria-hidden="true">↑</span>
        <span className="drop-title">{file ? file.name : "Drop a file here"}</span>
        <span className="drop-hint">{file ? `${(file.size / 1024).toFixed(1)} KB` : "or browse your computer"}</span>
        <input
          ref={inputRef}
          type="file"
          accept={ALLOWED_EXTENSIONS.join(",")}
          onChange={(event) => chooseFile(event.target.files?.[0])}
          disabled={progress !== null}
        />
      </label>
      {error && <p className="message error-message" role="alert">{error}</p>}
      {progress !== null && (
        <div className="progress-wrap" aria-live="polite">
          <div className="progress-label"><span>Uploading and indexing…</span><span>{progress}%</span></div>
          <progress max="100" value={progress}>{progress}%</progress>
        </div>
      )}
      <button className="button primary" type="button" onClick={submit} disabled={!file || progress !== null}>
        {progress !== null ? "Processing…" : "Add to library"}
      </button>
    </section>
  );
}
