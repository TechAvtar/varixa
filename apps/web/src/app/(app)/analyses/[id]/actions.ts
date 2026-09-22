"use server";

import type { ReportResponse } from "@verixa/shared-types";
import { redirect } from "next/navigation";
import { authedRequest } from "@/lib/auth/session";

/** Ask the API to render a report, then return to the overview with the outcome in the URL. */
export async function createReport(analysisId: string, formData: FormData): Promise<void> {
  const format = String(formData.get("format") ?? "pdf");
  const result = await authedRequest<ReportResponse>(`/analysis/${analysisId}/report`, {
    method: "POST",
    body: { format },
  });
  const params = new URLSearchParams({ tab: "overview" });
  if (result.ok) {
    params.set("report", result.data.status === "completed" ? "ready" : "failed");
  } else {
    params.set("report", "error");
    params.set("message", result.message.slice(0, 200));
  }
  redirect(`/analyses/${analysisId}?${params.toString()}`);
}
