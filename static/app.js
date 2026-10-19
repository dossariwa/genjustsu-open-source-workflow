// Workflow API and legacy reference identifiers remain compatible with saved jobs.

const $ = (s) => document.querySelector(s);
let capabilities = {},
  promptTouched = false,
  referenceVersion = 0,
  omittedSecondary = false,
  generationSaved = false,
  savedGeneration = null;
let jobId = new URLSearchParams(location.search).get("job"),
  saved = {},
  maskApproved = false,
  maskFingerprint = "",
  selectedPreview = "",
  busy = false,
  pollTimer;
const base = () => "/runs/" + jobId + "/";
function status(t, error = false) {
  $("#status-text").textContent = t;
  $("#status").classList.toggle("error", error);
}
async function exists(file) {
  return (await fetch(base() + file, { method: "HEAD", cache: "no-store" })).ok;
}
async function json(url, options) {
  const r = await fetch(url, options);
  const j = await r.json();
  if (!r.ok)
    throw Error(
      typeof j.detail === "string"
        ? j.detail
        : "The request could not be completed.",
    );
  return j;
}
for (const input of document.querySelectorAll("form input[type=file]"))
  input.onchange = () => {
    const f = input.files[0];
    if (input.name === "sirio" || input.name === "tein") referenceVersion++;
    if (input.name === "tein") omittedSecondary = false;
    if (!f) return;
    input.closest(".upload").querySelector("[data-filename]").textContent =
      f.name;
    const img = input.closest(".upload").querySelector("img");
    if (input.name === "sirio" && !generationSaved)
      $("#mode-label").textContent = "Seedance 2.5 Draft · Reference video";
    if (img && f.type.startsWith("video/")) img.hidden = true;
    if (img && !f.type.startsWith("video/")) {
      img.src = URL.createObjectURL(f);
      img.hidden = false;
    }
    if (
      (input.name === "sirio" || input.name === "tein") &&
      jobId &&
      !promptTouched &&
      !f.type.startsWith("video/")
    )
      suggestPrompt(false);
  };
