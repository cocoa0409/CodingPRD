"""Computed reads, filtered listings and the conditional actions behind them."""
from test_helpers import api_client, validate_success, get_success_data, COMPLIANCE, REASON_ADMIN, create_and_activate_license, create_consumer, setup_released_dual_auto, setup_license_with_postings, setup_migration_event_list, setup_reason_code_catalogue_tree, setup_discovery_slot_consumed, register_bureau, post_score, make_score_consumer_headers, create_model_documentation_payload, create_model, author_variant, release_variant


class TestBureauDiscrepancyRead:

    def _three_bureau_capture(self):
        tuc = register_bureau("TUC", "TransUnion")
        exp = register_bureau("EXP", "Experian")
        eqf = register_bureau("EQF", "Equifax")
        # PRD §3.4 computes the cross-bureau spread over "the poster's own
        # consumer's non-voided postings, restricted to the poster's own score
        # model version" -- a different industry variant each, so no two postings
        # are restricted to one variant. A lender may only be licensed once per
        # variant (PRD §3.7), so a distinct lender_code is used per variant.
        bureau, model, variant = setup_released_dual_auto()
        license_ = create_and_activate_license(variant["id"], entitled_count=500)
        consumer = create_consumer(consumer_ref="cons-disc", age_years=49)
        p_tuc = post_score(license_["id"], consumer["id"], variant["id"], tuc["id"], 715)
        p_exp = post_score(license_["id"], consumer["id"], variant["id"], exp["id"], 717)
        p_eqf = post_score(license_["id"], consumer["id"], variant["id"], eqf["id"], 712)
        return license_, consumer, p_tuc, p_exp, p_eqf

    def test_the_read_reports_the_spread_across_peer_postings(self, api):
        """PRD §3.4: "The `peer_spread` reported is the highest peer
        `effective_score` minus the lowest."

        Design: Corner/endpoints/endpoint_bureau_discrepancies_reports_spread_across_bureaus
        """
        license_, consumer, p_tuc, p_exp, p_eqf = self._three_bureau_capture()
        assert p_tuc["effective_score"] == 700
        assert p_exp["effective_score"] == 702
        assert p_eqf["effective_score"] == 697
        data = validate_success(api_client.bureau_discrepancies(p_tuc["id"], COMPLIANCE), 200)
        assert data["peer_spread"] == 5

    def test_no_peer_reaches_the_flagging_threshold(self, api):
        """PRD §3.4: "A peer is flagged when the absolute difference between the
        peer's `effective_score` and the poster's `effective_score` is at least 15
        points."

        Design: Corner/endpoints/endpoint_bureau_discrepancies_reports_spread_across_bureaus
        """
        license_, consumer, p_tuc, p_exp, p_eqf = self._three_bureau_capture()
        data = validate_success(api_client.bureau_discrepancies(p_tuc["id"], COMPLIANCE), 200)
        assert data["flagged_peer_count"] == 0

    def test_the_read_lists_the_two_peer_bureaus(self, api):
        """PRD §3.4: "the response carries the poster's own `poster_effective_score`,
        the `peer_spread`, a `flagged_peer_count`, and the list of `peer_bureau_codes`."

        Design: Corner/endpoints/endpoint_bureau_discrepancies_reports_spread_across_bureaus
        """
        license_, consumer, p_tuc, p_exp, p_eqf = self._three_bureau_capture()
        data = validate_success(api_client.bureau_discrepancies(p_tuc["id"], COMPLIANCE), 200)
        assert len(data["peer_bureau_codes"]) == 2
        assert data["poster_effective_score"] == 700


