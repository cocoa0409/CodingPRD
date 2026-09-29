"""Queue B - corner section ``complexity_layers``.

Six instances, two of which the §1.8 difficulty queue already drives (the
provisional-versus-final charge variants over one timeline, and the four-hop
decide cascade), leaving four: the two optimistic-concurrency tokens PRD 2.7
declares, the independence of the per-aggregate ``version`` counters, and the
per-cycle reset of the tiered rate ladder.

Two rendering conventions apply to the PRD quotations in the docstrings below:
the PRD's em dashes are written as ASCII hyphens and its transition arrows as
``->``.  Nothing else is altered, so every quoted sentence is greppable in
``workspace/PRD.md`` once those two substitutions are made.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CAR_CYCLE_OVERLAP,
    ERR_INVALID_REQUEST,
    ERR_INVOICE_VERSION_STALE,
    ERR_RAIL_CAR_VERSION_STALE,
)
from test_helpers.assertions import (
    assert_error_meta_is_minimal,
    assert_subset_equal,
)
from test_helpers.constants import (
    ACCESS_MODE_EMBARGOED,
    ACCESS_MODE_GATE_CONTROLLED,
    ACCESS_MODE_OPEN,
    BILLING_POSTURE_CREDIT_HOLD,
    CHARGE_FINAL,
    CYCLE_A_ACTUAL_AT,
    CYCLE_A_CHARGEABLE_DAYS,
    CYCLE_A_GROSS_CENTS,
    CYCLE_B_ACTUAL_AT,
    CYCLE_B_CONSTRUCTIVE_AT,
    CYCLE_B_GROSS_CENTS,
    CYCLE_B_NOTICE_SENT_AT,
    COLD_START_CLOCK,
    DEFAULT_TIER1_DAY_COUNT,
    DEFAULT_TIER1_RATE_RAILROAD,
    DEFAULT_TIER2_RATE_RAILROAD,
    INVOICE_ISSUED,
    MOVEMENT_ORDERED,
    OWNERSHIP_RAILROAD_OWNED,
)
from test_helpers.test_users import ADMIN, AGENT

# PRD 2.7's two OCC tokens are exercised with claims well inside the reference
# invoice, so no ceiling or window band can be what answers.
FIRST_CLAIM_CENTS = 10000
SECOND_CLAIM_CENTS = 5000

REPLAYED_NARRATIVE = "Second reader replays the same version."
RETRY_NARRATIVE = "Re-read the version and try again."

WAYBILL_FIRST = "WB-C9L2-A"
WAYBILL_REPLAY = "WB-C9L2-B"
WAYBILL_RETRY = "WB-C9L2-C"

GATE_CREW_REASON = "Gate crew only."
WASHOUT_REASON = "Track washout."
PAST_DUE_REASON = "Past due."
UNDECLARED_ACCESS_MODE = "SIDING"

# PRD 3.5: the release date counts only from the gate-close hour, so these two
# releases differ by one chargeable day rather than by one calendar day.
TWO_DAY_RELEASE_AT = "2026-08-09T16:00:00.000Z"
RESET_RELEASE_AT = "2026-08-10T16:00:00.000Z"
TWO_DAY_GROSS_CENTS = 25100  # 2 x 12550, both days on tier one


# ===========================================================================
# instance: stale_invoice_version_on_dispute_create
# ===========================================================================
def test_the_replayed_invoice_version_is_told_its_read_is_stale(api):
    """The rejected body is byte-identical to one that just succeeded.

    PRD 2.7: "`POST /demurrage/disputes` requires a non-optional
    `expected_invoice_version` field carrying the `version` the client last
    observed on the invoice it is disputing. If that value does not equal the
    invoice's current `version`, the request is rejected with
    `ERR_INVOICE_VERSION_STALE` (HTTP 412). A successful create increments the
    invoice's `version` by 1 and re-derives its `dispute_count`, so a replayed
    `expected_invoice_version` fails and the client cannot silently overwrite a
    dispute roster it has not observed."

    Design: Corner/complexity_layers/stale_invoice_version_on_dispute_create
    """
    world = fx.reference_world(api)
    fx.released_cycle_a(api, world)
    invoice = fx.issued_invoice(api, world)
    assert_subset_equal(
        invoice,
        {
            "status": INVOICE_ISSUED,
            "total_gross_cents": CYCLE_A_GROSS_CENTS,
            "dispute_count": 0,
        },
    )
    first_version = invoice["version"]

    payload = f.dispute_payload(
        invoice["id"],
        first_version,
        FIRST_CLAIM_CENTS,
        narrative=REPLAYED_NARRATIVE,
    )
    accepted = get_success_data(
        api.create_dispute(payload, world["customer_headers"]), 201
    )
    assert accepted["claimed_credit_cents"] == FIRST_CLAIM_CENTS

    # The very same object, sent again by a reader that never re-read.
    replay = api.create_dispute(payload, world["customer_headers"])
    validate_error(replay, ERR_INVOICE_VERSION_STALE)
    assert replay.status_code == 412
    assert_error_meta_is_minimal(replay)

    after_replay = fx.get_invoice(api, invoice["id"])
    assert_subset_equal(
        after_replay,
        {"version": first_version + 1, "dispute_count": 1},
    )

    # Re-reading the version is the only sanctioned remedy: there is no retry
    # token anywhere in this service.
    retry = f.dispute_payload(
        invoice["id"],
        after_replay["version"],
        SECOND_CLAIM_CENTS,
        narrative=RETRY_NARRATIVE,
    )
    second = get_success_data(
        api.create_dispute(retry, world["customer_headers"]), 201
    )
    assert second["id"] != accepted["id"]

    settled = fx.get_invoice(api, invoice["id"])
    assert_subset_equal(
        settled,
        {"version": first_version + 2, "dispute_count": 2},
    )


# ===========================================================================
# instance: stale_rail_car_version_on_cycle_create
# ===========================================================================
def test_the_stale_car_read_outranks_the_overlap_it_could_not_see(api):
    """Two agents ordering one car: 412 first, then 409 once the read is fresh.

    PRD 3.2: "Note the ordering consequence spelled out in §2.8: the stale-version
    check on the car is evaluated *before* the overlap check, so a client working
    from a stale read is told its read is stale rather than being told about an
    overlap it had no way of seeing."

    Design: Corner/complexity_layers/stale_rail_car_version_on_cycle_create
    """
    world = fx.reference_world(api)
    car = fx.make_rail_car(api, ownership=OWNERSHIP_RAILROAD_OWNED)
    first_version = car["version"]
    assert car["active_cycle_count"] == 0

    def order(expected_version, waybill):
        return api.create_placement_cycle(
            f.placement_cycle_payload(
                world["customer_id"],
                car["id"],
                world["facility_id"],
                world["tariff_id"],
                expected_version,
                waybill_number=waybill,
            ),
            AGENT,
        )

    cycle = get_success_data(order(first_version, WAYBILL_FIRST), 201)
    assert cycle["movement_status"] == MOVEMENT_ORDERED

    stale = order(first_version, WAYBILL_REPLAY)
    validate_error(stale, ERR_RAIL_CAR_VERSION_STALE)
    assert stale.status_code == 412
    assert_error_meta_is_minimal(stale)

    fresh = fx.get_car(api, car["id"])
    assert_subset_equal(
        fresh, {"version": first_version + 1, "active_cycle_count": 1}
    )

    # The version was the only thing the retry fixed, and the overlap the first
    # caller could not see is now the answer.
    overlapping = order(fresh["version"], WAYBILL_RETRY)
    validate_error(overlapping, ERR_CAR_CYCLE_OVERLAP)
    assert overlapping.status_code == 409

    unchanged = fx.get_car(api, car["id"])
    assert_subset_equal(
        unchanged, {"version": first_version + 1, "active_cycle_count": 1}
    )


# ===========================================================================
# instance: version_counters_advance_once_per_write_and_only_on_the_written_aggregate
# ===========================================================================
def test_each_aggregate_keeps_its_own_version_counter(api):
    """One increment per successful write, on the written aggregate alone.

    PRD 2.9: "Whenever an operation mutates a resource, that resource's
    `updated_at` is refreshed to the current logical clock and its `version`
    increases by exactly 1. When an operation cascades into a second resource - an
    invoice whose totals are rewritten, a consignee whose balance is re-derived, a
    rail car whose cycle count changes, a facility whose occupancy changes - the
    narrative in §3 states explicitly whether that second resource's `version`
    also increments."

    Design: Corner/complexity_layers/version_counters_advance_once_per_write_and_only_on_the_written_aggregate
    """
    fx.set_clock(api, COLD_START_CLOCK)
    facility = fx.make_industry_track(api)
    customer = fx.make_customer(api)
    car = fx.make_rail_car(api)
    assert facility["version"] == 1
    assert customer["version"] == 1
    assert car["version"] == 1
    assert facility["access_mode"] == ACCESS_MODE_OPEN

    gated = get_success_data(
        api.set_facility_access_mode(
            facility["id"],
            f.access_mode_payload(ACCESS_MODE_GATE_CONTROLLED, reason=GATE_CREW_REASON),
            AGENT,
        )
    )
    assert_subset_equal(
        gated, {"access_mode": ACCESS_MODE_GATE_CONTROLLED, "version": 2}
    )

    embargoed = get_success_data(
        api.set_facility_access_mode(
            facility["id"],
            f.access_mode_payload(ACCESS_MODE_EMBARGOED, reason=WASHOUT_REASON),
            AGENT,
        )
    )
    # Two writes, two increments, no skips.
    assert_subset_equal(
        embargoed, {"access_mode": ACCESS_MODE_EMBARGOED, "version": 3}
    )

    held = get_success_data(
        api.set_credit_hold(
            customer["id"], f.credit_hold_payload(True, reason=PAST_DUE_REASON), ADMIN
        )
    )
    assert_subset_equal(
        held, {"billing_posture": BILLING_POSTURE_CREDIT_HOLD, "version": 2}
    )

    # §4 gives a facility no read endpoint at all, so the only way to observe
    # its counter is to write to it again: version 4 here is this write's own
    # single increment, which is exactly what proves the consignee's credit-hold
    # write added nothing to the facility.  These are independent counters, not
    # one global sequence.
    reopened = fx.probe_facility(api, facility["id"])
    assert_subset_equal(reopened, {"access_mode": ACCESS_MODE_OPEN, "version": 4})
    # And no unrelated write touched the car at all.
    assert fx.get_car(api, car["id"])["version"] == 1

    # A rejected write bumps nothing: the next accepted write still lands on 5.
    refused = api.set_facility_access_mode(
        facility["id"], {"access_mode": UNDECLARED_ACCESS_MODE}, AGENT
    )
    validate_error(refused, ERR_INVALID_REQUEST)
    assert refused.status_code == 400
    after_refusal = get_success_data(
        api.set_facility_access_mode(
            facility["id"],
            f.access_mode_payload(ACCESS_MODE_GATE_CONTROLLED, reason=GATE_CREW_REASON),
            AGENT,
        )
    )
    assert after_refusal["version"] == 5
    assert fx.get_customer(api, customer["id"])["version"] == 2
    assert fx.get_car(api, car["id"])["version"] == 1


# ===========================================================================
# instance: tier_ladder_crosses_at_the_third_day_and_resets_on_the_next_cycle
# ===========================================================================
def test_the_tier_ladder_crosses_at_the_third_day_and_resets_per_cycle(api):
    """The cumulative threshold is per placement cycle, not per consignee.

    PRD 3.6: "The number of tier-one days is the lesser of `billable_days` and
    `tier1_day_count`. The number of tier-two days is `billable_days` less
    `tier1_day_count`, floored at zero, and then capped at `tier2_day_count`."
    And: "At the tariff defaults of 2 tier-one days and 3 tier-two days: exactly 2
    billable days bills entirely at the tier-one rate; 3 billable days straddle
    into tier two for exactly one day".

    Design: Corner/complexity_layers/tier_ladder_crosses_at_the_third_day_and_resets_on_the_next_cycle
    """
    world = fx.reference_world(api)
    # Each cycle gets its own industry track: PRD 3.1 re-derives last_switch_at
    # from releases as well as spots, so three cycles whose recorded instants
    # interleave would otherwise trip the PRD 3.4 switch-buffer guard for a
    # reason that has nothing to do with the rate ladder.
    second_track = fx.make_industry_track(api)
    third_track = fx.make_industry_track(api)

    two_day_cycle = fx.released_cycle(api, world, released_at=TWO_DAY_RELEASE_AT)
    two_day_charge = fx.charge_of_cycle(api, two_day_cycle["id"])
    assert_subset_equal(
        two_day_charge,
        {
            "status": CHARGE_FINAL,
            "chargeable_days": DEFAULT_TIER1_DAY_COUNT,
            "billable_days": DEFAULT_TIER1_DAY_COUNT,
            "bunching_exempt_days": 0,
            "gross_amount_cents": TWO_DAY_GROSS_CENTS,
        },
    )
    assert TWO_DAY_GROSS_CENTS == 2 * DEFAULT_TIER1_RATE_RAILROAD

    # The same free-time window released one calendar day later crosses into
    # tier two, and the third day is the first day to price there.
    three_day_cycle = fx.released_cycle_a(api, world, facility_id=third_track["id"])
    three_day_charge = fx.charge_of_cycle(api, three_day_cycle["id"])
    assert_subset_equal(
        three_day_charge,
        {
            "chargeable_days": CYCLE_A_CHARGEABLE_DAYS,
            "billable_days": CYCLE_A_CHARGEABLE_DAYS,
            "gross_amount_cents": CYCLE_A_GROSS_CENTS,
        },
    )
    assert CYCLE_A_GROSS_CENTS == TWO_DAY_GROSS_CENTS + DEFAULT_TIER2_RATE_RAILROAD
    assert three_day_charge["gross_amount_cents"] - two_day_charge[
        "gross_amount_cents"
    ] == DEFAULT_TIER2_RATE_RAILROAD

    # The next cycle for the same consignee starts back at tier one: its single
    # billable day prices at 12550 and not at the 22450 the consignee's running
    # total had already reached.
    reset_cycle = fx.released_cycle(
        api,
        world,
        constructive_at=CYCLE_B_CONSTRUCTIVE_AT,
        sent_at=CYCLE_B_NOTICE_SENT_AT,
        actual_at=CYCLE_B_ACTUAL_AT,
        released_at=RESET_RELEASE_AT,
        facility_id=second_track["id"],
    )
    reset_charge = fx.charge_of_cycle(api, reset_cycle["id"])
    assert_subset_equal(
        reset_charge,
        {
            "status": CHARGE_FINAL,
            "chargeable_days": 1,
            "billable_days": 1,
            "gross_amount_cents": CYCLE_B_GROSS_CENTS,
        },
    )
    assert CYCLE_B_GROSS_CENTS == DEFAULT_TIER1_RATE_RAILROAD
    assert two_day_cycle["customer_id"] == reset_cycle["customer_id"]
    assert two_day_cycle["tariff_rule_set_id"] == reset_cycle["tariff_rule_set_id"]
    # The two spot instants are the reference ones, so the two windows really do
    # differ by the release alone.
    assert fx.get_cycle(api, two_day_cycle["id"])["actual_placement_at"] == (
        CYCLE_A_ACTUAL_AT
    )
    assert fx.get_cycle(api, reset_cycle["id"])["actual_placement_at"] == (
        CYCLE_B_ACTUAL_AT
    )
