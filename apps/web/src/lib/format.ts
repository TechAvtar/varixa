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
