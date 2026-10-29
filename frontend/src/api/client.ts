import type { DocumentRecord, QuestionResponse } from "./types";
import { frontendConfig } from "../config";

export const API_BASE_URL = frontendConfig.apiBaseUrl;

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function detailMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object") return fallback;
  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) =>
        item && typeof item === "object" && "msg" in item ? String(item.msg) : String(item),
      )
      .join("; ");
  }
  const message = (payload as { message?: unknown }).message;
  return typeof message === "string" ? message : fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      payload = undefined;
    }
    throw new ApiError(detailMessage(payload, `Request failed (${response.status})`), response.status);
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function listDocuments(signal?: AbortSignal): Promise<DocumentRecord[]> {
  return request<DocumentRecord[]>("/documents", { signal });
}

export function deleteDocument(documentId: string): Promise<void> {
  return request<void>(`/documents/${encodeURIComponent(documentId)}`, { method: "DELETE" });
}

export function askQuestion(documentId: string, question: string): Promise<QuestionResponse> {
  return request<QuestionResponse>(`/documents/${encodeURIComponent(documentId)}/questions`, {
    method: "POST",
    body: JSON.stringify({ question }),
  });
}

export function uploadDocument(
  file: File,
  onProgress: (percentage: number) => void,
): Promise<DocumentRecord> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", `${API_BASE_URL}/documents`);
    request.setRequestHeader("Accept", "application/json");

    request.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    });
    request.addEventListener("error", () => reject(new ApiError("Unable to reach the server.", 0)));
    request.addEventListener("load", () => {
      let payload: unknown;
      try {
        payload = request.responseText ? JSON.parse(request.responseText) : undefined;
      } catch {
        payload = undefined;
      }
      if (request.status >= 200 && request.status < 300) {
        onProgress(100);
        resolve(payload as DocumentRecord);
      } else {
        reject(
          new ApiError(
            detailMessage(payload, `Upload failed (${request.status || "network error"})`),
            request.status,
          ),
        );
      }
    });

    const body = new FormData();
    body.append("file", file);
    request.send(body);
  });
}
