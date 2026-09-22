import type { Metadata } from "next";
import { ImageUploadForm } from "@/components/analyses/image-upload-form";

export const metadata: Metadata = { title: "New analysis · Verixa" };

export default function NewAnalysisPage() {
  return (
    <div className="mx-auto max-w-2xl space-y-8">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">New analysis</h1>
        <p className="text-sm text-muted-foreground">
          Upload an image to examine its metadata, provenance, forensic signals and sources. The
          original is stored privately and only you can access it.
        </p>
      </div>
      <ImageUploadForm />
      <p className="text-xs text-muted-foreground">
        Text analysis is not available in this build yet.
      </p>
    </div>
  );
}
