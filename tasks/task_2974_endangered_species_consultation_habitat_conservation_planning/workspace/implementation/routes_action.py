"""Screening: actions, presence determinations, the effect determination fork,
and plan creation."""
from flask import Blueprint

import auth
import calc
import envelope
import resolve
import serialize
import shape
import store
import util
from errors import ApiError

bp = Blueprint("actions", __name__)

PROPONENT = ("Proponent",)


@bp.route("/project-actions", methods=["POST"])
def register_action():
    caller = auth.authenticate(PROPONENT)
    auth.require_identity(caller)

    # Rung 5 has a non-path variant here: a proponent may not open an action in
    # another proponent's name.  A body proponent_id that resolves to nothing
    # falls through to rung 6 instead.
    supplied = shape.peek_str("proponent_id")
    if supplied is not None:
        owner = store.get("proponents", supplied)
        if owner is not None and owner["id"] != caller.user_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER")
        if owner is None:
            raise ApiError("ERR_PROPONENT_NOT_FOUND")

    body = shape.Body()
    proponent_id = body.ident("proponent_id")
    action_name = body.string("action_name", 1, 160)
    action_type = body.enum("action_type", calc.ACTION_TYPES)
    footprint_acres = body.quantity("footprint_acres", positive=True)
    county_code = body.digits("county_code", 5)
    start_date = body.date("construction_start_date")
    end_date = body.date("construction_end_date")
    body.close()

    if start_date > end_date:
        shape.bad("construction_start_date must not be later than "
                  "construction_end_date.")

    row = store.new_row(
        proponent_id=proponent_id,
        action_name=action_name,
        action_type=action_type,
        footprint_acres=footprint_acres,
        county_code=county_code,
        construction_start_date=start_date,
        construction_end_date=end_date,
        status="SCREENING",
        effect_determination="PENDING",
        total_overlap_acres=util.q2(0),
        overlap_pct=util.q2(0),
        active_consultation_id=None,
        reinitiation_reason="NONE",
    )
    store.insert("actions", row)
    return envelope.created(serialize.action(row))


@bp.route("/project-actions/<aid>/presence-determinations", methods=["POST"])
def record_determination(aid):
    caller = auth.authenticate(PROPONENT)
    action = resolve.action(aid)
    auth.require_owner(caller, auth.owner_of_action(action))

    # Rung 6, in the declared order: species_id then critical_habitat_unit_id.
    species_id = shape.peek_str("species_id")
    species = resolve.species(species_id) if species_id is not None else None
    unit_id = shape.peek_str("critical_habitat_unit_id")
    unit = None
    if unit_id is not None:
        unit = resolve.habitat_unit(unit_id)
        # A unit designated for another species does not exist for this one.
        if species is not None and unit["species_id"] != species["id"]:
            raise ApiError("ERR_CRITICAL_HABITAT_UNIT_NOT_FOUND")

    body = shape.Body()
    body.ident("species_id")
    body.ident("critical_habitat_unit_id", required=False)
    method = body.enum("method", calc.METHODS)
    detection_result = body.enum("detection_result", calc.DETECTION_RESULTS)
    habitat_overlap_acres = body.quantity("habitat_overlap_acres")
    window_start = body.date("survey_window_start", required=False)
    window_end = body.date("survey_window_end", required=False)
    body.close()

    if species is None:
        species = resolve.species(species_id)

    # Rung 17: the window fields are strictly method-gated.
    if method == "FIELD_SURVEY":
        if window_start is None or window_end is None:
            raise ApiError("ERR_SURVEY_WINDOW_INVALID")
        if window_start > window_end:
            raise ApiError("ERR_SURVEY_WINDOW_INVALID")
    else:
        if window_start is not None or window_end is not None:
            raise ApiError("ERR_SURVEY_WINDOW_INVALID")

    # Rung 20: field surveys inside the same designated unit are spaced out by
    # a three-day buffer, across every project action.
    if method == "FIELD_SURVEY" and unit is not None:
        for other in store.ordered(store.values("determinations")):
            if other["method"] != "FIELD_SURVEY":
                continue
            if other.get("critical_habitat_unit_id") != unit["id"]:
                continue
            other_start = other["survey_window_start"]
            other_end = other["survey_window_end"]
            if other_start is None or other_end is None:
                continue
            buffered_end = util.add_days(other_end,
                                         calc.SURVEY_DISTURBANCE_BUFFER_DAYS)
            buffered_new_end = util.add_days(
                window_end, calc.SURVEY_DISTURBANCE_BUFFER_DAYS
            )
            if window_start <= buffered_end and buffered_new_end >= other_start:
                raise ApiError("ERR_SURVEY_WINDOW_CONFLICT")

    in_season = calc.survey_in_season(method, window_start, window_end, species)
    status = calc.presence_status(method, detection_result, in_season)

    row = store.new_row(
        project_action_id=action["id"],
        species_id=species["id"],
        critical_habitat_unit_id=unit["id"] if unit is not None else None,
        method=method,
        detection_result=detection_result,
        survey_window_start=window_start,
        survey_window_end=window_end,
        habitat_overlap_acres=habitat_overlap_acres,
        presence_status=status,
        survey_in_season=in_season,
        requires_reevaluation=False,
    )
    store.insert("determinations", row)
    return envelope.created(serialize.determination(row))


