"""Inspection scheduling, sampling, scoring and finalization (PRD 3.4-3.8)."""

from flask import Blueprint

import auth
import calc
import derive
import envelope
import shapes
import store
from errors import ApiError
from routes import common

bp = Blueprint("inspections", __name__)

LIVE_INSPECTION_EXCLUDED = ("CANCELLED", "CLOSED")


def window_conflict(property_id, start, end, exclude_inspection_id=None):
    """Closed-interval intersection after a 72-hour cooldown expansion."""
    buffer_hours = calc.hours(calc.INSPECTION_COOLDOWN_BUFFER_HOURS)
    a_start = start - buffer_hours
    a_end = end + buffer_hours
    for row in store.inspections.values():
        if row["property_id"] != property_id:
            continue
        if exclude_inspection_id is not None and row["id"] == exclude_inspection_id:
            continue
        if row["status"] in LIVE_INSPECTION_EXCLUDED:
            continue
        b_start = store.parse_instant(row["scheduled_start"]) - buffer_hours
        b_end = store.parse_instant(row["scheduled_end"]) + buffer_hours
        if calc.closed_intervals_conflict(a_start, a_end, b_start, b_end):
            return True
    return False


def new_inspection_row(property_id, standard_id, scheduled_start, scheduled_end, kind):
    row = {
        "property_id": property_id,
        "standard_id": standard_id,
        "inspection_kind": kind,
        "status": "SCHEDULED",
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "drawn_at": None,
        "started_at": None,
        "scored_at": None,
        "rescored_at": None,
        "finalized_at": None,
        "sample_tier_value": 0,
        "sample_size": 0,
        "inspected_unit_count": 0,
        "refused_unit_count": 0,
        "unit_area_points": calc.d("0.00"),
        "inside_area_points": calc.d("0.00"),
        "outside_area_points": calc.d("0.00"),
        "total_points_deducted": calc.d("0.00"),
        "life_threatening_count": 0,
        "provisional_score": None,
        "final_score": None,
        "appeal_deadline_at": None,
        "cap_required": False,
        "cap_window_days": None,
        "cap_due_at": None,
        "followup_due_at": None,
    }
    store.stamp_new(row)
    store.inspections[row["id"]] = row
    return row


@bp.post("/inspections")
def schedule_inspection():
    auth.authenticate([auth.INSPECTOR])
    values = shapes.validate(
        [
            shapes.F("property_id", "string"),
            shapes.F("standard_id", "string"),
            shapes.F("scheduled_start", "datetime"),
            shapes.F("scheduled_end", "datetime"),
            shapes.F(
                "inspection_kind", "enum", required=False, values=shapes.INSPECTION_KIND
            ),
        ]
    )
    prop = common.body_fetch("property", values["property_id"])
    standard = common.body_fetch("standard", values["standard_id"])
    if standard["adoption_status"] != "ADOPTED":
        raise ApiError(
            "ERR_STANDARD_NOT_ADOPTED", "The cited standard is not ADOPTED."
        )
    start = shapes.instant(values, "scheduled_start")
    end = shapes.instant(values, "scheduled_end")
    if end <= start:
        raise ApiError(
            "ERR_INVALID_TIME_WINDOW",
            "scheduled_end must be strictly after scheduled_start.",
        )
    if window_conflict(prop["id"], start, end):
        raise ApiError(
            "ERR_INSPECTION_WINDOW_CONFLICT",
            "The requested window conflicts with another live inspection window.",
        )
    row = new_inspection_row(
        prop["id"],
        standard["id"],
        values["scheduled_start"],
        values["scheduled_end"],
        values.get("inspection_kind") or "INITIAL",
    )
    return envelope.created(row)


@bp.get("/inspections/<inspection_id>")
def read_inspection(inspection_id):
    user_id, role = auth.authenticate(auth.ANY_ROLE)
    insp = common.fetch("inspection", inspection_id)
    auth.require_owner(role, user_id, insp["property_id"])
    return envelope.ok(insp)


@bp.get("/inspections")
def list_inspections():
    user_id, role = auth.authenticate(auth.ANY_ROLE)
    return common.listing(
        store.inspections.values(),
        ["property_id", "standard_id", "status", "inspection_kind"],
        role=role,
        user_id=user_id,
        property_getter=lambda r: r["property_id"],
    )


