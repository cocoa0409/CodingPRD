"""Role-based access control and segregation of duties (PRD §2.1, §2.10)."""
import pytest

from test_helpers import (
    api_client, ApiErrorId, validate_success, validate_error, get_success_data,
    build_user_headers, NON_EXISTENT_UUID,
    setup_network, create_sponsor, create_program, create_agreement,
    create_account, create_location, get_program, get_agreement,
    raise_alert, review_alert,
    make_program_manager_headers, make_bank_sponsor_headers,
    make_analyst_headers, make_officer_headers,
    make_retailer_clerk_headers, ADMIN, ANALYST, OFFICER, SETTLEMENT,
)


def test_program_manager_transitions_its_own_agreement():
    """PRD §2.1: "When `X-User-Role` is `ProgramManager`, `X-User-ID` is the `id`
    of the acting `Program`; a retailer agreement is actionable only when its
    `program_id` equals `X-User-ID`".

    Design: Corner/rbac/program_manager_transitions_own_agreement
    """
    net = setup_network(activate_agreement_flag=False)
    assert net["agreement"]["agreement_status"] == "DRAFT"
    resp = api_client.set_retailer_agreement_state(
        net["agreement"]["id"], {"to_status": "ACTIVE"},
        make_program_manager_headers(net["program"]["id"]))
    updated = validate_success(resp, 200)
    assert updated["agreement_status"] == "ACTIVE"


