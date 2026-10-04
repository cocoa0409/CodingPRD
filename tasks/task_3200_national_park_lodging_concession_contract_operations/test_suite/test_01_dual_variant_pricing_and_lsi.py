"""Two valid pricing algorithms, one physical stay (PRD 3.3).

Under BANDED the reservation prices at the declared band's rate; under
ACTUAL_HEADCOUNT it prices from the supplied bed count.  The same FAMILY room
occupied by two guests quotes the FAMILY rate under BANDED but the DOUBLE
rate under ACTUAL_HEADCOUNT.
"""

from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers.assertions import (
    assert_cents,
    get_success_data,
    validate_success,
)
from test_helpers.fixtures import (
    book_reservation,
    bookable_inventory,
    contract_version,
)
from test_helpers.test_users import FRONT_DESK


class TestOccupancyModeDivergence:
    """One stay, two quotes: the variant names the pricing rule."""

    def _two_reservations_for_identical_stay(self, client):
        scenario = bookable_inventory(client)
        contract_id = scenario["contract"]["id"]
        season_id = scenario["season"]["id"]
        room_class_id = scenario["room_class"]["id"]

        banded = book_reservation(
            client,
            contract_id,
            season_id,
            room_class_id,
            scenario["version"],
            guest_ref="guest-banded",
            check_in_date="2027-07-10T00:00:00Z",
            check_out_date="2027-07-13T00:00:00Z",
            occupancy_band=C.BAND_FAMILY,
        )
        actual = book_reservation(
            client,
            contract_id,
            season_id,
            room_class_id,
            contract_version(client, contract_id, headers=FRONT_DESK),
            guest_ref="guest-actual",
            check_in_date="2027-07-10T00:00:00Z",
            check_out_date="2027-07-13T00:00:00Z",
            occupancy_band=C.BAND_FAMILY,
            occupancy_mode=C.MODE_ACTUAL_HEADCOUNT,
            beds_occupied=2,
        )
        return contract_id, banded, actual

    def test_identical_stay_prices_at_family_under_banded_and_double_under_headcount(
        self, client
    ):
        """PRD 3.3: "The two variants deliberately price identical inputs
        differently — a family-band reservation actually occupied by two
        guests quotes the family rate under `BANDED` but the double rate
        under `ACTUAL_HEADCOUNT`."

        Design: Difficulty/dual_variant_calc/occupancy_rate_banded_vs_actual_headcount_divergence
        """
        _contract_id, banded, actual = self._two_reservations_for_identical_stay(client)

        assert_cents(
            banded["quoted_nightly_rate_cents"], 26000,
            "banded quoted_nightly_rate_cents",
        )
        assert_cents(
            actual["quoted_nightly_rate_cents"], 23000,
            "actual-headcount quoted_nightly_rate_cents",
        )

    def test_money_chain_differs_by_the_variant_alone(self, client):
        """PRD 3.3: "The `total_charge_cents` is the quoted nightly rate
        multiplied by the number of nights. The `deposit_cents` is the total
        charge multiplied by 0.2, rounded half-up to whole cents, but capped
        at 50000 cents."

        Design: Difficulty/dual_variant_calc/occupancy_rate_banded_vs_actual_headcount_divergence
        """
        _contract_id, banded, actual = self._two_reservations_for_identical_stay(client)

        assert_cents(banded["total_charge_cents"], 78000, "banded total_charge_cents")
        assert_cents(banded["deposit_cents"], 15600, "banded deposit_cents")
        assert_cents(actual["total_charge_cents"], 69000, "actual total_charge_cents")
        assert_cents(actual["deposit_cents"], 13800, "actual deposit_cents")
        assert (
            banded["total_charge_cents"] - actual["total_charge_cents"] == 9000
        ), "the two variants must price the identical stay 9000 cents apart"

    def test_omitting_the_mode_stores_banded_and_prices_the_declared_band(
        self, client
    ):
        """PRD 3.3: "Two optional inputs refine pricing: `occupancy_mode`,
        which defaults to `BANDED`..." and "Under the default `BANDED` mode,
        the `quoted_nightly_rate_cents` is simply the approved filing's
        nightly rate for the declared `occupancy_band`."

        Design: Corner/entities/reservation_default_occupancy_mode_is_banded
        """
        scenario = bookable_inventory(client)
        reservation = book_reservation(
            client,
            scenario["contract"]["id"],
            scenario["season"]["id"],
            scenario["room_class"]["id"],
            scenario["version"],
            guest_ref="g-def",
            check_in_date="2027-07-10T00:00:00Z",
            check_out_date="2027-07-12T00:00:00Z",
            occupancy_band=C.BAND_FAMILY,
        )
        assert reservation["occupancy_mode"] == C.MODE_BANDED
        assert_cents(
            reservation["quoted_nightly_rate_cents"], 26000,
            "default-mode quoted_nightly_rate_cents",
        )
        assert reservation["nights"] == 2
        assert_cents(reservation["total_charge_cents"], 52000, "total_charge_cents")
        assert_cents(reservation["deposit_cents"], 10400, "deposit_cents")

    def test_actual_headcount_without_beds_occupied_is_an_invalid_request(
        self, client
    ):
        """PRD 3.3: "beds_occupied, which is required exactly when the mode is
        `ACTUAL_HEADCOUNT` and must then be between 1 and 3."

        Design: Corner/validations/actual_headcount_mode_requires_beds_occupied
        """
        scenario = bookable_inventory(client)
        payload = f.reservation_payload(
            scenario["season"]["id"],
            scenario["room_class"]["id"],
            scenario["version"],
            guest_ref="g-cond",
            occupancy_band=C.BAND_FAMILY,
            occupancy_mode=C.MODE_ACTUAL_HEADCOUNT,
        )
        response = client.create_reservation(
            scenario["contract"]["id"], payload, headers=FRONT_DESK
        )
        from test_helpers.api_errors import ERR_INVALID_REQUEST
        from test_helpers.assertions import validate_error

        validate_error(response, ERR_INVALID_REQUEST)


