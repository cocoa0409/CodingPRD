"""PRD 3.4 and 3.9: opening, activating, holding, resuming and ending therapy."""

from flask import Blueprint

import calculations as calc
import cascades
import constants as C
import serializers as S
from auth import endpoint
from errors import fail
from response import created, ok
from store import bump, db, stamp_versioned
from validation import (
    q_enum,
    q_int,
    q_string,
    read_body,
    v_bool,
    v_enum,
    v_instant,
    v_int,
    v_string,
)

from .common import episode_or_404, paginate

bp = Blueprint("episodes", __name__)

EPISODE_READ_ROLES = [
    "Rheumatologist",
    "InfusionNurse",
    "PriorAuthCoordinator",
    "BenefitsCounselor",
    "PayerReviewer",
    "RegistryAdmin",
]


@bp.post("/therapy-episodes")
@endpoint(["Rheumatologist"])
def create_episode():
    body = read_body()
    patient_id = v_string(body, "patient_id")
    drug_id = v_string(body, "drug_id")
    payer_plan_id = v_string(body, "payer_plan_id")
    therapy_start_at = v_instant(body, "therapy_start_at")
    expected_patient_version = v_int(body, "expected_patient_version")
    prior_episode_id = v_string(body, "prior_episode_id", required=False)

    patient = db.patients.get(patient_id)
    if patient is None:
        fail("ERR_REFERENCE_NOT_FOUND", "The named patient does not exist.")
    drug = db.drugs.get(drug_id)
    if drug is None:
        fail("ERR_REFERENCE_NOT_FOUND", "The named drug does not exist.")
    plan = db.payer_plans.get(payer_plan_id)
    if plan is None:
        fail("ERR_REFERENCE_NOT_FOUND", "The named payer plan does not exist.")
    prior = None
    if prior_episode_id is not None:
        prior = db.episodes.get(prior_episode_id)
        if prior is None:
            fail("ERR_REFERENCE_NOT_FOUND", "The named prior episode does not exist.")

    if expected_patient_version != patient["version"]:
        fail("ERR_STALE_PATIENT_VERSION")

    # PRD 2.10 places ERR_NO_BENEFIT_CHANNEL_AVAILABLE (38) above
    # ERR_PRIOR_EPISODE_INVALID (39), so routing is settled first.
    routing = calc.benefit_routing(drug, plan)
    if routing is None:
        fail("ERR_NO_BENEFIT_CHANNEL_AVAILABLE")
    benefit_channel, site_of_care = routing

    if prior is not None:
        if prior["patient_id"] != patient_id:
            fail("ERR_PRIOR_EPISODE_INVALID", "The prior episode belongs to another patient.")
        if prior["therapy_state"] != "DISCONTINUED":
            fail("ERR_PRIOR_EPISODE_INVALID", "The prior episode is not discontinued.")
        if prior["line_of_therapy"] + 1 > C.MAX_LINE_OF_THERAPY:
            fail("ERR_PRIOR_EPISODE_INVALID", "The line of therapy cap would be exceeded.")

    training_status = "PENDING" if site_of_care == "SELF_ADMIN" else "NOT_REQUIRED"

    row = {
        "patient_id": patient_id,
        "drug_id": drug_id,
        "payer_plan_id": payer_plan_id,
        "prior_episode_id": prior_episode_id,
        "therapy_start_at": therapy_start_at,
        "therapy_state": "PLANNED",
        "funding_state": "UNFUNDED",
        "line_of_therapy": calc.line_of_therapy(prior),
        "benefit_channel": benefit_channel,
        "site_of_care": site_of_care,
        "routing_frozen": True,
        "hold_reason": None,
        "held_at": None,
        "resume_not_before": None,
        "hold_count": 0,
        "discontinuation_reason": None,
        "discontinued_at": None,
        "therapy_exposure_weeks": None,
        "doses_administered": 0,
        "self_injection_training_status": training_status,
        "self_injection_training_attempts": 0,
        "_ever_activated": False,
    }
    stamp_versioned(row)
    db.episodes[row["id"]] = row

    # PRD 3.4: every OTHER still-PLANNED episode of this patient is superseded.
    cascades.supersede_planned_episodes(patient, row["id"])
    bump(patient)

    return created(S.episode_out(row))


