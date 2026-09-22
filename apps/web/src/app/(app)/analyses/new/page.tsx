import type { Metadata } from "next";
import Link from "next/link";
import { ImageUploadForm } from "@/components/analyses/image-upload-form";
import { TextInputForm } from "@/components/analyses/text-input-form";

export const metadata: Metadata = { title: "New analysis · Verixa" };

const MODES = [
  { key: "image", label: "Analyze image" },
  { key: "text", label: "Analyze text" },
] as const;
type Mode = (typeof MODES)[number]["key"];

export default async function NewAnalysisPage({
  searchParams,
}: {
  searchParams: Promise<{ mode?: string }>;
}) {
  const { mode: raw } = await searchParams;
  const mode: Mode = raw === "text" ? "text" : "image";

  return (
    <div className="mx-auto max-w-2xl space-y-8">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">New analysis</h1>
        <p className="text-sm text-muted-foreground">
          {mode === "image"
            ? "Upload an image to examine its metadata, provenance, fingerprints and, later, forensic signals and sources."
            : "Paste text to measure its structure and statistics and, later, AI-generation signals and source matches."}{" "}
          Everything you submit is stored privately and only you can access it.
        </p>
      </div>

      <nav aria-label="Analysis type" className="border-b">
        <ul role="tablist" className="flex gap-1">
          {MODES.map((m) => {
            const active = m.key === mode;
            return (
              <li key={m.key} role="presentation">
                <Link
                  role="tab"
                  aria-selected={active}
                  href={`/analyses/new?mode=${m.key}`}
                  className={`-mb-px inline-block border-b-2 px-3 py-2 text-sm ${
                    active
                      ? "border-foreground font-medium text-foreground"
                      : "border-transparent text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {m.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      {mode === "image" ? <ImageUploadForm /> : <TextInputForm />}
    </div>
  );
}
