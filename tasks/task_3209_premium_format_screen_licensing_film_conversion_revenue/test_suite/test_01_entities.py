"""Entity corner tests: creation, retrieval, listing, not-found, required
fields, defaults, computed fields, system fields, type constraints,
immutability, parent relationships."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_auditorium,
    assert_box_office_report,
    get_statement_line,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
    create_agreement_payload,
    create_box_office_report_payload,
    create_conversion_order_payload,
    create_market_payload,
    create_qa_alert_payload,
    create_screen_slot_payload,
    create_tech_dispatch_payload,
    create_approved_market,
    create_conversion_order,
    create_signed_agreement,
    create_active_studio,
    create_film,
    create_operating_auditorium,
    propose_slot,
    set_clock,
    setup_bookable_scenario,
    setup_confirmed_slot_scenario,
)


class TestMarketCreation:
    def test_market_create_returns_201_with_prospect_and_zero_opened(
        self, api, network_planner_headers
    ):
        """PRD §3.1: "A new market enters in `PROSPECT`."
        PRD §2.4: "The `version` is an integer that starts at 1 on creation
        and increments by one on every mutation, including mutations driven by
        cascading side effects from other entities."
        PRD §2.10: "tracks `opened_screen_count`, the current count of its
        auditoriums in `OPERATING`."

        Design: Corner/entities/market_create_returns_201_and_initial_state_prospect
        """
        set_clock()
        resp = api.create_market(create_market_payload(), network_planner_headers)
        data = validate_success(resp, expected_status=201)
        assert resp.json()["response_type"] == "object"
        assert data["status"] == "PROSPECT"
        assert data["version"] == 1
        assert data["opened_screen_count"] == 0
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert is_iso8601_timestamp(data["updated_at"])

    def test_market_create_ignores_client_supplied_system_fields(
        self, api, network_planner_headers
    ):
        """PRD §2.4: "The `id` is a server-minted UUID with no type prefix."
        and "The `version` is an integer that starts at 1 on creation and
        increments by one on every mutation, including mutations driven by
        cascading side effects from other entities."

        Design: Corner/entities/market_create_extra_field_id_and_version_are_ignored_input
        """
        set_clock()
        payload = create_market_payload(
            market_name="M",
            screen_capacity_cap=1,
            id="11111111-1111-4111-8111-111111111111",
            version=99,
        )
        resp = api.create_market(payload, network_planner_headers)
        data = validate_success(resp, expected_status=201)
        assert data["version"] == 1, (
            f"version must start at 1 on creation, got {data['version']}"
        )


class TestAgreementRetrieval:
    def test_agreement_get_round_trips_input_fields(
        self, api, network_planner_headers, contract_manager_headers
    ):
        """PRD §3.1: "A new agreement enters in `NEGOTIATING` with
        `total_slots_committed_count` at zero."
        PRD §2.10: "which starts at zero when the agreement is created."

        Design: Corner/entities/agreement_get_returns_stored_fields_unchanged
        """
        set_clock()
        market = create_approved_market()
        agreement = get_success_data(
            api.create_agreement(
                create_agreement_payload(
                    market_id=market["id"],
                    exhibitor_legal_name="Exh A",
                    agreement_type="REVENUE_SHARE",
                    committed_screen_count=2,
                    revenue_share_tier1_pct=0.12,
                    revenue_share_tier2_pct=0.15,
                    revenue_share_tier3_pct=0.18,
                    term_start_date="2026-09-01T00:00:00Z",
                    term_end_date="2027-09-01T00:00:00Z",
                ),
                contract_manager_headers,
            )
        )
        fetched = validate_success(
            api.get_agreement(agreement["id"], contract_manager_headers)
        )
        assert fetched["exhibitor_legal_name"] == "Exh A"
        assert fetched["agreement_type"] == "REVENUE_SHARE"
        assert fetched["revenue_share_tier1_pct"] == 0.12
        assert fetched["total_slots_committed_count"] == 0


class TestPagination:
    def test_markets_paginate_with_total_count_and_has_more(
        self, api, network_planner_headers
    ):
        """PRD §2.3: "The `limit` parameter caps the number of items returned"
        and "every list response carries `limit`, `offset`, `total_count`, and
        `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/list_endpoints_paginate_with_total_count_and_has_more
        """
        set_clock()
        for name in ("M1", "M2", "M3"):
            get_success_data(
                api.create_market(
                    create_market_payload(market_name=name), network_planner_headers)
            )
        page1, meta1 = validate_paginated(
            api.list_markets(network_planner_headers, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(
            api.list_markets(network_planner_headers, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestNotFound:
    def test_get_auditorium_unknown_id_returns_404(
        self, api, field_engineer_headers
    ):
        """PRD §2.9: "each missing referenced resource produces the
        corresponding `ERR_{RESOURCE}_NOT_FOUND` (HTTP 404)."
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/entities/get_auditorium_with_unknown_id_returns_404
        """
        set_clock()
        resp = api.get_auditorium(NON_EXISTENT_UUID, field_engineer_headers)
        assert resp.status_code == 404, (
            f"Expected 404, got {resp.status_code}: {resp.text}"
        )
        validate_error(resp, ApiErrorId.ERR_AUDITORIUM_NOT_FOUND)
        body = resp.json()
        assert body["response_type"] == "error"
        assert "error_id" in body["data"] and "message" in body["data"]


class TestRequiredFields:
    def test_agreement_create_missing_term_start_date_is_400(
        self, api, network_planner_headers, contract_manager_headers
    ):
        """PRD §3.1: "the contract's `term_start_date` (UTC midnight,
        inclusive) and `term_end_date` (UTC midnight, exclusive)" are
        supplied at drafting, and PRD §2.9: "Malformed payloads — a missing
        required field, a type mismatch, an unrecognized enum value — are
        rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/agreement_create_missing_term_start_date_returns_invalid_request
        """
        set_clock()
        market = create_approved_market()
        payload = create_agreement_payload(market_id=market["id"])
        del payload["term_start_date"]
        resp = api.create_agreement(payload, contract_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestConversionDefaults:
    def test_filmmaker_approval_required_defaults_false(
        self, api, studio_manager_headers, post_scheduler_headers,
        qa_reviewer_headers
    ):
        """PRD §3.3: "an optional `filmmaker_approval_required` flag that
        defaults to false."
        and "`QC_REVIEW → APPROVED_FOR_RELEASE` — requires that whenever
        `filmmaker_approval_required` is true, the request sets
        `filmmaker_signoff` to true."

        Design: Corner/entities/conversion_order_create_defaults_filmmaker_approval_required_false
        """
        set_clock()
        studio = create_active_studio()
        film = create_film(studio["id"], title="F", runtime_minutes=90,
                           worldwide_release_date="2026-09-15T00:00:00Z")
        order = create_conversion_order(
            film["id"],
            scheduled_post_start_date="2026-09-01T00:00:00Z",
            scheduled_post_end_date="2026-09-03T00:00:00Z",
        )
        assert order["filmmaker_approval_required"] is False
        get_success_data(api.begin_post(order["id"], post_scheduler_headers))
        set_clock("2026-09-04T00:00:00Z")
        get_success_data(api.submit_for_qc(order["id"], post_scheduler_headers))
        resp = api.approve_release(order["id"], qa_reviewer_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "APPROVED_FOR_RELEASE"


class TestComputedFields:
    def test_slot_committed_screen_seconds_computed_at_creation(
        self, api, release_scheduler_headers
    ):
        """PRD §3.5: "take the slot length in whole days (the difference
        between `slot_end_date` and `slot_start_date`, which must be at least
        1), multiply by `showings_per_day`, multiply by the parent film's
        `runtime_minutes`, and multiply by 60 to reach seconds."
        and "A new slot enters in `PROPOSED`."

        Design: Corner/entities/screen_slot_committed_screen_seconds_computed_at_creation
        """
        ctx = setup_bookable_scenario()
        slot = propose_slot(
            ctx["window"]["id"], ctx["auditorium"]["id"], ctx["film"]["id"],
            ctx["conversion"]["id"],
            slot_start_date="2026-09-07T00:00:00Z",
            slot_end_date="2026-09-14T00:00:00Z",
            showings_per_day=2,
        )
        # 7 days x 2 showings x 100 min x 60 s = 84000
        assert slot["committed_screen_seconds"] == 84000
        assert slot["status"] == "PROPOSED"


class TestTypeConstraints:
    def test_invalid_severity_enum_rejected_400(
        self, api, field_engineer_headers
    ):
        """PRD §3.7: "a `severity` of `INFO`, `WARNING`, or `CRITICAL`"
        and PRD §2.9: "Malformed payloads — a missing required field, a type
        mismatch, an unrecognized enum value — are rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/invalid_enum_on_severity_returns_invalid_request
        """
        set_clock()
        market = create_approved_market()
        agreement = create_signed_agreement(market["id"])
        auditorium = create_operating_auditorium(agreement["id"])
        resp = api.create_qa_alert(
            create_qa_alert_payload(
                auditorium_id=auditorium["id"],
                alert_code="SOUND_DRIFT",
                severity="FATAL",
            ),
            field_engineer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestBoxOfficeReportImmutability:
    def test_report_response_omits_updated_at_and_version(
        self, api, box_office_analyst_headers
    ):
        """PRD §2.4: "Both `updated_at` and `version` are absent from
        BoxOfficeReport resources; once created, a report is never modified,
        only transitioned between `RECEIVED`, `VALIDATED`, and
        `FLAGGED_DISCREPANCY`."

        Design: Corner/entities/box_office_report_is_immutable_no_update_endpoint
        """
        ctx = setup_confirmed_slot_scenario()
        resp = api.create_box_office_report(
            create_box_office_report_payload(
                screen_slot_id=ctx["slot"]["id"],
                reported_date="2026-09-07T00:00:00Z",
                gross_receipts_cents=100,
                admissions=1,
            ),
            box_office_analyst_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_box_office_report(data)
        assert data["status"] == "RECEIVED"


class TestParentRelationships:
    def test_dispatch_auditorium_must_match_alert_auditorium(
        self, api, network_planner_headers, contract_manager_headers,
        field_engineer_headers
    ):
        """PRD §3.7: "the `auditorium_id` (denormalized for routing, and it
        must equal the alert's own `auditorium_id`)."
        PRD §2.9: "Malformed payloads — a missing required field, a type
        mismatch, an unrecognized enum value — are rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/tech_dispatch_auditorium_id_must_match_qa_alert_auditorium
        """
        set_clock()
        market = create_approved_market()
        agreement = create_signed_agreement(market["id"])
        aud_1 = get_success_data(
            api.create_auditorium(
                {"agreement_id": agreement["id"], "auditorium_label": "S1",
                 "screen_geometry": {"width_m": 20, "height_m": 11, "curvature_deg": 60},
                 "seating_capacity": 200, "supported_formats": ["PREMIUM_2D"],
                 "sound_calibration_profile": {"spl_target_db": 85,
                                               "eq_curve_id": "STD",
                                               "channel_count": 12}},
                contract_manager_headers,
            )
        )
        aud_2 = get_success_data(
            api.create_auditorium(
                {"agreement_id": agreement["id"], "auditorium_label": "S2",
                 "screen_geometry": {"width_m": 20, "height_m": 11, "curvature_deg": 60},
                 "seating_capacity": 200, "supported_formats": ["PREMIUM_2D"],
                 "sound_calibration_profile": {"spl_target_db": 85,
                                               "eq_curve_id": "STD",
                                               "channel_count": 12}},
                contract_manager_headers,
            )
        )
        alert = get_success_data(
            api.create_qa_alert(
                create_qa_alert_payload(
                    auditorium_id=aud_1["id"], alert_code="SOUND_DRIFT",
                    severity="WARNING"),
                field_engineer_headers,
            )
        )
        resp = api.create_tech_dispatch(
            create_tech_dispatch_payload(
                qa_alert_id=alert["id"], auditorium_id=aud_2["id"],
                scheduled_visit_date="2026-09-05T00:00:00Z",
                tech_specialty="SOUND"),
            field_engineer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
