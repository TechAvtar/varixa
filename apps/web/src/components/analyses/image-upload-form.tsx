"use client";

import { IMAGE_UPLOAD } from "@verixa/shared-types";
import { useActionState, useEffect, useId, useRef, useState } from "react";
import { createImageAnalysisAction, type UploadFormState } from "@/app/(app)/analyses/actions";
import { FormError } from "@/components/auth/form-error";
import { SubmitButton } from "@/components/auth/submit-button";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formatBytes } from "@/lib/format";

const initial: UploadFormState = {};
const ACCEPT = IMAGE_UPLOAD.acceptedMimeTypes.join(",");

interface Picked {
  file: File;
  previewUrl: string;
  width?: number;
  height?: number;
  problem?: string;
}

function inspect(file: File): Picked {
  const picked: Picked = { file, previewUrl: URL.createObjectURL(file) };
  const accepted = IMAGE_UPLOAD.acceptedMimeTypes as readonly string[];
  if (file.type && !accepted.includes(file.type)) {
    picked.problem = "This file type is not supported. Use JPEG, PNG, WebP or TIFF.";
  } else if (file.size > IMAGE_UPLOAD.maxBytes) {
    picked.problem = `The file is larger than ${IMAGE_UPLOAD.maxBytes / (1024 * 1024)} MB.`;
  }
  return picked;
}

export function ImageUploadForm() {
  const [state, action] = useActionState(createImageAnalysisAction, initial);
  const [picked, setPicked] = useState<Picked | null>(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const dropId = useId();

  // Release object URLs when the selection changes or the form unmounts.
  useEffect(() => {
    const url = picked?.previewUrl;
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [picked?.previewUrl]);

  function syncInput(file: File) {
    // The hidden input is what actually submits; keep it in step with `picked`.
    if (!inputRef.current) return;
    const dt = new DataTransfer();
    dt.items.add(file);
    inputRef.current.files = dt.files;
  }

  function choose(file: File | undefined) {
    if (!file) return;
    setPicked(inspect(file));
    syncInput(file);
  }

  function clear() {
    setPicked(null);
    if (inputRef.current) inputRef.current.value = "";
  }

  const canSubmit = Boolean(picked) && !picked?.problem;

  return (
    <form
      action={action}
      className="space-y-6"
      noValidate
      onSubmit={() => {
        // React resets uncontrolled fields after a server action settles, which
        // would drop the file on a retry after an error. Restore it from state.
        if (picked && inputRef.current && inputRef.current.files?.length === 0) {
          syncInput(picked.file);
        }
      }}
    >
      <FormError message={state.error} />
      {state.requestId ? (
        <p className="-mt-4 font-mono text-xs text-muted-foreground">request {state.requestId}</p>
      ) : null}

      <div className="space-y-2">
        <Label htmlFor={dropId}>Image</Label>
        <div
          id={dropId}
          role="button"
          tabIndex={0}
          aria-describedby={`${dropId}-hint`}
          onClick={() => inputRef.current?.click()}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              inputRef.current?.click();
            }
          }}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            choose(e.dataTransfer.files?.[0]);
          }}
          className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-6 py-10 text-center text-sm transition-colors focus-visible:outline-2 focus-visible:outline-ring ${
            dragging ? "border-foreground bg-muted" : "border-border hover:bg-muted/50"
          }`}
        >
          <span className="font-medium">
            {picked ? "Choose a different image" : "Drop an image here, or click to browse"}
          </span>
          <span id={`${dropId}-hint`} className="text-xs text-muted-foreground">
            JPEG, PNG, WebP or TIFF · up to {IMAGE_UPLOAD.maxBytes / (1024 * 1024)} MB
          </span>
        </div>
        <input
          ref={inputRef}
          name="file"
          type="file"
          accept={ACCEPT}
          className="sr-only"
          tabIndex={-1}
          onChange={(e) => choose(e.target.files?.[0])}
        />
      </div>

      {picked ? (
        <div className="grid gap-4 rounded-lg border p-4 sm:grid-cols-[8rem_1fr]">
          {/* eslint-disable-next-line @next/next/no-img-element -- local object URL preview */}
          <img
            src={picked.previewUrl}
            alt=""
            className="h-32 w-32 rounded object-cover"
            onLoad={(e) => {
              const img = e.currentTarget;
              setPicked((p) =>
                p ? { ...p, width: img.naturalWidth, height: img.naturalHeight } : p,
              );
            }}
          />
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
            <dt className="text-muted-foreground">File</dt>
            <dd className="truncate" title={picked.file.name}>
              {picked.file.name}
            </dd>
            <dt className="text-muted-foreground">Type</dt>
            <dd>{picked.file.type || "unknown (the server will check)"}</dd>
            <dt className="text-muted-foreground">Size</dt>
            <dd>{formatBytes(picked.file.size)}</dd>
            <dt className="text-muted-foreground">Dimensions</dt>
            <dd>{picked.width && picked.height ? `${picked.width} × ${picked.height}` : "—"}</dd>
            {picked.problem ? (
              <>
                <dt className="text-destructive">Problem</dt>
                <dd className="text-destructive">{picked.problem}</dd>
              </>
            ) : null}
          </dl>
          <div className="sm:col-span-2">
            <Button type="button" variant="ghost" size="sm" onClick={clear}>
              Remove
            </Button>
          </div>
        </div>
      ) : null}

      <div className="space-y-2">
        <Label htmlFor="title">Title (optional)</Label>
        <Input id="title" name="title" maxLength={300} placeholder="Defaults to the file name" />
      </div>

      <SubmitButton pendingLabel="Uploading…" disabled={!canSubmit}>
        Start analysis
      </SubmitButton>
    </form>
  );
}
