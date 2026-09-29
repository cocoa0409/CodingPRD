"""Facility-side gates: the bond, the guard ratio, the zone and the posture.

Every refusal here is produced with the neighbouring rules on the same endpoint
deliberately satisfied, and each one is followed by the repair that makes the
identical request succeed.
"""

from test_helpers import (
    AccessStatus,
    ApiErrorId,
    BondPaymentPlan,
    BondStatus,
    CertType,
    CertificationStatus,
    FacilityPosture,
    FindingSeverity,
    GuardShiftStatus,
    ReservationStatus,
    SeasonStatus,
    ShiftRole,
    Zone,
    assertions as a,
    canonical_instant,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    guest_visit_payload,
    household_payment_payload,
    party_reservation_payload,
    transition_payload,
)
from test_helpers.test_users import POOL_MANAGER, TREASURER

FACILITY_CLOCK = "2027-07-01T09:00:00Z"
PARTY_START = "2027-07-15T14:00:00Z"
PARTY_END = "2027-07-15T18:00:00Z"


def _a_household_billed_for_its_bond_but_not_paid_up(api):
    """A SENIOR membership on INSTALLMENTS: the bond is billed and unpaid.

    The invoice carries a 30000-cent bond installment line while the household's
    own ``bond_paid_cents`` is still 0, so the two figures disagree.
    """
    fx.set_clock(api, FACILITY_CLOCK)
    category = fx.create_senior_category(api)
    season = fx.setup_open_season(api)
    household = fx.create_household(
        api, primary_contact_name="Bond Gate Household",
        address_line="201 Cedar Court", member_count=4, prior_member=False,
    )
    membership = fx.setup_membership(
        api, household["id"], category["id"], season["id"],
        join_date="2027-07-01",
        bond_payment_plan=BondPaymentPlan.INSTALLMENTS,
    )
    invoiced = fx.invoice_membership(api, membership["id"])
    return {"category": category, "season": season, "household": household,
            "membership": invoiced, "fresh_household": household}


def _attempt_party(api, membership_id, zone=Zone.PAVILION,
                   start_iso=PARTY_START, end_iso=PARTY_END,
                   guest_count=12, host_party_size=14):
    return api.create_party_reservation(
        party_reservation_payload(
            membership_id=membership_id, zone=zone, start_iso=start_iso,
            end_iso=end_iso, guest_count=guest_count,
            host_party_size=host_party_size,
        ),
        POOL_MANAGER,
    )


def _reservations(api, params=None):
    rows, _ = validate_paginated(api.list_party_reservations(POOL_MANAGER,
                                                            params))
    return rows