async function refresh() {
  if (!jobId) return;
  const items = [
    [
      "Prepared input",
      "seedance-input.mp4",
      "Prepared video + isolated vocals pitched +3",
    ],
    ["Original", "original.mp4", "Original video"],
    ["Depth", "depth.mp4", "Exact depth colors from the model"],
    ["Mask", "mask.mp4", "Full subject mask"],
  ];
  const present = await Promise.all(items.map((x) => exists(x[1])));
  $("#tabs").replaceChildren();
  items.forEach((x, i) => {
    if (!present[i]) return;
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = x[0];
    b.dataset.file = x[1];
    b.onclick = () => {
      selectedPreview = x[1];
      document
        .querySelectorAll("#tabs button")
        .forEach((t) => t.classList.remove("active"));
      b.classList.add("active");
      if ($("#input-video").getAttribute("src") !== base() + x[1])
        $("#input-video").src = base() + x[1];
      $("#input-caption").textContent = x[2];
      $("#input-download").href = base() + x[1];
    };
    $("#tabs").append(b);
  });
  if (present.some(Boolean)) {
    $("#input-empty").hidden = true;
    $("#input-ready").hidden = false;
    (
      [...document.querySelectorAll("#tabs button")].find(
        (b) => b.dataset.file === selectedPreview,
      ) || $("#tabs button")
    ).click();
  }
  const review = await json("/jobs/" + jobId + "/mask-review");
  maskApproved = review.approved;
  maskFingerprint = review.fingerprint || "";
  $("#mask-review-status").textContent = review.note || review.status;
  $("#review-fingerprint").textContent =
    maskFingerprint || "Awaiting prepared artifacts";
  $("#review-check").checked = maskApproved;
  $("#approve-mask").disabled = true;
  if (review.audit)
    $("#audit-status").textContent =
      "Sampled advice only: " + review.audit.findings;
  $("#draft-button").disabled = !present[0] || busy || !maskApproved;
  $("#audio-links").replaceChildren();
  for (const [file, title] of [
    ["isolated_vocals.wav", "Isolated vocals"],
    ["guidance-audio.wav", "Guidance vocals"],
    ["music.wav", "Estimated background"],
    ["dialogue.txt", "Scribe transcript"],
  ]) {
    if (await exists(file)) {
      const a = document.createElement("a");
      a.href = base() + file;
      a.download = file;
      a.textContent = title + " ↓";
      $("#audio-links").append(a);
    }
  }
  for (const name of ["sirio", "tein"]) {
    if ((name === "tein" && omittedSecondary) || saved[name]) continue;
    for (const ext of ["png", "jpg", "jpeg", "webp", "mp4", "mov", "webm"]) {
      const file = name + "-reference." + ext;
      if (await exists(file)) {
        saved[name] = file;
        const img = $("#" + name + "-img");
        if (!["mp4", "mov", "webm"].includes(ext)) {
          img.src = base() + file;
          img.hidden = false;
        }
        img.closest(".upload").querySelector("small").textContent =
          "Saved reference · click to replace";
        break;
      }
    }
  }
  if (await exists("generation.json")) {
    generationSaved = true;
    $("#draft-button").disabled = true;
    $("#suggest-prompt").disabled = true;
    $("#seedance textarea").readOnly = true;
    for (const input of document.querySelectorAll("#seedance input[type=file]"))
      input.disabled = true;
    $("#remove-secondary").disabled = true;
    const g = await json(base() + "generation.json");
    savedGeneration = g;
    const legacy = g.provider === "dreamina-canvas" || g.mode === "m2v";
    $("#resume-preparation").hidden = legacy || g.status !== "preparing";
    $("#provider-label").textContent = legacy
      ? "Dreamina Canvas · saved job"
      : "OpenArt";
    $("#mode-label").textContent =
      g.mode_label ||
      (legacy
        ? "Seedance · Omni (m2v)"
        : "Seedance 2.5 Draft · Reference video (element2video)");
    $("#draft-resolution").textContent =
      "Quality · " + (g.resolution || "unverified") + " draft";
    $("#sent-details").hidden = false;
    $("#generation-id").textContent =
      (legacy ? "Dreamina Canvas" : "OpenArt") +
      " · " +
      (g.history_id || g.submit_id || g.request_id || g.submitId || "saved");
    $("#sent-prompt").textContent = g.prompt;
    $("#sent-references").textContent =
      "Ordered references: " +
      (Array.isArray(g.reference_labels)
        ? g.reference_labels
        : [
            "Prepared source video",
            ...["sirio", "tein"]
              .filter((name) => saved[name])
              .map((name, i) => "Character " + (i + 1) + " · " + saved[name]),
          ]
      ).join(" → ");
    $("#canvas-link").hidden = true;
    if (g.web_url && /^https:\/\//.test(g.web_url)) {
      $("#canvas-link").href = g.web_url;
      $("#canvas-link").textContent = legacy
        ? "Open saved Dreamina canvas ↗"
        : "Open saved OpenArt result ↗";
      $("#canvas-link").hidden = false;
    }
    if (!$("#seedance textarea").dataset.loaded && !promptTouched) {
      $("#seedance textarea").value = g.prompt;
      $("#seedance textarea").dataset.loaded = "true";
    }
    $("#raw-link").href = base() + "seedance-result.mp4";
  }
  const hd = await exists("hd/final-preview.mp4"),
    draft = await exists("final-preview.mp4");
  if (draft || hd) {
    const url = base() + (hd ? "hd/" : "") + "final-preview.mp4";
    $("#final-empty").hidden = true;
    $("#final-ready").hidden = false;
    if ($("#final-video").getAttribute("src") !== url)
      $("#final-video").src = url;
    $("#final-download").href = url;
    const originalURL = base() + "upload.mp4";
    if ($("#comparison-original").getAttribute("src") !== originalURL)
      $("#comparison-original").src = originalURL;
    const audio = await json(
      base() + (hd ? "hd/" : "") + "audio-restoration.json",
    ).catch(() => ({ mode: "unknown" }));
    $("#quality-label").textContent =
      (hd ? "1080P" : "DRAFT") +
      " · " +
      (audio.mode === "original"
        ? "ORIGINAL AUDIO"
        : audio.mode === "elevenlabs_sts"
          ? "CONVERTED VOICE"
          : "AUDIO MODE UNVERIFIED");
    $("#final-download").textContent = hd
      ? "Download 1080p ↓"
      : "Download draft ↓";
    $("#upgrade").disabled =
      hd ||
      busy ||
      !maskApproved ||
      savedGeneration?.provider !== "openart" ||
      capabilities.generation?.video_hd_supported !== true;
  }
}
async function watch() {
  clearTimeout(pollTimer);
  try {
    const j = await json("/jobs/" + jobId);
    busy = j.state === "running";
    status(j.status, j.state === "error");
    $("#credit-panel").hidden = j.state !== "awaiting_credit_approval";
    updateQuoteConsent(j);
    $("#resume-generation").hidden = j.state !== "error";
    if (j.state === "awaiting_credit_approval") {
      $("#credit-status").textContent = j.status;
    }
    $("#go").disabled = busy;
    $("#draft-button").disabled =
      generationSaved || busy || $("#input-ready").hidden || !maskApproved;
    if (busy) {
      $("#upgrade").disabled = true;
      pollTimer = setTimeout(watch, 3000);
    } else await refresh();
  } catch (e) {
    status(e.message, true);
  }
}
$("#form").onsubmit = async (e) => {
  e.preventDefault();
  if (!validateSourceDuration()) return;
  $("#go").disabled = true;
  try {
    status("Uploading and preparing your video…");
    const j = await json("/jobs", {
      method: "POST",
      body: new FormData(e.target),
    });
    location.href = "/?job=" + j.id;
  } catch (e) {
    status(e.message, true);
    $("#go").disabled = false;
  }
};
$("#seedance").onsubmit = async (e) => {
  e.preventDefault();
  if (!jobId) return;
  if (!maskApproved) {
    status("Review and approve the mask first.", true);
    return;
  }
  const button = $("#draft-button");
  button.disabled = true;
  try {
    const data = new FormData(e.target);
    for (const name of ["sirio", "tein"]) {
      if (name === "tein" && omittedSecondary) {
        data.delete(name);
        continue;
      }
      if (!e.target.elements[name].files.length) {
        if (!saved[name]) {
          if (name === "tein") {
            data.delete(name);
            continue;
          }
          throw Error("Choose Character 1’s reference first.");
        }
        data.set(
          name,
          new File(
            [await (await fetch(base() + saved[name])).blob()],
            saved[name],
          ),
        );
      }
    }
    status("Preparing your OpenArt Seedance 2.5 Draft and credit quote…");
    await json("/jobs/" + jobId + "/seedance", { method: "POST", body: data });
    await watch();
  } catch (e) {
    await refresh().catch(() => {});
    status(e.message, true);
    button.disabled = generationSaved || busy || !maskApproved;
  }
};
$("#finish").onsubmit = async (e) => {
  e.preventDefault();
  if (!jobId) {
    status("Prepare your original video first.", true);
    return;
  }
  const b = e.target.querySelector("button");
  b.disabled = true;
  try {
    status("Restoring your entire original audio…");
    await json("/jobs/" + jobId + "/finish", {
      method: "POST",
      body: new FormData(e.target),
    });
    await refresh();
    status("Preview ready with original audio.");
  } catch (e) {
    status(e.message, true);
  } finally {
    b.disabled = false;
  }
};
$("#upgrade").onclick = async () => {
  $("#upgrade").disabled = true;
  try {
    const j = await json("/jobs/" + jobId + "/hd", { method: "POST" });
    $("#upgrade-status").textContent =
      "Generating your approved draft in 1080p…";
    pollHD();
  } catch (e) {
    $("#upgrade-status").textContent = e.message;
    $("#upgrade").disabled = true;
  }
};
async function pollHD() {
  try {
    const j = await json("/jobs/" + jobId + "/hd");
    $("#upgrade-status").textContent = j.status;
    if (j.state === "running") setTimeout(pollHD, 4000);
    else {
      await refresh();
      if (j.state === "error") $("#upgrade").disabled = true;
    }
  } catch (e) {
    $("#upgrade-status").textContent = e.message;
  }
}
$("#review-check").onchange = () => {
  $("#approve-mask").disabled = !$("#review-check").checked;
};
async function saveReview(approved) {
  try {
    const data = new FormData();
    data.set("approved", approved);
    data.set("fingerprint", maskFingerprint);
    data.set(
      "note",
      approved
        ? "User confirms full-clip visual and audio review of the current input."
        : "Mask needs correction. Seedance submission is blocked.",
    );
    await json("/jobs/" + jobId + "/mask-review", {
      method: "POST",
      body: data,
    });
    await refresh();
  } catch (e) {
    status(e.message, true);
  }
}
$("#approve-mask").onclick = () => saveReview(true);
$("#reject-mask").onclick = () => saveReview(false);
$("#seedance textarea").addEventListener("input", () => {
  promptTouched = true;
});
async function referenceData() {
  const form = $("#seedance");
  const data = new FormData();
  for (const name of ["sirio", "tein"]) {
    if (name === "tein" && omittedSecondary) continue;
    const file = form.elements[name].files[0];
    if (file) data.set(name, file);
    else if (saved[name])
      data.set(
        name,
        new File(
          [await (await fetch(base() + saved[name])).blob()],
          saved[name],
        ),
      );
    else if (name === "sirio")
      throw Error("Choose Character 1 reference first.");
  }
  return data;
}
let suggesting = false;
async function suggestPrompt(explicit = true) {
  if (!jobId || suggesting || generationSaved) return;
  const textarea = $("#seedance textarea");
  const previous = textarea.value,
    version = referenceVersion;
  try {
    suggesting = true;
    $("#suggest-prompt").disabled = true;
    const data = await referenceData();
    const result = await json("/jobs/" + jobId + "/prompt", {
      method: "POST",
      body: data,
    });
    if (
      referenceVersion === version &&
      textarea.value === previous &&
      (explicit || !promptTouched)
    ) {
      textarea.value = result.prompt;
      promptTouched = false;
      status(
        "Prompt suggested. Verify the transcript, mapping and exact wording before submission.",
      );
    }
  } catch (e) {
    status(e.message, true);
  } finally {
    suggesting = false;
    $("#suggest-prompt").disabled = false;
    if (referenceVersion !== version && !promptTouched) {
      const f = $("#seedance").elements.sirio.files[0];
      if (f && !f.type.startsWith("video/")) suggestPrompt(false);
    }
  }
}
$("#suggest-prompt").onclick = () => suggestPrompt(true);
$("#remove-secondary").onclick = () => {
  omittedSecondary = true;
  referenceVersion++;
  delete saved.tein;
  const input = $("#seedance").elements.tein;
  input.value = "";
  $("#tein-img").hidden = true;
  input.closest(".upload").querySelector("[data-filename]").textContent =
    "No second character";
  if (!promptTouched) suggestPrompt(false);
};
$("#audit-input").onclick = async () => {
  const b = $("#audit-input");
  b.disabled = true;
  try {
    const a = await json("/jobs/" + jobId + "/audit", { method: "POST" });
    $("#audit-status").textContent = "Sampled advice only: " + a.findings;
  } catch (e) {
    $("#audit-status").textContent = e.message;
  } finally {
    b.disabled = false;
  }
};
$("#approve-credit").onclick = async () => {
  if (!validCreditConsent()) return;
  creditApprovalPending = true;
  const b = $("#approve-credit");
  b.disabled = true;
  $("#credit-check").checked = false;
  $("#credit-check").disabled = true;
  $("#credit-ceiling").disabled = true;
  try {
    const data = new FormData();
    data.set("credit_ceiling", $("#credit-ceiling").value);
    await json("/jobs/" + jobId + "/credit-approval", {
      method: "POST",
      body: data,
    });
    await watch();
  } catch (e) {
    status(e.message, true);
  } finally {
    creditApprovalPending = false;
    $("#credit-check").disabled = false;
    $("#credit-ceiling").disabled = false;
    updateCreditButton();
  }
};
$("#resume-preparation").onclick = async () => {
  const b = $("#resume-preparation");
  b.disabled = true;
  try {
    await json("/jobs/" + jobId + "/resume-preparation", { method: "POST" });
    await watch();
  } catch (e) {
    status(e.message, true);
  } finally {
    b.disabled = false;
  }
};
$("#resume-generation").onclick = async () => {
  try {
    await json("/jobs/" + jobId + "/resume", { method: "POST" });
    await watch();
  } catch (e) {
    status(e.message, true);
  }
};
json("/capabilities")
  .then((c) => {
    capabilities = c;
    renderConfiguration(c);
    const generation = c.generation || {};
    $("#provider-status").textContent =
      generation.detail ||
      (generation.available === true
        ? "OpenArt connection configured. Generation requires your approved credit quote."
        : "OpenArt reference-video contract configured. Check the account telemetry; each submission validates the live model schema.");
    $("#hd-detail").textContent =
      generation.hd_detail ||
      "HD is intentionally disabled until separate quote approval and draft lineage checks are implemented. Your draft is preserved; a new generation must never stand in for an upgrade.";
    $("#upgrade").textContent =
      generation.video_hd_supported === true
        ? "Approve 1080p completion"
        : "1080p upgrade unavailable";
    if (!jobId && !c.segmentation?.ready)
      status(
        "UI ready. Depth preparation needs a raw-mask Space endpoint; Fast face mesh is independent.",
      );
    if (!jobId && c.final_audio_source === "elevenlabs_sts")
      $("#quality-label").textContent =
        "CONVERTED VOICE + ESTIMATED BACKGROUND";
  })
  .catch(() => {
    configurationUnavailable();
    status(
      "Configuration could not be checked. The studio remains available; verify provider setup before preparation.",
      true,
    );
  });
