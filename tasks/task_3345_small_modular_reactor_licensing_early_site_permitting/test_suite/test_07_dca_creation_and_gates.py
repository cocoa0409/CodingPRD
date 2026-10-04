"""DCA creation contract: the response envelope and computed EPZ fields,
required-field validation, unknown-resource 404s, docket uniqueness, the
escalation range gate, and SAR listing reachability."""

from test_helpers import (
    ApiErrorId,
    APPLICANT,
    DOE,
    NON_EXISTENT_UUID,
    assert_dca,
    assert_sar,
    create_cost_share_agreement,
    create_dca,
    create_sar,
    dca_payload,
    escalate_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestDcaCreation:
    """A filing is born SUBMITTED with its EPZ variants computed immediately."""

    def test_create_returns_envelope_and_computed_epz(self, api):
        """PRD §4: "Operations that create a new resource return `201
        Created`; operations that modify an existing resource — including
        every state-transition action — return `200 OK`."
        PRD §3.1: "Filing immediately triggers emergency-planning-zone
        sizing, and the same calculation re-runs whenever the applicant later
        amends `source_term_fraction` or `site_boundary_miles` — an amendment
        permitted only while the application is `SUBMITTED` or
        `SAFETY_REVIEW`."

        Design: Corner/entities/dca_create_success_returns_envelope_and_computed_epz
        """
        created = validate_success(
            api.create_dca(
                dca_payload(
                    docket_number="52-900",
                    reactor_model="SMR-77",
                    target_power_mwt=250,
                    plant_net_capacity_mw=77,
                    source_term_fraction=0.10,
                    site_boundary_miles=0.25,
                ),
                APPLICANT,
            ),
            201,
        )
        assert_dca(created)
        assert created["status"] == "SUBMITTED"
        # deterministic: 10.0 * 0.10 = 1.00
        assert created["epz_radius_deterministic_miles"] == 1.00
        # dose-based: 2*sqrt(0.25) + 5*0.9 = 1.0 + 4.5 = 5.50
        assert created["epz_radius_dose_based_miles"] == 5.50
        assert created["epz_radius_selected_miles"] == 5.50
        # A fresh resource's version starts at 1.
        assert created["version"] == 1

    def test_fresh_dca_has_zero_subscription_position(self, api):
        """PRD §3.1: "Two computed fields track the subscription position
        continuously: `subscribed_mw` is the sum of `committed_mw` over the
        application's subscription commitments whose status is `EXECUTED` or
        `LOCKED`, and `available_mw` is `plant_net_capacity_mw` minus
        `subscribed_mw`."

        Design: Corner/entities/dca_create_success_returns_envelope_and_computed_epz
        """
        dca = create_dca(api, docket_number="52-901", plant_net_capacity_mw=77)
        assert dca["subscribed_mw"] == 0
        assert dca["available_mw"] == 77
        assert dca["funding_gap_usd"] == 0


class TestDcaRequiredFields:
    """A missing required field is a 400 ERR_VALIDATION."""

    def test_missing_docket_number_rejected(self, api):
        """PRD §2.7: "A missing required field or a malformed payload is
        rejected with `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/dca_missing_required_field_returns_validation_error
        """
        payload = dca_payload(docket_number="52-902")
        del payload["docket_number"]
        resp = api.create_dca(payload, APPLICANT)
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)

    def test_missing_source_term_fraction_rejected(self, api):
        """PRD §2.7: "A missing required field or a malformed payload is
        rejected with `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/dca_missing_required_field_returns_validation_error
        """
        payload = dca_payload(docket_number="52-903")
        del payload["source_term_fraction"]
        resp = api.create_dca(payload, APPLICANT)
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)


class TestDcaNotFound:
    """An unknown identifier on retrieval is a 404 ERR_NOT_FOUND."""

    def test_get_unknown_dca_rejected(self, api):
        """PRD §2.7: "For any request whose path contains multiple resource
        identifiers — for example a vendor qualification addressed as a vendor
        plus a qualification id — the system validates the identifiers
        left-to-right, and rejects with `ERR_NOT_FOUND` (HTTP 404) at the
        first identifier that does not resolve to an existing resource."

        Design: Corner/entities/get_nonexistent_dca_returns_not_found
        """
        resp = api.get_dca(NON_EXISTENT_UUID, APPLICANT)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)

    def test_get_unknown_subscription_rejected(self, api):
        """PRD §2.7: "For any request whose path contains multiple resource
        identifiers — for example a vendor qualification addressed as a vendor
        plus a qualification id — the system validates the identifiers
        left-to-right, and rejects with `ERR_NOT_FOUND` (HTTP 404) at the
        first identifier that does not resolve to an existing resource."

        Design: Corner/entities/get_nonexistent_dca_returns_not_found
        """
        resp = api.get_subscription(NON_EXISTENT_UUID, DOE)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


