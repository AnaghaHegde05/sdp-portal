"""Rule-based (deterministic) eligibility checking with three outcomes.

    ELIGIBLE       every automatic check passed - payment may start.
    INELIGIBLE     a VERIFIED policy condition is not met - payment is blocked.
                   (Stored in the database as the existing status NOT_ELIGIBLE so no data or vocabulary changes.)
    MANUAL_REVIEW  eligibility cannot be confirmed automatically (unclear/mismatching documents, or a
                   condition that is not yet verified as university policy) - payment is blocked until
                   a person verifies it. Stored as the status MANUAL_REVIEW.

PRINCIPLES
* No CGPA, backlog or fee-clearance rule exists here. No official KLE Tech policy was found for them,
  so none is invented. (The student's CGPA / backlog / fee fields remain in the database, unused.)
* A rule is only allowed to REJECT (INELIGIBLE) when `verified=True` in POLICY below. A failing rule that
  is marked unverified is downgraded to MANUAL_REVIEW, with that stated in the reason. Today every
  rule that could reject is unverified, so by default NO application is automatically rejected.
* OCR uncertainty (USN not found, no readable text) and document mismatches (a different USN) always
  mean MANUAL_REVIEW - never an academic rejection.
* Which rules apply to which request type, and whether each is verified, is configuration (POLICY).
  Which details/documents each request needs lives in app/core/request_types.py.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy.orm import Session

from app.core.request_types import document_spec, get_request_type
from app.core.statuses import ApplicationStatus
from app.core.usn import normalize_usn
from app.models import Application, Student


class Outcome(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    MANUAL_REVIEW = "MANUAL_REVIEW"


# Outcome -> the status stored on the application. INELIGIBLE reuses the existing NOT_ELIGIBLE value.
STATUS_FOR_OUTCOME = {
    Outcome.ELIGIBLE: ApplicationStatus.ELIGIBLE,
    Outcome.INELIGIBLE: ApplicationStatus.NOT_ELIGIBLE,
    Outcome.MANUAL_REVIEW: ApplicationStatus.MANUAL_REVIEW,
}

UNVERIFIED_NOTE = (
    "This condition is not yet confirmed as university policy, so the application is sent for "
    "verification instead of being rejected."
)


@dataclass(frozen=True)
class RuleConfig:
    code: str  # which implementation below to run
    on_fail: Outcome  # outcome when the rule fails (INELIGIBLE only takes effect if verified)
    verified: bool  # True only once the condition is confirmed against official university policy
    basis: str  # where the rule comes from (shown to maintainers, not students)


# Messages from an implementation: (text, always_verify). always_verify=True means "this is uncertainty,
# send to MANUAL_REVIEW" regardless of the rule's on_fail.
Failure = tuple[str, bool]


def _documents_by_category(app: Application) -> dict[str, object]:
    return {d.document_category: d for d in app.documents if d.document_category}


def _rule_required_documents(app: Application, student: Student) -> list[Failure]:
    spec = get_request_type(app.document_type.code)
    if spec is None:
        return [("This document type has no online requirements configured.", True)]
    have = _documents_by_category(app)
    if not have and app.documents:
        return [("This application was submitted before document slots were recorded, so its files "
                 "cannot be matched to the required documents.", True)]
    missing = [d["label"] for d in spec["documents"] if d["required"] and d["code"] not in have]
    return [(f"Required document not provided: {label}.", False) for label in missing]


def _rule_usn_on_documents(app: Application, student: Student) -> list[Failure]:
    out: list[Failure] = []
    for category, doc in _documents_by_category(app).items():
        spec = document_spec(app.document_type.code, category)
        if not spec or not spec.get("expects_usn"):
            continue
        label = spec["label"]
        r = doc.ocr_result
        if r is None or r.status != "SUCCESS":
            out.append((f"'{label}' has not been read successfully yet.", True))
            continue
        fields = r.extracted_fields or {}
        if not fields.get("word_count"):
            out.append((f"No readable text was found in '{label}'.", True))
            continue
        usns = [normalize_usn(u) for u in fields.get("detected_usns") or []]
        if not usns:
            out.append((f"Your USN could not be found in '{label}'; a person needs to check the document.", True))
        elif normalize_usn(student.usn) not in usns:
            out.append((f"'{label}' shows a USN that differs from the one on your student record "
                        f"({', '.join(usns)}); a person needs to check the document.", True))
    return out


def _rule_pdc_completion_declared(app: Application, student: Student) -> list[Failure]:
    data = app.form_data or {}
    out: list[Failure] = []
    if data.get("final_result_declared") == "No":
        out.append(("You indicated that your final-semester result has not been declared.", False))
    if data.get("all_requirements_completed") == "No":
        out.append(("You indicated that you have not completed all requirements for the degree.", False))
    return out


RULE_IMPLEMENTATIONS = {
    "required_documents": _rule_required_documents,
    "usn_on_documents": _rule_usn_on_documents,
    "pdc_completion_declared": _rule_pdc_completion_declared,
}

# ---- POLICY: edit this to change the rules (no engine change needed) --------------------------------------
_REQUIRED_DOCS = RuleConfig(
    "required_documents", Outcome.INELIGIBLE, verified=False,
    basis="Portal submission requirement; the per-type document lists themselves are provisional (see request_types.py).",
)
_USN_CHECK = RuleConfig(
    "usn_on_documents", Outcome.MANUAL_REVIEW, verified=True,
    basis="Verification of uploaded documents against the student's record; never a rejection.",
)

COMMON_RULES: list[RuleConfig] = [_REQUIRED_DOCS, _USN_CHECK]

RULES_BY_DOCUMENT_TYPE: dict[str, list[RuleConfig]] = {
    "TRANSCRIPT": [],
    "MIGRATION_CERTIFICATE": [],
    "DUPLICATE_GRADE_CARD": [],
    "PROVISIONAL_DEGREE_CERTIFICATE": [
        RuleConfig(
            "pdc_completion_declared", Outcome.INELIGIBLE, verified=False,
            basis="Definition of a provisional degree certificate (degree requirements completed); "
                  "not a confirmed KLE Tech rule. Set verified=True once confirmed to make this reject.",
        ),
    ],
}
# -----------------------------------------------------------------------------------------------------------


@dataclass
class EligibilityOutcome:
    outcome: Outcome
    reasons: list[dict]  # {code, outcome, message, verified}; empty when ELIGIBLE
    checks: list[str]  # codes of every rule that was run

    @property
    def eligible(self) -> bool:
        return self.outcome == Outcome.ELIGIBLE


def evaluate(application: Application, student: Student) -> EligibilityOutcome:
    """Run every rule configured for this application's request type. Never raises."""
    code = application.document_type.code
    rules = COMMON_RULES + RULES_BY_DOCUMENT_TYPE.get(code, [])
    reasons: list[dict] = []
    for rule in rules:
        for message, always_verify in RULE_IMPLEMENTATIONS[rule.code](application, student):
            effective = Outcome.MANUAL_REVIEW if always_verify else rule.on_fail
            if effective == Outcome.INELIGIBLE and not rule.verified:
                effective = Outcome.MANUAL_REVIEW  # never reject on an unverified rule
                message = f"{message} {UNVERIFIED_NOTE}"
            reasons.append(
                {"code": rule.code, "outcome": effective.value, "message": message, "verified": rule.verified}
            )
    if any(r["outcome"] == Outcome.INELIGIBLE for r in reasons):
        outcome = Outcome.INELIGIBLE
    elif reasons:
        outcome = Outcome.MANUAL_REVIEW
    else:
        outcome = Outcome.ELIGIBLE
    return EligibilityOutcome(outcome, reasons, [r.code for r in rules])


