"""Member registration, member-scoped diagnostics and lifecycle operations."""

from flask import Blueprint

from db import DB
from errors import ERR_INSUFFICIENT_POINTS, ERR_INVALID_STATE, ERR_MEMBER_NOT_FOUND, ApiError
from errors import ERR_PRINCIPAL_BELOW_ZERO, ERR_REDEMPTION_LIMIT_EXCEEDED
from middleware import (
    as_int,
    as_enum,
    as_string,
    auth,
    paginate,
    raw_body,
    reject_unknown,
    request_version,
    require_fields,
    require_owner,
)
from response import ok_array, ok_object
from routes.common import fetch, fetch_member, guard_member_view, mk
from services import calc, recompute, serialize, workflows

BP = Blueprint("members", __name__)

PRODUCT_LINES = ("LENDING", "BANKING", "INVESTING", "CAREER")
BENEFIT_CODES = (
    "LOAN_RATE_DISCOUNT",
    "DIRECT_DEPOSIT",
    "CAREER_COACHING_CREDIT",
    "INVESTING_FEE_WAIVER",
    "REWARDS_MULTIPLIER",
)
MEMBER_CREATE_ALLOWED = {"member_number", "full_name", "email"}
DEPOSIT_ALLOWED = {"enrollment_id", "amount_cents", "posted_at", "holding_id"}
REVERSE_ALLOWED = {"posting_id"}
CYCLE_ALLOWED = {"expected_member_version"}
ENTITLEMENT_ALLOWED = {"source_holding_id", "benefit_code", "value_bps", "governing_rule_id"}
REDEEM_ALLOWED = {"loan_account_id", "points", "source_event_code"}
ADJUST_ALLOWED = {"points_delta", "source_event_code"}


@BP.route("/benefits/members", methods=["POST"])
def register_member():
    user_id, role = auth(("Anonymous", "PlatformAdmin"))
    del user_id, role
    payload = raw_body()
    reject_unknown(payload, MEMBER_CREATE_ALLOWED)
    require_fields(payload, ("member_number", "full_name", "email"))
    member_number = as_string(payload, "member_number")
    full_name = as_string(payload, "full_name")
    email = as_string(payload, "email")
    for existing in DB.members.values():
        if existing["member_number"] == member_number:
            raise ApiError(ERR_INVALID_STATE, "A member with this member_number already exists.")
        if existing["email"] == email:
            raise ApiError(ERR_INVALID_STATE, "A member with this email already exists.")
    member = mk(
        "members",
        member_number=member_number,
        full_name=full_name,
        email=email,
        member_status="PROSPECT",
        member_since_at=None,
        product_adoption_count=0,
        product_line_set=[],
        member_tier="NONE",
        qualifying_deposit_balance_cents=0,
        benefit_entitlement_state="NONE",
        rewards_points_balance=0,
        churn_risk_score=0,
        last_qualifying_deposit_at=None,
    )
    return ok_object(serialize.member(member)), 201


@BP.route("/benefits/members", methods=["GET"])
def list_members():
    auth(("PlatformAdmin", "ComplianceOfficer", "BenefitsAdmin"))
    for row in DB.members.values():
        recompute.recompute_member(row["id"], bump=False)
    items = list(DB.members.values())
    filters = {"member_status": "member_status", "member_tier": "member_tier", "email": "email"}
    from middleware import query_filter

    items = query_filter(items, filters)
    items.sort(key=lambda m: (m.get("created_at") or "", m["id"]))
    page, limit, offset, total = paginate(items)
    return ok_array([serialize.member(m) for m in page], limit, offset, total)


@BP.route("/benefits/members/<member_id>", methods=["GET"])
def get_member(member_id):
    user_id, role = auth(
        ("Member", "PlatformAdmin", "ComplianceOfficer", "BenefitsAdmin", "Underwriter")
    )
    member = fetch_member(member_id)
    guard_member_view(user_id, role, member_id)
    recompute.recompute_member(member_id, bump=False)
    return ok_object(serialize.member(member))


