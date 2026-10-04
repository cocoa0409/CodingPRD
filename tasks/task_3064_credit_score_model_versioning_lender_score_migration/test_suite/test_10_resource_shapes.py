"""What a resource returns: defaults, round-trips, computed fields, bounds."""
from test_helpers import api_client, validate_success, validate_paginated, get_success_data, DEVELOPER, COMPLIANCE, create_score_model_payload, create_consumer_payload, create_archive_sample_payload, create_score_result_payload, setup_license_with_postings, setup_released_dual_auto, create_consumer, create_and_activate_license, make_score_consumer_headers, post_score


class TestScoreModelShape:

    def test_a_minimal_create_returns_the_declared_defaults(self, api):
        """PRD §3.1: "and optionally its `score_floor` and `score_ceiling`, which
        default to 300 and 850 when omitted."
        PRD §3.1: "A newly created version begins in `DEVELOPMENT` with
        `active_variant_count` counted from its own variants alone."
        PRD §3.1: "The `cascade_depth` of a new version is zero when it has no
        `predecessor_model_id`"

        Design: Corner/entities/score_model_create_returns_declared_fields_and_development_status
        """
        data = validate_success(
            api_client.create_score_model(
                create_score_model_payload(family_code="FICO_CORE",
                                           version_label="CREDIT-DUAL-V1",
                                           min_input_count=100), DEVELOPER), 201)
        assert data["status"] == "DEVELOPMENT"
        assert data["cascade_depth"] == 0
        assert data["active_variant_count"] == 0

    def test_the_score_bounds_default_without_being_supplied(self, api):
        """PRD §3.1: "and optionally its `score_floor` and `score_ceiling`, which
        default to 300 and 850 when omitted."

        Design: Corner/entities/score_model_create_returns_declared_fields_and_development_status
        """
        data = validate_success(
            api_client.create_score_model(
                create_score_model_payload(family_code="FICO_CORE",
                                           version_label="CREDIT-DUAL-V1",
                                           min_input_count=100), DEVELOPER), 201)
        assert data["score_floor"] == 300
        assert data["score_ceiling"] == 850

    def test_the_response_carries_the_managed_properties_and_envelope(self, api):
        """PRD §2.4: "Every primary resource in the system carries a system-managed
        `id`, a `created_at`, an `updated_at`, and a `version`."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
        the request that starts with `req_`."

        Design: Corner/entities/score_model_create_returns_declared_fields_and_development_status
        """
        res = api_client.create_score_model(
            create_score_model_payload(family_code="FICO_CORE",
                                       version_label="CREDIT-DUAL-V1",
                                       min_input_count=100), DEVELOPER)
        data = validate_success(res, 201)
        assert data["id"] and data["created_at"] and data["updated_at"]
        assert data["version"] == 1
        body = res.json()
        assert body["meta"]["api_request_id"]
        assert body["meta"]["api_request_timestamp"]
        assert body["response_type"] == "object"

    def test_a_body_carrying_server_sourced_fields_is_rejected(self, api):
        """PRD §2.12: "A violation of any of them, or a malformed body, unknown
        field or wrong type, is reported as `ERR_INVALID_REQUEST`."

        Design: Corner/entities/score_model_invalid_extra_system_fields_are_rejected
        """
        res = api_client.create_score_model(
            {"family_code": "FICO_CORE", "version_label": "SYS-V1", "min_input_count": 100,
             "status": "RELEASED", "released_at": "2026-01-01T00:00:00.000Z",
             "cascade_depth": 9, "active_variant_count": 4}, DEVELOPER)
        assert res.status_code == 400
        assert res.json()["data"]["error_id"] == "ERR_INVALID_REQUEST"

    def test_the_rejected_create_wrote_nothing(self, api):
        """PRD §2.12: "A violation of any of them, or a malformed body, unknown
        field or wrong type, is reported as `ERR_INVALID_REQUEST`."

        Design: Corner/entities/score_model_invalid_extra_system_fields_are_rejected
        """
        api_client.create_score_model(
            {"family_code": "FICO_CORE", "version_label": "SYS-V1", "min_input_count": 100,
             "status": "RELEASED", "released_at": "2026-01-01T00:00:00.000Z",
             "cascade_depth": 9, "active_variant_count": 4}, DEVELOPER)
        res = api_client.list_score_models(DEVELOPER)
        data, meta = validate_paginated(res)
        assert meta["total_count"] == 0

    def test_omitting_the_minimum_input_count_is_a_malformed_request(self, api):
        """PRD §3.1: "A `ModelDeveloper` opens a scoring family by creating a version
        and supplying its `family_code`, its `version_label`, the minimum tradeline
        row count the model needs before any study can run against it as
        `min_input_count`"
        PRD §2.12: "A violation of any of them, or a malformed body, unknown field or
        wrong type, is reported as `ERR_INVALID_REQUEST`."

        Design: Corner/entities/score_model_create_missing_min_input_count_returns_invalid_request
        """
        res = api_client.create_score_model(
            {"family_code": "FICO_CORE", "version_label": "NO-MIN-V1"}, DEVELOPER)
        assert res.status_code == 400
        assert res.json()["data"]["error_id"] == "ERR_INVALID_REQUEST"

    def test_the_incomplete_create_left_no_row_behind(self, api):
        """PRD §3.1: "A `ModelDeveloper` opens a scoring family by creating a version
        and supplying its `family_code`, its `version_label`, the minimum tradeline
        row count the model needs before any study can run against it as
        `min_input_count`"

        Design: Corner/entities/score_model_create_missing_min_input_count_returns_invalid_request
        """
        api_client.create_score_model(
            {"family_code": "FICO_CORE", "version_label": "NO-MIN-V1"}, DEVELOPER)
        res = api_client.list_score_models(DEVELOPER)
        data, meta = validate_paginated(res)
        assert meta["total_count"] == 0