class TestAPartyReservationNeedsASettledBond:
    """The bond gate reads the household's ledger, not the invoice line."""

    def test_billing_the_installment_is_not_paying_it(self, api):
        """One quarter of the bond is charged and nothing is credited.

        PRD §3.4: "a plan of `INSTALLMENTS` bills one quarter of `bond_cents`,
        rounded half up to a whole cent"

        PRD §3.2: "A household is born in `GOOD_STANDING` with `conduct_points`
        at 0, with `bond_status` `NONE` and `bond_paid_cents` at 0"

        Design: Corner/validations/violation_to_error_a_party_reservation_needs_a_settled_bond
        """
        ctx = _a_household_billed_for_its_bond_but_not_paid_up(api)

        assert ctx["fresh_household"]["bond_status"] == BondStatus.NONE
        assert ctx["fresh_household"]["bond_paid_cents"] == 0
        assert ctx["membership"]["bond_installment_cents"] == 30000
        assert ctx["membership"]["access_status"] == AccessStatus.ACTIVE
        assert ctx["season"]["facility_posture"] == FacilityPosture.OPEN

        household = fx.read_household(api, ctx["household"]["id"])
        assert household["bond_status"] == BondStatus.INSTALLMENTS
        assert household["bond_paid_cents"] == 0

    def test_the_party_is_refused_while_the_bond_is_unsettled(self, api):
        """A billed installment satisfies neither arm of the bond test.

        PRD §3.7: "its bond must be settled — `bond_status` of `PAID` or
        `TRANSFERRED`, or `bond_paid_cents` having reached the category's
        `bond_cents` — before it may reserve the facility at all, with an
        unsettled bond reported as `ERR_BOND_NOT_PAID`"

        Design: Corner/validations/violation_to_error_a_party_reservation_needs_a_settled_bond
        """
        ctx = _a_household_billed_for_its_bond_but_not_paid_up(api)

        validate_error(_attempt_party(api, ctx["membership"]["id"]),
                       ApiErrorId.BOND_NOT_PAID, 402)
        assert _reservations(api) == []
        assert fx.read_household(
            api, ctx["household"]["id"]
        )["party_charges_owed_cents"] == 0

    def test_the_bond_arm_of_the_payment_ceiling_is_the_remaining_bond(self, api):
        """The ceiling is the bond still owed, not the amount already billed.

        PRD §3.2: "for `BOND` it is the category's `bond_cents` less the
        household's `bond_paid_cents` already credited. Exceeding any of those is
        rejected with `ERR_PAYMENT_EXCEEDS_BALANCE`."

        Design: Corner/validations/violation_to_error_a_party_reservation_needs_a_settled_bond
        """
        ctx = _a_household_billed_for_its_bond_but_not_paid_up(api)

        validate_error(
            api.create_household_payment(
                ctx["household"]["id"],
                household_payment_payload(amount_cents=130000,
                                          allocation="BOND"),
                TREASURER,
            ),
            ApiErrorId.PAYMENT_EXCEEDS_BALANCE, 422,
        )

        household = fx.read_household(api, ctx["household"]["id"])
        assert household["bond_paid_cents"] == 0
        assert household["bond_status"] == BondStatus.INSTALLMENTS

    def test_the_exact_bond_payment_opens_the_facility(self, api):
        """Settling the bond turns the same refused request into a booking.

        PRD §3.2: "`BOND` raises `bond_paid_cents` and moves `bond_status` from
        `NONE` or `INSTALLMENTS` to `PAID` once `bond_paid_cents` has reached the
        `bond_cents` of the category of this household's membership"

        Design: Corner/validations/violation_to_error_a_party_reservation_needs_a_settled_bond
        """
        ctx = _a_household_billed_for_its_bond_but_not_paid_up(api)
        validate_error(_attempt_party(api, ctx["membership"]["id"]),
                       ApiErrorId.BOND_NOT_PAID, 402)

        household = fx.pay_household(api, ctx["household"]["id"], 120000,
                                     "BOND")
        assert household["bond_paid_cents"] == 120000
        assert household["bond_status"] == BondStatus.PAID

        reservation = validate_success(
            _attempt_party(api, ctx["membership"]["id"]), 201
        )
        assert reservation["status"] == ReservationStatus.REQUESTED
        a.assert_party_pricing(
            reservation, projected_bather_load=26, required_guard_count=2,
            duration_hours_ceil=4, lifeguard_surcharge_cents=17600,
            base_facility_fee_cents=6000, guest_overage_fee_cents=1400,
            subtotal_cents=25000, member_discount_cents=2500,
            total_charge_cents=22500,
        )


def _a_priced_party_with_nobody_on_the_deck(api):
    """A REQUESTED party needing one guard in a season with no shifts at all."""
    fx.set_clock(api, FACILITY_CLOCK)
    category = fx.create_couple_category(api)
    season = fx.setup_open_season(api)
    household = fx.create_household(
        api, primary_contact_name="Uncovered Party Household",
        address_line="211 Cedar Court", member_count=2, prior_member=False,
    )
    membership = fx.setup_membership(api, household["id"], category["id"],
                                    season["id"], join_date="2027-07-01")
    membership = fx.invoice_membership(api, membership["id"])
    reservation = fx.request_party(api, membership["id"], guest_count=12,
                                   host_party_size=8)
    return {"season": season, "household": household, "membership": membership,
            "reservation": reservation}


def _window_at(api, season_id, at_iso):
    return validate_success(
        api.get_staffing_window(season_id, POOL_MANAGER, {"at_iso": at_iso}),
        200,
    )


def _attempt_confirm_party(api, reservation_id):
    return api.transition_party_reservation(
        reservation_id, transition_payload(ReservationStatus.CONFIRMED),
        POOL_MANAGER,
    )


