import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, askQuestion, deleteDocument, listDocuments } from "./client";

describe("API client", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("lists documents from the configured v1 API", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify([{ id: "doc-1" }]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(listDocuments()).resolves.toEqual([{ id: "doc-1" }]);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/api\/v1\/documents$/),
      expect.objectContaining({ headers: expect.objectContaining({ Accept: "application/json" }) }),
    );
  });

  it("sends a JSON question and accepts a no-content deletion", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ answer: "Yes", insufficient_evidence: false, sources: [] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await askQuestion("doc id", "Is this covered?");
    await expect(deleteDocument("doc id")).resolves.toBeUndefined();
    expect(fetchMock.mock.calls[0][0]).toMatch(/documents\/doc%20id\/questions$/);
    expect(fetchMock.mock.calls[0][1]).toEqual(expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ question: "Is this covered?" }),
    }));
  });

  it("turns FastAPI validation details into a useful error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: [{ msg: "Question must not be empty" }] }), {
        status: 422,
        headers: { "Content-Type": "application/json" },
      }),
    ));

    const error = await askQuestion("doc-1", "").catch((caught) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ message: "Question must not be empty", status: 422 });
  });
});
