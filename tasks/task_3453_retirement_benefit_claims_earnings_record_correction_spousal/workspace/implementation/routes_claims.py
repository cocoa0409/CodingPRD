"""Benefit claim lifecycle (PRD §3.4, §3.6): filing guards, entitlement
adjudication with the type-specific gates, denial/reopen with adjudicator
segregation, withdrawal of application (12-month window, full simultaneous
repayment, once per lifetime), and voluntary suspension/resumption with
delayed retirement credits.
"""

from datetime import timedelta

from flask import Blueprint

import calc
import timeutil as tu
import validation as v
from benefits import (
    covered_pia_for_aux,
    covered_retirement_claim,
    covered_worker_id_of,
    recompute_claim,
    reevaluate_family_maximum,
    resume_claim,
    worker_pia_context,
)
from db import store, stamp_common_new, touch
from envelope import ok
from errors import (
    ApiError,
    ERR_AGE_INELIGIBLE,
    ERR_CLAIM_ALREADY_TERMINAL,
    ERR_CLAIM_NOT_FOUND,
    ERR_DIVORCE_WAITING_PERIOD,
    ERR_DUPLICATE_ACTIVE_CLAIM,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_MARRIAGE_DURATION_INSUFFICIENT,
    ERR_RELATIONSHIP_NOT_FOUND,
    ERR_RELATIONSHIP_NOT_VERIFIED,
    ERR_REOPEN_WINDOW_EXPIRED,
    ERR_REPAYMENT_SHORTFALL,
    ERR_SAME_ADJUDICATOR,
    ERR_SPOUSE_NOT_ENTITLED,
    ERR_STALE_VERSION,
    ERR_SUSPENSION_AGE_INELIGIBLE,
    ERR_WITHDRAWAL_ALREADY_USED,
    ERR_WITHDRAWAL_WINDOW_EXPIRED,
    ERR_WORKER_DECEASED,
    ERR_WORKER_NOT_DECEASED,
    ERR_WORKER_NOT_FOUND,
)
from security import (
    ROLE_CLAIMANT,
    ROLE_CLAIMS_SPECIALIST,
    ROLE_SENIOR_ADJUDICATOR,
    authenticate,
    claimant_owns,
    require_role,
)
from serializers import claim_dict, claim_total_paid_cents

bp = Blueprint("claims", __name__)

CLAIM_TYPES = {"RETIREMENT", "SPOUSAL", "DIVORCED_SPOUSAL", "SURVIVOR"}
AUX_TYPES = {"SPOUSAL", "DIVORCED_SPOUSAL", "SURVIVOR"}
NON_TERMINAL_CLAIM_STATES = {"FILED", "ENTITLED", "DENIED", "SUSPENDED"}
REOPEN_WINDOW_DAYS = 60
WITHDRAWAL_WINDOW_MONTHS = 12


def load_claim(claim_id):
    c = store.claims.get(claim_id)
    if c is None:
        raise ApiError(ERR_CLAIM_NOT_FOUND, f"No claim with id {claim_id}.")
    return c


def _require_not_terminal(claim):
    if claim["status"] in ("WITHDRAWN", "TERMINATED"):
        raise ApiError(
            ERR_CLAIM_ALREADY_TERMINAL,
            "Claim is WITHDRAWN or TERMINATED; no further actions exist.",
        )