class TestConfirmingAPartyWithoutGuardCoverage:
    """The ratio is enforced on confirm, so an uncovered party may still exist."""

    def test_the_reservation_is_priced_for_a_guard_that_does_not_exist(self, api):
        """Pricing runs at creation while the deck is empty.

        PRD §3.7: "`required_guard_count` is derived from that load: divide the
        load by the twenty-five bathers each guard may cover and round up to the
        next whole number, take the larger of that figure and the standing minimum
        of one guard whenever the facility is open"

        Design: Corner/validations/violation_to_error_confirming_a_party_without_guard_coverage
        """
        ctx = _a_priced_party_with_nobody_on_the_deck(api)

        reservation = ctx["reservation"]
        assert reservation["status"] == ReservationStatus.REQUESTED
        a.assert_party_pricing(
            reservation, projected_bather_load=20, required_guard_count=1,
            duration_hours_ceil=4, lifeguard_surcharge_cents=8800,
            base_facility_fee_cents=6000, guest_overage_fee_cents=1400,
            subtotal_cents=16200, member_discount_cents=0,
            total_charge_cents=16200,
        )

        shifts, _ = validate_paginated(
            api.list_guard_shifts(POOL_MANAGER,
                                  {"season_id": ctx["season"]["id"]})
        )
        assert shifts == []

    def test_the_staffing_window_reports_the_deck_uncovered(self, api):
        """The requested reservation loads the window it cannot staff.

        PRD §3.8: "The load is the sum of `guest_count` plus `host_party_size`
        over the season's reservations in `REQUESTED` or `CONFIRMED` whose window
        contains the instant"

        Design: Corner/validations/violation_to_error_confirming_a_party_without_guard_coverage
        """
        ctx = _a_priced_party_with_nobody_on_the_deck(api)

        window = _window_at(api, ctx["season"]["id"], PARTY_START)
        a.assert_staffing_window(window, bather_load=20,
                                 required_guard_count=1,
                                 scheduled_guard_count=0, compliant=False)

    def test_confirming_is_refused_and_the_reservation_stays_requested(self, api):
        """A declared edge whose only failure is its staffing precondition.

        PRD §3.7: "Confirming — `REQUESTED → CONFIRMED` — is permitted only while
        the season's `facility_posture` is `OPEN`, and only when the staffing ratio
        of §3.8 reports the deck compliant at two probes: at the reservation's
        `start_iso`, and at one minute before its `end_iso`. A failure at either
        probe is `ERR_GUARD_RATIO_NOT_MET`."

        Design: Corner/validations/violation_to_error_confirming_a_party_without_guard_coverage
        """
        ctx = _a_priced_party_with_nobody_on_the_deck(api)

        body = validate_error(
            _attempt_confirm_party(api, ctx["reservation"]["id"]),
            ApiErrorId.GUARD_RATIO_NOT_MET, 422,
        )
        assert body["error_id"] != ApiErrorId.INVALID_TRANSITION
        assert fx.read_reservation(
            api, ctx["reservation"]["id"]
        )["status"] == ReservationStatus.REQUESTED

    def test_a_refused_confirmation_is_not_a_refund_event(self, api):
        """The charge booked at request survives the refusal untouched.

        PRD §3.7: "A new reservation is born `REQUESTED` with `refunded_cents` at
        0, and its `total_charge_cents` is booked onto the household immediately:
        `party_charges_owed_cents` rises by that amount"

        Design: Corner/validations/violation_to_error_confirming_a_party_without_guard_coverage
        """
        ctx = _a_priced_party_with_nobody_on_the_deck(api)
        validate_error(
            _attempt_confirm_party(api, ctx["reservation"]["id"]),
            ApiErrorId.GUARD_RATIO_NOT_MET, 422,
        )

        assert fx.read_household(
            api, ctx["household"]["id"]
        )["party_charges_owed_cents"] == 16200
        assert fx.read_reservation(
            api, ctx["reservation"]["id"]
        )["refunded_cents"] == 0


SHIFT_START = "2027-07-15T13:00:00Z"
SHIFT_END = "2027-07-15T19:00:00Z"
SECOND_PROBE = "2027-07-15T17:59:00Z"