if (jobId) {
  refresh()
    .then(watch)
    .catch((e) => status(e.message, true));
  fetch("/jobs/" + jobId + "/hd")
    .then((r) => (r.ok ? r.json() : null))
    .then((j) => {
      if (j && j.state === "running") {
        $("#upgrade").disabled = true;
        pollHD();
      }
    });
}

// Consent is scoped to the displayed quote. Editing a ceiling revokes the check.
let quoteSignature = "", creditApprovalPending = false;
function updateQuoteConsent(job) {
  const next =
    job.state === "awaiting_credit_approval"
      ? JSON.stringify([jobId, job.status, job.minimum_credit_ceiling])
      : "";
  if (next !== quoteSignature) {
    quoteSignature = next;
    $("#credit-check").checked = false;
    $("#credit-ceiling").value = next ? (job.minimum_credit_ceiling ?? "") : "";
  }
  updateCreditButton();
}
function validCreditConsent() {
  const field = $("#credit-ceiling");
  return (
    !creditApprovalPending &&
    !$("#credit-panel").hidden &&
    $("#credit-check").checked &&
    field.value.trim() !== "" &&
    field.validity.valid &&
    Number.isSafeInteger(Number(field.value)) &&
    Number(field.value) >= 0
  );
}
function updateCreditButton() {
  $("#approve-credit").disabled = !validCreditConsent();
}
$("#credit-check").addEventListener("change", updateCreditButton);
$("#credit-ceiling").addEventListener("input", () => {
  $("#credit-check").checked = false;
  updateCreditButton();
});

