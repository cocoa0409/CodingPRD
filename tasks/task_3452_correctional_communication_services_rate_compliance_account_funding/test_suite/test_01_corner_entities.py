"""Corner coverage: entity creation defaults, system fields, conditional
required fields, entity-specific not-found, append-only ledger shape, and
list pagination (PRD §2.3, §2.5, §2.9, §3.1, §3.3, §3.4).
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_account,
    assert_facility,
    assert_funding_transaction,
    assert_ledger_balance,
    assert_recipient_number,
    book_inmate,
    create_account_payload,
    create_facility_raw,
    create_recipient_number_payload,
    get_account,
    get_ledger,
    make_account_holder_headers,
    open_account,
    setup_funded_account,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_facility_create_applies_defaults_and_system_fields(
    api, platform_admin_headers
):
    """PRD §3.1: "Two further fields are optional: `video_turnover_minutes`, a cleaning and turnover buffer extending both sides of every confirmed session for capacity counting, which defaults to 10, and `daily_session_limit_per_inmate`, the maximum number of confirmed sessions one inmate may hold on a single UTC date, which defaults to 2. A new facility is born `ONBOARDING`."
    PRD §2.5: "`id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. `updated_at` is the same kind of timestamp, refreshed on every mutation of the resource."

    Design: Corner/entities/facility_create_applies_defaults_and_system_fields
    """
    payload = {
        "name": "Defaults Facility",
        "state_code": "ST",
        "video_booth_count": 3,
        "max_session_minutes": 30,
        "visiting_open_minutes": 480,
        "visiting_close_minutes": 1200,
    }
    resp = api.create_facility(payload, platform_admin_headers)
    body = resp.json()
    assert body["response_type"] == "object"
    facility = validate_success(resp, 201)
    assert_facility(facility)
    assert facility["video_turnover_minutes"] == 10, (
        f"default video_turnover_minutes must be 10, got "
        f"{facility['video_turnover_minutes']}"
    )
    assert facility["daily_session_limit_per_inmate"] == 2, (
        f"default daily_session_limit_per_inmate must be 2, got "
        f"{facility['daily_session_limit_per_inmate']}"
    )
    assert facility["status"] == "ONBOARDING"
    assert facility["id"] and facility["created_at"] and facility["updated_at"]


def test_account_create_collect_without_credit_limit_returns_invalid_request(
    api, facility_staff_headers, compliance_officer_headers
):
    """PRD §3.3: "A `COLLECT` account must also declare `collect_credit_limit_cents`, its receivable ceiling; omitting it is rejected with `ERR_INVALID_REQUEST`, while for the other two funding models the field is simply ignored. New accounts start `ACTIVE` with `escheat_status` `NONE` and an empty ledger."

    Design: Corner/entities/account_create_collect_without_credit_limit_returns_invalid_request
    """
    facility = create_facility_raw(name="Collect Facility")
    inmate = book_inmate(facility["id"])

    missing = api.create_account(
        create_account_payload(
            facility["id"], inmate["id"], funding_model="COLLECT"
        ),
        facility_staff_headers,
    )
    validate_error(missing, ApiErrorId.ERR_INVALID_REQUEST)

    created = api.create_account(
        create_account_payload(
            facility["id"],
            inmate["id"],
            funding_model="COLLECT",
            collect_credit_limit_cents=20000,
        ),
        facility_staff_headers,
    )
    account = validate_success(created, 201)
    assert_account(account)
    assert account["collect_credit_limit_cents"] == 20000
    assert account["status"] == "ACTIVE"
    assert account["escheat_status"] == "NONE"
    assert account["balance_cents"] == 0

    rows, meta = validate_paginated(
        api.list_accounts(
            compliance_officer_headers, params={"inmate_id": inmate["id"]}
        )
    )
    assert meta["total_count"] == 1 and len(rows) == 1, (
        "exactly one account must persist for the inmate "
        "(the rejected creation stored nothing)"
    )


def test_regulatory_cap_get_unknown_id_returns_cap_not_found(
    api, state_regulator_headers
):
    """PRD §2.9: "Each entity has its own not-found error, all HTTP 404: `ERR_FACILITY_NOT_FOUND`, `ERR_REGULATORY_CAP_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_RATE_SCHEDULE_NOT_FOUND`, `ERR_INMATE_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_RECIPIENT_NUMBER_NOT_FOUND`, `ERR_CALL_NOT_FOUND`, `ERR_VIDEO_SESSION_NOT_FOUND`, `ERR_MESSAGE_NOT_FOUND`, `ERR_REFUND_REQUEST_NOT_FOUND`, and `ERR_COMPLAINT_NOT_FOUND`."

    Design: Corner/entities/regulatory_cap_get_unknown_id_returns_cap_not_found
    """
    resp = api.get_regulatory_cap(NON_EXISTENT_UUID, state_regulator_headers)
    err = validate_error(resp, ApiErrorId.ERR_REGULATORY_CAP_NOT_FOUND)
    assert resp.status_code == 404
    assert err["message"].strip(), "error body must carry a human-readable message"


def test_recipient_create_attorney_auto_enters_privilege_requested(api):
    """PRD §3.4: "Registering an `ATTORNEY` or `LEGAL_AID` contact automatically enters `privilege_status` `PRIVILEGE_REQUESTED`; all other relationship types start at `NONE`, and `privilege_decision_note` stays null until a compliance officer rules."
    PRD §3.4: "A new recipient number starts with `verification_status` `VERIFICATION_SENT`, `block_status` `NOT_BLOCKED`, `consent_to_recording` false, and `block_reason` null; the server generates a six-digit `verification_code` and returns it in the creation response so it can be delivered to the recipient."

    Design: Corner/entities/recipient_create_attorney_auto_enters_privilege_requested
    """
    facility = create_facility_raw(name="Priv Facility")
    inmate = book_inmate(facility["id"])
    account = open_account(facility["id"], inmate["id"])
    holder = make_account_holder_headers(account["id"])

    atty = validate_success(
        api.create_recipient_number(
            create_recipient_number_payload(
                account["id"], label="Atty Rivera", relationship_type="ATTORNEY"
            ),
            holder,
        ),
        201,
    )
    fam = validate_success(
        api.create_recipient_number(
            create_recipient_number_payload(
                account["id"], label="Mom", relationship_type="FAMILY"
            ),
            holder,
        ),
        201,
    )
    assert_recipient_number(atty)
    assert_recipient_number(fam)
    assert atty["privilege_status"] == "PRIVILEGE_REQUESTED"
    assert isinstance(atty["verification_code"], str) and atty["verification_code"]
    assert fam["privilege_status"] == "NONE"
    for rec in (atty, fam):
        assert rec["verification_status"] == "VERIFICATION_SENT"
        assert rec["block_status"] == "NOT_BLOCKED"
        assert rec["consent_to_recording"] is False


def test_funding_transaction_rows_are_immutable_and_versionless(api):
    """PRD §2.5: "A `FundingTransaction` row carries only `id` and `created_at` — `updated_at` and `version` are absent because ledger rows are never modified or deleted: the ledger is append-only."
    PRD §3.3: "Each accepted deposit appends two ledger entries in order: a `DEPOSIT` credit of the full `amount_cents`, then a `DEPOSIT_FEE` debit of the fee, after which the balance is recomputed from the ledger."

    Design: Corner/entities/funding_transaction_rows_are_immutable_and_versionless
    """
    env = setup_funded_account(deposit_amount=100)
    account_id = env["account"]["id"]

    rows = get_ledger(account_id)
    assert len(rows) == 2, f"expected exactly 2 ledger rows, got {len(rows)}"
    for row in rows:
        assert_funding_transaction(row)
    assert rows[0]["type"] == "DEPOSIT" and rows[0]["amount_cents"] == 100
    assert rows[1]["type"] == "DEPOSIT_FEE" and rows[1]["amount_cents"] == -25

    account = get_account(account_id)
    assert account["balance_cents"] == 75
    assert_ledger_balance(account, rows)


def test_accounts_list_paginates_with_total_count_and_has_more(
    api, compliance_officer_headers
):
    """PRD §2.3: "`limit` sets the maximum number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0."
    PRD §2.3: "Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order, and the `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.3: "accounts by `facility_id`, `inmate_id`, `funding_model`, `status`, or `escheat_status`"

    Design: Corner/entities/accounts_list_paginates_with_total_count_and_has_more
    """
    facility = create_facility_raw(name="Paging Facility")
    inmate = book_inmate(facility["id"])
    open_account(facility["id"], inmate["id"], funding_model="PREPAID")
    open_account(facility["id"], inmate["id"], funding_model="PREPAID")
    open_account(facility["id"], inmate["id"], funding_model="DEBIT")

    page1, meta1 = validate_paginated(
        api.list_accounts(
            compliance_officer_headers,
            params={"facility_id": facility["id"], "limit": 2, "offset": 0},
        )
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3 and meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_accounts(
            compliance_officer_headers,
            params={"facility_id": facility["id"], "limit": 2, "offset": 2},
        )
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3 and meta2["has_more"] is False

    debit, meta3 = validate_paginated(
        api.list_accounts(
            compliance_officer_headers,
            params={"facility_id": facility["id"], "funding_model": "DEBIT"},
        )
    )
    assert len(debit) == 1 and meta3["total_count"] == 1

    all_rows, meta4 = validate_paginated(
        api.list_accounts(
            compliance_officer_headers, params={"facility_id": facility["id"]}
        )
    )
    assert len(all_rows) == 3
    assert meta4["limit"] == 10 and meta4["offset"] == 0
