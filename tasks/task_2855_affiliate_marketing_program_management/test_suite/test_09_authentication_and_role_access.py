"""Who may call what: authentication, role exclusivity, duty separation and ownership."""

import pytest
from prd_bench_local_runner.testing import NON_EXISTENT_UUID

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_AFFILIATE_NOT_FOUND,
    ERR_NOT_RESOURCE_OWNER,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import (
    assert_created,
    assert_error_response,
    assert_field,
    assert_fields,
    assert_list_response,
    assert_object_response,
    assert_one_decimal_score,
    assert_pagination_meta,
    assert_total_count,
)
from test_helpers.fixtures import (
    create_network,
    file_application,
    open_case,
    pin_clock,
)
from test_helpers.test_users import (
    ANONYMOUS,
    COMPLIANCE_ANALYST,
    COMPLIANCE_ANALYST_ID,
    FINANCE_ANALYST,
    FINANCE_CONTROLLER,
    NO_USER_ID_PROGRAM_ADMIN,
    PARTNER_MANAGER,
    PROGRAM_ADMIN,
    SECOND_COMPLIANCE_ANALYST,
    make_affiliate_partner_headers,
)

CLOCK = f.JUL_05_00_00


class TestAnonymousRouteAndUnauthenticatedRejection:
    def test_partner_self_registration_is_served_without_any_credentials(self, api):
        """A publisher registers itself with no acting user on the request at all.

        PRD §3.1: "Publisher partners register themselves, and this is the one place in
        the API where an unauthenticated caller is served — a `ProgramAdmin` or
        `PartnerManager` may also register a partner on the publisher's behalf."

        Design: Corner/rbac/anonymous_registration_allowed_but_all_other_routes_return_unauthenticated
        """
        pin_clock(api, CLOCK)
        network = create_network(api)

        created = assert_created(
            api.create_affiliate(
                {
                    "legal_name": "Walk In Media LLC",
                    "contact_email": "walkin@example.com",
                    "partner_type": "CONTENT",
                    "network_id": network["id"],
                    "payout_currency": "USD",
                },
                ANONYMOUS,
            )
        )

        # §3.1: "A freshly registered partner starts life in `status`
        # `PENDING_APPLICATION` with `suspension_cause` `NONE`."
        assert_fields(
            created,
            {
                "legal_name": "Walk In Media LLC",
                "status": "PENDING_APPLICATION",
                "suspension_cause": "NONE",
                "version": 1,
            },
        )

    @pytest.mark.parametrize(
        "operation",
        [
            pytest.param(
                lambda api, affiliate_id: api.get_affiliate(affiliate_id, ANONYMOUS),
                id="read_one_partner",
            ),
            pytest.param(
                lambda api, affiliate_id: api.create_network(
                    f.network_payload(name="Ghost Network"), ANONYMOUS
                ),
                id="register_a_network",
            ),
            pytest.param(
                lambda api, affiliate_id: api.list_payout_lines(
                    ANONYMOUS, {"limit": 10, "offset": 0}
                ),
                id="list_payout_lines",
            ),
            pytest.param(
                lambda api, affiliate_id: api.list_affiliates(
                    ANONYMOUS, {"limit": 10, "offset": 0}
                ),
                id="list_partners",
            ),
            pytest.param(
                lambda api, affiliate_id: api.create_network(
                    f.network_payload(name="Ghost Network"), NO_USER_ID_PROGRAM_ADMIN
                ),
                id="omitted_user_id_under_an_authenticated_role",
            ),
        ],
    )
    def test_every_other_route_rejects_the_unauthenticated_caller(self, api, operation):
        """Only self-registration is reachable without credentials; every other route 401s.

        PRD §2.1: "A request that omits `X-User-ID`, or supplies one that names no known
        user, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The single exception is
        partner self-registration, which is deliberately reachable without credentials;
        every other route in the API requires authentication."

        Design: Corner/rbac/anonymous_registration_allowed_but_all_other_routes_return_unauthenticated
        """
        pin_clock(api, CLOCK)
        network = create_network(api)
        partner = assert_created(
            api.create_affiliate(
                f.affiliate_payload(network["id"], partner_type="CONTENT"), ANONYMOUS
            )
        )

        response = operation(api, partner["id"])

        assert_error_response(response, ERR_UNAUTHENTICATED, 401)

    def test_unauthenticated_read_of_unknown_partner_id_answers_unauthenticated(self, api):
        """A header-less read of a partner id that names nothing still answers 401, not 404.

        PRD §2.10 rule 1: "`X-User-ID` is present and names a known user — otherwise
        `ERR_UNAUTHENTICATED` (401). Applies to every route except partner
        self-registration, which is the only anonymous route."

        Design: Corner/rbac/anonymous_registration_allowed_but_all_other_routes_return_unauthenticated
        """
        pin_clock(api, CLOCK)

        response = api.get_affiliate(NON_EXISTENT_UUID, ANONYMOUS)

        # §2.10: "Rules are evaluated in strictly ascending order of the numbers below,
        # and the **first** rule whose condition fails decides the response" — rule 1
        # outranks the rule 3 `ERR_AFFILIATE_NOT_FOUND`.
        assert_error_response(response, ERR_UNAUTHENTICATED, 401)