// Local duration feedback; provider duration validation still applies.
let sourceDuration = null,
  sourceMetadataVersion = 0;
const modeSelect = $("#form select[name=mode]");
const sourceFile = $("#form input[name=video]");
function validateSourceDuration() {
  const depthMode = modeSelect.value !== "face_mesh";
  const invalid = depthMode && sourceDuration !== null && sourceDuration > 8.0;
  sourceFile.setCustomValidity(
    invalid
      ? "Depth modes accept at most 8.0 seconds (192 frames at 24fps). Choose a shorter clip or Fast · Face Mesh."
      : "",
  );
  $("#duration-status").dataset.invalid = String(invalid);
  if (sourceDuration !== null) {
    $("#duration-status").textContent =
      `${sourceDuration.toFixed(2)}s selected · ${invalid ? "over the depth limit; shorten the clip or choose Fast · Face Mesh." : depthMode ? "within the 8.0s depth limit." : "Fast mode skips SAM; provider duration limits still apply."}`;
  }
  return !invalid;
}
function updatePreparationMode() {
  const mode = modeSelect.value;
  $("#duration-warning").hidden = mode === "face_mesh";
  $("#mode-description").textContent = {
    depth:
      "Colored Hugging Face depth + raw per-frame SAM masks. Keep exact depth colors and isolate the full selected subject.",
    face_mesh:
      "Experimental · one centered speaker. Tracks original frames in the isolated CPU worker; skips depth and SAM. Review every frame for facial alignment and gaps. Seedance drafts support 4–30 seconds.",
    depth_mesh:
      "Experimental · one centered speaker. Colored depth + raw SAM masks with original-frame facial tracking. Both mask and tracking review are required.",
  }[mode];
  validateSourceDuration();
}
modeSelect.addEventListener("change", updatePreparationMode);
sourceFile.addEventListener("change", () => {
  const version = ++sourceMetadataVersion;
  sourceDuration = null;
  sourceFile.setCustomValidity("");
  const file = sourceFile.files[0];
  $("#duration-status").dataset.invalid = "false";
  $("#duration-status").textContent = file
    ? "Reading clip duration locally…"
    : "Choose a clip to check its duration locally.";
  if (!file) return;
  const media = document.createElement("video");
  const url = URL.createObjectURL(file);
  media.preload = "metadata";
  const clean = () => {
    URL.revokeObjectURL(url);
    media.removeAttribute("src");
    media.load();
  };
  media.onloadedmetadata = () => {
    if (version === sourceMetadataVersion) {
      sourceDuration = Number.isFinite(media.duration) ? media.duration : null;
      if (sourceDuration === null)
        $("#duration-status").textContent =
          "Duration unavailable locally; the backend will validate the source.";
      validateSourceDuration();
    }
    clean();
  };
  media.onerror = () => {
    if (version === sourceMetadataVersion)
      $("#duration-status").textContent =
        "Duration unavailable locally; the backend will validate the source.";
    clean();
  };
  media.src = url;
});