class TestConsumerShape:

    def test_a_consumer_round_trips_every_stored_field(self, api):
        """PRD §4: "| POST | `/consumers` | Register a pseudonymous archive consumer |
        ModelDeveloper, ValidationAnalyst, FairLendingOfficer, ReasonCodeAdministrator |"

        Design: Corner/entities/consumer_get_round_trips_every_stored_field
        """
        created = get_success_data(api_client.create_consumer(
            create_consumer_payload(consumer_ref="cons-rt-1", age_years=57,
                                    is_protected_class=True), DEVELOPER), 201)
        data = validate_success(api_client.get_consumer(created["id"], DEVELOPER), 200)
        assert data["consumer_ref"] == "cons-rt-1"
        assert data["age_years"] == 57
        assert data["is_protected_class"] is True

    def test_a_fresh_consumer_has_no_undecided_postings_and_no_upload(self, api):
        """PRD §3.6: "Third, `model_undecided_count` is recomputed for every affected
        consumer."

        Design: Corner/entities/consumer_get_round_trips_every_stored_field
        """
        created = get_success_data(api_client.create_consumer(
            create_consumer_payload(consumer_ref="cons-rt-1", age_years=57,
                                    is_protected_class=True), DEVELOPER), 201)
        data = validate_success(api_client.get_consumer(created["id"], DEVELOPER), 200)
        assert data["model_undecided_count"] == 0
        assert data["latest_uploaded_at"] is None