def _submitted_application(api):
    """Clock, network, a `PENDING_APPLICATION` partner and one `SUBMITTED` application."""
    pin_clock(api, CLOCK)
    network = create_network(api)
    partner = assert_created(
        api.create_affiliate(
            f.affiliate_payload(network["id"], partner_type="CONTENT"), ANONYMOUS
        )
    )
    application = file_application(api, partner["id"])
    return {
        "network_id": network["id"],
        "affiliate_id": partner["id"],
        "affiliate_version": partner["version"],
        "application_id": application["id"],
    }


def _assert_application_untouched(api, context):
    application = assert_object_response(
        api.get_application(context["application_id"], PROGRAM_ADMIN)
    )
    assert_fields(
        application,
        {
            "review_state": "SUBMITTED",
            "screening_outcome": "NOT_SCREENED",
            "version": 1,
        },
    )


def _assert_no_monitoring_scan(api, context):
    assert_total_count(
        api.list_monitoring_scans(
            context["affiliate_id"], COMPLIANCE_ANALYST, {"limit": 10, "offset": 0}
        ),
        0,
    )


def _assert_no_payout_batch(api, context):
    assert_total_count(
        api.list_payout_batches(FINANCE_ANALYST, {"limit": 10, "offset": 0}), 0
    )


class TestRoleExclusiveOperations:
    @pytest.mark.parametrize(
        "operation,verify_nothing_persisted",
        [
            pytest.param(
                lambda api, context: api.screen_application(
                    context["application_id"], f.screen_payload(), PARTNER_MANAGER
                ),
                _assert_application_untouched,
                id="screening_is_refused_to_a_partner_manager",
            ),
            pytest.param(
                # §2.10: "a request that violates three rules at once must answer with
                # the lowest-numbered one" — rule 2 outranks the rule 19
                # `ERR_APPLICATION_NOT_SCREENED` this `SUBMITTED` application would raise.
                lambda api, context: api.decide_application(
                    context["application_id"],
                    f.decide_payload("APPROVE", context["affiliate_version"]),
                    COMPLIANCE_ANALYST,
                ),
                _assert_application_untouched,
                id="deciding_is_refused_to_a_compliance_analyst",
            ),
            pytest.param(
                lambda api, context: api.create_monitoring_scan(
                    f.monitoring_scan_payload(context["affiliate_id"]), PARTNER_MANAGER
                ),
                _assert_no_monitoring_scan,
                id="recording_a_scan_is_refused_to_a_partner_manager",
            ),
            pytest.param(
                lambda api, context: api.create_payout_batch(
                    f.payout_batch_payload(context["network_id"]), FINANCE_CONTROLLER
                ),
                _assert_no_payout_batch,
                id="generating_a_batch_is_refused_to_a_finance_controller",
            ),
        ],
    )
    def test_one_roles_exclusive_operation_refuses_every_other_role(
        self, api, operation, verify_nothing_persisted
    ):
        """Screening, deciding, scanning and batch generation each refuse a foreign role.

        PRD §2.1: "A caller whose `X-User-Role` is absent from the operation's role list
        is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/role_cannot_perform_another_roles_exclusive_operation
        """
        context = _submitted_application(api)

        response = operation(api, context)

        assert_error_response(response, ERR_UNAUTHORIZED, 403)
        verify_nothing_persisted(api, context)

    def test_wrong_role_approving_an_unknown_batch_answers_unauthorized(self, api):
        """A finance analyst approving a batch id that names nothing learns only 403.

        PRD §2.10 rule 2: "The caller's role appears in the addressed operation's role
        list — otherwise `ERR_UNAUTHORIZED` (403). Applies to every route, and because it
        precedes every existence lookup a wrong-role caller cannot probe which
        identifiers exist."

        Design: Corner/rbac/role_cannot_perform_another_roles_exclusive_operation
        """
        pin_clock(api, CLOCK)

        response = api.approve_payout_batch(
            NON_EXISTENT_UUID, f.approve_batch_payload(1), FINANCE_ANALYST
        )

        assert_error_response(response, ERR_UNAUTHORIZED, 403)

    def test_the_owning_role_screens_the_identical_payload_successfully(self, api):
        """The payload a partner manager was refused succeeds for the compliance analyst.

        PRD §3.2: "Screening is exclusive to a `ComplianceAnalyst` and moves the
        application `SUBMITTED → SCREENED`."

        Design: Corner/rbac/role_cannot_perform_another_roles_exclusive_operation
        """
        context = _submitted_application(api)
        refused = api.screen_application(
            context["application_id"], f.screen_payload(), PARTNER_MANAGER
        )
        assert_error_response(refused, ERR_UNAUTHORIZED, 403)

        screened = assert_object_response(
            api.screen_application(
                context["application_id"], f.screen_payload(), COMPLIANCE_ANALYST
            )
        )

        # §3.2: "The base figure is the sum of three terms: forty-five hundredths of
        # `domain_authority`, thirty-five hundredths of `content_originality_pct`, and
        # twenty hundredths of a link-health term." — 0.45*80 + 0.35*92 + 0.20*98 = 87.8
        # under the 1.00 `ORGANIC_SEARCH` multiplier and a zero flag penalty.
        assert_one_decimal_score(screened, "site_quality_score", 87.8)
        assert_one_decimal_score(screened, "brand_suitability_score", 100.0)
        assert_fields(
            screened,
            {
                "review_state": "SCREENED",
                "screening_outcome": "PASS",
                "screened_by_user_id": COMPLIANCE_ANALYST_ID,
                "version": 2,
            },
        )


