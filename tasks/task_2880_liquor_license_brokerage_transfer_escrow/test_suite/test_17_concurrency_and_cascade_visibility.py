"""Version tokens on the two guarded writes, and the immediacy of the execute cascade.

A replayed token is refused ahead of the domain rule it would otherwise have
broken, writes nothing, and the same body succeeds once the caller re-reads the
parent row.
"""

from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    assert_instant_equals,
    create_purchase_agreement_payload,
    create_safekeeping_filing_payload,
    decide_safekeeping,
    file_safekeeping,
    make_broker_headers,
    make_seller_headers,
    read_agreement,
    read_county,
    read_license,
    read_listing,
    setup_safekeeping_bench,
    setup_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_replayed_listing_version_is_refused_ahead_of_the_window_overlap_it_would_break():
    """The second offer replaying version 2 answers 412, and the retry on version 3 is accepted.

    PRD: "Because a successful create itself advances the listing's `version`, a
    caller that replays the same `expected_listing_version` a second time is
    refused with `ERR_STALE_LISTING_VERSION`."

    PRD: "9. **Optimistic concurrency.** On agreement drafting and safekeeping
    filing only — `ERR_STALE_LISTING_VERSION` or `ERR_STALE_LICENSE_VERSION`
    (412)."

    PRD: "20. **License contract-window overlap** — `ERR_LICENSE_CONTRACT_OVERLAP`
    (409), on agreement drafting."

    PRD: "Because the intervals are half-open, two windows that merely touch — one
    ending at the exact instant the next begins — do not intersect and are both
    accepted."

    Design: Corner/cross-cutting complexity layers/stale_listing_version_rejects_a_replayed_second_offer
    """
    scenario = setup_scenario(stage="listing_active")
    listing_id = scenario["listing_id"]
    broker_headers = make_broker_headers(scenario["brokerage_id"])
    first_token = scenario["listing"]["version"]
    assert first_token == 2

    first = validate_success(api_client.create_purchase_agreement(
        create_purchase_agreement_payload(
            listing_id, scenario["buyer_id"], scenario["premises_id"], first_token,
            purchase_price_cents=18500010, deposit_pct_bps=1000,
            closing_window_start="2026-09-01T00:00:00Z",
        ),
        broker_headers,
    ), 201)
    assert first["agreement_status"] == "DRAFT"
    assert_instant_equals(first["contingency_deadline_at"], "2026-12-30T00:00:00Z",
                          "contingency_deadline_at")
    after_first = read_listing(listing_id)
    assert after_first["version"] == 3
    assert after_first["open_offer_count"] == 1

    # The replay reserves the very same window as the accepted offer, so the
    # overlap rule is violated too — and the version token still answers first.
    replay = api_client.create_purchase_agreement(
        create_purchase_agreement_payload(
            listing_id, scenario["buyer_id"], scenario["premises_id"], first_token,
            purchase_price_cents=19000000, deposit_pct_bps=1000,
            closing_window_start="2026-09-01T00:00:00Z",
        ),
        broker_headers,
    )
    stale_error = validate_error(
        replay, ApiErrorId.ERR_STALE_LISTING_VERSION.value, 412
    )
    assert stale_error["error_id"] != ApiErrorId.ERR_LICENSE_CONTRACT_OVERLAP.value

    unmoved = read_listing(listing_id)
    assert unmoved["version"] == 3
    assert unmoved["open_offer_count"] == 1

    # A fresh token plus a window that merely touches the first reservation is a
    # legitimate competing offer.
    second = validate_success(api_client.create_purchase_agreement(
        create_purchase_agreement_payload(
            listing_id, scenario["buyer_id"], scenario["premises_id"],
            unmoved["version"],
            purchase_price_cents=19000000, deposit_pct_bps=1000,
            closing_window_start="2026-12-30T00:00:00Z",
        ),
        broker_headers,
    ), 201)
    assert second["agreement_status"] == "DRAFT"
    assert second["id"] != first["id"]

    final = read_listing(listing_id)
    assert final["version"] == 4
    assert final["open_offer_count"] == 2
    assert final["status"] == "ACTIVE"
    assert read_agreement(first["id"])["agreement_status"] == "DRAFT"

    _, meta = validate_paginated(
        api_client.list_purchase_agreements(ADMIN, params={"listing_id": listing_id})
    )
    assert meta["total_count"] == 2


