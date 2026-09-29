"""Membership agreements, the dues ledger and inter-club transfers."""
from decimal import Decimal

from flask import Blueprint

import calc
import cascade
import config
import validate as v
from auth import guard, require_owner
from envelope import ok, created, listing
from errors import ApiError
from helpers import (ALL_ROLES, get_agreement, get_billing_event, get_club, get_corporate,
                     get_member, get_promotion, get_template, get_transfer, paged,
                     require_compliant, require_open)
from store import (db, common_fields, ledger_fields, clock_date, clock_date_str, parse_date,
                   add_days, days_between, touch)

bp = Blueprint("memberships", __name__)

MANAGER = ["ClubManager"]
CLIENT_EVENT_TYPES = ("DUES_POSTED", "PAYMENT_RECEIVED", "PAYMENT_FAILED", "WRITE_OFF")
ALL_EVENT_TYPES = CLIENT_EVENT_TYPES + ("TRANSFER_FEE_POSTED", "COLLECTION_PLACED")


# --------------------------------------------------------------------------
# signing
# --------------------------------------------------------------------------
@bp.post("/franchise/agreements")
def create_agreement():
    uid, role = guard(["ClubManager", "BrandAdministrator"])
    b = v.body()

    if role == "ClubManager":
        raw = b.get("home_club_id")
        if isinstance(raw, str):
            require_owner(raw == uid)

    member_id = v.req_id(b, "member_id")
    home_club_id = v.req_id(b, "home_club_id")
    plan_template_id = v.req_id(b, "plan_template_id")
    expected_club_version = v.req_int(b, "expected_club_version", minimum=0)
    v.req_date(b, "signed_on")
    multi_club_access = v.opt_bool(b, "multi_club_access", default=False)
    promotion_id = v.opt_id(b, "promotion_id")
    corporate_account_id = v.opt_id(b, "corporate_account_id")

    member = get_member(member_id)
    club = get_club(home_club_id)
    template = get_template(plan_template_id)
    promotion = get_promotion(promotion_id) if promotion_id else None
    account = get_corporate(corporate_account_id) if corporate_account_id else None

    if expected_club_version != club["version"]:
        raise ApiError("ERR_STALE_CLUB_VERSION")

    if template["status"] != "PUBLISHED":
        raise ApiError("ERR_PLAN_NOT_PUBLISHED")
    if promotion is not None and promotion["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_PROMOTION_STATE")
    if account is not None and account["status"] == "SUSPENDED":
        raise ApiError("ERR_CORPORATE_ACCOUNT_SUSPENDED")
    require_open(club)

    statute = config.STATE_STATUTES[club["state_code"]]
    if template["cancellation_notice_days"] > statute["max_notice_days"]:
        raise ApiError("ERR_STATUTE_NOTICE_LIMIT")

    require_compliant(club)

    if promotion is not None:
        if (promotion["franchisee_id"] != club["franchisee_id"]
                or promotion["plan_template_id"] != plan_template_id):
            raise ApiError("ERR_HOME_CLUB_MISMATCH")

    today = clock_date()
    if promotion is not None:
        if not (parse_date(promotion["starts_on"]) <= today <= parse_date(promotion["ends_on"])):
            raise ApiError("ERR_PROMOTION_WINDOW_CLOSED")

    pricing = calc.effective_monthly_dues(
        template["monthly_dues_cents"],
        Decimal(str(promotion["discount_pct"])) if promotion is not None else None,
        Decimal(str(account["corporate_credit_pct"])) if account is not None else None,
        multi_club_access)

    if pricing["gross_monthly_dues_cents"] < template["floor_price_cents"]:
        raise ApiError("ERR_PRICE_BELOW_FLOOR")

    signed_on = clock_date_str()
    record = common_fields()
    record.update({
        "member_id": member_id,
        "home_club_id": home_club_id,
        "plan_template_id": plan_template_id,
        "promotion_id": promotion_id,
        "corporate_account_id": corporate_account_id,
        "multi_club_access": multi_club_access,
        "state_code": club["state_code"],
        "signed_on": signed_on,
        "term_end_on": add_days(today, 30 * template["term_months"]).isoformat(),
        "monthly_dues_base_cents": template["monthly_dues_cents"],
        "initiation_fee_cents": template["initiation_fee_cents"],
        "cancellation_notice_days": min(template["cancellation_notice_days"],
                                        statute["max_notice_days"]),
        "promo_discount_cents": pricing["promo_discount_cents"],
        "corporate_credit_cents": pricing["corporate_credit_cents"],
        "multi_club_credit_cents": pricing["multi_club_credit_cents"],
        "effective_monthly_dues_cents": pricing["gross_monthly_dues_cents"],
        "agreement_status": "PENDING",
        "dues_status": "CURRENT",
        "outstanding_balance_cents": 0,
        "dues_paid_cents": 0,
        "delinquency_days": 0,
        "transfer_count": 0,
        "cancellation_requested_on": None,
        "cancellation_effective_on": None,
        "refund_cents": None,
        "early_termination_fee_cents": None,
        "net_settlement_cents": None,
    })
    db.agreements[record["id"]] = record

    member["agreement_count"] = cascade.member_agreement_count(member_id)
    if member["status"] == "INACTIVE":
        member["status"] = "ACTIVE"
    touch(member)

    if account is not None:
        account["enrolled_agreement_count"] += 1

    touch(club)
    return created(record)


