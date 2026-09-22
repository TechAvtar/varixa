"use client";

import { TEXT_INPUT } from "@verixa/shared-types";
import { useActionState, useState } from "react";
import { createTextAnalysisAction, type TextFormState } from "@/app/(app)/analyses/actions";
import { FormError } from "@/components/auth/form-error";
import { SubmitButton } from "@/components/auth/submit-button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const initial: TextFormState = {};

export function TextInputForm() {
  const [state, action] = useActionState(createTextAnalysisAction, initial);
  const [text, setText] = useState(state.text ?? "");
  const chars = text.length;
  const words = text.trim() ? text.trim().split(/\s+/).length : 0;
  const tooLong = chars > TEXT_INPUT.maxChars;
  const empty = text.trim().length === 0;

  return (
    <form action={action} className="space-y-6" noValidate>
      <FormError message={state.error} />
      {state.requestId ? (
        <p className="-mt-4 font-mono text-xs text-muted-foreground">request {state.requestId}</p>
      ) : null}

      <div className="space-y-2">
        <Label htmlFor="text">Text</Label>
        <textarea
          id="text"
          name="text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={14}
          spellCheck={false}
          aria-describedby="text-hint"
          className="w-full rounded-lg border bg-background px-3 py-2 font-mono text-sm leading-relaxed outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          placeholder="Paste the text to analyse…"
        />
        <p
          id="text-hint"
          className={`text-xs ${tooLong ? "text-destructive" : "text-muted-foreground"}`}
        >
          {chars.toLocaleString()} characters · {words.toLocaleString()} words · limit{" "}
          {TEXT_INPUT.maxChars.toLocaleString()} characters. The original is stored exactly as
          pasted; hidden characters are reported, not silently removed.
        </p>
      </div>

      <div className="space-y-2">
        <Label htmlFor="text-title">Title (optional)</Label>
        <Input
          id="text-title"
          name="title"
          maxLength={300}
          placeholder="Defaults to the first line"
          defaultValue={state.title}
        />
      </div>

      <SubmitButton pendingLabel="Submitting…" disabled={empty || tooLong}>
        Start analysis
      </SubmitButton>
    </form>
  );
}