@BP.route("/benefits/members/<member_id>/tier-projection", methods=["GET"])
def tier_projection(member_id):
    user_id, role = auth(("Member", "BenefitsAdmin", "PlatformAdmin"))
    member = fetch_member(member_id)
    guard_member_view(user_id, role, member_id)
    pending = [
        h
        for h in calc.holdings_of(member_id)
        if h["adoption_status"] == "PENDING"
    ]
    return ok_object(
        {
            "current_tier": member["member_tier"],
            "projected_tier": calc.member_tier_for(member_id, forward_looking=True),
            "pending_adoption_count": len(pending),
        }
    )


@BP.route("/benefits/members/<member_id>/churn-breakdown", methods=["GET"])
def churn_breakdown(member_id):
    user_id, role = auth(("Member", "ComplianceOfficer", "PlatformAdmin"))
    member = fetch_member(member_id)
    guard_member_view(user_id, role, member_id)
    recompute.recompute_member(member_id)
    factors = calc.churn_factors(member_id)
    return ok_object(
        {
            "stored_score": member["churn_risk_score"],
            "raw_score": sum(factors.values()),
            "deposit_factor": factors["deposit_factor"],
            "missed_cycle_factor": factors["missed_cycle_factor"],
            "tier_factor": factors["tier_factor"],
            "balance_factor": factors["balance_factor"],
        }
    )


@BP.route("/benefits/members/<member_id>/deposit-rate-projection", methods=["GET"])
def deposit_rate_projection(member_id):
    user_id, role = auth(("Member", "BenefitsAdmin", "PlatformAdmin"))
    fetch_member(member_id)
    guard_member_view(user_id, role, member_id)
    trailing = calc.trailing_average_balance_cents(member_id)
    return ok_object(
        {
            "current_boost_bps": calc.deposit_rate_boost_bps(member_id),
            "projected_boost_bps": calc.deposit_rate_boost_bps(member_id, balance=trailing),
            "trailing_average_balance_cents": trailing,
        }
    )


@BP.route("/benefits/members/<member_id>/benefit-summary", methods=["GET"])
def benefit_summary(member_id):
    user_id, role = auth(("Member", "BenefitsAdmin", "ComplianceOfficer", "PlatformAdmin"))
    member = fetch_member(member_id)
    guard_member_view(user_id, role, member_id)
    # The head-line rollup (`entitlement_state`) is computed over the member's
    # entitlements whose source holding is not closed (PRD §2.6). The per-status
    # counts describe the full entitlement set, so a row whose holding closed —
    # excluded from the rollup — is still visible in the catalogue as REVOKED.
    counted = calc.counted_entitlements(member_id)
    counted_profile = [_read_side_status(e) for e in counted]
    all_rows = calc.entitlements_of(member_id)
    all_profile = [_read_side_status(e) for e in all_rows]
    return ok_object(
        {
            "entitlement_state": _read_side_state(member_id, counted, counted_profile),
            "granted_count": sum(1 for s in all_profile if s == "GRANTED"),
            "pending_requalification_count": sum(
                1 for s in all_profile if s == "PENDING_REQUALIFICATION"
            ),
            "stepped_down_count": sum(1 for s in all_profile if s == "STEPPED_DOWN"),
            "revoked_count": sum(1 for s in all_profile if s == "REVOKED"),
        }
    )


def _read_side_status(ent):
    """The row's stored status, read side.

    The member-level rollup of §2.6 is a rollup over the entitlements' stored
    statuses (a lapsed member reads SUSPENDED; all-granted reads FULL; some
    granted reads PARTIAL), so the summary reports each row's own status. The
    drift between a stored row and its guard verdict is surfaced by the
    `reconciliation_state` field, not by rewriting the status here.
    """
    return ent["entitlement_status"]


