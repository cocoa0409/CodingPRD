"""Consultation review: assessments, tolling, concurrence, opinions."""
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

bp = Blueprint("consultations", __name__)

PROPONENT = ("Proponent",)
AGENCY = ("WildlifeAgency",)

BA_SOURCE_STATES = ("DRAFT_BA", "INFO_REQUESTED", "REINITIATION_REQUIRED")


@bp.route("/consultations/<cid>/biological-assessment", methods=["POST"])
def submit_assessment(cid):
    caller = auth.authenticate(PROPONENT)
    consultation = resolve.consultation(cid)
    auth.require_owner(caller, auth.owner_of_consultation(consultation))

    body = shape.Body()
    narrative = body.string("ba_narrative", 1)
    complete = body.boolean("ba_effects_analysis_complete")
    body.close()
    # The attestation must be supplied as true; false is a shape error.
    if complete is not True:
        shape.bad("ba_effects_analysis_complete must be supplied as true.")

    source = consultation["status"]
    if source not in BA_SOURCE_STATES:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    now = store.now()
    if source == "INFO_REQUESTED":
        # The episode tolls whole days only; a partial day is discarded.
        opened = consultation["info_requested_at"]
        if opened is not None:
            elapsed = util.whole_days_between(opened, now)
            consultation["tolled_days"] = consultation["tolled_days"] + elapsed
        consultation["info_requested_at"] = None
        calc.refresh_deadline(consultation)
    elif source == "REINITIATION_REQUIRED":
        # The statutory clock restarts rather than extends.
        consultation["clock_started_at"] = now
        consultation["tolled_days"] = 0
        consultation["info_request_count"] = 0
        calc.refresh_deadline(consultation)

    consultation["status"] = "UNDER_REVIEW"
    consultation["ba_revision_number"] = consultation["ba_revision_number"] + 1
    consultation["ba_submitted_at"] = now
    consultation["ba_narrative"] = narrative
    consultation["ba_effects_analysis_complete"] = complete
    store.touch(consultation)

    if source == "REINITIATION_REQUIRED":
        action = store.get("actions", consultation["project_action_id"])
        if action is not None and action["status"] == "REINITIATION_PENDING":
            action["status"] = "FORMAL_CONSULTATION"
            action["reinitiation_reason"] = "NONE"
            store.touch(action)
        if action is not None:
            calc.refresh_compliance(calc.proponent_of_action(action))

    return envelope.obj(serialize.consultation(consultation))


@bp.route("/consultations/<cid>/information-request", methods=["POST"])
def request_information(cid):
    auth.authenticate(AGENCY)
    consultation = resolve.consultation(cid)

    body = shape.Body()
    body.string("request_note", 1)
    body.close()

    if consultation["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    # The cap is a state rule, not a deadline rule.
    if consultation["info_request_count"] >= calc.MAX_INFO_REQUESTS:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    now = store.now()
    if consultation["deadline_at"] is not None and now > consultation["deadline_at"]:
        raise ApiError("ERR_CONSULTATION_DEADLINE_PASSED")

    consultation["status"] = "INFO_REQUESTED"
    consultation["info_requested_at"] = now
    consultation["info_request_count"] = consultation["info_request_count"] + 1
    store.touch(consultation)
    return envelope.obj(serialize.consultation(consultation))


@bp.route("/consultations/<cid>/concurrence", methods=["POST"])
def concur(cid):
    auth.authenticate(AGENCY)
    consultation = resolve.consultation(cid)

    body = shape.Body()
    body.string("concurrence_note", 1)
    body.close()

    if consultation["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if consultation["consultation_type"] != "INFORMAL":
        raise ApiError("ERR_CONSULTATION_TYPE_MISMATCH")

    consultation["status"] = "CONCLUDED_CONCURRENCE"
    store.touch(consultation)

    action = store.get("actions", consultation["project_action_id"])
    if action is not None and action["status"] == "INFORMAL_CONSULTATION":
        action["status"] = "CONSULTATION_CONCLUDED"
        store.touch(action)

    return envelope.obj(serialize.consultation(consultation))


@bp.route("/consultations/<cid>/biological-opinion", methods=["POST"])
def issue_opinion(cid):
    caller = auth.authenticate(AGENCY)
    consultation = resolve.consultation(cid)

    body = shape.Body()
    rpa_description = body.string("rpa_description", 1, required=False)
    body.close()

    if consultation["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if consultation["consultation_type"] != "FORMAL":
        raise ApiError("ERR_CONSULTATION_TYPE_MISMATCH")

    action = store.get("actions", consultation["project_action_id"])
    take = calc.incidental_take(action) if action is not None else None
    if take is None:
        raise ApiError("ERR_NO_PRESENCE_DETERMINATIONS")

    species = take["species"]
    fraction = take["jeopardy_fraction"]
    if fraction >= calc.JEOPARDY_FRACTION_THRESHOLD:
        rpa_required = True
        conclusion = "JEOPARDY_WITH_RPA" if rpa_description else "JEOPARDY"
    else:
        rpa_required = False
        conclusion = "NO_JEOPARDY"

    now = store.now()
    deadline = consultation["deadline_at"]
    opinion = store.new_row(
        consultation_id=consultation["id"],
        primary_species_scientific_name=species["scientific_name"],
        primary_species_listing_status=species["listing_status"],
        conclusion=conclusion,
        rpa_required=rpa_required,
        rpa_description=rpa_description,
        exposed_acres=take["exposed_acres"],
        take_unit=take["take_unit"],
        authorized_take_units=take["authorized_take_units"],
        jeopardy_fraction=fraction,
        reinitiation_trigger_units=take["reinitiation_trigger_units"],
        issued_by_user_id=caller.user_id,
        issued_at=now,
        issued_late=bool(deadline is not None and now > deadline),
    )
    # An opinion is immutable: it carries no updated_at and no version.
    opinion.pop("updated_at", None)
    opinion.pop("version", None)
    store.insert("opinions", opinion)

    consultation["status"] = "OPINION_ISSUED"
    store.touch(consultation)

    if action is not None and action["status"] == "FORMAL_CONSULTATION":
        action["status"] = "CONSULTATION_CONCLUDED"
        store.touch(action)

    return envelope.created(serialize.opinion(opinion))
