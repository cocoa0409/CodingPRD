"""Money figures the ranch computes twice from the same contract data.

Two domains are exercised: the booking's package charge, priced once at the hold
and again at departure, and the seasonal retention bonus, published as a
projected accrual and settled against a vesting cliff.
"""
from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import assertions, constants
from test_helpers.factories import (
    check_out_payload,
    onboard_payload,
    party_member,
    payment_payload,
)
from test_helpers.fixtures import (
    build_booking,
    build_cabin,
    build_guest,
    build_in_season,
    build_season,
    build_staff_member,
    check_in,
    confirm_booking,
    set_clock_to,
)
from test_helpers.test_users import RANCH_MANAGER, RESERVATIONS_AGENT

ARRIVAL = "2026-10-11"
DEPARTURE = "2026-10-18"
DEPOSIT_CENTS = 377607
EARLY_SETTLEMENT_CENTS = 683290


def _confirmed_family_party(client):
    """One in-season stay: two adults and a child on a 7-night CLASSIC package."""
    season = build_in_season(
        client,
        package_tiers=[dict(constants.TIER_CLASSIC), dict(constants.TIER_SIGNATURE)],
    )
    cabin = build_cabin(client, name="Aspen", bed_capacity=4)
    ann = build_guest(client, "Ann Adult", "1985-04-02", 165)
    ben = build_guest(client, "Ben Adult", "1983-07-11", 190)
    cal = build_guest(client, "Cal Child", "2016-05-20", 95)
    members = [
        party_member(ann["id"], "ADULT"),
        party_member(ben["id"], "ADULT"),
        party_member(cal["id"], "CHILD"),
    ]
    booking = build_booking(
        client,
        season["id"],
        cabin["id"],
        members,
        package_tier_code="CLASSIC",
        arrival_date=ARRIVAL,
        departure_date=DEPARTURE,
    )
    get_success_data(
        client.post_payment(
            booking["id"], payment_payload(DEPOSIT_CENTS, "DEPOSIT"), RESERVATIONS_AGENT
        )
    )
    booking = confirm_booking(client, booking["id"])
    return season, cabin, booking


def _depart_early(client, booking_id):
    """Arrive on the contracted day, leave after five of the seven nights."""
    set_clock_to(client, "2026-10-11T16:00:00Z")
    check_in(client, booking_id)
    set_clock_to(client, "2026-10-16T14:00:00Z")
    return validate_success(
        client.check_out_booking(
            booking_id, check_out_payload(EARLY_SETTLEMENT_CENTS), RESERVATIONS_AGENT
        )
    )


class TestPackageChargePricedTwice:
    """The hold price and the departure price are different numbers."""

    def test_early_departure_reprices_the_stay_on_realized_nights(self, client):
        """A stay abandoned after five of seven nights is re-priced on five.

        PRD: "That figure is used exactly as measured, with **no** floor at the
        season's `min_stay_nights`, so a party that leaves early genuinely
        re-bands the length-of-stay discount"

        Design: Difficulty/dual_variant_calc/package_total_provisional_at_hold_vs_final_at_early_checkout
        """
        _season, _cabin, booking = _confirmed_family_party(client)
        assert booking["provisional_package_total_cents"] == 1258691
        assert booking["deposit_required_cents"] == DEPOSIT_CENTS

        departed = _depart_early(client, booking["id"])
        assertions.assert_booking(departed)
        assert departed["realized_nights"] == 5
        assert departed["realized_subtotal_cents"] == 899065
        assert departed["provisional_package_total_cents"] == 1258691
        assert (
            departed["provisional_package_total_cents"]
            - departed["realized_subtotal_cents"]
            == 359626
        )

    def test_departure_settles_the_folio_from_the_realized_subtotal(self, client):
        """Gratuity and the folio total follow the re-priced subtotal, not the hold.

        PRD: "The result is written to `realized_subtotal_cents`, which will
        normally differ from `provisional_package_total_cents`."

        Design: Difficulty/dual_variant_calc/package_total_provisional_at_hold_vs_final_at_early_checkout
        """
        _season, _cabin, booking = _confirmed_family_party(client)
        departed = _depart_early(client, booking["id"])

        assert departed["gratuity_cents"] == 161832
        assert departed["final_folio_total_cents"] == 1060897
        assert departed["folio_balance_cents"] == 0
        assert departed["booking_status"] == "CHECKED_OUT"
        assert departed["payment_status"] == "PAID_IN_FULL"
        assertions.assert_folio_waterfall_consistent(departed)
        assertions.assert_folio_balance_consistent(departed)


