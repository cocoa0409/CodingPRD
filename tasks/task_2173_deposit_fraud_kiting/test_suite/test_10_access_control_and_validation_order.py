"""Authentication, role authorisation, ownership, not-found codes and the ladder."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_same_instant,
    assert_three_fractional_digits,
    build_user_headers,
    create_active_account,
    first_hold,
    make_account_holder_headers,
    new_account,
    new_customer,
    open_override_review,
    read_account,
    read_review,
    submit_override_review,
    take_deposit,
    validate_error,
    validate_paginated,
    validate_success,
)

SUPERVISOR = TEST_USERS["supervisor_headers"]
ANALYST = TEST_USERS["analyst_headers"]
OPS = TEST_USERS["ops_admin_headers"]
COUNSEL = TEST_USERS["counsel_headers"]


# ===========================================================================
# The state gate outranks the fiscal authority gate
# ===========================================================================
def _submitted_review_above_the_supervisor_authority():
    """A 20022500-cent CHECK leaves 20000000 held on a STANDARD-band account.

    20000000 * 275 / 10000 = 550000, and the STANDARD multiplier leaves it there —
    above the 500,000-cent supervisor authority.
    """
    scenario = create_active_account(
        legal_name="Corinne Baptiste", tin_last4="2020", kyc_tier="TIER_2",
        watchlist_hit=False, product_type="CHECKING", open_channel="BRANCH",
    )
    item = take_deposit(scenario["account_id"], item_type="CHECK", amount_cents=20022500)
    hold = first_hold(item["id"], ANALYST)
    review = open_override_review(
        hold["id"], hold["version"],
        requested_release_cents=20000000,
        release_effective_at="2026-08-01T00:00:00Z",
        release_window_end_at="2026-08-02T00:00:00Z",
        justification="Commercial customer, wire settlement expected",
    )
    submit_override_review(review["id"])
    scenario.update({"item": item, "hold": hold, "review": review, "review_id": review["id"]})
    return scenario


def test_executing_a_submitted_review_reports_the_state_error_not_the_fiscal_one(
    api, analyst_headers
):
    """PRD §2.10: "9. **Entity state gates** — the "is this resource in a state
    that admits this operation" family, described alongside each workflow in §3 and
    reported as `ERR_ACCOUNT_NOT_ACTIVE`, `ERR_FUNDING_INVALID_STATE`,
    `ERR_ITEM_ALREADY_SETTLED`, `ERR_HOLD_NOT_ACTIVE`, `ERR_REVIEW_NOT_SUBMITTED`,
    `ERR_REVIEW_NOT_APPROVED`, `ERR_CASE_INVALID_STATE`,
    `ERR_CASE_NOT_SUBSTANTIATED`, `ERR_REFERRAL_INVALID_STATE`,
    `ERR_CHARGE_OFF_INVALID_STATE`, or `ERR_SUBPOENA_INVALID_STATE`."
    PRD §2.10: "19. **Fiscal limits,** last and at the same rank:
    `ERR_RELEASE_EXCEEDS_HOLD`, `ERR_EXPOSURE_EXCEEDS_AUTHORITY`,
    `ERR_NO_NET_LOSS`, and `ERR_RECOVERY_EXCEEDS_LOSS`."
    PRD §3.4: "The review must be in `APPROVED`, else `ERR_REVIEW_NOT_APPROVED`
    (HTTP 409); the hold must still be `ACTIVE`, else `ERR_HOLD_NOT_ACTIVE`;
    `requested_release_cents` must still be no greater than the hold's current
    `held_amount_cents`, else `ERR_RELEASE_EXCEEDS_HOLD`; and
    `adjusted_exposure_cents` must still be within the 500,000-cent authority, else
    `ERR_EXPOSURE_EXCEEDS_AUTHORITY`."

    Design: Difficulty/priority_pair_validation_conflict/execute_state_check_outranks_exposure_authority_check
    """
    scenario = _submitted_review_above_the_supervisor_authority()
    assert scenario["hold"]["held_amount_cents"] == 20000000
    assert scenario["review"]["adjusted_exposure_cents"] == 550000, (
        "550000 is above the 500,000-cent supervisor authority"
    )

    validate_error(
        api.execute_override_review(scenario["review_id"], SUPERVISOR),
        ApiErrorId.ERR_REVIEW_NOT_APPROVED.value,
    )

    assert read_review(scenario["review_id"], analyst_headers)["status"] == "SUBMITTED"


def test_the_fiscal_authority_gate_fires_once_the_state_gate_is_satisfied(api, analyst_headers):
    """PRD §3.4: "An approval carries one extra fiscal gate:
    `adjusted_exposure_cents` must be less than or equal to 500,000 cents — a
    supervisor's authority runs to $5,000.00 of adjusted exposure — and an approval
    above it is refused with `ERR_EXPOSURE_EXCEEDS_AUTHORITY` (HTTP 422). Denials
    and returns are not subject to that limit."
    PRD §3.4: "`adjusted_exposure_cents` is `loss_exposure_cents` multiplied by the
    account's risk-band multiplier, divided by 10,000, and rounded half up to whole
    cents a second time. The multipliers are 10,000 basis points for a `STANDARD`
    band — that is, no adjustment — 12,500 basis points for `ELEVATED`, and 16,000
    basis points for `HIGH`."

    Design: Difficulty/priority_pair_validation_conflict/execute_state_check_outranks_exposure_authority_check
    """
    scenario = _submitted_review_above_the_supervisor_authority()

    validate_error(
        api.decide_override_review(
            scenario["review_id"],
            {"decision": "APPROVE", "decision_note": "Attempted approval"},
            SUPERVISOR,
        ),
        ApiErrorId.ERR_EXPOSURE_EXCEEDS_AUTHORITY.value,
    )

    review = read_review(scenario["review_id"], analyst_headers)
    assert review["status"] == "SUBMITTED", "The refused approval left the review where it was"
    assert review["loss_exposure_cents"] == 550000


# ===========================================================================
# Each collection reports its own not-found code
# ===========================================================================
def test_every_path_collection_reports_its_own_not_found_code(api, analyst_headers):
    """PRD §2.10: "3. **Path existence.** Every `id` appearing in the request path
    resolves to a stored row, validated left to right, so on a nested path the
    outer segment is resolved before the inner one. The failure carries the code for
    the resource kind that failed: `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_ACCOUNT_NOT_FOUND`, `ERR_FUNDING_SOURCE_NOT_FOUND`,
    `ERR_DEPOSIT_ITEM_NOT_FOUND`, `ERR_CHECK_HOLD_NOT_FOUND`,
    `ERR_REVIEW_NOT_FOUND`, `ERR_FRAUD_CASE_NOT_FOUND`,
    `ERR_CHARGE_OFF_NOT_FOUND`, `ERR_SUBPOENA_NOT_FOUND`, or
    `ERR_BSA_REFERRAL_NOT_FOUND` (all HTTP 404)."

    Design: Corner/entities/unknown_ids_on_every_path_collection_return_their_own_not_found_error
    """
    validate_error(
        api.get_customer("11111111-1111-4111-8111-111111111111", analyst_headers),
        ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value,
    )
    validate_error(
        api.get_account("22222222-2222-4222-8222-222222222222", analyst_headers),
        ApiErrorId.ERR_ACCOUNT_NOT_FOUND.value,
    )
    validate_error(
        api.resend_micro_deposits("33333333-3333-4333-8333-333333333333", OPS),
        ApiErrorId.ERR_FUNDING_SOURCE_NOT_FOUND.value,
    )
    validate_error(
        api.get_deposit_item("44444444-4444-4444-8444-444444444444", analyst_headers),
        ApiErrorId.ERR_DEPOSIT_ITEM_NOT_FOUND.value,
    )
    validate_error(
        api.get_check_hold("55555555-5555-4555-8555-555555555555", analyst_headers),
        ApiErrorId.ERR_CHECK_HOLD_NOT_FOUND.value,
    )
    validate_error(
        api.get_override_review("66666666-6666-4666-8666-666666666666", analyst_headers),
        ApiErrorId.ERR_REVIEW_NOT_FOUND.value,
    )
    validate_error(
        api.get_fraud_case("77777777-7777-4777-8777-777777777777", analyst_headers),
        ApiErrorId.ERR_FRAUD_CASE_NOT_FOUND.value,
    )
    validate_error(
        api.get_charge_off("88888888-8888-4888-8888-888888888888", analyst_headers),
        ApiErrorId.ERR_CHARGE_OFF_NOT_FOUND.value,
    )
    validate_error(
        api.get_subpoena("99999999-9999-4999-8999-999999999999", COUNSEL),
        ApiErrorId.ERR_SUBPOENA_NOT_FOUND.value,
    )
    validate_error(
        api.submit_bsa_referral("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", analyst_headers),
        ApiErrorId.ERR_BSA_REFERRAL_NOT_FOUND.value,
    )


# ===========================================================================
# Authentication and role authorisation
# ===========================================================================
def test_an_undeclared_role_fails_authentication_before_any_later_check(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying
    the caller, and `X-User-Role`, naming the caller's role. If either header is
    absent, or if `X-User-Role` is not one of the six declared roles, the request is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401). This is the very first thing
    evaluated on every endpoint without exception."
    PRD §2.10: "1. **Authentication.** Both headers present and `X-User-Role` a
    declared role, else `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/unrecognised_role_header_returns_unauthenticated_before_any_other_check
    """
    unknown_role = build_user_headers("aud-1", "Auditor")
    validate_error(
        api.get_account("cccccccc-cccc-4ccc-8ccc-cccccccccccc", unknown_role),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )

    missing_role = {"X-User-ID": "aud-1", "Content-Type": "application/json"}
    validate_error(
        api.get_account("cccccccc-cccc-4ccc-8ccc-cccccccccccc", missing_role),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )


def test_the_bsa_officer_may_not_open_a_case_or_take_a_deposit(api, bsa_officer_headers,
                                                                analyst_headers):
    """PRD §2.1: "If the caller's role is present and well-formed but is not one of
    the roles authorised for the endpoint it is calling — the authorised set for
    each endpoint is listed in §4 — the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.1: "`BsaOfficer` belongs to the Bank Secrecy Act unit and adjudicates
    the referrals the fraud unit files. It holds no write authority over accounts,
    holds, cases, or charge-offs; its only mutating capability is referral
    adjudication."

    Design: Corner/rbac/bsa_officer_cannot_open_a_fraud_case_or_take_a_deposit
    """
    scenario = create_active_account(legal_name="Role Boundary Depositor", tin_last4="0038")

    validate_error(
        api.create_fraud_case(
            {"primary_account_id": scenario["account_id"], "case_type": "MULE"},
            bsa_officer_headers,
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )
    validate_error(
        api.create_deposit_item(
            scenario["account_id"], {"item_type": "CHECK", "amount_cents": 30000},
            bsa_officer_headers,
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )

    case = validate_success(
        api.create_fraud_case(
            {"primary_account_id": scenario["account_id"], "case_type": "MULE"}, analyst_headers
        ),
        201,
    )
    assert case["status"] == "OPENED", "The identical call succeeds for a FraudAnalyst"

    _rows, meta = validate_paginated(
        api.list_account_deposit_items(scenario["account_id"], analyst_headers)
    )
    assert meta["total_count"] == 0, "The refused deposit created nothing"


def test_an_account_holder_may_read_only_their_own_account(api):
    """PRD §2.1: "Role identity is interpreted in one of two ways. When
    `X-User-Role` is `AccountHolder`, `X-User-ID` is the `id` of the acting
    `Customer`; ownership checks on any resource that references a `Customer`
    compare the resource's `customer_id` to `X-User-ID`. Concretely, an
    `AccountHolder` reading a deposit account, or answering that account's step-up
    challenge, must have an `X-User-ID` equal to that account's `customer_id`;
    otherwise the request is rejected with `ERR_NOT_ACCOUNT_OWNER` (HTTP 403)."
    PRD §2.10: "6. **Ownership.** When the caller is an `AccountHolder`,
    `X-User-ID` equals the `customer_id` of the account named in the path, else
    `ERR_NOT_ACCOUNT_OWNER`. This applies to reading a single deposit account and
    to answering a step-up challenge."

    Design: Corner/rbac/account_holder_cannot_read_another_customers_account
    """
    owner_one = new_customer(legal_name="Owner One", tin_last4="0039")
    owner_two = new_customer(legal_name="Owner Two", tin_last4="0040")
    account_one = new_account(owner_one["id"], product_type="CHECKING", open_channel="BRANCH")
    account_two = new_account(owner_two["id"], product_type="CHECKING", open_channel="BRANCH")

    holder_one = make_account_holder_headers(owner_one["id"])

    own = validate_success(api.get_account(account_one["id"], holder_one))
    assert own["lifecycle_status"] == "PENDING_FUNDING"

    validate_error(
        api.get_account(account_two["id"], holder_one),
        ApiErrorId.ERR_NOT_ACCOUNT_OWNER.value,
    )


# ===========================================================================
# The logical clock's fixed default
# ===========================================================================
def test_the_logical_clock_reads_its_fixed_default_before_any_set_call(api, ops_admin_headers,
                                                                       analyst_headers):
    """PRD §2.5: "Before the clock is ever set, it reads exactly
    `2026-08-01T00:00:00Z`. It never falls back to real wall-clock time."
    PRD §3.1: "The server stamps `opened_at` from the logical clock; this instant,
    and not `created_at`, is the baseline for the new-account availability exception
    described in §3.3."
    PRD §2.5: "An `OperationsAdmin` may move the clock by supplying a `to_iso8601`
    instant; the response reports the clock's new value as `current_utc`."
    PRD §2.4: "`created_at` and `updated_at` are ISO 8601 UTC timestamps with three
    fractional digits, taken from the logical clock described in §2.5."

    Design: Corner/endpoints/logical_clock_reads_its_fixed_default_before_any_set_call
    """
    customer = new_customer(legal_name="Default Clock Depositor", tin_last4="0035")

    account = validate_success(
        api.create_account(
            {"customer_id": customer["id"], "product_type": "CHECKING", "open_channel": "BRANCH"},
            ops_admin_headers,
        ),
        201,
    )
    assert_same_instant(account["opened_at"], "2026-08-01T00:00:00Z", "opened_at")

    clock = validate_success(
        api.set_clock({"to_iso8601": "2026-08-01T00:00:00Z"}, ops_admin_headers)
    )
    assert_same_instant(clock["current_utc"], "2026-08-01T00:00:00Z", "current_utc")

    reread = read_account(account["id"], analyst_headers)
    assert_same_instant(reread["created_at"], "2026-08-01T00:00:00Z", "created_at")
    assert_three_fractional_digits(reread["created_at"], "created_at")