def test_a_replayed_license_version_is_refused_before_the_chained_extension_is_priced():
    """The filing and its grant both bump the licence, so the pre-filing token is stale.

    PRD: "A successful filing advances the license's `version`, so a replay of the
    same `expected_license_version` is refused with
    `ERR_STALE_LICENSE_VERSION`."

    PRD: "Here too a second filing is legitimate in principle — an extension
    petition deliberately supersedes the window installed by the previous one — so
    the rejection is triggered only by staleness: the filer's view of
    `safekeeping_expires_at`, `safekeeping_extensions_count` and
    `safekeeping_filing_pending` determines the fee step and the chained effective
    date, and acting on a stale view of them would produce a wrong fee and a wrong
    window."

    PRD: "For an extension, `extension_index` is the license's current
    `safekeeping_extensions_count` plus one, `granted_months` is the requested
    figure capped at 6 months, and `effective_from` is the license's current
    `safekeeping_expires_at` — windows are **chained, never overlapped**, so an
    extension begins exactly where the prior window ended rather than at the
    filing instant."

    Design: Corner/cross-cutting complexity layers/stale_license_version_rejects_the_chained_extension_filing
    """
    bench = setup_safekeeping_bench(license_number="SAFE-OCC-1")
    license_id = bench["license_id"]
    seller_headers = make_seller_headers(bench["seller_id"])
    stale_token = bench["license"]["version"]
    assert stale_token == 1

    initial = file_safekeeping(license_id, stale_token, requested_months=12,
                              seller_id=bench["seller_id"])
    assert initial["fee_cents"] == 20000
    decide_safekeeping(initial["id"], "GRANT")

    replay = api_client.create_safekeeping_filing(
        create_safekeeping_filing_payload(license_id, stale_token,
                                          filing_type="EXTENSION", requested_months=6),
        seller_headers,
    )
    stale_error = validate_error(replay, ApiErrorId.ERR_STALE_LICENSE_VERSION.value, 412)
    assert stale_error["error_id"] != ApiErrorId.ERR_SAFEKEEPING_EXTENSION_LIMIT.value

    current = read_license(license_id)
    assert current["version"] == 3
    assert current["status"] == "SAFEKEEPING"
    assert current["safekeeping_filing_pending"] is False
    assert current["safekeeping_extensions_count"] == 0
    assert_instant_equals(current["safekeeping_expires_at"], "2027-08-01T00:00:00Z",
                          "safekeeping_expires_at")

    accepted = validate_success(api_client.create_safekeeping_filing(
        create_safekeeping_filing_payload(license_id, current["version"],
                                          filing_type="EXTENSION", requested_months=6),
        seller_headers,
    ), 201)
    assert accepted["extension_index"] == 1
    assert accepted["fee_cents"] == 40000
    assert_instant_equals(accepted["effective_from"], "2027-08-01T00:00:00Z",
                          "effective_from")
    assert_instant_equals(accepted["expires_at"], "2028-02-01T00:00:00Z", "expires_at")

    after = read_license(license_id)
    assert after["version"] == 4
    assert after["safekeeping_filing_pending"] is True

    filings, meta = validate_paginated(
        api_client.list_license_safekeeping_filings(license_id, ADMIN)
    )
    assert meta["total_count"] == 2
    assert [row["fee_cents"] for row in filings] == [20000, 40000]


def test_the_execute_response_already_carries_every_hop_of_the_cascade():
    """Execution answers with the moved agreement, and the next reads already agree.

    PRD: "On success, `executed_at` is stamped with the current logical instant and
    `commission_mode` is frozen from the `FULLY_ACKED` disclosure: it becomes
    `DUAL_AGENCY` when that disclosure asserts both `represents_seller` and
    `represents_buyer`, and `SINGLE_AGENCY` in every other case."

    PRD: "The agreement moves `DRAFT → EXECUTED`. The license moves `ACTIVE →
    IN_ESCROW` or `SAFEKEEPING → IN_ESCROW` as appropriate; when it comes from
    `SAFEKEEPING`, its `safekeeping_expires_at` is deliberately retained unchanged
    so that the window can be restored if the transfer later fails. The listing
    moves `ACTIVE → UNDER_CONTRACT`. The county's counters are recomputed, so
    `escrow_committed_count` rises by one for a counted license, and the county's
    `version` advances."

    Design: Corner/consistency model/every_cascade_is_visible_in_the_same_response
    """
    scenario = setup_scenario(stage="escrow_held")
    agreement_id = scenario["agreement_id"]
    assert read_county(scenario["county_id"])["escrow_committed_count"] == 0

    executed = validate_success(api_client.execute_agreement(
        agreement_id, make_broker_headers(scenario["brokerage_id"])
    ))
    assert executed["agreement_status"] == "EXECUTED"
    assert executed["commission_mode"] == "SINGLE_AGENCY"
    assert executed["escrow_status"] == "HELD"
    assert_instant_equals(executed["executed_at"], "2026-08-01T00:00:00Z", "executed_at")

    license_row = read_license(scenario["license_id"])
    listing_row = read_listing(scenario["listing_id"])
    county_row = read_county(scenario["county_id"])
    assert license_row["status"] == "IN_ESCROW"
    assert listing_row["status"] == "UNDER_CONTRACT"
    assert county_row["escrow_committed_count"] == 1

    # Nothing converges after the fact: a second read of each row is identical.
    assert read_agreement(agreement_id) == executed
    assert read_license(scenario["license_id"]) == license_row
    assert read_listing(scenario["listing_id"]) == listing_row
    assert read_county(scenario["county_id"]) == county_row
