import type {
  AIDetectionResponse,
  AnalysisResponse,
  ImageFingerprintsResponse,
  ImageForensicsResponse,
  ImageMetadataResponse,
  ImageProvenanceResponse,
  ProviderCallsResponse,
  SourceMatchesResponse,
  TextAnalysisResponse,
  TextFingerprintsResponse,
} from "@verixa/shared-types";
import { EVIDENCE_LEVELS } from "@verixa/shared-types";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { AICard } from "@/components/analyses/ai-card";
import { AnalysisStatusBadge } from "@/components/analyses/analysis-status-badge";
import { ELACard } from "@/components/analyses/ela-card";
import { FingerprintsCard } from "@/components/analyses/fingerprints-card";
import { MetadataCard } from "@/components/analyses/metadata-card";
import { NotAvailable } from "@/components/analyses/not-available";
import { ProcessingSteps } from "@/components/analyses/processing-steps";
import { ProviderCallsCard } from "@/components/analyses/provider-calls-card";
import { ProvenanceCard } from "@/components/analyses/provenance-card";
import { RawJson } from "@/components/analyses/raw-json";
import { SourceMatchesCard } from "@/components/analyses/source-matches-card";
import { TextFingerprintsCard } from "@/components/analyses/text-fingerprints-card";
import { TextStatsCard } from "@/components/analyses/text-stats-card";
import { isReportTab, type ReportTab, ReportTabs } from "@/components/analyses/report-tabs";
import { EvidenceList } from "@/components/evidence/evidence-card";
import { EvidenceLevelBadge } from "@/components/evidence/evidence-level-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { authedRequest } from "@/lib/auth/session";
import { deriveEvidence, type EvidenceItem, summarise } from "@/lib/evidence";
import { formatBytes, formatDateTime, formatType } from "@/lib/format";

export const metadata: Metadata = { title: "Analysis · Verixa" };
export const dynamic = "force-dynamic";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const UNAVAILABLE_IMAGE: ReadonlySet<ReportTab> = new Set(["timeline"]);
const UNAVAILABLE_TEXT: ReadonlySet<ReportTab> = new Set([
  "metadata",
  "provenance",
  "forensics",
  "timeline",
]);

export default async function AnalysisPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ tab?: string }>;
}) {
  const [{ id }, { tab }] = await Promise.all([params, searchParams]);
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

  const evidence = deriveEvidence(a, md, prov, fp, txt, tfp, ai, sources, forensics);
  const counts = summarise(evidence);
  const processing = a.status === "queued" || a.status === "processing";

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
          </div>
          <div className="flex items-center gap-3">
            <AnalysisStatusBadge status={a.status} />
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
            · preliminary, derived from deterministic steps
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
          <Overview a={a} evidence={evidence} text={txt} calls={calls} />
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
                <ELACard data={forensics} />
                <p className="text-xs text-muted-foreground">
                  Compression, noise, resampling and copy-move heuristics arrive in later builds.
                  Nothing is inferred for them in the meantime.
                </p>
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
        ) : (
          <NotAvailable
            title="No timeline can be reconstructed yet"
            description="A timeline is built only from dated evidence (capture time, signing time, edit actions). The evidence engine that assembles it is a later step; nothing is inferred in the meantime."
          />
        )}
      </section>
    </div>
  );
}

function Overview({
  a,
  evidence,
  text,
  calls,
}: {
  a: AnalysisResponse;
  evidence: EvidenceItem[];
  text: TextAnalysisResponse | null;
  calls: ProviderCallsResponse | null;
}) {
  const facts = evidence.filter((e) => e.kind === "fact");
  const signals = evidence.filter((e) => e.kind === "signal");
  const unknowns = evidence.filter((e) => e.kind === "unknown");
  return (
    <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
      <div className="space-y-6">
        <Group
          title="Established facts"
          hint="Directly determined by deterministic or cryptographic checks."
          items={facts}
          empty="Nothing has been established yet."
        />
        <Group
          title="Signals"
          hint="Recorded values and observations worth weighing. None of these is proof."
          items={signals}
          empty="No signals were recorded."
        />
        <Group
          title="Interpretation"
          hint="Plain-language synthesis of the evidence."
          items={[]}
          empty="Not available in this build. Interpretation will be generated only from the evidence above and will always cite it."
        />
        <Group
          title="Unknown"
          hint="What could not be established. Absence of evidence is not evidence."
          items={unknowns}
          empty="Nothing is unknown."
        />
      </div>
      <div className="space-y-6">
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
