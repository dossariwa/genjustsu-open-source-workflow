"use client";

import { useState } from "react";
import { Check, CheckCircle2, LoaderCircle, ScanEye, ShieldCheck, Sparkles, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import type { Studio } from "@/lib/studio/use-studio";
import { Hint } from "./panel";
import { ToneBadge } from "./tone-badge";

const APPROVE_NOTE = "User confirms full-clip visual and audio review of the current input.";
const REJECT_NOTE = "Mask needs correction. Seedance submission is blocked.";

function shortHash(hash: string) {
  return hash.length > 20 ? `${hash.slice(0, 12)}…${hash.slice(-8)}` : hash;
}

/**
 * Figma "MaskReviewGate". Approval is bound server-side to the artifact
 * SHA-256 (mask_review.py); the UI only posts the fingerprint it was shown.
 */
export function MaskReviewGate({ studio }: { studio: Studio }) {
  const { api, jobId, review, refresh, setStatus } = studio;
  const approved = !!review?.approved;
  const rejected = review?.status === "rejected";
  const fingerprint = review?.fingerprint ?? "";
  // The checkbox mirrors the saved approval; Approve is armed only by a fresh check.
  const [checkState, setCheckState] = useState<{ key: string; checked: boolean; armed: boolean } | null>(null);
  const key = `${fingerprint}:${review?.status ?? ""}`;
  const current = checkState?.key === key ? checkState : { key, checked: approved, armed: false };
  const [saving, setSaving] = useState<"approve" | "reject" | null>(null);
  const [auditing, setAuditing] = useState(false);
  const [auditText, setAuditText] = useState<string | null>(null);

  async function save(next: boolean) {
    if (!jobId) return;
    setSaving(next ? "approve" : "reject");
    try {
      const data = new FormData();
      data.set("approved", String(next));
      data.set("fingerprint", fingerprint);
      data.set("note", next ? APPROVE_NOTE : REJECT_NOTE);
      await api.saveMaskReview(jobId, data);
      setCheckState(null);
      await refresh();
      setStatus(next ? "Input approved · choose the replacement identity." : "Input marked as needing fixes. Seedance submission is blocked.", next ? "success" : "error");
    } catch (error) {
      setStatus((error as Error).message, "error");
    } finally {
      setSaving(null);
    }
  }

  async function audit() {
    if (!jobId) return;
    setAuditing(true);
    try {
      const result = await api.audit(jobId);
      setAuditText("Sampled advice only: " + result.findings);
    } catch (error) {
      setAuditText((error as Error).message);
    } finally {
      setAuditing(false);
    }
  }

  const auditMessage =
    auditText ?? (review?.audit?.findings ? "Sampled advice only: " + review.audit.findings : "AI sampled-frame checks are advisory; full-clip review is required.");

  return (
    <div
      className={cn(
        "space-y-3 rounded-xl border p-4",
        approved && "border-success/50 bg-success/5",
        rejected && "border-danger-text/50 bg-danger-text/5",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-base font-semibold leading-6">Mandatory · Review the complete input</h3>
        <ToneBadge tone={approved ? "success" : rejected ? "danger" : "info"}>
          {approved ? "APPROVED" : rejected ? "NEEDS FIXING" : "HUMAN REVIEW"}
        </ToneBadge>
      </div>
      <Hint>
        Depth: inspect the full mask. Fast Face Mesh: inspect tracking, eyes and mouth across every frame. Combined: review both. Listen
        to embedded guidance throughout.
      </Hint>
      <div className="flex items-center gap-3 rounded-lg border bg-inset px-3 py-2.5">
        <ShieldCheck className="size-4 shrink-0 text-muted-foreground" aria-hidden />
        <span className="label-mono-sm text-muted-foreground">ARTIFACT SHA-256</span>
        <code id="review-fingerprint" className="ml-auto truncate font-mono text-xs text-info-text" title={fingerprint}>
          {fingerprint ? shortHash(fingerprint) : "Awaiting prepared artifacts"}
        </code>
      </div>
      <Button type="button" variant="outline" size="lg" id="audit-input" onClick={audit} disabled={auditing || !jobId}>
        {auditing ? <LoaderCircle className="animate-spin" /> : <Sparkles />} Check sample frames with OpenAI
      </Button>
      <Hint id="audit-status" role="status">
        {auditMessage}
      </Hint>
      <p id="mask-review-status" role="status" className="flex items-center gap-2 text-[13px] text-muted-foreground">
        {approved ? (
          <CheckCircle2 className="size-3.5 text-success" aria-hidden />
        ) : rejected ? (
          <XCircle className="size-3.5 text-danger-text" aria-hidden />
        ) : (
          <ScanEye className="size-3.5" aria-hidden />
        )}
        {review?.note || review?.status || "Mask review required."}
      </p>
      <label
        className={cn(
          "flex cursor-pointer items-start gap-3 rounded-lg border px-3 py-3 text-sm",
          current.checked && "border-crimson/60 bg-crimson/5",
        )}
      >
        <Checkbox
          id="review-check"
          checked={current.checked}
          onCheckedChange={(value) => setCheckState({ key, checked: value === true, armed: value === true })}
          disabled={!fingerprint}
          className="mt-0.5"
        />
        <span>I reviewed the entire prepared clip; its mask or face mesh is correctly aligned throughout.</span>
      </label>
      <div className="flex flex-wrap gap-2">
        <Button type="button" size="lg" id="approve-mask" disabled={!current.armed || !current.checked || !!saving} onClick={() => save(true)}>
          {saving === "approve" ? <LoaderCircle className="animate-spin" /> : <Check />} Approve input
        </Button>
        <Button type="button" variant="outline" size="lg" id="reject-mask" disabled={!!saving || !fingerprint} onClick={() => save(false)}>
          {saving === "reject" && <LoaderCircle className="animate-spin" />} Input needs fixing
        </Button>
      </div>
    </div>
  );
}