def _case_awaiting_verification(api):
    """A `FORCED_CLICK` case opened by cmp-001 and remediated by the partner itself."""
    pin_clock(api, CLOCK)
    network = create_network(api)
    partner = assert_created(
        api.create_affiliate(
            f.affiliate_payload(network["id"], partner_type="CONTENT"), ANONYMOUS
        )
    )
    case = open_case(
        api,
        partner["id"],
        violation_type="FORCED_CLICK",
        detected_at="2026-07-04T09:00:00.000Z",
        headers=COMPLIANCE_ANALYST,
    )
    assert_object_response(
        api.transition_violation_case(
            case["id"],
            f.case_transition_payload(
                "REQUEST_REMEDIATION", note="remove the auto-triggered iframe"
            ),
            COMPLIANCE_ANALYST,
        )
    )
    submitted = assert_object_response(
        api.transition_violation_case(
            case["id"],
            f.case_transition_payload(
                "SUBMIT_REMEDIATION",
                note="iframe removed",
                remediation_evidence_ref="EV-FIX-1",
            ),
            make_affiliate_partner_headers(partner["id"]),
        )
    )
    # §3.7: "Every transition increments the case's `version`." — open, request, submit.
    assert_fields(
        submitted,
        {
            "opened_by_user_id": COMPLIANCE_ANALYST_ID,
            "state": "REMEDIATION_SUBMITTED",
            "failed_verification_count": 0,
            "version": 3,
        },
    )
    return {"affiliate_id": partner["id"], "case_id": case["id"]}


