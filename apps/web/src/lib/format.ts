import type { AnalysisType } from "@verixa/shared-types";

const dateTime = new Intl.DateTimeFormat("en-GB", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "UTC",
});

/** Renders API timestamps in UTC so server and client output never disagree. */
export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : `${dateTime.format(d)} UTC`;
}

export function formatType(type: AnalysisType): string {
  return type === "image" ? "Image" : "Text";
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[i]}`;
}

/**
 * Only plain web links are ever rendered as anchors. Provider-supplied URLs are untrusted data:
 * anything else (javascript:, data:, protocol-relative, malformed) is shown as text instead.
 */
export function safeExternalHref(url: string): string | null {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : null;
  } catch {
    return null;
  }
}