@bp.get("/franchise/agreements/<aid>")
def read_agreement(aid):
    guard(ALL_ROLES)
    return ok(get_agreement(aid))


@bp.get("/franchise/agreements")
def list_agreements():
    guard(ALL_ROLES)
    return paged(db.agreements, "member_id", "home_club_id", "plan_template_id", "promotion_id",
                 "corporate_account_id", "agreement_status", "dues_status")


# --------------------------------------------------------------------------
# freeze / unfreeze
# --------------------------------------------------------------------------
def _owned_agreement(aid, uid):
    """Band 3 on the home club, resolved silently so band 5 still owns the 404."""
    record = db.agreements.get(aid)
    if record is not None:
        require_owner(record["home_club_id"] == uid)
    return record


@bp.post("/franchise/agreements/<aid>/freeze")
def freeze_agreement(aid):
    uid, role = guard(MANAGER)
    _owned_agreement(aid, uid)
    b = v.body()
    v.opt_str(b, "reason")
    agreement = get_agreement(aid)

    if agreement["agreement_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_AGREEMENT_STATE")
    if agreement["dues_status"] not in ("CURRENT", "PAST_DUE"):
        raise ApiError("ERR_INVALID_DUES_STATE")

    agreement["agreement_status"] = "FROZEN"
    cascade.recompute_corporate_enrolment(cascade.corporate_of(agreement))
    touch(agreement)
    return ok(agreement)


@bp.post("/franchise/agreements/<aid>/unfreeze")
def unfreeze_agreement(aid):
    uid, role = guard(MANAGER)
    _owned_agreement(aid, uid)
    b = v.body()
    v.opt_str(b, "note")
    agreement = get_agreement(aid)

    if agreement["agreement_status"] != "FROZEN":
        raise ApiError("ERR_INVALID_AGREEMENT_STATE")

    agreement["agreement_status"] = "ACTIVE"
    cascade.recompute_corporate_enrolment(cascade.corporate_of(agreement))
    touch(agreement)
    return ok(agreement)


# --------------------------------------------------------------------------
# cancellation
# --------------------------------------------------------------------------
def _cancellation_cascade(agreement):
    """The full unwind shared by the cooling-off branch and finalization."""
    club = db.clubs.get(agreement["home_club_id"])
    if club is not None:
        cascade.recompute_club(club, bump="always")
        cascade.recompute_franchisee(cascade.franchisee_of_club(club), bump="never")
    member = db.members.get(agreement["member_id"])
    if member is not None:
        cascade.recompute_member(member, bump=True)
    cascade.recompute_corporate_enrolment(cascade.corporate_of(agreement))