class TestDocketUniqueness:
    """Two applications may never share a docket number."""

    def test_duplicate_docket_rejected(self, api):
        """PRD §3.1: "Two applications may never share a `docket_number`; a
        duplicate filing is rejected with `ERR_DUPLICATE` (HTTP 409)."

        Design: Corner/entities/duplicate_docket_number_rejected
        """
        create_dca(api, docket_number="52-901")
        resp = api.create_dca(dca_payload(docket_number="52-901"), APPLICANT)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE, 409)

    def test_distinct_docket_accepted(self, api):
        """PRD §3.1: "Two applications may never share a `docket_number`; a
        duplicate filing is rejected with `ERR_DUPLICATE` (HTTP 409)."

        Design: Corner/entities/duplicate_docket_number_rejected
        """
        create_dca(api, docket_number="52-904")
        second = validate_success(
            api.create_dca(dca_payload(docket_number="52-905"), APPLICANT), 201
        )
        assert second["docket_number"] == "52-905"


class TestSarListing:
    """The section list filters by owning application and paginates."""

    def test_sars_filtered_by_dca_id(self, api):
        """PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the response
        envelope."

        Design: Corner/entities/sars_list_filtered_by_dca_id_reverse_reachability
        """
        dca_a = create_dca(api, docket_number="52-910")
        dca_b = create_dca(api, docket_number="52-911")
        sar_a = create_sar(api, dca_a["id"], section_code="CH01")
        create_sar(api, dca_b["id"], section_code="CH01")

        data, meta = validate_paginated(api.list_sars(APPLICANT, params={"dca_id": dca_a["id"]}))
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert len(data) == 1
        assert data[0]["id"] == sar_a["id"]
        assert data[0]["dca_id"] == dca_a["id"]
        assert_sar(data[0])

    def test_sars_unfiltered_lists_both_applications(self, api):
        """PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the response
        envelope."

        Design: Corner/entities/sars_list_filtered_by_dca_id_reverse_reachability
        """
        dca_a = create_dca(api, docket_number="52-912")
        dca_b = create_dca(api, docket_number="52-913")
        create_sar(api, dca_a["id"], section_code="CH01")
        create_sar(api, dca_b["id"], section_code="CH02")

        data, meta = validate_paginated(api.list_sars(APPLICANT))
        assert meta["total_count"] == 2
        assert len(data) == 2


class TestEscalationRange:
    """The overrun must be positive and at most three times the pool."""

    def test_zero_overrun_rejected(self, api):
        """PRD §3.5: "Applying an overrun requires an `overrun_usd` amount
        that is strictly greater than zero and at most three times the
        agreement's `participant_share_usd`; anything outside that range is
        rejected with `ERR_ESCALATION_OUT_OF_RANGE` (HTTP 422)."

        Design: Corner/validations/escalate_out_of_range_rejected
        """
        dca = create_dca(api, docket_number="52-942")
        csa = create_cost_share_agreement(api, dca["id"], 1000, 0)
        resp = api.escalate_cost_share(csa["id"], escalate_payload(0), DOE)
        validate_error(resp, ApiErrorId.ERR_ESCALATION_OUT_OF_RANGE, 422)

    def test_overrun_above_triple_share_rejected(self, api):
        """PRD §3.5: "Applying an overrun requires an `overrun_usd` amount
        that is strictly greater than zero and at most three times the
        agreement's `participant_share_usd`; anything outside that range is
        rejected with `ERR_ESCALATION_OUT_OF_RANGE` (HTTP 422)."

        Design: Corner/validations/escalate_out_of_range_rejected
        """
        dca = create_dca(api, docket_number="52-946")
        csa = create_cost_share_agreement(api, dca["id"], 1000, 0)
        # participant_share is 1000; 4000 exceeds three times the pool.
        resp = api.escalate_cost_share(csa["id"], escalate_payload(4000), DOE)
        validate_error(resp, ApiErrorId.ERR_ESCALATION_OUT_OF_RANGE, 422)