def _a_priced_party_and_a_fully_certified_guard(api):
    """The positive twin: the same uncovered party plus one certifiable guard."""
    fx.set_clock(api, FACILITY_CLOCK)
    category = fx.create_couple_category(api)
    season = fx.setup_open_season(api)
    household = fx.create_household(
        api, primary_contact_name="Covered Party Household",
        address_line="221 Cedar Court", member_count=2, prior_member=False,
    )
    membership = fx.setup_membership(api, household["id"], category["id"],
                                    season["id"], join_date="2027-07-01")
    membership = fx.invoice_membership(api, membership["id"])
    reservation = fx.request_party(api, membership["id"], guest_count=12,
                                   host_party_size=8)
    fresh_guard = fx.create_lifeguard(api, full_name="Dana Okonjo",
                                      hire_date="2026-05-01")
    lifeguard_cert = fx.certify(api, fresh_guard["id"], CertType.LIFEGUARD,
                                issued_on="2026-06-01",
                                expires_on="2028-05-31")
    cpr_cert = fx.certify(api, fresh_guard["id"], CertType.CPR_AED,
                          issued_on="2026-06-01", expires_on="2028-05-31")
    return {"season": season, "household": household, "membership": membership,
            "reservation": reservation, "fresh_guard": fresh_guard,
            "lifeguard_id": fresh_guard["id"], "lifeguard_cert": lifeguard_cert,
            "cpr_cert": cpr_cert}


class TestAConfirmedPrimaryShiftAdmitsThePartyConfirmation:
    """Coverage counts only in one exact shape: CONFIRMED, ratio-bearing, closed."""

    def test_a_fresh_guard_carries_no_certification_flags(self, api):
        """Both flags are recomputed from the certifications that exist.

        PRD §3.8: "Both certification flags are recomputed after every such write
        — `has_valid_lifeguard_cert` is true when at least one of the guard's
        certifications has `cert_type` `LIFEGUARD` and `status` `VALID`, and
        `has_valid_cpr_cert` is the same test for `CPR_AED`"

        Design: Corner/validations/satisfaction_to_pass_a_confirmed_primary_shift_admits_the_confirmation
        """
        ctx = _a_priced_party_and_a_fully_certified_guard(api)

        assert ctx["fresh_guard"]["has_valid_lifeguard_cert"] is False
        assert ctx["fresh_guard"]["has_valid_cpr_cert"] is False
        assert ctx["lifeguard_cert"]["status"] == CertificationStatus.VALID
        assert ctx["cpr_cert"]["status"] == CertificationStatus.VALID
        assert ctx["lifeguard_cert"]["expires_on"] == "2028-05-31"
        assert ctx["cpr_cert"]["expires_on"] == "2028-05-31"

        guard = fx.read_lifeguard(api, ctx["lifeguard_id"])
        assert guard["has_valid_lifeguard_cert"] is True
        assert guard["has_valid_cpr_cert"] is True

    def test_a_scheduled_shift_does_not_cover_the_deck(self, api):
        """The shift exists, carries the ratio flag, and still counts for nothing.

        PRD §3.8: "Coverage counts the distinct `lifeguard_id` values over the
        season's shifts that are in `CONFIRMED`, that have `counts_toward_ratio`
        true, and whose interval contains the instant"

        Design: Corner/validations/satisfaction_to_pass_a_confirmed_primary_shift_admits_the_confirmation
        """
        ctx = _a_priced_party_and_a_fully_certified_guard(api)

        shift = fx.schedule_shift(api, ctx["lifeguard_id"], ctx["season"]["id"],
                                  SHIFT_START, SHIFT_END,
                                  shift_role=ShiftRole.PRIMARY)
        assert shift["status"] == GuardShiftStatus.SCHEDULED
        assert shift["counts_toward_ratio"] is True
        assert shift["duration_hours"] == 6

        window = _window_at(api, ctx["season"]["id"], PARTY_START)
        a.assert_staffing_window(window, bather_load=20,
                                 required_guard_count=1,
                                 scheduled_guard_count=0, compliant=False)

    def test_confirming_the_shift_covers_both_probe_instants(self, api):
        """One confirmed shift satisfies the ratio at 14:00 and at 17:59.

        PRD §3.8: "The verdict is compliant when the covering guard count is
        greater than or equal to the required count; exactly meeting the
        requirement is compliant."

        Design: Corner/validations/satisfaction_to_pass_a_confirmed_primary_shift_admits_the_confirmation
        """
        ctx = _a_priced_party_and_a_fully_certified_guard(api)
        shift = fx.schedule_shift(api, ctx["lifeguard_id"], ctx["season"]["id"],
                                  SHIFT_START, SHIFT_END,
                                  shift_role=ShiftRole.PRIMARY)

        confirmed = fx.transition_shift(api, shift["id"],
                                        GuardShiftStatus.CONFIRMED)
        assert confirmed["status"] == GuardShiftStatus.CONFIRMED

        for probe in (PARTY_START, SECOND_PROBE):
            window = _window_at(api, ctx["season"]["id"], probe)
            a.assert_staffing_window(window, bather_load=20,
                                     required_guard_count=1,
                                     scheduled_guard_count=1, compliant=True)

    def test_the_party_confirmation_is_then_admitted(self, api):
        """Coverage exactly equal to the requirement is enough.

        PRD §3.7: "Confirmation moves no money, because the charge was booked when
        the party was requested."

        Design: Corner/validations/satisfaction_to_pass_a_confirmed_primary_shift_admits_the_confirmation
        """
        ctx = _a_priced_party_and_a_fully_certified_guard(api)
        shift = fx.schedule_shift(api, ctx["lifeguard_id"], ctx["season"]["id"],
                                  SHIFT_START, SHIFT_END,
                                  shift_role=ShiftRole.PRIMARY)
        fx.transition_shift(api, shift["id"], GuardShiftStatus.CONFIRMED)

        reservation = validate_success(
            _attempt_confirm_party(api, ctx["reservation"]["id"]), 200
        )
        assert reservation["status"] == ReservationStatus.CONFIRMED
        assert reservation["required_guard_count"] == 1
        assert reservation["refunded_cents"] == 0
        assert fx.read_household(
            api, ctx["household"]["id"]
        )["party_charges_owed_cents"] == 16200


