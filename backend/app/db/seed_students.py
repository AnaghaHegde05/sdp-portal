"""Load SIMULATED student records for development and testing.

These are NOT real KLE Tech students: the USNs, names and academic values are invented. The
values are varied on purpose (CGPA, backlogs, fee dues) so later phases (eligibility rules,
risk scoring) have different situations to work with. A larger simulated dataset for the ML
components is built in Phase 4.

Usage (from the backend/ folder):  python -m app.db.seed_students   (safe to re-run)
"""
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import Student

CSE = "Computer Science and Engineering"
ECE = "Electronics and Communication Engineering"
EEE = "Electrical and Electronics Engineering"
MEC = "Mechanical Engineering"
CIV = "Civil Engineering"

# (usn, full_name, department, semester, cgpa, backlog_count, fee_status)
SIMULATED_STUDENTS = [
    ("01FE23CSE001", "Sim Student 01", CSE, 7, "8.90", 0, "CLEAR"),
    ("01FE23CSE002", "Sim Student 02", CSE, 7, "7.45", 1, "CLEAR"),
    ("01FE23CSE003", "Sim Student 03", CSE, 8, "9.30", 0, "CLEAR"),
    ("01FE23CSE004", "Sim Student 04", CSE, 7, "6.10", 3, "DUE"),
    ("01FE23ECE001", "Sim Student 05", ECE, 7, "8.05", 0, "CLEAR"),
    ("01FE23ECE002", "Sim Student 06", ECE, 8, "7.20", 2, "CLEAR"),
    ("01FE23EEE001", "Sim Student 07", EEE, 7, "8.60", 0, "DUE"),
    ("01FE23EEE002", "Sim Student 08", EEE, 5, "7.80", 0, "CLEAR"),
    ("01FE23MEC001", "Sim Student 09", MEC, 8, "6.85", 1, "CLEAR"),
    ("01FE23MEC002", "Sim Student 10", MEC, 7, "9.10", 0, "CLEAR"),
    ("01FE23CIV001", "Sim Student 11", CIV, 8, "7.05", 0, "CLEAR"),
    ("01FE23CIV002", "Sim Student 12", CIV, 6, "5.90", 4, "DUE"),
]

LEGACY_USNS = {
    "SIM23CSE001": "01FE23CSE001",
    "SIM23CSE002": "01FE23CSE002",
    "SIM23CSE003": "01FE23CSE003",
    "SIM23CSE004": "01FE23CSE004",
    "SIM23ECE001": "01FE23ECE001",
    "SIM23ECE002": "01FE23ECE002",
    "SIM23EEE001": "01FE23EEE001",
    "SIM23EEE002": "01FE23EEE002",
    "SIM23MEC001": "01FE23MEC001",
    "SIM23MEC002": "01FE23MEC002",
    "SIM23CIV001": "01FE23CIV001",
    "SIM23CIV002": "01FE23CIV002",
}


def seed_students(db: Session) -> int:
    """Insert missing students and migrate matching legacy seed IDs. Returns how many were added."""
    existing = set(db.scalars(select(Student.usn)).all())
    added = 0
    for usn, name, dept, sem, cgpa, backlogs, fee in SIMULATED_STUDENTS:
        if usn not in existing:
            legacy_usn = next((old for old, current in LEGACY_USNS.items() if current == usn and old in existing), None)
            if legacy_usn is not None:
                student = db.scalar(select(Student).where(Student.usn == legacy_usn))
                student.usn = usn
                existing.remove(legacy_usn)
            else:
                db.add(
                    Student(
                        usn=usn, full_name=name, department=dept, semester=sem,
                        cgpa=Decimal(cgpa), backlog_count=backlogs, fee_status=fee,
                    )
                )
                added += 1
            existing.add(usn)
    db.commit()
    return added


if __name__ == "__main__":
    with SessionLocal() as session:
        added = seed_students(session)
    print(f"Simulated students: {added} added ({len(SIMULATED_STUDENTS)} defined).")
