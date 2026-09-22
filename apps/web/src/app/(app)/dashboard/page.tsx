import type {
  AnalysisCounts,
  AnalysisListResponse,
  UsagePeriodResponse,
} from "@verixa/shared-types";
import type { Metadata } from "next";
import Link from "next/link";
import { AnalysesTable } from "@/components/analyses/analyses-table";
import { EmptyState } from "@/components/empty-state";
import { StatCard } from "@/components/stat-card";
import { UsageCard } from "@/components/usage-card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { authedRequest } from "@/lib/auth/session";

export const metadata: Metadata = { title: "Dashboard · Verixa" };
export const dynamic = "force-dynamic";

const RECENT_LIMIT = 10;

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: Promise<{ deleted?: string }>;
}) {
  const { deleted } = await searchParams;
  const [counts, recent, usage] = await Promise.all([
    authedRequest<AnalysisCounts>("/analysis/counts"),
    authedRequest<AnalysisListResponse>(`/analysis?page=1&page_size=${RECENT_LIMIT}`),
    authedRequest<UsagePeriodResponse>("/usage"),
  ]);

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
          <p className="text-sm text-muted-foreground">
            Your analyses and what has been established so far.
          </p>
        </div>
        <Button nativeButton={false} render={<Link href="/analyses/new" />}>
          New analysis
        </Button>
      </div>

      {deleted === "1" ? (
        <Alert role="status">
          <AlertTitle>Analysis deleted</AlertTitle>
          <AlertDescription>
            The record is marked deleted and its stored content is being removed under the retention
            policy.
          </AlertDescription>
        </Alert>
      ) : null}

      <section aria-labelledby="stats-heading" className="space-y-3">
        <h2 id="stats-heading" className="sr-only">
          Totals
        </h2>
        {counts.ok ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label="Total analyses" value={counts.data.total} />
            <StatCard label="Image analyses" value={counts.data.image} />
            <StatCard label="Text analyses" value={counts.data.text} />
            {usage.ok ? (
              <UsageCard usage={usage.data} />
            ) : (
              <StatCard label="Usage" value={counts.data.total} hint={usage.message} />
            )}
          </div>
        ) : (
          <LoadError what="totals" message={counts.message} requestId={counts.requestId} />
        )}
      </section>

      <section aria-labelledby="recent-heading" className="space-y-3">
        <div className="flex items-end justify-between">
          <h2 id="recent-heading" className="text-lg font-medium">
            Recent analyses
          </h2>
          {recent.ok && recent.data.total > RECENT_LIMIT ? (
            <span className="text-xs text-muted-foreground">
              Showing {RECENT_LIMIT} of {recent.data.total}
            </span>
          ) : null}
        </div>
        {!recent.ok ? (
          <LoadError what="recent analyses" message={recent.message} requestId={recent.requestId} />
        ) : recent.data.items.length === 0 ? (
          <EmptyState
            title="No analyses yet"
            description="Upload an image or paste text to start an evidence-backed analysis."
            action={
              <Button nativeButton={false} render={<Link href="/analyses/new" />}>
                Upload an image
              </Button>
            }
          />
        ) : (
          <AnalysesTable items={recent.data.items} />
        )}
      </section>
    </div>
  );
}

function LoadError({
  what,
  message,
  requestId,
}: {
  what: string;
  message: string;
  requestId?: string;
}) {
  return (
    <Alert variant="destructive" role="alert">
      <AlertTitle>Could not load {what}</AlertTitle>
      <AlertDescription>
        {message}
        {requestId ? <span className="block font-mono text-xs">request {requestId}</span> : null}
      </AlertDescription>
    </Alert>
  );
}