ZONE_CAPACITY = 40
A_START, A_END = "2027-07-15T14:00:00Z", "2027-07-15T18:00:00Z"
B_OVERLAP_START, B_OVERLAP_END = "2027-07-15T16:00:00Z", "2027-07-15T20:00:00Z"
B_ADJACENT_START, B_ADJACENT_END = "2027-07-15T18:00:00Z", "2027-07-15T20:00:00Z"
C_START, C_END = "2027-07-15T15:00:00Z", "2027-07-15T17:00:00Z"


def _three_households_in_a_forty_bather_season(api):
    """Three bookable households under a deliberately tight capacity of 40."""
    fx.set_clock(api, FACILITY_CLOCK)
    category = fx.create_couple_category(api)
    season = fx.setup_open_season(api, bather_load_capacity=ZONE_CAPACITY)
    memberships = {}
    for label, address in (("A", "231 Cedar Court"), ("B", "232 Cedar Court"),
                           ("C", "233 Cedar Court")):
        household = fx.create_household(
            api, primary_contact_name="Zone Household " + label,
            address_line=address, member_count=2, prior_member=False,
        )
        membership = fx.setup_membership(api, household["id"], category["id"],
                                        season["id"], join_date="2027-07-01")
        memberships[label] = fx.invoice_membership(api, membership["id"])
    return {"season": season, "category": category, "memberships": memberships}


