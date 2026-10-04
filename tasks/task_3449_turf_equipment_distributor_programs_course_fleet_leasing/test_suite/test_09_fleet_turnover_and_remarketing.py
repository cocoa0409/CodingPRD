"""Fleet turnover and remarketing: Cascade C1 (unit -> lease -> course),
duplicate serials, reservation expiry, compounding ask decay with its floor,
and the billing progression's conserved net contract value (PRD §3.6, §3.7,
§2.9).
"""
from test_helpers import (
    ApiErrorId,
    advance_clock,
    assert_lease_billing_invariant,
    create_catalog_model,
    create_course_for,
    create_lease_for,
    list_lease_units,
    make_course_manager_headers,
    make_distributor_manager_headers,
    record_unit_return,
    run_rollover,
    setup_program,
    setup_remarketed_unit,
    setup_turned_over_lease,
    walk_lease_to,
    deliver_unit,
    validate_error,
    validate_success,
)

WK_MDX = {
    "model_code": "WK-MDX",
    "category": "UTILITY_VEHICLE",
    "tier": "PRO",
    "list_price_cents": 2800000,
    "eligible_turf_types": ["BENTGRASS", "BERMUDA", "POA_ANNUA", "MIXED"],
    "warranty_labor_hourly_cap_cents": 8500,
    "parts_support_years": 8,
}


def test_return_records_observations_and_closes_lease(api, corporate_admin_headers):
    """PRD §3.6: "The physical return, from `RETURN_REQUESTED` to `RETURNED`,
    is recorded by the owning `DistributorManager` with two observations: the
    `hours_used` on the engine and a `condition_grade` of `A`, `B`, `C`, or
    `D`."
    PRD §2.9: "Its first link fires when a unit completes its return: if every
    unit of the lease has left the active pipeline states `ORDERED`,
    `DELIVERED`, `IN_SERVICE`, and `RETURN_REQUESTED`, the lease itself moves
    from `TURNOVER_IN_PROGRESS` to `CLOSED` — that closure is the cascade's
    second link."

    Design: Difficulty/transitive_cascade/unit_return_closes_lease_and_renews_course
    """
    ctx = setup_turned_over_lease(unit_count=1)
    unit = record_unit_return(ctx["units"][0], hours_used=300, condition_grade="B")
    assert unit["status"] == "RETURNED"
    assert unit["hours_used"] == 300 and unit["condition_grade"] == "B"
    lease = validate_success(api.get_lease(ctx["lease"]["id"], corporate_admin_headers))
    assert lease["status"] == "CLOSED", (
        f"the last unit leaving the active pipeline closes the lease; got "
        f"{lease['status']!r}"
    )


def test_lease_closure_moves_course_to_in_renewal(api, corporate_admin_headers):
    """PRD §2.9: "The third link then returns the course from `ACTIVE_LEASE` to
    `IN_RENEWAL`, where it awaits its next replacement cycle."

    Design: Difficulty/transitive_cascade/unit_return_closes_lease_and_renews_course
    """
    ctx = setup_turned_over_lease(unit_count=1)
    record_unit_return(ctx["units"][0], hours_used=300, condition_grade="B")
    lease = validate_success(api.get_lease(ctx["lease"]["id"], corporate_admin_headers))
    assert lease["status"] == "CLOSED"
    course = validate_success(api.get_course(ctx["course"]["id"], corporate_admin_headers))
    assert course["status"] == "IN_RENEWAL", (
        f"the lease closure cascades to the course; got {course['status']!r}"
    )


def test_one_unit_outstanding_keeps_lease_in_turnover(api, corporate_admin_headers):
    """PRD §3.6: "The return also fires the first link of Cascade C1: if that
    return leaves every unit of the lease outside the active pipeline states
    `ORDERED`, `DELIVERED`, `IN_SERVICE`, and `RETURN_REQUESTED`, the lease
    closes — `TURNOVER_IN_PROGRESS` to `CLOSED` — and its course steps from
    `ACTIVE_LEASE` back to `IN_RENEWAL`, ready for the next replacement cycle."

    Design: Corner/state_machines/one_unit_outstanding_keeps_lease_in_turnover
    """
    ctx = setup_turned_over_lease(unit_count=2)
    unit = record_unit_return(ctx["units"][0], hours_used=300, condition_grade="B")
    assert unit["status"] == "RETURNED"
    lease = validate_success(api.get_lease(ctx["lease"]["id"], corporate_admin_headers))
    assert lease["status"] == "TURNOVER_IN_PROGRESS", (
        "closure requires the LAST unit to leave the active pipeline"
    )
    course = validate_success(api.get_course(ctx["course"]["id"], corporate_admin_headers))
    assert course["status"] == "ACTIVE_LEASE", (
        "the closure cascade has not fired while a unit is outstanding"
    )


