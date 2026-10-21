"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { apiPostJson } from "../../lib/api";
import { setToken } from "../../lib/auth";
import { isValidUsn, normalizeUsn } from "../../lib/usn";
import { Alert, PageHeader } from "../components/ui";

export default function RegisterPage() {
  const router = useRouter();
  const [usn, setUsn] = useState("");
  const [usnError, setUsnError] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function onSubmit(e) {
    e.preventDefault();
    if (busy) return;
    const normalizedUsn = normalizeUsn(usn);
    setUsn(normalizedUsn);
    if (!isValidUsn(normalizedUsn)) {
      setUsnError("Enter a USN in the format 01FE{YY}{BRANCH}{NNN}, using BCS, BEE, BEC, BEV, BCI, or BME.");
      return;
    }
    setUsnError("");
    setError("");
    setBusy(true);
    try {
      const { access_token } = await apiPostJson("/api/auth/register", { usn: normalizedUsn, email, password });
      setToken(access_token);
      router.push("/dashboard");
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <main className="container auth">
      <PageHeader
        title="Create your account"
        subtitle="Link a login to your existing student record using your USN."
      />
      <form className="card" onSubmit={onSubmit}>
        {error && <Alert title="Could not create the account">{error}</Alert>}

        <label htmlFor="usn">University Seat Number (USN)</label>
        <input id="usn" type="text" autoComplete="off" value={usn}
          onChange={(e) => { setUsn(normalizeUsn(e.target.value)); setUsnError(""); }}
          placeholder="e.g. 01FE23BCS064" maxLength={12}
          aria-invalid={Boolean(usnError)} aria-describedby={usnError ? "usn-error" : "usn-hint"} required />
        {usnError ? <p className="field-error" id="usn-error">{usnError}</p> : (
          <p className="hint" id="usn-hint">Format: 01FE + year + branch code + 3 digits. Example: 01FE23BCS064.</p>
        )}

        <label htmlFor="email">Email address</label>
        <input id="email" type="email" autoComplete="email" value={email}
          onChange={(e) => setEmail(e.target.value)} required />

        <label htmlFor="password">Password</label>
        <input id="password" type="password" autoComplete="new-password" value={password}
          onChange={(e) => setPassword(e.target.value)} minLength={8} required />
        <p className="hint">At least 8 characters.</p>

        <div className="callout">
          USN format validation checks only the number&apos;s structure; it does not confirm eligibility or guarantee
          that a matching student record is available. Student records in this prototype are simulated.
        </div>

        <div className="form-actions">
          <button type="submit" className="btn btn-lg" disabled={busy}>
            {busy ? "Creating account…" : "Create account"}
          </button>
        </div>
        <p className="auth-foot">
          Already registered? <Link href="/login">Sign in</Link>
        </p>
      </form>
    </main>
  );
}
