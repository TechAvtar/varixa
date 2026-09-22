import type {
  AIDetectionResponse,
  AnalysisFileLink,
  AnalysisResponse,
  EvidenceListResponse,
  ImageFingerprintsResponse,
  ImageForensicsResponse,
  ImageMetadataResponse,
  ImageProvenanceResponse,
  OverviewResponse,
  ProviderCallsResponse,
  ReportFileLink,
  ReportListResponse,
  SourceMatchesResponse,
  TextAnalysisResponse,
  TextFingerprintsResponse,
  TimelineResponse,
} from "@verixa/shared-types";
import { EVIDENCE_LEVELS } from "@verixa/shared-types";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { AICard } from "@/components/analyses/ai-card";
import { AnalysisStatusBadge } from "@/components/analyses/analysis-status-badge";
import { DeleteAnalysisButton } from "@/components/analyses/delete-analysis-button";
import { CompressionCard } from "@/components/analyses/compression-card";
import { CopyMoveCard } from "@/components/analyses/copy-move-card";
import { ELACard } from "@/components/analyses/ela-card";
import { FingerprintsCard } from "@/components/analyses/fingerprints-card";
import { ForensicViewer } from "@/components/analyses/forensic-viewer";
import { ForensicsSummary } from "@/components/analyses/forensics-summary";
import { MethodologyNotes } from "@/components/analyses/methodology-notes";
import { MetadataCard } from "@/components/analyses/metadata-card";
import { NoiseCard } from "@/components/analyses/noise-card";
import { NotAvailable } from "@/components/analyses/not-available";
import { ProcessingSteps } from "@/components/analyses/processing-steps";
import { ResamplingCard } from "@/components/analyses/resampling-card";
import { ProviderCallsCard } from "@/components/analyses/provider-calls-card";
import { ProvenanceCard } from "@/components/analyses/provenance-card";
import { RawJson } from "@/components/analyses/raw-json";
import { ReportsCard, type ReportWithLink } from "@/components/analyses/reports-card";
import { RetentionNotice } from "@/components/analyses/retention-notice";
import { SourceMatchesCard } from "@/components/analyses/source-matches-card";
import { SynthesisCard } from "@/components/analyses/synthesis-card";
import { TextFingerprintsCard } from "@/components/analyses/text-fingerprints-card";
import { TextStatsCard } from "@/components/analyses/text-stats-card";
import { TimelineCard } from "@/components/analyses/timeline-card";
import { isReportTab, type ReportTab, ReportTabs } from "@/components/analyses/report-tabs";
import { EvidenceList } from "@/components/evidence/evidence-card";
import { EvidenceLevelBadge } from "@/components/evidence/evidence-level-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { authedRequest } from "@/lib/auth/session";
import {
  deriveEvidence,
  type EvidenceItem,
  fromServerEvidence,
  recordsToItems,
  summarise,
} from "@/lib/evidence";
import { formatBytes, formatDateTime, formatType } from "@/lib/format";
import { createReport, deleteAnalysis, setKeep } from "./actions";

export const metadata: Metadata = { title: "Analysis · Verixa" };
export const dynamic = "force-dynamic";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const UNAVAILABLE_IMAGE: ReadonlySet<ReportTab> = new Set([]);
const UNAVAILABLE_TEXT: ReadonlySet<ReportTab> = new Set(["metadata", "provenance", "forensics"]);

