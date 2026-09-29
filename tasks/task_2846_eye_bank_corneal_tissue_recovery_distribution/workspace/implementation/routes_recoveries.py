"""Recovery dispatch, arrival, preservation and abort."""

from flask import Blueprint, request

import auth
import calc
import envelope
import serialize
import store
import validate
from errors import ApiError

bp = Blueprint("recoveries", __name__)

PRESERVATION_MEDIA = ("OPTISOL_GS", "LIFE4C")
LATERALITIES = ("OD", "OS")
RECOVERY_STATUSES = ("DISPATCHED", "ON_SITE", "COMPLETED", "ABORTED")


def _certification_ok(technician):
    return (
        technician["status"] == "ACTIVE"
        and technician["certification_expires_at"] > store.now()
    )


@bp.post("/eye-bank/recoveries")
def create_recovery():
    auth.authenticate(("EyeBankCoordinator",))
    body = auth.body_dict()

    donor = validate.resolve_fk(body, "donor_id", "donors")
    technician = validate.resolve_fk(body, "technician_id", "technicians")

    validate.req_str(body, "donor_id")
    validate.req_str(body, "technician_id")
    dispatched_at = validate.req_dt(body, "dispatched_at")
    planned_release_at = validate.req_dt(body, "planned_release_at")
    if donor is None:
        raise ApiError("ERR_INVALID_REQUEST", "donor_id must reference a donor.")
    if technician is None:
        raise ApiError("ERR_INVALID_REQUEST", "technician_id must reference a technician.")
    if dispatched_at < donor["death_at"]:
        raise ApiError("ERR_INVALID_REQUEST", "dispatched_at must not precede death_at.")
    if planned_release_at <= dispatched_at:
        raise ApiError(
            "ERR_INVALID_REQUEST", "planned_release_at must be strictly after dispatched_at."
        )

    if donor["status"] != "APPROVED_FOR_RECOVERY":
        raise ApiError(
            "ERR_DONOR_STATE_INVALID", "Dispatch requires an APPROVED_FOR_RECOVERY donor."
        )
    if not _certification_ok(technician):
        raise ApiError(
            "ERR_TECHNICIAN_NOT_CERTIFIED", "The technician is inactive or lapsed."
        )

    occupation_end = store.add_minutes(planned_release_at, calc.TURNAROUND_MINUTES)
    if calc.has_dispatch_overlap(technician["id"], dispatched_at, occupation_end):
        raise ApiError(
            "ERR_TECHNICIAN_DISPATCH_OVERLAP",
            "The technician is already occupied over that interval.",
        )

    row = store.base_row()
    row.update(
        {
            "donor_id": donor["id"],
            "technician_id": technician["id"],
            "dispatched_at": dispatched_at,
            "planned_release_at": planned_release_at,
            "arrival_at": None,
            "preservation_at": None,
            "preservation_medium": None,
            "status": "DISPATCHED",
            "abort_reason": None,
            "occupation_end_at": occupation_end,
            "death_to_preservation_minutes": None,
            "time_limit_band": None,
            "recovered_lateralities": [],
        }
    )
    store.DB["recoveries"][row["id"]] = row

    technician["open_dispatch_count"] = technician["open_dispatch_count"] + 1
    store.touch(technician)

    return envelope.ok(serialize.recovery(row), 201)


@bp.get("/eye-bank/recoveries/<recovery_id>")
def get_recovery(recovery_id):
    auth.authenticate(
        (
            "EyeBankCoordinator",
            "MedicalDirector",
            "RecoveryTechnician",
            "EvaluationTechnician",
        )
    )
    row = validate.lookup("recoveries", recovery_id)
    return envelope.ok(serialize.recovery(row))


@bp.get("/eye-bank/recoveries")
def list_recoveries():
    auth.authenticate(("EyeBankCoordinator", "MedicalDirector", "RecoveryTechnician"))
    rows = list(store.DB["recoveries"].values())
    donor_id = request.args.get("donor_id")
    if donor_id is not None:
        rows = [r for r in rows if r["donor_id"] == donor_id]
    technician_id = request.args.get("technician_id")
    if technician_id is not None:
        rows = [r for r in rows if r["technician_id"] == technician_id]
    status = request.args.get("status")
    if status is not None:
        validate.filter_enum("status", status, RECOVERY_STATUSES)
        rows = [r for r in rows if r["status"] == status]
    rows = store.sort_desc(rows, lambda r: r["dispatched_at"])
    return envelope.paginated(rows, serialize.recovery)


def _require_owner(actor, recovery):
    if actor.is_technician and actor.user_id != recovery["technician_id"]:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER", "Only the dispatched technician may act on this recovery."
        )


