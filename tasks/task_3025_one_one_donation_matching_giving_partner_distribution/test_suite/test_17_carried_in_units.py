"""Carried-in units and the successor season's obligation (PRD §3.3, §3.7)."""
from test_helpers import (
    TEST_USERS,
    add_product_line,
    api_client,
    commit_allocation,
    confirm_receipt,
    create_active_product,
    create_approved_partner,
    create_season,
    declare_capacity,
    get_profile,
    get_season,
    register_claim,
    set_clock,
    ship_allocation,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
PLANNER = TEST_USERS["planner_headers"]
FULFILL = TEST_USERS["fulfillment_headers"]
AUDITOR = TEST_USERS["auditor_headers"]

class TestCarriedInUnitsReachTheSuccessorSeason:
    """Corner/calculations — the reversal forecasts the next season's obligation."""

    def _previous_season_reversal(self):
        """A closed earlier season whose received allocation is reversed into the successor."""
        # PRD §2.11 bounds the freeze-bearing writes by the resolved season's
        # calendar, and PRD §3.3 settles a receipt only while its season is not
        # `PLANNED`; a clock inside the earlier season's own window satisfies
        # both for the whole fixture, so it never has to move.
        set_clock("2026-06-01T00:00:00Z")
        prev = create_season(
            season_code="2026-Q2",
            starts_at="2026-06-01T00:00:00Z",
            ends_at="2026-08-31T00:00:00Z",
            freezes_at="2026-07-15T00:00:00Z",
        )
        current = create_season()
        product = create_active_product()
        add_product_line(product["id"], "00000000000630", "M", True)
        partner = create_approved_partner()
        profile = declare_capacity(
            partner["id"], max_allocatable_units=5000, season_code="2026-Q2"
        )
        claim = register_claim(product["id"], partner["id"], stated_donation_units=2000)
        allocation = commit_allocation(
            prev["id"], partner["id"], claim["id"], product["id"],
            allocated_units=1000, priority_tier="CRITICAL",
        )
        distribution = ship_allocation(allocation["id"], 1000, "TRK-CI-1", "UPS")
        confirm_receipt(distribution["id"], 1000, "RCV-CI-1")
        return prev, current, product, partner, profile, claim, allocation

    def test_the_reversal_reserves_units_and_forecasts_the_next_season(self, api):
        """PRD §3.3: "A successful reversal creates a child allocation whose `allocation_kind` is `REVERSAL` carrying the same `allocated_units`, raises the profile's `reserved_units` by that amount, and creates the make-up donation liability for the next impact season with `carried_in_units` equal to those units."
        PRD §3.7: "Carry-forward is the make-up mechanism, and it exists because a published claim can promise more than a season actually froze. It requires that `required_stated_units` is strictly greater than `frozen_units` and that the season named by `carry_from_season_code` is `CLOSED`; when either fails the attempt is refused with `ERR_CARRY_PRECONDITION_UNMET` (HTTP 409). A successful carry-forward sets `carried_out_units` to the excess of the required stated units over the frozen units, hands the successor liability for the next season that many `carried_in_units`, places that successor in `ACCUMULATING` so the inherited units are folded into its own freeze, and recomputes the season's `liability_carry_in_units`."

        Design: Corner/calculations/carried_in_units_enter_the_successor_season_obligation
        """
        prev, current, product, partner, profile, claim, allocation = (
            self._previous_season_reversal()
        )

        validate_success(
            api_client.reverse_allocation(
                allocation["id"],
                {
                    "allocated_units": 1000,
                    "claim_id": claim["id"],
                    "priority_tier": "CRITICAL",
                    "reason": "Capacity re-declared downward for the frozen season",
                },
                PLANNER,
            ),
            200,
        )

        from test_helpers import get_allocation

        assert get_allocation(allocation["id"])["status"] == "REVERSED"

        from test_helpers import get_allocation

        assert get_allocation(allocation["id"])["status"] == "REVERSED"
        # PRD §3.3: "raises the profile's `reserved_units` by that amount".
        assert get_profile(profile["id"])["reserved_units"] == 1000

    def test_the_successor_season_reports_the_carried_in_units(self, api):
        """PRD §3.7: "Carry-forward is the make-up mechanism, and it exists because a published claim can promise more than a season actually froze. It requires that `required_stated_units` is strictly greater than `frozen_units` and that the season named by `carry_from_season_code` is `CLOSED`; when either fails the attempt is refused with `ERR_CARRY_PRECONDITION_UNMET` (HTTP 409). A successful carry-forward sets `carried_out_units` to the excess of the required stated units over the frozen units, hands the successor liability for the next season that many `carried_in_units`, places that successor in `ACCUMULATING` so the inherited units are folded into its own freeze, and recomputes the season's `liability_carry_in_units`."

        Design: Corner/calculations/carried_in_units_enter_the_successor_season_obligation
        """
        prev, current, product, partner, profile, claim, allocation = (
            self._previous_season_reversal()
        )
        validate_success(
            api_client.reverse_allocation(
                allocation["id"],
                {
                    "allocated_units": 1000,
                    "claim_id": claim["id"],
                    "priority_tier": "CRITICAL",
                    "reason": "Capacity re-declared downward for the frozen season",
                },
                PLANNER,
            ),
            200,
        )

        # PRD §3.3: the reversal "creates the make-up donation liability for the
        # next impact season with `carried_in_units` equal to those units", and
        # PRD §3.7 has the season sum it as `liability_carry_in_units`.
        liabilities = validate_success(
            api_client.list_liabilities(AUDITOR, {"donation_product_id": product["id"]}), 200
        )
        carried = [row for row in liabilities if (row.get("carried_in_units") or 0) == 1000]
        assert len(carried) == 1
        successor_season = api_client.list_impact_seasons(AUDITOR, {"season_code": "2026-Q3"})
        season_row = validate_success(successor_season, 200)[0]
        assert season_row["liability_carry_in_units"] == 1000