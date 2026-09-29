"""PRD 3.5: prior authorization, step therapy, formulary exceptions, determination."""

from flask import Blueprint

import calculations as calc
import cascades
import constants as C
import serializers as S
from auth import acting_user_id, endpoint
from errors import fail
from response import created, ok
from store import add_days, bump, db, sort_rows, stamp_versioned
from validation import q_enum, q_string, read_body, v_bool, v_enum, v_instant, v_int, v_string

from .common import paginate, resolve

bp = Blueprint("authorizations", __name__)

AUTH_READ_ROLES = [
    "PriorAuthCoordinator",
    "PayerReviewer",
    "Rheumatologist",
    "BenefitsCounselor",
    "InfusionNurse",
    "RegistryAdmin",
]


def _authorization_or_404(authorization_id):
    return resolve(db.authorizations, authorization_id, "ERR_AUTHORIZATION_NOT_FOUND")


@bp.post("/authorizations")
@endpoint(["PriorAuthCoordinator"])
def create_authorization():
    body = read_body()
    episode_id = v_string(body, "episode_id")
    requested_units = v_int(body, "requested_units", minimum=1, maximum=24)
    expected_episode_version = v_int(body, "expected_episode_version")
    exception_requested = v_bool(
        body, "formulary_exception_requested", required=False, default=False
    )
    hbv_prophylaxis = v_bool(
        body, "hbv_prophylaxis_documented", required=False, default=False
    )

    episode = db.episodes.get(episode_id)
    if episode is None:
        fail("ERR_EPISODE_NOT_FOUND")
    if expected_episode_version != episode["version"]:
        fail("ERR_STALE_EPISODE_VERSION")

    row = {
        "episode_id": episode_id,
        "exception_attested_by_clinician_id": None,
        # PRD 3.5: the channel is copied from the episode and frozen here.
        "benefit_channel": episode["benefit_channel"],
        "status": "DRAFT",
        "requested_units": requested_units,
        "approved_units": None,
        "units_reserved": 0,
        "units_consumed": 0,
        "units_remaining": None,
        "formulary_exception_requested": exception_requested,
        "hbv_prophylaxis_documented": hbv_prophylaxis,
        "appeal_round": 0,
        "decision_reason": None,
        "determination_at": None,
        "valid_from": None,
        "valid_through": None,
        "submitted_at": None,
        "unmet_step_therapy_classes": [],
    }
    stamp_versioned(row)
    db.authorizations[row["id"]] = row

    # Any earlier DRAFT of the same episode is expired with a supersede note.
    for other in sort_rows(
        [a for a in db.authorizations.values() if a["episode_id"] == episode_id]
    ):
        if other["id"] == row["id"] or other["status"] != "DRAFT":
            continue
        other["status"] = "EXPIRED"
        other["decision_reason"] = C.DRAFT_SUPERSEDE_NOTE
        bump(other)

    episode["funding_state"] = "PENDING_AUTH"
    bump(episode)

    return created(S.authorization_out(row))


@bp.post("/authorizations/<authorization_id>/attest-exception")
@endpoint(["Rheumatologist"])
def attest_exception(authorization_id):
    # PRD 2.10 rule 3: the credential check sits above every existence and
    # state check, so an uncredentialed caller sees the 403 either way.
    clinician = db.clinicians.get(acting_user_id())
    if (
        clinician is None
        or clinician["role_type"] != "RHEUMATOLOGIST"
        or not clinician["can_attest_formulary_exception"]
    ):
        fail("ERR_CLINICIAN_NOT_AUTHORIZED_TO_ATTEST")

    authorization = _authorization_or_404(authorization_id)
    if authorization["status"] not in ("DRAFT", "DENIED"):
        fail("ERR_AUTHORIZATION_STATE_INVALID")

    authorization["exception_attested_by_clinician_id"] = acting_user_id()
    bump(authorization)
    return ok(S.authorization_out(authorization))