class TestVoidRestoresLicenceCounters:

    def test_the_void_returns_the_count_and_the_fee_to_the_earlier_state(self, api):
        """PRD §3.8: "A `ComplianceOfficer` may later void the posting, which
        appends a `VOID_REVERSAL` entry whose `fee_cents` is the negation of that
        posting's marginal charge, decrements the licence's `cumulative_score_count`,
        recomputes `cumulative_fee_cents` from the ledger"
        PRD §3.7: "A void restores exactly the same formula evaluated at the
        posting's captured `cumulative_count_before`, so the reversal cancels the
        charge precisely."

        Design: Corner/endpoints/endpoint_score_result_void_restores_the_license_counters
        """
        fixture = setup_license_with_postings(num_postings=2, consumer_ref="cons-void")
        license_id = fixture["license"]["id"]
        first, second = fixture["results"]
        before = get_success_data(api_client.get_license(license_id, COMPLIANCE), 200)
        assert before["cumulative_score_count"] == 2
        assert before["cumulative_fee_cents"] == 36
        validate_success(
            api_client.void_score_result(second["id"], before["version"], COMPLIANCE), 200)
        after = get_success_data(api_client.get_license(license_id, COMPLIANCE), 200)
        assert after["cumulative_score_count"] == 1
        assert after["cumulative_fee_cents"] == 18

    def test_the_reversal_is_priced_from_the_captured_count(self, api):
        """PRD §2.5: "Voiding a posting requires it, because the reversal is priced
        from the posting's captured `cumulative_count_before` and the licence may
        have settled further postings since the client read it."

        Design: Corner/endpoints/endpoint_score_result_void_restores_the_license_counters
        """
        fixture = setup_license_with_postings(num_postings=2, consumer_ref="cons-void")
        license_id = fixture["license"]["id"]
        second = fixture["results"][1]
        before = get_success_data(api_client.get_license(license_id, COMPLIANCE), 200)
        api_client.void_score_result(second["id"], before["version"], COMPLIANCE)
        rows = get_success_data(api_client.list_fee_ledger_entries(
            COMPLIANCE, params={"license_id": license_id}), 200)
        reversals = [r for r in rows if r["kind"] == "VOID_REVERSAL"]
        assert len(reversals) == 1
        assert reversals[0]["fee_cents"] == -18

    def test_the_ledger_holds_two_accruals_and_one_reversal(self, api):
        """PRD §3.8: "A `MARGINAL_PRICING` entry is appended to the fee ledger — its
        `ledger_description` carrying the audit prose for the accrual, its
        `cumulative_count_before` recording the licence's cumulative count
        immediately before the entry was written"

        Design: Corner/endpoints/endpoint_score_result_void_restores_the_license_counters
        """
        fixture = setup_license_with_postings(num_postings=2, consumer_ref="cons-void")
        license_id = fixture["license"]["id"]
        second = fixture["results"][1]
        before = get_success_data(api_client.get_license(license_id, COMPLIANCE), 200)
        api_client.void_score_result(second["id"], before["version"], COMPLIANCE)
        rows = get_success_data(api_client.list_fee_ledger_entries(
            COMPLIANCE, params={"license_id": license_id}), 200)
        assert len(rows) == 3
        assert len([r for r in rows if r["kind"] == "MARGINAL_PRICING"]) == 2


class TestMigrationEventListing:

    def test_the_pair_filter_returns_exactly_the_crossing_event(self, api):
        """PRD §2.3: "a migration listing by `lender_code`, `from_score_variant_id`,
        `to_score_variant_id`, `carried_decision_reason_code_id` or `event_type`"

        Design: Corner/endpoints/endpoint_migration_event_list_filters_by_both_endpoint_variants
        """
        bureau, m1, v1, m2, v2, crossing, snapshot = setup_migration_event_list()
        res = api_client.list_migration_events(
            COMPLIANCE, params={"from_score_variant_id": v1["id"],
                                "to_score_variant_id": v2["id"]})
        data = validate_success(res, 200)
        assert len(data) == 1
        assert data[0]["id"] == crossing["id"]

    def test_the_event_type_filter_separates_the_two_shapes(self, api):
        """PRD §3.9: "the `event_type` — one of `RECALIBRATED`, `SNAPSHOT_COMPILED`
        or `MIGRATED`"

        Design: Corner/endpoints/endpoint_migration_event_list_filters_by_both_endpoint_variants
        """
        bureau, m1, v1, m2, v2, crossing, snapshot = setup_migration_event_list()
        res = api_client.list_migration_events(
            COMPLIANCE, params={"from_score_variant_id": v1["id"],
                                "event_type": "SNAPSHOT_COMPILED"})
        data = validate_success(res, 200)
        assert len(data) == 1
        assert data[0]["id"] == snapshot["id"]
        assert data[0]["id"] != crossing["id"]

    def test_the_lender_filter_narrows_that_lenders_own_event(self, api):
        """PRD §4: "| GET | `/migration-events` | List migration events, filterable by
        lender and by both endpoint variants | BureauAdministrator, ModelDeveloper,
        ValidationAnalyst, ComplianceOfficer, FairLendingOfficer, ScoreConsumer |"

        Design: Corner/endpoints/endpoint_migration_event_list_filters_by_both_endpoint_variants
        """
        setup_migration_event_list()
        res = api_client.list_migration_events(COMPLIANCE,
                                               params={"lender_code": "LEND-NORTH"})
        _, meta = validate_success(res, 200), res.json()["meta"]
        assert meta["total_count"] == 1


