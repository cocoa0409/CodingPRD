"""OutsideServiceClaim endpoints (PRD 3.6)."""

from flask import Blueprint

from calculations import (
    claim_lines_from_body,
    final_liability_cents,
    provisional_liability_cents,
)
from clock import now_iso
from constants import (
    ROLE_REGIONAL_FINANCE_OFFICER,
    ROLE_UTILIZATION_REVIEWER,
)
from db import STORE
from domain import (
    check_member_version,
    enforce_posture_gate,
    get_claim,
    get_region,
    latest_budget_for,
    new_record,
    perfor_m_fiscal_line_check,
    recompute_region_aggregates,
    require_body_reference,
    run_posture_ladder,
    store_row,
    touch,
)
from errors import (
    ERR_APPEAL_ROUNDS_EXHAUSTED,
    ERR_BUDGET_NOT_APPROVED,
    ERR_CLAIM_NOT_ADJUDICABLE,
    ERR_CROSS_REGION_REFERENCE,
    ERR_INVALID_STATE,
    raise_error,
)
from constants import APPEAL_ROUNDS_MAX
from routes._common import (
    CLAIM_READERS,
    arg,
    filter_rows,
    list_response,
    optional_field,
    payload,
    principal,
    require_field,
    single_response,
)

bp = Blueprint("claims", __name__)


def _booked_amount(claim):
    """A claim's booked liability: the final figure once pinned, else the
    forward-looking provisional booked at submission (PRD 3.6 / 3.7)."""
    if claim.get("status") in ("ADJUDICATED", "PAID"):
        return int(claim.get("final_liability_cents") or 0)
    if claim.get("status") == "DENIED":
        return 0
    return int(claim.get("provisional_liability_cents") or 0)


def _region_committed(region_id):
    total = 0
    for claim in STORE.claims.values():
        if claim.get("region_id") != region_id:
            continue
        total += _booked_amount(claim)
    region = STORE.regions.get(region_id)
    if region is not None:
        total += int(STORE.integration_outside.get(region_id, 0) or 0)
    return total


def _outside_services_budget_cents(region_id):
    budget = latest_budget_for(region_id)
    if budget is None:
        return None
    return int(budget.get("outside_services_budget_cents") or 0)


def _approved_budget(region_id):
    for budget in STORE.budgets.values():
        if budget.get("region_id") == region_id and budget.get("status") == "APPROVED":
            return budget
    return None


@bp.post("/regions/<region_id>/outside-service-claims")
def submit_claim(region_id):
    principal((ROLE_REGIONAL_FINANCE_OFFICER,))
    get_region(region_id)
    body = payload()

    member_id = require_field(body, "member_id")
    member = require_body_reference("members", member_id)
    expected = optional_field(body, "expected_member_version")
    check_member_version(member, expected)

    claim_type = require_field(body, "claim_type")
    if claim_type != "OUT_OF_AREA" and member.get("region_id") != region_id:
        raise_error(ERR_CROSS_REGION_REFERENCE)

    enforce_posture_gate(region_id)
    perfor_m_fiscal_line_check(region_id)

    vendor_name = require_field(body, "vendor_name")
    billed = require_field(body, "billed_amount_cents")
    emergency_flag = bool(optional_field(body, "emergency_flag", False))

    row = new_record(
        member_id=member_id,
        region_id=region_id,
        vendor_name=vendor_name,
        service_code=require_field(body, "service_code"),
        claim_type=claim_type,
        emergency_flag=emergency_flag,
        billed_amount_cents=billed,
        provisional_liability_cents=provisional_liability_cents(
            billed, vendor_name, emergency_flag),
        final_liability_cents=0,
        submitted_at=now_iso(),
        adjudicated_at=None,
        appeal_rounds=0,
        provider_type=optional_field(body, "provider_type", None),
        claim_line_number=optional_field(body, "claim_line_number", None),
        derived_claim_type=optional_field(body, "derived_claim_type", None),
        status="SUBMITTED",
    )
    store_row("claims", row)

    lines = claim_lines_from_body(body, row)
    STORE.claim_lines[row["id"]] = lines

    budget_line = _outside_services_budget_cents(region_id)
    if budget_line is not None and _region_committed(region_id) > budget_line:
        row["status"] = "PENDED"

    touch(member)
    recompute_region_aggregates(region_id, bump_version=True)
    run_posture_ladder(region_id)
    return single_response("claims", row, 201)


@bp.get("/regions/<region_id>/outside-service-claims")
def list_region_claims(region_id):
    principal(CLAIM_READERS)
    get_region(region_id)
    rows = [c for c in STORE.claims.values() if c.get("region_id") == region_id]
    rows = filter_rows(rows, status=arg("status"), claim_type=arg("claim_type"))
    return list_response("claims", rows)


@bp.get("/outside-service-claims")
def list_claims():
    principal(CLAIM_READERS)
    rows = list(STORE.claims.values())
    rows = filter_rows(rows, member_id=arg("member_id"),
                       region_id=arg("region_id"), status=arg("status"))
    return list_response("claims", rows)


