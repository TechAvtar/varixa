import Link from "next/link";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/empty-state";

export default function AnalysisNotFound() {
  return (
    <EmptyState
      title="Analysis not found"
      description="It may have been deleted, or the link may belong to another account."
      action={
        <Button variant="outline" nativeButton={false} render={<Link href="/dashboard" />}>
          Back to dashboard
        </Button>
      }
    />
  );
}
