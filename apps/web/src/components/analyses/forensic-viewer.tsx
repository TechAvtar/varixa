"use client";

import type { AnalysisFileLink, ImageForensicsResponse } from "@verixa/shared-types";
import { useId, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

type MapKey = "ela" | "noise" | "copy_move";
type RegionKey = "ela" | "noise" | "copy_move";

const MAP_LABEL: Record<MapKey, string> = {
  ela: "ELA error map",
  noise: "Noise map",
  copy_move: "Copy-move mask",
};

const REGION_LABEL: Record<RegionKey, string> = {
  ela: "ELA regions",
  noise: "Noise regions",
  copy_move: "Copy-move source → target",
};

// Colours are reinforcement only: every box also carries a text label and a legend entry.
const STROKE: Record<RegionKey, string> = {
  ela: "#d97706", // amber-600
  noise: "#2563eb", // blue-600
  copy_move: "#dc2626", // red-600
};

interface Box {
  key: RegionKey;
  x: number;
  y: number;
  w: number;
  h: number;
  label: string;
  dashed?: boolean;
}

interface Arrow {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

function collect(f: ImageForensicsResponse): { boxes: Box[]; arrows: Arrow[] } {
  const boxes: Box[] = [];
  const arrows: Arrow[] = [];
  f.ela?.regions.forEach((r, i) =>
    boxes.push({
      key: "ela",
      x: r.x,
      y: r.y,
      w: r.width,
      h: r.height,
      label: `ELA ${i + 1}`,
    }),
  );
  f.noise?.regions.forEach((r, i) =>
    boxes.push({
      key: "noise",
      x: r.x,
      y: r.y,
      w: r.width,
      h: r.height,
      label: `noise ${i + 1} (${r.sigma > (f.noise?.baseline_sigma ?? 0) ? "noisier" : "smoother"})`,
    }),
  );
  f.copy_move?.matches.forEach((m, i) => {
    boxes.push({
      key: "copy_move",
      x: m.source_x,
      y: m.source_y,
      w: m.width,
      h: m.height,
      label: `clone ${i + 1} source`,
      dashed: true,
    });
    boxes.push({
      key: "copy_move",
      x: m.target_x,
      y: m.target_y,
      w: m.width,
      h: m.height,
      label: `clone ${i + 1} copy`,
    });
    arrows.push({
      x1: m.source_x + m.width / 2,
      y1: m.source_y + m.height / 2,
      x2: m.target_x + m.width / 2,
      y2: m.target_y + m.height / 2,
    });
  });
  return { boxes, arrows };
}

/**
 * Original image with every method's regions drawn over it (original pixel coordinates) and
 * optional blending of the ELA / noise / copy-move maps. Purely presentational: nothing here
 * changes or reinterprets a finding.
 */
export function ForensicViewer({
  data,
  original,
}: {
  data: ImageForensicsResponse;
  original: AnalysisFileLink | null;
}) {
  const id = useId();
  const width = original?.width ?? data.ela?.original_width ?? data.noise?.width ?? 0;
  const height = original?.height ?? data.ela?.original_height ?? data.noise?.height ?? 0;
  const { boxes, arrows } = collect(data);
  const availableMaps = data.artifacts.filter((a): a is typeof a & { method: MapKey } =>
    ["ela", "noise", "copy_move"].includes(a.method),
  );
  const availableRegions = (["ela", "noise", "copy_move"] as RegionKey[]).filter((k) =>
    boxes.some((b) => b.key === k),
  );

  const [map, setMap] = useState<MapKey | "none">("none");
  const [opacity, setOpacity] = useState(0.6);
  const [shown, setShown] = useState<Record<RegionKey, boolean>>({
    ela: true,
    noise: true,
    copy_move: true,
  });

  if (!original || !width || !height) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Viewer</CardTitle>
          <CardDescription>
            The original could not be loaded for this session (link unavailable). Regions are listed
            on each method&apos;s card in original pixel coordinates.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const activeArtifact = map === "none" ? null : availableMaps.find((a) => a.method === map);
  // Maps at a method's working size cover the whole picture; the noise map covers only the
  // whole-block area at native resolution, so it is anchored top-left at its own extent.
  const cover =
    activeArtifact && map === "noise" && data.noise
      ? { w: activeArtifact.width / data.noise.width, h: activeArtifact.height / data.noise.height }
      : { w: 1, h: 1 };
  const fontSize = Math.max(10, Math.round(width / 70));
  const stroke = Math.max(1, Math.round(width / 500));

  return (
    <Card>
      <CardHeader>
        <CardTitle>Viewer</CardTitle>
        <CardDescription>
          Regions from every method drawn over the original, in original pixel coordinates. Blend a
          method&apos;s map to see what it measured. Boxes mark where a heuristic reacted, not where
          an edit is proven.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs">
          <fieldset className="flex flex-wrap items-center gap-3">
            <legend className="sr-only">Regions to show</legend>
            {availableRegions.length === 0 ? (
              <span className="text-muted-foreground">No method reported a region.</span>
            ) : (
              availableRegions.map((k) => (
                <label key={k} className="inline-flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={shown[k]}
                    onChange={(e) => setShown({ ...shown, [k]: e.target.checked })}
                  />
                  <span
                    aria-hidden
                    className="inline-block h-3 w-3 rounded-sm border-2"
                    style={{ borderColor: STROKE[k] }}
                  />
                  {REGION_LABEL[k]}
                </label>
              ))
            )}
          </fieldset>
          {availableMaps.length > 0 ? (
            <div className="flex flex-wrap items-center gap-3">
              <label htmlFor={`${id}-map`} className="inline-flex items-center gap-1.5">
                Blend map
                <select
                  id={`${id}-map`}
                  value={map}
                  onChange={(e) => setMap(e.target.value as MapKey | "none")}
                  className="rounded border bg-background px-1.5 py-0.5"
                >
                  <option value="none">none</option>
                  {availableMaps.map((a) => (
                    <option key={a.method} value={a.method}>
                      {MAP_LABEL[a.method]}
                    </option>
                  ))}
                </select>
              </label>
              <label htmlFor={`${id}-opacity`} className="inline-flex items-center gap-1.5">
                Opacity
                <input
                  id={`${id}-opacity`}
                  type="range"
                  min={0}
                  max={1}
                  step={0.05}
                  value={opacity}
                  disabled={map === "none"}
                  onChange={(e) => setOpacity(Number(e.target.value))}
                />
                <span className="w-8 font-mono tabular-nums">{Math.round(opacity * 100)}%</span>
              </label>
            </div>
          ) : null}
        </div>

        <div
          className="relative mx-auto max-h-[75vh] overflow-hidden rounded border bg-black"
          style={{ aspectRatio: `${width} / ${height}`, maxWidth: "100%" }}
        >
          {/* eslint-disable-next-line @next/next/no-img-element -- signed, short-lived URL; never optimised or cached by the app */}
          <img
            src={original.url}
            alt="Stored original"
            width={width}
            height={height}
            className="block h-full w-full object-contain"
          />
          {activeArtifact ? (
            // eslint-disable-next-line @next/next/no-img-element -- signed, short-lived URL
            <img
              src={activeArtifact.url}
              alt={`${MAP_LABEL[activeArtifact.method]} blended over the original`}
              className="pointer-events-none absolute top-0 left-0"
              style={{
                width: `${cover.w * 100}%`,
                height: `${cover.h * 100}%`,
                opacity,
                mixBlendMode: activeArtifact.method === "copy_move" ? "normal" : "screen",
              }}
            />
          ) : null}
          <svg
            viewBox={`0 0 ${width} ${height}`}
            className="pointer-events-none absolute inset-0 h-full w-full"
            role="img"
            aria-label={`${boxes.filter((b) => shown[b.key]).length} region markers`}
          >
            {arrows.map((a, i) =>
              shown.copy_move ? (
                <line
                  key={`a${i}`}
                  x1={a.x1}
                  y1={a.y1}
                  x2={a.x2}
                  y2={a.y2}
                  stroke={STROKE.copy_move}
                  strokeWidth={stroke}
                  strokeDasharray={`${stroke * 4} ${stroke * 3}`}
                />
              ) : null,
            )}
            {boxes.map((b, i) =>
              shown[b.key] ? (
                <g key={i}>
                  <rect
                    x={b.x}
                    y={b.y}
                    width={b.w}
                    height={b.h}
                    fill="none"
                    stroke={STROKE[b.key]}
                    strokeWidth={stroke}
                    strokeDasharray={b.dashed ? `${stroke * 3} ${stroke * 3}` : undefined}
                  />
                  <text
                    x={b.x + stroke * 2}
                    y={Math.max(fontSize, b.y - stroke * 2)}
                    fontSize={fontSize}
                    fill={STROKE[b.key]}
                    stroke="black"
                    strokeWidth={fontSize / 8}
                    paintOrder="stroke"
                    fontFamily="ui-monospace, monospace"
                  >
                    {b.label}
                  </text>
                </g>
              ) : null,
            )}
          </svg>
        </div>

        <ul className="space-y-1 text-xs text-muted-foreground">
          {boxes.map((b, i) => (
            <li key={i} className="font-mono">
              <span style={{ color: STROKE[b.key] }}>■</span> {b.label}: x {b.x} y {b.y} · {b.w} ×{" "}
              {b.h} px
            </li>
          ))}
          <li>
            Original {width} × {height} px · link expires in{" "}
            {Math.round(original.expires_in_seconds / 60)} min; reload for a fresh one.
          </li>
        </ul>
      </CardContent>
    </Card>
  );
}
