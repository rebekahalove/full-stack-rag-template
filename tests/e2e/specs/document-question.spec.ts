import { expect, test } from "@playwright/test";

const documentId = "66d51b8b-dbc0-43c8-88aa-3bf662e85d6c";
const chunkId = "13e211b7-ea1e-431e-89ea-9709adb1ea47";
const failedDocumentId = "0254b21d-9f5e-4ff4-a42a-8a7d3a9a88f8";
const now = "2026-10-27T14:30:00Z";
const corsHeaders = { "access-control-allow-origin": "*" };

test("uploads a document and displays a cited grounded answer", async ({ page }) => {
  let documents: unknown[] = [];

  await page.route("**/api/v1/documents", async (route) => {
    const method = route.request().method();
    if (method === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        headers: corsHeaders,
        body: JSON.stringify(documents),
      });
      return;
    }

    if (method === "POST") {
      const uploaded = {
        id: documentId,
        original_filename: "benefits.md",
        media_type: "text/markdown",
        byte_size: 164,
        status: "ready",
        chunk_count: 2,
        error_message: null,
        created_at: now,
        updated_at: now,
      };
      documents = [uploaded];
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        headers: corsHeaders,
        body: JSON.stringify(uploaded),
      });
      return;
    }

    await route.fallback();
  });

  await page.route(`**/api/v1/documents/${documentId}/questions`, async (route) => {
    expect(route.request().method()).toBe("POST");
    expect(route.request().postDataJSON()).toEqual({ question: "When does coverage begin?" });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: corsHeaders,
      body: JSON.stringify({
        answer: "Coverage begins on the first day of the month following enrollment.",
        insufficient_evidence: false,
        sources: [
          {
            chunk_id: chunkId,
            document_id: documentId,
            document_name: "benefits.md",
            excerpt: "Coverage begins on the first day of the month following enrollment.",
            heading_path: ["Benefits handbook", "Eligibility"],
            page_start: null,
            page_end: null,
            score: 0.94,
          },
        ],
      }),
    });
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Document library" })).toBeVisible();

  await page.locator('input[type="file"]').setInputFiles("fixtures/benefits.md");
  await page.getByRole("button", { name: "Add to library" }).click();

  await expect(page.getByText("benefits.md", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: /benefits\.md/i }).first().click();

  await page.getByLabel("What would you like to know?").fill("When does coverage begin?");
  await page.getByRole("button", { name: "Ask question" }).click();

  await expect(
    page.getByText("Coverage begins on the first day of the month following enrollment.").first(),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "Supporting sources" })).toBeVisible();
  await expect(page.getByText("Benefits handbook › Eligibility")).toBeVisible();
  await expect(page.getByText("Relevance 94%")).toBeVisible();
});

test("renders an insufficient-evidence result without inventing a citation", async ({ page }) => {
  const readyDocument = {
    id: documentId,
    original_filename: "benefits.md",
    media_type: "text/markdown",
    byte_size: 164,
    status: "ready",
    chunk_count: 2,
    error_message: null,
    created_at: now,
    updated_at: now,
  };

  await page.route("**/api/v1/documents", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: corsHeaders,
      body: JSON.stringify([readyDocument]),
    }),
  );
  await page.route(`**/api/v1/documents/${documentId}/questions`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: corsHeaders,
      body: JSON.stringify({
        answer: "The document does not contain that information.",
        insufficient_evidence: true,
        sources: [],
      }),
    }),
  );

  await page.goto("/");
  await page.getByRole("button", { name: /benefits\.md/i }).first().click();
  await page.getByLabel("What would you like to know?").fill("What is the dental deductible?");
  await page.getByRole("button", { name: "Ask question" }).click();

  await expect(page.getByText("Not enough evidence")).toBeVisible();
  await expect(page.getByText("The document does not contain that information.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Supporting sources" })).toHaveCount(0);
});

test("deleting the latest failed document clears its staged upload and error", async ({ page }) => {
  const failedDocument = {
    id: failedDocumentId,
    original_filename: "benefits.md",
    media_type: "text/markdown",
    byte_size: 164,
    status: "failed",
    chunk_count: 0,
    error_message: "Document processing failed.",
    created_at: now,
    updated_at: now,
  };
  let documents: typeof failedDocument[] = [];

  await page.route("**/api/v1/documents", async (route) => {
    const method = route.request().method();
    if (method === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        headers: corsHeaders,
        body: JSON.stringify(documents),
      });
      return;
    }
    if (method === "POST") {
      documents = [failedDocument];
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        headers: corsHeaders,
        body: JSON.stringify({ detail: "Document processing failed." }),
      });
      return;
    }
    await route.fallback();
  });
  await page.route(`**/api/v1/documents/${failedDocumentId}`, async (route) => {
    expect(route.request().method()).toBe("DELETE");
    documents = [];
    await route.fulfill({ status: 204, headers: corsHeaders, body: "" });
  });

  await page.goto("/");
  const fileInput = page.locator('input[type="file"]');
  await fileInput.setInputFiles("fixtures/benefits.md");
  await expect(page.getByText("benefits.md", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Add to library" }).click();

  await expect(page.getByRole("alert")).toHaveText("Document processing failed.");
  await expect(page.getByText("failed", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Delete benefits.md" })).toBeVisible();
  await page.getByRole("button", { name: /benefits\.md.*failed/i }).click();
  await expect(
    page.getByText("This document could not be processed. Delete it and try uploading it again."),
  ).toBeVisible();

  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Delete benefits.md" }).click();

  await expect(page.getByText("Drop a file here")).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(page.getByLabel("0 documents")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Select a document to begin" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Delete benefits.md" })).toHaveCount(0);
  await expect(fileInput).toHaveValue("");
  expect(
    await fileInput.evaluate((element) => (element as HTMLInputElement).files?.length),
  ).toBe(0);
});
