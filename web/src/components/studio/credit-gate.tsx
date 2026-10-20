"use client";

import { useState } from "react";
import { Coins, LoaderCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { Studio } from "@/lib/studio/use-studio";
import { Hint } from "./panel";
import { ToneBadge } from "./tone-badge";

/**
 * Figma "CreditGate". Consent is scoped to the displayed quote: a new quote
 * or any edit to the ceiling clears the checkbox (same as static/app.js).
 * The server re-checks the ceiling against its saved quote.
 */
export function CreditGate({ studio }: { studio: Studio }) {
  const { api, jobId, job, watch, setStatus } = studio;
  const signature = JSON.stringify([jobId, job?.status, job?.minimum_credit_ceiling]);
  const [consent, setConsent] = useState<{ signature: string; ceiling: string; checked: boolean } | null>(null);
  const current =
    consent?.signature === signature ? consent : { signature, ceiling: String(job?.minimum_credit_ceiling ?? ""), checked: false };
  const [pending, setPending] = useState(false);

  const value = current.ceiling.trim();
  const numeric = Number(value);
  const valid = !pending && current.checked && value !== "" && /^\d+$/.test(value) && Number.isSafeInteger(numeric) && numeric >= 0;

  async function approve() {
    if (!valid || !jobId) return;
    setPending(true);
    setConsent({ ...current, checked: false });
    try {
      const data = new FormData();
      data.set("credit_ceiling", value);
      await api.creditApproval(jobId, data);
      await watch();
    } catch (error) {
      setStatus((error as Error).message, "error");
    } finally {
      setPending(false);
    }
  }

  return (
    <div id="credit-panel" className="space-y-3 rounded-xl border border-warning/70 bg-card p-4 shadow-[0_0_0_1px] shadow-warning/10">
      <div className="flex items-center justify-between gap-3">
        <span className="label-mono flex items-center gap-2 text-warning-text">
          <Coins className="size-4" aria-hidden /> EXPLICIT SPENDING APPROVAL
        </span>
        <ToneBadge tone="warning">PAID STEP</ToneBadge>
      </div>
      <h3 className="text-base font-semibold">Review the fresh OpenArt quote</h3>
      <p id="credit-status" role="status" className="text-[13px] text-muted-foreground">
        {job?.status}
      </p>
      <div className="space-y-1.5">
        <Label htmlFor="credit-ceiling">Maximum provider credits you approve</Label>
        <div className="relative">
          <Input
            id="credit-ceiling"
            type="number"
            inputMode="numeric"
            min={0}
            step={1}
            value={current.ceiling}
            disabled={pending}
            className="h-10 pr-16"
            onChange={(e) => setConsent({ signature, ceiling: e.target.value, checked: false })}
          />
          <span className="pointer-events-none absolute inset-y-0 right-3 grid place-items-center text-[13px] text-muted-foreground">credits</span>
        </div>
        <Hint>Editing the ceiling clears the approval checkbox.</Hint>
      </div>
      <label className={cn("flex cursor-pointer items-start gap-3 rounded-lg border px-3 py-3 text-sm", current.checked && "border-crimson/60 bg-crimson/5")}>
        <Checkbox
          id="credit-check"
          checked={current.checked}
          disabled={pending}
          onCheckedChange={(v) => setConsent({ ...current, checked: v === true })}
          className="mt-0.5"
        />
        <span>
          I approve this quoted request and the credit ceiling entered above. This is a local approval gate, not a server-enforced
          maximum charge.
        </span>
      </label>
      <Button id="approve-credit" size="lg" className="h-10" disabled={!valid} onClick={approve}>
        {pending ? <LoaderCircle className="animate-spin" /> : <Coins />} Approve quoted credits & continue
      </Button>
    </div>
  );
}