@bp.get("/therapy-episodes/<episode_id>")
@endpoint(EPISODE_READ_ROLES)
def get_episode(episode_id):
    episode = episode_or_404(episode_id)
    return ok(S.episode_out(episode))


@bp.get("/therapy-episodes")
@endpoint(EPISODE_READ_ROLES)
def list_episodes():
    patient_id = q_string("patient_id")
    drug_id = q_string("drug_id")
    payer_plan_id = q_string("payer_plan_id")
    prior_episode_id = q_string("prior_episode_id")
    therapy_state = q_enum("therapy_state", C.THERAPY_STATES)
    funding_state = q_enum("funding_state", C.FUNDING_STATES)

    rows = []
    for episode in db.episodes.values():
        if patient_id is not None and episode["patient_id"] != patient_id:
            continue
        if drug_id is not None and episode["drug_id"] != drug_id:
            continue
        if payer_plan_id is not None and episode["payer_plan_id"] != payer_plan_id:
            continue
        if prior_episode_id is not None and episode["prior_episode_id"] != prior_episode_id:
            continue
        if therapy_state is not None and episode["therapy_state"] != therapy_state:
            continue
        if funding_state is not None and episode["funding_state"] != funding_state:
            continue
        rows.append(episode)
    return paginate(rows, S.episode_out)


@bp.post("/therapy-episodes/<episode_id>/activate")
@endpoint(["Rheumatologist"])
def activate_episode(episode_id):
    episode = episode_or_404(episode_id)
    drug = db.drugs[episode["drug_id"]]
    patient = db.patients[episode["patient_id"]]

    # PRD 3.4: seven conditions, checked in exactly this order.
    if episode["therapy_state"] != "PLANNED":
        fail("ERR_EPISODE_NOT_PLANNED")
    if episode["funding_state"] != "AUTHORIZED":
        fail("ERR_FUNDING_NOT_AUTHORIZED")
    if drug["tb_screen_required"]:
        if not calc.tb_cleared(calc.tb_screen_status(patient["id"])):
            fail("ERR_TB_SCREEN_NOT_CLEARED")
    if drug["hbv_screen_required"]:
        hbv = calc.hbv_screen_status(patient["id"])
        if hbv == "ACTIVE_INFECTION":
            fail("ERR_HBV_ACTIVE_INFECTION_CONTRAINDICATED")
        if hbv == "INCOMPLETE":
            fail("ERR_HBV_SCREEN_INCOMPLETE")
    if calc.monitoring_status(episode, drug) != "CURRENT":
        fail("ERR_MONITORING_LAB_OVERDUE")
    if drug["route"] == "SC" and episode["self_injection_training_status"] != "PASSED":
        fail("ERR_SELF_INJECTION_TRAINING_INCOMPLETE")

    episode["therapy_state"] = "ACTIVE"
    episode["_ever_activated"] = True
    bump(episode)

    patient["active_episode_count"] += 1
    bump(patient)

    return ok(S.episode_out(episode))


@bp.post("/therapy-episodes/<episode_id>/hold")
@endpoint(["Rheumatologist"])
def hold_episode(episode_id):
    episode = episode_or_404(episode_id)
    body = read_body()
    hold_reason = v_enum(body, "hold_reason", C.HOLD_REASONS)
    if episode["therapy_state"] != "ACTIVE":
        fail("ERR_EPISODE_NOT_ACTIVE")
    patient = db.patients[episode["patient_id"]]
    cascades.enter_hold(episode, patient, hold_reason)
    return ok(S.episode_out(episode))


