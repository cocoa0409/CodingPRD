"""Two assembled figures whose evaluation order is part of the specification.

PRD §2.6: "The **order** in which rounding is applied is part of the
specification."
"""

from test_helpers import (
    AccessStatus,
    BondStatus,
    DuesStatus,
    HouseholdPaymentAllocation,
    ReservationStatus,
    Squad,
    Zone,
    assertions as a,
    fixtures as fx,
    validate_success,
)
from test_helpers.factories import (
    household_payment_payload,
    party_reservation_payload,
    registration_payload,
)
from test_helpers.test_users import POOL_MANAGER, SWIM_TEAM_COACH, TREASURER


def _family_membership_joining_july_fifth(api, member_count=5):
    """A first-time FAMILY household joining 2027-07-05 on INSTALLMENTS.

    The invoice is cut on 2027-07-06, which is later than the season's
    dues_due_date of 2027-04-15, so PRD §3.4's Line 5 penalty fires.
    """
    return fx.setup_club(
        api,
        clock_iso="2027-07-06T09:00:00Z",
        category="FAMILY",
        member_count=member_count,
        household_overrides={
            "primary_contact_name": "Alvarez Household",
            "address_line": "14 Poolside Lane",
            "prior_member": False,
        },
        join_date="2027-07-05",
        bond_payment_plan="INSTALLMENTS",
    )


def _register(api, ctx, name, birthdate, squad):
    payload = registration_payload(
        membership_id=ctx["membership"]["id"], season_id=ctx["season"]["id"],
        swimmer_name=name, swimmer_birthdate=birthdate, squad=squad,
    )
    return validate_success(api.create_registration(payload, SWIM_TEAM_COACH), 201)


def _three_swimmers(api, ctx):
    first = _register(api, ctx, "Mateo Alvarez", "2013-03-04", Squad.SENIOR)
    second = _register(api, ctx, "Nina Alvarez", "2015-06-11", Squad.JUNIOR)
    third = _register(api, ctx, "Oli Alvarez", "2017-09-20", Squad.MINI)
    return first, second, third


class TestInvoiceRoundingOrderAcrossPerSwimmerLines:
    """Three swimmers on one membership, each fee rounded as it is produced."""

    def test_each_swimmer_fee_is_rounded_at_its_own_creation(self, api):
        """The per-swimmer figure is rounded before Line 4 ever sums it.

        PRD §3.6: "`assessed_fee_cents` is the base fee multiplied by one minus
        that capped rate, rounded half up to a whole cent, and it is that
        already-rounded per-swimmer figure that Line 4 of the invoice sums."

        Design: Difficulty/combinatorial_formula/invoice_rounding_order_per_swimmer_lines_mode_b
        """
        ctx = _family_membership_joining_july_fifth(api)
        first, second, third = _three_swimmers(api, ctx)

        assert first["squad_seq"] == 1
        assert first["assessed_fee_cents"] == 14500
        assert second["squad_seq"] == 2
        assert second["assessed_fee_cents"] == 13594
        assert third["squad_seq"] == 3
        assert third["assessed_fee_cents"] == 12688

    def test_the_five_invoice_lines_total_167674_not_the_sum_then_round_answer(
        self, api
    ):
        """Line 4 is 40782, and the invoice total lands one cent above 167673.

        PRD §3.4: "Line 4 is the swim-team fee, written to
        `swim_team_fee_cents`, and it is the sum of the **already-rounded**
        per-swimmer `assessed_fee_cents` figures over the membership's
        registrations whose `status` is `PENDING`, `CONFIRMED` or `COMPLETED`."

        Design: Difficulty/combinatorial_formula/invoice_rounding_order_per_swimmer_lines_mode_b
        """
        ctx = _family_membership_joining_july_fifth(api)
        _three_swimmers(api, ctx)

        invoiced = validate_success(
            api.invoice_membership(ctx["membership"]["id"], TREASURER), 200
        )

        a.assert_invoice_lines(
            invoiced,
            dues=46222,
            initiation=45000,
            bond_installment=30000,
            swim_team_fee=40782,
            late_penalty=5670,
            invoice_total=167674,
        )
        assert invoiced["invoice_total_cents"] != 167673

    def test_the_one_cent_difference_survives_into_the_balance(self, api):
        """The rounding order is observable on the money the household owes.

        PRD §3.4: "Summing the exact unrounded swim-team values and rounding
        once at the end produces a different total, and the difference survives
        all the way into `balance_due_cents` — the pinned order is the
        specification."

        Design: Difficulty/combinatorial_formula/invoice_rounding_order_per_swimmer_lines_mode_b
        """
        ctx = _family_membership_joining_july_fifth(api)
        _three_swimmers(api, ctx)

        invoiced = validate_success(
            api.invoice_membership(ctx["membership"]["id"], TREASURER), 200
        )

        assert invoiced["volunteer_buyout_cents"] == 0
        assert invoiced["balance_due_cents"] == 167674
        assert invoiced["dues_status"] == DuesStatus.INVOICED
        assert invoiced["access_status"] == AccessStatus.ACTIVE


