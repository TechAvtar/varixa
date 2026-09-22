import Link from "next/link";
import { Button } from "@/components/ui/button";
import { fetchApiHealth } from "@/lib/api";
import { getCurrentUser } from "@/lib/auth/session";

export const dynamic = "force-dynamic";

export default async function Home() {
  const [health, user] = await Promise.all([fetchApiHealth(), getCurrentUser()]);

  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col justify-center gap-8 px-6 py-16">
      <header className="space-y-3">
        <h1 className="text-3xl font-semibold tracking-tight">Verixa</h1>
        <p className="text-muted-foreground">
          Evidence-first content forensics for images and text. Verixa separates what can be
          verified, what the signals suggest, and what remains unknown.
        </p>
        <div className="flex gap-3 pt-2">
          {user ? (
            <Button render={<Link href="/dashboard" />}>Open dashboard</Button>
          ) : (
            <>
              <Button render={<Link href="/login" />}>Sign in</Button>
              <Button variant="outline" render={<Link href="/register" />}>
                Create account
              </Button>
            </>
          )}
        </div>
      </header>

      <section aria-label="API status" className="rounded-lg border bg-card p-4 text-sm">
        <h2 className="mb-2 font-medium">API status</h2>
        {health.ok ? (
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 font-mono text-xs">
            <dt className="text-muted-foreground">status</dt>
            <dd>{health.data.status}</dd>
            <dt className="text-muted-foreground">service</dt>
            <dd>{health.data.service}</dd>
            <dt className="text-muted-foreground">version</dt>
            <dd>{health.data.version}</dd>
            <dt className="text-muted-foreground">environment</dt>
            <dd>{health.data.environment}</dd>
            <dt className="text-muted-foreground">database</dt>
            <dd>{health.data.database}</dd>
          </dl>
        ) : (
          <p className="text-amber-700 dark:text-amber-400">
            Unavailable: {health.error}. Start the API and reload.
          </p>
        )}
      </section>
    </main>
  );
}
