"""Error catalogue: authentication, negotiation turn, transfer-active close block."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, get_success_data,
    api_client, ApiErrorId,
    setup_retiring_advisor_with_transfer, set_clock, make_advisor_headers,
)

ADMIN = TEST_USERS["home_office_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_principal_headers"]


def test_unauthenticated_missing_headers():
    """PRD §2.1: "A request missing either header, or presenting a role string
    the system does not recognize, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/error_unauthenticated_missing_headers
    """
    from test_helpers import NON_EXISTENT_UUID
    validate_error(
        api_client.get_advisor(NON_EXISTENT_UUID, headers={}),
        ApiErrorId.ERR_UNAUTHENTICATED,
    )


def test_negotiation_turn_same_party_rejected():
    """PRD §3.7: "Within an ongoing negotiation the same party may not speak
    twice in a row: the acting advisor must not be the maker of the
    immediately preceding offer, and a violation is rejected with
    `ERR_NEGOTIATION_TURN`."

    Design: Corner/errors/error_negotiation_turn_same_party
    """
    transfer, retiring, successor, branch = setup_retiring_advisor_with_transfer()

    first = validate_success(api_client.counter_offer(
        transfer["id"],
        {"expected_transfer_version": transfer["version"], "offer_price_cents": 1700000},
        make_advisor_headers(successor["id"]),
    ))
    assert first["negotiation_round"] == 1

    # The successor speaks twice in a row.
    validate_error(
        api_client.counter_offer(
            transfer["id"],
            {
                "expected_transfer_version": first["version"],
                "offer_price_cents": 1650000,
            },
            make_advisor_headers(successor["id"]),
        ),
        ApiErrorId.ERR_NEGOTIATION_TURN,
    )

    fresh = get_success_data(api_client.get_goodwill_transfer(transfer["id"], ADMIN))
    assert fresh["negotiation_round"] == 1


def test_transfer_active_blocks_branch_close():
    """PRD §3.3: "Closing is terminal and available only from `SUSPENDED`: it
    requires every financial period of the branch to be `FINALIZED` — none may
    remain `OPEN` or `CLOSED` — and no goodwill transfer on the branch may be
    in `OFFERED`, `NEGOTIATING`, or `ACCEPTED` status, otherwise the close is
    rejected with `ERR_TRANSFER_ACTIVE`."

    Design: Corner/errors/error_transfer_active_blocks_close
    """
    from test_helpers import validate_paginated

    transfer, retiring, successor, branch = setup_retiring_advisor_with_transfer(
        with_boa=True,
    )
    # Branch is OPEN with staffing SUCCESSION_PENDING; suspend requires OPEN.
    validate_success(api_client.suspend_branch(branch["id"], ADMIN))

    # Finalize the auto-created first period so only the transfer blocks close.
    periods, meta = validate_paginated(
        api_client.list_branch_financial_periods(branch["id"], ADMIN)
    )
    for period in periods:
        if period["status"] == "OPEN":
            set_clock("2026-10-02T00:00:00Z")
            validate_success(api_client.close_period(period["id"], ADMIN))
            validate_success(api_client.finalize_period(period["id"], ADMIN))

    validate_error(
        api_client.close_branch(branch["id"], ADMIN),
        ApiErrorId.ERR_TRANSFER_ACTIVE,
    )
    assert get_success_data(
        api_client.get_branch(branch["id"], ADMIN)
    )["operating_status"] == "SUSPENDED"