def _read_side_state(member_id, rows, profile):
    member = DB.members.get(member_id)
    if member is not None and member["member_status"] == "MEMBER_LAPSED":
        return "SUSPENDED"
    if not rows:
        return "NONE"
    granted = [s for s in profile if s == "GRANTED"]
    if len(granted) == len(profile):
        return "FULL"
    if granted:
        return "PARTIAL"
    return "NONE"


@BP.route("/benefits/members/<member_id>/rewards-balance", methods=["GET"])
def rewards_balance(member_id):
    user_id, role = auth(("Member", "PlatformAdmin"))
    member = fetch_member(member_id)
    guard_member_view(user_id, role, member_id)
    rows = calc.ledger_of(member_id)
    return ok_object(
        {
            "points_balance": calc.rewards_points_balance(member_id),
            "posted_entry_count": sum(1 for e in rows if e["entry_status"] == "POSTED"),
            "reversed_entry_count": sum(1 for e in rows if e["entry_status"] == "REVERSED"),
        }
    )


@BP.route("/benefits/members/<member_id>/deposits", methods=["POST"])
def post_deposit(member_id):
    auth(("PlatformAdmin",))
    member = fetch_member(member_id)
    payload = raw_body()
    reject_unknown(payload, DEPOSIT_ALLOWED)
    require_fields(payload, ("enrollment_id", "amount_cents", "posted_at"))
    enrollment_id = as_string(payload, "enrollment_id")
    amount_cents = as_int(payload, "amount_cents")
    from middleware import as_timestamp

    posted_at = as_timestamp(payload, "posted_at")
    enr = fetch("enrollments", enrollment_id)
    if enr["member_id"] != member_id:
        raise ApiError(ERR_INVALID_STATE)
    holding = None
    if payload.get("holding_id") is not None:
        holding = fetch("holdings", as_string(payload, "holding_id"))
        if holding["member_id"] != member_id:
            raise ApiError(ERR_INVALID_STATE)
    workflows.post_deposit(enr, amount_cents, posted_at, holding)
    return ok_object(serialize.enrollment(enr)), 201


@BP.route("/benefits/members/<member_id>/deposits/reverse", methods=["POST"])
def reverse_deposit(member_id):
    auth(("PlatformAdmin",))
    fetch_member(member_id)
    payload = raw_body()
    reject_unknown(payload, REVERSE_ALLOWED)
    require_fields(payload, ("posting_id",))
    posting = fetch("deposit_postings", as_string(payload, "posting_id"))
    if posting["member_id"] != member_id:
        raise ApiError(ERR_INVALID_STATE)
    enr = workflows.reverse_deposit(posting)
    return ok_object(serialize.enrollment(enr))


@BP.route("/benefits/members/<member_id>/requalification-cycles", methods=["POST"])
def open_cycle(member_id):
    auth(("PlatformAdmin",))
    member = fetch_member(member_id)
    payload = raw_body()
    reject_unknown(payload, CYCLE_ALLOWED)
    expected = request_version("expected_member_version")
    if expected is not None and expected != int(member["version"]):
        from errors import ERR_STALE_VERSION

        raise ApiError(ERR_STALE_VERSION)

    from timeutil import fmt_ts, month_index, month_start

    now = DB.clock()
    existing = [c for c in DB.cycles.values() if c["member_id"] == member_id]
    next_index = 1 + max([int(c["cycle_index"]) for c in existing], default=0)
    cycle = mk(
        "cycles",
        member_id=member_id,
        cycle_index=next_index,
        opened_at=fmt_ts(now),
        due_at=fmt_ts(month_start(month_index(now) + workflows.REQUALIFICATION_WINDOW_MONTHS)),
        evaluated_at=None,
        status="OPEN",
        qualifying_month_count=0,
        qualifying_deposit_total_cents=0,
    )
    recompute.recompute_cycle_indexes(member_id)
    recompute.recompute_cycle_rollups(cycle["id"])
    member["version"] = int(member["version"]) + 1
    return ok_object(serialize.cycle(cycle)), 201


