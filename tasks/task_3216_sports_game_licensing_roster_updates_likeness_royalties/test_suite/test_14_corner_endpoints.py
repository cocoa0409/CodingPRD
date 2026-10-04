"""Corner queue B, section=endpoints (2 instances)."""
from test_helpers import (
    ADMIN,
    create_active_agreement,
    create_agreement_payload,
    create_eligible_athlete,
    create_funded_wallet,
    create_live_season,
    create_released_drop,
    get_success_data,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

LIVEOPS = TEST_USERS["liveops_manager_headers"]


def test_list_agreements_pagination_envelope(api):
    """PRD §2.3: "Paginated list responses always populate limit, offset,
    total_count, and has_more in the meta object of the response envelope, so
    a client can distinguish 'empty page' from 'no such data' and can compute
    whether further pages exist."

    Design: Corner/endpoints/list_agreements_pagination_envelope
    """
    for name in ("A", "B", "C"):
        get_success_data(
            api_client.create_agreement(
                create_agreement_payload(licensor_name=name), ADMIN
            )
        )
    page1, meta1 = validate_paginated(
        api_client.list_agreements(ADMIN, params={"limit": 2, "offset": 0})
    )
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert len(page1) == 2

    page2, meta2 = validate_paginated(
        api_client.list_agreements(ADMIN, params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["has_more"] is False


def test_purchase_drop_debits_wallet_atomically(api):
    """PRD §3.4: "A debit may post only while the wallet is OPEN and only when
    the wallet's current balance is at least the debit's amount_vc." and "A
    successful purchase posts a SPEND_DROP DEBIT ledger entry and decreases
    vc_balance accordingly."

    Design: Corner/endpoints/purchase_drop_debits_wallet_atomically
    """
    agreement = create_active_agreement()
    athlete, _ = create_eligible_athlete(agreement["id"])
    season = create_live_season(agreement["id"], athlete["id"])
    drop = create_released_drop(season["id"], drop_kind="VANITY",
                                drop_label="Exact Price", price_vc=250)
    wallet = create_funded_wallet(season["id"], 250, owner_tag="exact")

    entry = get_success_data(
        api_client.purchase_content_drop(drop["id"], {"wallet_id": wallet["id"]},
                                         LIVEOPS)
    )
    assert entry["entry_status"] == "POSTED"
    assert entry["direction"] == "DEBIT"
    assert entry["reason_code"] == "SPEND_DROP"
    assert entry["amount_vc"] == 250

    wallet_after = get_success_data(api_client.get_wallet(wallet["id"], LIVEOPS))
    assert wallet_after["vc_balance"] == 0