class TestPostingShapes:

    def test_effective_score_is_derived_and_not_echoed_from_input(self, api):
        """PRD §3.8: "the difference between `raw_posted_score` and the variant's
        `ref_score` is divided by the variant's `segment_width`, rounded down to a
        whole number, and that index is constrained to the range 0 to 2 inclusive.
        Then the provisional score is formed by adding the variant's
        `segment_offsets` entry for that band to the raw score and clamping the
        result between the model's `score_floor` and `score_ceiling`."

        Design: Corner/entities/score_result_effective_score_is_computed_and_ignores_client_supplied_value
        """
        bureau, model, variant = setup_released_dual_auto()
        license_ = create_and_activate_license(variant["id"], entitled_count=500)
        consumer = create_consumer(consumer_ref="cons-cf-1", age_years=26)
        posting = get_success_data(api_client.create_score_result(
            create_score_result_payload(
                consumer_id=consumer["id"], score_variant_id=variant["id"],
                bureau_id=bureau["id"], license_id=license_["id"],
                raw_posted_score=715, expected_license_version=license_["version"]),
            make_score_consumer_headers(license_["id"])), 201)
        assert posting["effective_score"] == 700
        assert posting["effective_score"] != 715

    def test_the_stored_row_agrees_with_the_create_response(self, api):
        """PRD §3.8: "Only then is the rounding penalty computed, as the variant's
        `rounding_penalty_pct` applied to the already-clamped provisional score and
        rounded up to a whole point, and subtracted from the provisional score to
        give the stored `effective_score`."

        Design: Corner/entities/score_result_effective_score_is_computed_and_ignores_client_supplied_value
        """
        bureau, model, variant = setup_released_dual_auto()
        license_ = create_and_activate_license(variant["id"], entitled_count=500)
        consumer = create_consumer(consumer_ref="cons-cf-1", age_years=26)
        posting = get_success_data(api_client.create_score_result(
            create_score_result_payload(
                consumer_id=consumer["id"], score_variant_id=variant["id"],
                bureau_id=bureau["id"], license_id=license_["id"],
                raw_posted_score=715, expected_license_version=license_["version"]),
            make_score_consumer_headers(license_["id"])), 201)
        stored = validate_success(api_client.get_score_result(posting["id"], DEVELOPER), 200)
        assert stored["effective_score"] == posting["effective_score"]
        assert stored["odds_at_posted_score"] == posting["odds_at_posted_score"]

    def test_the_reported_odds_are_taken_at_the_effective_score(self, api):
        """PRD §3.8: "The odds reported alongside the score are formed from the
        effective score rather than the raw one."

        Design: Corner/entities/score_result_effective_score_is_computed_and_ignores_client_supplied_value
        """
        bureau, model, variant = setup_released_dual_auto()
        license_ = create_and_activate_license(variant["id"], entitled_count=500)
        consumer = create_consumer(consumer_ref="cons-cf-1", age_years=26)
        posting = get_success_data(api_client.create_score_result(
            create_score_result_payload(
                consumer_id=consumer["id"], score_variant_id=variant["id"],
                bureau_id=bureau["id"], license_id=license_["id"],
                raw_posted_score=715, expected_license_version=license_["version"]),
            make_score_consumer_headers(license_["id"])), 201)
        assert posting["effective_score"] == 700
        assert isinstance(posting["odds_at_posted_score"], (int, float))
        assert posting["odds_at_posted_score"] > 0

    def test_a_raw_score_below_the_floor_is_refused(self, api):
        """PRD §2.12: "The magnitude bounds enforced at the format layer are:
        `raw_posted_score` between 300 and 850 inclusive"

        Design: Corner/entities/score_result_rejects_an_out_of_range_raw_score
        """
        fixture = setup_license_with_postings(num_postings=0, consumer_ref="cons-tc-1")
        res = api_client.create_score_result(
            create_score_result_payload(
                consumer_id=fixture["consumer"]["id"],
                score_variant_id=fixture["variant"]["id"],
                bureau_id=fixture["bureau"]["id"], license_id=fixture["license"]["id"],
                raw_posted_score=299,
                expected_license_version=fixture["license"]["version"]),
            make_score_consumer_headers(
                fixture["license"]["id"]))
        assert res.status_code == 400
        assert res.json()["data"]["error_id"] == "ERR_INVALID_REQUEST"

    def test_a_raw_score_above_the_ceiling_is_refused(self, api):
        """PRD §2.12: "The magnitude bounds enforced at the format layer are:
        `raw_posted_score` between 300 and 850 inclusive"

        Design: Corner/entities/score_result_rejects_an_out_of_range_raw_score
        """
        fixture = setup_license_with_postings(num_postings=0, consumer_ref="cons-tc-1")
        res = api_client.create_score_result(
            create_score_result_payload(
                consumer_id=fixture["consumer"]["id"],
                score_variant_id=fixture["variant"]["id"],
                bureau_id=fixture["bureau"]["id"], license_id=fixture["license"]["id"],
                raw_posted_score=851,
                expected_license_version=fixture["license"]["version"]),
            make_score_consumer_headers(fixture["license"]["id"]))
        assert res.status_code == 400
        assert res.json()["data"]["error_id"] == "ERR_INVALID_REQUEST"

    def test_the_closed_interval_endpoint_300_is_accepted(self, api):
        """PRD §3.8: "A licensed lender's service posts a score by naming the
        `consumer_id`, the `score_variant_id`, the `bureau_id`, the `license_id`,
        and the `raw_posted_score` received from the bureau, between 300 and 850
        inclusive."

        Design: Corner/entities/score_result_rejects_an_out_of_range_raw_score
        """
        fixture = setup_license_with_postings(num_postings=0, consumer_ref="cons-tc-1")
        posting = post_score(fixture["license"]["id"], fixture["consumer"]["id"],
                             fixture["variant"]["id"], fixture["bureau"]["id"], 300)
        assert posting["id"] is not None
        res = api_client.list_score_results(
            DEVELOPER, params={"consumer_id": fixture["consumer"]["id"]})
        data, meta = validate_paginated(res)
        assert meta["total_count"] == 1