class TestCaseVerificationSeparationOfDuties:
    def test_the_analyst_who_opened_the_case_may_not_verify_its_remediation(self, api):
        """The analyst who filed a case is refused when verifying the partner's fix.

        PRD §2.8: "The analyst who opened a violation case may not verify the remediation
        submitted against it. Any of these three collisions is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/case_verification_must_not_be_performed_by_the_opening_analyst
        """
        context = _case_awaiting_verification(api)

        response = api.transition_violation_case(
            context["case_id"],
            f.case_transition_payload(
                "VERIFY", note="fix confirmed", verify_outcome="CLEARED"
            ),
            COMPLIANCE_ANALYST,
        )

        assert_error_response(response, ERR_SEGREGATION_OF_DUTIES, 403)
        # §2.10: "the **first** rule whose condition fails decides the response; no later
        # rule is evaluated and nothing is persisted."
        case = assert_object_response(
            api.get_violation_case(context["case_id"], COMPLIANCE_ANALYST)
        )
        assert_fields(
            case,
            {
                "state": "REMEDIATION_SUBMITTED",
                "failed_verification_count": 0,
                "version": 3,
            },
        )

    def test_a_second_analyst_clears_the_identical_verification(self, api):
        """A different analyst holding the same role clears the case the filer could not.

        PRD §3.7: "A verification whose outcome is cleared moves the case to the terminal
        `VERIFIED_CLEARED`, lowers the partner's `open_violation_case_count` by one and
        recomputes both fraud variants."

        Design: Corner/rbac/case_verification_must_not_be_performed_by_the_opening_analyst
        """
        context = _case_awaiting_verification(api)
        refused = api.transition_violation_case(
            context["case_id"],
            f.case_transition_payload(
                "VERIFY", note="fix confirmed", verify_outcome="CLEARED"
            ),
            COMPLIANCE_ANALYST,
        )
        assert_error_response(refused, ERR_SEGREGATION_OF_DUTIES, 403)

        # §2.8: "the separation is enforced on `X-User-ID`, never on `X-User-Role` — two
        # users holding the same role satisfy it".
        cleared = assert_object_response(
            api.transition_violation_case(
                context["case_id"],
                f.case_transition_payload(
                    "VERIFY",
                    note="fix confirmed on independent review",
                    verify_outcome="CLEARED",
                ),
                SECOND_COMPLIANCE_ANALYST,
            )
        )

        assert_fields(cleared, {"state": "VERIFIED_CLEARED", "version": 4})
        partner = assert_object_response(
            api.get_affiliate(context["affiliate_id"], COMPLIANCE_ANALYST)
        )
        assert_field(partner, "open_violation_case_count", 0)


def _two_partners_one_tax_document(api):
    """Two registered partners, where partner A has filed one `W9` on its own row."""
    pin_clock(api, CLOCK)
    network = create_network(api)
    partner_a = assert_created(
        api.create_affiliate(
            f.affiliate_payload(
                network["id"],
                partner_type="CONTENT",
                legal_name="Beacon Content LLC",
                contact_email="beacon@example.com",
            ),
            ANONYMOUS,
        )
    )
    partner_b = assert_created(
        api.create_affiliate(
            f.affiliate_payload(
                network["id"],
                partner_type="LOYALTY_CASHBACK",
                legal_name="Sunset Cashback Inc",
                contact_email="sunset@example.com",
            ),
            ANONYMOUS,
        )
    )
    document = assert_created(
        api.file_tax_document(
            partner_a["id"],
            f.tax_document_payload(
                form_type="W9", tax_id_last4="1234", treaty_withholding_bps=0
            ),
            make_affiliate_partner_headers(partner_a["id"]),
        )
    )
    return {
        "affiliate_a": partner_a["id"],
        "affiliate_b": partner_b["id"],
        "document_id": document["id"],
    }


