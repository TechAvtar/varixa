"use client";

import { useTransition } from "react";
import { Button } from "@/components/ui/button";

/**
 * Deletes the analysis after an explicit confirmation. The server action soft-deletes the record
 * and the API sweeps its stored content (docs/09 deletion steps); nothing is reversible.
 */
export function DeleteAnalysisButton({
  title,
  action,
}: {
  title: string;
  action: () => Promise<void>;
}) {
  const [pending, startTransition] = useTransition();
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      disabled={pending}
      className="text-red-700 hover:text-red-800 dark:text-red-300"
      onClick={() => {
        if (
          window.confirm(
            `Delete "${title}"? The original, its derived data and reports are removed. This cannot be undone.`,
          )
        ) {
          startTransition(() => action());
        }
      }}
    >
      {pending ? "Deleting…" : "Delete analysis"}
    </Button>
  );
}