@BP.route("/benefits/members/<member_id>/reinstate", methods=["POST"])
def reinstate(member_id):
    auth(("PlatformAdmin",))
    member = fetch_member(member_id)
    if member["member_status"] != "MEMBER_LAPSED":
        raise ApiError(ERR_INVALID_STATE)
    if int(member["product_adoption_count"]) < 1:
        raise ApiError(ERR_INVALID_STATE)
    workflows.reinstate_member(member)
    return ok_object(serialize.member(member))


@BP.route("/benefits/members/<member_id>/reset-to-prospect", methods=["POST"])
def reset_to_prospect(member_id):
    auth(("PlatformAdmin",))
    member = fetch_member(member_id)
    if member["member_status"] != "MEMBER_LAPSED":
        raise ApiError(ERR_INVALID_STATE)
    if int(member["product_adoption_count"]) != 0:
        raise ApiError(ERR_INVALID_STATE)
    workflows.reset_to_prospect(member)
    return ok_object(serialize.member(member))


@BP.route("/benefits/members/<member_id>/detect-churn", methods=["POST"])
def detect_churn(member_id):
    auth(("PlatformAdmin",))
    member = fetch_member(member_id)
    workflows.detect_churn(member)
    return ok_object(serialize.member(member))


@BP.route("/benefits/members/<member_id>/entitlements", methods=["POST"])
def declare_entitlement(member_id):
    auth(("BenefitsAdmin",))
    fetch_member(member_id)
    payload = raw_body()
    reject_unknown(payload, ENTITLEMENT_ALLOWED)
    require_fields(payload, ("source_holding_id", "benefit_code", "value_bps"))
    source_holding_id = as_string(payload, "source_holding_id")
    benefit_code = as_enum(payload, "benefit_code", BENEFIT_CODES)
    value_bps = as_int(payload, "value_bps")
    governing_rule_id = None
    if payload.get("governing_rule_id") is not None:
        governing_rule_id = as_string(payload, "governing_rule_id")

    holding = DB.holdings.get(source_holding_id)
    if holding is None or holding["member_id"] != member_id:
        from errors import ERR_ENTITLEMENT_NO_SOURCE_HOLDING

        raise ApiError(ERR_ENTITLEMENT_NO_SOURCE_HOLDING)
    if governing_rule_id is not None and DB.rules.get(governing_rule_id) is None:
        raise ApiError(ERR_INVALID_STATE, "The governing rule does not exist.")

    for existing in calc.entitlements_of(member_id):
        if (
            existing["benefit_code"] == benefit_code
            and existing["source_holding_id"] == source_holding_id
        ):
            from errors import ERR_DUPLICATE_ENTITLEMENT

            raise ApiError(ERR_DUPLICATE_ENTITLEMENT)
        # No two rows may share the same member and benefit code while both are
        # granted against different source holdings (PRD §3.1).
        if (
            existing["benefit_code"] == benefit_code
            and existing["source_holding_id"] != source_holding_id
            and existing["entitlement_status"] == "GRANTED"
            and calc.entitlement_unlocked(existing)
        ):
            from errors import ERR_DUPLICATE_ENTITLEMENT

            raise ApiError(ERR_DUPLICATE_ENTITLEMENT)

    ent = mk(
        "entitlements",
        member_id=member_id,
        source_holding_id=source_holding_id,
        benefit_code=benefit_code,
        entitlement_status="PENDING",
        value_bps=value_bps,
        governing_rule_id=governing_rule_id,
        granted_at=None,
        stepped_down_at=None,
        reconciliation_state="IN_SYNC",
        override_requested_by=None,
        override_approved_by=None,
        _declared_value_bps=value_bps,
    )
    if calc.entitlement_unlocked(ent):
        recompute.grant_entitlement(ent, DB.clock())
    recompute.recompute_member(member_id)
    return ok_object(serialize.entitlement(ent)), 201


