import { fetchApiHealth } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Home() {
  const health = await fetchApiHealth();

  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col justify-center gap-8 px-6 py-16">
      <header className="space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight">Verixa</h1>
        <p className="text-zinc-600 dark:text-zinc-400">
          Evidence-first content forensics for images and text.
        </p>
      </header>

      <section
        aria-label="API status"
        className="rounded-lg border border-zinc-200 bg-white p-4 text-sm dark:border-zinc-800 dark:bg-zinc-900"
      >
        <h2 className="mb-2 font-medium">API status</h2>
        {health.ok ? (
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 font-mono text-xs">
            <dt className="text-zinc-500">status</dt>
            <dd>{health.data.status}</dd>
            <dt className="text-zinc-500">service</dt>
            <dd>{health.data.service}</dd>
            <dt className="text-zinc-500">version</dt>
            <dd>{health.data.version}</dd>
            <dt className="text-zinc-500">environment</dt>
            <dd>{health.data.environment}</dd>
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