class TestPaginationAndReads:

    def test_a_page_reports_the_whole_filtered_total(self, api):
        """PRD §2.3: "`limit` caps the number of items returned, defaults to 10, has
        a minimum of 1 and a maximum of 100. `offset` is the number of items to skip
        before the page begins and defaults to 0."
        PRD §2.3: "Responses that carry a collection include `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/score_results_list_paginates_and_reports_total_count_and_has_more
        """
        fixture = setup_license_with_postings(num_postings=3, consumer_ref="cons-page")
        res = api_client.list_score_results(
            DEVELOPER, params={"consumer_id": fixture["consumer"]["id"],
                               "limit": 2, "offset": 0})
        data, meta = validate_paginated(res)
        assert len(data) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

    def test_the_last_page_reports_no_more(self, api):
        """PRD §2.3: "Responses that carry a collection include `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/score_results_list_paginates_and_reports_total_count_and_has_more
        """
        fixture = setup_license_with_postings(num_postings=3, consumer_ref="cons-page")
        res = api_client.list_score_results(
            DEVELOPER, params={"consumer_id": fixture["consumer"]["id"],
                               "limit": 100, "offset": 2})
        data, meta = validate_paginated(res)
        assert len(data) == 1
        assert meta["total_count"] == 3
        assert meta["has_more"] is False

    def test_an_unpaged_list_applies_the_declared_defaults(self, api):
        """PRD §2.3: "`limit` caps the number of items returned, defaults to 10, has
        a minimum of 1 and a maximum of 100. `offset` is the number of items to skip
        before the page begins and defaults to 0."

        Design: Corner/entities/score_results_list_paginates_and_reports_total_count_and_has_more
        """
        fixture = setup_license_with_postings(num_postings=3, consumer_ref="cons-page")
        res = api_client.list_score_results(
            DEVELOPER, params={"consumer_id": fixture["consumer"]["id"]})
        data, meta = validate_paginated(res)
        assert len(data) == 3
        assert meta["limit"] == 10
        assert meta["offset"] == 0

    def test_an_unallocated_licence_id_raises_the_entity_specific_not_found(self, api):
        """PRD §2.7: "The entity-specific not-found error is raised rather than a
        generic one: `ERR_BUREAU_NOT_FOUND`, `ERR_SCORE_MODEL_NOT_FOUND`,
        `ERR_SCORE_VARIANT_NOT_FOUND`, `ERR_CONSUMER_NOT_FOUND`,
        `ERR_ARCHIVE_SAMPLE_NOT_FOUND`, `ERR_VALIDATION_STUDY_NOT_FOUND`,
        `ERR_REFERENCE_SET_NOT_FOUND`, `ERR_SCORE_RESULT_NOT_FOUND`,
        `ERR_REASON_CODE_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`, `ERR_MODEL_DOCUMENTATION_NOT_FOUND`,
        `ERR_MIGRATION_EVENT_NOT_FOUND`, `ERR_DISCOVERY_REQUEST_NOT_FOUND` and
        `ERR_FEE_LEDGER_ENTRY_NOT_FOUND` — each at HTTP status 404."

        Design: Corner/entities/license_get_with_an_unknown_id_returns_license_not_found
        """
        res = api_client.get_license("0ab1c2d3-4e5f-4061-8273-849506172839", COMPLIANCE)
        assert res.status_code == 404
        assert res.json()["data"]["error_id"] == "ERR_LICENSE_NOT_FOUND"

    def test_the_error_envelope_carries_a_message(self, api):
        """PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/entities/license_get_with_an_unknown_id_returns_license_not_found
        """
        res = api_client.get_license("0ab1c2d3-4e5f-4061-8273-849506172839", COMPLIANCE)
        body = res.json()
        assert body["response_type"] == "error"
        assert body["data"]["message"].strip()

    def test_an_unknown_parent_model_blocks_the_archive_draw(self, api):
        """PRD §2.7: "Foreign-key identifiers supplied in a *request body* are
        resolved at a later point in the ordering, and a body reference that does not
        resolve raises the corresponding entity-specific 404 as well."

        Design: Corner/entities/archive_sample_returns_not_found_for_an_unknown_parent_model
        """
        res = api_client.create_archive_sample(
            create_archive_sample_payload(
                score_model_id="7f3a1b2c-3d4e-4f50-9161-728394a5b6c7",
                sample_ref="DEV-ORPHAN", record_count=1000, segment_name="PRIME",
                sample_kind="DEVELOPMENT", observation_window_months=12,
                window_start_month="2025-01", window_end_month="2026-01"), DEVELOPER)
        assert res.status_code == 404
        assert res.json()["data"]["error_id"] == "ERR_SCORE_MODEL_NOT_FOUND"

    def test_the_refused_draw_wrote_no_sample(self, api):
        """PRD §3.3: "A `ModelDeveloper` or `ValidationAnalyst` draws a sample
        against a version by supplying its `sample_ref` — unique within that model
        version"

        Design: Corner/entities/archive_sample_returns_not_found_for_an_unknown_parent_model
        """
        api_client.create_archive_sample(
            create_archive_sample_payload(
                score_model_id="7f3a1b2c-3d4e-4f50-9161-728394a5b6c7",
                sample_ref="DEV-ORPHAN", record_count=1000, segment_name="PRIME",
                sample_kind="DEVELOPMENT", observation_window_months=12,
                window_start_month="2025-01", window_end_month="2026-01"), DEVELOPER)
        res = api_client.list_archive_samples(DEVELOPER)
        data, meta = validate_paginated(res)
        assert meta["total_count"] == 0


