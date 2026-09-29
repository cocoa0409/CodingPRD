"""Who may do what — the endpoint gate, the action gate, the two entity-backed
identities, channel ownership and the two segregation pairs — together with the
concurrency guards and the cross-entity cascades that ride on top of them."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_terminal_census,
    attest_disclosures,
    cost_documentation_payload,
    create_jurisdiction,
    create_merchant,
    create_program,
    create_refund,
    decide_registration,
    effectuate_registration,
    file_complaint,
    file_cost_documentation,
    file_rate_rule,
    investigation_action_payload,
    jurisdiction_payload,
    list_page,
    list_total,
    make_headers,
    make_merchant_operator_headers,
    make_terminal_agent_headers,
    program_status_action_payload,
    provision_terminal,
    rate_rule_payload,
    read_complaint_case,
    read_merchant,
    read_program,
    read_refund,
    read_registration,
    read_terminal,
    registration_decision_payload,
    required_artifact_types,
    set_clock,
    setup_configured_terminal,
    setup_draft_program,
    setup_enforcing_cash_discount_estate,
    setup_enforcing_surcharge_estate,
    setup_active_surcharge_program,
    setup_program_with_effective_registration,
    setup_refundable_sale,
    setup_surcharged_sale,
    submit_registration,
    terminal_configuration_payload,
    transaction_payload,
    validate_error,
    validate_success,
)
from test_helpers.constants import (
    CLOCK_AUG_01,
    CLOCK_AUG_31,
    OFFICER_ONE_USER_ID,
    TS_AUG_01,
    TS_AUG_31,
    UNMINTED_UUID,
)
from test_helpers.fixtures import ADMIN, AUDITOR, OFFICER_ONE, OFFICER_TWO, REGULATOR


def test_a_merchant_operator_cannot_seed_a_jurisdiction(api):
    """PRD §2.1: "A well-formed request whose role is simply not listed as authorised for the target operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403); the authorised roles per operation are tabulated in §4."
    PRD §2.1: "A `PlatformAdmin` is a platform operator: it seeds jurisdictions and merchants and it drives the service's logical clock."

    Design: Corner/rbac/merchant_operator_cannot_create_a_jurisdiction
    """
    response = api_client.create_jurisdiction(
        jurisdiction_payload("AZ"), make_merchant_operator_headers(UNMINTED_UUID)
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)
    assert response.status_code == 403
    assert list_total(api_client.list_jurisdictions(ADMIN)) == 0


def test_a_platform_admin_is_still_barred_from_activating_a_program(api):
    """PRD §2.9: "**Endpoint authorisation** — the acting role is listed for the operation: `ERR_UNAUTHORIZED`, 403. Applies to every operation."
    PRD §2.9: "**Path existence** — every identifier in the path resolves, left to right: the 404 family of §2.6. Applies to every operation with a path identifier."

    Design: Corner/rbac/platform_admin_cannot_activate_a_program
    """
    response = api_client.activate_program(UNMINTED_UUID, ADMIN)
    error_data = validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)
    assert response.status_code == 403
    assert error_data["error_id"] != ApiErrorId.ERR_PROGRAM_NOT_FOUND


def test_the_auditor_that_may_suspend_may_not_resume(api):
    """PRD §2.1: "Where the acting role is authorised for the endpoint but not for the specific value requested, the rejection is `ERR_ACTION_ROLE_FORBIDDEN` (HTTP 403) rather than `ERR_UNAUTHORIZED`."
    PRD §2.1: "Concretely: on program status actions, `SUSPEND` is open to both `ComplianceOfficer` and `NetworkAuditor` while `RESUME` and `WITHDRAW` are open to `ComplianceOfficer` only; on terminal state actions, `ENFORCE` and `RESTORE` are open to `MerchantOperator` only while `QUARANTINE` is open to `MerchantOperator` and `ComplianceOfficer`; on complaint investigation actions, `REVIEW` is open to `ComplianceOfficer` only while `SUBSTANTIATE` and `DISMISS` are open to `NetworkAuditor` and `StateRegulator` only; on complaint remediation actions, `SUBMIT_PLAN` is open to `ComplianceOfficer` only while `ACCEPT_PLAN` and `CLOSE` are open to `NetworkAuditor` and `StateRegulator` only."

    Design: Corner/rbac/network_auditor_cannot_resume_a_suspended_program
    """
    ctx = setup_active_surcharge_program()
    program_id = ctx["program"]["id"]
    suspended = validate_success(
        api_client.program_status_action(
            program_id,
            program_status_action_payload("SUSPEND", reason="network audit hold"),
            AUDITOR,
        )
    )
    assert suspended["status"] == "SUSPENDED"

    response = api_client.program_status_action(
        program_id, program_status_action_payload("RESUME"), AUDITOR
    )
    validate_error(response, ApiErrorId.ERR_ACTION_ROLE_FORBIDDEN)
    assert response.status_code == 403

    program = read_program(program_id)
    assert program["status"] == "SUSPENDED"
    assert program["disable_reason"] == "OPERATOR_SUSPENSION"


def test_the_two_roles_cover_opposite_halves_of_the_status_endpoint(api):
    """PRD §3.7: "**`SUSPEND`**, available to a `ComplianceOfficer` or a `NetworkAuditor`, requires `status` of `ACTIVE` and moves the program `ACTIVE → SUSPENDED` with `disable_reason` set to `OPERATOR_SUSPENSION`."
    PRD §3.7: "On success `disable_reason` is set to `NONE`, `activated_at` and `activated_by_user_id` are re-stamped from the logical clock and the acting `X-User-ID`, `effective_cap_pct` and `disclosure_ready` are recomputed, and the program's `version` is bumped by 1."

    Design: Corner/rbac/compliance_officer_and_network_auditor_share_the_suspend_action
    """
    ctx = setup_active_surcharge_program()
    program_id = ctx["program"]["id"]

    suspend_response = api_client.program_status_action(
        program_id,
        program_status_action_payload("SUSPEND", reason="network audit hold"),
        AUDITOR,
    )
    suspended = validate_success(suspend_response)
    assert suspend_response.status_code == 200
    assert suspended["status"] == "SUSPENDED"
    assert suspended["disable_reason"] == "OPERATOR_SUSPENSION"

    resume_response = api_client.program_status_action(
        program_id, program_status_action_payload("RESUME"), OFFICER_ONE
    )
    resumed = validate_success(resume_response)
    assert resume_response.status_code == 200
    assert resumed["status"] == "ACTIVE"
    assert resumed["disable_reason"] == "NONE"
    assert resumed["effective_cap_pct"] == pytest.approx(2.19, abs=0.0001)
    assert resumed["activated_by_user_id"] == "officer-1"


def test_an_operator_cannot_configure_a_terminal_it_does_not_own(api):
    """PRD §2.1: "When `X-User-Role` is `MerchantOperator`, `X-User-ID` is the `id` of the acting `Merchant`; ownership checks on any resource that references a `Merchant` compare the resource's merchant foreign-key field to `X-User-ID`, so a `MerchantOperator` may only provision terminals under its own merchant record, only configure and drive terminals whose `merchant_id` equals `X-User-ID`, and only draft disclosure artifacts for programs whose `merchant_id` equals `X-User-ID`."
    PRD §2.1: "A mismatch is rejected with `ERR_MERCHANT_OWNERSHIP_REQUIRED` (HTTP 403)."

    Design: Corner/rbac/merchant_operator_cannot_configure_another_merchants_terminal
    """
    set_clock(CLOCK_AUG_01)
    jurisdiction = create_jurisdiction("AZ")
    merchant_a = create_merchant(jurisdiction["id"], legal_name="Saguaro Retail A")
    merchant_b = create_merchant(jurisdiction["id"], legal_name="Saguaro Retail B")
    documentation = file_cost_documentation(merchant_a["id"])
    program_a = create_program(
        merchant_a["id"],
        jurisdiction["id"],
        documentation["id"],
        "SURCHARGE",
        "BRAND_LEVEL",
    )
    terminal_a = provision_terminal(merchant_a["id"], "TRM-AZ-8801")

    response = api_client.configure_terminal(
        terminal_a["id"],
        terminal_configuration_payload(program_a["id"]),
        make_merchant_operator_headers(merchant_b["id"]),
    )
    validate_error(response, ApiErrorId.ERR_MERCHANT_OWNERSHIP_REQUIRED)
    assert response.status_code == 403

    terminal = read_terminal(terminal_a["id"])
    assert terminal["state"] == "PROVISIONED"
    assert terminal["program_id"] is None
    assert terminal["last_configured_at"] is None


def test_a_terminal_cannot_book_a_sale_in_a_siblings_name(api):
    """PRD §2.1: "When `X-User-Role` is `TerminalAgent`, `X-User-ID` is the `id` of the acting `Terminal`; a capture whose body `terminal_id` differs from `X-User-ID` is rejected with `ERR_TERMINAL_IDENTITY_MISMATCH` (HTTP 403)."
    PRD §2.9: "**Terminal identity** — a `TerminalAgent`'s `X-User-ID` equals the body `terminal_id`: `ERR_TERMINAL_IDENTITY_MISMATCH`, 403. Applies to sale capture only."

    Design: Corner/rbac/terminal_agent_cannot_book_a_sale_for_another_terminal
    """
    ctx = setup_enforcing_surcharge_estate(terminal_count=2)
    acting, sibling = ctx["terminals"]
    assert acting["state"] == "ENFORCING"
    assert sibling["state"] == "ENFORCING"

    response = api_client.create_transaction(
        transaction_payload(sibling["id"], ctx["program"]["id"]),
        make_terminal_agent_headers(acting["id"]),
    )
    validate_error(response, ApiErrorId.ERR_TERMINAL_IDENTITY_MISMATCH)
    assert response.status_code == 403

    assert list_total(api_client.list_transactions(ADMIN)) == 0
    merchant = read_merchant(ctx["merchant"]["id"])
    assert_terminal_census(merchant, 2)
    assert merchant["gross_surcharge_collected_cents"] == 0


def test_only_the_regulator_may_rule_on_an_attorney_general_case(api):
    """PRD §2.1: "A `NetworkAuditor` may file and decide cases whose `source` is `NETWORK` or `CARDHOLDER`; a `StateRegulator` may file and decide cases whose `source` is `ATTORNEY_GENERAL`."
    PRD §2.1: "A role reaching across that boundary — a `NetworkAuditor` acting on an `ATTORNEY_GENERAL` case, or a `StateRegulator` acting on a `NETWORK` or `CARDHOLDER` case — is rejected with `ERR_COMPLAINT_SOURCE_ROLE_MISMATCH` (HTTP 403), and the check applies to complaint filing, to investigation actions, and to remediation actions alike."

    Design: Corner/rbac/network_auditor_cannot_substantiate_an_attorney_general_case
    """
    ctx = setup_draft_program(with_rate_rule=False)
    case = file_complaint(ctx["program"]["id"], "ATTORNEY_GENERAL")
    assert case["investigation_state"] == "OPEN"

    response = api_client.complaint_investigation_action(
        case["id"],
        investigation_action_payload("SUBSTANTIATE", note="network review"),
        AUDITOR,
    )
    validate_error(response, ApiErrorId.ERR_COMPLAINT_SOURCE_ROLE_MISMATCH)
    assert response.status_code == 403

    untouched = read_complaint_case(case["id"])
    assert untouched["investigation_state"] == "OPEN"
    assert untouched["remediation_state"] == "NONE"

    ruled = validate_success(
        api_client.complaint_investigation_action(
            case["id"],
            investigation_action_payload(
                "SUBSTANTIATE", note="state inspection confirms"
            ),
            REGULATOR,
        )
    )
    assert ruled["investigation_state"] == "SUBSTANTIATED"
    assert ruled["remediation_state"] == "PLAN_REQUIRED"


def test_the_officer_who_attested_the_signage_cannot_activate(api):
    """PRD §2.10: "A program may not be activated by an officer who attested any of that program's disclosure artifacts."
    PRD §2.10: "At activation, the acting `X-User-ID` is compared against `attested_by_user_id` of every `DisclosureArtifact` belonging to the program; if it matches any of them, the activation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/activating_officer_cannot_be_an_attesting_officer
    """
    ctx = setup_program_with_effective_registration(jurisdiction_profile="NY")
    program_id = ctx["program"]["id"]
    required = required_artifact_types("SURCHARGE", ctx["jurisdiction"])
    assert sorted(required) == ["ENTRY_SIGNAGE", "POS_SIGNAGE", "RECEIPT_TEMPLATE"]
    artifacts = attest_disclosures(
        program_id,
        ctx["merchant"]["id"],
        required,
        officer_user_id=OFFICER_ONE_USER_ID,
    )
    assert [artifact["attested_by_user_id"] for artifact in artifacts.values()] == [
        "officer-1"
    ] * 3

    response = api_client.activate_program(program_id, OFFICER_ONE)
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert response.status_code == 403

    blocked = read_program(program_id)
    assert blocked["status"] == "PENDING_REGISTRATION"
    assert blocked["activated_at"] is None

    activated = validate_success(api_client.activate_program(program_id, OFFICER_TWO))
    assert activated["status"] == "ACTIVE"
    assert activated["activated_by_user_id"] == "officer-2"
    assert activated["disclosure_ready"] is True
    assert activated["effective_cap_pct"] == pytest.approx(2.19, abs=0.0001)


def test_the_officer_who_created_the_refund_cannot_issue_it(api):
    """PRD §2.10: "A refund may not be issued by the officer who created it."
    PRD §2.10: "At issuance, the acting `X-User-ID` is compared against the refund's `created_by_user_id`, and equality is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/refund_creator_cannot_issue_the_same_refund
    """
    ctx = setup_refundable_sale()
    refund = create_refund(
        ctx["complaint_case"]["id"], ctx["transaction"]["id"], 219
    )
    assert refund["created_by_user_id"] == "officer-1"

    response = api_client.issue_refund(refund["id"], OFFICER_ONE)
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert response.status_code == 403

    blocked = read_refund(refund["id"])
    assert blocked["state"] == "PENDING"
    assert blocked["issued_by_user_id"] is None

    issued = validate_success(api_client.issue_refund(refund["id"], OFFICER_TWO))
    assert issued["state"] == "ISSUED"
    assert issued["issued_by_user_id"] == "officer-2"

    merchant = read_merchant(ctx["merchant"]["id"])
    assert merchant["gross_surcharge_collected_cents"] == 219
    assert merchant["net_surcharge_collected_cents"] == 0


def test_empty_identity_headers_fail_before_the_path_is_resolved(api):
    """PRD §2.1: "Both must be present and non-empty, and `X-User-Role` must name one of the six declared roles."
    PRD §2.9: "**Header validity** — both auth headers present, non-empty, and naming one of the six roles: `ERR_UNAUTHENTICATED`, 401. Applies to every operation."

    Design: Corner/rbac/request_with_blank_identity_headers_is_unauthenticated
    """
    response = api_client.get_program(
        UNMINTED_UUID, {"X-User-ID": "", "X-User-Role": ""}
    )
    error_data = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)
    assert response.status_code == 401
    assert error_data["error_id"] != ApiErrorId.ERR_PROGRAM_NOT_FOUND


def test_a_role_outside_the_declared_six_is_not_authenticated_at_all(api):
    """PRD §2.1: "A request that omits either header, sends either header empty, or names a role outside the declared six is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.1: "The six roles are `PlatformAdmin`, `ComplianceOfficer`, `MerchantOperator`, `NetworkAuditor`, `StateRegulator`, and `TerminalAgent`."

    Design: Corner/rbac/request_with_an_undeclared_role_name_is_unauthenticated
    """
    response = api_client.list_jurisdictions(make_headers("auditor-1", "Auditor"))
    error_data = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)
    assert response.status_code == 401
    assert error_data["error_id"] != ApiErrorId.ERR_UNAUTHORIZED


def test_a_replayed_program_version_cannot_file_a_second_rate_rule(api):
    """PRD §2.7: "If `expected_program_version` does not equal the program's current `version`, the request is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412), because the client validated its rate against a cap that no longer holds."
    PRD §2.7: "Filing a `BrandRateRule` under a program requires `expected_program_version` in the body as a mandatory field, carrying the client's last observed `version` of the parent `SurchargeProgram`."

    Design: Corner/cross_cutting_complexity_layers/stale_program_version_rejects_a_second_rate_rule_filing
    """
    ctx = setup_draft_program(with_rate_rule=False)
    program_id = ctx["program"]["id"]
    creation_version = ctx["program"]["version"]
    assert creation_version == 1

    file_rate_rule(program_id, creation_version, brand="VISA")
    after_first = read_program(program_id)
    assert after_first["version"] == creation_version + 1

    stale = api_client.create_rate_rule(
        program_id,
        rate_rule_payload(creation_version, brand="MASTERCARD"),
        OFFICER_ONE,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_PROGRAM_VERSION)
    assert stale.status_code == 412
    assert (
        list_total(
            api_client.list_rate_rules(OFFICER_ONE, params={"program_id": program_id})
        )
        == 1
    )

    created = validate_success(
        api_client.create_rate_rule(
            program_id,
            rate_rule_payload(after_first["version"], brand="MASTERCARD"),
            OFFICER_ONE,
        ),
        expected_status=201,
    )
    assert created["brand"] == "MASTERCARD"
    assert created["rate_pct"] == pytest.approx(2.19, abs=0.0001)

    assert read_program(program_id)["version"] == 3
    assert (
        list_total(
            api_client.list_rate_rules(OFFICER_ONE, params={"program_id": program_id})
        )
        == 2
    )


def test_a_replayed_merchant_version_cannot_supersede_the_cost_documentation(api):
    """PRD §2.7: "Filing a `CostDocumentation` under a merchant requires `expected_merchant_version` in the body as a mandatory field, carrying the client's last observed `version` of the parent `Merchant`."
    PRD §3.2: "The merchant's existing document in state `ACTIVE`, if there is one, moves to `SUPERSEDED` with `superseded_at` stamped from the logical clock and its own `version` bumped; the merchant's `active_cost_documentation_id` is repointed at the new document; and the merchant's `version` is bumped by 1."

    Design: Corner/cross_cutting_complexity_layers/stale_merchant_version_rejects_a_superseding_cost_documentation
    """
    set_clock(CLOCK_AUG_01)
    jurisdiction = create_jurisdiction("AZ")
    merchant = create_merchant(jurisdiction["id"])
    creation_version = merchant["version"]
    documentation_a = file_cost_documentation(merchant["id"], creation_version, "docA")
    after_first = read_merchant(merchant["id"])
    assert after_first["version"] == creation_version + 1

    stale = api_client.create_cost_documentation(
        merchant["id"], cost_documentation_payload(creation_version, "docB"), OFFICER_ONE
    )
    validate_error(stale, ApiErrorId.ERR_STALE_MERCHANT_VERSION)
    assert stale.status_code == 412

    rows, meta = list_page(
        api_client.list_cost_documentations(
            OFFICER_ONE, params={"merchant_id": merchant["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["state"] == "ACTIVE"

    documentation_b = validate_success(
        api_client.create_cost_documentation(
            merchant["id"],
            cost_documentation_payload(after_first["version"], "docB"),
            OFFICER_ONE,
        ),
        expected_status=201,
    )
    assert documentation_b["documented_cost_pct"] == pytest.approx(3.05, abs=0.0001)
    assert documentation_b["state"] == "ACTIVE"

    superseded = validate_success(
        api_client.get_cost_documentation(documentation_a["id"], OFFICER_ONE)
    )
    assert superseded["state"] == "SUPERSEDED"
    assert superseded["superseded_at"] == TS_AUG_01

    merchant_final = read_merchant(merchant["id"])
    assert merchant_final["version"] == 3
    assert merchant_final["active_cost_documentation_id"] == documentation_b["id"]


def test_the_program_counter_ignores_writes_that_only_touch_the_registration(api):
    """PRD §2.7: "No other operation in this service accepts a version field."
    PRD §3.5: "The first registration also drives the program from `DRAFT` to `PENDING_REGISTRATION`, and the program's `version` is bumped by 1."

    Design: Corner/cross_cutting_complexity_layers/program_version_increments_only_on_writes_that_touch_the_program
    """
    ctx = setup_draft_program(with_rate_rule=False)
    program_id = ctx["program"]["id"]
    assert ctx["program"]["version"] == 1

    file_rate_rule(program_id, 1, brand="VISA")
    assert read_program(program_id)["version"] == 2

    registration = submit_registration(program_id, "VISA", "VS-2940-AZ-551")
    assert read_program(program_id)["version"] == 3

    decide_registration(registration["id"], "ACKNOWLEDGE")
    set_clock(CLOCK_AUG_31)
    effectuate_registration(registration["id"])
    assert read_program(program_id)["version"] == 3

    activated = validate_success(api_client.activate_program(program_id, OFFICER_ONE))
    assert activated["status"] == "ACTIVE"
    assert activated["version"] == 4
    assert read_registration(registration["id"])["version"] == 3


def test_a_revocation_reaches_the_enforcing_terminal_and_stops_there(api):
    """PRD §3.5: "When a `NetworkAuditor` revokes a registration that was `EFFECTIVE`, and the owning program's `status` is `ACTIVE`, the program moves `ACTIVE → SUSPENDED` with `disable_reason` set to `REGISTRATION_REVOKED`; every `Terminal` of that program in state `ENFORCING` moves to `QUARANTINED` with `quarantine_reason` set to `PROGRAM_SUSPENDED`; and each of those terminal transitions recomputes `enforcing_terminal_count` on the terminal's merchant."
    PRD §3.5: "`REVOKE` moves `EFFECTIVE → REVOKED`, stamps `revoked_at` from the logical clock, and carries a cross-entity consequence described below."

    Design: Corner/cross_cutting_complexity_layers/registration_revocation_cascades_three_levels_and_skips_the_configured_terminal
    """
    ctx = setup_enforcing_surcharge_estate(terminal_count=1)
    merchant_id = ctx["merchant"]["id"]
    program_id = ctx["program"]["id"]
    enforcing = ctx["terminal"]
    configured = setup_configured_terminal(merchant_id, program_id, "TRM-AZ-0002")
    assert configured["state"] == "CONFIGURED"
    assert_terminal_census(read_merchant(merchant_id), 1)

    revoked = validate_success(
        api_client.decide_network_registration(
            ctx["registration"]["id"],
            registration_decision_payload(
                "REVOKE", decision_note="brand rules violation confirmed"
            ),
            AUDITOR,
        )
    )
    assert revoked["state"] == "REVOKED"
    assert revoked["revoked_at"] == TS_AUG_31
    assert revoked["decided_by_user_id"] == "auditor-1"

    program = read_program(program_id)
    assert program["status"] == "SUSPENDED"
    assert program["disable_reason"] == "REGISTRATION_REVOKED"

    quarantined = read_terminal(enforcing["id"])
    assert quarantined["state"] == "QUARANTINED"
    assert quarantined["quarantine_reason"] == "PROGRAM_SUSPENDED"

    untouched = read_terminal(configured["id"])
    assert untouched["state"] == "CONFIGURED"
    assert untouched["quarantine_reason"] == "NONE"

    assert_terminal_census(read_merchant(merchant_id), 0)
    assert (
        list_total(
            api_client.list_terminals(
                ADMIN, params={"program_id": program_id, "state": "QUARANTINED"}
            )
        )
        == 1
    )


def test_the_cash_discount_arm_deducts_where_the_surcharge_arm_adds(api):
    """PRD §3.9: "On a `CASH_DISCOUNT` program, whatever the funding: `surcharge_amount_cents` is 0; `cash_discount_amount_cents` is `base_amount_cents` multiplied by the applied rate, divided by 100, rounded half up to a whole cent; `cash_price_cents` is `base_amount_cents` minus `cash_discount_amount_cents`; `total_amount_cents` equals `base_amount_cents`, because under a cash-discount structure the card price *is* the posted price; and `outcome` is `APPROVED_CASH_DISCOUNT`."
    PRD §3.3: "For a `CASH_DISCOUNT` program the cap is simply the cash-discount ceiling of 10.0 percent."

    Design: Corner/cross_cutting_complexity_layers/cash_discount_program_deducts_where_the_surcharge_program_adds
    """
    ctx = setup_enforcing_cash_discount_estate(terminal_count=1)
    program_id = ctx["program"]["id"]
    terminal_id = ctx["terminal"]["id"]

    captured = validate_success(
        api_client.create_transaction(
            transaction_payload(
                terminal_id,
                program_id,
                requested_surcharge_cents=0,
                receipt_line_present=False,
            ),
            make_terminal_agent_headers(terminal_id),
        ),
        expected_status=201,
    )
    assert captured["applied_rate_pct"] == pytest.approx(2.19, abs=0.0001)
    assert captured["surcharge_amount_cents"] == 0
    assert captured["cash_discount_amount_cents"] == 219
    assert captured["cash_price_cents"] == 9781
    assert captured["total_amount_cents"] == 10000
    assert captured["outcome"] == "APPROVED_CASH_DISCOUNT"

    program = read_program(program_id)
    assert program["program_type"] == "CASH_DISCOUNT"
    assert program["status"] == "ACTIVE"
    assert program["effective_cap_pct"] == pytest.approx(10.0, abs=0.0001)
    assert program["disclosure_ready"] is True

    merchant = read_merchant(ctx["merchant"]["id"])
    assert merchant["gross_surcharge_collected_cents"] == 0
    assert merchant["net_surcharge_collected_cents"] == 0

    summary = validate_success(
        api_client.get_settlement_summary(program_id, OFFICER_ONE)
    )
    assert summary["transaction_count"] == 1
    assert summary["base_amount_total_cents"] == 10000
    assert summary["per_line_rounded_surcharge_cents"] == 0


def test_one_cardholder_case_stays_a_notch_below_the_remediation_trigger(api):
    """PRD §3.10: "One substantiated `NETWORK` case therefore scores 20 multiplied by 1.5, which is 30.00, while one substantiated `CARDHOLDER` case scores 20 multiplied by 1.0, which is 20.00."
    PRD §3.10: "If the recomputed score stays below 30, or the program was not `ACTIVE`, only the case's own fields move."
    PRD §3.10: "Every case whose `investigation_state` is `OPEN`, `UNDER_REVIEW`, or `SUBSTANTIATED` contributes: 20 points if it is `SUBSTANTIATED`, and 8 points if it is merely `OPEN` or `UNDER_REVIEW`."

    Design: Corner/cross_cutting_complexity_layers/cardholder_case_below_the_remediation_threshold_leaves_the_program_active
    """
    ctx = setup_surcharged_sale()
    program_id = ctx["program"]["id"]
    case = file_complaint(program_id, "CARDHOLDER")

    ruled = validate_success(
        api_client.complaint_investigation_action(
            case["id"],
            investigation_action_payload("SUBSTANTIATE", note="receipt image reviewed"),
            AUDITOR,
        )
    )
    assert ruled["investigation_state"] == "SUBSTANTIATED"
    assert ruled["remediation_state"] == "PLAN_REQUIRED"

    summary = validate_success(api_client.get_exposure_summary(program_id, OFFICER_ONE))
    assert summary["network_exposure_score"] == pytest.approx(20.0, abs=0.005)
    assert summary["ag_exposure_score"] == pytest.approx(10.0, abs=0.005)
    assert summary["substantiated_case_count"] == 1
    assert summary["unresolved_case_count"] == 0
    assert summary["posture_multiplier"] == pytest.approx(0.5, abs=0.0001)
    assert summary["remediation_threshold"] == pytest.approx(30.0, abs=0.005)

    program = read_program(program_id)
    assert program["status"] == "ACTIVE"
    assert program["disable_reason"] == "NONE"
    assert program["network_exposure_score"] == pytest.approx(20.0, abs=0.005)

    assert read_terminal(ctx["terminal"]["id"])["state"] == "ENFORCING"
    assert_terminal_census(read_merchant(ctx["merchant"]["id"]), 1)
