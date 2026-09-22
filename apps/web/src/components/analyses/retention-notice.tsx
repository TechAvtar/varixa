import type { AnalysisResponse } from "@verixa/shared-types";
import { Button } from "@/components/ui/button";
import { formatDateTime } from "@/lib/format";

/** Raw-content retention status and the owner's keep/release control (docs/09). */
export function RetentionNotice({
  a,
  action,
}: {
  a: AnalysisResponse;
  action: (formData: FormData) => Promise<void>;
}) {
  if (a.content_purged_at) {
    return (
      <p className="text-xs text-muted-foreground">
        Original content removed on {formatDateTime(a.content_purged_at)} under the retention
        policy. Records, evidence and the report text remain; images and downloads are gone.
      </p>
    );
  }
  return (
    <form action={action} className="flex flex-wrap items-center gap-2 text-xs">
      <input type="hidden" name="keep" value={a.kept_at ? "0" : "1"} />
      <span className="text-muted-foreground">
        {a.kept_at
          ? `Kept since ${formatDateTime(a.kept_at)}: the original will not expire.`
          : a.retention_at
            ? `Original content expires ${formatDateTime(a.retention_at)} unless kept.`
            : "Original content is retained indefinitely by this deployment's policy."}
      </span>
      {a.retention_at || a.kept_at ? (
        <Button type="submit" size="sm" variant="outline">
          {a.kept_at ? "Release" : "Keep"}
        </Button>
      ) : null}
    </form>
  );
}
