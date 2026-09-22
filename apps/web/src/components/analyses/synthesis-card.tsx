import type { SynthesisResponse } from "@verixa/shared-types";
import { EvidenceLevelBadge } from "@/components/evidence/evidence-level-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDateTime } from "@/lib/format";

/** The model's explanation, shown only with its citations, grounding flags and warnings. */
export function SynthesisCard({ data }: { data: SynthesisResponse }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          Synthesis
          {data.grounded ? (
            <Badge variant="outline" className="border-transparent bg-muted text-muted-foreground">
              grounded
            </Badge>
          ) : (
            <Badge
              variant="outline"
              className="border-transparent bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200"
            >
              partly ungrounded
            </Badge>
          )}
          {!data.current ? (
            <Badge
              variant="outline"
              className="border-transparent bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200"
            >
              not current
            </Badge>
          ) : null}
        </CardTitle>
        <CardDescription>
          {data.provider} · {data.model}@{data.model_version} · prompt {data.prompt_version} ·{" "}
          {formatDateTime(data.generated_at)}
          {data.cached ? " · cached" : ""}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {data.warnings.length > 0 ? (
          <Alert role="status">
            <AlertTitle>Checks flagged {data.warnings.length} issue(s) in this text</AlertTitle>
            <AlertDescription>
              <ul className="list-disc space-y-0.5 pl-4">
                {data.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        ) : null}

        {data.sections.map((s) => (
          <section key={s.key} aria-labelledby={`syn-${s.key}`} className="space-y-1.5">
            <h3
              id={`syn-${s.key}`}
              className="flex flex-wrap items-center gap-2 text-sm font-medium"
            >
              {s.question}
              {!s.grounded ? (
                <span className="text-[11px] font-normal uppercase tracking-wide text-amber-700 dark:text-amber-300">
                  ungrounded
                </span>
              ) : null}
              {s.dropped_citations > 0 ? (
                <span className="text-[11px] font-normal text-muted-foreground">
                  {s.dropped_citations} invalid citation(s) dropped
                </span>
              ) : null}
            </h3>
            <p className={`text-sm ${s.grounded ? "" : "text-muted-foreground"}`}>{s.text}</p>
            {s.citations.length > 0 ? (
              <ul className="flex flex-wrap gap-1.5" aria-label="Evidence cited">
                {s.citations.map((c) => (
                  <li
                    key={c.id}
                    className="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px]"
                    title={c.claim}
                  >
                    <EvidenceLevelBadge level={c.level} />
                    <span className="font-mono">{c.rule}</span>
                  </li>
                ))}
              </ul>
            ) : null}
          </section>
        ))}

        <ul className="space-y-1 border-t pt-3 text-xs text-muted-foreground">
          {data.limitations.map((l) => (
            <li key={l}>{l}</li>
          ))}
          {data.tokens_in != null || data.estimated_cost != null ? (
            <li className="font-mono">
              tokens {data.tokens_in ?? "?"} in / {data.tokens_out ?? "?"} out
              {data.estimated_cost != null ? ` · est. $${data.estimated_cost.toFixed(4)}` : ""}
            </li>
          ) : null}
        </ul>
      </CardContent>
    </Card>
  );
}
