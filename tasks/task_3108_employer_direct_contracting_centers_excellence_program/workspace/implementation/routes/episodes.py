"""Episodes: intake, screening, reviews, scheduling, surgery, discharge,
day advance, readmissions, benefits, and care items."""
from flask import Blueprint, g

from core import (
    ApiError,
    body,
    db,
    dump,
    endpoint,
    f_bool,
    f_enum,
    f_int,
    f_str,
    new_row,
    paginate,
    q_str,
    respond_object,
    sort_created,
    touch,
)
from core import scope_employer
from domain import (
    CARE_PHASES,
    CONCLUSIONS,
    DOC_TYPES,
    BENEFIT_KINDS,
    EPISODE_CONCURRENT_SCOPE,
    EPISODE_MONTHLY_SCOPE,
    EPISODE_STATUSES,
    EPISODE_TERMINAL,
    QUIET_TAIL_DAYS,
    REPRICE_NOTICE_DAYS,
    SCREEN_RESULTS,
    TRAVELERS,
    cancel_episode,
    dump_episode,
    episode_template,
    estimate,
    get_or_404,
    pool_remaining,
    release_benefits,
    waive_open_care_items,
)

bp = Blueprint("episodes", __name__)


def _episode_employer_id(ep):
    contract = db.contracts.get(ep["contract_id"])
    return contract["employer_id"] if contract else None


def _bump_seq(ep):
    """Advance the episode day counter by one and return the new value."""
    ep["screen_seq"] += 1
    return ep["screen_seq"]


def _check_occ(ep, expected):
    if expected != ep["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_episode_version is stale.")


# ---------------------------------------------------------------------------
# Intake / read
# ---------------------------------------------------------------------------
@bp.route("/coe/episodes", methods=["POST"])
@endpoint("CareCoordinator")
def create_episode():
    data = body()
    patient_id = f_str(data, "patient_id")
    contract_id = f_str(data, "contract_id")
    intake_request_id = f_str(data, "intake_request_id")
    triage_rank = f_int(data, "triage_rank", required=False, default=0, choices=(0, 1))
    patient = db.patients.get(patient_id)
    if patient is None:
        raise ApiError("ERR_NOT_FOUND", "Patient does not exist.")
    contract = db.contracts.get(contract_id)
    if contract is None:
        raise ApiError("ERR_NOT_FOUND", "Contract does not exist.")
    template = db.templates.get(contract["template_id"])
    family = template["procedure_family"] if template else None
    employer_id = contract["employer_id"]

    # Intake idempotency per employer (priority tier 9).
    payload = {
        "patient_id": patient_id,
        "contract_id": contract_id,
        "triage_rank": triage_rank,
    }
    for other in db.episodes.values():
        other_contract = db.contracts.get(other["contract_id"])
        if other_contract is None or other_contract["employer_id"] != employer_id:
            continue
        if other["intake_request_id"] == intake_request_id:
            if other["_intake_payload"] == payload:
                return respond_object(dump_episode(other), status=201)
            raise ApiError(
                "ERR_DUPLICATE_INTAKE_REQUEST",
                "intake_request_id already used by this employer with a different payload.",
            )

    # One active episode per patient per procedure family (priority tier 9).
    for other in db.episodes.values():
        if (
            other["patient_id"] == patient_id
            and other["family"] == family
            and other["status"] not in EPISODE_TERMINAL
        ):
            raise ApiError(
                "ERR_ACTIVE_EPISODE_EXISTS",
                "Patient already has a non-terminal episode in this procedure family.",
            )

    if patient["employer_id"] != employer_id:
        raise ApiError(
            "ERR_PATIENT_EMPLOYER_MISMATCH",
            "Patient does not belong to the employer that owns the contract.",
        )
    employer = db.employers.get(employer_id)
    if employer is not None and employer["status"] != "ACTIVE":
        raise ApiError("ERR_EMPLOYER_TERMINATED", "Employer is TERMINATED.")

    row = new_row(
        "episode",
        patient_id=patient_id,
        contract_id=contract_id,
        family=family,
        intake_request_id=intake_request_id,
        status="INTAKE_PENDING",
        screen_seq=0,
        scheduled_start_seq=0,
        warranty_end_seq=0,
        warranty_close_seq=0,
        surgery_done_seq=0,
        discharge_seq=0,
        price_rule=None,
        applied_bundle_price_cents=None,
        applied_rate_components=None,
        closed_outcome=None,
        triage_rank=triage_rank,
        _intake_payload=payload,
        _outlier_flag=False,
        _outlier_expected=None,
        _approve_seq=None,
        _approve_clock=None,
        _terminal_seq=None,
        _terminal_clock=None,
        _first_scheduled_start=None,
        _first_scheduled_clock=None,
    )
    db.episodes[row["id"]] = row
    return respond_object(dump_episode(row), status=201)