class TestZoneConflictAndAggregateBatherCapacity:
    """Two rules read the same overlapping set: one by zone, one by headcount."""

    def test_the_first_pavilion_party_takes_half_the_capacity(self, api):
        """The season's ceiling and the first booking's load are both 40 and 20.

        PRD §3.1: "`bather_load_capacity`, the hard aggregate ceiling on bathers
        anywhere in the facility at any instant, which defaults to 120 and must be
        at least 1"

        PRD §3.7: "`projected_bather_load` is the reservation's `guest_count` plus
        its `host_party_size`"

        Design: Corner/validations/violation_to_error_zone_conflict_and_aggregate_bather_capacity
        """
        ctx = _three_households_in_a_forty_bather_season(api)
        assert ctx["season"]["bather_load_capacity"] == ZONE_CAPACITY

        first = validate_success(
            _attempt_party(api, ctx["memberships"]["A"]["id"],
                           zone=Zone.PAVILION, start_iso=A_START,
                           end_iso=A_END, guest_count=12, host_party_size=8),
            201,
        )
        assert first["projected_bather_load"] == 20
        assert first["status"] == ReservationStatus.REQUESTED

    def test_an_overlapping_pavilion_window_is_double_booked(self, api):
        """Overlap refuses, adjacency does not.

        PRD §3.7: "No other reservation in `REQUESTED` or `CONFIRMED` may hold a
        conflicting zone over an overlapping half-open window: a `WHOLE_FACILITY`
        booking conflicts with every zone including itself, while `PAVILION` and
        `SHALLOW_END` conflict only with themselves, and a conflict is
        `ERR_ZONE_DOUBLE_BOOKED`."

        PRD §3.7: "Reservation windows are treated as half-open intervals that
        include the start instant and exclude the end instant, so two parties that
        merely abut — where one ends at the exact instant the next begins — do not
        overlap."

        Design: Corner/validations/violation_to_error_zone_conflict_and_aggregate_bather_capacity
        """
        ctx = _three_households_in_a_forty_bather_season(api)
        validate_success(
            _attempt_party(api, ctx["memberships"]["A"]["id"],
                           zone=Zone.PAVILION, start_iso=A_START,
                           end_iso=A_END, guest_count=12, host_party_size=8),
            201,
        )

        validate_error(
            _attempt_party(api, ctx["memberships"]["B"]["id"],
                           zone=Zone.PAVILION, start_iso=B_OVERLAP_START,
                           end_iso=B_OVERLAP_END, guest_count=12,
                           host_party_size=8),
            ApiErrorId.ZONE_DOUBLE_BOOKED, 409,
        )

        abutting = validate_success(
            _attempt_party(api, ctx["memberships"]["B"]["id"],
                           zone=Zone.PAVILION, start_iso=B_ADJACENT_START,
                           end_iso=B_ADJACENT_END, guest_count=12,
                           host_party_size=8),
            201,
        )
        assert abutting["status"] == ReservationStatus.REQUESTED

    def test_a_shallow_end_booking_clears_the_zone_test_and_fails_capacity(self, api):
        """Different zones never conflict, but their loads still sum.

        PRD §3.7: "The aggregate bather load of every `REQUESTED` and `CONFIRMED`
        reservation overlapping the requested half-open window, plus this
        reservation's own load, must not exceed the season's
        `bather_load_capacity`, or the request is
        `ERR_BATHER_CAPACITY_EXCEEDED`."

        Design: Corner/validations/violation_to_error_zone_conflict_and_aggregate_bather_capacity
        """
        ctx = _three_households_in_a_forty_bather_season(api)
        validate_success(
            _attempt_party(api, ctx["memberships"]["A"]["id"],
                           zone=Zone.PAVILION, start_iso=A_START,
                           end_iso=A_END, guest_count=12, host_party_size=8),
            201,
        )

        body = validate_error(
            _attempt_party(api, ctx["memberships"]["C"]["id"],
                           zone=Zone.SHALLOW_END, start_iso=C_START,
                           end_iso=C_END, guest_count=12, host_party_size=14),
            ApiErrorId.BATHER_CAPACITY_EXCEEDED, 409,
        )
        assert body["error_id"] != ApiErrorId.ZONE_DOUBLE_BOOKED

    def test_the_capacity_comparison_is_inclusive_at_forty(self, api):
        """A load reaching the ceiling exactly is admitted, and nothing else is.

        PRD §3.7: "Reservations are listed and filtered by `membership_id`,
        `zone` and `status`."

        Design: Corner/validations/violation_to_error_zone_conflict_and_aggregate_bather_capacity
        """
        ctx = _three_households_in_a_forty_bather_season(api)
        validate_success(
            _attempt_party(api, ctx["memberships"]["A"]["id"],
                           zone=Zone.PAVILION, start_iso=A_START,
                           end_iso=A_END, guest_count=12, host_party_size=8),
            201,
        )
        validate_error(
            _attempt_party(api, ctx["memberships"]["B"]["id"],
                           zone=Zone.PAVILION, start_iso=B_OVERLAP_START,
                           end_iso=B_OVERLAP_END, guest_count=12,
                           host_party_size=8),
            ApiErrorId.ZONE_DOUBLE_BOOKED, 409,
        )
        validate_success(
            _attempt_party(api, ctx["memberships"]["B"]["id"],
                           zone=Zone.PAVILION, start_iso=B_ADJACENT_START,
                           end_iso=B_ADJACENT_END, guest_count=12,
                           host_party_size=8),
            201,
        )
        validate_error(
            _attempt_party(api, ctx["memberships"]["C"]["id"],
                           zone=Zone.SHALLOW_END, start_iso=C_START,
                           end_iso=C_END, guest_count=12, host_party_size=14),
            ApiErrorId.BATHER_CAPACITY_EXCEEDED, 409,
        )

        squeezed = validate_success(
            _attempt_party(api, ctx["memberships"]["C"]["id"],
                           zone=Zone.SHALLOW_END, start_iso=C_START,
                           end_iso=C_END, guest_count=12, host_party_size=8),
            201,
        )
        assert squeezed["projected_bather_load"] == 20
        assert squeezed["status"] == ReservationStatus.REQUESTED

        requested = _reservations(api, {"status": ReservationStatus.REQUESTED})
        assert len(requested) == 3


