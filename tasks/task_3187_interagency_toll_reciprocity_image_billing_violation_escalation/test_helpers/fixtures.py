"""Composite setup helpers (PRD §3 workflows).

Every helper builds its preconditions from scratch against an empty database
using only PRD-declared endpoints, and returns the domain objects the tests
need. Setup calls use the lenient get_success_data so failures surface as
clear "Setup failed" messages.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_account_payload,
    create_agency_payload,
    create_away_agency_payload,
    create_discount_plan_payload,
    create_plate_data_agreement_payload,
    create_rate_schedule_payload,
    create_toll_transaction_payload,
    create_transponder_payload,
)
from .test_users import TEST_USERS, make_account_holder_headers

SO = TEST_USERS["settlement_officer_headers"]
AO = TEST_USERS["agency_ops_headers"]
VO = TEST_USERS["violations_officer_headers"]
PL = TEST_USERS["plate_lookup_agent_headers"]

DEFAULT_WINDOW_FROM = "2026-09-01T00:00:00Z"
DEFAULT_WINDOW_TO = "2026-09-30T00:00:00Z"
LONG_WINDOW_TO = "2027-01-01T00:00:00Z"
AGREEMENT_WINDOW_TO = "2027-09-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def create_home_agency(fee_bps=100, **overrides):
    resp = api_client.create_agency(
        create_agency_payload(reciprocity_fee_bps=fee_bps, **overrides), SO
    )
    return get_success_data(resp)


def create_away_agency(fee_bps=150, **overrides):
    resp = api_client.create_agency(
        create_away_agency_payload(reciprocity_fee_bps=fee_bps, **overrides), SO
    )
    return get_success_data(resp)


def create_rate_schedule(agency_id, **overrides):
    resp = api_client.create_rate_schedule(
        agency_id, create_rate_schedule_payload(**overrides), AO
    )
    return get_success_data(resp)


def create_discount_plan(agency_id, **overrides):
    resp = api_client.create_discount_plan(
        agency_id, create_discount_plan_payload(**overrides), AO
    )
    return get_success_data(resp)


def create_account(home_agency_id, discount_plan_id, **overrides):
    payload = create_account_payload(
        home_agency_id=home_agency_id, discount_plan_id=discount_plan_id, **overrides
    )
    resp = api_client.create_account(payload, AO)
    return get_success_data(resp)


def create_transponder(account_id, **overrides):
    resp = api_client.create_transponder(
        account_id, create_transponder_payload(**overrides), AO
    )
    return get_success_data(resp)


def post_trip(**overrides):
    resp = api_client.post_toll_transaction(create_toll_transaction_payload(**overrides), AO)
    return resp


def create_plate_agreement(requesting_agency_id, providing_agency_id, **overrides):
    payload = create_plate_data_agreement_payload(
        requesting_agency_id=requesting_agency_id,
        providing_agency_id=providing_agency_id,
        **overrides,
    )
    resp = api_client.create_plate_data_agreement(payload, SO)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: agency pair + plan + account + transponder hierarchy
# ---------------------------------------------------------------------------

def setup_agency_pair(home_fee_bps=100, away_fee_bps=150):
    """HOME (collector) and AWAY (facility) agencies, both ACTIVE."""
    home = create_home_agency(fee_bps=home_fee_bps)
    away = create_away_agency(fee_bps=away_fee_bps)
    return home, away


def setup_account_with_plan(home_id, plan_overrides=None, account_overrides=None):
    """Discount plan on HOME + account enrolled in it. Returns (plan, account)."""
    plan = create_discount_plan(home_id, **(plan_overrides or {}))
    account = create_account(home_id, plan["id"], **(account_overrides or {}))
    return plan, account


def setup_full_account(
    tag_number="TAG-1",
    vehicle_class="CLASS_2",
    plan_overrides=None,
    account_overrides=None,
    home_fee_bps=100,
    away_fee_bps=150,
):
    """Agency pair + plan + account + one ACTIVE transponder.

    Returns dict with keys: home, away, plan, account, transponder.
    """
    home, away = setup_agency_pair(home_fee_bps, away_fee_bps)
    plan_overrides = dict(plan_overrides or {})
    if "applies_to_agency_codes" not in plan_overrides:
        plan_overrides["applies_to_agency_codes"] = [away["agency_code"]]
    plan, account = setup_account_with_plan(home["id"], plan_overrides, account_overrides)
    transponder = create_transponder(
        account["id"], tag_number=tag_number, vehicle_class=vehicle_class
    )
    return {
        "home": home,
        "away": away,
        "plan": plan,
        "account": account,
        "transponder": transponder,
    }


def get_account(account_id):
    resp = api_client.get_account(account_id, AO)
    return get_success_data(resp)


def get_account_version(account_id):
    return get_account(account_id)["version"]


def record_replenishment(account_id, amount_cents, outcome, expected_version):
    resp = api_client.create_replenishment(
        account_id,
        {
            "amount_cents": amount_cents,
            "outcome": outcome,
            "expected_account_version": expected_version,
        },
        AO,
    )
    return get_success_data(resp)


def fail_replenishments(account_id, times, amount_cents=2500):
    """Drive replenishment_fail_count up by recording `times` failed top-ups.

    Returns the final replenishment response data.
    """
    result = None
    for _ in range(times):
        version = get_account_version(account_id)
        result = record_replenishment(account_id, amount_cents, "FAILED", version)
    return result


def setup_suspended_account(threshold=1000, replenishment_amount=2500, opening_balance=400):
    """Account SUSPENDED via three consecutive failed replenishments (PRD §3.5)."""
    home = create_home_agency()
    plan, account = setup_account_with_plan(
        home["id"],
        plan_overrides={"applies_to_agency_codes": []},
        account_overrides={
            "low_balance_threshold_cents": threshold,
            "replenishment_amount_cents": replenishment_amount,
            "opening_balance_cents": opening_balance,
        },
    )
    fail_replenishments(account["id"], 3, amount_cents=replenishment_amount)
    return {"home": home, "plan": plan, "account": get_account(account["id"])}


# ---------------------------------------------------------------------------
# Tier 3: image-billing and violation pipelines
# ---------------------------------------------------------------------------

def post_image_trip(away_id, plaza_code, plate_number, plate_state, trip_timestamp, idempotency_key, is_peak=False):
    """Post a plate-based (image) trip. Returns the TollTransaction."""
    resp = api_client.post_toll_transaction(
        create_toll_transaction_payload(
            plate_number=plate_number,
            plate_state=plate_state,
            away_agency_id=away_id,
            plaza_code=plaza_code,
            trip_timestamp=trip_timestamp,
            is_peak=is_peak,
            idempotency_key=idempotency_key,
        ),
        AO,
    )
    return get_success_data(resp)


def find_pending_image_bill():
    """Return the single PENDING_LOOKUP image bill (assumes exactly one exists)."""
    resp = api_client.list_image_bills(PL, params={"status": "PENDING_LOOKUP"})
    data = get_success_data(resp)
    assert len(data) == 1, f"Setup failed: expected 1 PENDING_LOOKUP bill, found {len(data)}"
    return data[0]


def resolve_bill_to_violation(image_bill_id):
    """Resolve with no account: bill ESCALATED and a Violation is created (PRD §3.6)."""
    resp = api_client.resolve_image_bill(image_bill_id, {}, PL)
    return get_success_data(resp)


def resolve_bill_to_account(image_bill_id, account_id):
    resp = api_client.resolve_image_bill(
        image_bill_id, {"resolved_account_id": account_id}, PL
    )
    return get_success_data(resp)


def setup_unregistered_plate_violation(base_rate_cents=800, image_fee_cents=100, plaza_code="P1", plate_number="UNREG1"):
    """Away agency + schedule + image trip for an unregistered plate resolved
    to no account -> Violation in OPEN status.

    Returns dict: away, txn, bill, violation. Violation toll_amount_cents
    equals the image gross (base + image_fee).
    """
    away = create_away_agency()
    provider = create_home_agency()  # any agency can act as the DMV proxy
    create_plate_agreement(
        away["id"], provider["id"],
        covers_states=["PA"],
        effective_to=LONG_WINDOW_TO,
    )
    create_rate_schedule(
        away["id"],
        plaza_code=plaza_code,
        base_rate_cents=base_rate_cents,
        image_fee_cents=image_fee_cents,
        effective_to=LONG_WINDOW_TO,
    )
    txn = post_image_trip(
        away["id"], plaza_code, plate_number, "PA", "2026-09-01T09:00:00Z", f"idem-{plate_number}"
    )
    bill = find_pending_image_bill()
    resolve_bill_to_violation(bill["id"])
    resp = api_client.list_violations(VO)
    violations = get_success_data(resp)
    assert len(violations) == 1, f"Setup failed: expected 1 violation, found {len(violations)}"
    return {"away": away, "txn": txn, "bill": bill, "violation": violations[0]}


def advance_days(days):
    resp = api_client.advance_day({"days": days}, SO)
    return get_success_data(resp)


def issue_notice(violation_id):
    resp = api_client.issue_notice(violation_id, VO)
    return get_success_data(resp)


def notice_three_times(violation_id):
    """Notices 1, 2, 3 spaced 30 days apart (PRD §3.7 fee schedule)."""
    issue_notice(violation_id)
    advance_days(30)
    issue_notice(violation_id)
    advance_days(30)
    issue_notice(violation_id)


def setup_billed_image_bill(account_balance=5000, base_rate_cents=800, image_fee_cents=100):
    """Full image-billing loop: agency pair + agreement + account + image trip
    + bill resolved to the account (BILLED, account debited).

    Returns dict: home, away, plan, account, txn, bill. The account balance
    after resolve is account_balance - (base_rate_cents + image_fee_cents).
    """
    home, away = setup_agency_pair()
    plan, account = setup_account_with_plan(
        home["id"],
        plan_overrides={"applies_to_agency_codes": [away["agency_code"]]},
        account_overrides={"opening_balance_cents": account_balance},
    )
    create_rate_schedule(
        away["id"], base_rate_cents=base_rate_cents, image_fee_cents=image_fee_cents
    )
    create_plate_agreement(away["id"], home["id"])
    txn = post_image_trip(
        away["id"], "P1", "IMG100", "NY", "2026-09-02T10:00:00Z", "img-trip-1"
    )
    bill = find_pending_image_bill()
    resolve_bill_to_account(bill["id"], account["id"])
    return {
        "home": home,
        "away": away,
        "plan": plan,
        "account": get_account(account["id"]),
        "txn": txn,
        "bill": bill,
    }


# ---------------------------------------------------------------------------
# Tier 4: disputes
# ---------------------------------------------------------------------------

def file_classification_dispute(account_id, toll_transaction_id, claimed_vehicle_class):
    resp = api_client.create_dispute(
        {
            "account_id": account_id,
            "dispute_type": "VEHICLE_CLASSIFICATION",
            "toll_transaction_id": toll_transaction_id,
            "claimed_vehicle_class": claimed_vehicle_class,
        },
        make_account_holder_headers(account_id),
    )
    return get_success_data(resp)


def file_misread_plate_dispute(account_id, image_bill_id, claimed_plate_number):
    resp = api_client.create_dispute(
        {
            "account_id": account_id,
            "dispute_type": "MISREAD_PLATE",
            "image_bill_id": image_bill_id,
            "claimed_plate_number": claimed_plate_number,
        },
        make_account_holder_headers(account_id),
    )
    return get_success_data(resp)


def begin_review(dispute_id):
    resp = api_client.begin_review_dispute(dispute_id, VO)
    return get_success_data(resp)


def setup_classification_dispute_under_review(
    tag_number="TAG-X",
    billed_class="CLASS_5",
    claimed_class="CLASS_2",
    billed_base=475,
    billed_axle=2.5,
    claimed_base=300,
    claimed_axle=1.0,
    opening_balance=100000,
    plaza_code="P3",
):
    """Account with a trip billed at `billed_class` and a classification
    dispute claiming `claimed_class` already in UNDER_REVIEW.

    Returns dict: home, away, plan, account, txn, dispute.
    """
    home, away = setup_agency_pair()
    plan, account = setup_account_with_plan(
        home["id"],
        plan_overrides={"applies_to_agency_codes": [away["agency_code"]]},
        account_overrides={"opening_balance_cents": opening_balance},
    )
    create_rate_schedule(
        away["id"],
        plaza_code=plaza_code,
        vehicle_class=billed_class,
        base_rate_cents=billed_base,
        axle_multiplier=billed_axle,
    )
    create_rate_schedule(
        away["id"],
        plaza_code=plaza_code,
        vehicle_class=claimed_class,
        base_rate_cents=claimed_base,
        axle_multiplier=claimed_axle,
    )
    create_transponder(account["id"], tag_number=tag_number, vehicle_class=billed_class)
    resp = post_trip(
        tag_number=tag_number,
        away_agency_id=away["id"],
        plaza_code=plaza_code,
        trip_timestamp="2026-09-05T09:00:00Z",
        idempotency_key=f"trip-{tag_number}",
    )
    txn = get_success_data(resp)
    dispute = file_classification_dispute(account["id"], txn["id"], claimed_class)
    begin_review(dispute["id"])
    return {
        "home": home,
        "away": away,
        "plan": plan,
        "account": account,
        "txn": txn,
        "dispute": dispute,
    }


# ---------------------------------------------------------------------------
# Tier 5: settlement files
# ---------------------------------------------------------------------------

def generate_settlement_file(from_agency_id, to_agency_id):
    resp = api_client.generate_settlement_file(
        {"from_agency_id": from_agency_id, "to_agency_id": to_agency_id}, SO
    )
    return get_success_data(resp)


def get_settlement_file(settlement_file_id):
    resp = api_client.get_settlement_file(settlement_file_id, SO)
    return get_success_data(resp)


def setup_three_tier_schedules(away_id, plaza_code="P1"):
    """Three CLASS_2 schedules on `away_id` with base rates 101/202/303 in
    adjacent half-open windows covering 03:00 / 09:00 / 15:00 on 2026-09-01."""
    create_rate_schedule(
        away_id,
        plaza_code=plaza_code,
        base_rate_cents=101,
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2026-09-01T06:00:00Z",
    )
    create_rate_schedule(
        away_id,
        plaza_code=plaza_code,
        base_rate_cents=202,
        effective_from="2026-09-01T06:00:00Z",
        effective_to="2026-09-01T12:00:00Z",
    )
    create_rate_schedule(
        away_id,
        plaza_code=plaza_code,
        base_rate_cents=303,
        effective_from="2026-09-01T12:00:00Z",
        effective_to="2026-09-01T18:00:00Z",
    )


def setup_three_trips_101_202_303(tag_number="TAG-A", opening_balance=100000, plaza_code="P1"):
    """HOME/AWAY pair + discount-0 plan + account + tag + three trips whose
    charged amounts are exactly 101, 202, 303 cents.

    Returns dict: home, away, plan, account, transponder, txns (list of 3).
    """
    ctx = setup_full_account(
        tag_number=tag_number,
        account_overrides={"opening_balance_cents": opening_balance},
    )
    setup_three_tier_schedules(ctx["away"]["id"], plaza_code=plaza_code)
    txns = []
    for ts, key in (
        ("2026-09-01T03:00:00Z", f"{tag_number}-trip-1"),
        ("2026-09-01T09:00:00Z", f"{tag_number}-trip-2"),
        ("2026-09-01T15:00:00Z", f"{tag_number}-trip-3"),
    ):
        resp = post_trip(
            tag_number=tag_number,
            away_agency_id=ctx["away"]["id"],
            plaza_code=plaza_code,
            trip_timestamp=ts,
            idempotency_key=key,
        )
        txns.append(get_success_data(resp))
    ctx["txns"] = txns
    return ctx