def run_eligibility_for_application(
    db: Session, application: Application, student: Student, changed_by: int | None = None
) -> Application:
    """Evaluate, store the structured result, and record the new status via set_status()."""
    result = evaluate(application, student)
    status = STATUS_FOR_OUTCOME[result.outcome]
    if result.outcome == Outcome.ELIGIBLE:
        note = "Eligible: all automatic checks passed."
    elif result.outcome == Outcome.MANUAL_REVIEW:
        note = "Needs verification: " + "; ".join(r["message"] for r in result.reasons)
    else:
        note = "; ".join(r["message"] for r in result.reasons)

    spec = get_request_type(application.document_type.code) or {}
    application.eligibility_result = {
        "outcome": result.outcome.value,
        "reasons": result.reasons,
        "checks": result.checks,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "requirements_verified": bool(spec.get("requirements_verified", False)),
    }

    from app.services.applications import set_status  # local import: avoids a circular import

    set_status(db, application, status, changed_by=changed_by, note=note)
    db.commit()
    db.refresh(application)
    return application


def payment_block_reason(application: Application) -> str | None:
    """None if payment may start/retry; otherwise the reason it may not.

    Payment needs BOTH the right status AND a stored eligibility decision of ELIGIBLE. An older
    application with no stored decision (decided under the former placeholder rules) must be
    re-evaluated first. Ownership is enforced by the caller loading the application per student.
    """
    status = application.status
    if status not in (ApplicationStatus.ELIGIBLE.value, ApplicationStatus.PAYMENT_PENDING.value):
        if status == ApplicationStatus.MANUAL_REVIEW.value:
            return "This application needs verification before payment can be made."
        if status == ApplicationStatus.NOT_ELIGIBLE.value:
            return "This application is not eligible, so payment is not available."
        return (f"Cannot start payment on an application with status '{status}'. "
                "The application must be ELIGIBLE first.")
    result = application.eligibility_result
    if not result or result.get("outcome") != Outcome.ELIGIBLE.value:
        return "This application has no confirmed eligibility decision; it must be re-checked before payment."
    return None