def test_unit_deliver_duplicate_serial_rejected(api, corporate_admin_headers):
    """PRD §3.6: "Delivery requires the owning lease to be in `APPROVED` or
    `ACTIVE`, and the serial must be unique within the model: a
    `serial_number` already carried by another unit of the same model is
    rejected with `ERR_DUPLICATE_SERIAL` (HTTP 409)."

    Design: Corner/validations/unit_deliver_duplicate_serial_rejected
    """
    ctx = setup_program()
    lease = create_lease_for(
        ctx["distributor"], ctx["course"],
        [{"model_id": ctx["model"]["id"], "qty": 2}],
        cycle_months=36, start_date="2026-09-01",
    )
    lease = walk_lease_to(lease, "APPROVED")
    u1, u2 = list_lease_units(lease)[:2]
    delivered = deliver_unit(u1, "SN-DUP")
    assert delivered["status"] == "DELIVERED"
    resp = api.transition_unit(
        u2["id"], "DELIVERED",
        make_distributor_manager_headers(ctx["distributor"]["id"]),
        serial_number="SN-DUP",
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SERIAL.value)
    after = validate_success(api.get_unit(u2["id"], corporate_admin_headers))
    assert after["status"] == "ORDERED", (
        "the rejected delivery leaves the second unit ORDERED"
    )


def test_rollover_expires_reservation_relists_unit(api, corporate_admin_headers):
    """PRD §3.7: "A `CourseManager` may reserve a listed unit, moving it to
    `RESERVED`; the reservation records the acting course as
    `reserved_by_course_id` and sets `reservation_expires_at` to the logical
    clock plus a 7-day hold."
    PRD §3.7: "If the hold lapses first, the season rollover returns the unit
    to `REMARKET_LISTED`, clearing `reserved_by_course_id` and
    `reservation_expires_at` — and notably leaving the ask untouched, since
    reservation expiry is not a decay step; the listing-reservation loop is
    cyclic."

    Design: Corner/state_machines/rollover_expires_reservation_relists_unit
    """
    ctx = setup_remarketed_unit(model_overrides=WK_MDX)
    unit = ctx["unit"]
    # Listing: round_half_up(2,800,000 x 0.55 x 0.85) = 1,309,000 (grade B).
    assert unit["status"] == "REMARKET_LISTED"
    assert unit["asking_price_cents"] == 1309000
    buyer = create_course_for(
        ctx["distributor"], name="Coyote Run GC", turf_profile="BERMUDA",
        cut_quality_standard="MAINTENANCE", credit_limit_cents=5000000,
    )
    reserved = validate_success(
        api.transition_unit(
            unit["id"], "RESERVED", make_course_manager_headers(buyer["id"])
        )
    )
    assert reserved["reserved_by_course_id"] == buyer["id"]
    assert reserved["reservation_expires_at"] is not None

    advance_clock("2026-10-10T00:00:00Z")  # hold set 2026-10-02 + 7 days has lapsed
    run_rollover()
    after = validate_success(api.get_unit(unit["id"], corporate_admin_headers))
    assert after["status"] == "REMARKET_LISTED"
    assert after["reserved_by_course_id"] is None
    assert after["reservation_expires_at"] is None
    assert after["asking_price_cents"] == 1309000, (
        f"reservation expiry is not a decay step; ask must be untouched, got "
        f"{after['asking_price_cents']}"
    )


