"use server";

import type { AnalysisCreatedResponse } from "@verixa/shared-types";
import { IMAGE_UPLOAD } from "@verixa/shared-types";
import { redirect } from "next/navigation";
import { apiUpload } from "@/lib/api/client";
import { getAccessToken } from "@/lib/auth/session";

export interface UploadFormState {
  error?: string;
  requestId?: string;
}

export async function createImageAnalysisAction(
  _: UploadFormState,
  form: FormData,
): Promise<UploadFormState> {
  const file = form.get("file");
  if (!(file instanceof File) || file.size === 0) {
    return { error: "Choose an image to analyse." };
  }
  if (file.size > IMAGE_UPLOAD.maxBytes) {
    return { error: `The file is larger than ${IMAGE_UPLOAD.maxBytes / (1024 * 1024)} MB.` };
  }

  // Forward only the fields the API expects; the API re-validates everything.
  const upstream = new FormData();
  upstream.append("file", file, file.name);
  const title = form.get("title");
  if (typeof title === "string" && title.trim()) upstream.append("title", title.trim());

  const result = await apiUpload<AnalysisCreatedResponse>("/analysis/image", upstream, {
    token: await getAccessToken(),
  });
  if (!result.ok) return { error: result.message, requestId: result.requestId };

  redirect(`/analyses/${result.data.id}`);
}
