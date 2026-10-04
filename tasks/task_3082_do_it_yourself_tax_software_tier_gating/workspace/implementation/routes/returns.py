"""TaxReturn endpoints: lifecycle, forms, tier selection, filing, amendment."""
from datetime import timedelta

from flask import Blueprint

from core import (
    AMENDMENT_HOLD_HOURS,
    ApiError,
    RANK_TIER,
    TIER_RANK,
    check_ownership,
    db,
    endpoint,
    expected_version,
    f_int,
    f_str,
    body,
    dump,
    new_row,
    now,
    paginate,
    respond_object,
    touch,
)
import svc

bp = Blueprint("returns", __name__)


def _own_return(return_id):
    """Fetch return + owning account with path-existence and Taxpayer ownership."""
    ret = svc.get_return(return_id)
    acct = db.accounts[ret["account_id"]]
    check_ownership(acct)
    return ret, acct


# ---------------------------------------------------------------------------
# Create / read
# ---------------------------------------------------------------------------
@bp.post("/tax/accounts/<account_id>/returns")
@endpoint("Taxpayer")
def create_return(account_id):
    acct = svc.get_account(account_id)
    check_ownership(acct)
    payload = body()
    tax_year = f_int(payload, "tax_year")
    ret = new_row(
        "return",
        account_id=acct["id"],
        tax_year=tax_year,
        current_tier="FREE",
        minimum_required_tier="FREE",
        free_file_eligible=None,
        upgrade_prompt_pending=False,
        refund_transfer_selected=False,
        federal_refund_cents=0,
        total_fees_due_cents=0,
        status="DRAFT",
    )
    svc.recompute_classification(ret, acct)  # income-only free-file check
    svc.recompute_fees(ret)                  # FREE tier price
    db.returns[ret["id"]] = ret
    return respond_object(dump(ret), status=201)


@bp.get("/tax/accounts/<account_id>/returns")
@endpoint("Taxpayer", "ClaimsAdjuster")
def list_returns(account_id):
    acct = svc.get_account(account_id)
    check_ownership(acct)
    rows = [r for r in db.returns.values() if r["account_id"] == acct["id"]]
    return paginate(rows)


@bp.get("/tax/returns/<return_id>")
@endpoint("Taxpayer", "ClaimsAdjuster", "PlatformOperator")
def get_return(return_id):
    ret, _acct = _own_return(return_id)
    return respond_object(dump(ret))


# ---------------------------------------------------------------------------
# Tier selection
# ---------------------------------------------------------------------------
@bp.post("/tax/returns/<return_id>/select-tier")
@endpoint("Taxpayer")
def select_tier(return_id):
    ret, acct = _own_return(return_id)
    payload = body()
    target = f_str(payload, "target_tier")
    if target not in TIER_RANK:
        from core import bad_request
        bad_request("Field 'target_tier' must be one of %s." % ", ".join(TIER_RANK))
    svc.require_account_active(acct)
    svc.require_return_editable(ret, error_id="ERR_INVALID_STATE")
    expected_version(payload, ret)
    if TIER_RANK[target] <= TIER_RANK[ret["current_tier"]]:
        raise ApiError("ERR_INVALID_REQUEST", "target_tier must be strictly above the current tier.")
    if TIER_RANK[target] < TIER_RANK[ret["minimum_required_tier"]]:
        raise ApiError("ERR_TIER_BELOW_REQUIRED", "target_tier is below the minimum required tier.")
    ret["current_tier"] = target
    svc.recompute_fees(ret)
    touch(ret)
    return respond_object(dump(ret))


