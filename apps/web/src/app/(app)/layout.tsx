import Link from "next/link";
import { redirect } from "next/navigation";
import { logoutAction } from "@/app/(auth)/actions";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { getSession } from "@/lib/auth/session";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const session = await getSession();
  if (session.kind === "signed_out") redirect("/login");

  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b">
        <div className="mx-auto flex h-14 w-full max-w-6xl items-center justify-between gap-4 px-4">
          <nav className="flex items-center gap-6 text-sm">
            <Link href="/dashboard" className="font-semibold tracking-tight">
              Verixa
            </Link>
            <Link href="/dashboard" className="text-muted-foreground hover:text-foreground">
              Dashboard
            </Link>
            <Link href="/analyses/new" className="text-muted-foreground hover:text-foreground">
              New analysis
            </Link>
          </nav>
          <div className="flex items-center gap-3 text-sm">
            {session.kind === "signed_in" ? (
              <span
                className="hidden truncate text-muted-foreground sm:inline"
                title={session.user.email}
              >
                {session.user.name || session.user.email}
              </span>
            ) : null}
            <form action={logoutAction}>
              <Button type="submit" variant="outline" size="sm">
                Sign out
              </Button>
            </form>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8">
        {session.kind === "unavailable" ? (
          <Alert variant="destructive" role="alert" className="mb-6">
            <AlertTitle>Verixa API unavailable</AlertTitle>
            <AlertDescription>
              {session.message} You are still signed in; data will load once the API is back.
            </AlertDescription>
          </Alert>
        ) : null}
        {children}
      </main>
    </div>
  );
}
