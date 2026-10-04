"""Image billing: resolve gating, rebill net-credit, void rules (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_account,
    create_discount_plan,
    create_home_agency,
    create_rate_schedule,
    create_away_agency,
    create_plate_agreement,
    find_pending_image_bill,
    get_account,
    get_success_data,
    make_account_holder_headers,
    post_image_trip,
    resolve_bill_to_account,
    resolve_bill_to_violation,
    setup_agency_pair,
    setup_account_with_plan,
    setup_billed_image_bill,
    validate_error,
    validate_paginated,
)

SO = TEST_USERS["settlement_officer_headers"]
PL = TEST_USERS["plate_lookup_agent_headers"]
AO = TEST_USERS["agency_ops_headers"]


def test_image_bill_resolve_gated_by_plate_data_agreement():
    """PRD §3.9: "An officer may revoke an agreement outright, moving it from
    `ACTIVE` to `REVOKED` (terminal); from that moment, plate lookups relying
    on it are rejected with `ERR_PLATE_LOOKUP_NOT_AVAILABLE`."

    Design: Difficulty/cross_entity_state_dependency/image_bill_resolve_gated_by_plate_data_agreement
    """
    home, away = setup_agency_pair()
    create_rate_schedule(away["id"], base_rate_cents=800,
                         effective_to="2026-12-31T00:00:00Z")
    plan = create_discount_plan(
        home["id"], plan_code="STD", applies_to_agency_codes=[away["agency_code"]]
    )
    account = create_account(
        home["id"], plan["id"], holder_name="Pat Lookup", holder_email="pat@example.com",
        opening_balance_cents=10000,
    )
    agreement = create_plate_agreement(away["id"], home["id"])

    post_image_trip(away["id"], "P1", "NYP100", "NY", "2026-09-02T09:00:00Z", "l1")
    post_image_trip(away["id"], "P1", "NYP200", "NY", "2026-09-02T09:30:00Z", "l2")
    resp = api_client.list_image_bills(PL, params={"status": "PENDING_LOOKUP"})
    bills, _ = validate_paginated(resp)
    assert len(bills) == 2
    b_ok, b_blocked = bills[0]["id"], bills[1]["id"]

    first = resolve_bill_to_account(b_ok, account["id"])
    assert first["status"] == "BILLED"

    get_success_data(api_client.revoke_plate_data_agreement(agreement["id"], SO))

    resp2 = api_client.resolve_image_bill(
        b_blocked, {"resolved_account_id": account["id"]}, PL
    )
    validate_error(resp2, ApiErrorId.ERR_PLATE_LOOKUP_NOT_AVAILABLE)
    still = get_success_data(api_client.get_image_bill(b_blocked, PL))
    assert still["status"] == "PENDING_LOOKUP"


def test_misread_plate_net_credit_vs_void_and_rebill():
    """PRD §3.8: "Upholding a misread-plate or rental dispute drives the linked
    image bill from `BILLED` to `REBILLED`: the original account is credited
    exactly `billed_amount_cents` once — a single net-credit entry,
    deliberately not a reversal-plus-separate-credit-memo pair — and for a
    misread the bill's `misread_flag` is set true. A brand-new image bill for
    the corrected plate or the rental liable party is then created in
    `PENDING_LOOKUP`, priced at the video rate against the corrected party's
    account (or sent down the unregistered-plate violation path if no account
    matches)."

    Design: Difficulty/dual_variant_calc/misread_plate_net_credit_vs_void_and_rebill
    """
    ctx = setup_billed_image_bill(account_balance=5000)
    account = ctx["account"]
    bill = ctx["bill"]
    v0 = account["version"]
    assert get_account(account["id"])["balance_cents"] == 4100

    resp = api_client.create_dispute(
        {
            "account_id": account["id"],
            "dispute_type": "MISREAD_PLATE",
            "image_bill_id": bill["id"],
            "claimed_plate_number": "XYZ999",
        },
        make_account_holder_headers(account["id"]),
    )
    dispute = get_success_data(resp)
    get_success_data(api_client.begin_review_dispute(dispute["id"], TEST_USERS["violations_officer_headers"]))
    get_success_data(api_client.uphold_dispute(dispute["id"], TEST_USERS["violations_officer_headers"]))

    acct = get_account(account["id"])
    assert acct["balance_cents"] == 5000  # single net credit of 900
    # v0 was captured AFTER the resolve debit; only the uphold credit touches
    # the account afterwards.
    assert acct["version"] == v0 + 1

    rebilled = get_success_data(api_client.get_image_bill(bill["id"], PL))
    assert rebilled["status"] == "REBILLED"
    assert rebilled["misread_flag"] is True

    pend, meta = validate_paginated(
        api_client.list_image_bills(PL, params={"status": "PENDING_LOOKUP"})
    )
    assert len(pend) == 1
    assert pend[0]["plate_number"] == "XYZ999"


def test_image_bill_void_blocked_by_active_dispute():
    """PRD §3.6: "Voiding a `BILLED` bill credits its account back
    `billed_amount_cents`, but only when no dispute in `FILED` or
    `UNDER_REVIEW` references the bill — such a dispute blocks the void with
    `ERR_IMAGE_BILL_HAS_ACTIVE_DISPUTE`."

    Design: Corner/errors/image_bill_void_blocked_by_active_dispute
    """
    ctx = setup_billed_image_bill(account_balance=5000)
    account = ctx["account"]
    bill = ctx["bill"]
    holder = make_account_holder_headers(account["id"])

    dispute = get_success_data(
        api_client.create_dispute(
            {
                "account_id": account["id"],
                "dispute_type": "MISREAD_PLATE",
                "image_bill_id": bill["id"],
                "claimed_plate_number": "ZZZ999",
            },
            holder,
        )
    )
    resp1 = api_client.void_image_bill(bill["id"], AO)
    validate_error(resp1, ApiErrorId.ERR_IMAGE_BILL_HAS_ACTIVE_DISPUTE)
    assert get_success_data(api_client.get_image_bill(bill["id"], PL))["status"] == "BILLED"
    assert get_account(account["id"])["balance_cents"] == 4100

    get_success_data(api_client.withdraw_dispute(dispute["id"], holder))

    resp2 = api_client.void_image_bill(bill["id"], AO)
    assert resp2.status_code == 200
    assert get_success_data(api_client.get_image_bill(bill["id"], PL))["status"] == "VOIDED"
    assert get_account(account["id"])["balance_cents"] == 5000