@bp.route("/ssa/claims", methods=["POST"])
def create_claim():
    ctx = authenticate()
    require_role(ctx, {ROLE_CLAIMANT, ROLE_CLAIMS_SPECIALIST})
    body = v.get_body()
    worker_id = v.req_str(body, "worker_id")
    # Layer 3 — ownership precedes the remaining body checks (PRD §2.9).
    claimant_owns(ctx, worker_id)
    claim_type = v.req_enum(body, "claim_type", CLAIM_TYPES)
    entitlement_month = v.req_month(body, "entitlement_month")
    relationship_id = body.get("relationship_id")
    if claim_type in AUX_TYPES:
        if not isinstance(relationship_id, str) or not relationship_id:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "relationship_id is required for SPOUSAL, DIVORCED_SPOUSAL and SURVIVOR claims.",
            )
    elif relationship_id is not None:
        raise ApiError(ERR_INVALID_REQUEST, "relationship_id is forbidden for RETIREMENT claims.")
    worker = store.workers.get(worker_id)
    if worker is None:
        raise ApiError(ERR_WORKER_NOT_FOUND, f"No worker with id {worker_id}.")
    # Layer 8 — no new RETIREMENT claim for a DECEASED worker.
    if claim_type == "RETIREMENT" and worker["status"] == "DECEASED":
        raise ApiError(ERR_WORKER_DECEASED, "No new RETIREMENT claim for a DECEASED worker.")
    # Layer 9 — at most one non-terminal claim per (worker, claim_type);
    # WITHDRAWN and TERMINATED claims do not block re-filing.
    for other in store.claims.values():
        if (
            other["worker_id"] == worker_id
            and other["claim_type"] == claim_type
            and other["status"] in NON_TERMINAL_CLAIM_STATES
        ):
            raise ApiError(
                ERR_DUPLICATE_ACTIVE_CLAIM,
                "A non-terminal claim already exists for this worker and claim type.",
            )
    ent = tu.parse_month_str(entitlement_month)
    claim = stamp_common_new(
        {
            "worker_id": worker_id,
            "claim_type": claim_type,
            "entitlement_month": entitlement_month,
            "relationship_id": relationship_id,
            "status": "FILED",
            "claiming_age_months": tu.age_months_at(worker["birth_year"], worker["birth_month"], ent),
            "aime_cents": None,
            "pia_cents": None,
            "reduction_months": None,
            "drc_months": 0,
            "monthly_benefit_cents": 0,
            "underpayment_credit_cents": 0,
            "recovery_mode": "FULL",
            "has_active_payee": False,
            "suspended_since": None,
            "decided_by": None,
            "decided_at": None,
            "denial_reason": None,
            "partial_rate_cents": None,
        }
    )
    store.claims[claim["id"]] = claim
    return ok(claim_dict(claim), 201)


