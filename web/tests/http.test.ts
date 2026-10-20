import { createElement } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { httpApi } from "@/lib/api/http";
import { ApiError } from "@/lib/api/types";
import { SubstitutePanel } from "@/components/studio/substitute-panel";
import { makeStudio } from "./fixtures/studio";

describe("artifact downloads", () => {
  it("returns successful media bytes unchanged", async () => {
    const bytes = new Uint8Array([0, 1, 255, 43]);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(bytes, { headers: { "content-type": "video/mp4" } })));

    const result = await httpApi.runBlob("job-a", "sirio-reference.mp4");

    const contents = await new Promise<ArrayBuffer>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as ArrayBuffer);
      reader.onerror = () => reject(reader.error);
      reader.readAsArrayBuffer(result);
    });
    expect(new Uint8Array(contents)).toEqual(bytes);
    expect(result.type).toBe("video/mp4");
  });

  it.each([401, 404, 500])("surfaces FastAPI's detail and HTTP %s before returning a blob", async (status) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Reference is unavailable." }), { status })));

    const result = httpApi.runBlob("job-a", "sirio-reference.mp4");

    await expect(result).rejects.toBeInstanceOf(ApiError);
    await expect(result).rejects.toMatchObject({ status, message: "Reference is unavailable." });
  });

  it.each(["<html>Gateway failed</html>", JSON.stringify({ detail: [{ msg: "Unexpected payload" }] })])(
    "uses the existing safe fallback for a non-string error response",
    async (body) => {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body, { status: 502 })));
      await expect(httpApi.runBlob("job-a", "sirio-reference.mp4")).rejects.toMatchObject({
        status: 502,
        message: "The request could not be completed.",
      });
    },
  );

  it.each(["draft", "prompt"])("blocks the %s request when a saved reference cannot be downloaded", async (action) => {
    const seedance = vi.fn();
    const suggestPrompt = vi.fn();
    const studio = makeStudio({
      api: { ...httpApi, seedance, suggestPrompt },
      savedRefs: { sirio: { file: "sirio-reference.mp4", url: "/runs/test-job/sirio-reference.mp4", isVideo: true } },
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Saved identity reference is missing." }), { status: 404 })));
    render(createElement(SubstitutePanel, { studio, go: vi.fn() }));

    fireEvent.click(screen.getByRole("button", { name: action === "draft" ? /Prepare draft & get quote/ : /Suggest prompt with OpenAI/ }));

    await waitFor(() => expect(studio.setStatus).toHaveBeenCalledWith("Saved identity reference is missing.", "error"));
    expect(seedance).not.toHaveBeenCalled();
    expect(suggestPrompt).not.toHaveBeenCalled();
    expect(studio.watch).not.toHaveBeenCalled();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledWith("/runs/test-job/sirio-reference.mp4");
  });
});
