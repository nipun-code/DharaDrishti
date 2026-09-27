import { BookOpenText, Quote, ShieldCheck } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { describeError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { Logo, Spinner } from "../components/ui";

function AuthLayout({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return (
    <div className="grid min-h-dvh lg:grid-cols-[1.1fr_1fr]">
      <aside className="relative hidden overflow-hidden bg-navy-900 p-12 text-white lg:flex lg:flex-col">
        <div
          className="absolute -right-32 -top-32 size-96 rounded-full bg-saffron-500/10 blur-3xl"
          aria-hidden
        />
        <Logo />
        <div className="relative mt-auto max-w-lg">
          <Quote className="size-8 text-saffron-400" aria-hidden />
          <p className="mt-4 font-serif text-3xl leading-snug">
            Answers from the bare acts themselves, with the section behind every sentence.
          </p>
          <ul className="mt-10 space-y-4 text-navy-200">
            <li className="flex gap-3">
              <BookOpenText className="size-5 shrink-0 text-saffron-400" aria-hidden />
              Search BNS, BNSS, BSA, the IT Act and the repealed IPC in plain English.
            </li>
            <li className="flex gap-3">
              <ShieldCheck className="size-5 shrink-0 text-saffron-400" aria-hidden />
              Every claim is cited; if the acts don't say it, DharaDrishti won't either.
            </li>
          </ul>
        </div>
        <p className="relative mt-12 text-xs text-navy-400">
          Legal information, not legal advice. Consult a qualified advocate for your situation.
        </p>
      </aside>

      <section className="flex items-center justify-center px-4 py-12 sm:px-8">
        <div className="w-full max-w-sm">
          <div className="mb-8 lg:hidden">
            <Logo />
          </div>
          <h1 className="font-serif text-3xl font-bold">{title}</h1>
          <p className="mt-2 text-sm text-navy-600 dark:text-navy-300">{subtitle}</p>
          <div className="mt-8">{children}</div>
        </div>
      </section>
    </div>
  );
}

function FormError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-800 dark:bg-red-950 dark:text-red-200">
      {message}
    </p>
  );
}

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      const from = (location.state as { from?: string } | null)?.from;
      navigate(from && from !== "/login" ? from : "/", { replace: true });
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthLayout title="Welcome back" subtitle="Sign in to continue your research.">
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <FormError message={error} />
        <div>
          <label htmlFor="email" className="label">
            Email
          </label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="input"
          />
        </div>
        <div>
          <label htmlFor="password" className="label">
            Password
          </label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="input"
          />
        </div>
        <button type="submit" disabled={busy || !email || !password} className="btn-primary w-full py-2.5">
          {busy && <Spinner />} Sign in
        </button>
      </form>
      <p className="mt-6 text-center text-sm text-navy-600 dark:text-navy-300">
        New here?{" "}
        <Link to="/register" className="font-medium text-saffron-600 hover:underline dark:text-saffron-400">
          Create an account
        </Link>
      </p>
    </AuthLayout>
  );
}

export function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const mismatch = confirm.length > 0 && confirm !== password;
  const tooShort = password.length > 0 && password.length < 8;

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (mismatch || tooShort) return;
    setBusy(true);
    setError(null);
    try {
      await register(email, password);
      navigate("/", { replace: true });
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthLayout title="Create your account" subtitle="Free access to plain-English research on Indian statutes.">
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <FormError message={error} />
        <div>
          <label htmlFor="email" className="label">
            Email
          </label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="input"
          />
        </div>
        <div>
          <label htmlFor="password" className="label">
            Password
          </label>
          <input
            id="password"
            type="password"
            autoComplete="new-password"
            required
            minLength={8}
            aria-describedby="password-hint"
            aria-invalid={tooShort}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="input"
          />
          <p id="password-hint" className={`mt-1 text-xs ${tooShort ? "text-red-600 dark:text-red-400" : "text-navy-500 dark:text-navy-400"}`}>
            At least 8 characters.
          </p>
        </div>
        <div>
          <label htmlFor="confirm" className="label">
            Confirm password
          </label>
          <input
            id="confirm"
            type="password"
            autoComplete="new-password"
            required
            aria-invalid={mismatch}
            aria-describedby={mismatch ? "confirm-error" : undefined}
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            className="input"
          />
          {mismatch && (
            <p id="confirm-error" className="mt-1 text-xs text-red-600 dark:text-red-400">
              Passwords don't match.
            </p>
          )}
        </div>
        <button
          type="submit"
          disabled={busy || !email || !password || !confirm || mismatch || tooShort}
          className="btn-primary w-full py-2.5"
        >
          {busy && <Spinner />} Create account
        </button>
      </form>
      <p className="mt-6 text-center text-sm text-navy-600 dark:text-navy-300">
        Already have an account?{" "}
        <Link to="/login" className="font-medium text-saffron-600 hover:underline dark:text-saffron-400">
          Sign in
        </Link>
      </p>
    </AuthLayout>
  );
}
