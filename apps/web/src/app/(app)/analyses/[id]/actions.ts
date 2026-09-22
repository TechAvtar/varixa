"use server";

import type { ReportResponse } from "@verixa/shared-types";
import { redirect } from "next/navigation";
import { authedRequest } from "@/lib/auth/session";

/** Keep or release the raw content under the retention policy, then return to the report. */
export async function setKeep(analysisId: string, keep: boolean): Promise<void> {
  await authedRequest<unknown>(`/analysis/${analysisId}/keep`, {
    method: keep ? "POST" : "DELETE",
  });
  redirect(`/analyses/${analysisId}?tab=overview`);
}

/** Soft-delete the analysis (the API sweeps its stored content) and return to the dashboard. */
export async function deleteAnalysis(analysisId: string): Promise<void> {
  const result = await authedRequest<unknown>(`/analysis/${analysisId}`, { method: "DELETE" });
  if (!result.ok) {
    const params = new URLSearchParams({ tab: "overview", message: result.message.slice(0, 200) });
    redirect(`/analyses/${analysisId}?${params.toString()}`);
  }
  redirect("/dashboard?deleted=1");
}

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
