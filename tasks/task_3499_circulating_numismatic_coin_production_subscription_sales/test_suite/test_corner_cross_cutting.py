"""Corner coverage — the two OCC-guarded write endpoints (PRD §2.6) and the
clock-driven scheduled release of a program-less product (§3.6)."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    validate_error,
    validate_success,
)
from test_helpers.assertions import validate_created
from test_helpers.constants import BOOT_CLOCK_UTC
from test_helpers.factories import billing_cycle_payload, create_allocation_payload
from test_helpers.fixtures import (
    create_allocation_offer,
    create_authorized_purchaser,
    create_product,
    set_clock,
    setup_billed_subscription,
    setup_bullion_issue,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["program_manager_headers"]


def test_occ_allocation_offer_stale_version_rejected(api):
    """PRD §2.6: "Creating a bullion allocation requires the request to carry
    `expected_bullion_issue_version`, holding the `version` of the parent
    `BullionIssue` as the client last observed it. If the issue's current
    `version` has advanced since that observation — because another offer was
    accepted against the issue or an expiry restored units to its pool — the
    create is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client
    never sizes and prices an offer against a stale view of the remaining
    pool."
    PRD §2.5: "`version` is an integer that starts at 1 on creation and
    increments by exactly 1 on every mutation of the resource, including
    system-driven auto-transitions."
    PRD §3.8: "A created offer decrements the issue's `remaining_pool_units`
    by the offered quantity, increments the issue's `version`, records
    `offered_by_user_id` from the manager's `X-User-ID`, fixes
    `offer_expires_at` as the current logical-clock instant plus the issue's
    `offer_window_hours`, and sits in `OFFERED` with `total_price_cents` still
    null."

    Design: Corner/cross_cutting_layers/occ_allocation_offer_stale_version_rejected
    """
    issue = setup_bullion_issue(api, clock_ts="2026-09-10T00:00:00Z")  # pool 1000
    ap = create_authorized_purchaser(api)
    observed_version = issue["version"]  # 1 at creation

    # First offer against the observed version succeeds and advances the issue.
    _, issue_after_first = create_allocation_offer(api, issue, ap, 10)
    assert issue_after_first["version"] == observed_version + 1

    # A second offer still carrying the stale version is rejected.
    stale = api.create_allocation(
        issue["id"],
        create_allocation_payload(
            authorized_purchaser_id=ap["id"], quantity_units=10,
            expected_bullion_issue_version=observed_version),
        MANAGER)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)  # 412 auto-checked

    # Refetching shows version 2; retrying with it succeeds.
    refetched = validate_success(api.get_bullion_issue(issue["id"], MANAGER))
    assert refetched["version"] == 2, (
        f"one accepted offer must advance the issue to version 2, got {refetched['version']}")
    retry = api.create_allocation(
        issue["id"],
        create_allocation_payload(
            authorized_purchaser_id=ap["id"], quantity_units=10,
            expected_bullion_issue_version=refetched["version"]),
        MANAGER)
    validate_created(retry)

    final = validate_success(api.get_bullion_issue(issue["id"], MANAGER))
    assert final["remaining_pool_units"] == 980, (
        f"two accepted offers of 10 against a 1000-unit pool leave 980, got "
        f"{final['remaining_pool_units']}")


def test_occ_billing_cycle_stale_version_rejected(api):
    """PRD §2.6: "Running a subscription billing cycle requires the request to
    carry `expected_subscription_version`, holding the `version` of the
    `Subscription` as the client last observed it. A mismatch with the
    subscription's current `version` — advanced by an intervening billing
    cycle or a dunning transition — is rejected with `ERR_STALE_VERSION`
    (HTTP 412), preventing a billing run against a schedule the client has not
    observed."
    PRD §2.7: "Validations are evaluated as a fixed ladder; the earliest rung
    that fails produces the response, and later rungs are never consulted."
    PRD §3.7: "The cycle then advances `next_billing_date` by one month for
    `MONTHLY` or three months for `QUARTERLY`, increments `cycles_billed` by
    one, increments the subscription's `version`, and returns the created
    invoice."

    Design: Corner/cross_cutting_layers/occ_billing_cycle_stale_version_rejected
    """
    # One billing cycle already ran: the subscription is at version 2 with
    # next_billing_date 2026-10-01 while the clock still reads 2026-09-01, so
    # the replayed request is stale AND not-due — the rung-5 OCC check fires
    # before the rung-8 temporal check.
    _, _, subscription, _ = setup_billed_subscription(api)
    stale_version = subscription["version"] - 1  # the version observed at enrollment

    replay = api.run_billing_cycle(
        subscription["id"], billing_cycle_payload(stale_version), ADMIN)
    validate_error(replay, ApiErrorId.ERR_STALE_VERSION)  # 412 auto-checked

    after = validate_success(api.get_subscription(subscription["id"], ADMIN))
    assert after["cycles_billed"] == 1, (
        f"the stale replay must not bill again; cycles_billed must stay 1, got "
        f"{after['cycles_billed']}")


def test_product_release_auto_opens_at_release_datetime(api):
    """PRD §3.6: "When a clock-set sweep finds the logical clock at or past a
    `SCHEDULED` product's `release_datetime`, the product moves to `ON_SALE` —
    unless it belongs to a program that is not yet `ON_SALE`, in which case it
    waits in `SCHEDULED` until the program opens."

    Design: Corner/cross_cutting_layers/product_release_auto_opens_at_release_datetime
    """
    set_clock(api, BOOT_CLOCK_UTC)
    product = create_product(api, product_code="REL-1", product_family="RELF",
                             release_datetime="2026-09-20T00:00:00Z")

    set_clock(api, "2026-09-19T00:00:00Z")  # one day before release
    before = validate_success(api.get_product(product["id"], MANAGER))
    assert before["status"] == "SCHEDULED", (
        f"before release_datetime the product must stay SCHEDULED, got {before['status']}")

    set_clock(api, "2026-09-20T00:00:00Z")  # the release instant, inclusive
    after = validate_success(api.get_product(product["id"], MANAGER))
    assert after["status"] == "ON_SALE", (
        f"at the release instant the product must flip to ON_SALE, got {after['status']}")
