"""Multi-line formulas whose rounding points and evaluation order are pinned."""

from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers.test_users import FINANCE_HEADERS, USER_FINANCE


def _producer_with_one_suspension_point(client):
    """A BASIC producer carrying exactly one point from a settled minor damage.

    A minor incident under the 50000-cent escalation threshold is worth one
    point, and one point leaves the producer short of the suspension threshold.
    """
    producer = fx.setup_basic_certified_producer(
        client, score=88, legal_name="Ada Lovelace", email="ada@patv.example"
    )
    resource = fx.create_resource(
        client,
        resource_code="STUDIO-A",
        resource_class="STUDIO_A",
        required_competency_code="STUDIO_FLOOR",
        capacity_slots=1,
        turnaround_minutes=30,
        base_deposit_cents=12345,
        replacement_value_cents=900000,
    )
    _resource, first = fx.setup_confirmed_reservation(
        client,
        producer["id"],
        resource,
        start_at="2026-08-06T10:00:00Z",
        end_at="2026-08-06T12:00:00Z",
    )
    fx.set_clock(client, "2026-08-06T10:00:00Z")
    fx.checkout_reservation(client, first["id"], condition_notes="Tripod head intact at handover")
    fx.set_clock(client, "2026-08-06T11:00:00Z")
    fx.return_damaged(
        client, first["id"], "MINOR", 40000, damage_notes="Scuffed tripod head"
    )
    assessment = fx.list_assessments_for(client, first["id"])[0]
    fx.finalize_assessment(client, assessment["id"])
    return producer, resource, first


def test_deposit_hold_rounds_each_line_before_summing_them(client):
    """The risk line and the duration line are rounded independently.

    PRD 3.6: "The risk line is the asset's `base_deposit_cents` multiplied by
    ten thousand plus `risk_bp`, divided by ten thousand, rounded half up to a
    whole cent — note that this line carries the whole base deposit plus its
    risk loading, not just the loading."

    PRD 3.6: "**Rounding each line separately is normative**: for a base deposit
    of 12345 cents with one suspension point, a three-hour window and a live
    link, the risk line is 14197, the duration line is 1235 and the live line is
    2469, for a hold of 17901 cents — whereas summing the loadings to 14500
    basis points and rounding once would give 17900, a cent adrift."

    PRD 3.6: "Step one computes `risk_bp`, the producer's risk loading in basis
    points: multiply their current `suspension_points` by 1500 basis points per
    point, then take whichever is smaller of that product and the cap of 4500
    basis points"

    Design: Difficulty/combinatorial_formula/deposit_hold_per_line_rounding_beats_combined_rate_mode_b
    """
    producer, resource, _first = _producer_with_one_suspension_point(client)
    before = fx.read_producer(client, producer["id"])
    a.assert_producer_counters(before, suspension_points=1)
    assert before["status"] == "ACTIVE"

    second = fx.request_reservation(
        client,
        producer["id"],
        resource["id"],
        start_at="2026-08-07T09:00:00Z",
        end_at="2026-08-07T12:00:00Z",
    )
    confirmed = fx.confirm_reservation(client, second["id"])

    assert confirmed["risk_bp"] == 1500
    a.assert_cents(confirmed["deposit_hold_cents"], 15432, "deposit_hold_cents")
    assert confirmed["deposit_hold_cents"] != 15431
    assert confirmed["status"] == "CONFIRMED"

    after = fx.read_producer(client, producer["id"])
    a.assert_producer_counters(after, held=15432)
    assert fx.read_resource(client, resource["id"])["open_reservation_count"] == 1


