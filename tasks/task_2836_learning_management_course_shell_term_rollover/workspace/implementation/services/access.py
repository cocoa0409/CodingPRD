"""Ownership (PRD 2.1) and the post-term student access gate (PRD 3.1)."""

from db import db, now
from errors import require
from middleware import INSTRUCTOR, STUDENT, actor, role


def own_shell(shell):
    """An Instructor acting on a shell whose owner_person_id differs from their
    X-User-ID is rejected."""
    if role() != INSTRUCTOR or shell is None:
        return
    require(shell["owner_person_id"] == actor(), "ERR_NOT_RESOURCE_OWNER",
            "The acting instructor does not own this shell.")


def own_enrollment(enrollment):
    if role() != STUDENT or enrollment is None:
        return
    require(enrollment["person_id"] == actor(), "ERR_NOT_RESOURCE_OWNER",
            "The acting student does not own this enrollment.")


def student_gate(term):
    """A student read or dispute filing must happen at or before the term's
    student_access_end_at, with the acting person's access_revoked_at null or
    still in the future."""
    if role() != STUDENT:
        return
    moment = now()
    if term is not None and term.get("student_access_end_at") is not None:
        require(moment <= term["student_access_end_at"],
                "ERR_STUDENT_ACCESS_EXPIRED",
                "Post-term student access for this term has ended.")
    person = db.people.get(actor())
    if person is not None and person.get("access_revoked_at") is not None:
        require(moment < person["access_revoked_at"],
                "ERR_STUDENT_ACCESS_EXPIRED",
                "The acting person's LMS access has been withdrawn.")
