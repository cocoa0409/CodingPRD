"""Cross-cutting: transfer OCC stale versions and finalize tier trigger."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, get_success_data,
    api_client, ApiErrorId,
    setup_retiring_advisor_with_transfer, create_open_branch,
    create_period, set_clock, make_advisor_headers,
)

ADMIN = TEST_USERS["home_office_admin_headers"]


def test_stale_version_on_counter_offer():
    """PRD §2.4: "Submitting a counter-offer against a goodwill transfer
    requires `expected_transfer_version` equal to the transfer's current
    `version`; if the other party has countered since the client last read
    the negotiation (advancing both `negotiation_round` and `version`), the
    counter-offer is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/stale_version_on_counter_offer
    """
    transfer, retiring, successor, branch = setup_retiring_advisor_with_transfer()
    stale_version = transfer["version"]

    first = validate_success(api_client.counter_offer(
        transfer["id"],
        {"expected_transfer_version": stale_version, "offer_price_cents": 1700000},
        make_advisor_headers(successor["id"]),
    ))

    # Replay with the pre-counter version.
    validate_error(
        api_client.counter_offer(
            transfer["id"],
            {"expected_transfer_version": stale_version, "offer_price_cents": 1750000},
            make_advisor_headers(retiring["id"]),
        ),
        ApiErrorId.ERR_STALE_VERSION,
    )

    # Fresh version succeeds.
    second = validate_success(api_client.counter_offer(
        transfer["id"],
        {"expected_transfer_version": first["version"], "offer_price_cents": 1750000},
        make_advisor_headers(retiring["id"]),
    ))
    assert second["negotiation_round"] == 2


def test_tier_threshold_trigger_on_finalize():
    """PRD §3.5: "Third, it recomputes the branch's `service_tier` as a
    threshold trigger (§3.6)."
    PRD §3.6: "Both `tier_score` and `service_tier` are recomputed on every
    book-attribute update and again at period finalization."

    Design: Corner/cross_cutting_layers/tier_threshold_trigger_on_finalize
    """
    branch, territory, advisor, boa = create_open_branch()
    # Opening the branch auto-creates the first OPEN period covering the
    # current calendar month (the clock starts at 2026-09-01, so September);
    # an overlapping creation would be rejected, so fetch it via the listing.
    data = get_success_data(api_client.list_branch_financial_periods(branch["id"], ADMIN))
    periods = data["items"] if isinstance(data, dict) and "items" in data else data
    period = [p for p in periods
              if p["period_start"].startswith("2026-09-01T00:00:00")
              and p["period_end"].startswith("2026-10-01T00:00:00")][0]

    set_clock("2026-10-02T00:00:00Z")
    validate_success(api_client.close_period(period["id"], ADMIN))

    current = get_success_data(api_client.get_branch(branch["id"], ADMIN))
    patched = validate_success(api_client.patch_branch(
        branch["id"],
        {
            "expected_branch_version": current["version"],
            "household_count": 31,
            "assets_under_care_dollars": 0,
        },
        ADMIN,
    ))
    # 31 * 10 + 0 = 310 -> TIER_2
    assert patched["tier_score"] == 310
    assert patched["service_tier"] == "TIER_2"

    finalized = validate_success(api_client.finalize_period(period["id"], ADMIN))
    assert finalized["status"] == "FINALIZED"

    after = get_success_data(api_client.get_branch(branch["id"], ADMIN))
    assert after["service_tier"] == "TIER_2"
    assert after["tier_score"] == 310
