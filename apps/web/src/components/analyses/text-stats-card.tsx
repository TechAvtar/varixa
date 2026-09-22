import type { TextAnalysisResponse } from "@verixa/shared-types";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

function num(v: unknown): string {
  return typeof v === "number" ? v.toLocaleString() : "—";
}

export function TextStatsCard({ data }: { data: TextAnalysisResponse | null }) {
  if (!data) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Text</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">Text statistics are not available yet.</p>
        </CardContent>
      </Card>
    );
  }
  const s = data.statistics;
  const st = data.structure;
  const n = data.normalization;
  const hidden =
    (Number(n.zero_width_removed) || 0) +
    (Number(n.bidi_controls_removed) || 0) +
    (Number(n.control_chars_removed) || 0);
  const trigrams = (s.repeated_trigrams as Array<{ phrase: string; count: number }>) ?? [];

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Text statistics</CardTitle>
          <CardDescription>
            Deterministic measurements of the normalised text. They describe the text; they do not
            decide who or what wrote it.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-4">
            <dt className="text-muted-foreground">Characters</dt>
            <dd className="tabular-nums">{num(s.character_count)}</dd>
            <dt className="text-muted-foreground">Words</dt>
            <dd className="tabular-nums">{num(s.word_count)}</dd>
            <dt className="text-muted-foreground">Sentences</dt>
            <dd className="tabular-nums">{num(s.sentence_count)}</dd>
            <dt className="text-muted-foreground">Paragraphs</dt>
            <dd className="tabular-nums">{num(s.paragraph_count)}</dd>
            <dt className="text-muted-foreground">Avg sentence</dt>
            <dd className="tabular-nums">{num(s.avg_sentence_length_words)} words</dd>
            <dt className="text-muted-foreground">Sentence σ</dt>
            <dd className="tabular-nums">{num(s.sentence_length_stddev)}</dd>
            <dt className="text-muted-foreground">Type/token</dt>
            <dd className="tabular-nums">{num(s.type_token_ratio)}</dd>
            <dt className="text-muted-foreground">Avg word</dt>
            <dd className="tabular-nums">{num(s.avg_word_length)} chars</dd>
            <dt className="text-muted-foreground">Repeated sentences</dt>
            <dd className="tabular-nums">{num(s.repeated_sentence_count)}</dd>
            <dt className="text-muted-foreground">Punctuation /100w</dt>
            <dd className="tabular-nums">{num(s.punctuation_per_100_words)}</dd>
            <dt className="text-muted-foreground">URLs / emails</dt>
            <dd className="tabular-nums">
              {num(s.url_count)} / {num(s.email_count)}
            </dd>
            <dt className="text-muted-foreground">Hidden chars removed</dt>
            <dd className={`tabular-nums ${hidden ? "text-amber-700 dark:text-amber-400" : ""}`}>
              {hidden.toLocaleString()}
            </dd>
          </dl>

          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-sm">
            <dt className="text-muted-foreground">Language (detected)</dt>
            <dd>
              {data.language?.language ? (
                <>
                  <span className="font-mono">{data.language.language}</span>
                  <span className="ml-2 text-xs text-muted-foreground">
                    p≈{data.language.confidence?.toFixed(2)} · {data.language.engine} · a
                    statistical guess, not a fact
                  </span>
                </>
              ) : (
                <span className="text-muted-foreground">
                  not determined{data.language?.reason ? ` (${data.language.reason})` : ""}
                </span>
              )}
            </dd>
            <dt className="text-muted-foreground">Structure</dt>
            <dd className="text-xs text-muted-foreground">
              {num(st.markdown_headings)} headings · {num(st.bullet_lines)} bullets ·{" "}
              {num(st.numbered_lines)} numbered · {num(st.blank_line_count)} blank lines
            </dd>
            {trigrams.length ? (
              <>
                <dt className="text-muted-foreground">Repeated phrases</dt>
                <dd className="text-xs">
                  {trigrams.map((t) => `“${t.phrase}” ×${t.count}`).join(" · ")}
                </dd>
              </>
            ) : null}
          </dl>

          <ul className="space-y-1 border-t pt-3 text-xs text-muted-foreground">
            {data.limitations.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Text (original)</CardTitle>
          <CardDescription>
            Stored exactly as submitted{data.truncated ? " — showing the first " : ""}
            {data.truncated ? `${data.excerpt_chars.toLocaleString()} characters.` : "."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <pre className="max-h-96 overflow-auto rounded-lg border bg-muted/40 p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap">
            {data.original_excerpt}
          </pre>
        </CardContent>
      </Card>
    </div>
  );
}
