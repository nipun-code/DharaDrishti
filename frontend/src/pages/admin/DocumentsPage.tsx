import { CheckCircle2, CircleAlert, FileText, FileUp, Loader2, RefreshCw, Trash2, UploadCloud } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type FormEvent } from "react";

import { api, describeError } from "../../api/client";
import { useToast } from "../../components/Toasts";
import { ActBadge, EmptyState, Spinner } from "../../components/ui";
import type { ActStatus, ActSummary, DocumentRead, DocumentStatus } from "../../types/api";

const POLL_MS = 2000;
const MAX_MB = 25;

const STATUS_STYLES: Record<DocumentStatus, string> = {
  pending: "bg-navy-100 text-navy-700 dark:bg-navy-800 dark:text-navy-200",
  processing: "bg-saffron-100 text-saffron-700 dark:bg-saffron-500/15 dark:text-saffron-300",
  ready: "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300",
  failed: "bg-red-100 text-red-800 dark:bg-red-500/15 dark:text-red-300",
};

function StatusPill({ status }: { status: DocumentStatus }) {
  const Icon =
    status === "ready" ? CheckCircle2 : status === "failed" ? CircleAlert : status === "processing" ? Loader2 : FileText;
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium capitalize ${STATUS_STYLES[status]}`}>
      <Icon className={`size-3 ${status === "processing" ? "animate-spin" : ""}`} aria-hidden />
      {status}
    </span>
  );
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

// ---------------------------------------------------------------- upload form
function UploadCard({ acts, onUploaded }: { acts: ActSummary[]; onUploaded: () => void }) {
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [year, setYear] = useState("");
  const [status, setStatus] = useState<ActStatus>("in_force");
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const existing = acts.find((a) => a.short_code === code.trim().toUpperCase());
  const isNew = code.trim() !== "" && !existing;
  const fileError =
    file && !file.name.toLowerCase().endsWith(".pdf")
      ? "Only PDF files are accepted."
      : file && file.size > MAX_MB * 1024 * 1024
        ? `The file is larger than ${MAX_MB} MB.`
        : null;
  const canSubmit = file && !fileError && code.trim() && (!isNew || (name.trim() && year)) && !busy;

  const pick = (f: File | undefined) => f && setFile(f);
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    pick(e.dataTransfer.files[0]);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit || !file) return;
    setBusy(true);
    try {
      await api.documents.upload({
        file,
        actShortCode: code.trim().toUpperCase(),
        actFullName: name.trim() || undefined,
        actYear: year ? Number(year) : undefined,
        actStatus: isNew ? status : undefined,
      });
      toast.success(`${file.name} uploaded — ingestion started.`);
      setFile(null);
      if (input.current) input.current.value = "";
      onUploaded();
    } catch (err) {
      toast.error(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="card space-y-4 p-5" aria-labelledby="upload-heading">
      <h2 id="upload-heading" className="flex items-center gap-2 font-serif text-lg font-semibold">
        <FileUp className="size-5 text-saffron-500" aria-hidden /> Upload a bare act
      </h2>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`rounded-xl border-2 border-dashed p-5 text-center transition-colors ${
          dragging
            ? "border-saffron-400 bg-saffron-50 dark:bg-saffron-500/10"
            : "border-navy-200 dark:border-navy-700"
        }`}
      >
        <UploadCloud className="mx-auto size-8 text-navy-400" aria-hidden />
        <p className="mt-2 text-sm">
          {file ? (
            <span className="font-medium">{file.name}</span>
          ) : (
            <>Drag a PDF here, or</>
          )}{" "}
          <label className="cursor-pointer font-medium text-saffron-600 hover:underline dark:text-saffron-400">
            {file ? "choose another" : "browse"}
            <input
              ref={input}
              type="file"
              accept="application/pdf,.pdf"
              className="sr-only"
              onChange={(e) => pick(e.target.files?.[0])}
            />
          </label>
        </p>
        <p className="mt-1 text-xs text-navy-500 dark:text-navy-400">
          {file ? `${(file.size / 1024 / 1024).toFixed(1)} MB` : `PDF with selectable text, up to ${MAX_MB} MB`}
        </p>
        {fileError && <p className="mt-2 text-sm text-red-600 dark:text-red-400">{fileError}</p>}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor="act-code" className="label">
            Act code
          </label>
          <input
            id="act-code"
            list="act-codes"
            value={code}
            onChange={(e) => setCode(e.target.value.toUpperCase())}
            placeholder="BNS"
            className="input uppercase"
            required
            aria-describedby="act-code-hint"
          />
          <datalist id="act-codes">
            {acts.map((a) => (
              <option key={a.short_code} value={a.short_code}>
                {a.full_name}
              </option>
            ))}
          </datalist>
          <p id="act-code-hint" className="mt-1 text-xs text-navy-500 dark:text-navy-400">
            {existing ? `Replaces the current version of ${existing.full_name}.` : isNew ? "New act — add its details." : "e.g. BNS, BNSS, BSA, IPC, ITA"}
          </p>
        </div>
        <div>
          <label htmlFor="act-year" className="label">
            Year {isNew && <span className="text-red-600">*</span>}
          </label>
          <input
            id="act-year"
            type="number"
            min={1800}
            max={2100}
            value={year}
            onChange={(e) => setYear(e.target.value)}
            placeholder={existing ? String(existing.year) : "2023"}
            className="input"
          />
        </div>
        <div className="sm:col-span-2">
          <label htmlFor="act-name" className="label">
            Full name {isNew && <span className="text-red-600">*</span>}
          </label>
          <input
            id="act-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={existing?.full_name ?? "Bharatiya Nyaya Sanhita"}
            className="input"
          />
        </div>
        {isNew && (
          <div className="sm:col-span-2">
            <span className="label">Status</span>
            <div className="flex gap-4 text-sm">
              {(["in_force", "repealed"] as const).map((s) => (
                <label key={s} className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="act-status"
                    checked={status === s}
                    onChange={() => setStatus(s)}
                    className="accent-saffron-500"
                  />
                  {s === "in_force" ? "In force" : "Repealed"}
                </label>
              ))}
            </div>
          </div>
        )}
      </div>

      <button type="submit" disabled={!canSubmit} className="btn-primary w-full">
        {busy ? <Spinner /> : <FileUp className="size-4" aria-hidden />} Upload and ingest
      </button>
    </form>
  );
}

// ---------------------------------------------------------------- page
export function DocumentsPage() {
  const toast = useToast();
  const [docs, setDocs] = useState<DocumentRead[] | null>(null);
  const [acts, setActs] = useState<ActSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [list, actList] = await Promise.all([api.documents.list(), api.catalog.acts()]);
      setDocs(list.items);
      setActs(actList);
      setError(null);
    } catch (err) {
      setError(describeError(err));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Live status: poll while anything is still pending or processing.
  const active = useMemo(() => docs?.some((d) => d.status === "pending" || d.status === "processing") ?? false, [docs]);
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [active, refresh]);

  const remove = async (doc: DocumentRead) => {
    if (!window.confirm(`Delete ${doc.filename} and all its chunks? This cannot be undone.`)) return;
    setDeleting(doc.id);
    try {
      await api.documents.remove(doc.id);
      toast.success(`${doc.filename} deleted.`);
      await refresh();
    } catch (err) {
      toast.error(describeError(err));
    } finally {
      setDeleting(null);
    }
  };

  return (
    <div className="scroll-thin h-full overflow-y-auto">
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6">
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="font-serif text-3xl font-bold">Documents</h1>
            <p className="mt-1 text-navy-600 dark:text-navy-300">
              Upload bare acts and follow their ingestion. Re-uploading an act replaces its previous version.
            </p>
          </div>
          <button type="button" onClick={() => void refresh()} className="btn-ghost">
            <RefreshCw className={`size-4 ${active ? "animate-spin" : ""}`} aria-hidden /> Refresh
          </button>
        </header>

        <div className="mt-6 grid items-start gap-6 lg:grid-cols-[22rem_1fr]">
          <UploadCard acts={acts} onUploaded={() => void refresh()} />

          <section className="card overflow-hidden" aria-labelledby="docs-heading">
            <h2 id="docs-heading" className="sr-only">
              Uploaded documents
            </h2>
            {error && (
              <p role="alert" className="m-4 rounded-lg bg-red-50 p-3 text-sm text-red-800 dark:bg-red-950 dark:text-red-200">
                {error}
              </p>
            )}
            {docs === null && !error && (
              <div className="space-y-3 p-5" aria-label="Loading documents">
                {[0, 1, 2].map((i) => (
                  <div key={i} className="skeleton h-10" />
                ))}
              </div>
            )}
            {docs?.length === 0 && (
              <EmptyState icon={<FileText className="size-5" aria-hidden />} title="No documents yet">
                Upload the English bare-act PDFs (BNS, BNSS, BSA, IPC, IT Act) from India Code to get started.
              </EmptyState>
            )}
            {docs && docs.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[640px] text-left text-sm">
                  <thead className="bg-navy-50 text-xs uppercase tracking-wider text-navy-500 dark:bg-navy-800/60 dark:text-navy-400">
                    <tr>
                      <th scope="col" className="px-4 py-3 font-semibold">Document</th>
                      <th scope="col" className="px-4 py-3 font-semibold">Status</th>
                      <th scope="col" className="px-4 py-3 text-right font-semibold">Pages</th>
                      <th scope="col" className="px-4 py-3 text-right font-semibold">Chunks</th>
                      <th scope="col" className="px-4 py-3 font-semibold">Updated</th>
                      <th scope="col" className="px-4 py-3"><span className="sr-only">Actions</span></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-navy-100 dark:divide-navy-800">
                    {docs.map((doc) => (
                      <tr key={doc.id} className="align-top">
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <ActBadge code={doc.act_short_code} />
                            <span className="max-w-[16rem] truncate font-medium" title={doc.filename}>
                              {doc.filename}
                            </span>
                          </div>
                          {doc.error && <p className="mt-1.5 max-w-md text-xs text-red-700 dark:text-red-300">{doc.error}</p>}
                        </td>
                        <td className="px-4 py-3">
                          <StatusPill status={doc.status} />
                          {(doc.status === "processing" || doc.status === "pending") && (
                            <div className="mt-2 w-32">
                              <div
                                className="h-1.5 overflow-hidden rounded-full bg-navy-100 dark:bg-navy-800"
                                role="progressbar"
                                aria-valuenow={doc.progress}
                                aria-valuemin={0}
                                aria-valuemax={100}
                                aria-label={`${doc.filename} progress`}
                              >
                                <div className="h-full rounded-full bg-saffron-500 transition-all" style={{ width: `${doc.progress}%` }} />
                              </div>
                              <p className="mt-0.5 text-xs text-navy-500">{doc.progress}%</p>
                            </div>
                          )}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums">{doc.pages ?? "—"}</td>
                        <td className="px-4 py-3 text-right tabular-nums">{doc.chunks_count}</td>
                        <td className="whitespace-nowrap px-4 py-3 text-navy-500 dark:text-navy-400">{formatTime(doc.updated_at)}</td>
                        <td className="px-4 py-3 text-right">
                          <button
                            type="button"
                            onClick={() => void remove(doc)}
                            disabled={deleting === doc.id}
                            className="rounded-md p-1.5 text-navy-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-950"
                            aria-label={`Delete ${doc.filename}`}
                          >
                            {deleting === doc.id ? <Spinner /> : <Trash2 className="size-4" aria-hidden />}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
