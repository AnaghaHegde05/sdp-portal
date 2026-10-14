// Client-side checks that MIRROR the backend's validation for fast feedback. The backend
// (app/services/request_forms.py, app/services/uploads.py) is authoritative and re-checks everything;
// the field/document definitions and the upload limits come from GET /api/request-types.

const PHONE_RE = /^\+?[0-9][0-9 ()-]{6,18}[0-9]$/;

// extension -> accepted leading bytes (same table as the backend: the real type is decided by content)
const SIGNATURES = {
  pdf: [[0x25, 0x50, 0x44, 0x46, 0x2d]],
  jpg: [[0xff, 0xd8, 0xff]],
  jpeg: [[0xff, 0xd8, 0xff]],
  png: [[0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]],
};

export const extOf = (name) => (name.includes(".") ? name.split(".").pop().toLowerCase() : "");

export function isRequired(field, values) {
  if (field.required) return true;
  const c = field.required_if;
  return Boolean(c && values[c.field] === c.equals);
}

// Returns an error message, or "" when the value is acceptable.
export function validateField(field, rawValue, values) {
  const v = typeof rawValue === "string" ? rawValue.trim() : rawValue;
  const empty = v === undefined || v === null || v === "";
  if (empty) return isRequired(field, values) ? `${field.label} is required.` : "";
  switch (field.type) {
    case "tel":
      if (v.length > (field.max_length || 200)) return `${field.label} is too long.`;
      return PHONE_RE.test(v) ? "" : `${field.label} is not a valid phone number.`;
    case "text":
    case "textarea":
      return v.length > (field.max_length || 200) ? `${field.label} is too long.` : "";
    case "number": {
      const n = Number(v);
      if (!Number.isInteger(n)) return `${field.label} must be a whole number.`;
      return n < field.min || n > field.max ? `${field.label} must be between ${field.min} and ${field.max}.` : "";
    }
    case "select":
      return field.options.includes(v) ? "" : `${field.label}: choose one of the listed options.`;
    default:
      return "";
  }
}

export function cleanValues(fields, values) {
  const out = {};
  for (const f of fields) {
    const raw = values[f.name];
    const v = typeof raw === "string" ? raw.trim() : raw;
    if (v === undefined || v === null || v === "") continue;
    out[f.name] = f.type === "number" ? Number(v) : v;
  }
  return out;
}

function readHead(file, n = 8) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(new Uint8Array(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsArrayBuffer(file.slice(0, n));
  });
}

// Checks type (extension), size, emptiness and real content (leading bytes). Returns "" if OK.
export async function validateFile(file, limits) {
  const ext = extOf(file.name);
  if (!limits.allowed_extensions.includes(ext)) {
    return `“${file.name}” is not allowed. Use ${limits.allowed_description}.`;
  }
  if (file.size === 0) return `“${file.name}” is empty.`;
  if (file.size > limits.max_file_mb * 1024 * 1024) {
    return `“${file.name}” is larger than ${limits.max_file_mb} MB.`;
  }
  try {
    const head = await readHead(file);
    const ok = SIGNATURES[ext].some((sig) => sig.every((b, i) => head[i] === b));
    if (!ok) return `“${file.name}” does not look like a real ${ext.toUpperCase()} file (its content does not match its extension).`;
  } catch {
    return `“${file.name}” could not be read.`;
  }
  return "";
}
