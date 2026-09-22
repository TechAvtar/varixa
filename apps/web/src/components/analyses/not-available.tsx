import { EvidenceLevelBadge } from "@/components/evidence/evidence-level-badge";

/** Honest empty state for a report section whose pipeline step does not exist yet. */
export function NotAvailable({ title, description }: { title: string; description: string }) {
  return (
    <div className="space-y-3 rounded-lg border border-dashed px-6 py-10 text-center">
      <EvidenceLevelBadge level="UNKNOWN" />
      <p className="font-medium">{title}</p>
      <p className="mx-auto max-w-lg text-sm text-muted-foreground">{description}</p>
    </div>
  );
}
