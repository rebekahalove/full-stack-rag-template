import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import type { DocumentRecord, QuestionResponse } from "./api/types";
import { askQuestion, deleteDocument, listDocuments, uploadDocument } from "./api/client";

vi.mock("./api/client", () => ({
  listDocuments: vi.fn(),
  uploadDocument: vi.fn(),
  askQuestion: vi.fn(),
  deleteDocument: vi.fn(),
}));

const document: DocumentRecord = {
  id: "doc-1",
  original_filename: "benefits-guide.pdf",
  media_type: "application/pdf",
  byte_size: 24_000,
  status: "ready",
  chunk_count: 8,
  error_message: null,
  created_at: "2026-10-27T12:00:00Z",
  updated_at: "2026-10-27T12:00:00Z",
};

const failedDocument: DocumentRecord = {
  ...document,
  id: "doc-failed",
  original_filename: "failed-upload.pdf",
  status: "failed",
  chunk_count: 0,
  error_message: "Document processing failed.",
  created_at: "2026-10-28T12:00:00Z",
  updated_at: "2026-10-28T12:00:00Z",
};

const otherDocument: DocumentRecord = {
  ...document,
  id: "doc-2",
  original_filename: "other-guide.md",
  media_type: "text/markdown",
  created_at: "2026-10-26T12:00:00Z",
  updated_at: "2026-10-26T12:00:00Z",
};

const answer: QuestionResponse = {
  answer: "Employees are eligible after 30 days.",
  insufficient_evidence: false,
  sources: [
    {
      chunk_id: "chunk-1",
      document_id: "doc-1",
      document_name: "benefits-guide.pdf",
      excerpt: "Coverage begins after the employee completes 30 days of service.",
      heading_path: ["Benefits", "Eligibility"],
      page_start: 4,
      page_end: 4,
      score: 0.91,
    },
  ],
};