@bp.post("/franchise/agreements/<aid>/request-cancellation")
def request_cancellation(aid):
    uid, role = guard(["Member"])
    agreement = db.agreements.get(aid)
    if agreement is not None:
        require_owner(agreement["member_id"] == uid)
    b = v.body()
    v.opt_str(b, "reason")
    agreement = get_agreement(aid)

    if agreement["agreement_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_AGREEMENT_STATE")
    if agreement["dues_status"] in cascade.DELINQUENT_SET:
        raise ApiError("ERR_CANCELLATION_BLOCKED_BY_ARREARS")

    statute = config.STATE_STATUTES[agreement["state_code"]]
    today = clock_date()
    elapsed = days_between(today, parse_date(agreement["signed_on"]))
    agreement["cancellation_requested_on"] = clock_date_str()

    if elapsed <= statute["cooling_off_days"]:
        agreement["cancellation_effective_on"] = clock_date_str()
        refund = agreement["initiation_fee_cents"] + agreement["dues_paid_cents"]
        agreement["refund_cents"] = refund
        agreement["early_termination_fee_cents"] = 0
        agreement["net_settlement_cents"] = refund
        agreement["agreement_status"] = "CANCELLED"
        _cancellation_cascade(agreement)
    else:
        effective = add_days(today, agreement["cancellation_notice_days"]).isoformat()
        agreement["cancellation_effective_on"] = effective
        refund, _unused, _paid_through = calc.notice_refund(
            agreement["effective_monthly_dues_cents"], agreement["dues_paid_cents"],
            agreement["signed_on"], effective, statute["prorate_on_cancel"])
        fee, _months = calc.early_termination_fee(
            agreement["effective_monthly_dues_cents"], effective, agreement["term_end_on"])
        agreement["refund_cents"] = refund
        agreement["early_termination_fee_cents"] = fee
        agreement["net_settlement_cents"] = refund - fee
        agreement["agreement_status"] = "CANCELLATION_PENDING"

    touch(agreement)
    return ok(agreement)


@bp.post("/franchise/agreements/<aid>/finalize-cancellation")
def finalize_cancellation(aid):
    uid, role = guard(MANAGER)
    _owned_agreement(aid, uid)
    b = v.body()
    v.opt_str(b, "note")
    agreement = get_agreement(aid)

    if agreement["agreement_status"] != "CANCELLATION_PENDING":
        raise ApiError("ERR_INVALID_AGREEMENT_STATE")
    effective = agreement["cancellation_effective_on"]
    if effective is None or clock_date() < parse_date(effective):
        raise ApiError("ERR_NOTICE_PERIOD_NOT_ELAPSED")

    agreement["agreement_status"] = "CANCELLED"
    _cancellation_cascade(agreement)
    touch(agreement)
    return ok(agreement)


@bp.post("/franchise/agreements/<aid>/place-in-collections")
def place_in_collections(aid):
    guard(["BillingPartner"])
    b = v.body()
    v.req_str(b, "agency_reference")
    agreement = get_agreement(aid)

    if agreement["dues_status"] != "DELINQUENT":
        raise ApiError("ERR_INVALID_DUES_STATE")
    if agreement["delinquency_days"] < config.COLLECTIONS_DAYS_THRESHOLD:
        raise ApiError("ERR_COLLECTIONS_THRESHOLD_NOT_MET")

    row = cascade.append_system_event(agreement, "COLLECTION_PLACED", 0, clock_date_str())
    row["resulting_outstanding_balance_cents"] = agreement["outstanding_balance_cents"]
    agreement["dues_status"] = "IN_COLLECTIONS"

    club = db.clubs.get(agreement["home_club_id"])
    if club is not None:
        cascade.recompute_club(club, bump="never")
        cascade.recompute_franchisee(cascade.franchisee_of_club(club), bump="never")
    touch(agreement)
    return ok(agreement)


