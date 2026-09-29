"""The 404 family on every entity that owns one, the three uniqueness constraints, the
shape of a failure envelope, and the two capture gates that outrank each other."""

from test_helpers import (
    ApiErrorId,
    api_client,
    attestation_payload,
    create_jurisdiction,
    create_merchant,
    create_program,
    investigation_action_payload,
    jurisdiction_payload,
    law_change_payload,
    list_items,
    list_total,
    program_payload,
    program_status_action,
    provision_terminal,
    network_registration_payload,
    read_program,
    read_terminal,
    registration_decision_payload,
    setup_enforcing_surcharge_estate,
    setup_draft_program,
    setup_program_pending_registration,
    terminal_configuration_payload,
    terminal_payload,
    transaction_payload,
    validate_error,
)
from test_helpers.constants import CLOCK_AUG_01, CLOCK_DEC_31, UNMINTED_UUID
from test_helpers.fixtures import ADMIN, AUDITOR, OFFICER_ONE, OFFICER_TWO, REGULATOR
from test_helpers.test_users import make_merchant_operator_headers, make_terminal_agent_headers


def test_a_law_change_on_an_unminted_jurisdiction_is_not_found(api):
    """PRD §2.6: "Identifiers in a request path are resolved left to right, and the first one that does not resolve determines the rejection."
    PRD §2.6: "Each entity has its own not-found code: `ERR_JURISDICTION_NOT_FOUND`, `ERR_MERCHANT_NOT_FOUND`, `ERR_COST_DOCUMENTATION_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`, `ERR_ARTIFACT_NOT_FOUND`, `ERR_TERMINAL_NOT_FOUND`, `ERR_TRANSACTION_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, and `ERR_REFUND_NOT_FOUND`, each carrying HTTP 404."
    PRD §2.9: "**Path existence** — every identifier in the path resolves, left to right: the 404 family of §2.6. Applies to every operation with a path identifier."

    Design: Corner/errors/unknown_jurisdiction_on_a_law_change_returns_not_found
    """
    response = api_client.apply_law_change(
        UNMINTED_UUID, law_change_payload(True, surcharge_cap_pct=3.0), REGULATOR
    )
    validate_error(response, ApiErrorId.ERR_JURISDICTION_NOT_FOUND)

    assert list_total(api_client.list_jurisdictions(ADMIN)) == 0


def test_pinning_an_unminted_cost_document_is_not_found(api):
    """PRD §2.6: "Foreign keys supplied in a request body are resolved with the same codes, and a body foreign key that does not resolve is likewise a 404."
    PRD §2.6: "Body-level resolution happens after request-shape validation and before any business rule: a create that names a non-existent merchant is a 404, not a 422, even when the body would also have failed a later compliance check."

    Design: Corner/errors/unknown_cost_documentation_on_program_creation_returns_not_found
    """
    jurisdiction = create_jurisdiction("AZ")
    merchant = create_merchant(jurisdiction["id"])

    response = api_client.create_program(
        program_payload(
            merchant["id"], jurisdiction["id"], UNMINTED_UUID, "SURCHARGE", "BRAND_LEVEL"
        ),
        OFFICER_ONE,
    )
    validate_error(response, ApiErrorId.ERR_COST_DOCUMENTATION_NOT_FOUND)

    assert (
        list_total(api_client.list_programs(ADMIN, params={"merchant_id": merchant["id"]})) == 0
    )


def test_activating_an_unminted_program_is_not_found(api):
    """PRD §2.6: "Identifiers in a request path are resolved left to right, and the first one that does not resolve determines the rejection."
    PRD §2.9: "Checks are evaluated in the following fixed order, and the first failing check determines both the `error_id` and the HTTP status. Later checks are not evaluated once an earlier one has failed."

    Design: Corner/errors/unknown_program_on_activate_returns_not_found
    """
    response = api_client.activate_program(UNMINTED_UUID, OFFICER_ONE)
    validate_error(response, ApiErrorId.ERR_PROGRAM_NOT_FOUND)

    assert list_total(api_client.list_programs(ADMIN)) == 0


