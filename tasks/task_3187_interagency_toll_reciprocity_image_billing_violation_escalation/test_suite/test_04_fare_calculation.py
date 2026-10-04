"""Toll fare calculation: rounding, discounts, peak, image variant (PRD §3.4)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_account,
    create_discount_plan,
    create_home_agency,
    create_rate_schedule,
    create_transponder,
    create_away_agency,
    create_plate_agreement,
    get_account,
    get_success_data,
    setup_full_account,
    setup_agency_pair,
    setup_account_with_plan,
)

AO = TEST_USERS["agency_ops_headers"]


def _post(away_id, **overrides):
    payload = {
        "away_agency_id": away_id,
        "plaza_code": overrides.pop("plaza_code", "P1"),
        "trip_timestamp": overrides.pop("trip_timestamp", "2026-09-02T09:00:00Z"),
        "is_peak": overrides.pop("is_peak", False),
        "idempotency_key": overrides.pop("idempotency_key", "k1"),
    }
    payload.update(overrides)
    return get_success_data(api_client.post_toll_transaction(payload, AO))


def test_daily_cap_chronological_nested_rounding():
    """PRD §3.4: "If the plan's `daily_discount_cap_cents` is greater than zero,
    the granted discount is the smaller of the raw discount and the remaining
    cap, where the remaining cap is the cap minus the account's
    `discount_used_today_cents`, floored at zero; otherwise the raw discount
    stands."
    PRD §3.4: "Trips within a single UTC day are processed in `trip_timestamp`
    order with `created_at` as the tie-breaker, each trip drawing down the
    remaining cap as it posts; the cap is never redistributed retroactively, so
    an earlier trip keeps its full discount even if a later trip is voided —
    voiding does not restore `discount_used_today_cents`."

    Design: Difficulty/combinatorial_formula/daily_cap_chronological_nested_rounding (mode b)
    """
    home, away = setup_agency_pair()
    create_rate_schedule(away["id"], plaza_code="P2", base_rate_cents=575)
    plan = create_discount_plan(
        home["id"],
        plan_code="COMMUTER",
        discount_pct=0.20,
        daily_discount_cap_cents=300,
        applies_to_agency_codes=[away["agency_code"]],
    )
    account = create_account(
        home["id"],
        plan["id"],
        holder_name="Fran Cap",
        holder_email="fran@example.com",
        opening_balance_cents=100000,
    )
    create_transponder(account["id"], tag_number="TAG-C", plate_number="CAP300")

    t1 = _post(away["id"], tag_number="TAG-C", plaza_code="P2",
               trip_timestamp="2026-09-04T09:00:00Z", idempotency_key="c1")
    t2 = _post(away["id"], tag_number="TAG-C", plaza_code="P2",
               trip_timestamp="2026-09-04T10:00:00Z", idempotency_key="c2")
    t3 = _post(away["id"], tag_number="TAG-C", plaza_code="P2",
               trip_timestamp="2026-09-04T11:00:00Z", idempotency_key="c3")

    # round_half_up(575*0.2)=115 per trip; cap 300 -> 115, 115, 70.
    assert t1["discount_amount_cents"] == 115
    assert t1["charged_amount_cents"] == 460
    assert t2["discount_amount_cents"] == 115
    assert t2["charged_amount_cents"] == 460
    assert t3["discount_amount_cents"] == 70
    assert t3["charged_amount_cents"] == 505

    acct = get_account(account["id"])
    assert acct["discount_used_today_cents"] == 300
    assert acct["balance_cents"] == 98575


def test_min_trips_threshold_gates_discount():
    """PRD §3.2: "An optional `min_trips_per_month`, defaulting to zero, gates
    the discount on loyalty: when it is greater than zero, the discount applies
    only once the account has accumulated at least that many posted transponder
    trips in the current UTC month."

    Design: Corner/calculations/min_trips_threshold_gates_discount
    """
    home, away = setup_agency_pair()
    create_rate_schedule(away["id"], base_rate_cents=1000)
    plan = create_discount_plan(
        home["id"],
        plan_code="FLEET",
        discount_pct=0.10,
        daily_discount_cap_cents=0,
        applies_to_agency_codes=[away["agency_code"]],
        min_trips_per_month=2,
    )
    account = create_account(
        home["id"], plan["id"], opening_balance_cents=100000
    )
    create_transponder(account["id"], tag_number="TAG-M", plate_number="TRP100")

    t1 = _post(away["id"], tag_number="TAG-M", trip_timestamp="2026-09-14T08:00:00Z", idempotency_key="m1")
    t2 = _post(away["id"], tag_number="TAG-M", trip_timestamp="2026-09-14T09:00:00Z", idempotency_key="m2")
    t3 = _post(away["id"], tag_number="TAG-M", trip_timestamp="2026-09-14T10:00:00Z", idempotency_key="m3")

    assert t1["discount_amount_cents"] == 0
    assert t2["discount_amount_cents"] == 0
    assert t3["discount_amount_cents"] == 100
    assert get_account(account["id"])["trips_this_month"] == 3


def test_image_toll_gets_no_discount_regardless_of_plan():
    """PRD §3.4: "For an image trip, no discount ever applies:
    `discount_amount_cents` is zero, and `gross_amount_cents` is the pre-fee
    gross plus the schedule's `image_fee_cents`."

    Design: Corner/calculations/image_toll_gets_no_discount_regardless_of_plan
    """
    home, away = setup_agency_pair()
    create_rate_schedule(away["id"], base_rate_cents=800, image_fee_cents=100)
    plan = create_discount_plan(
        home["id"],
        plan_code="PROMO20",
        discount_pct=0.20,
        daily_discount_cap_cents=0,
        applies_to_agency_codes=[away["agency_code"]],
    )
    create_account(home["id"], plan["id"], opening_balance_cents=10000)
    create_plate_agreement(away["id"], home["id"])

    txn = _post(
        away["id"],
        plate_number="VID100",
        plate_state="NY",
        trip_timestamp="2026-09-15T09:00:00Z",
        idempotency_key="vimg",
    )
    assert txn["detection_method"] == "IMAGE"
    assert txn["gross_amount_cents"] == 900
    assert txn["discount_amount_cents"] == 0
    assert txn["charged_amount_cents"] == 900


def test_peak_flag_off_skips_peak_multiplier():
    """PRD §3.4: "The base computation multiplies `base_rate_cents` by
    `axle_multiplier` and rounds the product half-up to whole cents; if
    `is_peak` is true, that axle component is then multiplied by
    `peak_multiplier` and again rounded half-up to whole cents."

    Design: Corner/calculations/peak_flag_off_skips_peak_multiplier
    """
    home, away = setup_agency_pair()
    create_rate_schedule(away["id"], base_rate_cents=800, peak_multiplier=1.25)
    plan = create_discount_plan(
        home["id"], plan_code="STD", applies_to_agency_codes=[away["agency_code"]]
    )
    account = create_account(home["id"], plan["id"], opening_balance_cents=10000)
    create_transponder(account["id"], tag_number="TAG-P", plate_number="PEAK10")

    tp = _post(away["id"], tag_number="TAG-P", trip_timestamp="2026-09-16T07:00:00Z",
               is_peak=True, idempotency_key="pk1")
    to = _post(away["id"], tag_number="TAG-P", trip_timestamp="2026-09-16T13:00:00Z",
               is_peak=False, idempotency_key="pk2")

    assert tp["gross_amount_cents"] == 1000
    assert to["gross_amount_cents"] == 800


def test_discount_usage_resets_on_day_rollover():
    """PRD §2.6: "Advancing the day counter is the system's ops-run checkpoint:
    each advancement increments the epoch day index and triggers a sweep that
    re-evaluates plate data agreement expiry, runs the violation escalation
    pipeline, auto-rejects stale disputes, resets every account's
    `discount_used_today_cents` as the UTC day rolls over, and resets every
    account's `trips_this_month` when the advancement crosses a UTC month
    boundary."

    Design: Corner/cross_cutting_layers/discount_usage_resets_on_day_rollover
    """
    home, away = setup_agency_pair()
    create_rate_schedule(away["id"], plaza_code="P2", base_rate_cents=575)
    plan = create_discount_plan(
        home["id"],
        plan_code="COMMUTER",
        discount_pct=0.20,
        daily_discount_cap_cents=300,
        applies_to_agency_codes=[away["agency_code"]],
    )
    account = create_account(home["id"], plan["id"], opening_balance_cents=100000)
    create_transponder(account["id"], tag_number="TAG-DS", plate_number="RST100")

    for ts, key in (
        ("2026-09-04T09:00:00Z", "ds1"),
        ("2026-09-04T10:00:00Z", "ds2"),
        ("2026-09-04T11:00:00Z", "ds3"),
    ):
        _post(away["id"], tag_number="TAG-DS", plaza_code="P2",
              trip_timestamp=ts, idempotency_key=key)

    assert get_account(account["id"])["discount_used_today_cents"] == 300

    get_success_data(api_client.advance_day({"days": 1}, TEST_USERS["settlement_officer_headers"]))

    t4 = _post(away["id"], tag_number="TAG-DS", plaza_code="P2",
               trip_timestamp="2026-09-05T09:00:00Z", idempotency_key="ds4")
    assert t4["discount_amount_cents"] == 115
    assert get_account(account["id"])["discount_used_today_cents"] == 115
