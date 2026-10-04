"""Difficulty coverage: compensating invariants — money conservation across
relief repricing, and single-GOVERNING cardinality across AEP supersedes."""

from test_helpers import (
    adjudicate_relief_case,
    assert_money_conservation,
    assert_single_governing_election,
    beneficiary_version,
    create_election,
    enroll,
    list_elections,
    list_invoices,
    read_beneficiary,
    register_beneficiary,
    set_clock,
    setup_relief_case_on_paid_pair,
)


class TestReliefRepricingConservesPaidEqualsAppliedPlusCredit:
    """Forward: two invoices paid at the penalized 20900. Compensation: the
    grant reprices them to 19000. sum(paid) == sum(applied) + credit holds on
    both sides of the cascade."""

    def test_money_conservation_holds_before_and_after_relief_grant(self, client):
        """PRD section 3.1: "The system maintains a conservation invariant
        over the beneficiary's money at all times: the sum of `paid_cents`
        across all of the beneficiary's invoices equals the sum of
        `applied_cents` across those invoices plus the beneficiary's
        `credit_cents`."

        Design: Difficulty/compensating_invariant/relief_repricing_conserves_paid_equals_applied_plus_credit
        """
        state = setup_relief_case_on_paid_pair(client)
        before_beneficiary = read_beneficiary(client, state["beneficiary"]["id"])
        before_invoices = list_invoices(client, state["beneficiary"])
        assert sum(inv["paid_cents"] for inv in before_invoices) == 41800
        assert before_beneficiary["credit_cents"] == 0
        assert_money_conservation(before_beneficiary, before_invoices)

        adjudicate_relief_case(client, state["relief_case"], decision="GRANTED")

        after_beneficiary = read_beneficiary(client, state["beneficiary"]["id"])
        after_invoices = list_invoices(client, state["beneficiary"])
        assert sum(inv["paid_cents"] for inv in after_invoices) == 41800
        assert sum(inv["applied_cents"] for inv in after_invoices) == 38000
        assert after_beneficiary["credit_cents"] == 3800
        assert_money_conservation(after_beneficiary, after_invoices)

    def test_relief_grant_reduces_applied_amounts_and_credits_difference(
        self, client
    ):
        """PRD section 3.9: "invoices already `PAID` keep their `paid_cents`,
        have their `applied_cents` reduced to the corrected amount, and the
        difference between what was paid and what now applies is credited to
        the beneficiary's `credit_cents`."

        Design: Difficulty/compensating_invariant/relief_repricing_conserves_paid_equals_applied_plus_credit
        """
        state = setup_relief_case_on_paid_pair(client)
        adjudicate_relief_case(client, state["relief_case"], decision="GRANTED")

        invoices = list_invoices(client, state["beneficiary"])
        assert len(invoices) == 2
        for invoice in invoices:
            assert invoice["status"] == "PAID"
            assert invoice["paid_cents"] == 20900
            assert invoice["applied_cents"] == 19000

        beneficiary = read_beneficiary(client, state["beneficiary"]["id"])
        assert beneficiary["credit_cents"] == 3800


class TestAepSupersedeConservesSingleGoverningElection:
    """The count of GOVERNING elections in season AEP-2026 is exactly one
    before and after a second filing supersedes the first."""

    def _setup_aep_season(self, client):
        set_clock(client, "2025-01-10T00:00:00Z")
        beneficiary = register_beneficiary(
            client, date_of_birth="1960-01-15", full_name="Elle Ection"
        )
        enroll(client, beneficiary, part="PART_B")
        set_clock(client, "2026-10-20T00:00:00Z")
        return beneficiary

    def test_aep_election_fields_and_version_increment(self, client):
        """PRD section 3.8: "It also computes the `season_key`, which
        identifies the window instance — `AEP-<yyyy>` for the AEP opening in
        year yyyy". PRD section 3.8: "an AEP election takes effect in January
        of the year after the window opens". PRD section 3.8: "A successful
        filing also increments the Beneficiary's `version` by 1".

        Design: Difficulty/compensating_invariant/aep_supersede_conserves_single_governing_election
        """
        beneficiary = self._setup_aep_season(client)
        version_before = beneficiary_version(client, beneficiary["id"])

        election = create_election(client, beneficiary, "AEP", "MA")
        assert election["status"] == "GOVERNING"
        assert election["season_key"] == "AEP-2026"
        assert election["effective_month"] == "2027-01"
        assert election["current_coverage"] == "ORIGINAL"
        assert election["target_coverage"] == "MA"
        assert (
            beneficiary_version(client, beneficiary["id"]) == version_before + 1
        )

    def test_second_aep_election_supersedes_first_keeping_one_governing(
        self, client
    ):
        """PRD section 3.8: "AEP is last-in-wins: creating a second election
        for the same beneficiary in the same season supersedes the previously
        `GOVERNING` one, keeping the count of `GOVERNING` elections per season
        at exactly one."

        Design: Difficulty/compensating_invariant/aep_supersede_conserves_single_governing_election
        """
        beneficiary = self._setup_aep_season(client)
        first = create_election(client, beneficiary, "AEP", "MA")
        assert_single_governing_election(
            list_elections(client, beneficiary), "AEP-2026"
        )
        version_after_first = beneficiary_version(client, beneficiary["id"])

        second = create_election(client, beneficiary, "AEP", "MA")
        elections = list_elections(client, beneficiary)
        assert len(elections) == 2
        assert elections[0]["id"] == first["id"]
        assert elections[0]["status"] == "SUPERSEDED"
        assert elections[1]["id"] == second["id"]
        assert elections[1]["status"] == "GOVERNING"
        assert_single_governing_election(elections, "AEP-2026")
        assert (
            beneficiary_version(client, beneficiary["id"])
            == version_after_first + 1
        )
