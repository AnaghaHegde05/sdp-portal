"""Public description of what each request type asks for (details + documents) and the upload limits.

The student portal renders its forms from this, so the form and the backend validation share one source
(app/core/request_types.py, app/core/config.py).
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.request_types import REQUEST_TYPES
from app.db.session import get_db
from app.models import DocumentType
from app.services.uploads import ALLOWED_DESCRIPTION, allowed_extensions

router = APIRouter(tags=["request-types"])


@router.get("/request-types")
def list_request_types(db: Session = Depends(get_db)):
    rows = db.scalars(select(DocumentType).where(DocumentType.is_active).order_by(DocumentType.id)).all()
    return {
        "upload_limits": {
            "max_files": settings.max_files_per_application,
            "max_file_mb": settings.max_upload_mb,
            "allowed_extensions": allowed_extensions(),
            "allowed_description": ALLOWED_DESCRIPTION,
        },
        "request_types": [
            {"id": r.id, "code": r.code, "name": r.name, **REQUEST_TYPES[r.code]}
            for r in rows
            if r.code in REQUEST_TYPES
        ],
    }