@bp.post("/therapy-episodes/<episode_id>/resume")
@endpoint(["Rheumatologist"])
def resume_episode(episode_id):
    episode = episode_or_404(episode_id)
    body = read_body(required=False)
    infection_resolved = v_bool(body, "infection_resolved_attested", required=False)
    wound_healed = v_bool(body, "wound_healed_attested", required=False)

    drug = db.drugs[episode["drug_id"]]

    # PRD 3.9: five checks, in exactly this order.
    if episode["therapy_state"] != "HELD":
        fail("ERR_EPISODE_NOT_HELD")
    if episode["funding_state"] != "AUTHORIZED":
        fail("ERR_FUNDING_NOT_AUTHORIZED")
    if calc.monitoring_status(episode, drug) != "CURRENT":
        fail("ERR_MONITORING_LAB_OVERDUE")

    reason = episode["hold_reason"]
    if reason == "INFECTION":
        if infection_resolved is not True:
            fail(
                "ERR_RESUMPTION_PROTOCOL_INCOMPLETE",
                "An infection hold requires infection_resolved_attested.",
            )
    elif reason == "SURGERY":
        if wound_healed is not True:
            fail(
                "ERR_RESUMPTION_PROTOCOL_INCOMPLETE",
                "A surgery hold requires wound_healed_attested.",
            )
    elif reason == "LAB_ABNORMALITY":
        # A repeat draw strictly after the hold, grading at most 2, clears it.
        cleared = any(
            lab["collected_at"] > episode["held_at"] and lab["abnormal_grade"] <= 2
            for lab in calc.episode_matching_labs(episode, drug)
        )
        if not cleared:
            fail(
                "ERR_RESUMPTION_PROTOCOL_INCOMPLETE",
                "A repeat panel collected after the hold and grading at most 2 is required.",
            )

    if db.now() < episode["resume_not_before"]:
        fail("ERR_WASHOUT_PERIOD_NOT_ELAPSED")

    episode["therapy_state"] = "ACTIVE"
    episode["hold_reason"] = None
    episode["held_at"] = None
    episode["resume_not_before"] = None
    bump(episode)

    patient = db.patients[episode["patient_id"]]
    patient["active_episode_count"] += 1
    bump(patient)

    return ok(S.episode_out(episode))


@bp.post("/therapy-episodes/<episode_id>/discontinue")
@endpoint(["Rheumatologist"])
def discontinue_episode(episode_id):
    episode = episode_or_404(episode_id)
    body = read_body()
    reason = v_enum(body, "discontinuation_reason", C.CALLER_DISCONTINUATION_REASONS)
    if episode["therapy_state"] == "DISCONTINUED":
        fail("ERR_EPISODE_NOT_ACTIVE", "This episode is already discontinued.")
    patient = db.patients[episode["patient_id"]]
    cascades.discontinue(episode, patient, reason)
    return ok(S.episode_out(episode))


@bp.post("/therapy-episodes/<episode_id>/record-training")
@endpoint(["InfusionNurse"])
def record_training(episode_id):
    episode = episode_or_404(episode_id)
    body = read_body()
    outcome = v_enum(body, "outcome", C.TRAINING_OUTCOMES)
    episode["self_injection_training_status"] = outcome
    episode["self_injection_training_attempts"] += 1
    bump(episode)
    return ok(S.episode_out(episode))


@bp.get("/therapy-episodes/<episode_id>/cost-share-estimate")
@endpoint(["BenefitsCounselor", "PriorAuthCoordinator", "Rheumatologist", "RegistryAdmin"])
def cost_share_estimate(episode_id):
    episode = episode_or_404(episode_id)
    dose_count = q_int("dose_count", minimum=1)
    drug = db.drugs[episode["drug_id"]]
    plan = db.payer_plans[episode["payer_plan_id"]]
    return ok(calc.cost_share_waterfall(episode, drug, plan, dose_count))
