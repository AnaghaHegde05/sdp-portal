"""Per-request-type configuration: the details a student enters and the supporting documents required.

THE ONE PLACE to change what each request asks for. The student portal renders its forms from this
(GET /api/request-types) and the backend validates every submission against it, so the two cannot drift.

VERIFICATION STATUS - READ THIS:
No official KLE Technological University notice listing the required documents, fees or eligibility
conditions for these four requests could be found when this was written. The lists below are a
reasonable PROVISIONAL set (what such requests commonly need) and every request type is therefore
marked `requirements_verified: False`; the portal shows that to students. When the Examination
Section's real list is confirmed, edit the entries and set `requirements_verified` to True.
Nothing here is a CGPA, backlog or fee-clearance rule, and none is used to reject an application.

Field spec keys: name, label, type (text | textarea | tel | number | select), required, options,
max_length, min, max, help, required_if ({"field": ..., "equals": ...}).
Document spec keys: code, label, required, expects_usn (the document normally shows the student's
USN, so OCR may check it), help.
"""

# Sanity bounds for numeric inputs (input validation, not university policy).
_YEAR_MIN, _YEAR_MAX = 1990, 2100

_PHONE = {
    "name": "contact_phone", "label": "Contact phone number", "type": "tel", "required": True,
    "max_length": 20, "help": "Digits only, with an optional leading +. Used only for this request.",
}
_ID_PROOF = {
    "code": "id_proof", "label": "Photo ID proof", "required": True, "expects_usn": False,
    "help": "Any valid government-issued photo ID.",
}

REQUEST_TYPES: dict[str, dict] = {
    "TRANSCRIPT": {
        "summary": "Official record of the courses you took and the grades you earned.",
        "requirements_verified": False,
        "fields": [
            {"name": "year_of_passing", "label": "Year of passing (final examination)", "type": "number",
             "required": True, "min": _YEAR_MIN, "max": _YEAR_MAX},
            {"name": "purpose", "label": "Purpose", "type": "select", "required": True,
             "options": ["Higher studies", "Employment", "Immigration / credential evaluation", "Other"]},
            {"name": "number_of_copies", "label": "Number of copies", "type": "number", "required": True,
             "min": 1, "max": 10, "help": "Between 1 and 10."},
            {"name": "recipient", "label": "Send to (organisation / university), if applicable", "type": "text",
             "required": False, "max_length": 200},
            _PHONE,
        ],
        "documents": [
            {"code": "marks_cards", "label": "Marks cards / consolidated marks memo", "required": True,
             "expects_usn": True, "help": "Clear scan of your semester marks cards or consolidated memo."},
            {"code": "degree_certificate", "label": "Degree or provisional certificate (if already issued)",
             "required": False, "expects_usn": True},
            _ID_PROOF,
        ],
    },
    "MIGRATION_CERTIFICATE": {
        "summary": "Certificate for students moving to another institution or university.",
        "requirements_verified": False,
        "fields": [
            {"name": "year_of_passing", "label": "Year of last examination", "type": "number",
             "required": True, "min": _YEAR_MIN, "max": _YEAR_MAX},
            {"name": "reason", "label": "Reason for migration", "type": "select", "required": True,
             "options": ["Admission to another university", "Employment", "Other"]},
            {"name": "destination_institution", "label": "Institution / university you are moving to",
             "type": "text", "required": False, "max_length": 200,
             "required_if": {"field": "reason", "equals": "Admission to another university"}},
            _PHONE,
        ],
        "documents": [
            {"code": "last_marks_card", "label": "Marks card of your last examination", "required": True,
             "expects_usn": True},
            {"code": "admission_letter", "label": "Admission letter of the new institution (if available)",
             "required": False, "expects_usn": False},
            _ID_PROOF,
        ],
    },
    "DUPLICATE_GRADE_CARD": {
        "summary": "Replacement copy of a grade card that was lost or damaged.",
        "requirements_verified": False,
        "fields": [
            {"name": "semesters", "label": "Semester(s) needed", "type": "text", "required": True,
             "max_length": 100, "help": "For example: 3, 4"},
            {"name": "exam_session", "label": "Examination session", "type": "text", "required": True,
             "max_length": 100, "help": "For example: Dec 2023"},
            {"name": "reason", "label": "Reason for duplicate", "type": "select", "required": True,
             "options": ["Lost", "Damaged", "Other"]},
            {"name": "reason_details", "label": "Details", "type": "textarea", "required": False,
             "max_length": 1000, "required_if": {"field": "reason", "equals": "Other"}},
            _PHONE,
        ],
        "documents": [
            {"code": "loss_declaration", "label": "Signed declaration of loss or damage", "required": True,
             "expects_usn": False, "help": "A short signed statement on plain paper."},
            {"code": "card_copy", "label": "Photocopy of the original grade card (if available)",
             "required": False, "expects_usn": True},
            _ID_PROOF,
        ],
    },
    "PROVISIONAL_DEGREE_CERTIFICATE": {
        "summary": "Interim proof of degree completion, issued before the final degree certificate.",
        "requirements_verified": False,
        "fields": [
            {"name": "year_of_passing", "label": "Year of passing (final examination)", "type": "number",
             "required": True, "min": _YEAR_MIN, "max": _YEAR_MAX},
            {"name": "final_result_declared", "label": "Has your final-semester result been declared?",
             "type": "select", "required": True, "options": ["Yes", "No"]},
            {"name": "all_requirements_completed", "label": "Have you completed all requirements for the degree?",
             "type": "select", "required": True, "options": ["Yes", "No"]},
            {"name": "purpose", "label": "Purpose (optional)", "type": "text", "required": False, "max_length": 200},
            _PHONE,
        ],
        "documents": [
            {"code": "final_marks_card", "label": "Final-semester marks card or consolidated marks memo",
             "required": True, "expects_usn": True},
            _ID_PROOF,
        ],
    },
}

TEXT_MAX_DEFAULT = 200


def get_request_type(code: str) -> dict | None:
    return REQUEST_TYPES.get(code)


def document_spec(code: str, category: str) -> dict | None:
    rt = REQUEST_TYPES.get(code)
    return next((d for d in rt["documents"] if d["code"] == category), None) if rt else None
