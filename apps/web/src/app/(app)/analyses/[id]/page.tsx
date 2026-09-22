import type { AnalysisResponse } from "@verixa/shared-types";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { AnalysisStatusBadge } from "@/components/analyses/analysis-status-badge";
import { ProcessingSteps } from "@/components/analyses/processing-steps";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { authedRequest } from "@/lib/auth/session";
import { formatBytes, formatDateTime, formatType } from "@/lib/format";

export const metadata: Metadata = { title: "Analysis · Verixa" };
export const dynamic = "force-dynamic";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function AnalysisPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();

  const result = await authedRequest<AnalysisResponse>(`/analysis/${id}`);
  if (!result.ok && result.status === 404) notFound();
  if (!result.ok) {
    return (
      <Alert variant="destructive" role="alert">
        <AlertTitle>Could not load this analysis</AlertTitle>
        <AlertDescription>{result.message}</AlertDescription>
      </Alert>
    );
  }
  const a = result.data;

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            {formatType(a.type)} analysis
          </p>
          <h1 className="text-2xl font-semibold tracking-tight">{a.title ?? "Untitled"}</h1>
          <p className="font-mono text-xs text-muted-foreground">{a.id}</p>
        </div>
        <div className="flex items-center gap-3">
          <AnalysisStatusBadge status={a.status} />
          <Button variant="outline" size="sm" render={<Link href="/dashboard" />}>
            Back to dashboard
          </Button>
        </div>
      </div>

      {a.status === "queued" || a.status === "processing" ? (
        <Alert>
          <AlertTitle>{a.status === "queued" ? "Queued" : "Processing"}</AlertTitle>
          <AlertDescription>
            The file is stored and being processed. Reload this page to see progress; it does not
            refresh automatically.
          </AlertDescription>
        </Alert>
      ) : null}
      {a.status === "completed" ? (
        <Alert>
          <AlertTitle>Processing complete</AlertTitle>
          <AlertDescription>
            Only validation and hashing run in this build. Metadata, provenance, forensic and source
            findings are not yet produced, so no evidence is shown.
          </AlertDescription>
        </Alert>
      ) : null}
      {a.status === "failed" ? (
        <Alert variant="destructive" role="alert">
          <AlertTitle>Analysis failed{a.error_code ? ` (${a.error_code})` : ""}</AlertTitle>
          <AlertDescription>
            {a.error_message ?? "No further details are available."}
          </AlertDescription>
        </Alert>
      ) : null}

      <ProcessingSteps steps={a.steps ?? []} />

      <Card>
        <CardHeader>
          <CardTitle>File</CardTitle>
          <CardDescription>
            Verified facts about the stored original. Type and dimensions were determined from the
            file contents, not the name.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {a.file ? (
            <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
              <dt className="text-muted-foreground">Original name</dt>
              <dd className="truncate">{a.file.original_filename ?? "—"}</dd>
              <dt className="text-muted-foreground">Detected type</dt>
              <dd>{a.file.mime_type ?? "—"}</dd>
              <dt className="text-muted-foreground">Size</dt>
              <dd>{a.file.size_bytes != null ? formatBytes(a.file.size_bytes) : "—"}</dd>
              <dt className="text-muted-foreground">Dimensions</dt>
              <dd>
                {a.file.width != null && a.file.height != null
                  ? `${a.file.width} × ${a.file.height} px`
                  : "—"}
              </dd>
              <dt className="text-muted-foreground">SHA-256</dt>
              <dd className="break-all font-mono text-xs">{a.file.sha256}</dd>
              <dt className="text-muted-foreground">Uploaded</dt>
              <dd>{formatDateTime(a.created_at)}</dd>
            </dl>
          ) : (
            <p className="text-sm text-muted-foreground">No file is attached to this analysis.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
