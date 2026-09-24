import type { ImageProvenanceResponse, ProvenanceIngredient } from "@verixa/shared-types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

type Normalized = ImageProvenanceResponse["normalized"];

function Level({ n }: { n: Normalized }) {
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

function IngredientTree({ items, depth = 0 }: { items: ProvenanceIngredient[]; depth?: number }) {
  if (items.length === 0) return null;
  return (
    <ul className={depth === 0 ? "space-y-1" : "mt-1 space-y-1 border-l pl-3"}>
      {items.map((ing, i) => (
        <li key={`${ing.instance_id ?? ing.title ?? "ingredient"}-${i}`} className="text-xs">
          <span className="font-medium">{ing.title ?? ing.format ?? "untitled ingredient"}</span>
          {ing.relationship ? (
            <span className="text-muted-foreground"> · {ing.relationship}</span>
          ) : null}
          {ing.format ? (
            <span className="font-mono text-muted-foreground"> · {ing.format}</span>
          ) : null}
          {ing.failure_codes.length > 0 ? (
            <Badge
              variant="outline"
              className="ml-2 border-transparent bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200"
            >
              validation failures: {ing.failure_codes.join(", ")}
            </Badge>
          ) : ing.validation_codes.length > 0 ? (
            <span className="ml-2 font-mono text-[11px] text-muted-foreground">
              {ing.validation_codes.length} validation code
              {ing.validation_codes.length === 1 ? "" : "s"}
            </span>
          ) : null}
          <IngredientTree items={ing.children} depth={depth + 1} />
        </li>
      ))}
    </ul>
  );
}

/** Signed declarations: what the signer *stated*, shown as stated. */
function Declarations({ n }: { n: Normalized }) {
  const a = n.assertions;
  const sourceTypes = a.source_types ?? [];
  const training = a.training_mining ? Object.entries(a.training_mining) : [];
  const identity = a.identity;
  const hasAny =
    a.hash_data ||
    sourceTypes.length > 0 ||
    training.length > 0 ||
    identity?.present ||
    n.software_agents.length > 0;
  if (!hasAny) return null;
  return (
    <section className="space-y-2 border-t pt-3" aria-labelledby="c2pa-declarations-heading">
      <h3 id="c2pa-declarations-heading" className="text-sm font-medium">
        Signed declarations
      </h3>
      <p className="text-xs text-muted-foreground">
        Statements the signer put in the manifest. They are verified as stated, not as true.
      </p>
      <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
        {a.hash_data ? (
          <>
            <dt className="text-muted-foreground">Signature covers</dt>
            <dd>
              The file bytes ({a.hash_data.alg ?? "hash"}), except {a.hash_data.exclusion_count}{" "}
              excluded range{a.hash_data.exclusion_count === 1 ? "" : "s"} (normally the manifest
              itself).
            </dd>
          </>
        ) : null}
        {sourceTypes.length > 0 ? (
          <>
            <dt className="text-muted-foreground">Digital source type</dt>
            <dd>
              <ul className="space-y-0.5">
                {sourceTypes.map((s, i) => (
                  <li key={`${s.uri}-${i}`} className="font-mono text-xs">
                    {s.short}
                    {s.action ? <span className="text-muted-foreground"> · {s.action}</span> : null}
                  </li>
                ))}
              </ul>
            </dd>
          </>
        ) : null}
        {training.length > 0 ? (
          <>
            <dt className="text-muted-foreground">Training / mining</dt>
            <dd>
              <ul className="space-y-0.5">
                {training.map(([key, use]) => (
                  <li key={key} className="font-mono text-xs">
                    {key}: {use}
                  </li>
                ))}
              </ul>
            </dd>
          </>
        ) : null}
        {identity?.present ? (
          <>
            <dt className="text-muted-foreground">Creator identity (CAWG)</dt>
            <dd className="text-xs">
              {identity.names.length > 0 ? identity.names.join(", ") : "present"}
              {identity.kind ? (
                <span className="font-mono text-muted-foreground"> · {identity.kind}</span>
              ) : null}
            </dd>
          </>
        ) : null}
        {n.software_agents.length > 0 ? (
          <>
            <dt className="text-muted-foreground">Software agents</dt>
            <dd>
              <ul className="space-y-0.5">
                {n.software_agents.map((agent, i) => (
                  <li key={`${agent.name}-${i}`} className="font-mono text-xs">
                    {agent.name}
                    {agent.version ? ` ${agent.version}` : ""}
                    <span className="text-muted-foreground"> · {agent.origin}</span>
                  </li>
                ))}
              </ul>
            </dd>
          </>
        ) : null}
      </dl>
    </section>
  );
}

function Ingredients({ n }: { n: Normalized }) {
  if (n.ingredients.length === 0 && n.manifest_chain.length <= 1) return null;
  return (
    <section className="space-y-2 border-t pt-3" aria-labelledby="c2pa-ingredients-heading">
      <h3 id="c2pa-ingredients-heading" className="text-sm font-medium">
        Ingredients and manifest chain
      </h3>
      <p className="text-xs text-muted-foreground">
        Sources the signer recorded when composing this file, with the validation each carried at
        that time.
        {n.ingredient_failures > 0
          ? ` ${n.ingredient_failures} ingredient${n.ingredient_failures === 1 ? "" : "s"} carried validation failures.`
          : ""}
      </p>
      <IngredientTree items={n.ingredients} />
      {n.manifest_chain.length > 1 ? (
        <ol className="space-y-0.5 text-xs" aria-label="Manifest chain">
          {n.manifest_chain.map((m) => (
            <li key={m.label} className="font-mono">
              {m.parent ? "↳ " : ""}
              {m.signer ?? "unknown signer"}
              {m.signed_at ? ` · ${m.signed_at}` : ""}
              {m.claim_generator ? (
                <span className="text-muted-foreground"> · {m.claim_generator}</span>
              ) : null}
              {m.signed_after_parent ? (
                <span className="text-amber-700 dark:text-amber-300">
                  {" "}
                  · signed after its parent
                </span>
              ) : null}
            </li>
          ))}
        </ol>
      ) : null}
    </section>
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
              <>
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
                    {n.validation.state ? `${n.validation.state} · ` : ""}
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
                <Declarations n={n} />
                <Ingredients n={n} />
              </>
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