@bp.post("/authorizations/<authorization_id>/submit")
@endpoint(["PriorAuthCoordinator"])
def submit_authorization(authorization_id):
    authorization = _authorization_or_404(authorization_id)
    read_body(required=False)

    episode = db.episodes[authorization["episode_id"]]
    drug = db.drugs[episode["drug_id"]]
    plan = db.payer_plans[episode["payer_plan_id"]]
    patient = db.patients[episode["patient_id"]]

    previous_status = authorization["status"]
    if previous_status not in ("DRAFT", "DENIED"):
        fail("ERR_AUTHORIZATION_STATE_INVALID")
    if previous_status == "DENIED":
        if authorization["appeal_round"] >= plan["appeal_rounds_allowed"]:
            fail("ERR_APPEAL_ROUNDS_EXHAUSTED")
    if calc.hbv_screen_status(patient["id"]) == "OCCULT_RISK":
        if not authorization["hbv_prophylaxis_documented"]:
            fail("ERR_HBV_SCREEN_INCOMPLETE")

    # PRD 3.5: step therapy is evaluated afresh on every submission attempt.
    unmet = calc.step_therapy_evaluation(episode, drug, plan)
    if unmet and not authorization["formulary_exception_requested"]:
        fail("ERR_STEP_THERAPY_NOT_SATISFIED")
    if authorization["formulary_exception_requested"]:
        if authorization["exception_attested_by_clinician_id"] is None:
            fail("ERR_FORMULARY_EXCEPTION_NOT_ATTESTED")

    authorization["unmet_step_therapy_classes"] = unmet
    authorization["status"] = "SUBMITTED"
    authorization["submitted_at"] = db.now()
    if previous_status == "DENIED":
        authorization["appeal_round"] += 1
        authorization["decision_reason"] = None
    bump(authorization)
    return ok(S.authorization_out(authorization))


@bp.post("/authorizations/<authorization_id>/determination")
@endpoint(["PayerReviewer"])
def render_determination(authorization_id):
    authorization = _authorization_or_404(authorization_id)
    body = read_body()
    decision = v_enum(body, "decision", C.DETERMINATION_DECISIONS)
    decision_reason = v_string(body, "decision_reason", required=False, min_len=1, max_len=240)
    approved_units = v_int(body, "approved_units", required=False, minimum=0, maximum=24)
    valid_from = v_instant(body, "valid_from", required=False)
    valid_through = v_instant(body, "valid_through", required=False)

    if approved_units is not None and approved_units > authorization["requested_units"]:
        fail(
            "ERR_INVALID_REQUEST",
            "Field 'approved_units' must not exceed requested_units.",
        )

    if authorization["status"] != "SUBMITTED":
        fail("ERR_AUTHORIZATION_STATE_INVALID")

    episode = db.episodes[authorization["episode_id"]]
    plan = db.payer_plans[episode["payer_plan_id"]]
    now = db.now()

    if decision == "APPROVED":
        granted = (
            approved_units if approved_units is not None else authorization["requested_units"]
        )
        authorization["status"] = "APPROVED"
        authorization["approved_units"] = granted
        authorization["units_remaining"] = (
            granted - authorization["units_reserved"] - authorization["units_consumed"]
        )
        authorization["determination_at"] = now
        authorization["decision_reason"] = decision_reason
        start = valid_from if valid_from is not None else now
        authorization["valid_from"] = start
        authorization["valid_through"] = (
            valid_through
            if valid_through is not None
            else add_days(start, plan["auth_validity_days"])
        )
        bump(authorization)

        episode["funding_state"] = "AUTHORIZED"
        bump(episode)
        return ok(S.authorization_out(authorization))

    # A denial always records the reason and the determination instant.
    authorization["status"] = "DENIED"
    authorization["decision_reason"] = decision_reason
    authorization["determination_at"] = now
    bump(authorization)

    if authorization["appeal_round"] >= plan["appeal_rounds_allowed"]:
        # Final denial: the three-level unfunding cascade of PRD 3.5.
        episode["funding_state"] = "UNFUNDED"
        bump(episode)
        cascades.terminate_enrollments(episode, "FUNDING_DENIED")

    return ok(S.authorization_out(authorization))


@bp.get("/authorizations/<authorization_id>")
@endpoint(AUTH_READ_ROLES)
def get_authorization(authorization_id):
    authorization = _authorization_or_404(authorization_id)
    return ok(S.authorization_out(authorization))


@bp.get("/authorizations")
@endpoint(AUTH_READ_ROLES)
def list_authorizations():
    episode_id = q_string("episode_id")
    clinician_id = q_string("exception_attested_by_clinician_id")
    status = q_enum("status", C.AUTHORIZATION_STATUSES)

    rows = []
    for authorization in db.authorizations.values():
        if episode_id is not None and authorization["episode_id"] != episode_id:
            continue
        if (
            clinician_id is not None
            and authorization["exception_attested_by_clinician_id"] != clinician_id
        ):
            continue
        if status is not None and authorization["status"] != status:
            continue
        rows.append(authorization)
    return paginate(rows, S.authorization_out)