describe("document question workflow", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(listDocuments).mockReset().mockResolvedValue([]);
    vi.mocked(uploadDocument).mockReset().mockImplementation(async (_file, onProgress) => {
      onProgress(100);
      return document;
    });
    vi.mocked(askQuestion).mockReset().mockResolvedValue(answer);
    vi.mocked(deleteDocument).mockReset().mockResolvedValue();
  });

  it("uploads a document, asks a question, and shows cited evidence", async () => {
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByText("Your uploaded documents will appear here.")).toBeInTheDocument();
    const fileInput = screen.getByLabelText(/Drop a file here/i);
    await user.upload(fileInput, new File(["pdf content"], "benefits-guide.pdf", { type: "application/pdf" }));
    await user.click(screen.getByRole("button", { name: "Add to library" }));

    expect((await screen.findAllByText("benefits-guide.pdf")).length).toBeGreaterThan(0);
    expect(uploadDocument).toHaveBeenCalledOnce();
    expect(screen.getByText("Ask your document")).toBeInTheDocument();

    await user.type(screen.getByLabelText("What would you like to know?"), "When does coverage start?");
    await user.click(screen.getByRole("button", { name: "Ask question" }));

    expect(await screen.findByText("Employees are eligible after 30 days.")).toBeInTheDocument();
    expect(screen.getByText("Coverage begins after the employee completes 30 days of service.")).toBeInTheDocument();
    expect(screen.getByText("Benefits › Eligibility")).toBeInTheDocument();
    expect(screen.getByText("Page 4")).toBeInTheDocument();
    expect(askQuestion).toHaveBeenCalledWith("doc-1", "When does coverage start?");
  });

  it("rejects unsupported and empty uploads before calling the API", async () => {
    const user = userEvent.setup({ applyAccept: false });
    render(<App />);
    await screen.findByText("Your uploaded documents will appear here.");
    const fileInput = screen.getByLabelText(/Drop a file here/i);

    await user.upload(fileInput, new File(["hello"], "notes.txt", { type: "text/plain" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Choose a PDF, DOCX, or Markdown file.");
    expect(screen.getByRole("button", { name: "Add to library" })).toBeDisabled();

    await user.upload(fileInput, new File([], "empty.md", { type: "text/markdown" }));
    expect(screen.getByRole("alert")).toHaveTextContent("The selected file is empty.");
    expect(uploadDocument).not.toHaveBeenCalled();
  });

  it("shows an explicit insufficient-evidence response", async () => {
    vi.mocked(listDocuments).mockResolvedValue([document]);
    vi.mocked(askQuestion).mockResolvedValue({
      answer: "The document does not address that topic.",
      insufficient_evidence: true,
      sources: [],
    });
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: /benefits-guide.pdf/i, pressed: false }));
    await user.type(screen.getByLabelText("What would you like to know?"), "What is the vacation policy?");
    await user.click(screen.getByRole("button", { name: "Ask question" }));

    expect(await screen.findByText("Not enough evidence")).toBeInTheDocument();
    expect(screen.getByText("The document does not address that topic.")).toBeInTheDocument();
  });

  it("surfaces loading and question errors without losing the selected document", async () => {
    vi.mocked(listDocuments).mockResolvedValue([document]);
    vi.mocked(askQuestion).mockRejectedValue(new Error("Question service is unavailable."));
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: /benefits-guide.pdf/i, pressed: false }));
    await user.type(screen.getByLabelText("What would you like to know?"), "Summarize this.");
    await user.click(screen.getByRole("button", { name: "Ask question" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Question service is unavailable.");
    expect(screen.getAllByText("benefits-guide.pdf").length).toBeGreaterThan(0);
  });

  it("can retry when the document list fails", async () => {
    vi.mocked(listDocuments)
      .mockRejectedValueOnce(new Error("Unable to reach the server."))
      .mockResolvedValueOnce([document]);
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Unable to reach the server.");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(listDocuments).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("benefits-guide.pdf")).toBeInTheDocument();
  });

  it("clears a failed upload and its alert after the persisted failed document is deleted", async () => {
    vi.mocked(listDocuments)
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([failedDocument]);
    vi.mocked(uploadDocument).mockRejectedValue(new Error("Document processing failed."));
    const user = userEvent.setup();
    render(<App />);

    await screen.findByText("Your uploaded documents will appear here.");
    const fileInput = screen.getByLabelText(/Drop a file here/i) as HTMLInputElement;
    await user.upload(
      fileInput,
      new File(["failed content"], "failed-upload.pdf", { type: "application/pdf" }),
    );
    await user.click(screen.getByRole("button", { name: "Add to library" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Document processing failed.");
    expect(screen.getByText("failed-upload.pdf", { selector: ".drop-title" })).toBeInTheDocument();
    expect(listDocuments).toHaveBeenCalledTimes(2);

    await user.click(await screen.findByRole("button", { name: /failed-upload.pdf/i, pressed: false }));
    expect(screen.getByText(/could not be processed/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Delete failed-upload.pdf" }));

    await waitFor(() => {
      expect(deleteDocument).toHaveBeenCalledWith("doc-failed");
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(screen.getByText("Drop a file here")).toBeInTheDocument();
      expect(fileInput.value).toBe("");
      expect(screen.getByText("Select a document to begin")).toBeInTheDocument();
    });
  });

  it("resets the selected answer when the most recently uploaded document is deleted", async () => {
    const user = userEvent.setup();
    render(<App />);

    await screen.findByText("Your uploaded documents will appear here.");
    await user.upload(
      screen.getByLabelText(/Drop a file here/i),
      new File(["pdf content"], "benefits-guide.pdf", { type: "application/pdf" }),
    );
    await user.click(screen.getByRole("button", { name: "Add to library" }));
    await user.type(await screen.findByLabelText("What would you like to know?"), "When does coverage start?");
    await user.click(screen.getByRole("button", { name: "Ask question" }));
    expect(await screen.findByText("Employees are eligible after 30 days.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Delete benefits-guide.pdf" }));

    await waitFor(() => {
      expect(deleteDocument).toHaveBeenCalledWith("doc-1");
      expect(screen.queryByText("Employees are eligible after 30 days.")).not.toBeInTheDocument();
      expect(screen.getByText("Select a document to begin")).toBeInTheDocument();
      expect(screen.getByText("Drop a file here")).toBeInTheDocument();
    });
  });

  it("keeps the current answer when a different document is deleted", async () => {
    vi.mocked(listDocuments).mockResolvedValue([document, otherDocument]);
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: /benefits-guide.pdf/i, pressed: false }));
    await user.type(screen.getByLabelText("What would you like to know?"), "When does coverage start?");
    await user.click(screen.getByRole("button", { name: "Ask question" }));
    expect(await screen.findByText("Employees are eligible after 30 days.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Delete other-guide.md" }));

    await waitFor(() => expect(deleteDocument).toHaveBeenCalledWith("doc-2"));
    expect(screen.getByText("Employees are eligible after 30 days.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /benefits-guide.pdf/i, pressed: true })).toBeInTheDocument();
  });
});
