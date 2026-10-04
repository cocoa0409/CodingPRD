"""Identity headers, role permissions, path/FK resolution, envelope shape."""
from test_helpers import (
    TEST_USERS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_market,
    create_market_payload,
    create_patient,
    create_patient_payload,
    create_payer_contract_payload,
    create_visit_request_payload,
    get_success_data,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
NURSE = TEST_USERS["triage_nurse_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


class TestUserContextAndPermissions:
    def test_missing_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying a malformed
        value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."

        Design: Corner/validations/missing_user_context_header_returns_400
        """
        set_clock("2026-09-01T00:00:00Z")
        resp = api._request(
            "GET", "/dh/markets", headers={"Content-Type": "application/json"}
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_wrong_role_on_contract_create_rejected(self, api):
        """PRD §2.1: "Once identity is established, the role is checked against
        the endpoint's authorization matrix; a role not permitted on the
        endpoint receives `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: the `POST /dh/payer-contracts` row authorizes `PlatformAdmin`
        only.

        Design: Corner/validations/insufficient_permissions_returns_403
        """
        set_clock("2026-09-01T00:00:00Z")
        market = get_success_data(
            api.create_market(create_market_payload(), ADMIN)
        )
        resp = api.create_payer_contract(
            create_payer_contract_payload(market["id"]), NURSE
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestExistenceAndFkResolution:
    def test_get_market_unknown_id_returns_not_found(self, api):
        """PRD §2.7: "Endpoints that address nested resources validate path
        identifiers left to right. A request whose path carries a parent id
        and a child id is rejected with `ERR_NOT_FOUND` (HTTP 404) at the
        first identifier — scanning left to right — that does not resolve to
        an existing resource".

        Design: Corner/entities/market_get_unknown_id_returns_not_found
        """
        set_clock("2026-09-01T00:00:00Z")
        resp = api.get_market(NON_EXISTENT_UUID, DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_formulary_entry_under_unknown_contract_returns_not_found(self, api):
        """PRD §2.7: "A request whose path carries a parent id and a child id
        is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier —
        scanning left to right — that does not resolve to an existing
        resource; the system does not continue to deeper path segments once an
        earlier segment has failed."

        Design: Corner/entities/formulary_entry_requires_valid_parent_contract
        """
        set_clock("2026-09-01T00:00:00Z")
        resp = api.create_formulary_entry(
            NON_EXISTENT_UUID,
            {
                "drug_code": "IVF-NS-1L", "max_units_per_visit": 3,
                "requires_physician_preauth": False, "unit_price_cents": 3000,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestMarketCreateAndPagination:
    def test_market_create_defaults_and_system_fields(self, api):
        """PRD §3.1: "The `is_active` flag, defaulting to true, controls
        whether the market accepts new visit requests and new dispatch
        offers".
        PRD §3.1: "Each market maintains a computed `open_visit_count` — the
        number of its visit requests currently in any non-terminal status ...
        which rises by one at intake".
        PRD §2.5: "`version` (integer): a system-managed integer starting at 1
        that increments on every mutation".
        PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."

        Design: Corner/entities/market_create_returns_system_fields_and_default_active
        """
        set_clock("2026-09-01T00:00:00Z")
        resp = api.create_market(
            create_market_payload(market_code="ATL-NE", display_name="Atlanta NE"),
            ADMIN,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        market = body["data"]
        assert market["is_active"] is True
        assert market["open_visit_count"] == 0
        assert market["version"] == 1

    def test_markets_list_pagination_meta(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10, accepts a minimum of 1, and rejects values above
        100. The `offset` parameter skips a number of items from the front of
        the result set and defaults to 0... Paginated list responses include
        `limit`, `offset`, `total_count`, and `has_more` in the `meta` object
        of the envelope."

        Design: Corner/entities/markets_list_paginates_with_total_count_and_has_more
        """
        set_clock("2026-09-01T00:00:00Z")
        for code in ("M1", "M2", "M3"):
            get_success_data(
                api.create_market(
                    create_market_payload(
                        market_code=code, display_name=code, polygon_geojson="{}"
                    ),
                    ADMIN,
                )
            )
        rows, meta = validate_paginated(
            api.list_markets(DISPATCHER, params={"limit": 2, "offset": 0})
        )
        assert len(rows) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        rows2, meta2 = validate_paginated(
            api.list_markets(DISPATCHER, params={"limit": 2, "offset": 2})
        )
        assert len(rows2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestPatientRoundTripAndDefaults:
    def test_patient_get_returns_stored_fields(self, api):
        """PRD §2.2: "operations that create or modify a resource will return
        the created or updated resource object in the data field."
        PRD §3.2: "A **Patient** is registered by a `PlatformAdmin` or a
        `TriageNurse` with a `full_name`, a `date_of_birth` given as an
        ISO 8601 calendar date, the `payer_code` printed on the insurance card
        together with the `member_id` under that payer, the primary care
        physician's `pcp_name` and ten-digit `pcp_npi`".

        Design: Corner/entities/patient_get_returns_stored_fields_unchanged
        """
        set_clock("2026-09-01T00:00:00Z")
        patient = get_success_data(
            api.create_patient(
                create_patient_payload(
                    full_name="Quentin Q", date_of_birth="1975-11-30",
                    payer_code="BCBS-TX", member_id="M2000",
                    pcp_name="Dr. W", pcp_npi="1231231234",
                    comorbidity_count=4,
                ),
                NURSE,
            )
        )
        fetched = validate_success(api.get_patient(patient["id"], NURSE))
        assert fetched["full_name"] == "Quentin Q"
        assert fetched["payer_code"] == "BCBS-TX"
        assert fetched["comorbidity_count"] == 4
        assert fetched["pcp_npi"] == "1231231234"

    def test_patient_comorbidity_count_defaults_to_zero(self, api):
        """PRD §3.2: "a `comorbidity_count` of documented chronic conditions
        (defaulting to zero and feeding acuity scoring)".

        Design: Corner/entities/patient_create_omitting_comorbidity_count_defaults_to_zero
        """
        set_clock("2026-09-01T00:00:00Z")
        payload = create_patient_payload(
            full_name="Sam S", member_id="M3001", pcp_npi="9999999992"
        )
        payload.pop("comorbidity_count")
        resp = api.create_patient(payload, NURSE)
        assert resp.status_code == 201
        assert resp.json()["data"]["comorbidity_count"] == 0


class TestVisitIntakeValidation:
    def test_missing_chief_complaint_rejected(self, api):
        """PRD §3.2: "The payload carries the `patient_id`, the chosen
        `market_id`, a `requestor_role` drawn from `PATIENT`, `PAYER`,
        `PROVIDER`, or `FACILITY` recording which channel originated the call,
        and a free-text `chief_complaint`."
        PRD §3.3: "Vital values outside their accepted ranges, like any other
        field-shape violation, are rejected with `ERR_INVALID_REQUEST`
        (HTTP 400)."

        Design: Corner/entities/visit_request_create_missing_chief_complaint_returns_invalid_request
        """
        set_clock("2026-09-01T00:00:00Z")
        market = create_market()
        patient = create_patient(
            full_name="Rita R", member_id="M3000", pcp_npi="9999999991"
        )
        resp = api.create_visit_request(
            {
                "patient_id": patient["id"], "market_id": market["id"],
                "requestor_role": "PATIENT",
            },
            NURSE,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        visits = validate_success(
            api.list_patient_visit_requests(patient["id"], NURSE)
        )
        assert visits == []

    def test_unknown_requestor_role_rejected(self, api):
        """PRD §3.2: "a `requestor_role` drawn from `PATIENT`, `PAYER`,
        `PROVIDER`, or `FACILITY`".
        PRD §3.3: "like any other field-shape violation, are rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/requestor_role_enum_rejection
        """
        set_clock("2026-09-01T00:00:00Z")
        market = get_success_data(
            api.create_market(
                create_market_payload(polygon_geojson="{}"), ADMIN
            )
        )
        patient = create_patient(
            full_name="Uma U", member_id="M5000", pcp_npi="9999999994"
        )
        resp = api.create_visit_request(
            {
                "patient_id": patient["id"], "market_id": market["id"],
                "requestor_role": "CAREGIVER", "chief_complaint": "headache",
            },
            NURSE,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_computed_fields_unset_at_intake(self, api):
        """PRD §3.2: "the visit carries a computed `acuity_band` (one of
        `EMERGENT`, `URGENT`, `STANDARD`, `NON_ACUTE`, derived from the latest
        triage assessment), ... a computed `sla_deadline_at` that stays null
        until a dispatch is accepted, a computed `sla_breached` flag latched
        false at creation, and a computed `claim_id` that stays null until a
        claim exists."

        Design: Corner/entities/visit_request_acuity_band_computed_at_triage_submit
        """
        set_clock("2026-09-01T00:00:00Z")
        market = create_market()
        patient = create_patient(
            full_name="Tess T", member_id="M4000", pcp_npi="9999999993",
            comorbidity_count=0,
        )
        vr = validate_success(
            api.create_visit_request(
                create_visit_request_payload(
                    patient["id"], market["id"], chief_complaint="stub toe"
                ),
                NURSE,
            ),
            expected_status=201,
        )
        assert vr["status"] == "INTAKE"
        assert vr.get("acuity_band") is None
        assert vr.get("sla_deadline_at") is None
        assert vr["sla_breached"] is False


class TestVisitListFiltering:
    def test_status_filter_scopes_total_count(self, api):
        """PRD §3.2: "Visit-request lists support filtering by `patient_id`,
        `market_id`, `status`, `acuity_band`, `assigned_care_team_id`, and
        `claim_id`."
        PRD §2.3: "Paginated list responses include `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/endpoints/list_endpoints_support_filter_and_pagination
        """
        from test_helpers import RED_FLAG_VITALS, create_triage_assessment_payload

        set_clock("2026-09-15T10:00:00Z")
        market = create_market()
        patient = create_patient(
            full_name="Guy G", member_id="M17000", pcp_npi="6666666668",
            comorbidity_count=0,
        )
        for complaint in ("v1", "v2"):
            get_success_data(
                api.create_visit_request(
                    create_visit_request_payload(
                        patient["id"], market["id"], chief_complaint=complaint
                    ),
                    NURSE,
                )
            )
        vr3 = get_success_data(
            api.create_visit_request(
                create_visit_request_payload(
                    patient["id"], market["id"],
                    chief_complaint="crushing chest pain",
                ),
                NURSE,
            )
        )
        trg3 = get_success_data(
            api.create_triage_assessment(
                vr3["id"], create_triage_assessment_payload(**RED_FLAG_VITALS), NURSE
            )
        )
        get_success_data(
            api.submit_triage_assessment(
                trg3["id"], {"outcome": "EMERGENCY_DIVERTED"}, NURSE
            )
        )
        rows, meta = validate_paginated(
            api.list_visit_requests(
                DISPATCHER, params={"status": "INTAKE", "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert all(r["status"] == "INTAKE" for r in rows)


class TestOccStaleVersion:
    def test_stale_expected_version_rejected_on_dispatch_offer(self, api):
        """PRD §2.9: "The request must carry
        `expected_visit_request_version`; a mismatch against the visit's
        current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)
        before any selection runs."
        PRD §2.5: "`version` (integer): a system-managed integer starting at 1
        that increments on every mutation".

        Design: Corner/validations/occ_stale_version_on_dispatch_offer
        """
        from test_helpers import setup_market_team_shift

        ctx = setup_market_team_shift(app_user="app-C", tech_user="tech-C")
        patient = create_patient(
            full_name="Cat C", member_id="M13000", pcp_npi="3333333334"
        )
        vr = get_success_data(
            api.create_visit_request(
                create_visit_request_payload(patient["id"], ctx["market"]["id"]),
                NURSE,
            )
        )
        stale_version = vr["version"]
        # An intervening visit mutation (triage creation moves INTAKE ->
        # TRIAGE_PENDING) increments the visit's version.
        from test_helpers import create_triage_assessment_payload

        get_success_data(
            api.create_triage_assessment(
                vr["id"], create_triage_assessment_payload(), NURSE
            )
        )
        resp = api.create_dispatch_offer(
            vr["id"],
            {"expected_visit_request_version": stale_version},
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        vr_after = validate_success(api.get_visit_request(vr["id"], DISPATCHER))
        assert vr_after["status"] == "TRIAGE_PENDING"
