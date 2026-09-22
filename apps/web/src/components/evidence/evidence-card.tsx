import { EvidenceLevelBadge } from "@/components/evidence/evidence-level-badge";
import type { EvidenceItem } from "@/lib/evidence";

const KIND_LABEL: Record<EvidenceItem["kind"], string> = {
  fact: "Fact",
  signal: "Signal",
  unknown: "Unknown",
  conflict: "Conflict",
};

export function EvidenceCard({ item }: { item: EvidenceItem }) {
  return (
    <article className="space-y-1.5 rounded-lg border p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <EvidenceLevelBadge level={item.level} />
        <span className="text-xs uppercase tracking-wide text-muted-foreground">
          {KIND_LABEL[item.kind]} · {item.category}
        </span>
        {item.confidence != null ? (
          <span className="font-mono text-[11px] text-muted-foreground">
            conf {item.confidence.toFixed(2)}
          </span>
        ) : null}
        <span className="ml-auto font-mono text-[11px] text-muted-foreground">{item.source}</span>
      </div>
      <p className="font-medium">{item.claim}</p>
      {item.detail ? <p className="text-muted-foreground">{item.detail}</p> : null}
      {item.conflictsWith && item.conflictsWith.length > 0 ? (
        <p className="text-xs text-muted-foreground">
          <span className="font-medium">Conflicts:</span> {item.conflictsWith.join(" ↔ ")}
        </p>
      ) : null}
      {item.limitation ? (
        <p className="text-xs text-muted-foreground">
          <span className="font-medium">Limitation:</span> {item.limitation}
        </p>
      ) : null}
    </article>
  );
}

export function EvidenceList({ items, empty }: { items: EvidenceItem[]; empty: string }) {
  if (items.length === 0) return <p className="text-sm text-muted-foreground">{empty}</p>;
  return (
    <div className="space-y-2">
      {items.map((i) => (
        <EvidenceCard key={i.id} item={i} />
      ))}
    </div>
  );
}