@bp.route("/ssa/claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    ctx = authenticate()
    require_role(
        ctx,
        {ROLE_CLAIMS_SPECIALIST, ROLE_SENIOR_ADJUDICATOR, "ProgramAdministrator", ROLE_CLAIMANT},
    )
    claim = load_claim(claim_id)
    claimant_owns(ctx, claim["worker_id"])
    return ok(claim_dict(claim))


@bp.route("/ssa/claims/<claim_id>/approve", methods=["POST"])
def approve_claim(claim_id):
    ctx = authenticate()
    require_role(ctx, {ROLE_CLAIMS_SPECIALIST})
    claim = load_claim(claim_id)
    _require_not_terminal(claim)
    if claim["status"] != "FILED":
        raise ApiError(ERR_INVALID_STATE, "Only a FILED claim can be approved.")
    worker = store.workers[claim["worker_id"]]
    ctype = claim["claim_type"]
    # Layer 8 — RETIREMENT requires the worker themself LIVING.
    if ctype == "RETIREMENT" and worker["status"] == "DECEASED":
        raise ApiError(ERR_WORKER_DECEASED, "Cannot approve a RETIREMENT claim for a DECEASED worker.")
    # Layer 5 — auxiliary claims resolve their relationship FK.
    rel = None
    covered = None
    covered_rc = None
    if ctype in AUX_TYPES:
        rel = store.relationships.get(claim["relationship_id"])
        if rel is None:
            raise ApiError(
                ERR_RELATIONSHIP_NOT_FOUND, f"No relationship with id {claim['relationship_id']}."
            )
        covered = store.workers.get(rel["worker_id"])
        covered_rc = covered_retirement_claim(store, rel["worker_id"])
    ent = tu.parse_month_str(claim["entitlement_month"])
    # Layer 10 — divorced-spouse independent-entitlement wait.
    if ctype == "DIVORCED_SPOUSAL" and covered_rc is None:
        divorce = tu.parse_date_str(rel["divorce_date"])
        if tu.months_between_date_and_month(divorce, ent) < 24:
            raise ApiError(
                ERR_DIVORCE_WAITING_PERIOD,
                "Fewer than 24 months have passed since the divorce and the covered worker is not entitled.",
            )
    # Layer 11 — referential entitlement.
    if ctype in AUX_TYPES:
        if rel["status"] != "VERIFIED":
            raise ApiError(ERR_RELATIONSHIP_NOT_VERIFIED, "The relationship is not VERIFIED.")
        if ctype == "SPOUSAL" and covered_rc is None:
            raise ApiError(
                ERR_SPOUSE_NOT_ENTITLED,
                "The covered worker holds no ENTITLED or SUSPENDED RETIREMENT claim.",
            )
        if ctype == "SURVIVOR" and (covered is None or covered["status"] != "DECEASED"):
            raise ApiError(ERR_WORKER_NOT_DECEASED, "The covered worker is not DECEASED.")
    # Layer 12 — claiming-age floors and ceiling.
    claiming_age = claim["claiming_age_months"]
    floor_months = calc.SURVIVOR_MIN_AGE_MONTHS if ctype == "SURVIVOR" else calc.MIN_CLAIM_AGE_MONTHS
    if claiming_age < floor_months or claiming_age > calc.MAX_DRC_AGE_MONTHS:
        raise ApiError(ERR_AGE_INELIGIBLE, "Claiming age is outside the permitted bounds.")
    # Layer 12 — marriage durations.
    marriage_start = tu.parse_date_str(rel["marriage_date"]) if rel else None
    if ctype == "SPOUSAL":
        if tu.months_between_date_and_month(marriage_start, ent) < 12:
            raise ApiError(
                ERR_MARRIAGE_DURATION_INSUFFICIENT, "Marriage shorter than 12 months at entitlement."
            )
    elif ctype == "DIVORCED_SPOUSAL":
        divorce = tu.parse_date_str(rel["divorce_date"])
        if tu.months_between_dates(marriage_start, divorce) < 120:
            raise ApiError(
                ERR_MARRIAGE_DURATION_INSUFFICIENT, "Marriage shorter than 120 months."
            )
    elif ctype == "SURVIVOR":
        death = tu.parse_date_str(covered["death_date"])
        if tu.months_between_dates(marriage_start, death) < 9:
            raise ApiError(
                ERR_MARRIAGE_DURATION_INSUFFICIENT, "Marriage shorter than 9 months at death."
            )
    # Compute and store the full benefit picture (PRD §3.5).
    if ctype == "RETIREMENT":
        aime = calc.compute_aime_cents(store, worker)
        pia = calc.compute_pia_cents(store, worker, aime)
        claim["aime_cents"] = aime
        claim["pia_cents"] = pia
        claim["reduction_months"] = max(0, worker["fra_months"] - claiming_age)
        claim["monthly_benefit_cents"] = calc.age_adjusted_monthly_cents(
            pia, worker["fra_months"], claiming_age, claim["drc_months"]
        )
    elif ctype in ("SPOUSAL", "DIVORCED_SPOUSAL"):
        worker_pia, aime = covered_pia_for_aux(store, rel["worker_id"])
        claim["aime_cents"] = aime
        claim["pia_cents"] = worker_pia
        claim["reduction_months"] = max(0, worker["fra_months"] - claiming_age)
        claim["status"] = "ENTITLED"
        claim["decided_by"] = ctx["user_id"]
        claim["decided_at"] = store.now_iso()
        touch(claim)
        # Family maximum spans every ENTITLED auxiliary on this record; the
        # new claim's own version increment is the one above.
        reevaluate_family_maximum(rel["worker_id"], bump_versions=True, skip_touch_id=claim["id"])
        return ok(claim_dict(claim))
    else:  # SURVIVOR
        aime, worker_pia = worker_pia_context(store, covered)
        claim["aime_cents"] = aime
        claim["pia_cents"] = worker_pia
        claim["reduction_months"] = max(0, calc.SURVIVOR_FRA_MONTHS - claiming_age)
        amount = calc.survivor_benefit_cents(worker_pia, claiming_age)
        claim["monthly_benefit_cents"] = max(0, amount - calc.gpo_offset_cents(worker))
    claim["status"] = "ENTITLED"
    claim["decided_by"] = ctx["user_id"]
    claim["decided_at"] = store.now_iso()
    touch(claim)
    return ok(claim_dict(claim))


@bp.route("/ssa/claims/<claim_id>/deny", methods=["POST"])
def deny_claim(claim_id):
    ctx = authenticate()
    require_role(ctx, {ROLE_CLAIMS_SPECIALIST})
    # Layer 4 — body well-formedness precedes path resolution (PRD §2.9).
    body = v.get_body()
    reason = v.req_str(body, "denial_reason")
    claim = load_claim(claim_id)
    _require_not_terminal(claim)
    if claim["status"] != "FILED":
        raise ApiError(ERR_INVALID_STATE, "Only a FILED claim can be denied.")
    claim["status"] = "DENIED"
    claim["decided_by"] = ctx["user_id"]
    claim["decided_at"] = store.now_iso()
    claim["denial_reason"] = reason
    touch(claim)
    return ok(claim_dict(claim))


@bp.route("/ssa/claims/<claim_id>/reopen", methods=["POST"])
def reopen_claim(claim_id):
    ctx = authenticate()
    require_role(ctx, {ROLE_SENIOR_ADJUDICATOR})
    # Layer 4 — body well-formedness precedes path resolution (PRD §2.9).
    body = v.get_body()
    v.req_str(body, "reopen_reason")
    claim = load_claim(claim_id)
    _require_not_terminal(claim)
    if claim["status"] != "DENIED":
        raise ApiError(ERR_INVALID_STATE, "Only a DENIED claim can be reopened.")
    if ctx["user_id"] == claim["decided_by"]:
        raise ApiError(ERR_SAME_ADJUDICATOR, "The denying operator may not reopen this claim.")
    decided = tu.parse_iso8601(claim["decided_at"])
    if store.clock > decided + timedelta(days=REOPEN_WINDOW_DAYS):
        raise ApiError(ERR_REOPEN_WINDOW_EXPIRED, "More than 60 days have passed since the denial.")
    claim["status"] = "FILED"
    claim["denial_reason"] = None
    claim["decided_by"] = None
    claim["decided_at"] = None
    touch(claim)
    return ok(claim_dict(claim))


@bp.route("/ssa/claims/<claim_id>/withdraw", methods=["POST"])
def withdraw_claim(claim_id):
    ctx = authenticate()
    require_role(ctx, {ROLE_CLAIMANT, ROLE_CLAIMS_SPECIALIST})
    claim = load_claim(claim_id)
    claimant_owns(ctx, claim["worker_id"])
    body = v.get_body()
    repaid = v.req_int(body, "repaid_amount_cents", min_v=0)
    _require_not_terminal(claim)
    if claim["status"] != "ENTITLED":
        raise ApiError(ERR_INVALID_STATE, "Only an ENTITLED claim can be withdrawn.")
    # Layer 10 — no more than 12 months between entitlement and now.
    ent = tu.parse_month_str(claim["entitlement_month"])
    if tu.months_between_ym(ent, store.clock_month()) > WITHDRAWAL_WINDOW_MONTHS:
        raise ApiError(
            ERR_WITHDRAWAL_WINDOW_EXPIRED,
            "Withdrawal attempted more than 12 months after entitlement_month.",
        )
    # Layer 12 — repayment equality, then the once-per-lifetime bar (the
    # order given in PRD §2.9's fiscal layer).
    if repaid != claim_total_paid_cents(claim["id"]):
        raise ApiError(
            ERR_REPAYMENT_SHORTFALL, "repaid_amount_cents differs from the claim's total_paid_cents."
        )
    worker = store.workers[claim["worker_id"]]
    if worker["withdrawal_used"]:
        raise ApiError(ERR_WITHDRAWAL_ALREADY_USED, "The worker has already used the once-per-lifetime withdrawal.")
    for p in store.payments.values():
        if p["claim_id"] == claim["id"] and p["status"] in ("PAID", "WITHHELD_FULL"):
            p["status"] = "REPAYED"
            touch(p)
    worker["withdrawal_used"] = True
    touch(worker)
    claim["status"] = "WITHDRAWN"
    claim["monthly_benefit_cents"] = 0
    touch(claim)
    return ok(claim_dict(claim))


@bp.route("/ssa/claims/<claim_id>/suspend", methods=["POST"])
def suspend_claim(claim_id):
    ctx = authenticate()
    require_role(ctx, {ROLE_CLAIMANT, ROLE_CLAIMS_SPECIALIST})
    claim = load_claim(claim_id)
    claimant_owns(ctx, claim["worker_id"])
    body = v.get_body()
    expected = v.req_int(body, "expected_claim_version", min_v=0)
    _require_not_terminal(claim)
    if claim["status"] != "ENTITLED":
        raise ApiError(ERR_INVALID_STATE, "Only an ENTITLED claim can be suspended.")
    if expected != claim["version"]:
        raise ApiError(ERR_STALE_VERSION, "expected_claim_version does not match the claim's current version.")
    worker = store.workers[claim["worker_id"]]
    age_now = tu.age_months_at(worker["birth_year"], worker["birth_month"], store.clock_month())
    if not (worker["fra_months"] <= age_now < calc.MAX_DRC_AGE_MONTHS):
        raise ApiError(
            ERR_SUSPENSION_AGE_INELIGIBLE,
            "Voluntary suspension requires FRA <= age < 70 at the logical clock.",
        )
    claim["status"] = "SUSPENDED"
    claim["suspended_since"] = tu.ym_str(store.clock_month())
    touch(claim)
    return ok(claim_dict(claim))


@bp.route("/ssa/claims/<claim_id>/resume", methods=["POST"])
def resume_claim_endpoint(claim_id):
    ctx = authenticate()
    require_role(ctx, {ROLE_CLAIMANT, ROLE_CLAIMS_SPECIALIST})
    claim = load_claim(claim_id)
    claimant_owns(ctx, claim["worker_id"])
    _require_not_terminal(claim)
    if claim["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, "Only a SUSPENDED claim can be resumed.")
    resume_claim(claim, store.clock_month())
    return ok(claim_dict(claim))
