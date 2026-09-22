"use server";

import type { TokenPair, UserResponse } from "@verixa/shared-types";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { apiRequest } from "@/lib/api/client";
import { clearTokenCookies, writeTokenCookies } from "@/lib/auth/cookies";
import { getAccessToken } from "@/lib/auth/session";

export interface AuthFormState {
  error?: string;
  /** Field values to re-populate after a failed submit (never the password). */
  email?: string;
  name?: string;
}

function field(form: FormData, key: string): string {
  const value = form.get(key);
  return typeof value === "string" ? value.trim() : "";
}

function safeNext(form: FormData): string {
  const next = field(form, "next");
  // Only allow same-origin relative paths to avoid open redirects.
  return next.startsWith("/") && !next.startsWith("//") ? next : "/dashboard";
}

export async function loginAction(_: AuthFormState, form: FormData): Promise<AuthFormState> {
  const email = field(form, "email");
  const password = form.get("password");
  if (!email || typeof password !== "string" || !password) {
    return { error: "Enter your email and password.", email };
  }

  const result = await apiRequest<TokenPair>("/auth/login", {
    method: "POST",
    body: { email, password },
  });
  if (!result.ok) return { error: result.message, email };

  writeTokenCookies(await cookies(), result.data);
  redirect(safeNext(form));
}

export async function registerAction(_: AuthFormState, form: FormData): Promise<AuthFormState> {
  const email = field(form, "email");
  const name = field(form, "name");
  const password = form.get("password");
  if (!email || typeof password !== "string" || !password) {
    return { error: "Enter your email and a password.", email, name };
  }

  const created = await apiRequest<UserResponse>("/auth/register", {
    method: "POST",
    body: { email, password, name: name || null },
  });
  if (!created.ok) return { error: created.message, email, name };

  const login = await apiRequest<TokenPair>("/auth/login", {
    method: "POST",
    body: { email, password },
  });
  if (!login.ok) return { error: "Account created. Please sign in.", email, name };

  writeTokenCookies(await cookies(), login.data);
  redirect("/dashboard");
}

export async function logoutAction(): Promise<void> {
  const token = await getAccessToken();
  if (token) {
    // Best effort: revoke the session server-side. Cookies are cleared regardless.
    await apiRequest("/auth/logout", { method: "POST", token });
  }
  clearTokenCookies(await cookies());
  redirect("/login");
}
