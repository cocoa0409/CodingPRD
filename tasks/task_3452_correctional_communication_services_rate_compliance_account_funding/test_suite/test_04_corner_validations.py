"""Corner coverage: validation ordering and violation errors — header
presence vs existence, body-FK resolution order, suspended-account gates,
verification code vs consent, and both segregation-of-duties pairings
(PRD §2.1, §2.8, §2.9, §3.3, §3.4, §3.5, §3.8).
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    block_recipient,
    book_inmate,
    close_account,
    create_call_payload,
    create_recipient,
    create_verified_recipient,
    deposit,
    get_account,
    get_success_data,
    make_account_holder_headers,
    make_compliance_officer_headers,
    make_facility_staff_headers,
    make_recipient_party_headers,
    open_account,
    setup_active_facility,
    setup_call_ready_account,
    setup_funded_account,
    validate_error,
    validate_paginated,
    validate_success,
)

_BOGUS_ACCOUNT = "00000000-0000-4000-8000-000000000001"
_BOGUS_RECIPIENT = "00000000-0000-4000-8000-000000000002"


def test_call_missing_header_beats_not_found(api, facility_staff_headers):
    """PRD §2.8: "Incoming requests are checked against ten tiers of rules, evaluated in a fixed order; a request that fails several checks is always rejected with the error from the earliest tier it fails."
    PRD §2.8: "1. **Header presence.** `X-User-ID` and `X-User-Role` must be present and non-empty, and the role must be one of the six declared roles — otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. This applies to every endpoint."

    Design: Corner/validations/call_missing_header_beats_not_found
    """
    no_headers = api.get_account(NON_EXISTENT_UUID, headers=None)
    validate_error(no_headers, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    assert no_headers.status_code == 400

    with_headers = api.get_account(NON_EXISTENT_UUID, facility_staff_headers)
    validate_error(with_headers, ApiErrorId.ERR_ACCOUNT_NOT_FOUND)
    assert with_headers.status_code == 404


def test_call_body_fks_checked_in_declared_input_order(
    api, facility_staff_headers
):
    """PRD §2.9: "Body foreign keys are then resolved in the endpoint's declared input order, with the same per-entity behavior."
    PRD §3.5: "A call begins when `FacilityStaff` connect one, supplying `account_id`, `inmate_id`, `recipient_number_id`, and the `call_type` — `LOCAL`, `INTRASTATE`, `INTERSTATE`, or `INTERNATIONAL`."

    Design: Corner/validations/call_body_fks_checked_in_declared_input_order
    """
    env = setup_active_facility()
    inmate = book_inmate(env["facility"]["id"])
    account = open_account(env["facility"]["id"], inmate["id"])

    both_unknown = api.create_call(
        create_call_payload(
            _BOGUS_ACCOUNT, inmate["id"], _BOGUS_RECIPIENT, call_type="LOCAL"
        ),
        facility_staff_headers,
    )
    validate_error(both_unknown, ApiErrorId.ERR_ACCOUNT_NOT_FOUND)
    assert both_unknown.json()["data"]["error_id"] != (
        ApiErrorId.ERR_RECIPIENT_NUMBER_NOT_FOUND
    ), "account_id is declared before recipient_number_id, so its miss reports first"

    recipient_unknown = api.create_call(
        create_call_payload(
            account["id"], inmate["id"], _BOGUS_RECIPIENT, call_type="LOCAL"
        ),
        facility_staff_headers,
    )
    validate_error(recipient_unknown, ApiErrorId.ERR_RECIPIENT_NUMBER_NOT_FOUND)

    _rows, meta = validate_paginated(api.list_calls(facility_staff_headers))
    assert meta["total_count"] == 0, "neither rejected attempt may persist a call"


def test_suspended_account_blocks_deposit_but_close_still_works(
    api, facility_staff_headers
):
    """PRD §3.3: "`FacilityStaff` may suspend an account, moving it from `ACTIVE` to `SUSPENDED`, which blocks new deposits, calls, messages, and video sessions against it with `ERR_ACCOUNT_NOT_ACTIVE` — closing the account, however, remains allowed while it is suspended."
    PRD §3.8: "a staff- or holder-initiated close from `SUSPENDED` applies the same guards and the same bookkeeping as a close from `ACTIVE`, including the fee, which only the release auto-close waives."

    Design: Corner/validations/suspended_account_blocks_deposit_but_close_still_works
    """
    env = setup_funded_account()
    account = env["account"]

    suspended = validate_success(
        api.suspend_account(account["id"], facility_staff_headers)
    )
    assert suspended["status"] == "SUSPENDED"

    deposit_attempt = api.create_deposit(
        account["id"], 500, make_account_holder_headers(account["id"])
    )
    validate_error(deposit_attempt, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE)
    assert get_account(account["id"])["balance_cents"] == 1000

    closed = close_account(account)
    assert closed["status"] == "CLOSED"
    assert closed["refundable_computed_cents"] == 900, (
        "1000 balance - 100 closure fee under SIMPLE_BALANCE"
    )


def test_verify_wrong_code_and_missing_consent_are_distinct_errors(api):
    """PRD §3.4: "a code that does not match fails with `ERR_VERIFICATION_CODE_INVALID`, and consent that is not affirmatively true fails with `ERR_CONSENT_REQUIRED`, because recording consent gates every non-privileged call."

    Design: Corner/validations/verify_wrong_code_and_missing_consent_are_distinct_errors
    """
    env = setup_active_facility()
    inmate = book_inmate(env["facility"]["id"])
    account = open_account(env["facility"]["id"], inmate["id"])
    recipient = create_recipient(account["id"])
    party = make_recipient_party_headers(recipient["id"])

    real_code = recipient["verification_code"]
    wrong_code = "000000" if real_code != "000000" else "111111"

    bad_code = api.verify_recipient_number(
        recipient["id"], wrong_code, True, party
    )
    validate_error(bad_code, ApiErrorId.ERR_VERIFICATION_CODE_INVALID)

    no_consent = api.verify_recipient_number(
        recipient["id"], real_code, False, party
    )
    validate_error(no_consent, ApiErrorId.ERR_CONSENT_REQUIRED)

    reread = get_success_data(api.get_recipient_number(recipient["id"], party))
    assert reread["verification_status"] == "VERIFICATION_SENT"
    assert reread["consent_to_recording"] is False


def test_staff_requester_cannot_self_decide_and_decider_cannot_self_pay(api):
    """PRD §3.8: "Either decision is forbidden when the requester was staff rather than the account holder or the system and the deciding officer is the same person who requested the closure — that self-decision fails with `ERR_SOD_VIOLATION`."
    PRD §3.8: "Disbursement is a separate act by a `ComplianceOfficer`, and it carries its own segregation check: the payer's identity must differ from `decided_by_user_id` — a 'system' decider never conflicts — otherwise `ERR_SOD_VIOLATION`, and only an `APPROVED` request can be paid, anything else failing with `ERR_REFUND_NOT_PAYABLE`."

    Design: Corner/validations/staff_requester_cannot_self_decide_and_decider_cannot_self_pay
    """
    env = setup_active_facility()
    inmate = book_inmate(env["facility"]["id"])
    account = open_account(env["facility"]["id"], inmate["id"])
    staff_fs1 = make_facility_staff_headers("fs-1")

    validate_success(api.create_deposit(account["id"], 1025, staff_fs1), 201)
    closed = validate_success(api.close_account(account["id"], staff_fs1))
    refund_request_id = closed["latest_refund_request_id"]
    assert refund_request_id, "a positive refundable amount must open a request"

    self_decide = api.decide_refund_request(
        refund_request_id,
        "APPROVE",
        make_compliance_officer_headers("fs-1"),
    )
    validate_error(self_decide, ApiErrorId.ERR_SOD_VIOLATION)

    decided = validate_success(
        api.decide_refund_request(
            refund_request_id, "APPROVE", make_compliance_officer_headers("co-1")
        )
    )
    assert decided["status"] == "APPROVED"
    assert decided["computed_payout_cents"] == 900

    self_pay = api.mark_refund_paid(
        refund_request_id, make_compliance_officer_headers("co-1")
    )
    validate_error(self_pay, ApiErrorId.ERR_SOD_VIOLATION)

    paid = validate_success(
        api.mark_refund_paid(
            refund_request_id, make_compliance_officer_headers("co-2")
        )
    )
    assert paid["status"] == "PAID"


def test_suspended_account_with_blocked_recipient_reports_state_first(
    api, facility_staff_headers
):
    """PRD §2.8: "Incoming requests are checked against ten tiers of rules, evaluated in a fixed order; a request that fails several checks is always rejected with the error from the earliest tier it fails."
    PRD §2.8: "7. **Recipient consent and protection.** Connecting a call requires a verified, unblocked recipient whose recording consent has been captured — otherwise `ERR_NUMBER_NOT_VERIFIED` or `ERR_NUMBER_BLOCKED`. The attorney-privilege recording exemption is resolved at this tier, at connect time."

    Design: Corner/validations/suspended_account_with_blocked_recipient_reports_state_first
    """
    env = setup_call_ready_account()
    account, inmate, recipient = env["account"], env["inmate"], env["recipient"]
    block_recipient(recipient, reason="stop")
    validate_success(api.suspend_account(account["id"], facility_staff_headers))

    resp = api.create_call(
        create_call_payload(
            account["id"], inmate["id"], recipient["id"], call_type="LOCAL"
        ),
        facility_staff_headers,
    )
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE)
    assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_NUMBER_BLOCKED, (
        "state gates (tier 6) precede consent and protection (tier 7)"
    )

    _rows, meta = validate_paginated(
        api.list_calls(facility_staff_headers, params={"account_id": account["id"]})
    )
    assert meta["total_count"] == 0