@bp.get("/outside-service-claims/<claim_id>")
def get_one_claim(claim_id):
    principal(CLAIM_READERS)
    return single_response("claims", get_claim(claim_id))


def _adjudicate(claim):
    region_id = claim["region_id"]
    lines = STORE.claim_lines.get(claim["id"]) or []
    claim["final_liability_cents"] = final_liability_cents(lines)
    claim["adjudicated_at"] = now_iso()
    claim["status"] = "ADJUDICATED"
    touch(claim)

    recompute_region_aggregates(region_id, bump_version=True)
    run_posture_ladder(region_id)
    return claim


@bp.post("/outside-service-claims/<claim_id>/adjudicate")
def adjudicate_claim(claim_id):
    principal((ROLE_REGIONAL_FINANCE_OFFICER,))
    claim = get_claim(claim_id)
    region_id = claim["region_id"]

    # state admissibility and the APPROVED-budget requirement are evaluated
    # together, before the committed-outside-services comparison (PRD 3.7).
    if claim.get("status") not in ("SUBMITTED", "PENDED", "APPEALED"):
        raise_error(ERR_CLAIM_NOT_ADJUDICABLE)
    if _approved_budget(region_id) is None:
        raise_error(ERR_BUDGET_NOT_APPROVED)

    budget_line = _outside_services_budget_cents(region_id)
    if budget_line is not None and _region_committed(region_id) > budget_line:
        raise_error(ERR_INVALID_STATE, "The region's outside-services budget is exceeded.")

    _adjudicate(claim)
    return single_response("claims", claim)


@bp.post("/outside-service-claims/<claim_id>/pay")
def pay_claim(claim_id):
    principal((ROLE_REGIONAL_FINANCE_OFFICER,))
    claim = get_claim(claim_id)
    if claim.get("status") != "ADJUDICATED":
        raise_error(ERR_CLAIM_NOT_ADJUDICABLE)
    if _approved_budget(claim["region_id"]) is None:
        raise_error(ERR_BUDGET_NOT_APPROVED)
    claim["status"] = "PAID"
    touch(claim)
    return single_response("claims", claim)


@bp.post("/outside-service-claims/<claim_id>/deny")
def deny_claim(claim_id):
    principal((ROLE_UTILIZATION_REVIEWER,))
    claim = get_claim(claim_id)
    if claim.get("status") not in ("ADJUDICATED", "APPEALED"):
        raise_error(ERR_CLAIM_NOT_ADJUDICABLE)
    if (claim.get("status") == "APPEALED"
            and int(claim.get("appeal_rounds") or 0) >= APPEAL_ROUNDS_MAX):
        raise_error(ERR_APPEAL_ROUNDS_EXHAUSTED)

    was_adjudicated = claim.get("status") == "ADJUDICATED"
    claim["status"] = "DENIED"
    touch(claim)
    if was_adjudicated:
        recompute_region_aggregates(claim["region_id"], bump_version=True)
    return single_response("claims", claim)


@bp.post("/outside-service-claims/<claim_id>/appeal")
def appeal_claim(claim_id):
    principal((ROLE_UTILIZATION_REVIEWER,))
    claim = get_claim(claim_id)
    if claim.get("status") != "DENIED":
        raise_error(ERR_CLAIM_NOT_ADJUDICABLE)
    if int(claim.get("appeal_rounds") or 0) >= APPEAL_ROUNDS_MAX:
        raise_error(ERR_APPEAL_ROUNDS_EXHAUSTED)
    claim["status"] = "APPEALED"
    claim["appeal_rounds"] = int(claim.get("appeal_rounds") or 0) + 1
    touch(claim)
    return single_response("claims", claim)


@bp.post("/referral-claims/bulk-adjudicate")
def bulk_adjudicate():
    principal((ROLE_REGIONAL_FINANCE_OFFICER,))
    body = payload()
    referral_id = require_field(body, "referral_id")
    require_body_reference("referrals", referral_id)

    linked = [c for c in STORE.claims.values()
              if c.get("referral_id") == referral_id
              or c.get("service_code") == _referral_service_code(referral_id)]
    targets = [c for c in linked
               if c.get("status") in ("SUBMITTED", "APPEALED")]

    for claim in targets:
        if _approved_budget(claim["region_id"]) is None:
            raise_error(ERR_BUDGET_NOT_APPROVED)

    for claim in targets:
        _adjudicate(claim)

    from flask import jsonify
    from response import success
    return jsonify(success({}))


def _referral_service_code(referral_id):
    referral = STORE.referrals.get(referral_id)
    if referral is None:
        return None
    return referral.get("service_code")


@bp.get("/referral-claims/<referral_id>")
def get_referral_claim_batch(referral_id):
    principal((CLAIM_READERS[0], CLAIM_READERS[1], CLAIM_READERS[2]))
    claim = get_claim(referral_id)
    return single_response("claims", claim)