"""The compensating actions conserve the quantities they reverse."""
from test_helpers import (
    api_client, validate_success, get_success_data,
    COMPLIANCE,
    setup_license_with_postings,
    setup_migration_credit_fixture,
    post_score,
)


class TestFeeLedgerConservation:

    def _one_settled_posting(self):
        fixture = setup_license_with_postings(num_postings=1, entitled_count=500)
        return fixture

    def test_the_settlement_brackets_the_fee_balance(self, api):
        """PRD §2.9: "For a licence, let `B` be the licence's `cumulative_fee_cents`
        immediately before a posting settled, `P` the same quantity immediately
        after that posting settled, and λ the licence's `cumulative_fee_cents`
        immediately after the void."

        Design: Difficulty/compensating_invariant/invariant_fee_ledger_conserved_across_void
        """
        fixture = self._one_settled_posting()
        license_id = fixture["license"]["id"]
        rows = get_success_data(
            api_client.list_fee_ledger_entries(COMPLIANCE,
                                               params={"license_id": license_id}), 200)
        marginal = [r for r in rows if r["kind"] == "MARGINAL_PRICING"]
        assert len(marginal) == 1
        assert marginal[0]["cumulative_count_before"] == 0
        assert marginal[0]["fee_cents"] == 18

    def test_the_void_cancels_the_settled_charge_exactly(self, api):
        """PRD §2.9: "The invariant requires that the product of λ and the
        difference between `P` and `B` is zero for every licence — in other words a
        void must cancel the settled charge exactly, irrespective of which tier
        arithmetic produced it."

        Design: Difficulty/compensating_invariant/invariant_fee_ledger_conserved_across_void
        """
        fixture = self._one_settled_posting()
        license_id = fixture["license"]["id"]
        posting = fixture["results"][0]
        before = get_success_data(api_client.get_license(license_id, COMPLIANCE), 200)
        b_value = before["cumulative_fee_cents"] - 18
        p_value = before["cumulative_fee_cents"]
        validate_success(
            api_client.void_score_result(posting["id"], before["version"], COMPLIANCE), 200)
        after = get_success_data(api_client.get_license(license_id, COMPLIANCE), 200)
        lam = after["cumulative_fee_cents"]
        assert lam * (p_value - b_value) == 0
        assert lam == 0

    def test_the_void_restores_the_count_and_the_ledger_pair(self, api):
        """PRD §3.8: "A `ComplianceOfficer` may later void the posting, which
        appends a `VOID_REVERSAL` entry whose `fee_cents` is the negation of that
        posting's marginal charge, decrements the licence's `cumulative_score_count`,
        recomputes `cumulative_fee_cents` from the ledger"
        PRD §3.7: "A void restores exactly the same formula evaluated at the
        posting's captured `cumulative_count_before`, so the reversal cancels the
        charge precisely."

        Design: Difficulty/compensating_invariant/invariant_fee_ledger_conserved_across_void
        """
        fixture = self._one_settled_posting()
        license_id = fixture["license"]["id"]
        posting = fixture["results"][0]
        before = get_success_data(api_client.get_license(license_id, COMPLIANCE), 200)
        api_client.void_score_result(posting["id"], before["version"], COMPLIANCE)
        after = get_success_data(api_client.get_license(license_id, COMPLIANCE), 200)
        assert after["cumulative_score_count"] == 0
        rows = get_success_data(
            api_client.list_fee_ledger_entries(COMPLIANCE,
                                               params={"license_id": license_id}), 200)
        reversals = [r for r in rows if r["kind"] == "VOID_REVERSAL"]
        assert len(reversals) == 1
        assert reversals[0]["fee_cents"] == -18

    def test_voiding_an_already_voided_posting_is_refused(self, api):
        """PRD §3.3: "While the study is still unfinalized — that is, while
        `finalized_by` is null — a `ValidationAnalyst` may revert it"
        PRD §2.12: "the target must occupy the state named by the transition's
        originating clause and the transition must be declared on that entity"

        A voided posting is no longer in a state from which the void transition is
        declared, so the second attempt is refused and the ledger stays balanced.

        Design: Difficulty/compensating_invariant/invariant_fee_ledger_conserved_across_void
        """
        fixture = self._one_settled_posting()
        license_id = fixture["license"]["id"]
        posting = fixture["results"][0]
        current = get_success_data(api_client.get_license(license_id, COMPLIANCE), 200)
        api_client.void_score_result(posting["id"], current["version"], COMPLIANCE)
        current = get_success_data(api_client.get_license(license_id, COMPLIANCE), 200)
        res = api_client.void_score_result(posting["id"], current["version"], COMPLIANCE)
        assert res.status_code == 409
        after = get_success_data(api_client.get_license(license_id, COMPLIANCE), 200)
        assert after["cumulative_fee_cents"] == 0


