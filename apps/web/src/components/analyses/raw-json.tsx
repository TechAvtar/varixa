/** Collapsible raw data viewer. Closed by default so raw dumps never dominate a report. */
export function RawJson({ title, data }: { title: string; data: unknown }) {
  const text = JSON.stringify(data ?? null, null, 2);
  const empty = data == null || (typeof data === "object" && Object.keys(data).length === 0);
  return (
    <details className="rounded-lg border">
      <summary className="cursor-pointer px-3 py-2 text-sm font-medium">
        {title}
        {empty ? <span className="ml-2 text-xs text-muted-foreground">(empty)</span> : null}
      </summary>
      <pre className="max-h-96 overflow-auto border-t bg-muted/40 p-3 font-mono text-xs leading-relaxed">
        {text}
      </pre>
    </details>
  );
}
