export type DocumentStatus = "pending" | "processing" | "ready" | "failed" | string;

export interface DocumentRecord {
  id: string;
  original_filename: string;
  media_type: string;
  byte_size: number;
  status: DocumentStatus;
  chunk_count: number;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface AnswerSource {
  chunk_id: string;
  document_id: string;
  document_name: string;
  excerpt: string;
  heading_path: string[] | string | null;
  page_start: number | null;
  page_end: number | null;
  score: number;
}

export interface QuestionResponse {
  answer: string;
  insufficient_evidence: boolean;
  sources: AnswerSource[];
}