def test_remarketing_decay_compounds_per_rollover_with_floor(api, corporate_admin_headers):
    """PRD §3.7: "The initial ask, recorded as `asking_price_cents`, is 55
    percent of the model's `list_price_cents` scaled by the return
    `condition_grade`'s multiplier — 1.00 for `A`, 0.85 for `B`, 0.70 for `C`,
    0.50 for `D` — rounded half-up to integer cents. The `floor_price_cents`,
    the minimum the ask may ever reach, is 60 percent of that initial ask,
    likewise rounded half-up."
    PRD §3.7: "every season rollover applies exactly one decay step to each
    unit still in `REMARKET_LISTED`, reducing `asking_price_cents` by 2 percent
    with round-half-up at every step, subject to the floor — the new ask is the
    larger of `floor_price_cents` and the decayed figure. Because the decay
    applies to the current ask rather than the original, it compounds across
    rollover runs."

    Design: Corner/calculations/remarketing_decay_compounds_per_rollover_with_floor
    """
    ctx = setup_remarketed_unit(model_overrides=WK_MDX)
    unit = ctx["unit"]
    assert unit["asking_price_cents"] == 1309000
    # floor = round_half_up(1,309,000 x 0.60) = 785,400.
    assert unit["floor_price_cents"] == 785400
    run_rollover()  # 1,309,000 -> 1,282,820
    run_rollover()  # 1,282,820 -> 1,257,164
    run_rollover()  # 1,257,164 -> 1,232,021
    after = validate_success(api.get_unit(unit["id"], corporate_admin_headers))
    assert after["asking_price_cents"] == 1232021, (
        f"three per-run decay steps with per-step round_half_up; got "
        f"{after['asking_price_cents']}"
    )
    assert after["asking_price_cents"] >= after["floor_price_cents"]


def test_rollover_bills_elapsed_months(api, corporate_admin_headers):
    """PRD §3.6: "While a lease is `ACTIVE`, each season rollover also advances
    its billing. The elapsed term is the number of whole months between
    `start_date` and the current logical date, clamped to the range from 0 to
    `cycle_months`."
    PRD §3.6: "Equivalently, `billed_to_date_cents` is the smaller of
    `net_contract_value_cents` and the elapsed months times `monthly_rate_cents`
    while the elapsed term is below `cycle_months`, and equals the full
    `net_contract_value_cents` once the term is reached."

    Design: Difficulty/compensating_invariant/lease_billing_conserves_net_contract_value
    """
    ctx = setup_program()
    m2 = create_catalog_model(**WK_MDX)
    lease = create_lease_for(
        ctx["distributor"], ctx["course"],
        [{"model_id": ctx["model"]["id"], "qty": 4}, {"model_id": m2["id"], "qty": 2}],
        cycle_months=36, start_date="2026-09-01",
    )
    lease = walk_lease_to(lease, "ACTIVE")
    # CLUB, September start: net = total = round(35,600,000 x 1.08) =
    # 38,448,000; monthly = 38,448,000 / 36 = 1,068,000 exactly.
    assert lease["net_contract_value_cents"] == 38448000
    assert lease["monthly_rate_cents"] == 1068000
    advance_clock("2026-12-01T00:00:00Z")  # 3 whole months elapsed
    run_rollover()
    after = validate_success(api.get_lease(lease["id"], corporate_admin_headers))
    assert after["billed_to_date_cents"] == 3204000, (
        f"3 elapsed months x 1,068,000; got {after['billed_to_date_cents']}"
    )
    assert after["remaining_balance_cents"] == 35244000


def test_billing_invariant_conserves_net_contract_value(api, corporate_admin_headers):
    """PRD §3.6: "`remaining_balance_cents` is always
    `net_contract_value_cents` minus `billed_to_date_cents`, and the system
    maintains the invariant, at every observable instant, that
    `billed_to_date_cents` plus `remaining_balance_cents` equals
    `net_contract_value_cents` exactly."

    Design: Difficulty/compensating_invariant/lease_billing_conserves_net_contract_value
    """
    ctx = setup_program()
    m2 = create_catalog_model(**WK_MDX)
    lease = create_lease_for(
        ctx["distributor"], ctx["course"],
        [{"model_id": ctx["model"]["id"], "qty": 4}, {"model_id": m2["id"], "qty": 2}],
        cycle_months=36, start_date="2026-09-01",
    )
    lease = walk_lease_to(lease, "ACTIVE")
    assert_lease_billing_invariant(lease)
    advance_clock("2026-12-01T00:00:00Z")
    run_rollover()
    after = validate_success(api.get_lease(lease["id"], corporate_admin_headers))
    assert_lease_billing_invariant(after)
    assert (
        after["billed_to_date_cents"] + after["remaining_balance_cents"]
        == after["net_contract_value_cents"]
        == 38448000
    ), "billing moves value between billed and remaining with zero drift"