export default async function AnalysisPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ tab?: string; report?: string; message?: string }>;
}) {
  const [{ id }, { tab, report: reportOutcome, message: reportMessage }] = await Promise.all([
    params,
    searchParams,
  ]);
  if (!UUID.test(id)) notFound();
  const active: ReportTab = isReportTab(tab) ? tab : "overview";

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

  const isImage = a.type === "image";
  const [
    metadataResult,
    provenanceResult,
    fingerprintsResult,
    textResult,
    textFpResult,
    aiResult,
    matchesResult,
    callsResult,
    forensicsResult,
    fileLinkResult,
    evidenceResult,
    timelineResult,
    overviewResult,
    reportsResult,
  ] = await Promise.all([
    isImage ? authedRequest<ImageMetadataResponse>(`/analysis/${id}/metadata`) : null,
    isImage ? authedRequest<ImageProvenanceResponse>(`/analysis/${id}/provenance`) : null,
    isImage ? authedRequest<ImageFingerprintsResponse>(`/analysis/${id}/fingerprints`) : null,
    isImage ? null : authedRequest<TextAnalysisResponse>(`/analysis/${id}/text`),
    isImage ? null : authedRequest<TextFingerprintsResponse>(`/analysis/${id}/fingerprints`),
    authedRequest<AIDetectionResponse>(`/analysis/${id}/ai`),
    authedRequest<SourceMatchesResponse>(`/analysis/${id}/matches`),
    authedRequest<ProviderCallsResponse>(`/analysis/${id}/provider-calls`),
    isImage ? authedRequest<ImageForensicsResponse>(`/analysis/${id}/forensics`) : null,
    isImage && active === "forensics"
      ? authedRequest<AnalysisFileLink>(`/analysis/${id}/file`)
      : null,
    authedRequest<EvidenceListResponse>(`/analysis/${id}/evidence`),
    active === "timeline" ? authedRequest<TimelineResponse>(`/analysis/${id}/timeline`) : null,
    active === "overview" ? authedRequest<OverviewResponse>(`/analysis/${id}/overview`) : null,
    active === "overview" ? authedRequest<ReportListResponse>(`/analysis/${id}/reports`) : null,
  ]);
  const md = metadataResult?.ok ? metadataResult.data : null;
  const prov = provenanceResult?.ok ? provenanceResult.data : null;
  const fp = fingerprintsResult?.ok ? fingerprintsResult.data : null;
  const txt = textResult?.ok ? textResult.data : null;
  const tfp = textFpResult?.ok ? textFpResult.data : null;
  const ai = aiResult.ok ? aiResult.data : null;
  const sources = matchesResult.ok ? matchesResult.data : null;
  const calls = callsResult.ok ? callsResult.data : null;
  const forensics = forensicsResult?.ok ? forensicsResult.data : null;
  const fileLink = fileLinkResult?.ok ? fileLinkResult.data : null;

  const engine = evidenceResult.ok ? evidenceResult.data : null;
  const timeline = timelineResult?.ok ? timelineResult.data : null;
  const overview = overviewResult?.ok ? overviewResult.data : null;
  const reportItems = reportsResult?.ok ? reportsResult.data.items : [];
  const reports: ReportWithLink[] = await Promise.all(
    reportItems.slice(0, 5).map(async (r) => {
      if (r.status !== "completed") return { ...r, url: null };
      const link = await authedRequest<ReportFileLink>(`/reports/${r.id}/pdf`);
      return { ...r, url: link.ok ? link.data.url : null };
    }),
  );
  const reportError =
    reportOutcome === "error"
      ? (reportMessage ?? "The report could not be generated.")
      : reportOutcome === "failed"
        ? "Rendering failed; the failure is recorded on the report entry below."
        : null;
  const evidence = engine
    ? fromServerEvidence(engine)
    : deriveEvidence(a, md, prov, fp, txt, tfp, ai, sources, forensics);
  const counts = summarise(evidence);
  const processing = a.status === "queued" || a.status === "processing";
  const keepAction = async (formData: FormData) => {
    "use server";
    await setKeep(a.id, String(formData.get("keep")) === "1");
  };
  const deleteAction = async () => {
    "use server";
    await deleteAnalysis(a.id);
  };

  return (
    <div className="space-y-6">
      <header className="space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-1">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">
              {formatType(a.type)} analysis · report
            </p>
            <h1 className="text-2xl font-semibold tracking-tight">{a.title ?? "Untitled"}</h1>
            <p className="font-mono text-xs text-muted-foreground">
              {a.id} · created {formatDateTime(a.created_at)}
            </p>
            <RetentionNotice a={a} action={keepAction} />
          </div>
          <div className="flex items-center gap-3">
            <AnalysisStatusBadge status={a.status} />
            <DeleteAnalysisButton title={a.title ?? "Untitled"} action={deleteAction} />
            <Button
              variant="outline"
              size="sm"
              nativeButton={false}
              render={<Link href="/dashboard" />}
            >
              Dashboard
            </Button>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2" aria-label="Overall evidence summary">
          {EVIDENCE_LEVELS.map((level) => (
            <span key={level} className="inline-flex items-center gap-1.5 text-xs">
              <EvidenceLevelBadge level={level} />
              <span className="tabular-nums text-muted-foreground">{counts[level]}</span>
            </span>
          ))}
          <span className="text-xs text-muted-foreground">
            {engine
              ? `· evidence engine ${engine.engine_version}, ${formatDateTime(engine.generated_at)} · synthesis confidence ${engine.synthesis_confidence.toFixed(2)}${
                  engine.conflicts
                    ? ` · ${engine.conflicts} conflict${engine.conflicts === 1 ? "" : "s"}`
                    : ""
                }`
              : "· preliminary, derived on the client until the evidence step has run"}
          </span>
        </div>

        {processing ? (
          <Alert>
            <AlertTitle>{a.status === "queued" ? "Queued" : "Processing"}</AlertTitle>
            <AlertDescription>
              The file is stored and being processed. Reload to see progress; sections fill in as
              steps complete.
            </AlertDescription>
          </Alert>
        ) : null}
        {engine && engine.conflicts > 0 ? (
          <Alert role="status">
            <AlertTitle>
              {engine.conflicts === 1
                ? "The evidence contains a conflict"
                : `The evidence contains ${engine.conflicts} conflicts`}
            </AlertTitle>
            <AlertDescription>
              Records point in different directions. Both sides are kept and shown under Conflicts
              on the overview; synthesis confidence is {engine.synthesis_confidence.toFixed(2)}.
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

        <ReportTabs
          analysisId={a.id}
          active={active}
          unavailable={isImage ? UNAVAILABLE_IMAGE : UNAVAILABLE_TEXT}
        />
      </header>

      <section role="tabpanel" aria-label={active} className="space-y-6">
        {active === "overview" ? (
          <Overview
            a={a}
            evidence={evidence}
            overview={overview}
            text={txt}
            calls={calls}
            reports={reports}
            reportError={reportError}
            createReportAction={createReport.bind(null, a.id)}
          />
        ) : active === "ai" ? (
          <>
            <EvidenceList
              items={evidence.filter((e) => e.category === "ai")}
              empty="No AI-detection evidence."
            />
            {ai ? (
              <AICard data={ai} />
            ) : (
              <NotAvailable
                title="AI-generation signals were not evaluated"
                description="No AI detector is configured for this deployment, so nothing was scored. When one is connected its output is shown as a probabilistic signal with provider, model and version, never as proof of authorship."
              />
            )}
          </>
        ) : !isImage && active === "matches" ? (
          <>
            <EvidenceList
              items={evidence.filter((e) => e.category === "matches" || e.category === "sources")}
              empty="No match evidence."
            />
            <SourceMatchesCard data={sources} />
            <TextFingerprintsCard data={tfp} />
          </>
        ) : !isImage ? (
          <NotAvailable
            title="Not applicable to text"
            description="This section applies to image analyses only."
          />
        ) : active === "metadata" ? (
          <>
            <EvidenceList
              items={evidence.filter((e) => e.category === "metadata")}
              empty="No metadata evidence."
            />
            <MetadataCard metadata={md} />
            {md ? (
              <div className="space-y-2">
                <RawJson title="Raw EXIF" data={md.exif} />
                <RawJson title="Raw XMP" data={md.xmp} />
                <RawJson title="Raw IPTC" data={md.iptc} />
                <RawJson title="Raw ICC" data={md.icc} />
                <RawJson title="Other groups" data={md.other} />
              </div>
            ) : null}
          </>
        ) : active === "provenance" ? (
          <>
            <EvidenceList
              items={evidence.filter((e) => e.category === "provenance")}
              empty="No provenance evidence."
            />
            <ProvenanceCard provenance={prov} />
            {prov?.normalized.has_c2pa ? (
              <div className="space-y-2">
                <RawJson title="Manifest store" data={prov.manifests} />
                <RawJson title="Validation status" data={prov.validation_status} />
              </div>
            ) : null}
          </>
        ) : active === "forensics" ? (
          <>
            <EvidenceList
              items={evidence.filter((e) => e.category === "forensics")}
              empty="No forensic evidence."
            />
            {forensics ? (
              <>
                <ForensicsSummary data={forensics} />
                <ForensicViewer data={forensics} original={fileLink} />
                <ELACard data={forensics} />
                <CompressionCard data={forensics} />
                <ResamplingCard data={forensics} />
                <NoiseCard data={forensics} />
                <CopyMoveCard data={forensics} />
              </>
            ) : (
              <NotAvailable
                title="Forensic analysis was not run"
                description="The forensic step did not produce a record for this analysis (still processing, or it failed before writing). Each method carries its own observation, confidence and limitations; nothing is inferred without one."
              />
            )}
          </>
        ) : active === "matches" ? (
          <>
            <EvidenceList
              items={evidence.filter((e) => e.category === "matches" || e.category === "sources")}
              empty="No match evidence."
            />
            <SourceMatchesCard data={sources} />
            <FingerprintsCard data={fp} />
          </>
        ) : timeline ? (
          <TimelineCard data={timeline} />
        ) : (
          <NotAvailable
            title="No timeline has been built yet"
            description="The timeline is assembled by the evidence step from recorded times only (capture, signing, edit actions, publication, discovery, submission). It appears once processing completes; nothing is inferred in the meantime."
          />
        )}
      </section>
    </div>
  );
}

function Overview({
  a,
  evidence,
  overview,
  text,
  calls,
  reports,
  reportError,
  createReportAction,
}: {
  a: AnalysisResponse;
  evidence: EvidenceItem[];
  overview: OverviewResponse | null;
  text: TextAnalysisResponse | null;
  calls: ProviderCallsResponse | null;
  reports: ReportWithLink[];
  reportError: string | null;
  createReportAction: (formData: FormData) => Promise<void>;
}) {
  // Server-assembled groups when the report exists; otherwise the client-side preliminary
  // derivation, grouped by the same rule (level first, conflicts apart).
  const verified = overview
    ? recordsToItems(overview.verified)
    : evidence.filter((e) => e.level === "VERIFIED" && e.kind !== "conflict");
  const strong = overview
    ? recordsToItems(overview.strong)
    : evidence.filter((e) => e.level === "STRONG" && e.kind !== "conflict");
  const probabilistic = overview
    ? recordsToItems(overview.probabilistic)
    : evidence.filter(
        (e) => (e.level === "PROBABLE" || e.level === "POSSIBLE") && e.kind !== "conflict",
      );
  const conflicts = overview
    ? recordsToItems(overview.conflicts)
    : evidence.filter((e) => e.kind === "conflict");
  const unknowns = overview
    ? recordsToItems(overview.unknown)
    : evidence.filter((e) => e.level === "UNKNOWN" && e.kind !== "conflict");
  const synthesis = overview?.synthesis ?? null;
  return (
    <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
      <div className="space-y-6">
        <Group
          title="Verified facts"
          hint="Directly established by deterministic or cryptographic checks."
          items={verified}
          empty="Nothing has been directly verified beyond what processing could establish."
        />
        <Group
          title="Strong evidence"
          hint="Technical observations with meaningful evidentiary value. Still not proof on their own."
          items={strong}
          empty="No strong evidence was recorded."
        />
        <Group
          title="Probabilistic signals"
          hint="Detector scores, heuristics and recorded values worth weighing. None of these is proof."
          items={probabilistic}
          empty="No probabilistic signals were recorded."
        />
        <Group
          title="Conflicts"
          hint="Evidence that points in different directions. Both sides are retained and synthesis confidence is lowered."
          items={conflicts}
          empty="No conflicting evidence."
        />
        <section aria-labelledby="grp-interpretation" className="space-y-2">
          <div>
            <h2 id="grp-interpretation" className="text-base font-medium">
              Interpretation
            </h2>
            <p className="text-xs text-muted-foreground">
              Plain-language synthesis written by a language model from the evidence above, and
              nothing else. It cannot add evidence or change a level.
            </p>
          </div>
          {synthesis ? (
            <SynthesisCard data={synthesis} />
          ) : (
            <p className="text-sm text-muted-foreground">
              No synthesis is available: either no LLM provider is configured or the step has not
              run. The evidence above stands on its own.
            </p>
          )}
        </section>
        <Group
          title="Unknown"
          hint="What could not be established, and checks that found nothing. Absence of evidence is not evidence."
          items={unknowns}
          empty="Nothing is unknown."
        />
        {overview ? <MethodologyNotes data={overview.methodology} /> : null}
      </div>
      <div className="space-y-6">
        <ReportsCard
          reports={reports}
          canExport={a.status === "completed"}
          action={createReportAction}
          error={reportError}
        />
        <ProcessingSteps steps={a.steps ?? []} />
        {a.type === "text" ? <TextStatsCard data={text} /> : null}
        <ProviderCallsCard data={calls} />
        <Card>
          <CardHeader>
            <CardTitle>File</CardTitle>
            <CardDescription>Verified facts about the stored original.</CardDescription>
          </CardHeader>
          <CardContent>
            {a.file ? (
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
                <dt className="text-muted-foreground">Name</dt>
                <dd className="truncate">{a.file.original_filename ?? "—"}</dd>
                <dt className="text-muted-foreground">Type</dt>
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
                <dd className="break-all font-mono">{a.file.sha256}</dd>
              </dl>
            ) : (
              <p className="text-sm text-muted-foreground">No file is attached.</p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function Group({
  title,
  hint,
  items,
  empty,
}: {
  title: string;
  hint: string;
  items: EvidenceItem[];
  empty: string;
}) {
  const id = `grp-${title.toLowerCase().replace(/\s+/g, "-")}`;
  return (
    <section aria-labelledby={id} className="space-y-2">
      <div>
        <h2 id={id} className="text-base font-medium">
          {title}
          <span className="ml-2 text-xs font-normal text-muted-foreground">{items.length}</span>
        </h2>
        <p className="text-xs text-muted-foreground">{hint}</p>
      </div>
      <EvidenceList items={items} empty={empty} />
    </section>
  );
}
