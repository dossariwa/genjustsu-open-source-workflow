import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ManualImport } from "@/components/studio/manual-import";
import { RestorePanel } from "@/components/studio/restore-panel";
import type { Studio } from "@/lib/studio/use-studio";
import { makeStudio } from "./fixtures/studio";

function withFinal(audioMode: string, configuredMode?: string): Studio {
  return makeStudio({
    capabilities: { final_audio_source: configuredMode },
    finalPreview: { url: "/runs/test-job/final-preview.mp4", originalUrl: "/runs/test-job/upload.mp4", hd: false, audioMode },
  });
}

describe("completed audio restoration messages", () => {
  it.each(["original", "elevenlabs_sts"])("does not promise an audio mode from current %s configuration before an output exists", (configuredMode) => {
    render(<RestorePanel studio={makeStudio({ capabilities: { final_audio_source: configuredMode } })} go={vi.fn()} />);
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("New identity. Review the soundtrack.");
    expect(screen.getByText(/The job's saved preparation determines the restored audio/)).toBeInTheDocument();
    expect(screen.queryByText(/Original audio packets are restored byte-for-byte/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Preview ready with original audio/)).not.toBeInTheDocument();
  });

  it("uses saved STS output metadata even when the current configuration is original", () => {
    render(<RestorePanel studio={withFinal("elevenlabs_sts", "original")} go={vi.fn()} />);
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("New identity. Converted soundtrack.");
    expect(screen.getByRole("status")).toHaveTextContent("Preview ready with converted vocals and estimated background audio.");
    expect(screen.getByText(/This is not the original soundtrack/)).toBeInTheDocument();
    expect(screen.getByText("DRAFT · CONVERTED VOICE + ESTIMATED BACKGROUND")).toBeInTheDocument();
    expect(screen.queryByText("Preview ready with original audio.")).not.toBeInTheDocument();
  });

  it("uses saved original output metadata even when the current configuration is STS", () => {
    render(<RestorePanel studio={withFinal("original", "elevenlabs_sts")} go={vi.fn()} />);
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("New identity. Original soundtrack.");
    expect(screen.getByRole("status")).toHaveTextContent("Preview ready with original audio.");
    expect(screen.getByText(/Original audio packets are restored byte-for-byte/)).toBeInTheDocument();
    expect(screen.getByText("DRAFT · ORIGINAL AUDIO")).toBeInTheDocument();
    expect(screen.queryByText(/This is not the original soundtrack/)).not.toBeInTheDocument();
  });

  it.each(["unknown", "future-mode", ""])("does not infer original audio from configuration for an unverified %s output", (mode) => {
    render(<RestorePanel studio={withFinal(mode, "original")} go={vi.fn()} />);
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("New identity. Review the soundtrack.");
    expect(screen.getByRole("status")).toHaveTextContent("Preview ready. Audio restoration mode is unverified.");
    expect(screen.getByText("DRAFT · AUDIO MODE UNVERIFIED")).toBeInTheDocument();
    expect(screen.queryByText(/Original audio packets are restored byte-for-byte/)).not.toBeInTheDocument();
  });
});

describe("manual restoration", () => {
  async function submit(studio: Studio) {
    render(<ManualImport studio={studio} />);
    fireEvent.click(screen.getByRole("button", { name: /Import a generated result manually/ }));
    const input = screen.getByLabelText("Seedance result");
    const file = new File(["generated-video"], "result.mp4", { type: "video/mp4" });
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.submit(input.closest("form")!);
    await waitFor(() => expect(studio.api.finish).toHaveBeenCalledTimes(1));
    return file;
  }

  it("keeps pending audio neutral despite original server configuration and uses the saved STS result for success", async () => {
    const studio = makeStudio({ capabilities: { final_audio_source: "original" } });
    studio.api = {
      ...studio.api,
      finish: vi.fn().mockResolvedValue({ url: "/runs/test-job/final-preview.mp4" }),
      runJson: vi.fn().mockResolvedValue({ mode: "elevenlabs_sts" }),
    };

    const file = await submit(studio);

    await waitFor(() => expect(studio.setStatus).toHaveBeenLastCalledWith("Preview ready with converted vocals and estimated background audio.", "success"));
    expect(studio.setStatus).toHaveBeenCalledWith("Restoring the configured source audio…", "busy");
    expect(studio.setStatus).not.toHaveBeenCalledWith("Restoring your entire original audio…", "busy");
    expect(studio.api.runJson).toHaveBeenCalledWith("test-job", "audio-restoration.json");
    expect(vi.mocked(studio.api.finish).mock.calls[0][1].get("video")).toBe(file);
  });

  it("reports original audio when saved metadata differs from the pending configuration", async () => {
    const studio = makeStudio({ capabilities: { final_audio_source: "elevenlabs_sts" } });
    studio.api = {
      ...studio.api,
      finish: vi.fn().mockResolvedValue({ url: "/runs/test-job/final-preview.mp4" }),
      runJson: vi.fn().mockResolvedValue({ mode: "original" }),
    };
    await submit(studio);
    await waitFor(() => expect(studio.setStatus).toHaveBeenLastCalledWith("Preview ready with original audio.", "success"));
  });

  it.each([null, {}, { mode: "future-mode" }])("leaves missing or unknown saved metadata unverified", async (metadata) => {
    const studio = makeStudio();
    studio.api = {
      ...studio.api,
      finish: vi.fn().mockResolvedValue({ url: "/runs/test-job/final-preview.mp4" }),
      runJson: metadata === null ? vi.fn().mockRejectedValue(new Error("Metadata unavailable")) : vi.fn().mockResolvedValue(metadata),
    };
    await submit(studio);
    await waitFor(() => expect(studio.setStatus).toHaveBeenLastCalledWith("Preview ready. Audio restoration mode is unverified.", "neutral"));
    expect(studio.setStatus).not.toHaveBeenCalledWith("Preview ready with original audio.", "success");
  });

  it.each([null, { final_audio_source: "original" }, { final_audio_source: "elevenlabs_sts" }])(
    "keeps the import action neutral until the job's saved audio mode is known",
    (capabilities) => {
      render(<ManualImport studio={makeStudio({ capabilities })} />);
      fireEvent.click(screen.getByRole("button", { name: /Import a generated result manually/ }));
      expect(screen.getByRole("button", { name: "Restore configured audio" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Restore original audio" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Restore configured converted audio" })).not.toBeInTheDocument();
    },
  );

  it("gives each retained import form a unique ID", () => {
    const { container } = render(<><ManualImport studio={makeStudio()} /><ManualImport studio={makeStudio()} /></>);
    screen.getAllByRole("button", { name: /Import a generated result manually/ }).forEach((button) => fireEvent.click(button));
    const forms = Array.from(container.querySelectorAll("form"));
    expect(forms).toHaveLength(2);
    expect(forms[0].id).toBeTruthy();
    expect(forms[1].id).not.toBe(forms[0].id);
  });
});
