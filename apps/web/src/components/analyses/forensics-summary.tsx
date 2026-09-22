import type { ImageForensicsResponse } from "@verixa/shared-types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

type Outcome = "possible" | "nothing" | "unmeasured" | "not-applicable" | "missing";

interface Row {
  method: string;
  label: string;
  outcome: Outcome;
  confidence: string | null;
  observation: string;
  hasMap: boolean;
}

const OUTCOME: Record<Outcome, { text: string; className: string }> = {
  possible: {
    text: "POSSIBLE · signal",
    className: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200",
  },
  nothing: { text: "UNKNOWN · nothing stands out", className: "bg-muted text-muted-foreground" },
  unmeasured: { text: "UNKNOWN · not measurable", className: "bg-muted text-muted-foreground" },
  "not-applicable": {
    text: "UNKNOWN · not applicable",
    className: "bg-muted text-muted-foreground",
  },
  missing: { text: "UNKNOWN · no result", className: "bg-muted text-muted-foreground" },
};

function rows(f: ImageForensicsResponse): Row[] {
  const skipped = new Map(f.skipped.map((s) => [s.method, s.reason]));
  const maps = new Set(f.artifacts.map((a) => a.method));
  const out: Row[] = [];

  const ela = f.ela;
  out.push({
    method: "ela",
    label: "Error Level Analysis",
    outcome: skipped.has("ela")
      ? "not-applicable"
      : !ela
        ? "missing"
        : ela.anomaly
          ? "possible"
          : "nothing",
    confidence: ela?.confidence ?? null,
    observation: skipped.get("ela") ?? ela?.observation ?? "",
    hasMap: maps.has("ela"),
  });

  const c = f.compression;
  out.push({
    method: "compression",
    label: "Compression",
    outcome: skipped.has("compression")
      ? "not-applicable"
      : !c
        ? "missing"
        : c.anomaly || c.prior_jpeg_grid
          ? "possible"
          : "nothing",
    confidence: c?.confidence ?? null,
    observation: skipped.get("compression") ?? c?.observation ?? "",
    hasMap: false,
  });

  const r = f.resampling;
  out.push({
    method: "resampling",
    label: "Resampling",
    outcome: skipped.has("resampling")
      ? "not-applicable"
      : !r
        ? "missing"
        : !r.measured
          ? "unmeasured"
          : r.detected
            ? "possible"
            : "nothing",
    confidence: r?.confidence ?? null,
    observation: skipped.get("resampling") ?? r?.observation ?? "",
    hasMap: false,
  });

  const n = f.noise;
  out.push({
    method: "noise",
    label: "Noise consistency",
    outcome: skipped.has("noise")
      ? "not-applicable"
      : !n
        ? "missing"
        : !n.measured || n.blocks_smooth === 0
          ? "unmeasured"
          : n.anomaly
            ? "possible"
            : "nothing",
    confidence: n?.confidence ?? null,
    observation: skipped.get("noise") ?? n?.observation ?? "",
    hasMap: maps.has("noise"),
  });

  const cm = f.copy_move;
  out.push({
    method: "copy_move",
    label: "Copy-move",
    outcome: skipped.has("copy_move")
      ? "not-applicable"
      : !cm
        ? "missing"
        : !cm.measured
          ? "unmeasured"
          : cm.detected
            ? "possible"
            : "nothing",
    confidence: cm?.confidence ?? null,
    observation: skipped.get("copy_move") ?? cm?.observation ?? "",
    hasMap: maps.has("copy_move"),
  });
  return out;
}

export function ForensicsSummary({ data }: { data: ImageForensicsResponse }) {
  const list = rows(data);
  const signals = list.filter((r) => r.outcome === "possible").length;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Forensic methods</CardTitle>
        <CardDescription>
          Five heuristics ran on the stored original. Each reports what it observed, its design
          confidence and its failure modes; none proves manipulation on its own, and error-level and
          compression signals are correlated rather than independent.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm">
          <span className="font-medium tabular-nums">{signals}</span> of {list.length} methods
          report a signal worth weighing.
        </p>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">Outcome of each forensic method</caption>
            <thead className="text-left text-xs text-muted-foreground">
              <tr>
                <th scope="col" className="py-1 pr-3 font-medium">
                  Method
                </th>
                <th scope="col" className="py-1 pr-3 font-medium">
                  Outcome
                </th>
                <th scope="col" className="py-1 pr-3 font-medium">
                  Confidence
                </th>
                <th scope="col" className="py-1 font-medium">
                  Observation
                </th>
              </tr>
            </thead>
            <tbody className="divide-y align-top">
              {list.map((r) => (
                <tr key={r.method}>
                  <th scope="row" className="py-2 pr-3 text-left font-medium whitespace-nowrap">
                    <a
                      href={`#forensic-${r.method}`}
                      className="underline-offset-4 hover:underline"
                    >
                      {r.label}
                    </a>
                    {r.hasMap ? (
                      <span className="ml-1 text-[10px] uppercase tracking-wide text-muted-foreground">
                        map
                      </span>
                    ) : null}
                  </th>
                  <td className="py-2 pr-3 whitespace-nowrap">
                    <Badge
                      variant="outline"
                      className={`border-transparent ${OUTCOME[r.outcome].className}`}
                    >
                      {OUTCOME[r.outcome].text}
                    </Badge>
                  </td>
                  <td className="py-2 pr-3 font-mono text-xs">{r.confidence ?? "—"}</td>
                  <td className="py-2 text-xs text-muted-foreground">{r.observation}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <ul className="space-y-1 border-t pt-3 text-xs text-muted-foreground">
          {data.limitations.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