function renderConfiguration(c) {
  const generation = c.generation || {},
    segmentation = c.segmentation || {},
    audio = c.audio || {};
  $("#model-telemetry").textContent =
    generation.model || "byte-plus-seedance-2-5-draft";
  $("#model-detail").textContent =
    `${generation.mode || "element2video"} · ${generation.resolution || "480p"} · configured contract`;
  $("#sam-telemetry").textContent =
    segmentation.space || "Raw-mask Space not configured";
  $("#sam-detail").textContent =
    `≤ 8.0s / 192 frames @ 24fps · ${segmentation.ready ? "configured; live unverified" : "configuration required"}`;
  const george = audio.voice_id === "JBFqnCBsd6RMkjVDRZzb";
  $("#voice-telemetry").textContent =
    `${george ? "George" : audio.voice_id ? "Custom voice" : "Voice not set"} · ${audio.configured ? "key configured" : "key unverified"}`;
  $("#voice-detail").textContent =
    `${audio.voice_id || "Requested: JBFqnCBsd6RMkjVDRZzb"} · ${audio.guidance_mode === "elevenlabs_sts" ? "configured STS" : "+3 semitone guidance"}`;
  if (c.final_audio_source === "elevenlabs_sts") {
    $("#audio-mode-note").textContent =
      "Voice-conversion export is explicitly configured: converted vocals + estimated residual mix. This is not the original soundtrack. Generated audio is discarded.";
    $("#finish button").textContent = "Restore configured converted audio";
  }
}
function configurationUnavailable() {
  $("#model-detail").textContent =
    "element2video · 480p · configuration unverified";
  $("#sam-detail").textContent =
    "≤ 8.0s / 192 frames @ 24fps · configuration unverified";
  $("#voice-telemetry").textContent = "George · configuration unverified";
}
let checkingTelemetry = false;
async function refreshTelemetry() {
  if (checkingTelemetry) return;
  checkingTelemetry = true;
  $("#refresh-telemetry").disabled = true;
  const checks = await Promise.allSettled([
    json("/health", { signal: AbortSignal.timeout(10000) }),
    json("/telemetry", { signal: AbortSignal.timeout(30000) }),
  ]);
  const health = checks[0],
    account = checks[1];
  const loopback = $("#loopback-status");
  // Use actual origin so an alternate development port is never labelled 8770.
  loopback.replaceChildren();
  const dot = document.createElement("i");
  dot.className = "dot";
  loopback.append(dot);
  loopback.append(
    `${location.host} · ${health.status === "fulfilled" && health.value.status === "ok" ? "UI online" : "health unverified"}`,
  );
  const summary = account.status === "fulfilled" ? account.value.openart : null;
  if (summary?.authenticated) {
    const plan = summary.plan
      ? summary.plan.charAt(0).toUpperCase() + summary.plan.slice(1)
      : "Plan unavailable";
    const credits =
      typeof summary.credits === "number"
        ? `${summary.credits.toLocaleString()} credits`
        : "balance unavailable";
    $("#account-summary").textContent = `${plan} · ${credits}`;
    const checked = new Date(summary.checked_at);
    $("#account-detail").textContent =
      `MCP account checked${Number.isNaN(checked.getTime()) ? "" : " · " + checked.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} · generation unverified`;
  } else {
    $("#account-summary").textContent = "Account check unavailable";
    $("#account-detail").textContent =
      "Requested profile: Starter · 4,000 credits. Balance unverified.";
  }
  checkingTelemetry = false;
  $("#refresh-telemetry").disabled = false;
}
$("#refresh-telemetry").addEventListener("click", refreshTelemetry);
refreshTelemetry();