@bp.post("/eye-bank/recoveries/<recovery_id>/arrive")
def arrive(recovery_id):
    actor = auth.authenticate(("RecoveryTechnician",))
    recovery = validate.lookup("recoveries", recovery_id)
    body = auth.body_dict()
    arrival_at = validate.req_dt(body, "arrival_at")
    if arrival_at < recovery["dispatched_at"]:
        raise ApiError("ERR_INVALID_REQUEST", "arrival_at must not precede dispatched_at.")

    _require_owner(actor, recovery)
    if recovery["status"] != "DISPATCHED":
        raise ApiError("ERR_RECOVERY_STATE_INVALID", "Arrival requires a DISPATCHED recovery.")

    recovery["arrival_at"] = arrival_at
    recovery["status"] = "ON_SITE"
    store.touch(recovery)
    return envelope.ok(serialize.recovery(recovery))


@bp.post("/eye-bank/recoveries/<recovery_id>/complete")
def complete(recovery_id):
    actor = auth.authenticate(("RecoveryTechnician",))
    recovery = validate.lookup("recoveries", recovery_id)
    donor = store.DB["donors"][recovery["donor_id"]]
    body = auth.body_dict()

    preservation_at = validate.req_dt(body, "preservation_at")
    medium = validate.req_enum(body, "preservation_medium", PRESERVATION_MEDIA)
    lateralities = validate.req_str_list(body, "recovered_lateralities", LATERALITIES, 1, 2)
    if recovery["arrival_at"] is not None and preservation_at < recovery["arrival_at"]:
        raise ApiError("ERR_INVALID_REQUEST", "preservation_at must not precede arrival_at.")

    _require_owner(actor, recovery)
    if recovery["status"] != "ON_SITE":
        raise ApiError("ERR_RECOVERY_STATE_INVALID", "Completion requires an ON_SITE recovery.")
    if donor["consent_scope"] == "NONE":
        raise ApiError("ERR_CONSENT_SCOPE_VIOLATION", "The donor has no consent scope.")
    if preservation_at > donor["recovery_deadline_at"]:
        raise ApiError(
            "ERR_PRESERVATION_WINDOW_EXCEEDED",
            "preservation_at is later than the donor's recovery deadline.",
        )

    minutes, band = calc.recovery_time_limit(donor["death_at"], preservation_at)
    recovery["preservation_at"] = preservation_at
    recovery["preservation_medium"] = medium
    recovery["recovered_lateralities"] = list(lateralities)
    recovery["death_to_preservation_minutes"] = minutes
    recovery["time_limit_band"] = band
    recovery["status"] = "COMPLETED"
    calc.refresh_occupation(recovery)
    store.touch(recovery)

    hours = calc.provisional_shelf_life(medium, band)
    for laterality in lateralities:
        tissue = store.base_row()
        tissue.update(
            {
                "recovery_id": recovery["id"],
                "donor_id": donor["id"],
                "laterality": laterality,
                "preservation_medium": medium,
                "preserved_at": preservation_at,
                "shelf_life_hours": hours,
                "shelf_life_variant": "PROVISIONAL_AT_RECOVERY",
                "expires_at": store.add_hours(preservation_at, hours),
                "tissue_quality_score": None,
                "classification": None,
                "disposition_status": "UNGRADED",
                "custody_status": "IN_HOUSE",
                "issue_count": 0,
                "reissue_generation": 0,
                "quarantine_reason": None,
                "disposal_method": None,
            }
        )
        store.DB["tissues"][tissue["id"]] = tissue

    donor["status"] = "RECOVERED"
    donor["tissues_recovered_count"] = len(lateralities)
    store.touch(donor)

    technician = store.DB["technicians"].get(recovery["technician_id"])
    if technician is not None:
        technician["open_dispatch_count"] = max(0, technician["open_dispatch_count"] - 1)
        store.touch(technician)

    return envelope.ok(serialize.recovery(recovery))


@bp.post("/eye-bank/recoveries/<recovery_id>/abort")
def abort(recovery_id):
    actor = auth.authenticate(("RecoveryTechnician", "EyeBankCoordinator"))
    recovery = validate.lookup("recoveries", recovery_id)
    body = auth.body_dict()
    abort_reason = validate.req_str(body, "abort_reason", 1, 500)

    _require_owner(actor, recovery)
    if recovery["status"] not in ("DISPATCHED", "ON_SITE"):
        raise ApiError("ERR_RECOVERY_STATE_INVALID", "Only a live dispatch may be aborted.")

    recovery["abort_reason"] = abort_reason
    recovery["status"] = "ABORTED"
    store.touch(recovery)

    technician = store.DB["technicians"].get(recovery["technician_id"])
    if technician is not None:
        technician["open_dispatch_count"] = max(0, technician["open_dispatch_count"] - 1)
        store.touch(technician)

    return envelope.ok(serialize.recovery(recovery))
