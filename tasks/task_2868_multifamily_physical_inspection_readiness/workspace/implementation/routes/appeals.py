"""Appeals against a scored inspection, and the appeal-grant cascade
(PRD 3.7)."""

from flask import Blueprint

import auth
import calc
import derive
import envelope
import shapes
import store
from errors import ApiError
from routes import common

bp = Blueprint("appeals", __name__)

NON_TERMINAL = ("SUBMITTED", "RETURNED_FOR_INFO")


def _pending_remains(inspection_id, ignore_appeal_id=None):
    for row in derive.inspection_appeals(inspection_id):
        if ignore_appeal_id is not None and row["id"] == ignore_appeal_id:
            continue
        if row["status"] in NON_TERMINAL:
            return True
    return False


def _rescore(insp, decided_at):
    """Appeal-grant cascade links 3 and 4: recompute the sums, both score
    variants and the property posture."""
    derive.recompute_inspection_sums(insp)
    provisional, final = derive.compute_inspection_scores(insp)
    insp["provisional_score"] = provisional
    insp["final_score"] = final
    insp["rescored_at"] = decided_at


@bp.post("/appeals")
def file_appeal():
    user_id, role = auth.authenticate([auth.OWNER])
    values = shapes.validate(
        [
            shapes.F("inspection_id", "string"),
            shapes.F("appeal_type", "enum", values=shapes.APPEAL_TYPE),
            shapes.F("rationale", "string"),
            shapes.F("filed_at", "datetime"),
            shapes.F("contested_deficiency_id", "string", required=False),
            shapes.F("requested_point_adjustment", "number", required=False),
        ]
    )
    insp = common.body_fetch("inspection", values["inspection_id"])
    contested = None
    if values.get("contested_deficiency_id"):
        contested = common.body_fetch("deficiency", values["contested_deficiency_id"])
    auth.require_owner(role, user_id, insp["property_id"])
    if insp["status"] != "SCORED":
        raise ApiError(
            "ERR_INSPECTION_INVALID_STATE",
            "Only a SCORED inspection may be appealed.",
        )

    adjustment_supplied = values.get("requested_point_adjustment") is not None
    targeting_ok = (
        contested is not None
        and contested.get("inspection_id") == insp["id"]
        and contested["status"] != "VOIDED"
        and adjustment_supplied == (values["appeal_type"] == "SCORE_CORRECTION")
    )
    if not targeting_ok:
        raise ApiError(
            "ERR_DEFICIENCY_NOT_IN_INSPECTION",
            "The contested deficiency or the requested adjustment does not satisfy "
            "the appeal-targeting rule.",
        )
    filed = shapes.instant(values, "filed_at")
    deadline = store.parse_instant(insp.get("appeal_deadline_at"))
    if deadline is not None and filed > deadline:
        raise ApiError(
            "ERR_APPEAL_WINDOW_CLOSED",
            "The appeal window of this inspection has already closed.",
        )

    row = {
        "inspection_id": insp["id"],
        "contested_deficiency_id": contested["id"],
        "appeal_type": values["appeal_type"],
        "status": "SUBMITTED",
        "rationale": values["rationale"],
        "filed_at": values["filed_at"],
        "requested_point_adjustment": values.get("requested_point_adjustment"),
        "granted_point_adjustment": None,
        "decided_at": None,
        "resubmission_count": 0,
        "additional_evidence": None,
        "reviewer_note": None,
    }
    store.stamp_new(row)
    store.appeals[row["id"]] = row
    insp["status"] = "APPEALED"
    store.touch(insp, bump_version=True)
    return envelope.created(row)


@bp.get("/appeals/<appeal_id>")
def read_appeal(appeal_id):
    user_id, role = auth.authenticate(auth.ANY_ROLE)
    appeal = common.fetch("appeal", appeal_id)
    auth.require_owner(role, user_id, auth.property_of_appeal(appeal))
    return envelope.ok(appeal)


@bp.get("/appeals")
def list_appeals():
    user_id, role = auth.authenticate(auth.ANY_ROLE)
    return common.listing(
        store.appeals.values(),
        ["inspection_id", "contested_deficiency_id", "appeal_type", "status"],
        role=role,
        user_id=user_id,
        property_getter=auth.property_of_appeal,
    )