def test_finalized_minor_damage_drains_the_hold_and_leaves_uncovered_liability(client):
    """A repair above the hold forfeits all of it and records the shortfall.

    PRD 3.7: "Step four sets `deposit_forfeited_cents` to whichever is smaller
    of `deposit_hold_cents` and those total charges. Step five sets
    `deposit_refunded_cents` to `deposit_hold_cents` less
    `deposit_forfeited_cents`. Step six sets `uncovered_liability_cents` to the
    total charges less `deposit_hold_cents`, floored at 0."

    PRD 3.6: "A clean comparison case, with no suspension points, a two-hour
    window and no live link, gives the base 12345 plus a duration line of 617,
    for a hold of 12962 cents."

    Design: Difficulty/combinatorial_formula/deposit_hold_per_line_rounding_beats_combined_rate_mode_b
    """
    _producer, _resource, first = _producer_with_one_suspension_point(client)

    settled = fx.read_reservation(client, first["id"])

    assert settled["status"] == "SETTLED"
    a.assert_cents(settled["deposit_hold_cents"], 12962, "deposit_hold_cents")
    a.assert_cents(settled["assessed_repair_cents"], 40000, "assessed_repair_cents")
    a.assert_cents(settled["deposit_forfeited_cents"], 12962, "deposit_forfeited_cents")
    a.assert_cents(settled["deposit_refunded_cents"], 0, "deposit_refunded_cents")
    a.assert_cents(settled["uncovered_liability_cents"], 27038, "uncovered_liability_cents")
    a.assert_settlement_identities(settled)


def test_low_tier_reserve_precedes_the_capital_share_on_the_distributable(client):
    """One cent under the tier threshold picks 800bp, and 35 percent is taken after.

    PRD 3.8: "Step four splits what remains: the distributable amount is
    `allocable_base_cents` less `admin_reserve_cents`; the capital share is that
    distributable amount multiplied by 3500 basis points, divided by ten
    thousand, rounded half up; `capital_allocation_cents` is that capital share
    plus `capital_grant_cents`; and `operating_allocation_cents` is the
    distributable amount less the capital share, taken as an exact residual so
    that no cent is created or lost."

    PRD 3.8: "Step two chooses the administrative reserve rate from a two-row
    tier table: the rate is 500 basis points — 5 percent — when
    `allocable_base_cents` is at or above 5000000 cents, and 800 basis points —
    8 percent — below that threshold."

    Design: Difficulty/combinatorial_formula/franchise_pinned_evaluation_order_low_tier_mode_c
    """
    period = fx.open_funding_period(
        client,
        fiscal_year=2026,
        quarter=4,
        basis="ACCRUAL",
        gross_franchise_fee_cents=5100000,
        service_period_earned_cents=4999999,
        remittance_received_cents=4700000,
        capital_grant_cents=0,
    )

    submitted = a.data_of(client.submit_funding_report(period["id"], {}, FINANCE_HEADERS))

    a.assert_cents(submitted["allocable_base_cents"], 4999999, "allocable_base_cents")
    a.assert_cents(submitted["admin_reserve_cents"], 400000, "admin_reserve_cents")
    a.assert_cents(submitted["capital_allocation_cents"], 1610000, "capital_allocation_cents")
    assert submitted["capital_allocation_cents"] != 1750000
    a.assert_cents(submitted["operating_allocation_cents"], 2989999, "operating_allocation_cents")
    a.assert_cents(submitted["total_program_funds_cents"], 4999999, "total_program_funds_cents")
    a.assert_allocation_identity(submitted)


def test_report_submission_records_the_acting_finance_officer(client):
    """Submission stamps the acting operator identity onto the period.

    PRD 3.8: "Submission recomputes `allocable_base_cents`,
    `admin_reserve_cents`, `capital_allocation_cents`,
    `operating_allocation_cents` and `total_program_funds_cents` in the pinned
    order above, records `submitted_by_user_id` as the acting `X-User-ID`, and
    increments the period's `version` by 1."

    Design: Difficulty/combinatorial_formula/franchise_pinned_evaluation_order_low_tier_mode_c
    """
    period = fx.open_funding_period(
        client,
        fiscal_year=2026,
        quarter=4,
        basis="ACCRUAL",
        gross_franchise_fee_cents=5100000,
        service_period_earned_cents=4999999,
        remittance_received_cents=4700000,
        capital_grant_cents=0,
    )

    submitted = a.data_of(client.submit_funding_report(period["id"], {}, FINANCE_HEADERS))

    assert submitted["report_status"] == "SUBMITTED"
    assert submitted["submitted_by_user_id"] == USER_FINANCE
    a.assert_common_fields(submitted, expected_version=period["version"] + 1)
