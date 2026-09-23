import type { ImageMetadataResponse, ParsedTimestamp } from "@verixa/shared-types";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

function Timestamp({ ts }: { ts: ParsedTimestamp | null }) {
  if (!ts) return <>—</>;
  return (
    <span>
      <span className="font-mono">{ts.raw}</span>
      {ts.parsed ? (
        <span className="ml-2 text-xs text-muted-foreground">
          {ts.tz_known ? "timezone recorded" : "timezone not recorded"}
        </span>
      ) : (
        <span className="ml-2 text-xs text-muted-foreground">could not be parsed</span>
      )}
    </span>
  );
}

/** Recorded coordinates with a link the reader may open; the API never fetches map tiles. */
function GpsPosition({
  lat,
  lon,
  altitude,
}: {
  lat: number | null;
  lon: number | null;
  altitude: number | null;
}) {
  if (lat == null || lon == null) return <>—</>;
  const pos = `${lat.toFixed(6)}, ${lon.toFixed(6)}`;
  const href = `https://www.openstreetmap.org/?mlat=${lat.toFixed(6)}&mlon=${lon.toFixed(6)}#map=15/${lat.toFixed(5)}/${lon.toFixed(5)}`;
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <span className="font-mono">{pos}</span>
      {altitude != null ? (
        <span className="text-xs text-muted-foreground">altitude {altitude.toFixed(1)} m</span>
      ) : null}
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-xs underline-offset-4 hover:underline"
      >
        Open in OpenStreetMap
      </a>
    </span>
  );
}

function Presence({ present, label }: { present: boolean; label: string }) {
  return (
    <span
      className={`rounded border px-1.5 py-0.5 text-xs ${
        present ? "border-foreground/30" : "border-dashed text-muted-foreground"
      }`}
    >
      {label}: {present ? "present" : "none"}
    </span>
  );
}

export function MetadataCard({ metadata }: { metadata: ImageMetadataResponse | null }) {
  const n = metadata?.normalized;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Metadata</CardTitle>
        <CardDescription>
          Values recorded inside the file (EXIF/XMP/IPTC/ICC). They are signals written by software
          and can be edited; they are not verified facts.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {!n ? (
          <p className="text-sm text-muted-foreground">
            Metadata has not been extracted for this analysis.
          </p>
        ) : (
          <>
            <div className="flex flex-wrap gap-2">
              <Presence present={n.has_exif} label="EXIF" />
              <Presence present={n.has_xmp} label="XMP" />
              <Presence present={n.has_iptc} label="IPTC" />
              <Presence present={n.has_icc} label="ICC" />
              <Presence present={n.has_makernotes} label="MakerNotes" />
              <Presence present={n.gps_present} label="GPS" />
            </div>

            <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
              <dt className="text-muted-foreground">Camera</dt>
              <dd>{[n.camera_make, n.camera_model].filter(Boolean).join(" ") || "—"}</dd>
              <dt className="text-muted-foreground">Lens</dt>
              <dd>{n.lens ?? "—"}</dd>
              <dt className="text-muted-foreground">Software</dt>
              <dd>{n.software ?? "—"}</dd>
              <dt className="text-muted-foreground">Captured (recorded)</dt>
              <dd>
                <Timestamp ts={n.captured_at} />
              </dd>
              <dt className="text-muted-foreground">Modified (recorded)</dt>
              <dd>
                <Timestamp ts={n.modified_at} />
              </dd>
              {n.gps_present ? (
                <>
                  <dt className="text-muted-foreground">GPS position (recorded)</dt>
                  <dd>
                    <GpsPosition
                      lat={n.gps_latitude}
                      lon={n.gps_longitude}
                      altitude={n.gps_altitude_m}
                    />
                  </dd>
                  <dt className="text-muted-foreground">GPS time (recorded, UTC)</dt>
                  <dd>
                    <Timestamp ts={n.gps_time} />
                  </dd>
                </>
              ) : null}
              <dt className="text-muted-foreground">Orientation</dt>
              <dd>
                {n.orientation_label ?? (n.orientation != null ? String(n.orientation) : "—")}
              </dd>
              <dt className="text-muted-foreground">Colour profile</dt>
              <dd>{n.color_profile ?? "—"}</dd>
              <dt className="text-muted-foreground">Engine</dt>
              <dd className="font-mono text-xs">
                {n.engine} {n.engine_version}
                {Object.keys(n.tag_counts).length > 0 ? (
                  <span className="ml-2 text-muted-foreground">
                    {Object.entries(n.tag_counts)
                      .map(([g, c]) => `${g}: ${c}`)
                      .join(" · ")}
                  </span>
                ) : null}
              </dd>
            </dl>

            {metadata.limitations.length > 0 ? (
              <ul className="space-y-1 border-t pt-3 text-xs text-muted-foreground">
                {metadata.limitations.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
            ) : null}
            {n.warnings.length > 0 ? (
              <details className="text-xs">
                <summary className="cursor-pointer text-muted-foreground">
                  {n.warnings.length} engine warning{n.warnings.length === 1 ? "" : "s"}
                </summary>
                <ul className="mt-1 space-y-1 font-mono">
                  {n.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </details>
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  );
}
