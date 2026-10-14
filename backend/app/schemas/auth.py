from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.usn import is_valid_usn, normalize_usn


class RegisterRequest(BaseModel):
    usn: str
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("usn")
    @classmethod
    def normalise_usn(cls, v: str) -> str:
        normalized = normalize_usn(v)
        if not is_valid_usn(normalized):
            raise ValueError("USN must match 01FE{YY}{BRANCH}{NNN}.")
        return normalized


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class StudentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    usn: str
    full_name: str
    department: str
    semester: int
    cgpa: float
    backlog_count: int
    fee_status: str


class MeResponse(BaseModel):
    id: int
    email: str
    role: str
    student: StudentOut | None = None
