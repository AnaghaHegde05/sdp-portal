"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { apiGet, apiPostFormWithProgress } from "../../lib/api";
import { useRequireAuth } from "../../lib/useRequireAuth";
import { cleanValues, isRequired, validateField, validateFile } from "../../lib/requestForm";
import { formatBytes } from "../../lib/status";
import { Alert, PageHeader, PageLoading } from "../components/ui";

// The form is rendered from GET /api/request-types, so the fields, the required documents and the upload
// limits shown here are exactly what the backend validates. Nothing about them is hard-coded in this file.

function Field({ field, values, error, disabled, onChange }) {
  const id = `f-${field.name}`;
  const required = isRequired(field, values);
  const common = {
    id, name: field.name, value: values[field.name] ?? "", disabled,
    "aria-invalid": Boolean(error), "aria-describedby": error ? `${id}-err` : undefined,
    className: error ? "invalid" : undefined,
    onChange: (e) => onChange(field.name, e.target.value),
  };
  let control;
  if (field.type === "select") {
    control = (
      <select {...common}>
        <option value="">Select…</option>
        {field.options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    );
  } else if (field.type === "textarea") {
    control = <textarea {...common} maxLength={field.max_length} />;
  } else if (field.type === "number") {
    control = <input type="number" inputMode="numeric" step="1" min={field.min} max={field.max} {...common} />;
  } else if (field.type === "tel") {
    control = <input type="tel" autoComplete="tel" {...common} />;
  } else {
    control = <input type="text" maxLength={field.max_length} {...common} />;
  }
  return (
    <div className={`field ${field.type === "textarea" ? "full" : ""}`}>
      <label htmlFor={id}>
        {field.label}
        {required ? <span className="req" aria-hidden="true"> *</span> : <span className="muted small"> (optional)</span>}
      </label>
      {control}
      {field.help && !error && <p className="hint">{field.help}</p>}
      {error && <p className="field-error" id={`${id}-err`}>{error}</p>}
    </div>
  );
}

export default function ApplyPage() {
  const router = useRouter();
  const ready = useRequireAuth();
  const [config, setConfig] = useState(null); // { upload_limits, request_types }
  const [me, setMe] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [typeId, setTypeId] = useState("");
  const [values, setValues] = useState({});
  const [fieldErrors, setFieldErrors] = useState({});
  const [slotFiles, setSlotFiles] = useState({}); // document code -> File
  const [slotErrors, setSlotErrors] = useState({});
  const [submitError, setSubmitError] = useState("");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const submitting = useRef(false);

  useEffect(() => {
    if (!ready) return;
    Promise.all([apiGet("/api/request-types"), apiGet("/api/auth/me", { auth: true })])
      .then(([cfg, meData]) => {
        setConfig(cfg);
        setMe(meData);
        if (cfg.request_types.length) setTypeId(String(cfg.request_types[0].id));
      })
      .catch((err) => setLoadError(err.message));
  }, [ready]);

  function chooseType(id) {
    if (id === typeId) return;
    setTypeId(id);
    setValues({});
    setFieldErrors({});
    setSlotFiles({});
    setSlotErrors({});
    setSubmitError("");
  }

  function setValue(name, value) {
    setValues((v) => ({ ...v, [name]: value }));
    setFieldErrors((e) => ({ ...e, [name]: "" }));
  }

  async function pickFile(doc, file) {
    if (!file) return;
    const message = await validateFile(file, config.upload_limits);
    if (message) {
      setSlotErrors((e) => ({ ...e, [doc.code]: message }));
      return;
    }
    setSlotFiles((f) => ({ ...f, [doc.code]: file }));
    setSlotErrors((e) => ({ ...e, [doc.code]: "" }));
  }

  function removeFile(code) {
    setSlotFiles((f) => {
      const next = { ...f };
      delete next[code];
      return next;
    });
    setSlotErrors((e) => ({ ...e, [code]: "" }));
  }

  async function onSubmit(e) {
    e.preventDefault();
    if (submitting.current) return; // guards against double clicks / double Enter
    const rt = config.request_types.find((t) => String(t.id) === typeId);
    if (!rt) return;

    const fe = {};
    rt.fields.forEach((f) => {
      const m = validateField(f, values[f.name], values);
      if (m) fe[f.name] = m;
    });
    const se = {};
    rt.documents.forEach((d) => {
      if (d.required && !slotFiles[d.code]) se[d.code] = `${d.label} is required.`;
    });
    const attached = rt.documents.filter((d) => slotFiles[d.code]);
    setFieldErrors(fe);
    setSlotErrors((prev) => ({ ...Object.fromEntries(Object.keys(prev).map((k) => [k, ""])), ...se }));
    if (Object.keys(fe).length || Object.keys(se).length) {
      setSubmitError("Please correct the highlighted items and try again.");
      return;
    }
    if (attached.length > config.upload_limits.max_files) {
      setSubmitError(`At most ${config.upload_limits.max_files} files can be uploaded per application.`);
      return;
    }

    submitting.current = true;
    setSubmitError("");
    setBusy(true);
    setProgress(0);
    try {
      const form = new FormData();
      form.append("document_type_id", String(rt.id));
      form.append("form_data", JSON.stringify(cleanValues(rt.fields, values)));
      attached.forEach((d) => {
        form.append("files", slotFiles[d.code]);
        form.append("file_categories", d.code);
      });
      const application = await apiPostFormWithProgress("/api/applications", form, setProgress);
      // Keep the form locked while navigating so the application cannot be submitted twice.
      router.push(`/applications/${application.id}?submitted=1`);
    } catch (err) {
      setSubmitError(err.message);
      submitting.current = false;
      setBusy(false);
    }
  }

  if (!ready || (!config && !loadError)) return <PageLoading label="Loading the application form…" />;
  if (loadError) {
    return (
      <main className="container narrow">
        <Alert title="The application form could not be loaded">{loadError}</Alert>
        <Link href="/dashboard" className="btn btn-secondary">Back to dashboard</Link>
      </main>
    );
  }

  const limits = config.upload_limits;
  const rt = config.request_types.find((t) => String(t.id) === typeId);
  const student = me?.student;
  const uploadDone = busy && progress >= 1;
  const attachedCount = rt ? rt.documents.filter((d) => slotFiles[d.code]).length : 0;

  return (
    <main className="container narrow">
      <Link href="/dashboard" className="back-link">← Back to dashboard</Link>
      <PageHeader
        title="New application"
        subtitle="Choose what you need, fill in the details for that request, and attach the required documents."
      />

      <form onSubmit={onSubmit} noValidate>
        {submitError && <Alert title="Your application was not submitted">{submitError}</Alert>}

        <section className="card">
          <h2 style={{ marginBottom: 12 }}>1. What do you need?</h2>
          <fieldset className="type-grid" disabled={busy}>
            <legend className="sr-only">Request type</legend>
            {config.request_types.map((t) => (
              <label key={t.id} className="type-option">
                <input type="radio" name="document_type" value={t.id}
                  checked={typeId === String(t.id)} onChange={(e) => chooseType(e.target.value)} />
                <span className="box"><strong>{t.name}</strong><span>{t.summary}</span></span>
              </label>
            ))}
          </fieldset>
        </section>

        {rt && (
          <>
            {!rt.requirements_verified && (
              <Alert tone="warning" title="Requirements not yet confirmed">
                The details and documents listed below are a provisional set for this prototype. They have not been
                confirmed against the university&apos;s official notice, so the examination section may ask for more.
              </Alert>
            )}

            <section className="card">
              <h2 style={{ marginBottom: 6 }}>2. Your details</h2>
              {student && (
                <>
                  <p className="muted small">From your student record (read-only):</p>
                  <dl className="applicant-grid">
                    <div><dt>Name</dt><dd>{student.full_name}</dd></div>
                    <div><dt>USN</dt><dd>{student.usn}</dd></div>
                    <div><dt>Department</dt><dd>{student.department}</dd></div>
                    <div><dt>Email</dt><dd>{me.email}</dd></div>
                  </dl>
                </>
              )}
              <div className="form-grid" style={{ marginTop: 8 }}>
                {rt.fields.map((f) => (
                  <Field key={`${rt.code}-${f.name}`} field={f} values={values} error={fieldErrors[f.name]}
                    disabled={busy} onChange={setValue} />
                ))}
              </div>
              <p className="hint" style={{ marginTop: 14 }}><span className="req">*</span> Required</p>
            </section>

            <section className="card">
              <h2 style={{ marginBottom: 6 }}>3. Supporting documents</h2>
              <p className="muted small">
                Attach one file for each document below. Accepted: {limits.allowed_description}, up to {limits.max_file_mb} MB
                each, at most {limits.max_files} files per application. Files are read automatically after you submit, so
                please use clear, legible scans or photos.
              </p>
              {rt.documents.map((d) => {
                const file = slotFiles[d.code];
                const err = slotErrors[d.code];
                return (
                  <div key={`${rt.code}-${d.code}`} className={`slot ${err ? "has-error" : ""}`}>
                    <div className="slot-head">
                      <div>
                        <div className="slot-title">{d.label}</div>
                        {d.help && <div className="muted small">{d.help}</div>}
                      </div>
                      <span className={`badge ${d.required ? "badge-required" : "badge-optional"}`}>
                        {d.required ? "Required" : "Optional"}
                      </span>
                    </div>
                    <div className="slot-file">
                      {file ? (
                        <>
                          <div>
                            <div className="fname" style={{ fontWeight: 600, wordBreak: "break-all" }}>{file.name}</div>
                            <div className="fmeta muted small">{formatBytes(file.size)}</div>
                          </div>
                          <button type="button" className="link-btn" disabled={busy}
                            onClick={() => removeFile(d.code)} aria-label={`Remove ${file.name}`}>
                            Remove
                          </button>
                        </>
                      ) : (
                        <span className="btn btn-secondary btn-sm file-btn">
                          Choose file
                          <input type="file" accept={limits.allowed_extensions.map((x) => `.${x}`).join(",")}
                            aria-label={`Choose file for ${d.label}`} disabled={busy}
                            onChange={(e) => { pickFile(d, e.target.files?.[0]); e.target.value = ""; }} />
                        </span>
                      )}
                    </div>
                    {err && <p className="field-error">{err}</p>}
                  </div>
                );
              })}
              <p className="hint">{attachedCount} of {limits.max_files} files attached.</p>
            </section>

            <section className="card">
              {busy && (
                <div style={{ marginBottom: 14 }} aria-live="polite">
                  <div className="small">
                    {uploadDone ? "Upload complete — saving your application…" : `Uploading… ${Math.round(progress * 100)}%`}
                  </div>
                  <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={100}
                    aria-valuenow={Math.round(progress * 100)}>
                    <div style={{ width: `${Math.round(progress * 100)}%` }} />
                  </div>
                </div>
              )}
              <div className="btn-row">
                <button type="submit" className="btn btn-lg" disabled={busy}>
                  {busy ? "Submitting…" : "Submit application"}
                </button>
                {!busy && <Link href="/dashboard" className="btn btn-secondary btn-lg">Cancel</Link>}
              </div>
              <p className="hint">
                After you submit, your documents are read and your eligibility is checked automatically. If something
                needs a person to verify it, the application page will say so.
              </p>
            </section>
          </>
        )}
      </form>
    </main>
  );
}
