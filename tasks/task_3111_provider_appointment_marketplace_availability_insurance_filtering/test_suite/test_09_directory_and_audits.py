"""Tests for directory search (PRD §4 GET /marketplace/providers), audit
severity thresholds, and the audit finding-resolution gate (PRD §3.11).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_attestation,
    create_plan,
    create_provider,
    create_slot,
    get_attestation,
    get_slot,
    make_practice_staff_headers,
    set_clock,
    setup_bookable_practice,
    validate_error,
    validate_paginated,
    validate_success,
    verify_attestation,
)
from test_helpers.fixtures import (
    activate_provider,
    create_and_activate_practice,
)


class TestDirectorySearchFiltersByVerifiedAttestation:
    def _setup_three_practices(self):
        plan = create_plan()
        # Practice 1 ACTIVE + provider A with a VERIFIED attestation.
        p1 = create_and_activate_practice(name="P1")
        prov_a = activate_provider(create_provider(p1["id"], display_name="Dr A")["id"])
        verify_attestation(create_attestation(prov_a["id"], plan["id"])["id"], "VERIFY")
        # Practice 2 ACTIVE + provider B with an ATTESTED (unverified) attestation.
        p2 = create_and_activate_practice(name="P2")
        prov_b = activate_provider(create_provider(p2["id"], display_name="Dr B")["id"])
        create_attestation(prov_b["id"], plan["id"])
        # Practice 3 SUSPENDED + provider C with a VERIFIED attestation.
        p3 = create_and_activate_practice(name="P3")
        prov_c = activate_provider(create_provider(p3["id"], display_name="Dr C")["id"])
        verify_attestation(
            create_attestation(prov_c["id"], plan["id"])["id"], "VERIFY"
        )
        api_client.suspend_practice(p3["id"], TEST_USERS["ops_admin_headers"])
        return plan, prov_a, prov_b, prov_c

    def test_plan_filter_returns_only_verified_bookable_provider(self, api):
        """PRD §3.3: "Only a `VERIFIED` attestation whose window contains the current logical time — `effective_from` at or before now, and now strictly before `effective_to` — counts as actual acceptance, and that single fact drives both directory filtering and booking validation."
        PRD §3.1: "The derived field `bookable_in_directory` on a provider is true exactly when the provider's own `status` is `ACTIVE` and the owning practice's `status` is `ACTIVE`."

        Design: Corner/endpoints/directory_search_filters_by_verified_attestation
        """
        plan, prov_a, prov_b, prov_c = self._setup_three_practices()
        resp = api_client.list_providers(
            TEST_USERS["ops_admin_headers"],
            params={"plan_id": plan["id"], "bookable_only": "true"},
        )
        data, meta = validate_paginated(resp)
        ids = [p["id"] for p in data]
        assert meta["total_count"] == 1
        assert ids == [prov_a["id"]]

    def test_unverified_and_suspended_providers_excluded(self, api):
        """PRD §3.3: "Only a `VERIFIED` attestation whose window contains the current logical time — `effective_from` at or before now, and now strictly before `effective_to` — counts as actual acceptance, and that single fact drives both directory filtering and booking validation."
        PRD §3.1: "The derived field `bookable_in_directory` on a provider is true exactly when the provider's own `status` is `ACTIVE` and the owning practice's `status` is `ACTIVE`."

        Design: Corner/endpoints/directory_search_filters_by_verified_attestation
        """
        plan, prov_a, prov_b, prov_c = self._setup_three_practices()
        resp = api_client.list_providers(
            TEST_USERS["ops_admin_headers"],
            params={"plan_id": plan["id"], "bookable_only": "true", "limit": 100},
        )
        data, meta = validate_paginated(resp)
        ids = {p["id"] for p in data}
        assert prov_b["id"] not in ids, "provider B has only an ATTESTED attestation"
        assert prov_c["id"] not in ids, "provider C's practice is SUSPENDED"


class TestAuditSeverityThresholdBoundaries:
    def _provider_with_n_stale_slots(self, practice, n_stale, total=20):
        """Create a provider with `total` slots, of which the first `n_stale`
        will be in the past once the clock is advanced to 2026-09-03T01:00:00Z.
        Slots are ordered by start; all half-hour slots from 2026-09-03T00:00.
        """
        provider = activate_provider(create_provider(practice["id"], display_name="Dr A")["id"])
        # First `n_stale` slots before 01:00 on Sep 3; remaining after 01:00.
        for i in range(total):
            if i < n_stale:
                # 00:00 + i*5 min — all strictly before 01:00 for i < 12.
                start_min = i * 5
                start = f"2026-09-03T00:{start_min:02d}:00Z"
                end = f"2026-09-03T00:{start_min + 5:02d}:00Z"
            else:
                # 01:30 + (i - n_stale)*30 min — all after 01:00.
                base_min = 90 + (i - n_stale) * 30
                hh, mm = divmod(base_min, 60)
                start = f"2026-09-03T{hh:02d}:{mm:02d}:00Z"
                eh, em = divmod(base_min + 30, 60)
                end = f"2026-09-03T{eh:02d}:{em:02d}:00Z"
            create_slot(provider["id"], start, end)
        return provider

    def test_one_stale_of_twenty_is_clean_but_findings_open(self, api):
        """PRD §3.11: "Severity follows with strict thresholds: `severity` is `CRITICAL` when the mismatch rate is strictly greater than 0.20, `WARN` when strictly greater than 0.05, and `CLEAN` otherwise. With a full sample of 20 items, one mismatch is a rate of 0.05 and `CLEAN`; two is 0.10 and `WARN`; four is 0.20 and still `WARN`; five is 0.25 and `CRITICAL`."
        PRD §3.11: "When the run finds zero mismatches the case moves directly from `OPEN` to terminal `CLOSED_CLEAN`; otherwise it moves from `OPEN` to `FINDINGS_OPEN`."

        Design: Corner/calculations/audit_severity_threshold_boundaries
        """
        practice = create_and_activate_practice()
        provider = self._provider_with_n_stale_slots(practice, n_stale=1)
        set_clock("2026-09-03T01:00:00Z")
        resp = api_client.create_audit_case(
            {"provider_id": provider["id"], "scope": "AVAILABILITY"}, TEST_USERS["ops_admin_headers"]
        )
        case = validate_success(resp, 201)
        resp = api_client.run_audit_case(case["id"], TEST_USERS["ops_admin_headers"])
        data = validate_success(resp)
        assert data["mismatch_count"] == 1
        assert data["severity"] == "CLEAN", "1/20 = 0.05 is NOT strictly > 0.05"
        assert data["status"] == "FINDINGS_OPEN"

    def test_two_stale_of_twenty_is_warn_five_is_critical(self, api):
        """PRD §3.11: "Severity follows with strict thresholds: `severity` is `CRITICAL` when the mismatch rate is strictly greater than 0.20, `WARN` when strictly greater than 0.05, and `CLEAN` otherwise. With a full sample of 20 items, one mismatch is a rate of 0.05 and `CLEAN`; two is 0.10 and `WARN`; four is 0.20 and still `WARN`; five is 0.25 and `CRITICAL`."

        Design: Corner/calculations/audit_severity_threshold_boundaries
        """
        practice = create_and_activate_practice()
        prov_x = self._provider_with_n_stale_slots(practice, n_stale=2)
        prov_y = self._provider_with_n_stale_slots(practice, n_stale=5)
        set_clock("2026-09-03T01:00:00Z")

        case_x = validate_success(
            api_client.create_audit_case(
                {"provider_id": prov_x["id"], "scope": "AVAILABILITY"}, TEST_USERS["ops_admin_headers"]
            ), 201
        )
        run_x = validate_success(api_client.run_audit_case(case_x["id"], TEST_USERS["ops_admin_headers"]))
        assert run_x["mismatch_count"] == 2
        assert run_x["severity"] == "WARN"

        case_y = validate_success(
            api_client.create_audit_case(
                {"provider_id": prov_y["id"], "scope": "AVAILABILITY"}, TEST_USERS["ops_admin_headers"]
            ), 201
        )
        run_y = validate_success(api_client.run_audit_case(case_y["id"], TEST_USERS["ops_admin_headers"]))
        assert run_y["mismatch_count"] == 5
        assert run_y["severity"] == "CRITICAL"


class TestAuditCloseWithUnresolvedFindings:
    def _setup_findings_open_case(self):
        ctx = setup_bookable_practice(
            slot_windows=[("2026-09-03T10:00:00Z", "2026-09-03T10:30:00Z")]
        )
        set_clock("2026-09-04T00:00:00Z")
        case = validate_success(
            api_client.create_audit_case(
                {"provider_id": ctx["provider"]["id"], "scope": "AVAILABILITY"},
                TEST_USERS["ops_admin_headers"],
            ), 201
        )
        run = validate_success(api_client.run_audit_case(case["id"], TEST_USERS["ops_admin_headers"]))
        assert run["status"] == "FINDINGS_OPEN"
        return ctx, case

    def test_close_with_unresolved_findings_rejected(self, api):
        """PRD §3.11: "Only when every finding is resolved may the operator close the case — `FINDINGS_OPEN` to terminal `CLOSED`; closing with any unresolved finding is rejected with `ERR_UNRESOLVED_FINDINGS`."

        Design: Corner/state_machines/audit_close_with_unresolved_findings_rejected
        """
        ctx, case = self._setup_findings_open_case()
        resp = api_client.close_audit_case(case["id"], TEST_USERS["ops_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_FINDINGS)

    def test_close_succeeds_after_all_findings_resolved(self, api):
        """PRD §3.11: "Only when every finding is resolved may the operator close the case — `FINDINGS_OPEN` to terminal `CLOSED`; closing with any unresolved finding is rejected with `ERR_UNRESOLVED_FINDINGS`."

        Design: Corner/state_machines/audit_close_with_unresolved_findings_rejected
        """
        ctx, case = self._setup_findings_open_case()
        api_client.resolve_finding(
            case["id"],
            {"finding_index": 0, "resolution_note": "slot closed by sweep"},
            TEST_USERS["ops_admin_headers"],
        )
        resp = api_client.close_audit_case(case["id"], TEST_USERS["ops_admin_headers"])
        data = validate_success(resp)
        assert data["status"] == "CLOSED"


class TestProvidersListPaginationEnvelope:
    def test_list_carries_pagination_fields_and_filter_narrows_total(self, api):
        """PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints."
        PRD §2.3: "List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100."

        Design: Corner/entities/providers_list_pagination_envelope
        """
        practice = create_and_activate_practice()
        prov_a = activate_provider(create_provider(practice["id"], display_name="Dr A", specialty="DERM")["id"])
        prov_b = activate_provider(create_provider(practice["id"], display_name="Dr B", specialty="CARD")["id"])
        resp = api_client.list_providers(
            TEST_USERS["ops_admin_headers"], params={"specialty": "DERM", "limit": 10, "offset": 0}
        )
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0

    def test_unfiltered_list_total_count(self, api):
        """PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints."

        Design: Corner/entities/providers_list_pagination_envelope
        """
        practice = create_and_activate_practice()
        activate_provider(create_provider(practice["id"], display_name="Dr A", specialty="DERM")["id"])
        activate_provider(create_provider(practice["id"], display_name="Dr B", specialty="CARD")["id"])
        resp = api_client.list_providers(TEST_USERS["ops_admin_headers"])
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2
