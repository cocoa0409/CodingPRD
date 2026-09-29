"""PRD 3.3: screening records and the patient-scoped reverse channel."""

from flask import Blueprint

import constants as C
import serializers as S
from auth import acting_user_id, endpoint, require_patient_ownership
from errors import fail
from response import created
from store import bump, db, stamp_new
from validation import q_enum, read_body, v_enum, v_instant, v_string

from .common import paginate, patient_or_404

bp = Blueprint("screening", __name__)

# PRD 3.3: TB_LTBI_TREATMENT_COMPLETE carries COMPLETED and nothing else; every
# other screen type carries one of the three observational results.
TREATMENT_RESULTS = ("COMPLETED",)
OBSERVATIONAL_RESULTS = ("NEGATIVE", "POSITIVE", "INDETERMINATE")


@bp.post("/screening-records")
@endpoint(["InfusionNurse"])
def file_screening_record():
    body = read_body()
    patient_id = v_string(body, "patient_id")
    screen_type = v_enum(body, "screen_type", C.SCREEN_TYPES)
    result = v_enum(body, "result", C.SCREEN_RESULTS)
    collected_at = v_instant(body, "collected_at")
    resulted_at = v_instant(body, "resulted_at")

    permitted = (
        TREATMENT_RESULTS
        if screen_type == "TB_LTBI_TREATMENT_COMPLETE"
        else OBSERVATIONAL_RESULTS
    )
    if result not in permitted:
        fail(
            "ERR_INVALID_REQUEST",
            "Result '%s' is not permitted for screen type '%s'." % (result, screen_type),
        )
    if collected_at > resulted_at:
        fail(
            "ERR_INVALID_REQUEST",
            "Field 'collected_at' must be no later than 'resulted_at'.",
        )

    patient = db.patients.get(patient_id)
    if patient is None:
        fail("ERR_REFERENCE_NOT_FOUND", "The named patient does not exist.")

    row = {
        "patient_id": patient_id,
        "screen_type": screen_type,
        "result": result,
        "collected_at": collected_at,
        "resulted_at": resulted_at,
        # Audit only: never resolved as a foreign key (PRD 3.3).
        "recorded_by_user_id": acting_user_id(),
    }
    stamp_new(row)
    db.screening_records[row["id"]] = row

    # Filing re-derives both postures (they are computed on read) and advances
    # the patient's own revision counter.
    bump(patient)
    return created(S.screening_record_out(row))


@bp.get("/patients/<patient_id>/screening-records")
@endpoint(
    [
        "Rheumatologist",
        "InfusionNurse",
        "PriorAuthCoordinator",
        "RegistryAdmin",
        "Patient",
    ]
)
def list_patient_screening_records(patient_id):
    require_patient_ownership(patient_id)
    patient_or_404(patient_id)
    screen_type = q_enum("screen_type", C.SCREEN_TYPES)
    rows = [
        r
        for r in db.screening_records.values()
        if r["patient_id"] == patient_id
        and (screen_type is None or r["screen_type"] == screen_type)
    ]
    return paginate(rows, S.screening_record_out)
