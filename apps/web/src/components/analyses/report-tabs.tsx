import Link from "next/link";

export const REPORT_TABS = [
  { key: "overview", label: "Overview" },
  { key: "metadata", label: "Metadata" },
  { key: "provenance", label: "Provenance" },
  { key: "ai", label: "AI Analysis" },
  { key: "forensics", label: "Forensics" },
  { key: "matches", label: "Matches" },
  { key: "timeline", label: "Timeline" },
] as const;

export type ReportTab = (typeof REPORT_TABS)[number]["key"];

export function isReportTab(value: string | undefined): value is ReportTab {
  return REPORT_TABS.some((t) => t.key === value);
}

/**
 * Server-rendered, link-based tabs: each tab is a real URL (`?tab=`), so the
 * report is bookmarkable, works without JavaScript and is keyboard navigable.
 */
export function ReportTabs({
  analysisId,
  active,
  unavailable,
}: {
  analysisId: string;
  active: ReportTab;
  unavailable: ReadonlySet<ReportTab>;
}) {
  return (
    <nav aria-label="Report sections" className="-mx-4 overflow-x-auto px-4">
      <ul role="tablist" className="flex min-w-max gap-1 border-b">
        {REPORT_TABS.map((t) => {
          const isActive = t.key === active;
          const muted = unavailable.has(t.key);
          return (
            <li key={t.key} role="presentation">
              <Link
                role="tab"
                aria-selected={isActive}
                aria-current={isActive ? "page" : undefined}
                href={`/analyses/${analysisId}?tab=${t.key}`}
                className={`-mb-px inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm transition-colors focus-visible:outline-2 focus-visible:outline-ring ${
                  isActive
                    ? "border-foreground font-medium text-foreground"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                }`}
              >
                {t.label}
                {muted ? (
                  <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                    n/a
                  </span>
                ) : null}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
