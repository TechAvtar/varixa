import type { AnalysisResponse } from "@verixa/shared-types";
import Link from "next/link";
import { AnalysisStatusBadge } from "@/components/analyses/analysis-status-badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatDateTime, formatType } from "@/lib/format";

export function AnalysesTable({ items }: { items: AnalysisResponse[] }) {
  return (
    <div className="rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Title</TableHead>
            <TableHead>Type</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="text-right">Created</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((a) => (
            <TableRow key={a.id}>
              <TableCell className="max-w-[24rem]">
                <Link
                  href={`/analyses/${a.id}`}
                  className="block truncate font-medium underline-offset-4 hover:underline"
                >
                  {a.title ?? "Untitled"}
                </Link>
                {a.status === "failed" && a.error_message ? (
                  <span className="block truncate text-xs text-muted-foreground">
                    {a.error_message}
                  </span>
                ) : null}
              </TableCell>
              <TableCell>{formatType(a.type)}</TableCell>
              <TableCell>
                <AnalysisStatusBadge status={a.status} />
              </TableCell>
              <TableCell className="text-right tabular-nums text-muted-foreground">
                <time dateTime={a.created_at}>{formatDateTime(a.created_at)}</time>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