@bp.post("/inspections/<inspection_id>/draw-sample")
def draw_sample(inspection_id):
    auth.authenticate([auth.INSPECTOR])
    values = shapes.validate([shapes.F("drawn_at", "datetime")])
    insp = common.fetch("inspection", inspection_id)
    if insp["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_INSPECTION_INVALID_STATE",
            "The unit sample may only be drawn from a SCHEDULED inspection.",
        )
    prop = store.properties.get(insp["property_id"])
    if prop is not None and prop["readiness_posture"] == "FROZEN":
        raise ApiError("ERR_PROPERTY_FROZEN", "The property's readiness posture is FROZEN.")
    candidates = derive.eligible_candidates(insp)
    if not candidates:
        raise ApiError(
            "ERR_NO_ELIGIBLE_UNITS", "No eligible unit remains for this inspection."
        )
    tier_value = calc.sample_tier_value(prop["total_unit_count"])
    sample_size = min(tier_value, len(candidates))
    rank = 1
    for unit in candidates[:sample_size]:
        slot = {
            "inspection_id": insp["id"],
            "unit_id": unit["id"],
            "replaced_selection_id": None,
            "selection_rank": rank,
            "selection_basis": "SAMPLED",
            "selection_status": "ACTIVE",
            "access_status": "NOT_NOTIFIED",
            "notice_method": None,
            "notified_at": None,
            "access_window_start": None,
            "access_window_end": None,
            "notice_lead_hours": None,
            "access_recorded_at": None,
            "refusal_reason": None,
        }
        store.stamp_new(slot)
        store.selections[slot["id"]] = slot
        rank += 1
    insp["status"] = "SAMPLED"
    insp["drawn_at"] = values["drawn_at"]
    insp["sample_tier_value"] = tier_value
    insp["sample_size"] = sample_size
    store.touch(insp, bump_version=True)
    return envelope.ok(insp)


@bp.post("/inspections/<inspection_id>/start")
def start_inspection(inspection_id):
    auth.authenticate([auth.INSPECTOR])
    values = shapes.validate([shapes.F("started_at", "datetime")])
    insp = common.fetch("inspection", inspection_id)
    if insp["status"] != "NOTIFIED":
        raise ApiError(
            "ERR_INSPECTION_INVALID_STATE",
            "The on-site inspection may only start from NOTIFIED.",
        )
    prop = store.properties.get(insp["property_id"])
    if prop is not None and prop["readiness_posture"] == "FROZEN":
        raise ApiError("ERR_PROPERTY_FROZEN", "The property's readiness posture is FROZEN.")
    for slot in derive.inspection_selections(insp["id"]):
        if slot["selection_status"] != "ACTIVE":
            continue
        if slot["selection_basis"] != "SAMPLED":
            continue
        lead = slot["notice_lead_hours"]
        if lead is None or calc.d(lead) < calc.NOTICE_LEAD_HOURS_MIN:
            raise ApiError(
                "ERR_NOTICE_WINDOW_TOO_SHORT",
                "Every sampled slot needs at least 48.00 hours of tenant notice.",
            )
    insp["status"] = "IN_PROGRESS"
    insp["started_at"] = values["started_at"]
    store.touch(insp, bump_version=True)
    return envelope.ok(insp)