class TestLeaseholdScheduleDivergence:
    """Same project, same offsets: LINEAR and DECLINING_BALANCE disagree."""

    def _twin_projects(self, client):
        """Two ACTIVE contracts, identical except the LSI schedule type.

        Each carries an AUTHORIZED project of 2000000 cents; at logical clock
        2028-07-01 (month offset 18 on a 2027-01-01 start) each is completed
        with in_service_month_offset 2.
        """
        from test_helpers.fixtures import (
            active_contract,
            authorize_project,
            complete_project,
            create_project,
            reset_clock,
            set_clock,
        )

        reset_clock(client)
        lin, _s1, _l1 = active_contract(
            client, contract_number="GRCA-LIN-1",
            lsi_annual_schedule_type=C.LSI_LINEAR, term_months=24,
        )
        dec, _s2, _l2 = active_contract(
            client, contract_number="GRCA-DEC-1",
            lsi_annual_schedule_type=C.LSI_DECLINING_BALANCE, term_months=24,
        )
        p_lin = create_project(client, lin["id"], authorized_cost_cents=2000000)
        p_dec = create_project(client, dec["id"], authorized_cost_cents=2000000)
        authorize_project(client, lin["id"], p_lin["id"])
        authorize_project(client, dec["id"], p_dec["id"])
        set_clock(client, "2028-07-01T00:00:00Z")
        lin_project = complete_project(
            client, lin["id"], p_lin["id"], 1950000, in_service_month_offset=2
        )
        dec_project = complete_project(
            client, dec["id"], p_dec["id"], 1950000, in_service_month_offset=2
        )
        return lin_project, dec_project

    def test_linear_accrues_straight_line_while_declining_lags(self, client):
        """PRD 3.6: "Under `LINEAR`, the accrual is straight-line: the accrued
        amount at a given offset is the authorized cost multiplied by the
        number of accrued months — the current offset clamped to the term,
        minus the in-service offset, floored at zero — divided by the term in
        months."

        Design: Difficulty/dual_variant_calc/lsi_linear_vs_declining_balance_divergence
        """
        lin_project, _dec = self._twin_projects(client)
        # per-month step = round_half_up(2000000/24) = 83333; accrued months =
        # 18 - 2 = 16, so 83333 * 16 = 1333328.
        assert_cents(lin_project["accrued_lsi_cents"], 1333328,
                     "linear accrued_lsi_cents")

    def test_declining_balance_accrues_by_phase_weights(self, client):
        """PRD 3.6: "Under `DECLINING_BALANCE`, accrual is phase-weighted:
        half of the authorized cost amortizes linearly across the first half
        of the term months, thirty percent across the next forty percent of
        the term, and the remaining twenty percent across the final ten
        percent of the term, with each phase counting only months strictly
        after the in-service offset that fall inside that phase's window."

        Design: Difficulty/dual_variant_calc/lsi_linear_vs_declining_balance_divergence
        """
        lin_project, dec_project = self._twin_projects(client)
        # T=24: phase 1 covers months 1..12 at step round_half_up(1000000/12)
        # = 83333/month, phase 2 covers months 13..22 at 60000/month.
        # Months 3..12 accrue 10*83333 and months 13..18 accrue 6*60000:
        # 833330 + 360000 = 1193330 in total.
        assert_cents(dec_project["accrued_lsi_cents"], 1193330,
                     "declining-balance accrued_lsi_cents")
        assert (
            lin_project["accrued_lsi_cents"] - dec_project["accrued_lsi_cents"]
            == 139998
        ), "identical inputs must diverge by 139998 cents purely from the schedule type"