@bp.post("/appeals/<appeal_id>/review")
def review_appeal(appeal_id):
    auth.authenticate([auth.APPEALS])
    values = shapes.validate(
        [
            shapes.F("decision", "enum", values=shapes.APPEAL_DECISION),
            shapes.F("decided_at", "datetime"),
            shapes.F("reviewer_note", "string", required=False),
            shapes.F("granted_point_adjustment", "number", required=False),
        ]
    )
    appeal = common.fetch("appeal", appeal_id)
    decision = values["decision"]
    if appeal["status"] in ("GRANTED", "DENIED"):
        raise ApiError(
            "ERR_APPEAL_INVALID_STATE",
            "A GRANTED or DENIED appeal is terminal.",
        )
    if decision == "RETURNED_FOR_INFO" and appeal["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_APPEAL_INVALID_STATE",
            "Only a SUBMITTED appeal may be returned for more information.",
        )

    insp = store.inspections.get(appeal["inspection_id"])
    contested = store.deficiencies.get(appeal["contested_deficiency_id"])

    if decision == "GRANTED":
        adjustment = None
        if appeal["appeal_type"] == "SCORE_CORRECTION":
            if values.get("granted_point_adjustment") is None:
                raise ApiError(
                    "ERR_ADJUSTMENT_REQUIRED",
                    "Granting a score-correction appeal requires "
                    "granted_point_adjustment.",
                )
            adjustment = calc.r2(values["granted_point_adjustment"])
            current = calc.d(contested["points_deducted"])
            if adjustment <= calc.d("0.00") or adjustment > current:
                raise ApiError(
                    "ERR_ADJUSTMENT_EXCEEDS_POINTS",
                    "granted_point_adjustment must exceed 0.00 and may not exceed "
                    "the contested deficiency's points_deducted.",
                )
        appeal["status"] = "GRANTED"
        appeal["decided_at"] = values["decided_at"]
        appeal["reviewer_note"] = values.get("reviewer_note")
        if adjustment is not None:
            appeal["granted_point_adjustment"] = adjustment
        store.touch(appeal, bump_version=True)

        if appeal["appeal_type"] == "TECHNICAL_ERROR":
            contested["status"] = "VOIDED"
            contested["points_deducted"] = calc.d("0.00")
        else:
            reduced = calc.d(contested["points_deducted"]) - adjustment
            if reduced < calc.d("0.00"):
                reduced = calc.d("0.00")
            contested["points_deducted"] = calc.r2(reduced)
        store.touch(contested, bump_version=True)

        if contested.get("unit_id"):
            unit = store.units.get(contested["unit_id"])
            if unit is not None:
                derive.recompute_unit_open_count(unit)

        _rescore(insp, values["decided_at"])
        if not _pending_remains(insp["id"]):
            insp["status"] = "SCORED"
        store.touch(insp, bump_version=True)
        prop = store.properties.get(insp["property_id"])
        if prop is not None:
            derive.rederive_property(prop, bump_version=True)
        return envelope.ok(appeal)

    if decision == "DENIED":
        appeal["status"] = "DENIED"
        appeal["decided_at"] = values["decided_at"]
        appeal["reviewer_note"] = values.get("reviewer_note")
        store.touch(appeal, bump_version=True)
        if insp is not None and not _pending_remains(insp["id"]):
            insp["status"] = "SCORED"
            store.touch(insp, bump_version=True)
        return envelope.ok(appeal)

    appeal["status"] = "RETURNED_FOR_INFO"
    appeal["decided_at"] = values["decided_at"]
    appeal["reviewer_note"] = values.get("reviewer_note")
    store.touch(appeal, bump_version=True)
    return envelope.ok(appeal)


@bp.post("/appeals/<appeal_id>/resubmit")
def resubmit_appeal(appeal_id):
    user_id, role = auth.authenticate([auth.OWNER])
    values = shapes.validate([shapes.F("additional_evidence", "string")])
    appeal = common.fetch("appeal", appeal_id)
    auth.require_owner(role, user_id, auth.property_of_appeal(appeal))
    if appeal["status"] != "RETURNED_FOR_INFO":
        raise ApiError(
            "ERR_APPEAL_INVALID_STATE",
            "Only an appeal RETURNED_FOR_INFO may be resubmitted.",
        )
    if appeal["resubmission_count"] >= calc.APPEAL_RESUBMIT_LIMIT:
        raise ApiError(
            "ERR_APPEAL_RESUBMIT_LIMIT",
            "This appeal has already been resubmitted the maximum number of times.",
        )
    appeal["status"] = "SUBMITTED"
    appeal["additional_evidence"] = values["additional_evidence"]
    appeal["resubmission_count"] = appeal["resubmission_count"] + 1
    appeal["decided_at"] = None
    store.touch(appeal, bump_version=True)
    return envelope.ok(appeal)