POSTURE_VISIT = "2027-06-25T14:00:00Z"
POSTURE_PARTY_B_START = "2027-07-16T14:00:00Z"
POSTURE_PARTY_B_END = "2027-07-16T18:00:00Z"


def _a_season_restricted_by_two_major_findings(api):
    """Two open MAJOR findings, two solvent households and nothing else wrong."""
    fx.set_clock(api, FACILITY_CLOCK)
    category = fx.create_couple_category(api)
    season = fx.setup_open_season(api)
    households = {}
    memberships = {}
    for label, address in (("A", "241 Cedar Court"), ("B", "242 Cedar Court")):
        household = fx.create_household(
            api, primary_contact_name="Posture Household " + label,
            address_line=address, member_count=2, prior_member=False,
        )
        membership = fx.setup_membership(api, household["id"], category["id"],
                                        season["id"], join_date="2027-06-01")
        households[label] = household
        memberships[label] = fx.invoice_membership(api, membership["id"])

    fx.file_finding(api, season["id"], FindingSeverity.MAJOR,
                    inspected_on="2027-06-28", finding_code="CHEM-04",
                    narrative="Free chlorine below the required minimum.")
    fx.file_finding(api, season["id"], FindingSeverity.MAJOR,
                    inspected_on="2027-06-28", finding_code="FENCE-07",
                    narrative="Self-latching gate fails to latch.")
    return {"season": season, "category": category, "households": households,
            "memberships": memberships}


def _attempt_visit(api, ctx, label, guest_count, sponsor_name):
    household_id = ctx["households"][label]["id"]
    version = fx.read_household(api, household_id)["version"]
    return api.create_guest_visit(
        guest_visit_payload(
            membership_id=ctx["memberships"][label]["id"],
            expected_household_version=version, sponsor_name=sponsor_name,
            guest_count=guest_count, visit_start_iso=POSTURE_VISIT,
        ),
        POOL_MANAGER,
    )