class TestMigrationCreditConservation:

    def test_the_credited_delta_is_the_anchor_difference(self, api):
        """PRD §3.9: "The `credited_delta_bps` carried by the event is derived as
        the target variant's `ref_score` minus the source variant's `ref_score`"

        Design: Difficulty/compensating_invariant/invariant_migration_credit_conserved_across_void
        """
        fixture = setup_migration_credit_fixture()
        assert fixture["event"]["credited_delta_bps"] == -20

    def test_consuming_the_anchor_credits_the_licence_window(self, api):
        """PRD §3.8: "Consuming an event adds its `credited_delta_bps` to the
        licence's `window_credited_delta_bps` and refreshes
        `window_outcome_mixture_ratio_ppm`."

        Design: Difficulty/compensating_invariant/invariant_migration_credit_conserved_across_void
        """
        fixture = setup_migration_credit_fixture()
        license_id = fixture["license"]["id"]
        before = get_success_data(api_client.get_license(license_id, COMPLIANCE), 200)
        assert before["window_credited_delta_bps"] == 0
        post_score(license_id, fixture["consumer"]["id"], fixture["v2"]["id"],
                   fixture["bureau"]["id"], 715,
                   migration_event_id=fixture["event"]["id"])
        after = get_success_data(api_client.get_license(license_id, COMPLIANCE), 200)
        assert after["window_credited_delta_bps"] == -20

    def test_voiding_the_anchor_subtracts_exactly_its_credit(self, api):
        """PRD §3.9: "Voiding an event stamps `voided_at` and subtracts exactly that
        event's `credited_delta_bps` from the consuming licence, which restores the
        pre-event ratio whenever the anchor's posting is itself voided or untouched."

        Design: Difficulty/compensating_invariant/invariant_migration_credit_conserved_across_void
        """
        fixture = setup_migration_credit_fixture()
        license_id = fixture["license"]["id"]
        post_score(license_id, fixture["consumer"]["id"], fixture["v2"]["id"],
                   fixture["bureau"]["id"], 715,
                   migration_event_id=fixture["event"]["id"])
        api_client.void_migration_event(fixture["event"]["id"], COMPLIANCE)
        after = get_success_data(api_client.get_license(license_id, COMPLIANCE), 200)
        assert after["window_credited_delta_bps"] == 0

    def test_the_void_restores_the_pre_anchor_window_ratio(self, api):
        """PRD §2.9: "The second invariant is tolerant and governs migration-anchor
        re-consumption: it compares the window ratio observed before an anchor was
        consumed with the ratio observed after the void, and collapses to zero only
        when the re-consumed anchor restores the window ratio exactly."

        Design: Difficulty/compensating_invariant/invariant_migration_credit_conserved_across_void
        """
        fixture = setup_migration_credit_fixture()
        license_id = fixture["license"]["id"]
        posting = post_score(license_id, fixture["consumer"]["id"], fixture["v2"]["id"],
                             fixture["bureau"]["id"], 715,
                             migration_event_id=fixture["event"]["id"])
        credited = get_success_data(
            api_client.get_license(license_id, COMPLIANCE), 200)
        assert credited["window_credited_delta_bps"] == -20
        api_client.void_migration_event(fixture["event"]["id"], COMPLIANCE)
        after = get_success_data(api_client.get_license(license_id, COMPLIANCE), 200)
        # PRD §3.9: voiding the event "subtracts exactly that event's
        # credited_delta_bps from the consuming licence"; the posting itself is
        # untouched, so its contribution to the window ratio is unchanged.
        assert after["window_credited_delta_bps"] == 0
        assert after["cumulative_score_count"] == 1
        stored = get_success_data(
            api_client.get_score_result(posting["id"], COMPLIANCE), 200)
        assert stored["effective_score"] == posting["effective_score"]