@bp.route("/coe/episodes", methods=["GET"])
@endpoint("ProgramAdmin", "EmployerRep", "CareCoordinator", "ClaimsAdmin")
def list_episodes():
    rows = list(db.episodes.values())
    contract_id = q_str("contract_id")
    if contract_id is not None:
        rows = [r for r in rows if r["contract_id"] == contract_id]
    patient_id = q_str("patient_id")
    if patient_id is not None:
        rows = [r for r in rows if r["patient_id"] == patient_id]
    status = q_str("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if g.role == "EmployerRep":
        rows = [r for r in rows if _episode_employer_id(r) == g.user_id]
    return paginate(sort_created(rows), dumper=dump)


@bp.route("/coe/episodes/<ep_id>", methods=["GET"])
@endpoint("ProgramAdmin", "EmployerRep", "CareCoordinator", "PhysicianReviewer", "ClaimsAdmin")
def get_episode(ep_id):
    ep = get_or_404("episodes", ep_id)
    scope_employer(_episode_employer_id(ep))
    view = q_str("view", "employer")
    if view not in ("employer", "clinic"):
        raise ApiError("ERR_VIEW_UNKNOWN", "view must be employer or clinic.")
    return respond_object(dump(ep, {"estimated_total_billed_cents": estimate(ep, view)}))


# ---------------------------------------------------------------------------
# Screenings
# ---------------------------------------------------------------------------
@bp.route("/coe/episodes/<ep_id>/screenings", methods=["POST"])
@endpoint("CareCoordinator")
def create_screening(ep_id):
    ep = get_or_404("episodes", ep_id)
    data = body()
    doc_type = f_enum(data, "doc_type", DOC_TYPES)
    result = f_enum(data, "result", SCREEN_RESULTS)
    if ep["status"] not in ("INTAKE_PENDING", "SCREENING"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "Screenings are only accepted while the episode is INTAKE_PENDING or SCREENING.",
        )
    if ep["status"] == "INTAKE_PENDING":
        ep["status"] = "SCREENING"
    seq = _bump_seq(ep)
    row = new_row(
        "screening",
        audited=False,
        episode_id=ep["id"],
        doc_type=doc_type,
        result=result,
        screen_seq=seq,
    )
    db.screenings[row["id"]] = row
    if result == "CANDIDATE":
        _bump_seq(ep)
        ep["status"] = "SOR_PENDING"
    else:
        _bump_seq(ep)
        ep["status"] = "CANCELLED"
        ep["_terminal_seq"] = ep["screen_seq"]
        ep["_terminal_clock"] = db.clock
    touch(ep)
    return respond_object(dump(row), status=201)


@bp.route("/coe/episodes/<ep_id>/screenings", methods=["GET"])
@endpoint("ProgramAdmin", "CareCoordinator", "PhysicianReviewer")
def list_screenings(ep_id):
    ep = get_or_404("episodes", ep_id)
    rows = [s for s in db.screenings.values() if s["episode_id"] == ep["id"]]
    return paginate(sort_created(rows))


@bp.route("/coe/screenings/<screening_id>", methods=["GET"])
@endpoint("ProgramAdmin", "CareCoordinator", "PhysicianReviewer")
def get_screening(screening_id):
    row = get_or_404("screenings", screening_id)
    return respond_object(dump(row))


# ---------------------------------------------------------------------------
# Second-opinion reviews
# ---------------------------------------------------------------------------
def _approval_gates(ep, contract):
    """Coverage window (tier 8) and capacity gates (tier 10)."""
    if not (contract["effective_from"] <= db.clock < contract["effective_to"]):
        raise ApiError(
            "ERR_OUTSIDE_COVERAGE_WINDOW",
            "Approval is outside the contract coverage window.",
        )
    clock = db.clock
    approved_this_month = 0
    active_now = 0
    for other in db.episodes.values():
        if other["contract_id"] != contract["id"]:
            continue
        if other["status"] in EPISODE_MONTHLY_SCOPE:
            stamp = other.get("_approve_clock")
            if (
                stamp is not None
                and stamp.year == clock.year
                and stamp.month == clock.month
            ):
                approved_this_month += 1
        if other["status"] in EPISODE_CONCURRENT_SCOPE:
            active_now += 1
    if approved_this_month >= contract["episode_cap_per_month"]:
        raise ApiError(
            "ERR_CAPACITY_EXCEEDED", "Monthly episode cap reached on the contract."
        )
    if active_now >= contract["concurrent_capacity"]:
        raise ApiError(
            "ERR_CAPACITY_EXCEEDED", "Concurrent capacity reached on the contract."
        )


def _apply_price_basis(ep, contract, seq_at_approval):
    """price_basis_determination: LOCKED vs REPRICED with the 30-day notice rule."""
    history = contract["change_history"]
    if contract["reprice_count"] == 0:
        ep["price_rule"] = "LOCKED"
        ep["applied_bundle_price_cents"] = contract["bundle_price_cents"]
        ep["applied_rate_components"] = dict(contract["rate_components"])
        return
    latest = history[-1]
    if (seq_at_approval - latest["effective_from_seq"]) >= REPRICE_NOTICE_DAYS:
        ep["price_rule"] = "REPRICED"
        ep["applied_bundle_price_cents"] = latest["new_bundle_price_cents"]
        ep["applied_rate_components"] = dict(latest["new_rate_components"])
        return
    ep["price_rule"] = "LOCKED"
    if contract["reprice_count"] == 1:
        ep["applied_bundle_price_cents"] = contract["_created_bundle_price_cents"]
        ep["applied_rate_components"] = dict(contract["_created_rate_components"])
    else:
        prev = history[-2]
        ep["applied_bundle_price_cents"] = prev["new_bundle_price_cents"]
        ep["applied_rate_components"] = dict(prev["new_rate_components"])


@bp.route("/coe/episodes/<ep_id>/reviews", methods=["POST"])
@endpoint("PhysicianReviewer")
def create_review(ep_id):
    ep = get_or_404("episodes", ep_id)
    data = body()
    conclusion = f_enum(data, "conclusion", CONCLUSIONS)
    expected = f_int(data, "expected_episode_version", minimum=0)
    if ep["status"] not in ("SOR_PENDING", "SOR_REVIEW"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "Reviews are only accepted while the episode is SOR_PENDING or SOR_REVIEW.",
        )
    _check_occ(ep, expected)

    prev_status = ep["status"]
    if conclusion == "MORE_INFO_NEEDED":
        seq = _bump_seq(ep)
        ep["status"] = "SOR_REVIEW"
    elif conclusion == "SURGERY_UNNECESSARY":
        seq = _bump_seq(ep)
        ep["status"] = "AVOIDED"
        ep["_terminal_seq"] = seq
        ep["_terminal_clock"] = db.clock
        release_benefits(ep)
        waive_open_care_items(ep)
    else:  # SURGERY_INDICATED
        contract = db.contracts[ep["contract_id"]]
        if contract["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "Contract is not ACTIVE.")
        _approval_gates(ep, contract)
        seq = _bump_seq(ep)
        ep["status"] = "APPROVED"
        _apply_price_basis(ep, contract, seq)
        ep["_approve_seq"] = seq
        ep["_approve_clock"] = db.clock

    row = new_row(
        "review",
        audited=False,
        episode_id=ep["id"],
        reviewer_id=g.user_id,
        conclusion=conclusion,
        screen_seq=seq,
        prev_status=prev_status,
    )
    db.reviews[row["id"]] = row
    touch(ep)
    return respond_object(dump(row), status=201)


@bp.route("/coe/episodes/<ep_id>/reviews", methods=["GET"])
@endpoint("ProgramAdmin", "CareCoordinator", "PhysicianReviewer")
def list_reviews(ep_id):
    ep = get_or_404("episodes", ep_id)
    rows = [r for r in db.reviews.values() if r["episode_id"] == ep["id"]]
    return paginate(sort_created(rows))


@bp.route("/coe/reviews/<review_id>", methods=["GET"])
@endpoint("ProgramAdmin", "CareCoordinator", "PhysicianReviewer")
def get_review(review_id):
    row = get_or_404("reviews", review_id)
    return respond_object(dump(row))


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------
@bp.route("/coe/episodes/<ep_id>/schedule", methods=["POST"])
@endpoint("CareCoordinator")
def schedule_episode(ep_id):
    ep = get_or_404("episodes", ep_id)
    data = body()
    requested_day = f_int(data, "requested_day_seq", minimum=0)
    expected = f_int(data, "expected_episode_version", minimum=0)
    if ep["status"] not in ("APPROVED", "SCHEDULING"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "Scheduling requires the episode to be APPROVED or SCHEDULING.",
        )
    _check_occ(ep, expected)
    if requested_day <= ep["screen_seq"]:
        raise ApiError(
            "ERR_OUTSIDE_COVERAGE_WINDOW",
            "requested_day_seq must be strictly greater than the current day counter.",
        )
    if ep["triage_rank"] == 0:
        for other in db.episodes.values():
            if (
                other["id"] != ep["id"]
                and other["contract_id"] == ep["contract_id"]
                and other["family"] == ep["family"]
                and other["status"] == "APPROVED"
                and other["triage_rank"] == 1
                and (other.get("_approve_seq") or 0) < (ep.get("_approve_seq") or 0)
            ):
                raise ApiError(
                    "ERR_PRIORITY_BLOCKED",
                    "An earlier-approved urgent episode takes scheduling priority.",
                )
    ep["scheduled_start_seq"] = requested_day
    if ep["_first_scheduled_start"] is None:
        ep["_first_scheduled_start"] = requested_day
        ep["_first_scheduled_clock"] = db.clock
    ep["status"] = "SCHEDULING"
    _bump_seq(ep)
    touch(ep)
    return respond_object(dump_episode(ep))


# ---------------------------------------------------------------------------
# Care items
# ---------------------------------------------------------------------------
@bp.route("/coe/episodes/<ep_id>/care-items", methods=["POST"])
@endpoint("CareCoordinator")
def create_care_item(ep_id):
    ep = get_or_404("episodes", ep_id)
    data = body()
    phase = f_enum(data, "phase", CARE_PHASES)
    provider = f_str(data, "local_provider_name")
    required = f_bool(data, "required")
    if ep["status"] not in ("SCHEDULING", "PRE_OP"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "Care items are only added while the episode is SCHEDULING or PRE_OP.",
        )
    if ep["status"] == "SCHEDULING":
        if phase != "PRE_OP":
            raise ApiError(
                "ERR_INVALID_STATE",
                "The first care item on a SCHEDULING episode must be PRE_OP.",
            )
        ep["status"] = "PRE_OP"
        touch(ep)
    row = new_row(
        "care_item",
        episode_id=ep["id"],
        phase=phase,
        local_provider_name=provider,
        required=required,
        status="OPEN",
    )
    db.care_items[row["id"]] = row
    return respond_object(dump(row), status=201)


@bp.route("/coe/episodes/<ep_id>/care-items", methods=["GET"])
@endpoint("ProgramAdmin", "CareCoordinator", "PhysicianReviewer")
def list_care_items(ep_id):
    ep = get_or_404("episodes", ep_id)
    rows = [c for c in db.care_items.values() if c["episode_id"] == ep["id"]]
    return paginate(sort_created(rows))


@bp.route("/coe/care-items/<item_id>", methods=["GET"])
@endpoint("ProgramAdmin", "CareCoordinator")
def get_care_item(item_id):
    row = get_or_404("care_items", item_id)
    return respond_object(dump(row))


@bp.route("/coe/care-items/<item_id>/complete", methods=["POST"])
@endpoint("CareCoordinator")
def complete_care_item(item_id):
    row = get_or_404("care_items", item_id)
    if row["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Care plan item is not OPEN.")
    row["status"] = "DONE"
    touch(row)
    return respond_object(dump(row))


@bp.route("/coe/care-items/<item_id>/waive", methods=["POST"])
@endpoint("CareCoordinator")
def waive_care_item(item_id):
    row = get_or_404("care_items", item_id)
    if row["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Care plan item is not OPEN.")
    row["status"] = "WAIVED"
    touch(row)
    return respond_object(dump(row))


# ---------------------------------------------------------------------------
# Surgery / discharge / advance-day
# ---------------------------------------------------------------------------
@bp.route("/coe/episodes/<ep_id>/surgery-complete", methods=["POST"])
@endpoint("CareCoordinator")
def surgery_complete(ep_id):
    ep = get_or_404("episodes", ep_id)
    data = body()
    expected = f_int(data, "expected_episode_version", minimum=0)
    if ep["status"] != "PRE_OP":
        raise ApiError("ERR_INVALID_STATE", "Episode is not in PRE_OP.")
    _check_occ(ep, expected)
    if ep["screen_seq"] < ep["scheduled_start_seq"]:
        raise ApiError(
            "ERR_OUTSIDE_COVERAGE_WINDOW",
            "Surgery cannot complete before its scheduled day.",
        )
    for item in db.care_items.values():
        if (
            item["episode_id"] == ep["id"]
            and item["phase"] == "PRE_OP"
            and item["required"]
            and item["status"] == "OPEN"
        ):
            raise ApiError(
                "ERR_REQUIRED_CARE_INCOMPLETE",
                "A required PRE_OP care item is still OPEN.",
            )
    seq = _bump_seq(ep)
    ep["surgery_done_seq"] = seq
    ep["status"] = "SURGERY_DONE"
    touch(ep)
    return respond_object(dump_episode(ep))


@bp.route("/coe/episodes/<ep_id>/discharge", methods=["POST"])
@endpoint("CareCoordinator")
def discharge(ep_id):
    ep = get_or_404("episodes", ep_id)
    data = body()
    expected = f_int(data, "expected_episode_version", minimum=0)
    if ep["status"] != "SURGERY_DONE":
        raise ApiError("ERR_INVALID_STATE", "Episode is not in SURGERY_DONE.")
    _check_occ(ep, expected)
    template = episode_template(ep)
    seq = _bump_seq(ep)
    ep["discharge_seq"] = seq
    ep["warranty_end_seq"] = seq + template["warranty_days"]
    ep["warranty_close_seq"] = ep["warranty_end_seq"] + QUIET_TAIL_DAYS
    ep["status"] = "POST_OP_TRACKING"
    touch(ep)
    return respond_object(dump_episode(ep))


def _closure_preconditions(ep):
    """Raises when closure gates fail; returns silently when they hold."""
    for item in db.care_items.values():
        if (
            item["episode_id"] == ep["id"]
            and item["phase"] == "POST_OP"
            and item["required"]
            and item["status"] == "OPEN"
        ):
            raise ApiError(
                "ERR_REQUIRED_CARE_INCOMPLETE",
                "A required POST_OP care item is still OPEN.",
            )
    for claim in db.claims.values():
        if claim["episode_id"] == ep["id"] and claim["status"] == "PENDING":
            raise ApiError("ERR_PENDING_CLAIMS", "A claim on the episode is still PENDING.")


def _close_episode(ep):
    in_window_readmit = any(
        r["episode_id"] == ep["id"] and not r["out_of_window"]
        for r in db.readmissions.values()
    )
    ep["closed_outcome"] = "READMITTED" if in_window_readmit else "CLEAN"
    ep["status"] = "CLOSED"
    ep["_terminal_seq"] = ep["screen_seq"]
    ep["_terminal_clock"] = db.clock
    release_benefits(ep)
    for claim in db.claims.values():
        if claim["episode_id"] == ep["id"] and claim["status"] == "APPROVED":
            claim["status"] = "ABSORBED"
            touch(claim)


@bp.route("/coe/episodes/<ep_id>/advance-day", methods=["POST"])
@endpoint("CareCoordinator")
def advance_day(ep_id):
    ep = get_or_404("episodes", ep_id)
    if ep["status"] in EPISODE_TERMINAL:
        raise ApiError("ERR_INVALID_STATE", "Episode is in a terminal state.")
    if ep["status"] != "POST_OP_TRACKING":
        # The day counter advances in any live state (PRD §2.7 lists the
        # day-counter advance among the per-episode sequence events); the
        # warranty closure logic below only applies during POST_OP_TRACKING.
        _bump_seq(ep)
        touch(ep)
        return respond_object(dump_episode(ep))
    at_or_past_horizon = ep["screen_seq"] + 1 >= ep["warranty_close_seq"]
    if at_or_past_horizon:
        _closure_preconditions(ep)
    _bump_seq(ep)
    if at_or_past_horizon:
        _close_episode(ep)
    touch(ep)
    return respond_object(dump_episode(ep))


# ---------------------------------------------------------------------------
# Readmissions
# ---------------------------------------------------------------------------
@bp.route("/coe/episodes/<ep_id>/readmissions", methods=["POST"])
@endpoint("CareCoordinator")
def create_readmission(ep_id):
    ep = get_or_404("episodes", ep_id)
    data = body()
    related = f_bool(data, "related")
    billed = f_int(data, "provider_billed_cents", minimum=0)
    if ep["status"] != "POST_OP_TRACKING":
        raise ApiError("ERR_INVALID_STATE", "Episode is not in POST_OP_TRACKING.")
    recorded_seq = ep["screen_seq"]
    template = episode_template(ep)
    if recorded_seq >= ep["warranty_end_seq"]:
        out_of_window = True
        absorbed = 0
    else:
        out_of_window = False
        if template["readmit_policy"] == "ALL_CAUSE":
            absorbed = billed
        else:
            absorbed = billed if related else 0
    row = new_row(
        "readmission",
        episode_id=ep["id"],
        related=related,
        provider_billed_cents=billed,
        recorded_seq=recorded_seq,
        out_of_window=out_of_window,
        absorbed_cents=absorbed,
    )
    db.readmissions[row["id"]] = row
    _bump_seq(ep)
    ep["status"] = "POST_OP_TRACKING"
    touch(ep)
    return respond_object(dump(row), status=201)


@bp.route("/coe/episodes/<ep_id>/readmissions", methods=["GET"])
@endpoint("ProgramAdmin", "CareCoordinator", "ClaimsAdmin", "EmployerRep")
def list_readmissions(ep_id):
    ep = get_or_404("episodes", ep_id)
    scope_employer(_episode_employer_id(ep))
    rows = [r for r in db.readmissions.values() if r["episode_id"] == ep["id"]]
    return paginate(sort_created(rows))


@bp.route("/coe/readmissions/<readmission_id>", methods=["GET"])
@endpoint("ProgramAdmin", "CareCoordinator", "ClaimsAdmin", "EmployerRep")
def get_readmission(readmission_id):
    row = get_or_404("readmissions", readmission_id)
    ep = db.episodes.get(row["episode_id"])
    if ep is not None:
        scope_employer(_episode_employer_id(ep))
    return respond_object(dump(row))


# ---------------------------------------------------------------------------
# Benefits
# ---------------------------------------------------------------------------
@bp.route("/coe/episodes/<ep_id>/benefits", methods=["POST"])
@endpoint("CareCoordinator")
def create_benefit(ep_id):
    ep = get_or_404("episodes", ep_id)
    data = body()
    kind = f_enum(data, "kind", BENEFIT_KINDS)
    traveler = f_enum(data, "traveler", TRAVELERS)
    amount = f_int(data, "amount_cents", minimum=1)
    expected = f_int(data, "expected_episode_version", minimum=0)
    if ep["status"] in EPISODE_TERMINAL:
        raise ApiError(
            "ERR_INVALID_STATE", "Benefits cannot be administered on a terminal episode."
        )
    _check_occ(ep, expected)
    contract = db.contracts[ep["contract_id"]]
    if traveler == "COMPANION" and not contract["companion_allowed"]:
        raise ApiError(
            "ERR_BENEFIT_KIND_MISMATCH",
            "Companion benefits are not covered under this contract.",
        )
    if amount > pool_remaining(ep, kind):
        raise ApiError(
            "ERR_BENEFIT_POOL_EXCEEDED",
            "Benefit exceeds the remaining per-episode pool.",
        )
    row = new_row(
        "benefit",
        episode_id=ep["id"],
        kind=kind,
        traveler=traveler,
        amount_cents=amount,
        status="ADMINISTERED",
    )
    db.benefits[row["id"]] = row
    touch(ep)
    return respond_object(dump(row), status=201)


@bp.route("/coe/episodes/<ep_id>/benefits", methods=["GET"])
@endpoint("ProgramAdmin", "CareCoordinator", "EmployerRep")
def list_benefits(ep_id):
    ep = get_or_404("episodes", ep_id)
    scope_employer(_episode_employer_id(ep))
    rows = [b for b in db.benefits.values() if b["episode_id"] == ep["id"]]
    return paginate(sort_created(rows))


@bp.route("/coe/benefits/<benefit_id>", methods=["GET"])
@endpoint("ProgramAdmin", "CareCoordinator", "EmployerRep")
def get_benefit(benefit_id):
    row = get_or_404("benefits", benefit_id)
    ep = db.episodes.get(row["episode_id"])
    if ep is not None:
        scope_employer(_episode_employer_id(ep))
    return respond_object(dump(row))