@bp.post("/inspections/<inspection_id>/deficiencies")
def record_deficiency(inspection_id):
    auth.authenticate([auth.INSPECTOR])
    values = shapes.validate(
        [
            shapes.F("expected_inspection_version", "integer"),
            shapes.F("defect_definition_id", "string"),
            shapes.F("inspectable_area", "enum", values=shapes.INSPECTABLE_AREA),
            shapes.F("observed_at", "datetime"),
            shapes.F("unit_id", "string", required=False),
            shapes.F("supersedes_deficiency_id", "string", required=False),
            shapes.F("note", "string", required=False),
        ]
    )
    insp = common.fetch("inspection", inspection_id)
    definition = common.body_fetch("definition", values["defect_definition_id"])
    unit = None
    if values.get("unit_id"):
        unit = common.body_fetch("unit", values["unit_id"])
    if values.get("supersedes_deficiency_id"):
        common.body_fetch("deficiency", values["supersedes_deficiency_id"])
    if insp["status"] != "IN_PROGRESS":
        raise ApiError(
            "ERR_INSPECTION_INVALID_STATE",
            "Deficiencies may only be recorded on an IN_PROGRESS inspection.",
        )
    if values["expected_inspection_version"] != insp["version"]:
        raise ApiError(
            "ERR_STALE_INSPECTION_VERSION",
            "expected_inspection_version does not match the inspection's current version.",
        )
    if definition["standard_id"] != insp["standard_id"]:
        raise ApiError(
            "ERR_DEFECT_DEFINITION_STANDARD_MISMATCH",
            "The cited definition does not belong to the standard pinned on this inspection.",
        )
    area = values["inspectable_area"]
    if area != definition["inspectable_area"]:
        raise ApiError(
            "ERR_AREA_MISMATCH",
            "inspectable_area must equal the cited definition's inspectable_area.",
        )
    if (area == "UNIT") != bool(values.get("unit_id")):
        raise ApiError(
            "ERR_AREA_MISMATCH",
            "unit_id must be present exactly when inspectable_area is UNIT.",
        )
    if area == "UNIT":
        slot = None
        for candidate in derive.inspection_selections(insp["id"]):
            if candidate["unit_id"] == unit["id"] and candidate["selection_status"] == "ACTIVE":
                slot = candidate
                break
        if slot is not None and slot["access_status"] != "GRANTED":
            raise ApiError(
                "ERR_UNIT_ACCESS_NOT_GRANTED",
                "The cited unit's sample slot has not granted access.",
            )
        if slot is None or unit["property_id"] != insp["property_id"]:
            raise ApiError(
                "ERR_UNIT_NOT_IN_SAMPLE",
                "The cited unit is not held by an ACTIVE sample slot of this inspection.",
            )

    deficiency = {
        "inspection_id": insp["id"],
        "sweep_id": None,
        "defect_definition_id": definition["id"],
        "unit_id": values.get("unit_id"),
        "supersedes_deficiency_id": values.get("supersedes_deficiency_id"),
        "source": "INSPECTION",
        "inspectable_area": area,
        "severity": definition["severity"],
        "status": "OPEN",
        "observed_at": values["observed_at"],
        "correction_due_at": calc.add_hours(
            values["observed_at"], definition["correction_deadline_hours"]
        ),
        "corrected_at": None,
        "verified_at": None,
        "points_deducted": calc.deficiency_points(
            definition, area, values.get("supersedes_deficiency_id"), unit
        ),
        "recurrence_applied": bool(values.get("supersedes_deficiency_id")),
        "inspection_version_after_record": None,
        "note": values.get("note"),
    }
    store.stamp_new(deficiency)
    store.deficiencies[deficiency["id"]] = deficiency

    derive.recompute_inspection_sums(insp)
    store.touch(insp, bump_version=True)
    deficiency["inspection_version_after_record"] = insp["version"]

    prop = store.properties.get(insp["property_id"])
    if prop is not None:
        derive.rederive_property(prop, bump_version=True)
    if unit is not None:
        derive.recompute_unit_open_count(unit)
    return envelope.created(deficiency)


@bp.post("/inspections/<inspection_id>/score")
def score_inspection(inspection_id):
    auth.authenticate([auth.INSPECTOR])
    values = shapes.validate([shapes.F("scored_at", "datetime")])
    insp = common.fetch("inspection", inspection_id)
    if insp["status"] != "IN_PROGRESS":
        raise ApiError(
            "ERR_INSPECTION_INVALID_STATE",
            "Only an IN_PROGRESS inspection may be scored.",
        )
    for row in derive.inspection_deficiencies(insp["id"]):
        if row["severity"] == "LIFE_THREATENING" and row["status"] in ("OPEN", "OVERDUE"):
            raise ApiError(
                "ERR_LIFE_THREATENING_UNCORRECTED",
                "A life-threatening deficiency is still open on this inspection.",
            )
    for slot in derive.inspection_selections(insp["id"]):
        if slot["selection_status"] != "ACTIVE":
            continue
        if slot["access_status"] not in ("GRANTED", "REFUSED"):
            raise ApiError(
                "ERR_ACCESS_NOT_RECORDED",
                "Every active sample slot must have its access outcome recorded.",
            )
    provisional, final = derive.compute_inspection_scores(insp)
    insp["status"] = "SCORED"
    insp["scored_at"] = values["scored_at"]
    insp["provisional_score"] = provisional
    insp["final_score"] = final
    insp["appeal_deadline_at"] = calc.add_hours(
        values["scored_at"], calc.APPEAL_WINDOW_HOURS
    )
    store.touch(insp, bump_version=True)
    prop = store.properties.get(insp["property_id"])
    if prop is not None:
        derive.rederive_property(prop, bump_version=True)
    return envelope.ok(insp)