RETENTION_BONUS_CENTS = 120000
HIRED_ON = "2026-08-15"
CONTRACT_END_DATE = "2026-11-15"


def _guide_45_days_into_a_92_day_contract(client):
    """A seasonal guide onboarded on day one and read on contract day 45."""
    season = build_season(client, retention_bonus_cents=RETENTION_BONUS_CENTS)
    staff = build_staff_member(
        client,
        season["id"],
        full_name="Gus Guide",
        role_type="GUIDE",
        certifications=["EQUINE_HANDLER", "WILDERNESS_FIRST_AID"],
        hired_on=HIRED_ON,
        contract_end_date=CONTRACT_END_DATE,
    )
    set_clock_to(client, "2026-08-15T09:00:00Z")
    get_success_data(
        client.onboard_staff_member(
            staff["id"], onboard_payload("BUNKHOUSE-A", 3), RANCH_MANAGER
        )
    )
    set_clock_to(client, "2026-09-29T10:00:00Z")
    staff = validate_success(client.get_staff_member(staff["id"], RANCH_MANAGER))
    return season, staff


class TestRetentionBonusPricedTwice:
    """The projected accrual and the settled payout are different numbers."""

    def test_projected_bonus_accrues_pro_rata_with_no_cliff_applied(self, client):
        """Forty-five days of a ninety-two day contract project a part payment.

        PRD: "The **projected** variant, recomputed on every read of a `HIRED`
        or `ACTIVE` staff member and published as
        `retention_bonus_projected_cents`, is simply that pro-rated figure with
        no cliff applied, so it reports a positive accrual from the first day
        worked."

        Design: Difficulty/dual_variant_calc/retention_bonus_projected_vs_settled_below_vesting_cliff
        """
        _season, staff = _guide_45_days_into_a_92_day_contract(client)
        assertions.assert_staff_member(staff)
        assert staff["employment_status"] == "ACTIVE"
        assert staff["contract_days"] == 92
        assert staff["days_worked"] == 45
        assert staff["retention_bonus_projected_cents"] == 58696

    def test_settled_bonus_collapses_to_zero_below_the_half_contract_cliff(self, client):
        """Leaving under half way through settles the retention bonus at nothing.

        PRD: "otherwise, when twice `days_worked` is less than `contract_days`
        — that is, when the person worked less than half their contract — the
        payout collapses to 0"

        Design: Difficulty/dual_variant_calc/retention_bonus_projected_vs_settled_below_vesting_cliff
        """
        season, staff = _guide_45_days_into_a_92_day_contract(client)
        projected_before = staff["retention_bonus_projected_cents"]
        assert projected_before == 58696

        separated = validate_success(
            client.separate_staff_member(staff["id"], "family emergency", RANCH_MANAGER)
        )
        assert separated["employment_status"] == "DEPARTED_EARLY"
        assert separated["contract_days"] == 92
        assert separated["days_worked"] == 45
        assert separated["separated_on"] == "2026-09-29"
        assert separated["retention_bonus_settled_cents"] == 0

        season_after = validate_success(client.get_season(season["id"], RANCH_MANAGER))
        assert season_after["retention_bonus_liability_cents"] == 0
