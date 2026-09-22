import type { ImageForensicsResponse } from "@verixa/shared-types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

function Verdict({ anomaly, prior }: { anomaly: boolean; prior: boolean }) {
  if (anomaly) {
    return (
      <Badge
        variant="outline"
        className="border-transparent bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200"
      >
        POSSIBLE · offset block grid (crop or shift after an earlier JPEG save)
      </Badge>
    );
  }
  if (prior) {
    return (
      <Badge
        variant="outline"
        className="border-transparent bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200"
      >
        POSSIBLE · JPEG block grid inside a non-JPEG file
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="border-transparent bg-muted text-muted-foreground">
      UNKNOWN · no offset grid found
    </Badge>
  );
}

function Profile({ label, values }: { label: string; values: number[] }) {
  const max = Math.max(...values, 1e-6);
  return (
    <div className="space-y-1">
      <p className="text-xs text-muted-foreground">{label}</p>
      <ol className="flex items-end gap-1" aria-label={`${label} by phase`}>
        {values.map((v, i) => (
          <li key={i} className="flex flex-col items-center gap-0.5">
            <span
              className={`w-4 rounded-sm ${i === 0 ? "bg-foreground/70" : "bg-foreground/30"}`}
              style={{ height: `${Math.max(2, (v / max) * 40)}px` }}
              title={`phase ${i}: ${v}`}
            />
            <span className="font-mono text-[10px] text-muted-foreground">{i}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

export function CompressionCard({ data }: { data: ImageForensicsResponse | null }) {
  const c = data?.compression ?? null;
  const skipped = data?.skipped.find((s) => s.method === "compression") ?? null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Compression</CardTitle>
        <CardDescription>
          Encoder settings read from the file (JPEG) and an 8 × 8 block-grid measurement. Settings
          describe the last save only; the grid check is a heuristic correlated with ELA.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {!data ? (
          <p className="text-sm text-muted-foreground">
            Forensic analysis has not been run for this analysis.
          </p>
        ) : skipped ? (
          <p className="text-sm text-muted-foreground">Not applicable: {skipped.reason}</p>
        ) : !c ? (
          <p className="text-sm text-muted-foreground">
            Compression analysis did not produce a result (the step failed or was not run).
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Verdict anomaly={c.anomaly} prior={c.prior_jpeg_grid} />
              <span className="text-xs text-muted-foreground">
                method confidence: {c.confidence} · {c.method} {c.version}
              </span>
            </div>
            <p className="text-sm">{c.observation}</p>

            {c.encoding ? (
              <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-xs sm:grid-cols-[auto_1fr_auto_1fr]">
                <dt className="text-muted-foreground">Estimated quality</dt>
                <dd className="font-mono">
                  {c.encoding.estimated_quality ?? "—"}
                  {c.encoding.standard_tables ? " (standard IJG tables)" : " (custom tables)"}
                </dd>
                <dt className="text-muted-foreground">Chroma subsampling</dt>
                <dd className="font-mono">{c.encoding.subsampling ?? "unknown"}</dd>
                <dt className="text-muted-foreground">Mode</dt>
                <dd className="font-mono">{c.encoding.progressive ? "progressive" : "baseline"}</dd>
                <dt className="text-muted-foreground">Markers</dt>
                <dd className="font-mono">
                  {[c.encoding.has_jfif ? "JFIF" : null, c.encoding.has_adobe ? "Adobe" : null]
                    .filter(Boolean)
                    .join(", ") || "none"}
                </dd>
                <dt className="text-muted-foreground">Tables</dt>
                <dd className="font-mono">
                  {c.encoding.table_count} (luma deviation {c.encoding.luma_table_error ?? "—"})
                </dd>
                <dt className="text-muted-foreground">Chroma table quality</dt>
                <dd className="font-mono">{c.encoding.chroma_estimated_quality ?? "—"}</dd>
              </dl>
            ) : (
              <p className="text-xs text-muted-foreground">
                {c.format}
                {c.lossless_container ? " (lossless container)" : ""}: no JPEG quantisation settings
                to read.
              </p>
            )}

            {c.grid.measured ? (
              <div className="space-y-2 border-t pt-3">
                <h3 className="text-sm font-medium">
                  Block grid
                  <span className="ml-2 text-xs font-normal text-muted-foreground">
                    aligned strength {c.grid.aligned_strength} · strongest offset ({c.grid.offset_x}
                    , {c.grid.offset_y}) at {c.grid.offset_strength}
                  </span>
                </h3>
                <div className="grid gap-4 sm:grid-cols-2">
                  <Profile
                    label="Horizontal (phase 0 = file block boundary)"
                    values={c.grid.profile_x}
                  />
                  <Profile
                    label="Vertical (phase 0 = file block boundary)"
                    values={c.grid.profile_y}
                  />
                </div>
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">
                The image is too small for a block-grid measurement.
              </p>
            )}

            <ul className="space-y-1 border-t pt-3 text-xs text-muted-foreground">
              {c.limitations.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </>
        )}
      </CardContent>
    </Card>
  );
}