# --------------------------------------------------------------------------
# the dues ledger
# --------------------------------------------------------------------------
@bp.post("/franchise/billing-events")
def create_billing_event():
    guard(["BillingPartner", "BrandAdministrator"])
    b = v.body()
    agreement_id = v.req_id(b, "agreement_id")
    event_type = v.req_enum(b, "event_type", CLIENT_EVENT_TYPES)
    amount_cents = v.req_money(b, "amount_cents")
    occurred_on = v.req_date(b, "occurred_on")
    due_on = v.opt_date(b, "due_on")

    if event_type != "DUES_POSTED" and due_on is not None:
        raise v.bad("Field 'due_on' is only accepted on a DUES_POSTED entry.")
    if event_type == "PAYMENT_FAILED" and amount_cents != 0:
        raise v.bad("A PAYMENT_FAILED entry must carry 'amount_cents' of exactly 0.")

    agreement = get_agreement(agreement_id)

    if event_type == "WRITE_OFF" and agreement["dues_status"] != "IN_COLLECTIONS":
        raise ApiError("ERR_INVALID_DUES_STATE")

    if agreement["agreement_status"] == "CANCELLED":
        raise ApiError("ERR_INVALID_DUES_EVENT")
    if event_type == "DUES_POSTED" and due_on is None:
        raise ApiError("ERR_INVALID_DUES_EVENT")
    if (event_type in ("PAYMENT_RECEIVED", "WRITE_OFF")
            and amount_cents > agreement["outstanding_balance_cents"]):
        raise ApiError("ERR_INVALID_DUES_EVENT")

    row = ledger_fields()
    row.update({
        "agreement_id": agreement_id,
        "event_type": event_type,
        "amount_cents": amount_cents,
        "occurred_on": occurred_on,
        "due_on": due_on,
        "source": "BILLING_PARTNER",
        "resulting_outstanding_balance_cents": 0,
    })
    db.billing_events[row["id"]] = row

    figures = cascade.project(agreement)
    cascade.apply_projection(agreement, write_off_applied=(event_type == "WRITE_OFF"))
    row["resulting_outstanding_balance_cents"] = agreement["outstanding_balance_cents"]

    if (event_type == "PAYMENT_RECEIVED" and amount_cents > 0
            and agreement["agreement_status"] == "PENDING" and figures["payment_count"] == 1):
        agreement["agreement_status"] = "ACTIVE"

    club = db.clubs.get(agreement["home_club_id"])
    if club is not None:
        cascade.recompute_club(club, bump="always")
        cascade.recompute_franchisee(cascade.franchisee_of_club(club), bump="always")
    touch(agreement)
    return created(row)


@bp.get("/franchise/billing-events/<bid>")
def read_billing_event(bid):
    guard(ALL_ROLES)
    return ok(get_billing_event(bid))


@bp.get("/franchise/agreements/<aid>/billing-events")
def list_billing_events(aid):
    guard(ALL_ROLES)
    limit, offset = v.pagination()
    supplied = v.filters("event_type")
    get_agreement(aid)
    rows = [r for r in cascade.ledger_of(aid) if v.match(r, supplied)]
    return listing(rows, limit, offset)


# --------------------------------------------------------------------------
# inter-club transfers
# --------------------------------------------------------------------------
@bp.post("/franchise/transfer-requests")
def create_transfer():
    uid, role = guard(MANAGER)
    b = v.body()

    raw = b.get("from_club_id")
    if isinstance(raw, str):
        require_owner(raw == uid)

    agreement_id = v.req_id(b, "agreement_id")
    from_club_id = v.req_id(b, "from_club_id")
    to_club_id = v.req_id(b, "to_club_id")
    expected_version = v.req_int(b, "expected_agreement_version", minimum=0)
    reason = v.req_str(b, "reason")

    agreement = get_agreement(agreement_id)
    from_club = get_club(from_club_id)
    to_club = get_club(to_club_id)

    if expected_version != agreement["version"]:
        raise ApiError("ERR_STALE_AGREEMENT_VERSION")

    require_open(to_club)

    statute = config.STATE_STATUTES[agreement["state_code"]]
    if to_club["state_code"] != agreement["state_code"] and not statute["cross_state_transfer_allowed"]:
        raise ApiError("ERR_CROSS_STATE_TRANSFER_PROHIBITED")

    require_compliant(to_club)

    if agreement["home_club_id"] != from_club_id:
        raise ApiError("ERR_HOME_CLUB_MISMATCH")
    if from_club_id == to_club_id:
        raise ApiError("ERR_SAME_CLUB_TRANSFER")

    if agreement["dues_status"] in cascade.DELINQUENT_SET:
        raise ApiError("ERR_TRANSFER_BLOCKED_BY_ARREARS")

    record = common_fields()
    record.update({
        "agreement_id": agreement_id,
        "from_club_id": from_club_id,
        "to_club_id": to_club_id,
        "reason": reason,
        "status": "REQUESTED",
        "transfer_fee_cents": None,
        "effective_on": None,
        "decided_by_user_id": None,
    })
    db.transfer_requests[record["id"]] = record
    touch(agreement)
    return created(record)


