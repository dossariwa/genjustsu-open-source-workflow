/** Completed output must use its saved audio-restoration.json, never current configuration. */
export function audioRestoration(mode: unknown) {
  if (mode === "original") {
    return {
      title: "New identity. Original soundtrack.",
      ready: "Preview ready with original audio.",
      quality: "ORIGINAL AUDIO",
      note: "Original audio packets are restored byte-for-byte without re-encoding; generated audio is discarded.",
      verified: true,
    };
  }
  if (mode === "elevenlabs_sts") {
    return {
      title: "New identity. Converted soundtrack.",
      ready: "Preview ready with converted vocals and estimated background audio.",
      quality: "CONVERTED VOICE + ESTIMATED BACKGROUND",
      note: "Voice-conversion export uses converted vocals + estimated residual mix. This is not the original soundtrack. Generated audio is discarded.",
      verified: true,
    };
  }
  return {
    title: "New identity. Review the soundtrack.",
    ready: "Preview ready. Audio restoration mode is unverified.",
    quality: "AUDIO MODE UNVERIFIED",
    note: "The audio restoration mode is unverified. Check the saved restoration metadata and review the soundtrack before exporting.",
    verified: false,
  };
}