# ---------------------------------------------------------------------------
# Forms
# ---------------------------------------------------------------------------
@bp.post("/tax/returns/<return_id>/forms")
@endpoint("Taxpayer")
def add_form(return_id):
    ret, acct = _own_return(return_id)
    payload = body()
    form_code = f_str(payload, "form_code")
    amount = f_int(payload, "amount_cents")
    spec = db.form_specs.get(form_code)
    if spec is None:
        raise ApiError("ERR_FORM_SPEC_NOT_FOUND", "form_code not registered in FormSpec.")
    svc.require_account_active(acct)
    svc.require_return_editable(ret, error_id="ERR_INVALID_STATE")
    expected_version(payload, ret)
    for f in svc.active_forms_of(ret):
        if f["form_code"] == form_code:
            raise ApiError("ERR_DUPLICATE_FORM_ON_RETURN", "An ACTIVE form with this form_code already exists.")
    form = new_row(
        "form",
        return_id=ret["id"],
        form_code=form_code,
        source="MANUAL",
        carryforward_item_type="NONE",
        amount_cents=amount,
        status="ACTIVE",
    )
    db.forms[form["id"]] = form
    svc.recompute_classification(ret, acct)
    svc.recompute_refund(ret)
    svc.maybe_raise_prompt(ret)
    touch(ret)
    return respond_object(dump(form), status=201)


@bp.get("/tax/returns/<return_id>/forms")
@endpoint("Taxpayer", "ClaimsAdjuster")
def list_forms(return_id):
    ret, _acct = _own_return(return_id)
    return paginate(svc.forms_of(ret))


@bp.post("/tax/returns/<return_id>/forms/<form_id>/remove")
@endpoint("Taxpayer")
def remove_form(return_id, form_id):
    ret, acct = _own_return(return_id)
    form = svc.get_form_on_return(ret, form_id)
    payload = body()
    svc.require_account_active(acct)
    svc.require_return_editable(ret, error_id="ERR_INVALID_STATE")
    if form["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Form is not ACTIVE.")
    expected_version(payload, ret)
    form["status"] = "REMOVED"
    touch(form)
    svc.recompute_classification(ret, acct)
    svc.recompute_refund(ret)
    svc.maybe_raise_prompt(ret)  # supersedes a stale PENDING prompt when the minimum collapses
    touch(ret)
    return respond_object(dump(form))


# ---------------------------------------------------------------------------
# Review / reopen / file / amend
# ---------------------------------------------------------------------------
@bp.post("/tax/returns/<return_id>/submit-review")
@endpoint("Taxpayer")
def submit_review(return_id):
    ret, acct = _own_return(return_id)
    payload = body()
    svc.require_account_active(acct)
    if ret["status"] not in ("DRAFT", "AMENDED"):
        raise ApiError("ERR_INVALID_STATE", "Return is not in a submittable state.")
    expected_version(payload, ret)
    if any(p["status"] == "PENDING" for p in svc.prompts_of(ret)):
        raise ApiError("ERR_UPGRADE_ACK_REQUIRED", "A PENDING upgrade prompt blocks review.")
    if not svc.active_forms_of(ret):
        raise ApiError("ERR_NO_FORMS_ON_RETURN", "submit-review requires at least one ACTIVE form.")
    # Settled classification pass.
    svc.recompute_classification(ret, acct)
    if TIER_RANK[ret["minimum_required_tier"]] > TIER_RANK[ret["current_tier"]]:
        raise ApiError("ERR_TIER_BELOW_REQUIRED", "current tier is below the settled minimum required tier.")
    if ret["current_tier"] == "FREE" and not ret["free_file_eligible"]:
        raise ApiError("ERR_FREE_FILE_INELIGIBLE", "Return priced at FREE but not free-file eligible.")
    svc.recompute_fees(ret)
    ret["status"] = "READY_FOR_REVIEW"
    touch(ret)
    return respond_object(dump(ret))


