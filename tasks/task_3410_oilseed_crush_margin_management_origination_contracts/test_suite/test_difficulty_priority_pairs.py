"""Difficulty queue — priority_pair_validation_conflict: when one request
violates two rules, PRD §2.9's fixed order picks the winner. Pair one: state
(priority 6) beats shape/quantity (priority 9). Pair two: temporal
(priority 7) beats fiscal (priority 12).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_crush_run,
    create_and_apply_ticket,
    create_crush_plant,
    create_crush_run,
    create_deferred_contract,
    create_pricing_election_payload,
    elect_price,
    post_bean_quote,
    post_crush_quote_set,
    read_contract,
    read_crush_run,
    schedule_crush_run_payload,
    settle_contract,
    setup_origination_site,
    validate_error,
)

MERCH = TEST_USERS["origination_merchandiser_headers"]
SCHEDULER = TEST_USERS["plant_scheduler_headers"]


class TestStateBeatsConstraintOnSettledContractElection:
    """A DEFERRED 100-bu contract fully delivered, fully priced, and SETTLED;
    a further 10-bu election violates both the pricing-state gate and the
    quantity constraint (100 + 10 > 100)."""

    def _setup_settled(self):
        site = setup_origination_site()
        post_bean_quote("2026-12", 1100, "2026-09-01T00:00:00Z")
        contract = create_deferred_contract(
            site["farmer"]["id"], site["elevator"]["id"],
            quantity_bushels=100, futures_month="2026-12",
            pricing_deadline="2026-12-15T00:00:00Z",
            storage_rate_cents_per_bushel_day=0,
        )
        create_and_apply_ticket(contract["id"], gross_bushels=100)
        elect_price(contract["id"], 100)
        settle_contract(contract["id"])
        return read_contract(contract["id"])

    def test_pricability_state_error_wins_over_quantity(self, api):
        """PRD §2.9: "the system reports exactly one error — the one belonging to the earliest applicable rule in the following fixed order", with
        state preconditions at rule 6 and shape/quantity rules at rule 9.
        PRD §3.4: "a `CASH` contract, or one already `PRICED`, rejects with `ERR_CONTRACT_NOT_PRICABLE`."
        The settled contract's election must fail 409
        ERR_CONTRACT_NOT_PRICABLE, never ERR_PRICING_EXCEEDS_QUANTITY.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_constraint_on_settled_contract_election
        """
        settled = self._setup_settled()
        resp = api_client.create_pricing_election(
            settled["id"],
            create_pricing_election_payload(10, settled["version"]),
            MERCH,
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_PRICABLE)

    def test_rejected_election_leaves_contract_untouched(self, api):
        """PRD §3.4: "When fulfillment has reached `DELIVERED` and pricing has reached `PRICED` — and only then — an `OriginationMerchandiser` may settle". A contract that has already settled must not be mutated by a
        rejected election: it stays SETTLED with priced_bushels 100 and the
        single original election in its log.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_constraint_on_settled_contract_election
        """
        settled = self._setup_settled()
        resp = api_client.create_pricing_election(
            settled["id"],
            create_pricing_election_payload(10, settled["version"]),
            MERCH,
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_PRICABLE)
        after = read_contract(settled["id"])
        assert after["fulfillment_status"] == "SETTLED"
        assert float(after["priced_bushels"]) == pytest.approx(100)
        assert len(after["elections"]) == 1
        assert after["version"] == settled["version"]


class TestTemporalBeatsFiscalOnPastDatedNegativeMarginSchedule:
    """Quotes 1500/55/17 price a spread of 605 + 799 - 1500 = -96.00, so a
    100-bu run carries planned_margin_cents -9600; its run_date 2026-08-01 is
    also before the 2026-09-01 clock. Scheduling violates both rule 7 and
    rule 12."""

    def _setup_run(self):
        plant = create_crush_plant()
        post_crush_quote_set("2026-11", bean=1500, oil=55, meal=17,
                             quote_date="2026-09-01T00:00:00Z")
        return create_crush_run(
            plant["id"], run_date="2026-08-01T00:00:00Z",
            planned_bushels=100, futures_month="2026-11",
        )

    def test_temporal_error_wins_over_fiscal(self, api):
        """PRD §3.6: "the `run_date` must not be before the current clock date (`ERR_RUN_DATE_IN_PAST`)" and "finally the fiscal check, always last: `planned_margin_cents` must not be negative (`ERR_NEGATIVE_CRUSH_MARGIN`)."
        The schedule attempt must fail 422 ERR_RUN_DATE_IN_PAST, never
        ERR_NEGATIVE_CRUSH_MARGIN.

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_past_dated_negative_margin_schedule
        """
        run = self._setup_run()
        resp = api_client.schedule_crush_run(
            run["id"], schedule_crush_run_payload(run["version"]), SCHEDULER
        )
        validate_error(resp, ApiErrorId.ERR_RUN_DATE_IN_PAST)

    def test_run_stays_planned_with_negative_margin_on_record(self, api):
        """PRD §3.6: "planned_margin_cents` is that spread multiplied by `planned_bushels`, rounded half up to whole cents. The run is born `PLANNED". The rejected schedule mutates nothing: the run remains
        PLANNED carrying the -9600-cent margin that the temporal rule beat.

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_past_dated_negative_margin_schedule
        """
        run = self._setup_run()
        assert run["planned_margin_cents"] == -9600
        resp = api_client.schedule_crush_run(
            run["id"], schedule_crush_run_payload(run["version"]), SCHEDULER
        )
        validate_error(resp, ApiErrorId.ERR_RUN_DATE_IN_PAST)
        after = read_crush_run(run["id"])
        assert_crush_run(after)
        assert after["status"] == "PLANNED"
        assert after["planned_margin_cents"] == -9600
