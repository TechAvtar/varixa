import { EvidenceLevelBadge } from "@/components/evidence/evidence-level-badge";
import type { EvidenceItem } from "@/lib/evidence";

const KIND_LABEL: Record<EvidenceItem["kind"], string> = {
  fact: "Fact",
  signal: "Signal",
  unknown: "Unknown",
  conflict: "Conflict",
};

const MAX_JSON_CHARS = 2000;
const numberFormat = new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 });

function isPrimitive(v: unknown): v is string | number | boolean {
  return typeof v === "string" || typeof v === "number" || typeof v === "boolean";
}

function formatPrimitive(v: string | number | boolean): string {
  if (typeof v === "number") return numberFormat.format(v);
  return String(v);
}

/**
 * Generic view of a record's `data`: scalars as rows, short scalar lists joined, anything
 * nested behind a collapsed JSON block. Rules add data without touching this component.
 */
function EvidenceData({ data }: { data: Record<string, unknown> }) {
  const entries = Object.entries(data).filter(([, v]) => v !== null && v !== undefined);
  if (entries.length === 0) return null;
  const rows: Array<[string, string]> = [];
  const nested: Array<[string, unknown]> = [];
  for (const [key, value] of entries) {
    if (isPrimitive(value)) rows.push([key, formatPrimitive(value)]);
    else if (Array.isArray(value) && value.length <= 8 && value.every(isPrimitive))
      rows.push([key, value.map(formatPrimitive).join(", ")]);
    else nested.push([key, value]);
  }
  return (
    <div className="space-y-1 border-t pt-2">
      {rows.length > 0 ? (
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-0.5 text-xs">
          {rows.map(([key, value]) => (
            <div key={key} className="contents">
              <dt className="font-mono text-muted-foreground">{key}</dt>
              <dd className="break-words">{value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {nested.map(([key, value]) => {
        const text = JSON.stringify(value, null, 2) ?? "";
        const truncated = text.length > MAX_JSON_CHARS;
        return (
          <details key={key} className="text-xs">
            <summary className="cursor-pointer font-mono text-muted-foreground">{key}</summary>
            <pre className="mt-1 max-h-48 overflow-auto rounded bg-muted/40 p-2 font-mono leading-relaxed">
              {truncated ? `${text.slice(0, MAX_JSON_CHARS)}\n… (truncated)` : text}
            </pre>
          </details>
        );
      })}
    </div>
  );
}

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
      {item.data ? <EvidenceData data={item.data} /> : null}
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