class TestDiscoveryRequestRead:

    def test_the_slot_is_unbound_while_still_registered(self, api):
        """PRD §3.8: "A supplied `discovery_tag` consumes a discovery slot: the
        registered request carrying that tag moves from `REGISTERED` to `CONSUMED`
        and its `consumed_score_result_id` is bound to this posting"

        Design: Corner/endpoints/endpoint_discovery_request_read_exposes_the_consuming_posting
        """
        fixture = setup_discovery_slot_consumed()
        assert fixture["slot"]["status"] == "REGISTERED"
        assert fixture["slot"]["consumed_score_result_id"] is None

    def test_the_read_exposes_the_consuming_posting_after_settlement(self, api):
        """PRD §3.8: "the registered request carrying that tag moves from `REGISTERED`
        to `CONSUMED` and its `consumed_score_result_id` is bound to this posting"

        Design: Corner/endpoints/endpoint_discovery_request_read_exposes_the_consuming_posting
        """
        fixture = setup_discovery_slot_consumed()
        slot = get_success_data(api_client.get_discovery_request(
            fixture["slot"]["id"],
            make_score_consumer_headers(fixture["license"]["id"])), 200)
        assert slot["status"] == "CONSUMED"
        assert slot["consumed_score_result_id"] == fixture["result"]["id"]

    def test_a_posting_without_a_compiled_set_reports_a_null_binding(self, api):
        """PRD §3.8: "The `reference_set_id` is set to the most recently created
        `ReferenceSet` belonging to the same consumer whose `score_model_id` equals
        the posting variant's model version — most recent meaning the greatest
        `created_at`, with ties broken by the ascending creator identifier — and is
        left null when no such set exists."

        Design: Corner/endpoints/endpoint_discovery_request_read_exposes_the_consuming_posting
        """
        fixture = setup_discovery_slot_consumed()
        assert fixture["result"]["reference_set_id"] is None


class TestDocumentationFiling:

    def test_filing_is_what_moves_a_document_off_draft(self, api):
        """PRD §3.9: "Filing moves it from `DRAFT` to `FILED` with `filed_at`
        stamped, and this is the action that unlocks the release and termination
        gates described in §2.10"

        Design: Corner/endpoints/endpoint_model_documentation_file_unlocks_the_release_gate
        """
        model = create_model(version_label="CREDIT-DUAL-V1")
        variant = author_variant(model["id"])
        release_variant(variant["id"])
        md = get_success_data(api_client.create_model_documentation(
            create_model_documentation_payload(score_model_id=model["id"],
                                               doc_type="MODEL_RISK_REPORT",
                                               required_version_label="CREDIT-DUAL-V1"),
            COMPLIANCE), 201)
        assert md["filed_at"] is None
        filed = validate_success(
            api_client.file_model_documentation(md["id"], md["version"], COMPLIANCE), 200)
        assert filed["status"] == "FILED"

    def test_filing_stamps_the_time_and_advances_the_record(self, api):
        """PRD §2.4: "`version` is an integer that starts at its initial value and
        increments by one on every mutation; it exists so that clients can perform
        optimistic concurrency control."

        Design: Corner/endpoints/endpoint_model_documentation_file_unlocks_the_release_gate
        """
        model = create_model(version_label="CREDIT-DUAL-V1")
        variant = author_variant(model["id"])
        release_variant(variant["id"])
        md = get_success_data(api_client.create_model_documentation(
            create_model_documentation_payload(score_model_id=model["id"],
                                               doc_type="MODEL_RISK_REPORT",
                                               required_version_label="CREDIT-DUAL-V1"),
            COMPLIANCE), 201)
        filed = validate_success(
            api_client.file_model_documentation(md["id"], md["version"], COMPLIANCE), 200)
        assert filed["filed_at"] is not None
        assert filed["version"] > md["version"]

    def test_the_checksum_is_deterministic_and_recomputed_on_filing(self, api):
        """PRD §3.9: "Its `checksum` is computed deterministically over the attested
        model, the required version label, the document type and the document status,
        and is recomputed on every content mutation."

        Design: Corner/endpoints/endpoint_model_documentation_file_unlocks_the_release_gate
        """
        model = create_model(version_label="CREDIT-DUAL-V1")
        variant = author_variant(model["id"])
        release_variant(variant["id"])
        md = get_success_data(api_client.create_model_documentation(
            create_model_documentation_payload(score_model_id=model["id"],
                                               doc_type="MODEL_RISK_REPORT",
                                               required_version_label="CREDIT-DUAL-V1"),
            COMPLIANCE), 201)
        filed = validate_success(
            api_client.file_model_documentation(md["id"], md["version"], COMPLIANCE), 200)
        assert filed["checksum"]
        assert filed["checksum"] != md["checksum"], (
            "the status change from DRAFT to FILED must be reflected in the digest"
        )

    def test_the_filed_document_shows_up_under_the_status_filter(self, api):
        """PRD §2.3: "a documentation listing by `score_model_id`, `study_id`,
        `doc_type` or `status`"

        Design: Corner/endpoints/endpoint_model_documentation_file_unlocks_the_release_gate
        """
        model = create_model(version_label="CREDIT-DUAL-V1")
        variant = author_variant(model["id"])
        release_variant(variant["id"])
        md = get_success_data(api_client.create_model_documentation(
            create_model_documentation_payload(score_model_id=model["id"],
                                               doc_type="MODEL_RISK_REPORT",
                                               required_version_label="CREDIT-DUAL-V1"),
            COMPLIANCE), 201)
        api_client.file_model_documentation(md["id"], md["version"], COMPLIANCE)
        res = api_client.list_model_documentation(
            COMPLIANCE, params={"score_model_id": model["id"], "status": "FILED"})
        _, meta = validate_success(res, 200), res.json()["meta"]
        assert meta["total_count"] == 1


