import type { ImageProvenanceResponse } from "@verixa/shared-types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

function Level({ n }: { n: ImageProvenanceResponse["normalized"] }) {
  // Evidence level wording follows docs/07: VERIFIED only for an intact, validated manifest.
  if (!n.has_c2pa) {
    return (
      <Badge variant="outline" className="border-transparent bg-muted text-muted-foreground">
        UNKNOWN · no credentials found
      </Badge>
    );
  }
  if (n.valid_signature) {
    return (
      <Badge
        variant="outline"
        className="border-transparent bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200"
      >
        VERIFIED · manifest intact, signature valid
      </Badge>
    );
  }
  return (
    <Badge
      variant="outline"
      className="border-transparent bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200"
    >
      POSSIBLE · credentials present but validation reported problems
    </Badge>
  );
}

export function ProvenanceCard({ provenance }: { provenance: ImageProvenanceResponse | null }) {
  const n = provenance?.normalized;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Provenance (Content Credentials / C2PA)</CardTitle>
        <CardDescription>
          Cryptographically signed history embedded by capture devices and editing software. Absence
          is the norm and proves nothing.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {!n ? (
          <p className="text-sm text-muted-foreground">
            Provenance was not inspected for this analysis (no C2PA engine available or the step
            failed). Its status is unknown.
          </p>
        ) : (
          <>
            <Level n={n} />

            {n.has_c2pa ? (
              <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
                <dt className="text-muted-foreground">Signer (stated issuer)</dt>
                <dd>{n.signer ?? "—"}</dd>
                <dt className="text-muted-foreground">Signed at</dt>
                <dd className="font-mono text-xs">{n.signed_at ?? "—"}</dd>
                <dt className="text-muted-foreground">Claim generator</dt>
                <dd>{n.claim_generator ?? "—"}</dd>
                <dt className="text-muted-foreground">Title in manifest</dt>
                <dd>{n.title ?? "—"}</dd>
                <dt className="text-muted-foreground">Authors (as claimed)</dt>
                <dd>{n.authors.length ? n.authors.join(", ") : "—"}</dd>
                <dt className="text-muted-foreground">Manifests / ingredients</dt>
                <dd>
                  {n.manifest_count} / {n.ingredient_count}
                </dd>
                <dt className="text-muted-foreground">Actions</dt>
                <dd>
                  {n.actions.length === 0 ? (
                    "—"
                  ) : (
                    <ul className="space-y-0.5">
                      {n.actions.map((a, i) => (
                        <li key={i} className="font-mono text-xs">
                          {a.action ?? "?"}
                          {a.when ? ` · ${a.when}` : ""}
                          {a.software_agent ? ` · ${a.software_agent}` : ""}
                        </li>
                      ))}
                    </ul>
                  )}
                </dd>
                <dt className="text-muted-foreground">Validation</dt>
                <dd className="font-mono text-xs">
                  {n.validation_codes.length ? n.validation_codes.join(", ") : "—"}
                </dd>
                {n.validation_failures.length ? (
                  <>
                    <dt className="text-destructive">Problems</dt>
                    <dd className="text-xs text-destructive">
                      {n.validation_failures
                        .map((f) => `${f.code}: ${f.explanation ?? ""}`)
                        .join("; ")}
                    </dd>
                  </>
                ) : null}
                <dt className="text-muted-foreground">Engine</dt>
                <dd className="font-mono text-xs">
                  {n.engine} {n.engine_version}
                </dd>
              </dl>
            ) : (
              <p className="text-sm text-muted-foreground">
                Inspected with {n.engine} {n.engine_version}: no manifest store in this file.
              </p>
            )}

            <ul className="space-y-1 border-t pt-3 text-xs text-muted-foreground">
              {provenance.limitations.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </>
        )}
      </CardContent>
    </Card>
  );
}
