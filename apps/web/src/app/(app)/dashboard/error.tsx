"use client";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

export default function DashboardError({ reset }: { error: Error; reset: () => void }) {
  return (
    <div className="space-y-4">
      <Alert variant="destructive" role="alert">
        <AlertTitle>The dashboard failed to render</AlertTitle>
        <AlertDescription>
          Something went wrong on our side. Your data is unaffected. Try again, and if it keeps
          happening, sign out and back in.
        </AlertDescription>
      </Alert>
      <Button onClick={reset} variant="outline">
        Try again
      </Button>
    </div>
  );
}