class TestPartyChargeNineStepEvaluationOrder:
    """A four-and-a-half-hour WHOLE_FACILITY booking for 26 guests and 5 hosts."""

    def _party_ready_household(self, api):
        ctx = _family_membership_joining_july_fifth(api)
        fx.invoice_membership(api, ctx["membership"]["id"])
        household = validate_success(
            api.create_household_payment(
                ctx["household"]["id"],
                household_payment_payload(
                    amount_cents=120000,
                    allocation=HouseholdPaymentAllocation.BOND,
                ),
                TREASURER,
            ),
            200,
        )
        assert household["bond_status"] == BondStatus.PAID
        assert household["bond_paid_cents"] == 120000
        ctx["household"] = household
        return ctx

    def _request_whole_facility_party(self, api, ctx):
        payload = party_reservation_payload(
            membership_id=ctx["membership"]["id"],
            zone=Zone.WHOLE_FACILITY,
            start_iso="2027-07-10T14:00:00Z",
            end_iso="2027-07-10T18:30:00Z",
            guest_count=26,
            host_party_size=5,
        )
        return validate_success(
            api.create_party_reservation(payload, POOL_MANAGER), 201
        )

    def test_the_guard_surcharge_is_derived_before_the_discount_tier(self, api):
        """Load 31 needs three guards over five billable hours: 33000 cents.

        PRD §3.7: "`required_guard_count` is derived from that load: divide the
        load by the twenty-five bathers each guard may cover and round up to the
        next whole number, take the larger of that figure and the standing
        minimum of one guard whenever the facility is open, and then add one
        further guard when the reserved `zone` is `WHOLE_FACILITY`, because the
        deep end needs its own eyes."

        Design: Difficulty/combinatorial_formula/party_charge_nine_step_evaluation_order_mode_c
        """
        ctx = self._party_ready_household(api)
        reservation = self._request_whole_facility_party(api, ctx)

        assert reservation["projected_bather_load"] == 31
        assert reservation["required_guard_count"] == 3
        assert reservation["duration_hours_ceil"] == 5
        assert reservation["lifeguard_surcharge_cents"] == 33000

    def test_the_discount_tier_reads_the_subtotal_that_contains_the_surcharge(
        self, api
    ):
        """Subtotal 64200 earns fifteen per cent, so the total is 54570.

        PRD §3.7: "`subtotal_cents` is `base_facility_fee_cents` plus
        `guest_overage_fee_cents` plus `lifeguard_surcharge_cents` — the guard
        surcharge sits **inside** the discount base, and that is the step most
        easily got wrong."

        Design: Difficulty/combinatorial_formula/party_charge_nine_step_evaluation_order_mode_c
        """
        ctx = self._party_ready_household(api)
        reservation = self._request_whole_facility_party(api, ctx)

        a.assert_party_pricing(
            reservation,
            projected_bather_load=31,
            required_guard_count=3,
            duration_hours_ceil=5,
            lifeguard_surcharge_cents=33000,
            base_facility_fee_cents=20000,
            guest_overage_fee_cents=11200,
            subtotal_cents=64200,
            member_discount_cents=9630,
            total_charge_cents=54570,
        )
        assert reservation["total_charge_cents"] != 57780

    def test_the_charge_is_booked_onto_the_household_immediately(self, api):
        """A new reservation is REQUESTED with nothing refunded yet.

        PRD §3.7: "A new reservation is born `REQUESTED` with `refunded_cents`
        at 0, and its `total_charge_cents` is booked onto the household
        immediately: `party_charges_owed_cents` rises by that amount and the
        household's `version` advances."

        Design: Difficulty/combinatorial_formula/party_charge_nine_step_evaluation_order_mode_c
        """
        ctx = self._party_ready_household(api)
        before_version = ctx["household"]["version"]
        reservation = self._request_whole_facility_party(api, ctx)

        assert reservation["status"] == ReservationStatus.REQUESTED
        assert reservation["refunded_cents"] == 0

        household = fx.read_household(api, ctx["household"]["id"])
        assert household["party_charges_owed_cents"] == 54570
        assert household["version"] > before_version