@bp.post("/inspections/<inspection_id>/cancel")
def cancel_inspection(inspection_id):
    auth.authenticate([auth.INSPECTOR])
    insp = common.fetch("inspection", inspection_id)
    if insp["status"] not in ("SCHEDULED", "SAMPLED", "NOTIFIED"):
        raise ApiError(
            "ERR_INSPECTION_INVALID_STATE",
            "Only an inspection that has not started may be cancelled.",
        )
    for slot in derive.inspection_selections(insp["id"]):
        if slot["selection_status"] != "REPLACED":
            slot["selection_status"] = "REPLACED"
            store.touch(slot, bump_version=False)
    insp["status"] = "CANCELLED"
    store.touch(insp, bump_version=True)
    return envelope.ok(insp)


@bp.post("/inspections/<inspection_id>/finalize")
def finalize_inspection(inspection_id):
    auth.authenticate([auth.INSPECTOR])
    values = shapes.validate([shapes.F("finalized_at", "datetime")])
    insp = common.fetch("inspection", inspection_id)
    for appeal in derive.inspection_appeals(insp["id"]):
        if appeal["status"] in ("SUBMITTED", "RETURNED_FOR_INFO"):
            raise ApiError(
                "ERR_APPEAL_PENDING",
                "An appeal of this inspection is still pending a terminal decision.",
            )
    if insp["status"] == "SCORED":
        cap_required = (
            calc.d(insp["final_score"]) < calc.CAP_SCORE_THRESHOLD
            or insp["life_threatening_count"] >= 1
        )
        insp["finalized_at"] = values["finalized_at"]
        insp["cap_required"] = cap_required
        if cap_required:
            window_days = calc.cap_window_days(insp["final_score"])
            anchor = insp["rescored_at"] or insp["scored_at"]
            cap_due_at = calc.add_hours(anchor, window_days * 24)
            followup_offset = (
                calc.FOLLOWUP_OFFSET_LT_DAYS
                if insp["life_threatening_count"] >= 1
                else calc.FOLLOWUP_OFFSET_DAYS
            )
            insp["cap_window_days"] = window_days
            insp["cap_due_at"] = cap_due_at
            insp["followup_due_at"] = calc.add_hours(cap_due_at, followup_offset * 24)
            insp["status"] = "CAP_REQUIRED"
            store.touch(insp, bump_version=True)
            return envelope.ok(insp)
        insp["status"] = "CLOSED"
        store.touch(insp, bump_version=True)
        derive.refresh_unit_history(insp["id"])
        _complete_owning_plan(insp)
        return envelope.ok(insp)

    if insp["status"] == "FOLLOW_UP_SCHEDULED":
        follow_up_closed = False
        for plan in derive.inspection_plans(insp["id"]):
            follow_up_id = plan.get("follow_up_inspection_id")
            if not follow_up_id:
                continue
            follow_up = store.inspections.get(follow_up_id)
            if follow_up is not None and follow_up["status"] == "CLOSED":
                follow_up_closed = True
        if not follow_up_closed:
            raise ApiError(
                "ERR_FOLLOW_UP_NOT_CLOSED",
                "The follow-up inspection named by the plan has not reached CLOSED.",
            )
        insp["status"] = "CLOSED"
        insp["finalized_at"] = values["finalized_at"]
        store.touch(insp, bump_version=True)
        return envelope.ok(insp)

    raise ApiError(
        "ERR_INSPECTION_INVALID_STATE",
        "This inspection's status does not admit finalization.",
    )


def _complete_owning_plan(insp):
    """A closing FOLLOW_UP inspection completes the plan that created it."""
    if insp["inspection_kind"] != "FOLLOW_UP":
        return
    for plan in store.by_seq(list(store.plans.values())):
        if plan.get("follow_up_inspection_id") != insp["id"]:
            continue
        if plan["status"] == "FOLLOW_UP_SCHEDULED":
            plan["status"] = "COMPLETED"
            store.touch(plan, bump_version=True)
