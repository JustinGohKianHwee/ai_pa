"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);

    const form = new FormData(event.currentTarget);
    const email = String(form.get("email") ?? "");
    const password = String(form.get("password") ?? "");

    try {
      const supabase = createClient();
      const { error: signInError } = await supabase.auth.signInWithPassword({
        email,
        password,
      });
      if (signInError) {
        setError(signInError.message);
        return;
      }
      router.replace("/");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to sign in");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-bg p-6">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm space-y-5 rounded-2xl border border-border bg-surface p-8"
      >
        <div>
          <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-lg bg-accent text-sm font-medium text-accent-fg">
            J
          </div>
          <h1 className="text-2xl font-medium tracking-tight text-fg">Sign in</h1>
          <p className="mt-1 text-sm text-muted">AI Personal Assistant</p>
        </div>

        <label className="block text-sm font-medium text-muted">
          Email
          <input
            name="email"
            type="email"
            autoComplete="email"
            required
            className="mt-1.5 w-full rounded-lg border border-border bg-bg px-3 py-2 text-fg outline-none placeholder:text-faint focus-visible:ring-2 focus-visible:ring-accent"
          />
        </label>
        <label className="block text-sm font-medium text-muted">
          Password
          <input
            name="password"
            type="password"
            autoComplete="current-password"
            required
            className="mt-1.5 w-full rounded-lg border border-border bg-bg px-3 py-2 text-fg outline-none placeholder:text-faint focus-visible:ring-2 focus-visible:ring-accent"
          />
        </label>

        {error ? (
          <p
            role="alert"
            className="rounded-lg border border-border bg-surface-raised px-3 py-2 text-sm text-negative"
          >
            {error}
          </p>
        ) : null}

        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-accent-fg transition-colors hover:bg-accent-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
        >
          {submitting ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