@BP.route("/benefits/members/<member_id>/entitlements/reconcile", methods=["POST"])
def reconcile_entitlements(member_id):
    auth(("ComplianceOfficer",))
    fetch_member(member_id)
    for ent in calc.entitlements_of(member_id):
        holding = DB.holdings.get(ent["source_holding_id"])
        if holding is not None and holding["adoption_status"] == "CLOSED":
            from errors import ERR_HOLDING_NOT_ADOPTED

            raise ApiError(ERR_HOLDING_NOT_ADOPTED)
        if holding is None and ent["benefit_code"] != "DIRECT_DEPOSIT":
            from errors import ERR_HOLDING_NOT_ADOPTED

            raise ApiError(ERR_HOLDING_NOT_ADOPTED)
    rows = workflows.reconcile_entitlements(member_id)
    rows.sort(key=lambda e: (e.get("created_at") or "", e["id"]))
    payload = [serialize.entitlement(e) for e in rows]
    # The RECONCILED marker describes the rewrite this call performed; a later
    # read of an agreeing row reports IN_SYNC (PRD §2.6).
    for ent in rows:
        ent.pop("_reconciled", None)
    return ok_array(payload, None, None, len(rows))


@BP.route("/benefits/members/<member_id>/rewards/redeem-principal", methods=["POST"])
def redeem_principal(member_id):
    user_id, role = auth(("Member",))
    require_owner(user_id, member_id)
    fetch_member(member_id)
    payload = raw_body()
    reject_unknown(payload, REDEEM_ALLOWED)
    require_fields(payload, ("loan_account_id", "points"))
    loan_account_id = as_string(payload, "loan_account_id")
    points = as_int(payload, "points")
    source_event_code = None
    if payload.get("source_event_code") is not None:
        source_event_code = as_string(payload, "source_event_code")
    loan = fetch("loan_accounts", loan_account_id)
    if loan["member_id"] != member_id:
        raise ApiError(ERR_INVALID_STATE)

    balance = calc.rewards_points_balance(member_id)
    if points > balance:
        raise ApiError(ERR_INSUFFICIENT_POINTS)
    if points < workflows.MIN_REDEEM_POINTS or points > workflows.MAX_REDEEM_POINTS_PER_ENTRY:
        raise ApiError(ERR_REDEMPTION_LIMIT_EXCEEDED)
    reduction = calc.rewards_principal_reduction_cents(points)
    if int(loan["principal_cents"]) - reduction < 0:
        raise ApiError(ERR_PRINCIPAL_BELOW_ZERO)

    member = DB.members[member_id]
    entry = workflows.redeem_principal(member, loan, points, source_event_code)
    return ok_object(serialize.ledger(entry)), 201


@BP.route("/benefits/members/<member_id>/rewards/reconcile", methods=["POST"])
def reconcile_rewards(member_id):
    auth(("BenefitsAdmin",))
    fetch_member(member_id)
    result = workflows.reconcile_rewards(member_id)
    return ok_object(result)


@BP.route("/benefits/members/<member_id>/rewards/adjust", methods=["POST"])
def adjust_rewards(member_id):
    auth(("BenefitsAdmin",))
    fetch_member(member_id)
    payload = raw_body()
    reject_unknown(payload, ADJUST_ALLOWED)
    require_fields(payload, ("points_delta", "source_event_code"))
    points_delta = as_int(payload, "points_delta")
    source_event_code = as_string(payload, "source_event_code")
    if points_delta < 0 and calc.rewards_points_balance(member_id) + points_delta < 0:
        raise ApiError(ERR_INVALID_STATE)
    entry = workflows.append_ledger_entry(
        member_id, "ADJUST", points_delta, source_event_code=source_event_code
    )
    recompute.recompute_member(member_id)
    return ok_object(serialize.ledger(entry)), 201


__all__ = ["BP", "ERR_MEMBER_NOT_FOUND"]