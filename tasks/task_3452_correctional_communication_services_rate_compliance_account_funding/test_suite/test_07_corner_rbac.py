"""Corner coverage: role authorization and entity-backed ownership —
forbidden roles on staff/compliance operations and the AccountHolder
identity-equals-account-id rule (PRD §2.1, §4).
"""
from test_helpers import (
    ApiErrorId,
    book_inmate,
    create_call_payload,
    create_message,
    deposit,
    get_account,
    get_success_data,
    make_account_holder_headers,
    open_account,
    setup_active_facility,
    setup_call_ready_account,
    setup_closed_account_with_refund,
    validate_error,
)


def test_facility_staff_cannot_decide_refund_requests(
    api, facility_staff_headers, compliance_officer_headers
):
    """PRD §2.1: "Once authenticated, the caller's role must appear in the target endpoint's authorized role list; otherwise the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
    PRD §3.8: "Adjudication belongs to a `ComplianceOfficer` acting under segregation of duties."

    Design: Corner/rbac/facility_staff_cannot_decide_refund_requests
    """
    env = setup_closed_account_with_refund(close_as_staff=True)
    refund_request = env["refund_request"]
    assert refund_request is not None and refund_request["status"] == "REQUESTED"

    resp = api.decide_refund_request(
        refund_request["id"], "APPROVE", facility_staff_headers
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
    assert resp.status_code == 403

    reread = get_success_data(
        api.get_refund_request(refund_request["id"], compliance_officer_headers)
    )
    assert reread["status"] == "REQUESTED"


def test_account_holder_cannot_operate_calls_or_review_messages(api):
    """PRD §2.1: "Once authenticated, the caller's role must appear in the target endpoint's authorized role list; otherwise the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
    PRD §3.5: "A call begins when `FacilityStaff` connect one, supplying `account_id`, `inmate_id`, `recipient_number_id`, and the `call_type` — `LOCAL`, `INTRASTATE`, `INTERSTATE`, or `INTERNATIONAL`."
    PRD §3.6: "Content review is performed by `FacilityStaff`."

    Design: Corner/rbac/account_holder_cannot_operate_calls_or_review_messages
    """
    env = setup_call_ready_account()
    account, inmate, recipient = env["account"], env["inmate"], env["recipient"]
    holder = make_account_holder_headers(account["id"])
    message = create_message(account, inmate, "hello")

    call_attempt = api.create_call(
        create_call_payload(
            account["id"], inmate["id"], recipient["id"], call_type="LOCAL"
        ),
        holder,
    )
    validate_error(call_attempt, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
    assert call_attempt.status_code == 403

    review_attempt = api.review_message(message["id"], "APPROVE", holder)
    validate_error(review_attempt, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
    assert review_attempt.status_code == 403

    reread = get_success_data(api.get_message(message["id"], holder))
    assert reread["status"] == "PENDING_REVIEW"


def test_account_holder_deposit_into_another_account_denied(api):
    """PRD §2.1: "When `X-User-Role` is `AccountHolder`, `X-User-ID` is the `id` of the acting `Account`; ownership checks on any resource that references an `Account` compare the resource's account foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/account_holder_deposit_into_another_account_denied
    """
    env = setup_active_facility()
    inmate_a = book_inmate(env["facility"]["id"], full_name="Inmate A3")
    inmate_b = book_inmate(env["facility"]["id"], full_name="Inmate B3")
    account_a = open_account(env["facility"]["id"], inmate_a["id"])
    account_b = open_account(env["facility"]["id"], inmate_b["id"])

    foreign_deposit = api.create_deposit(
        account_b["id"], 500, make_account_holder_headers(account_a["id"])
    )
    validate_error(foreign_deposit, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    assert foreign_deposit.status_code == 403
    assert get_account(account_b["id"])["balance_cents"] == 0, (
        "a rejected deposit appends no ledger entries"
    )

    own_deposit = deposit(account_b, 500)
    assert own_deposit["balance_cents"] == 475, (
        "control: the same deposit succeeds for the owning holder "
        "(500 - 25 deposit fee)"
    )