@bp.route("/project-actions/<aid>/effect-determination", methods=["POST"])
def run_effect_determination(aid):
    caller = auth.authenticate(PROPONENT)
    action = resolve.action(aid)
    auth.require_owner(caller, auth.owner_of_action(action))
    shape.Body().close()

    # Rung 9 -- a second determination on the same action is a state error.
    if action["status"] != "SCREENING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    # Rung 22 -- zero rows is an error; zero candidates is a clean NO_EFFECT.
    existing = [
        row
        for row in store.values("determinations")
        if row["project_action_id"] == action["id"]
    ]
    if not existing:
        raise ApiError("ERR_NO_PRESENCE_DETERMINATIONS")

    outcome, total_overlap, overlap_pct = calc.effect_determination(action)
    action["effect_determination"] = outcome
    action["total_overlap_acres"] = total_overlap
    action["overlap_pct"] = overlap_pct

    if outcome == "NO_EFFECT":
        action["status"] = "CLEARED_NO_EFFECT"
    else:
        if outcome == "NLAA":
            action["status"] = "INFORMAL_CONSULTATION"
            consultation_type = "INFORMAL"
            statutory_days = calc.INFORMAL_CONSULTATION_DAYS
        else:
            action["status"] = "FORMAL_CONSULTATION"
            consultation_type = "FORMAL"
            statutory_days = calc.FORMAL_CONSULTATION_DAYS

        consultation = store.new_row(
            project_action_id=action["id"],
            consultation_type=consultation_type,
            status="DRAFT_BA",
            clock_started_at=store.now(),
            statutory_days=statutory_days,
            tolled_days=0,
            deadline_at=None,
            ba_revision_number=0,
            ba_submitted_at=None,
            ba_narrative=None,
            ba_effects_analysis_complete=False,
            info_request_count=0,
            info_requested_at=None,
            reinitiation_triggered_at=None,
            reinitiation_count=0,
        )
        calc.refresh_deadline(consultation)
        store.insert("consultations", consultation)
        action["active_consultation_id"] = consultation["id"]

    store.touch(action)
    return envelope.obj(serialize.action(action))


@bp.route("/project-actions/<aid>/habitat-conservation-plans", methods=["POST"])
def open_plan(aid):
    caller = auth.authenticate(PROPONENT)
    action = resolve.action(aid)
    auth.require_owner(caller, auth.owner_of_action(action))

    body = shape.Body()
    plan_name = body.string("plan_name", 1, 160)
    covered_acres = body.quantity("covered_acres", positive=True)
    permit_term_years = body.integer("permit_term_years", lo=1, hi=50)
    body.close()

    # Rung 9 before rung 15.
    if action["status"] != "CONSULTATION_CONCLUDED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if store.where("plans", project_action_id=action["id"]):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if action["action_type"] != "NON_FEDERAL":
        raise ApiError("ERR_HCP_NOT_ALLOWED_FOR_FEDERAL_ACTION")

    # Rung 22 -- raised by the PRELIMINARY variant on an empty candidate set.
    preliminary = calc.preliminary_mitigation_units(action, covered_acres)

    row = store.new_row(
        project_action_id=action["id"],
        plan_name=plan_name,
        covered_acres=covered_acres,
        permit_term_years=permit_term_years,
        plan_status="DRAFT",
        funding_status="UNFUNDED",
        preliminary_mitigation_units=preliminary,
        final_mitigation_units=util.q2(0),
        mitigation_delta_units=util.q2(0),
        secured_mitigation_units=util.q2(0),
        endowment_base_cents=0,
        changed_circumstance_reserve_cents=0,
        endowment_required_cents=0,
        endowment_secured_cents=0,
        funded_ratio=util.q4(0),
        reserve_drawn_cents=0,
        reserve_remaining_cents=0,
        approved_by_user_id=None,
        assurance_review_required=False,
    )
    store.insert("plans", row)

    action["status"] = "HCP_DEVELOPMENT"
    store.touch(action)
    return envelope.created(serialize.plan(row))