@bp.post("/tax/returns/<return_id>/reopen")
@endpoint("Taxpayer")
def reopen_return(return_id):
    ret, acct = _own_return(return_id)
    payload = body()
    svc.require_account_active(acct)
    # The in-flight gate fires whenever a PENDING attempt exists, regardless
    # of which from-state the reopen targets (a SUBMITTED return always has
    # its latest attempt PENDING until the authority resolves it).
    if svc.pending_attempt(ret) is not None:
        raise ApiError("ERR_FILING_IN_FLIGHT", "A PENDING filing attempt exists.")
    if ret["status"] not in ("READY_FOR_REVIEW", "REJECTED"):
        raise ApiError("ERR_INVALID_STATE", "Return cannot be reopened from its current state.")
    expected_version(payload, ret)
    ret["status"] = "DRAFT"
    touch(ret)
    return respond_object(dump(ret))


@bp.post("/tax/returns/<return_id>/file")
@endpoint("Taxpayer")
def file_return(return_id):
    ret, acct = _own_return(return_id)
    payload = body()
    transmission_hash = f_str(payload, "transmission_payload_hash")
    svc.require_account_active(acct)
    if ret["status"] != "READY_FOR_REVIEW":
        # Covers the explicitly forbidden AMENDED -> SUBMITTED direct file.
        raise ApiError("ERR_INVALID_STATE", "Return must be READY_FOR_REVIEW to file.")
    expected_version(payload, ret)
    if ret["refund_transfer_selected"]:
        active_agreements = [a for a in svc.agreements_of(ret) if a["status"] == "ACTIVE"]
        if not active_agreements:
            raise ApiError("ERR_REFUND_TRANSFER_NOT_ACTIVE", "Agreement must be ACTIVE before filing with refund transfer.")
    if svc.pending_attempt(ret) is not None:
        raise ApiError("ERR_FILING_IN_FLIGHT", "A PENDING filing attempt exists.")
    accepted = [a for a in svc.attempts_of(ret) if a["outcome"] == "ACCEPTED" and a["resolved_at"] is not None]
    if accepted:
        last = max(accepted, key=lambda a: a["resolved_at"])
        if now() <= last["resolved_at"] + timedelta(hours=AMENDMENT_HOLD_HOURS):
            raise ApiError("ERR_AMENDMENT_HOLD_ACTIVE", "Re-filing inside the amendment hold window.")
    if ret["refund_transfer_selected"]:
        svc.recompute_fees(ret)
        if ret["federal_refund_cents"] < ret["total_fees_due_cents"]:
            raise ApiError("ERR_REFUND_INSUFFICIENT_FOR_FEES", "federal refund does not cover total fees due.")
    seq = max((a["attempt_sequence"] for a in svc.attempts_of(ret)), default=0) + 1
    attempt = new_row(
        "filing_attempt",
        return_id=ret["id"],
        attempt_sequence=seq,
        transmission_payload_hash=transmission_hash,
        outcome="PENDING",
        rejection_code=None,
        correction_hint=None,
        resolved_at=None,
    )
    db.filing_attempts[attempt["id"]] = attempt
    ret["status"] = "SUBMITTED"
    for sr in svc.state_returns_of(ret):
        if sr["status"] == "READY":
            sr["status"] = "FILED"
            touch(sr)
    touch(ret)
    return respond_object(dump(attempt), status=201)


@bp.post("/tax/returns/<return_id>/amend")
@endpoint("Taxpayer")
def amend_return(return_id):
    ret, acct = _own_return(return_id)
    payload = body()
    svc.require_account_active(acct)
    if ret["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE", "Only an ACCEPTED return can be amended.")
    expected_version(payload, ret)
    if not any(a["outcome"] == "ACCEPTED" for a in svc.attempts_of(ret)):
        raise ApiError("ERR_INVALID_STATE", "Amendment requires an ACCEPTED filing attempt.")
    ret["status"] = "AMENDED"
    touch(ret)
    return respond_object(dump(ret))


# ---------------------------------------------------------------------------
# FilingAttempt reads
# ---------------------------------------------------------------------------
@bp.get("/tax/returns/<return_id>/filing-attempts")
@endpoint("Taxpayer", "ClaimsAdjuster", "PlatformOperator")
def list_filing_attempts(return_id):
    ret, _acct = _own_return(return_id)
    return paginate(svc.attempts_of(ret))
