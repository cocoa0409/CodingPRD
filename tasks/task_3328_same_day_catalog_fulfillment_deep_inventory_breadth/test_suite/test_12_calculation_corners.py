"""Calculation corners: the restock waterfall walked in delivered-subtotal rank order."""

from test_helpers import (
    DCM,
    account_headers,
    create_return_payload,
    list_lines,
    return_line_payload,
    setup_order_scenario,
    validate_success,
)


class TestRestockCapAllocationWalksTheLinesInRankOrder:
    """The restock ratio decays from 0.80 by 0.30 down the authorized lines."""

    def _approved_return(self, api):
        scenario = setup_order_scenario(
            api,
            lines_spec=[
                {"price": 3000, "qty": 2, "bundle": 8, "on_hand": 10, "sku": "RC-1001"},
                {"price": 9000, "qty": 2, "bundle": 8, "on_hand": 10, "sku": "RC-1002"},
            ],
            target="SHIPPED",
            utc="2026-09-14T10:05:00Z",
        )
        lines = list_lines(api, scenario["acct"], scenario["order"])
        ret = validate_success(api.create_return(
            create_return_payload(
                scenario["order"]["id"],
                [return_line_payload(line["id"], 2) for line in lines]),
            account_headers(scenario["acct"])), 201)
        approved = validate_success(api.approve_return(ret["id"], DCM))
        return scenario, lines, approved

    def test_the_restock_and_damage_shares_follow_the_ratio_waterfall(self, api):
        """PRD §3.9: "The lines are processed in order of the delivered
        `line_subtotal_cents` descending, ties broken by the line's `created_at` ascending.
        For each line in that order, the restock units are the authorized return units
        multiplied by a ratio that starts at 0.80 and is floored to a whole unit, and the
        damaged units are the remainder. After each line, the ratio drops by 0.30, never
        going below 0".
        PRD §3.9: "Approval sets `return_status` `APPROVED` and splits the return into a
        restock share and a damage share".

        Design: Corner/calculations/restock_cap_allocation_walks_the_lines_in_rank_order
        """
        scenario, lines, approved = self._approved_return(api)

        assert approved["return_status"] == "APPROVED"
        assert approved["restock_units"] == 2
        assert approved["damaged_units"] == 2