def test_deciding_an_unminted_registration_is_not_found(api):
    """PRD §2.6: "Each entity has its own not-found code: `ERR_JURISDICTION_NOT_FOUND`, `ERR_MERCHANT_NOT_FOUND`, `ERR_COST_DOCUMENTATION_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`, `ERR_ARTIFACT_NOT_FOUND`, `ERR_TERMINAL_NOT_FOUND`, `ERR_TRANSACTION_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, and `ERR_REFUND_NOT_FOUND`, each carrying HTTP 404."
    PRD §2.9: "**Declared transition available from the current state** — `ERR_INVALID_PROGRAM_STATE`, `ERR_INVALID_REGISTRATION_STATE`, `ERR_INVALID_ARTIFACT_STATE`, `ERR_INVALID_TERMINAL_STATE`, `ERR_INVALID_COMPLAINT_STATE`, or `ERR_INVALID_REFUND_STATE`, all 409. Applies to every state-changing operation."

    Design: Corner/errors/unknown_registration_on_decision_returns_not_found
    """
    response = api_client.decide_network_registration(
        UNMINTED_UUID, registration_decision_payload("ACKNOWLEDGE"), AUDITOR
    )
    validate_error(response, ApiErrorId.ERR_REGISTRATION_NOT_FOUND)

    assert list_total(api_client.list_network_registrations(ADMIN)) == 0


def test_attesting_an_unminted_artifact_is_not_found(api):
    """PRD §2.6: "Identifiers in a request path are resolved left to right, and the first one that does not resolve determines the rejection."
    PRD §2.9: "**Disclosure-window separation** — `ERR_DISCLOSURE_WINDOW_OVERLAP`, 409. Applies to artifact attestation."

    Design: Corner/errors/unknown_artifact_on_attest_returns_not_found
    """
    response = api_client.attest_disclosure_artifact(
        UNMINTED_UUID, attestation_payload(CLOCK_AUG_01, CLOCK_DEC_31), OFFICER_TWO
    )
    validate_error(response, ApiErrorId.ERR_ARTIFACT_NOT_FOUND)

    assert list_total(api_client.list_disclosure_artifacts(ADMIN)) == 0


def test_configuring_an_unminted_terminal_is_not_found(api):
    """PRD §2.6: "Identifiers in a request path are resolved left to right, and the first one that does not resolve determines the rejection."
    PRD §2.9: "**Merchant ownership** — a `MerchantOperator`'s `X-User-ID` equals the target's merchant: `ERR_MERCHANT_OWNERSHIP_REQUIRED`, 403. Applies to exactly four operations: provisioning a terminal under a merchant, configuring a terminal, driving a terminal's state action, and drafting a disclosure artifact for a program (where the comparison is against that program's `merchant_id`)."

    Design: Corner/errors/unknown_terminal_on_configure_returns_not_found
    """
    ctx = setup_draft_program(with_rate_rule=False)
    merchant_id = ctx["merchant"]["id"]

    response = api_client.configure_terminal(
        UNMINTED_UUID,
        terminal_configuration_payload(ctx["program"]["id"]),
        make_merchant_operator_headers(merchant_id),
    )
    validate_error(response, ApiErrorId.ERR_TERMINAL_NOT_FOUND)

    assert (
        list_total(api_client.list_terminals(ADMIN, params={"merchant_id": merchant_id})) == 0
    )


def test_reading_an_unminted_transaction_is_not_found(api):
    """PRD §2.6: "Each entity has its own not-found code: `ERR_JURISDICTION_NOT_FOUND`, `ERR_MERCHANT_NOT_FOUND`, `ERR_COST_DOCUMENTATION_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`, `ERR_ARTIFACT_NOT_FOUND`, `ERR_TERMINAL_NOT_FOUND`, `ERR_TRANSACTION_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, and `ERR_REFUND_NOT_FOUND`, each carrying HTTP 404."
    PRD §2.4: "A captured sale is an immutable event, not a mutable resource: a `Transaction` carries `id` and `created_at` only, and both `updated_at` and `version` are absent from its representation entirely."

    Design: Corner/errors/unknown_transaction_on_read_returns_not_found
    """
    response = api_client.get_transaction(UNMINTED_UUID, ADMIN)
    validate_error(response, ApiErrorId.ERR_TRANSACTION_NOT_FOUND)

    assert list_total(api_client.list_transactions(ADMIN)) == 0