def _owned_transfer(tid, uid):
    record = db.transfer_requests.get(tid)
    if record is not None:
        require_owner(record["to_club_id"] == uid)
    return record


@bp.post("/franchise/transfer-requests/<tid>/decide")
def decide_transfer(tid):
    uid, role = guard(MANAGER)
    _owned_transfer(tid, uid)
    b = v.body()
    decision = v.req_enum(b, "decision", ("APPROVE", "DENY"))
    v.opt_str(b, "note")
    record = get_transfer(tid)

    if record["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_TRANSFER_STATE")

    if decision == "APPROVE":
        agreement = get_agreement(record["agreement_id"])
        from_club = get_club(record["from_club_id"])
        to_club = get_club(record["to_club_id"])
        require_open(to_club)
        require_compliant(to_club)
        if agreement["dues_status"] not in ("CURRENT", "PAST_DUE"):
            raise ApiError("ERR_TRANSFER_BLOCKED_BY_ARREARS")
        record["transfer_fee_cents"] = calc.transfer_fee(
            from_club, to_club, agreement["effective_monthly_dues_cents"])
        record["status"] = "APPROVED"
    else:
        record["status"] = "DENIED"

    record["decided_by_user_id"] = uid
    touch(record)
    return ok(record)


@bp.post("/franchise/transfer-requests/<tid>/complete")
def complete_transfer(tid):
    uid, role = guard(MANAGER)
    _owned_transfer(tid, uid)
    b = v.body()
    v.opt_str(b, "note")
    record = get_transfer(tid)

    if record["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_TRANSFER_STATE")

    agreement = get_agreement(record["agreement_id"])
    if agreement["home_club_id"] != record["from_club_id"]:
        raise ApiError("ERR_HOME_CLUB_MISMATCH")

    from_club = get_club(record["from_club_id"])
    to_club = get_club(record["to_club_id"])

    record["effective_on"] = clock_date_str()
    record["status"] = "COMPLETED"
    agreement["home_club_id"] = record["to_club_id"]
    agreement["transfer_count"] += 1

    fee = record["transfer_fee_cents"] or 0
    if fee > 0:
        row = cascade.append_system_event(
            agreement, "TRANSFER_FEE_POSTED", fee, clock_date_str(),
            due_on=add_days(clock_date(), config.TRANSFER_FEE_DUE_DAYS).isoformat())
        cascade.apply_projection(agreement)
        row["resulting_outstanding_balance_cents"] = agreement["outstanding_balance_cents"]

    cascade.recompute_club(from_club, bump="always")
    cascade.recompute_club(to_club, bump="always")
    cascade.recompute_franchisee(cascade.franchisee_of_club(from_club), bump="never")
    cascade.recompute_franchisee(cascade.franchisee_of_club(to_club), bump="never")
    touch(agreement)
    touch(record)
    return ok(record)


@bp.get("/franchise/transfer-requests/<tid>")
def read_transfer(tid):
    guard(ALL_ROLES)
    return ok(get_transfer(tid))


@bp.get("/franchise/transfer-requests")
def list_transfers():
    guard(ALL_ROLES)
    return paged(db.transfer_requests, "agreement_id", "from_club_id", "to_club_id", "status")
