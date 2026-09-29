"""The school-enrollment right: records verification (PRD 3.9).

Creating and listing a youth's enrollments live on the youth-scoped routes; this
module owns the one enrollment-scoped transition.
"""

from flask import Blueprint

import authz
import envelope
import find
import serial
import store

bp = Blueprint("education", __name__)


@bp.post("/ryhs/education-enrollments/<enrollment_id>/verify-records")
def verify_records(enrollment_id):
    authz.require(authz.TLP_COORDINATOR, authz.SHELTER_CASE_MANAGER)
    enrollment = find.enrollment(enrollment_id)
    # "When the receiving school later confirms the youth's records, a staff member
    # records the verification, which moves the enrollment IMMEDIATE_ENROLLMENT ->
    # VERIFIED and stamps verified_at with the clock instant."
    enrollment["status"] = "VERIFIED"
    enrollment["verified_at"] = store.now()
    store.touch(enrollment)
    return envelope.ok(serial.enrollment(enrollment))