def test_reviewing_an_unminted_complaint_is_not_found(api):
    """PRD §2.6: "Identifiers in a request path are resolved left to right, and the first one that does not resolve determines the rejection."
    PRD §2.9: "**Complaint channel ownership** — the acting role owns the case's `source` channel: `ERR_COMPLAINT_SOURCE_ROLE_MISMATCH`, 403. Applies to exactly three operations: filing a complaint, investigation actions, and remediation actions."

    Design: Corner/errors/unknown_complaint_case_on_investigation_action_returns_not_found
    """
    response = api_client.complaint_investigation_action(
        UNMINTED_UUID, investigation_action_payload("REVIEW"), OFFICER_ONE
    )
    validate_error(response, ApiErrorId.ERR_COMPLAINT_NOT_FOUND)

    assert list_total(api_client.list_complaint_cases(ADMIN)) == 0


def test_issuing_an_unminted_refund_is_not_found(api):
    """PRD §2.6: "Identifiers in a request path are resolved left to right, and the first one that does not resolve determines the rejection."
    PRD §2.9: "**Segregation of duties** — `ERR_SEGREGATION_OF_DUTIES`, 403. Applies to exactly two operations: program activation and refund issuance."

    Design: Corner/errors/unknown_refund_on_issue_returns_not_found
    """
    response = api_client.issue_refund(UNMINTED_UUID, OFFICER_TWO)
    validate_error(response, ApiErrorId.ERR_REFUND_NOT_FOUND)

    assert list_total(api_client.list_refunds(ADMIN)) == 0


def test_a_second_jurisdiction_for_the_same_state_is_refused(api):
    """PRD §3.1: "No two jurisdictions may share a `state_code`; a second registration for the same code is rejected with `ERR_DUPLICATE_JURISDICTION_STATE`."
    PRD §3.1: "Finally `ag_enforcement_posture` records how aggressive the state's attorney general is, as one of `PERMISSIVE`, `MONITORED`, or `RESTRICTIVE`; that posture becomes a multiplier in the attorney-general exposure calculation of §3.10."

    Design: Corner/errors/second_jurisdiction_with_the_same_state_code_is_rejected
    """
    first = create_jurisdiction("AZ")

    response = api_client.create_jurisdiction(
        jurisdiction_payload(
            "CT",
            state_code="AZ",
            cash_discount_permitted=False,
            receipt_line_item_required=True,
        ),
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_JURISDICTION_STATE)

    rows = list_items(api_client.list_jurisdictions(ADMIN, params={"state_code": "AZ"}))
    assert len(rows) == 1
    assert rows[0]["id"] == first["id"]
    assert rows[0]["ag_enforcement_posture"] == "PERMISSIVE"
    assert rows[0]["cash_discount_permitted"] is True


def test_a_repeated_serial_under_one_merchant_is_refused(api):
    """PRD §3.8: "Serial numbers are unique per merchant: a second terminal with the same `serial_number` under the same merchant is rejected with `ERR_DUPLICATE_TERMINAL_SERIAL`, while two different merchants may legitimately hold the same serial."
    PRD §2.9: "**Uniqueness** — `ERR_DUPLICATE_JURISDICTION_STATE`, `ERR_DUPLICATE_TERMINAL_SERIAL`, and `ERR_DUPLICATE_NETWORK_REGISTRATION`, all 409. Applies to jurisdiction registration, terminal provisioning, and registration submission respectively."

    Design: Corner/errors/second_terminal_with_the_same_serial_under_one_merchant_is_rejected
    """
    jurisdiction = create_jurisdiction("AZ")
    merchant = create_merchant(jurisdiction["id"])
    first = provision_terminal(merchant["id"], "TRM-AZ-7301")

    response = api_client.create_terminal(
        merchant["id"],
        terminal_payload("TRM-AZ-7301"),
        make_merchant_operator_headers(merchant["id"]),
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_TERMINAL_SERIAL)

    rows = list_items(
        api_client.list_terminals(ADMIN, params={"merchant_id": merchant["id"]})
    )
    assert len(rows) == 1
    assert rows[0]["id"] == first["id"]
    assert rows[0]["state"] == "PROVISIONED"


def test_a_second_live_registration_for_the_same_network_is_refused(api):
    """PRD §3.5: "A program may hold at most one registration per network that is still live — that is, in state `SUBMITTED`, `ACKNOWLEDGED`, or `EFFECTIVE` — and a second submission for the same network while one of those is outstanding is rejected with `ERR_DUPLICATE_NETWORK_REGISTRATION`."
    PRD §3.5: "A registration that ended in `REJECTED` or `REVOKED` does not block a fresh submission for that network."

    Design: Corner/errors/second_registration_for_the_same_network_is_rejected
    """
    ctx = setup_program_pending_registration(registration_ref="VS-2940-AZ-481")
    program_id = ctx["program"]["id"]
    assert ctx["registration"]["state"] == "SUBMITTED"

    response = api_client.create_network_registration(
        program_id, network_registration_payload("VISA", "VS-2940-AZ-482"), OFFICER_ONE
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_NETWORK_REGISTRATION)

    rows = list_items(
        api_client.list_network_registrations(ADMIN, params={"program_id": program_id})
    )
    assert len(rows) == 1
    assert rows[0]["id"] == ctx["registration"]["id"]
    assert rows[0]["registration_ref"] == "VS-2940-AZ-481"


