import type { EvidenceLevel, OverviewMethodology } from "@verixa/shared-types";
import { EVIDENCE_LEVELS } from "@verixa/shared-types";
import { EvidenceLevelBadge } from "@/components/evidence/evidence-level-badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const STEP_STATUS_LABEL: Record<string, string> = {
  completed: "completed",
  skipped: "skipped",
  failed: "failed",
  running: "running",
  pending: "pending",
};

/** What ran, with which engines and thresholds, and what the levels mean (docs/07, docs/08). */
export function MethodologyNotes({ data }: { data: OverviewMethodology }) {
  const thresholds = data.thresholds as Record<string, unknown>;
  const confidence = (thresholds.confidence ?? {}) as Record<string, number>;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Methodology</CardTitle>
        <CardDescription>
          How this report was produced: the steps that ran, the engines and versions involved, the
          thresholds in force, and what each evidence level means.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5 text-sm">
        <section aria-labelledby="meth-levels" className="space-y-2">
          <h3 id="meth-levels" className="text-sm font-medium">
            Evidence levels
          </h3>
          <dl className="space-y-1.5">
            {EVIDENCE_LEVELS.map((level: EvidenceLevel) => (
              <div key={level} className="grid grid-cols-[auto_1fr] items-start gap-x-3">
                <dt>
                  <EvidenceLevelBadge level={level} />
                </dt>
                <dd className="text-xs text-muted-foreground">{data.level_definitions[level]}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section aria-labelledby="meth-steps" className="space-y-2">
          <h3 id="meth-steps" className="text-sm font-medium">
            Steps
          </h3>
          <ul className="grid gap-x-4 gap-y-1 text-xs sm:grid-cols-2">
            {data.steps.map((s) => (
              <li key={s.name} className="flex items-center gap-2 font-mono">
                <span className="w-24 truncate">{s.name}</span>
                <span
                  className={
                    s.status === "failed"
                      ? "text-red-700 dark:text-red-300"
                      : s.status === "skipped"
                        ? "text-muted-foreground"
                        : ""
                  }
                >
                  {STEP_STATUS_LABEL[s.status] ?? s.status}
                </span>
                {s.duration_ms != null ? (
                  <span className="text-muted-foreground">{s.duration_ms} ms</span>
                ) : null}
                {s.error_code ? (
                  <span className="text-muted-foreground">{s.error_code}</span>
                ) : null}
              </li>
            ))}
          </ul>
        </section>

        <section aria-labelledby="meth-engines" className="space-y-2">
          <h3 id="meth-engines" className="text-sm font-medium">
            Engines and providers
          </h3>
          {data.engines.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              No external engine or provider was called.
            </p>
          ) : (
            <ul className="space-y-1 text-xs">
              {data.engines.map((e) => (
                <li key={`${e.provider}@${e.model_version ?? ""}`} className="font-mono">
                  {e.provider}
                  {e.model_version ? `@${e.model_version}` : ""}{" "}
                  <span className="text-muted-foreground">
                    · {e.operations.join(", ")} · {e.calls} call{e.calls === 1 ? "" : "s"}
                    {e.cached ? `, ${e.cached} cached` : ""}
                    {e.failed ? `, ${e.failed} failed` : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section aria-labelledby="meth-thresholds" className="space-y-2">
          <h3 id="meth-thresholds" className="text-sm font-medium">
            Thresholds in force
          </h3>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-0.5 font-mono text-xs">
            <dt className="text-muted-foreground">AI score high / medium</dt>
            <dd>
              {String(thresholds.ai_score_high)} / {String(thresholds.ai_score_medium)}
            </dd>
            <dt className="text-muted-foreground">pHash near (bits)</dt>
            <dd>{String(thresholds.fingerprint_near_threshold)}</dd>
            <dt className="text-muted-foreground">Text near (Jaccard)</dt>
            <dd>{String(thresholds.text_near_threshold)}</dd>
            <dt className="text-muted-foreground">Language PROBABLE</dt>
            <dd>{String(thresholds.language_probable_confidence)}</dd>
            <dt className="text-muted-foreground">Forensic families for STRONG</dt>
            <dd>{String(thresholds.forensic_families_for_strong)}</dd>
            <dt className="text-muted-foreground">Default confidence</dt>
            <dd>
              {Object.entries(confidence)
                .map(([k, v]) => `${k} ${v}`)
                .join(" · ")}
            </dd>
            <dt className="text-muted-foreground">Conflict penalty</dt>
            <dd>{String(thresholds.conflict_penalty)}</dd>
          </dl>
        </section>

        <section aria-labelledby="meth-notes" className="space-y-2">
          <h3 id="meth-notes" className="text-sm font-medium">
            Principles
          </h3>
          <ul className="list-disc space-y-1 pl-4 text-xs text-muted-foreground">
            {data.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </section>
      </CardContent>
    </Card>
  );
}
