import { type FormEvent, useEffect, useState } from "react";
import { askQuestion } from "../api/client";
import type { AnswerSource, DocumentRecord, QuestionResponse } from "../api/types";
import { frontendConfig } from "../config";

interface QuestionWorkspaceProps {
  document: DocumentRecord | null;
}

function headingLabel(heading: AnswerSource["heading_path"]): string | null {
  if (Array.isArray(heading)) return heading.filter(Boolean).join(" › ") || null;
  return heading || null;
}

function pageLabel(source: AnswerSource): string | null {
  if (source.page_start == null) return null;
  if (source.page_end == null || source.page_end === source.page_start) return `Page ${source.page_start}`;
  return `Pages ${source.page_start}–${source.page_end}`;
}

export function QuestionWorkspace({ document }: QuestionWorkspaceProps) {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<QuestionResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setQuestion("");
    setResult(null);
    setError(null);
  }, [document?.id]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const cleanQuestion = question.trim();
    if (!document || !cleanQuestion) return;
    setError(null);
    setResult(null);
    setLoading(true);
    try {
      setResult(await askQuestion(document.id, cleanQuestion));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The question could not be answered.");
    } finally {
      setLoading(false);
    }
  }

  const ready = document?.status === "ready";

  return (
    <main className="workspace" aria-labelledby="workspace-title">
      <div className="workspace-heading">
        <div>
          <p className="eyebrow">Grounded answers</p>
          <h2 id="workspace-title">Ask your document</h2>
        </div>
        {document && <span className="active-document" title={document.original_filename}>{document.original_filename}</span>}
      </div>

      {!document && (
        <div className="workspace-placeholder">
          <span aria-hidden="true">⌁</span>
          <h3>Select a document to begin</h3>
          <p>Choose a ready document from your library, then ask a question about its contents.</p>
        </div>
      )}

      {document && !ready && (
        <div className="message warning-message" role="status">
          {document.status === "failed"
            ? "This document could not be processed. Delete it and try uploading it again."
            : "This document is still being indexed. Questions will be available when it is ready."}
        </div>
      )}

      {document && ready && (
        <>
          <form className="question-form" onSubmit={submit}>
            <label htmlFor="question">What would you like to know?</label>
            <div className="question-controls">
              <textarea
                id="question"
                rows={3}
                maxLength={frontendConfig.questionMaxCharacters}
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                placeholder="For example: What are the main recommendations?"
                disabled={loading}
              />
              <button className="button primary ask-button" type="submit" disabled={!question.trim() || loading}>
                {loading ? "Finding evidence…" : "Ask question"}
              </button>
            </div>
          </form>

          <div className="response-region" aria-live="polite" aria-busy={loading}>
            {loading && <div className="answer-skeleton" role="status">Searching the document and composing an answer…</div>}
            {error && <p className="message error-message" role="alert">{error}</p>}
            {result?.insufficient_evidence && (
              <section className="answer-card insufficient">
                <p className="eyebrow">Not enough evidence</p>
                <h3>I couldn’t find a supported answer in this document.</h3>
                <p>{result.answer || "Try rephrasing your question or asking about a different part of the document."}</p>
              </section>
            )}
            {result && !result.insufficient_evidence && (
              <section className="answer-card">
                <p className="eyebrow">Answer</p>
                <div className="answer-text">{result.answer}</div>
              </section>
            )}
            {result && result.sources.length > 0 && (
              <section className="sources" aria-labelledby="sources-title">
                <div className="source-heading">
                  <h3 id="sources-title">Supporting sources</h3>
                  <span>{result.sources.length} cited</span>
                </div>
                <ol>
                  {result.sources.map((source, index) => {
                    const heading = headingLabel(source.heading_path);
                    const page = pageLabel(source);
                    return (
                      <li className="source-card" key={source.chunk_id}>
                        <div className="source-number" aria-hidden="true">{index + 1}</div>
                        <div>
                          <div className="source-meta">
                            <strong>{source.document_name}</strong>
                            {heading && <span>{heading}</span>}
                            {page && <span>{page}</span>}
                          </div>
                          <blockquote>{source.excerpt}</blockquote>
                          <span className="score">Relevance {Math.round(source.score * 100)}%</span>
                        </div>
                      </li>
                    );
                  })}
                </ol>
              </section>
            )}
          </div>
        </>
      )}
    </main>
  );
}