class TestRestrictedThenClosedPostureNarrowsTheFacility:
    """RESTRICTED is an envelope; CLOSED is a shutdown; MINOR is neither."""

    def test_two_open_major_findings_restrict_the_facility(self, api):
        """The threshold is inclusive and no critical finding is needed.

        PRD §3.1: "otherwise, if two or more major findings are open, the posture
        is `RESTRICTED`; otherwise the posture is `OPEN`. Two major findings
        restrict the facility — the threshold is inclusive."

        Design: Corner/validations/violation_to_error_restricted_then_closed_posture_narrows_the_facility
        """
        ctx = _a_season_restricted_by_two_major_findings(api)

        season = fx.read_season(api, ctx["season"]["id"])
        assert season["facility_posture"] == FacilityPosture.RESTRICTED
        assert season["open_major_finding_count"] == 2
        assert season["open_critical_finding_count"] == 0
        assert season["closure_started_at"] is None
        assert season["status"] == SeasonStatus.OPEN

    def test_the_restricted_envelope_caps_a_visit_at_two_guests(self, api):
        """Three guests are refused for the posture, two are admitted.

        PRD §3.1: "While the posture is `RESTRICTED`, a guest visit may bring at
        most 2 guests and a party reservation may not book the `WHOLE_FACILITY`
        zone. A request that breaks the restricted envelope is rejected with
        `ERR_FACILITY_RESTRICTED`"

        Design: Corner/validations/violation_to_error_restricted_then_closed_posture_narrows_the_facility
        """
        ctx = _a_season_restricted_by_two_major_findings(api)

        body = validate_error(
            _attempt_visit(api, ctx, "A", 3, "Three Guests Under Restriction"),
            ApiErrorId.FACILITY_RESTRICTED, 409,
        )
        assert body["error_id"] != ApiErrorId.GUEST_LIMIT_EXCEEDED

        visit = validate_success(
            _attempt_visit(api, ctx, "A", 2, "Two Guests Under Restriction"),
            201,
        )
        assert visit["passes_used"] == 2
        assert visit["fee_charged_cents"] == 0
        assert visit["is_weekend"] is False

    def test_the_restricted_envelope_objects_only_to_the_whole_facility(self, api):
        """Zone, not size, is what a restricted posture forbids.

        PRD §3.7: "The season must be `OPEN`; the facility posture must not be
        `CLOSED`; a `RESTRICTED` posture forbids the `WHOLE_FACILITY` zone
        specifically."

        Design: Corner/validations/violation_to_error_restricted_then_closed_posture_narrows_the_facility
        """
        ctx = _a_season_restricted_by_two_major_findings(api)

        validate_error(
            _attempt_party(api, ctx["memberships"]["A"]["id"],
                           zone=Zone.WHOLE_FACILITY, start_iso=PARTY_START,
                           end_iso=PARTY_END, guest_count=12,
                           host_party_size=8),
            ApiErrorId.FACILITY_RESTRICTED, 409,
        )

        reservation = validate_success(
            _attempt_party(api, ctx["memberships"]["A"]["id"],
                           zone=Zone.PAVILION, start_iso=PARTY_START,
                           end_iso=PARTY_END, guest_count=12,
                           host_party_size=8),
            201,
        )
        assert reservation["status"] == ReservationStatus.REQUESTED
        assert reservation["zone"] == Zone.PAVILION

    def test_one_critical_finding_closes_both_doors(self, api):
        """A single critical finding outranks any count of majors.

        PRD §3.1: "otherwise, if at least one critical finding is open, the
        posture is `CLOSED`"

        PRD §3.1: "A `CLOSED` posture is stricter and blocks four operations with
        `ERR_FACILITY_CLOSED`: recording a guest visit, requesting a party
        reservation, confirming a requested reservation, and hosting a meet."

        Design: Corner/validations/violation_to_error_restricted_then_closed_posture_narrows_the_facility
        """
        ctx = _a_season_restricted_by_two_major_findings(api)
        fx.file_finding(
            api, ctx["season"]["id"], FindingSeverity.CRITICAL,
            inspected_on="2027-06-30", finding_code="FECAL-01",
            narrative="Confirmed fecal contamination event; pool must be closed "
                      "and shocked.",
        )

        season = fx.read_season(api, ctx["season"]["id"])
        assert season["facility_posture"] == FacilityPosture.CLOSED
        assert season["open_critical_finding_count"] == 1
        assert season["open_major_finding_count"] == 2
        assert canonical_instant(season["closure_started_at"]) == \
            canonical_instant(FACILITY_CLOCK)
        assert season["status"] == SeasonStatus.OPEN

        validate_error(
            _attempt_visit(api, ctx, "B", 1, "One Guest Under Closure"),
            ApiErrorId.FACILITY_CLOSED, 409,
        )
        validate_error(
            _attempt_party(api, ctx["memberships"]["B"]["id"],
                           zone=Zone.PAVILION, start_iso=POSTURE_PARTY_B_START,
                           end_iso=POSTURE_PARTY_B_END, guest_count=12,
                           host_party_size=8),
            ApiErrorId.FACILITY_CLOSED, 409,
        )

        household_b = fx.read_household(api, ctx["households"]["B"]["id"])
        assert household_b["guest_fee_owed_cents"] == 0
        assert household_b["party_charges_owed_cents"] == 0