class TestReasonCodeListing:

    def test_the_parent_filter_returns_only_the_direct_children(self, api):
        """PRD §2.3: "a catalogue listing by `score_variant_id`,
        `parent_reason_code_id`, `depth_tier` or `status`"

        Design: Corner/endpoints/endpoint_reason_code_list_filters_by_catalogue_parent
        """
        bureau, model, variant, root, child_a, child_b = setup_reason_code_catalogue_tree()
        res = api_client.list_reason_codes(
            REASON_ADMIN, params={"parent_reason_code_id": root["id"]})
        data, meta = validate_success(res, 200), res.json()["meta"]
        assert meta["total_count"] == 2
        assert {row["id"] for row in data} == {child_a["id"], child_b["id"]}

    def test_the_variant_filter_returns_the_whole_tree(self, api):
        """PRD §3.5: "Adverse-action explanations are organised as a catalogue per
        variant."

        Design: Corner/endpoints/endpoint_reason_code_list_filters_by_catalogue_parent
        """
        bureau, model, variant, root, child_a, child_b = setup_reason_code_catalogue_tree()
        res = api_client.list_reason_codes(REASON_ADMIN,
                                           params={"score_variant_id": variant["id"]})
        _, meta = validate_success(res, 200), res.json()["meta"]
        assert meta["total_count"] == 3

    def test_the_composite_code_is_minted_from_the_variant_and_the_authored_fields(self, api):
        """PRD §3.5: "the system-composed `composite_code`, formed by joining the
        variant's model `version_label`, the variant's `industry`, the
        `trigger_feature_code` and the `depth_tier` with hyphens"

        Design: Corner/endpoints/endpoint_reason_code_list_filters_by_catalogue_parent
        """
        bureau, model, variant, root, child_a, child_b = setup_reason_code_catalogue_tree()
        row = get_success_data(api_client.get_reason_code(child_b["id"], REASON_ADMIN), 200)
        assert row["composite_code"].endswith("TERTIARY")
        assert "CHILD-B" in row["composite_code"]
        assert variant["industry"] in row["composite_code"]

    def test_a_node_with_no_archived_descendants_receives_nothing(self, api):
        """PRD §3.5: "and the `weight_effective_pct`, which is the entry's own
        `weight_pct` plus whatever `weight_received_pct` has bubbled up to it,
        rounded half-up to four decimal places."

        Design: Corner/endpoints/endpoint_reason_code_list_filters_by_catalogue_parent
        """
        bureau, model, variant, root, child_a, child_b = setup_reason_code_catalogue_tree()
        row = get_success_data(api_client.get_reason_code(child_b["id"], REASON_ADMIN), 200)
        assert row["weight_received_pct"] == 0
        assert row["weight_effective_pct"] == row["weight_pct"]