// Artwork is browser-local decoration: it never joins job FormData or uploads.
// IndexedDB keeps animated GIFs intact without base64/localStorage size limits.
const heroDefault = "/static/assets/genjutsu_hero.webp";
let heroURL = null,
  heroVersion = 0,
  heroStorageQueue = Promise.resolve();
function heroStore(mode, action) {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open("genjustsu-studio", 1);
    request.onupgradeneeded = () =>
      request.result.createObjectStore("appearance");
    request.onerror = () => reject(request.error);
    request.onsuccess = () => {
      const db = request.result;
      const transaction = db.transaction("appearance", mode);
      const operation = action(transaction.objectStore("appearance"));
      transaction.oncomplete = () => {
        db.close();
        resolve(operation.result);
      };
      transaction.onerror = () => {
        db.close();
        reject(transaction.error);
      };
      transaction.onabort = () => {
        db.close();
        reject(transaction.error);
      };
    };
  });
}
function displayHero(blob) {
  if (heroURL) URL.revokeObjectURL(heroURL);
  heroURL = blob ? URL.createObjectURL(blob) : null;
  $("#hero-image").hidden = false;
  $("#hero-fallback").hidden = true;
  $("#hero-image").src = heroURL || heroDefault;
  $("#hero-image").alt = blob
    ? "Your custom studio visual reference"
    : "Colored depth silhouette transforming into a shinobi figure with crimson and cyan energy";
  $("#hero-origin").textContent = blob ? "YOUR REFERENCE" : "LOCAL ASSET";
}
function persistHero(action) {
  // Keep a rapid upload/reset/upload sequence in the same order on disk.
  heroStorageQueue = heroStorageQueue
    .catch(() => {})
    .then(() => heroStore("readwrite", action));
  return heroStorageQueue;
}
$("#hero-image").addEventListener("error", () => {
  $("#hero-image").hidden = true;
  $("#hero-fallback").hidden = false;
  $("#hero-status").textContent =
    "Default artwork unavailable. Choose a local image or GIF to customize this space.";
});
$("#hero-upload").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const version = ++heroVersion;
  e.target.value = "";
  if (
    !["image/png", "image/jpeg", "image/webp", "image/gif"].includes(
      file.type,
    ) ||
    file.size > 12 * 1024 * 1024
  ) {
    $("#hero-status").textContent =
      "Choose a PNG, JPEG, WebP or GIF up to 12 MB. Your current banner is unchanged.";
    return;
  }
  const probe = new Image(),
    url = URL.createObjectURL(file);
  try {
    await new Promise((resolve, reject) => {
      probe.onload = resolve;
      probe.onerror = reject;
      probe.src = url;
    });
    if (version !== heroVersion) return;
    displayHero(file);
    try {
      await persistHero((store) => store.put(file, "hero"));
      if (version === heroVersion)
        $("#hero-status").textContent =
          `${file.name} · saved in this browser only. Never sent with a generation.`;
    } catch {
      if (version === heroVersion)
        $("#hero-status").textContent =
          `${file.name} · preview only; browser storage is unavailable.`;
    }
  } catch {
    if (version === heroVersion)
      $("#hero-status").textContent =
        "This file could not be displayed. Your current banner is unchanged.";
  } finally {
    URL.revokeObjectURL(url);
  }
});
$("#hero-reset").addEventListener("click", async () => {
  const version = ++heroVersion;
  displayHero(null);
  try {
    await persistHero((store) => store.delete("hero"));
    if (version === heroVersion)
      $("#hero-status").textContent =
        "Default reference restored. Your banner stays separate from generation references.";
  } catch {
    if (version === heroVersion)
      $("#hero-status").textContent =
        "Default shown for this session; saved banner could not be cleared.";
  }
});
const initialHeroVersion = heroVersion;
heroStore("readonly", (store) => store.get("hero"))
  .then((blob) => {
    if (blob instanceof Blob && initialHeroVersion === heroVersion) {
      displayHero(blob);
      $("#hero-status").textContent =
        "Your saved reference · stored in this browser only.";
    }
  })
  .catch(() => {});

// Playing one comparison video pauses the other to prevent overlapping audio.
for (const id of ["comparison-original", "final-video"]) {
  $("#" + id).addEventListener("play", () => {
    $(
      "#" + (id === "final-video" ? "comparison-original" : "final-video"),
    ).pause();
  });
}
const stageObserver = new IntersectionObserver(
  (entries) => {
    const current = entries
      .filter((entry) => entry.isIntersecting)
      .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
    if (!current) return;
    for (const link of document.querySelectorAll(".steps a")) {
      if (link.hash === "#" + current.target.id)
        link.setAttribute("aria-current", "step");
      else link.removeAttribute("aria-current");
    }
  },
  { rootMargin: "-10% 0px -45% 0px", threshold: [0, 0.1, 0.5] },
);
for (const stage of document.querySelectorAll("section.panel[id]"))
  stageObserver.observe(stage);
