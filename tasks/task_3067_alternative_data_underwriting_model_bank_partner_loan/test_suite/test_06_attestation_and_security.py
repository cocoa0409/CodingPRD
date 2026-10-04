"""Performance attestations, applicant registration validation, platform
security (authentication and role authorization), and listing behavior."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_loan_periods,
    attach_active_credit_box,
    create_active_model,
    create_applicant,
    create_applicant_payload,
    create_attestation_payload,
    create_credit_box_payload,
    create_partner,
    find_loan_for_application,
    get_success_data,
    pass_all_instant_checks,
    setup_funded_loan,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPerformanceAttestation:

    def _partner_with_one_charged_off_loan(self, api, headers):
        """A bank partner holding two funded loans, the first charged off."""
        from test_helpers import (
            create_active_model,
            create_applicant,
            create_partner,
            pass_all_instant_checks,
            submit_application,
        )

        model = create_active_model(model_code="ADU-C-4")
        bank = create_partner(
            legal_name="Attest Bank",
            activator=TEST_USERS["partner_admin_nine_headers"],
        )
        attach_active_credit_box(bank["id"])

        loans = []
        for name in ("Attest One", "Attest Two"):
            applicant = create_applicant(full_name=name)
            app = pass_all_instant_checks(submit_application(applicant["id"])["id"])
            decision = validate_success(
                api.allocate_application(app["id"], TEST_USERS["platform_admin_headers"])
            )
            assert decision["channel"] == "PARTNER_RETAINED"
            loans.append(find_loan_for_application(app["id"]))

        loan1 = advance_loan_periods(loans[0]["id"], 4)
        assert loan1["status"] == "DEFAULTED"
        validate_success(
            api.charge_off_loan(loan1["id"], TEST_USERS["collections_agent_headers"])
        )
        return model, bank

    def test_attestation_computes_expected_actual_variance_bps(
        self, api, risk_officer_attester_headers
    ):
        """PRD 3.2: "The `actual_default_rate_bps` is the charged-off share of the partner's book: the count of the partner's held loans in `CHARGED_OFF`, divided by the count of all loans the partner has ever held (every loan that ever reached `FUNDED` with this holder), scaled to basis points and rounded half up"
        PRD 3.2: "The `expected_default_rate_bps` starts from a base of 500 basis points and is adjusted upward by 10 basis points for each point by which the partner's held-book average risk score falls below 550, floored at zero"
        PRD 3.2: "The `variance_bps` is the actual rate minus the expected rate, signed."
        PRD 3.2: "records the issuing officer's identity in `attested_by_user_id`"

        Design: Corner/calculations/attestation_computes_expected_actual_variance_bps
        """
        model, bank = self._partner_with_one_charged_off_loan(api, risk_officer_attester_headers)

        resp = api.create_attestation(
            model["id"],
            create_attestation_payload(bank["id"], period_label="2026-09"),
            risk_officer_attester_headers,
        )
        attestation = validate_success(resp, expected_status=201)
        # 1 charged off of 2 ever funded -> round_half_up(10000 * 1/2) == 5000.
        assert attestation["actual_default_rate_bps"] == 5000
        # Held-book average score 300 -> 500 + 10 * (550 - 300) == 3000.
        assert attestation["expected_default_rate_bps"] == 3000
        assert attestation["variance_bps"] == 2000
        assert attestation["attested_by_user_id"] == "ro-attester"

    def test_attestation_variance_is_signed_difference(
        self, api, risk_officer_attester_headers
    ):
        """PRD 3.2: "The `variance_bps` is the actual rate minus the expected rate, signed."

        Design: Corner/calculations/attestation_computes_expected_actual_variance_bps
        """
        model, bank = self._partner_with_one_charged_off_loan(api, risk_officer_attester_headers)

        resp = api.create_attestation(
            model["id"],
            create_attestation_payload(bank["id"], period_label="2026-09"),
            risk_officer_attester_headers,
        )
        attestation = validate_success(resp, expected_status=201)
        assert attestation["variance_bps"] == (
            attestation["actual_default_rate_bps"] - attestation["expected_default_rate_bps"]
        )


class TestApplicantValidation:

    def test_invalid_education_level_enum_returns_invalid_request(
        self, api, platform_admin_headers, auditor_headers
    ):
        """PRD 3.4: "`education_level` (one of `HIGH_SCHOOL`, `ASSOCIATE`, `BACHELOR`, `MASTER`, or `DOCTORATE`)"
        PRD 5: "`ERR_INVALID_REQUEST` | 400"

        Design: Corner/entities/applicant_create_with_invalid_education_level_enum_returns_invalid_request
        """
        resp = api.create_applicant(
            create_applicant_payload(full_name="Enum Erin", education_level="PHD"),
            platform_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        data, meta = validate_paginated(api.list_applicants(auditor_headers))
        assert meta["total_count"] == 0


class TestAuthentication:

    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD 2.1: "If either header is missing or malformed, or the role is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD 2.9: "Authentication (`ERR_UNAUTHENTICATED`) comes first, then role authorization (`ERR_FORBIDDEN`), then path-identifier existence (`ERR_NOT_FOUND`)"

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        # Unknown partner id AND no auth headers: authentication dominates.
        resp = api.get_partner("00000000-0000-4000-8000-000000000033", headers={})
        err = validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
        assert err["error_id"] != ApiErrorId.ERR_NOT_FOUND.value

    def test_unrecognized_role_returns_unauthenticated(self, api):
        """PRD 2.1: "If either header is missing or malformed, or the role is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        resp = api.get_partner(
            "00000000-0000-4000-8000-000000000033",
            headers={"X-User-ID": "mystery-1", "X-User-Role": "SuperUser"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRbac:

    def test_servicing_agent_cannot_activate_credit_box(
        self, api, partner_admin_headers, servicing_agent_headers
    ):
        """PRD 4: "POST | `/platform/partners/{id}/credit-boxes/{boxId}/activate` | Activate a DRAFT credit box (OCC on partner version) | PartnerAdmin"
        PRD 2.1: "If the role is recognized but not permitted to call the endpoint, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/roles_rbac/servicing_agent_cannot_activate_credit_box
        """
        partner = create_partner(legal_name="RBAC Bank")
        resp = api.create_credit_box(
            partner["id"], create_credit_box_payload(), partner_admin_headers
        )
        box = validate_success(resp, expected_status=201)
        partner = get_success_data(api.get_partner(partner["id"], partner_admin_headers))
        version_before = partner["version"]

        resp = api.activate_credit_box(
            partner["id"], box["id"],
            {"expected_partner_version": version_before},
            servicing_agent_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        box = get_success_data(api.get_credit_box(box["id"], partner_admin_headers))
        assert box["status"] == "DRAFT"
        partner = get_success_data(api.get_partner(partner["id"], partner_admin_headers))
        assert partner["version"] == version_before

    def test_auditor_read_only_can_get_but_not_post(
        self, api, partner_admin_headers, auditor_headers
    ):
        """PRD 2.1: "An `Auditor` has read-only oversight with access to all read endpoints and no write capability."
        PRD 2.1: "If the role is recognized but not permitted to call the endpoint, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/roles_rbac/auditor_read_only_can_get_but_not_post
        """
        partner = create_partner(legal_name="Audit Bank", activated=False)

        resp = api.get_partner(partner["id"], auditor_headers)
        data = validate_success(resp, expected_status=200)
        assert data["legal_name"] == "Audit Bank"

        resp = api.create_partner(
            {"legal_name": "Audit Bank 2", "partner_type": "BANK", "home_state": "TX"},
            auditor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        data, meta = validate_paginated(api.list_partners(auditor_headers))
        assert meta["total_count"] == 1

    def test_verification_officer_cannot_post_payments(
        self, api, verification_officer_headers, servicing_agent_headers
    ):
        """PRD 4: "POST | `/platform/loans/{id}/payments` | Post a payment through the waterfall (OCC on loan version) | ServicingAgent"
        PRD 2.1: "If the role is recognized but not permitted to call the endpoint, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD 2.9: "Authentication (`ERR_UNAUTHENTICATED`) comes first, then role authorization (`ERR_FORBIDDEN`), then path-identifier existence (`ERR_NOT_FOUND`)"

        Design: Corner/roles_rbac/verification_officer_cannot_post_payments
        """
        bundle = setup_funded_loan()
        loan = bundle["loan"]

        resp = api.post_payment(
            loan["id"],
            {"amount_cents": 166072, "expected_loan_version": loan["version"]},
            verification_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        loan = get_success_data(api.get_loan(loan["id"], servicing_agent_headers))
        assert loan["version"] == bundle["loan"]["version"]
        assert loan["outstanding_principal_cents"] == 5000000


class TestApplicationListing:

    def test_applications_list_paginates_total_count_and_has_more(
        self, api, platform_admin_headers, auditor_headers
    ):
        """PRD 2.3: "The `limit` parameter caps the number of returned items; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0."
        PRD 2.3: "Paginated responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/applications_list_paginates_total_count_and_has_more
        """
        create_active_model(model_code="ADU-E-2")
        for name in ("List One", "List Two", "List Three"):
            applicant = create_applicant(full_name=name)
            submit_application(applicant["id"])

        data, meta = validate_paginated(
            api.list_applications(auditor_headers, params={"limit": 2, "offset": 0})
        )
        assert len(data) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

        data, meta = validate_paginated(
            api.list_applications(auditor_headers, params={"limit": 2, "offset": 2})
        )
        assert len(data) == 1
        assert meta["total_count"] == 3
        assert meta["has_more"] is False

        data, meta = validate_paginated(api.list_applications(auditor_headers))
        assert len(data) == 3

        data, meta = validate_paginated(
            api.list_applications(auditor_headers, params={"status": "VERIFICATION_PENDING"})
        )
        assert len(data) == 3
        assert meta["total_count"] == 3