def test_the_error_envelope_carries_only_an_id_and_a_message(api):
    """PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/errors/error_envelope_carries_response_type_error_with_id_and_message
    """
    response = api_client.get_program(UNMINTED_UUID, OFFICER_ONE)
    error_data = validate_error(response, ApiErrorId.ERR_PROGRAM_NOT_FOUND)
    assert response.status_code == 404

    body = response.json()
    assert body["response_type"] == "error"
    assert set(error_data.keys()) == {"error_id", "message"}
    assert isinstance(error_data["message"], str)
    assert error_data["message"].strip() != ""
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}


def test_a_sale_against_a_withdrawn_program_reports_the_prohibition(api):
    """PRD §2.9: "**Program is not prohibited or withdrawn** — a sale may not be booked against a program in status `DISABLED` or `WITHDRAWN`: `ERR_PROGRAM_DISABLED_BY_PROHIBITION`, 422. Applies to sale capture."
    PRD §3.9: "The program must not be in status `DISABLED` or `WITHDRAWN`, else `ERR_PROGRAM_DISABLED_BY_PROHIBITION`."

    Design: Corner/errors/sale_booked_against_a_withdrawn_program_is_rejected
    """
    ctx = setup_enforcing_surcharge_estate(serial_prefix="TRM-AZ-")
    terminal_id = ctx["terminal"]["id"]
    sibling = create_program(
        ctx["merchant"]["id"],
        ctx["jurisdiction"]["id"],
        ctx["cost_documentation"]["id"],
        "SURCHARGE",
        "BRAND_LEVEL",
    )
    program_status_action(sibling["id"], "WITHDRAW", reason="the second filing was abandoned")

    response = api_client.create_transaction(
        transaction_payload(terminal_id, sibling["id"]),
        make_terminal_agent_headers(terminal_id),
    )
    validate_error(response, ApiErrorId.ERR_PROGRAM_DISABLED_BY_PROHIBITION)

    assert read_program(sibling["id"])["status"] == "WITHDRAWN"
    terminal = read_terminal(terminal_id)
    assert terminal["state"] == "ENFORCING"
    assert terminal["program_id"] == ctx["program"]["id"]
    assert list_total(api_client.list_transactions(ADMIN)) == 0


def test_a_sale_citing_a_sibling_draft_program_reports_the_binding(api):
    """PRD §2.9: "**Terminal-program agreement** — the terminal's `program_id` equals the body `program_id`: `ERR_TERMINAL_PROGRAM_MISMATCH`, 422. Applies to sale capture and to terminal configuration."
    PRD §3.9: "The terminal's stored `program_id` must equal the body's `program_id`, else `ERR_TERMINAL_PROGRAM_MISMATCH` — a terminal cannot book against a program it is not configured for, even if that program is perfectly healthy."

    Design: Corner/errors/sale_booked_against_a_sibling_draft_program_is_rejected
    """
    ctx = setup_enforcing_surcharge_estate(serial_prefix="TRM-AZ-")
    terminal_id = ctx["terminal"]["id"]
    sibling = create_program(
        ctx["merchant"]["id"],
        ctx["jurisdiction"]["id"],
        ctx["cost_documentation"]["id"],
        "SURCHARGE",
        "BRAND_LEVEL",
    )
    assert sibling["status"] == "DRAFT"

    response = api_client.create_transaction(
        transaction_payload(terminal_id, sibling["id"]),
        make_terminal_agent_headers(terminal_id),
    )
    validate_error(response, ApiErrorId.ERR_TERMINAL_PROGRAM_MISMATCH)

    terminal = read_terminal(terminal_id)
    assert terminal["state"] == "ENFORCING"
    assert terminal["program_id"] == ctx["program"]["id"]
    assert (
        list_total(api_client.list_transactions(ADMIN, params={"terminal_id": terminal_id})) == 0
    )