class TestAffiliatePartnerRowIsolation:
    def test_partner_reads_its_own_partner_row_and_its_own_tax_documents(self, api):
        """A publisher acting as itself sees its own row and its own filings.

        PRD §3.1: "The single-partner read exposes the partner's scores, tier, counters
        and balances, and is the channel through which an `AffiliatePartner` inspects its
        own money — it can read every figure but move none of them."

        Design: Corner/rbac/affiliate_partner_cannot_read_another_partners_rows
        """
        context = _two_partners_one_tax_document(api)
        as_partner_a = make_affiliate_partner_headers(context["affiliate_a"])

        own_row = assert_object_response(
            api.get_affiliate(context["affiliate_a"], as_partner_a)
        )
        assert_fields(
            own_row, {"id": context["affiliate_a"], "partner_type": "CONTENT"}
        )

        rows, meta = assert_list_response(
            api.list_tax_documents(
                context["affiliate_a"], as_partner_a, {"limit": 10, "offset": 0}
            )
        )
        assert_pagination_meta(meta, total_count=1)
        assert_field(rows[0], "id", context["document_id"])

    @pytest.mark.parametrize(
        "operation",
        [
            pytest.param(
                lambda api, context: api.get_affiliate(
                    context["affiliate_b"],
                    make_affiliate_partner_headers(context["affiliate_a"]),
                ),
                id="reading_another_partners_row",
            ),
            pytest.param(
                lambda api, context: api.list_tax_documents(
                    context["affiliate_a"],
                    make_affiliate_partner_headers(context["affiliate_b"]),
                    {"limit": 10, "offset": 0},
                ),
                id="listing_another_partners_tax_documents",
            ),
        ],
    )
    def test_partner_addressing_a_peer_partners_rows_is_refused(self, api, operation):
        """A publisher that addresses a row belonging to another publisher is refused.

        PRD §2.1: "When `X-User-Role` is `AffiliatePartner`, `X-User-ID` is the `id` of
        the acting `Affiliate`; ownership checks on any resource that references an
        `Affiliate` compare the resource's partner reference to `X-User-ID`, and an
        `AffiliatePartner` that addresses a resource resolving to a different partner is
        rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/rbac/affiliate_partner_cannot_read_another_partners_rows
        """
        context = _two_partners_one_tax_document(api)

        response = operation(api, context)

        assert_error_response(response, ERR_NOT_RESOURCE_OWNER, 403)

    def test_partner_reading_an_unknown_partner_id_answers_not_found(self, api):
        """Ownership is not existence: a partner id naming nothing answers its own 404.

        PRD §2.1: "That ownership check runs after existence, so the caller receives an
        accurate 403 rather than a misleading 404."

        Design: Corner/rbac/affiliate_partner_cannot_read_another_partners_rows
        """
        context = _two_partners_one_tax_document(api)

        response = api.get_affiliate(
            NON_EXISTENT_UUID, make_affiliate_partner_headers(context["affiliate_a"])
        )

        assert_error_response(response, ERR_AFFILIATE_NOT_FOUND, 404)

    def test_program_admin_reads_any_partner_row(self, api):
        """The ownership confinement binds publishers only, not the program's own staff.

        PRD §2.10 rule 13: "When the caller's role is `AffiliatePartner`, the addressed
        resource resolves to the caller's own partner row — otherwise
        `ERR_NOT_RESOURCE_OWNER` (403). Applies to seven operations: the single-partner
        read, the partner's tracking-link list, the partner's tax-document list,
        tax-document filing, application filing, application resubmission, and case
        transitions."

        Design: Corner/rbac/affiliate_partner_cannot_read_another_partners_rows
        """
        context = _two_partners_one_tax_document(api)
        refused = api.get_affiliate(
            context["affiliate_b"],
            make_affiliate_partner_headers(context["affiliate_a"]),
        )
        assert_error_response(refused, ERR_NOT_RESOURCE_OWNER, 403)

        peer_row = assert_object_response(
            api.get_affiliate(context["affiliate_b"], PROGRAM_ADMIN)
        )

        assert_fields(
            peer_row,
            {"id": context["affiliate_b"], "partner_type": "LOYALTY_CASHBACK"},
        )