class TestLedgerImmutability:

    def test_a_settlement_writes_one_marginal_ledger_row(self, api):
        """PRD §3.8: "Settlement closes the posting. A `MARGINAL_PRICING` entry is
        appended to the fee ledger — its `ledger_description` carrying the audit
        prose for the accrual, its `cumulative_count_before` recording the licence's
        cumulative count immediately before the entry was written"

        Design: Corner/entities/fee_ledger_entry_has_no_version_and_no_update_endpoint
        """
        fixture = setup_license_with_postings(num_postings=1, consumer_ref="cons-imm-1")
        rows = get_success_data(api_client.list_fee_ledger_entries(
            COMPLIANCE, params={"license_id": fixture["license"]["id"]}), 200)
        assert len(rows) == 1
        assert rows[0]["kind"] == "MARGINAL_PRICING"
        assert rows[0]["fee_cents"] == 18
        assert rows[0]["cumulative_count_before"] == 0

    def test_the_licence_counters_match_the_single_ledger_row(self, api):
        """PRD §3.8: "and the licence's `cumulative_fee_cents` and
        `cumulative_score_count` advance by the marginal charge and one unit
        respectively"

        Design: Corner/entities/fee_ledger_entry_has_no_version_and_no_update_endpoint
        """
        fixture = setup_license_with_postings(num_postings=1, consumer_ref="cons-imm-1")
        license_ = get_success_data(
            api_client.get_license(fixture["license"]["id"], COMPLIANCE), 200)
        assert license_["cumulative_fee_cents"] == 18
        assert license_["cumulative_score_count"] == 1

    def test_the_ledger_row_is_append_only_in_shape(self, api):
        """PRD §2.4: "A `FeeLedgerEntry` and a `MigrationEvent` are append-only
        ledger rows: each carries only `id` and `created_at`, and neither
        `updated_at` nor `version` exists on them."

        Design: Corner/entities/fee_ledger_entry_has_no_version_and_no_update_endpoint
        """
        fixture = setup_license_with_postings(num_postings=1, consumer_ref="cons-imm-1")
        rows = get_success_data(api_client.list_fee_ledger_entries(
            COMPLIANCE, params={"license_id": fixture["license"]["id"]}), 200)
        row = rows[0]
        assert row["id"] and row["created_at"]
        assert "updated_at" not in row
        assert "version" not in row