def test_program_manager_cannot_transition_another_programs_agreement():
    """PRD §2.1: "a retailer agreement is actionable only when its `program_id`
    equals `X-User-ID`".
    PRD §2.1: "A request whose declared role is not among the roles authorised for
    that operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/program_manager_cannot_transition_another_programs_agreement
    """
    net = setup_network(activate_agreement_flag=False)
    other = create_program(net["bank"]["id"], name="Harbor Two")
    resp = api_client.set_retailer_agreement_state(
        net["agreement"]["id"], {"to_status": "ACTIVE"},
        make_program_manager_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
    assert get_agreement(net["agreement"]["id"])["agreement_status"] == "DRAFT"


def test_bank_sponsor_cannot_move_another_banks_program_posture():
    """PRD §2.1: "a posture move or oversight review is refused unless the target
    program's `sponsor_bank_id` equals `X-User-ID`."

    Design: Corner/rbac/bank_sponsor_cannot_move_another_banks_program_posture
    """
    net = setup_network()
    other_bank = create_sponsor(legal_name="Granite National Bank",
                                charter_state_code="OH",
                                sponsorship_capacity_programs=5)
    program = get_program(net["program"]["id"])
    resp = api_client.set_program_state(
        net["program"]["id"],
        {"to_posture": "RESTRICTED", "expected_program_version": program["version"]},
        make_bank_sponsor_headers(other_bank["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
    assert get_program(net["program"]["id"])["compliance_posture"] == "OPEN"


def test_retailer_clerk_cannot_list_aml_alerts():
    """PRD §2.1: "When `X-User-Role` is `RetailerClerk`, `X-User-ID` is the `id`
    of the acting `RetailerAgreement`; a clerk may accept cash only at a location
    governed by the clerk's own agreement, and may answer a dispute only where the
    clerk's agreement is party to the disputed load."
    PRD §4: the AML alert list is authorised for PlatformAdmin, BankSponsor,
    ProgramManager, ComplianceAnalyst and ComplianceOfficer only.

    Design: Corner/rbac/retailer_clerk_cannot_read_aml_alerts
    """
    net = setup_network()
    resp = api_client.list_aml_alerts(
        make_retailer_clerk_headers(net["agreement"]["id"]),
        {"program_id": net["program"]["id"]})
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
    # the same collection is readable by the monitoring role
    ok = api_client.list_aml_alerts(ANALYST, {"program_id": net["program"]["id"]})
    validate_success(ok, 200)


def test_settlement_operator_cannot_create_programs():
    """PRD §2.1: "`PlatformAdmin` holds the cross-tenant administrative surface:
    only that role may register a sponsor bank, create a program, or set the
    logical clock."

    Design: Corner/rbac/settlement_operator_cannot_create_programs
    """
    net = setup_network()
    resp = api_client.create_program(
        {"name": "Unauthorized Program", "sponsor_bank_id": net["bank"]["id"],
         "program_type": "BAAS_PROGRAM_MANAGER", "settlement_cycle": "DAILY",
         "oversight_review_due_at": "2026-12-15T00:00:00Z"},
        SETTLEMENT)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)


def test_confirming_officer_cannot_be_the_reviewing_analyst():
    """PRD §2.10: "The confirming principal must be neither the analyst who raised
    the alert nor the analyst who took it into review: if `X-User-ID` equals the
    alert's `raised_by_analyst_id`, or equals its `assigned_analyst_id`, the
    confirmation is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/confirming_officer_cannot_be_the_reviewing_analyst
    """
    net = setup_network()
    alert = get_success_data(api_client.create_aml_alert(
        {"program_id": net["program"]["id"], "card_account_id": net["account"]["id"],
         "alert_type": "VELOCITY", "window_start_at": "2026-09-01T00:00:00Z",
         "window_end_at": "2026-09-02T00:00:00Z"},
        make_analyst_headers("a-raise")))
    get_success_data(api_client.review_aml_alert(
        alert["id"], {"resolution_note": "reviewed by a-rev"},
        make_analyst_headers("a-rev")))
    reviewed = get_success_data(api_client.get_aml_alert(alert["id"], ADMIN))
    assert reviewed["assigned_analyst_id"] == "a-rev"
    resp = api_client.confirm_aml_alert(alert["id"], make_officer_headers("a-rev"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
    still = get_success_data(api_client.get_aml_alert(alert["id"], ADMIN))
    assert still["alert_status"] == "UNDER_REVIEW"
    assert still["confirmed_by_analyst_id"] is None


def test_confirming_officer_cannot_be_the_raising_analyst():
    """PRD §2.10: "if `X-User-ID` equals the alert's `raised_by_analyst_id`, or
    equals its `assigned_analyst_id`, the confirmation is refused with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §2.10: "an officer who raised an alert must hand the confirmation to a
    different officer."

    Design: Corner/rbac/confirming_officer_cannot_be_the_raising_analyst
    """
    net = setup_network()
    alert = get_success_data(api_client.create_aml_alert(
        {"program_id": net["program"]["id"], "card_account_id": net["account"]["id"],
         "alert_type": "VELOCITY", "window_start_at": "2026-09-01T00:00:00Z",
         "window_end_at": "2026-09-02T00:00:00Z"},
        make_analyst_headers("a-raise")))
    get_success_data(api_client.review_aml_alert(
        alert["id"], {"resolution_note": "reviewed by a-rev"},
        make_analyst_headers("a-rev")))
    resp = api_client.confirm_aml_alert(alert["id"], make_officer_headers("a-raise"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
    still = get_success_data(api_client.get_aml_alert(alert["id"], ADMIN))
    assert still["alert_status"] == "UNDER_REVIEW"


def test_a_distinct_officer_can_confirm_the_alert():
    """PRD §2.10: "The confirming principal must be neither the analyst who raised
    the alert nor the analyst who took it into review".

    Design: Corner/rbac/confirming_officer_cannot_be_the_raising_analyst
    """
    net = setup_network()
    alert = get_success_data(api_client.create_aml_alert(
        {"program_id": net["program"]["id"], "card_account_id": net["account"]["id"],
         "alert_type": "VELOCITY", "window_start_at": "2026-09-01T00:00:00Z",
         "window_end_at": "2026-09-02T00:00:00Z"},
        make_analyst_headers("a-raise")))
    get_success_data(api_client.review_aml_alert(
        alert["id"], {"resolution_note": "reviewed by a-rev"},
        make_analyst_headers("a-rev")))
    confirmed = get_success_data(
        api_client.confirm_aml_alert(alert["id"], make_officer_headers("a-confirm")))
    assert confirmed["alert_status"] == "CONFIRMED"
    assert confirmed["confirmed_by_analyst_id"] == "a-confirm"


def test_auth_is_checked_before_path_existence():
    """PRD §2.1: "A request missing either header, or presenting a role string
    that is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."
    PRD §2.4: "Both checks precede every business rule: existence is settled
    before state, and state is settled before amounts."

    Design: Corner/validations/auth_precedes_existence_on_protected_write
    """
    resp = api_client.get_program(NON_EXISTENT_UUID,
                                  build_user_headers("some-operator", "NotARole"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)