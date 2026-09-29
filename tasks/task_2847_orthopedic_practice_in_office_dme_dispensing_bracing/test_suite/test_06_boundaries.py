"""Four thresholds checked exactly on the edge and one unit either side: the
money threshold that waives the dispensing fee, the half-open reasonable-useful-
lifetime window, the integer critical floor of a shelf, and the zero-count edge
of a shelf collection that has never carried stock.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    ApiErrors,
    add_product,
    add_shelf,
    assert_clinic_posture,
    assert_error,
    assert_list_meta,
    assert_money_fields,
    assert_shelf,
    assert_unit_ledger_balances,
    build_practice,
    insurance_coordinator_headers,
    inventory_manager_headers,
    read_clinic,
    read_encounter,
    read_shelf,
    read_summary,
    set_clock,
)
from test_helpers import factories as f

COVERED = {"covered": True, "deductible_remaining_cents": 0, "coinsurance_pct": 0.5}


def test_the_dispensing_fee_is_waived_at_exactly_the_threshold_subtotal(api):
    """Five units of a device whose discounted unit price is exactly 10000 cents
    make a subtotal of exactly the waiver threshold, and at the threshold the flat
    fee is not charged at all.

    PRD: "Fourth, the flat dispensing fee of 2500 cents, twenty-five dollars, is
    charged as `dispensing_fee_cents` when `estimated_subtotal_cents` is strictly
    below the waiver threshold of 50000 cents, five hundred dollars, and is 0 when
    the subtotal reaches that threshold or exceeds it — the fee is waived **at** the
    threshold, and the threshold is keyed on the subtotal and never on the total."

    Design: Difficulty/boundary_precision_check/dispensing_fee_waived_exactly_at_fifty_thousand_cent_subtotal
    """
    practice = build_practice(api, with_shelf=False)
    encounter_id = practice.verified_encounter(quantity=5, coverage={"covered": False})

    notice = practice.issue_abn(encounter_id)

    assert_money_fields(
        notice,
        unit_net_price_cents=10000,
        estimated_subtotal_cents=50000,
        dispensing_fee_cents=0,
        estimated_cost_cents=50000,
    )


def test_a_subtotal_one_cent_short_of_the_threshold_still_carries_the_fee(api):
    """A single unit priced one cent below the threshold leaves the subtotal just
    inside the charging range, so the flat fee is added on top.

    PRD: "Fourth, the flat dispensing fee of 2500 cents, twenty-five dollars, is
    charged as `dispensing_fee_cents` when `estimated_subtotal_cents` is strictly
    below the waiver threshold of 50000 cents, five hundred dollars, and is 0 when
    the subtotal reaches that threshold or exceeds it — the fee is waived **at** the
    threshold, and the threshold is keyed on the subtotal and never on the total."

    Design: Difficulty/boundary_precision_check/dispensing_fee_waived_exactly_at_fifty_thousand_cent_subtotal
    """
    practice = build_practice(
        api,
        product={
            "hcpcs_code": "L0631",
            "description": "LSO brace, second off-shelf line",
            "same_or_similar_group": "LSO_BRACE_TWO",
            "cash_price_cents": 49999,
            "allowed_amount_cents": 60000,
        },
        with_shelf=False,
    )
    encounter_id = practice.verified_encounter(coverage={"covered": False})

    notice = practice.issue_abn(encounter_id)

    assert_money_fields(
        notice,
        unit_net_price_cents=49999,
        estimated_subtotal_cents=49999,
        dispensing_fee_cents=2500,
        estimated_cost_cents=52499,
    )


def _splint_delivered_and_a_follow_up(api):
    """A wrist splint with a twelve-month useful lifetime delivered on the first of
    August, and a fresh follow-up encounter for the same patient awaiting coverage."""
    practice = build_practice(
        api,
        clinic={"accreditation_expires_on": "2028-12-31"},
        product_factory=f.wrist_splint_product_payload,
    )
    first_encounter = practice.delivered_encounter(coverage=COVERED)
    delivered = read_encounter(api, first_encounter)
    assert delivered["clinical_status"] == "DELIVERED"
    verifications = validate_success(
        api.list_coverage_verifications(first_encounter, insurance_coordinator_headers()), 200
    )
    assert verifications[0]["same_or_similar_conflict"] is False
    assert verifications[0]["prior_delivered_encounter_id"] is None
    follow_up = practice.attested_encounter()
    return practice, first_encounter, follow_up


def test_eleven_whole_months_after_delivery_is_still_inside_the_lifetime(api):
    """One month short of the device's useful lifetime the window is still occupied,
    so a covered verification is refused and no verification row is written.

    PRD: "A conflict blocks only a *covered* verification: an attempt to record a
    verification with `covered` true while a conflict exists is refused with
    `ERR_SAME_OR_SIMILAR_CONFLICT` and HTTP 409, while a non-covered verification
    records the conflict fields and proceeds."

    Design: Difficulty/boundary_precision_check/same_or_similar_half_open_window_closes_exactly_at_useful_lifetime
    """
    practice, _first, follow_up = _splint_delivered_and_a_follow_up(api)
    set_clock(api, "2027-07-31T00:00:00Z")

    response = api.create_coverage_verification(
        follow_up, f.coverage_verification_payload(**COVERED), insurance_coordinator_headers()
    )

    assert_error(response, ApiErrors.SAME_OR_SIMILAR_CONFLICT, 409)
    assert read_encounter(api, follow_up)["financial_status"] == "UNVERIFIED"
    rows = validate_success(
        api.list_coverage_verifications(follow_up, insurance_coordinator_headers()), 200
    )
    assert rows == []


def test_at_exactly_the_useful_lifetime_the_window_has_closed(api):
    """Exactly twelve whole months after the delivery the half-open window is over:
    the predecessor is still reported, but it no longer conflicts.

    PRD: "The occupation window is **half-open**: `same_or_similar_conflict` is true
    when `months_since_prior_delivery` is strictly less than the product's
    `reasonable_useful_lifetime_months`, and false at exactly that many months or
    more, because at exactly the lifetime the window has closed."

    Design: Difficulty/boundary_precision_check/same_or_similar_half_open_window_closes_exactly_at_useful_lifetime
    """
    practice, first_encounter, follow_up = _splint_delivered_and_a_follow_up(api)
    set_clock(api, "2027-08-01T00:00:00Z")

    verification = practice.verify_coverage(follow_up, **COVERED)

    assert verification["months_since_prior_delivery"] == 12
    assert verification["same_or_similar_conflict"] is False
    assert verification["prior_delivered_encounter_id"] == first_encounter
    assert verification["prior_delivered_on"] == "2026-08-01"
    assert read_encounter(api, follow_up)["financial_status"] == "VERIFIED"


def _unstocked_five_par_shelf(api):
    """A shelf whose par minimum is 5 units, created and not yet stocked, so its
    critical floor is 3 units."""
    practice = build_practice(api, with_shelf=False)
    shelf = add_shelf(practice, practice.product_id, par_min_qty=5, par_max_qty=20)
    assert_shelf(shelf, on_hand_qty=0, available_qty=0, stock_posture="STOCKOUT")
    return practice, shelf


def test_stock_below_the_critical_floor_reads_as_critical(api):
    """Two units on a shelf whose critical floor is three sit strictly below that
    floor, which is the critical posture and not merely below par.

    PRD: "Otherwise, when `on_hand_qty` is strictly below the critical floor, the
    posture is `CRITICAL`."

    Design: Difficulty/boundary_precision_check/par_stock_posture_exact_critical_floor_and_par_min_boundaries
    """
    practice, shelf = _unstocked_five_par_shelf(api)

    received = validate_success(
        api.receive_stock(shelf["id"], f.stock_receipt_payload(2), inventory_manager_headers()), 201
    )

    assert_shelf(
        received, on_hand_qty=2, available_qty=2, stock_posture="CRITICAL", lifetime_received_qty=2
    )
    assert_clinic_posture(
        read_clinic(api, practice.clinic_id), dispensing_status="ACTIVE", stockout_par_level_count=0
    )


def test_the_critical_floor_and_the_par_minimum_are_both_inclusive_upwards(api):
    """Exactly at the critical floor the shelf reads below par rather than critical,
    and exactly at the par minimum it reads healthy rather than below par.

    PRD: "The boundaries are exact and inclusive in the stated direction: an
    `on_hand_qty` exactly equal to the critical floor is `BELOW_PAR` and not
    `CRITICAL`, and an `on_hand_qty` exactly equal to `par_min_qty` is `OK` and not
    `BELOW_PAR`."

    Design: Difficulty/boundary_precision_check/par_stock_posture_exact_critical_floor_and_par_min_boundaries
    """
    practice, shelf = _unstocked_five_par_shelf(api)
    validate_success(
        api.receive_stock(shelf["id"], f.stock_receipt_payload(2), inventory_manager_headers()), 201
    )

    postures = []
    for _ in range(3):
        received = validate_success(
            api.receive_stock(shelf["id"], f.stock_receipt_payload(1), inventory_manager_headers()),
            201,
        )
        postures.append((received["on_hand_qty"], received["stock_posture"]))

    assert postures == [(3, "BELOW_PAR"), (4, "BELOW_PAR"), (5, "OK")]
    assert read_shelf(api, shelf["id"])["lifetime_received_qty"] == 5
    assert_clinic_posture(
        read_clinic(api, practice.clinic_id), dispensing_status="ACTIVE", stockout_par_level_count=0
    )


def _two_never_stocked_shelves(api):
    """Two shelves that exist and have never received a single unit."""
    practice = build_practice(api, with_shelf=False)
    splint = add_product(practice, f.wrist_splint_product_payload(practice.supplier_id))
    first = add_shelf(practice, practice.product_id)
    second = add_shelf(practice, splint["id"])
    return practice, first, second


def test_shelves_that_never_carried_stock_do_not_count_against_the_clinic(api):
    """Both shelves open in a stockout posture, yet neither is counted, because the
    count only looks at shelves that have actually received units.

    PRD: "The input is `stockout_par_level_count`, a **full recount** — not an
    increment — of that clinic's shelves whose `stock_posture` is `STOCKOUT` and
    whose `lifetime_received_qty` is greater than 0."

    Design: Difficulty/boundary_precision_check/never_stocked_shelf_is_stockout_yet_counts_zero_against_clinic
    """
    practice, first, second = _two_never_stocked_shelves(api)

    for shelf in (first, second):
        assert shelf["stock_posture"] == "STOCKOUT"
        assert shelf["lifetime_received_qty"] == 0
    assert_clinic_posture(
        read_clinic(api, practice.clinic_id), dispensing_status="ACTIVE", stockout_par_level_count=0
    )
    rows, _meta = assert_list_meta(
        api.list_par_levels(inventory_manager_headers(), {"clinic_id": practice.clinic_id}),
        expected_total=2,
    )
    assert len(rows) == 2


def test_the_summary_of_a_clinic_that_never_moved_a_unit_is_all_zero(api):
    """With two unstocked shelves and no encounter ever opened, every ledger figure
    the summary reports is zero and the clinic is still active.

    PRD: "`net_cash_position_cents` is `gross_charged_cents` less
    `refunded_cents`."

    Design: Difficulty/boundary_precision_check/never_stocked_shelf_is_stockout_yet_counts_zero_against_clinic
    """
    practice, _first, _second = _two_never_stocked_shelves(api)

    summary = read_summary(api, practice.clinic_id)

    assert summary["clinic_id"] == practice.clinic_id
    assert summary["dispensing_status"] == "ACTIVE"
    assert summary["stockout_par_level_count"] == 0
    assert summary["units_received_total"] == 0
    assert summary["units_on_hand_total"] == 0
    assert summary["units_reserved_total"] == 0
    assert summary["units_dispensed_total"] == 0
    assert summary["units_restocked_total"] == 0
    assert summary["units_destroyed_total"] == 0
    assert summary["units_accounted_total"] == 0
    assert summary["gross_charged_cents"] == 0
    assert summary["refunded_cents"] == 0
    assert summary["restock_fee_retained_cents"] == 0
    assert summary["net_cash_position_cents"] == 0
    assert_unit_ledger_balances(summary)
