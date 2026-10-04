"""Commercial onboarding and the subscription lifecycle: eligibility, period
overlap, plan changes under OCC, and the terminal cancellation cascade
(PRD §3.4)."""
from test_helpers import (
    CLOCK_SEP_05,
    CLOCK_SEP_10,
    ApiErrorId,
    assign_seat,
    create_account,
    create_plan,
    create_subscription,
    generate_invoice,
    get_invoice,
    get_subscription,
    get_user,
    issue_invoice,
    set_clock,
    setup_subscribed_user,
    subscription_payload,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

_LICENSING = TEST_USERS["licensing_manager_headers"]


def test_government_plan_requires_government_account(api):
    """PRD §3.4: "Eligibility is enforced after the overlap check per §2.9:
    subscribing a `government_only` plan to an account whose `account_type` is not
    `GOVERNMENT` fails with `ERR_PLAN_ACCOUNT_INCOMPATIBLE` (HTTP 422)."

    Design: Corner/validations/government_plan_requires_government_account
    """
    set_clock(CLOCK_SEP_05)
    plan = create_plan(flat=False, name="Gov Only", government_only=True)
    firm = create_account(org_name="Private Firm", account_type="LAW_FIRM")
    gov = create_account(org_name="State Agency", account_type="GOVERNMENT")

    rejected = api.create_subscription(
        subscription_payload(firm["id"], plan["id"]), _LICENSING,
    )
    validate_error(rejected, ApiErrorId.ERR_PLAN_ACCOUNT_INCOMPATIBLE, 422)

    accepted = api.create_subscription(
        subscription_payload(gov["id"], plan["id"]), _LICENSING,
    )
    data = validate_success(accepted, 201)
    assert data["account_id"] == gov["id"]
    assert data["status"] == "ACTIVE"


def test_subscription_overlap_half_open_semantics(api):
    """PRD §3.4: "The contract period is half-open, and it must not overlap the
    period of any non-`CANCELLED` subscription of the same account; adjacency is
    fine — a new period whose `period_start` equals an existing period's
    `period_end` is allowed — but interior overlap is rejected with
    `ERR_SUBSCRIPTION_OVERLAP` (HTTP 409)."

    Design: Corner/validations/subscription_overlap_half_open_semantics
    """
    set_clock(CLOCK_SEP_05)
    plan = create_plan(name="Ovl Plan")
    account = create_account(org_name="Ovl Co")
    create_subscription(account["id"], plan["id"])

    overlapping = api.create_subscription(
        subscription_payload(account["id"], plan["id"],
                             period_start="2026-09-15", period_end="2026-11-01"),
        _LICENSING,
    )
    validate_error(overlapping, ApiErrorId.ERR_SUBSCRIPTION_OVERLAP, 409)

    contiguous = api.create_subscription(
        subscription_payload(account["id"], plan["id"],
                             period_start="2026-10-01", period_end="2026-11-01"),
        _LICENSING,
    )
    data = validate_success(contiguous, 201)
    assert data["period_start"] == "2026-10-01", (
        "period_start == prior period_end is not overlap"
    )


def test_cancel_cancelled_subscription_rejected(api):
    """PRD §3.4: "Any request that asks for a transition the current state does not
    list — cancelling a `CANCELLED` subscription, resuming an `ACTIVE` one, and so
    on — is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/cancel_cancelled_subscription_rejected
    """
    set_clock(CLOCK_SEP_05)
    ctx = setup_subscribed_user(plan_overrides={"name": "Term Plan"}, searches=0)
    sub_id = ctx["subscription"]["id"]
    first = api.transition_subscription(sub_id, {"target_status": "CANCELLED"}, _LICENSING)
    validate_success(first, 200)

    resp = api.transition_subscription(sub_id, {"target_status": "ACTIVE"}, _LICENSING)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_subscription(sub_id)["status"] == "CANCELLED"


def test_subscription_cancel_releases_seats_and_voids_drafts(api):
    """PRD §3.4: "Cancellation is available from either `ACTIVE` or `SUSPENDED` and
    is terminal: every seated user loses the seat (`seat_status` becomes `NONE`,
    `seat_subscription_id` is cleared, and `seats_used` falls to zero), every
    `DRAFT` invoice of the subscription is voided, and `CANCELLED` admits no
    further transition."

    Design: Corner/state_machines/subscription_cancel_releases_seats_and_voids_drafts
    """
    set_clock(CLOCK_SEP_10)
    ctx = setup_subscribed_user(
        plan_overrides={"name": "Casc Plan"},
        period_start="2026-09-01", period_end="2026-12-01",
        searches=1,
    )
    sub_id = ctx["subscription"]["id"]
    invoice1 = issue_invoice(generate_invoice(sub_id, "2026-09-01", "2026-10-01")["id"])
    assert invoice1["status"] == "ISSUED"
    set_clock("2026-10-05T00:00:00Z")
    invoice2 = generate_invoice(sub_id, "2026-10-01", "2026-11-01")
    assert invoice2["status"] == "DRAFT"

    cancelled = validate_success(
        api.transition_subscription(sub_id, {"target_status": "CANCELLED"}, _LICENSING), 200
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["seats_used"] == 0

    user = get_user(ctx["user"]["id"])
    assert user["seat_status"] == "NONE"
    assert user["seat_subscription_id"] is None

    assert get_invoice(invoice2["id"])["status"] == "VOID", "DRAFT child compensated"
    # ISSUED at 2026-09-10; at clock 2026-10-05 the invoice is pre-due under the
    # design-pinned net-terms period (NET_TERMS_DAYS, PRD §3.6 symbolic), so the
    # cascade leaves it ISSUED rather than VOID.
    assert get_invoice(invoice1["id"])["status"] == "ISSUED", (
        "an ISSUED invoice is not touched by the cancellation cascade"
    )


def test_change_plan_success_updates_plan_and_bumps_version(api):
    """PRD §3.4: "Plans change mid-contract. A `LicensingManager` changes the plan
    by naming a `new_plan_id` alongside the OCC field
    `expected_subscription_version` of §2.8; the subscription's `plan_id` adopts
    the new value for future invoices, its `version` increments by one, and a stale
    version is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/endpoints/change_plan_success_updates_plan_and_bumps_version
    """
    set_clock(CLOCK_SEP_05)
    plan1 = create_plan(name="CP One")
    plan2 = create_plan(flat=False, name="CP Two", jurisdiction_scope="NATIONAL", firm_size_tier="MID")
    account = create_account(org_name="CP Co")
    subscription = create_subscription(account["id"], plan1["id"])
    version = get_subscription(subscription["id"])["version"]

    resp = api.change_plan(
        subscription["id"],
        {"new_plan_id": plan2["id"], "expected_subscription_version": version},
        _LICENSING,
    )
    data = validate_success(resp, 200)
    assert data["plan_id"] == plan2["id"]
    assert data["version"] == version + 1
    assert data["status"] == "ACTIVE"


def test_occ_change_plan_stale_then_fresh(api):
    """PRD §2.8: "The change-plan request must carry `expected_subscription_version`
    equal to the subscription's current `version`. Seat operations, suspensions,
    and earlier plan changes all bump that version, so a plan change built on an
    outdated read is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than
    silently overwriting a plan the client never saw."

    Design: Corner/cross_cutting/occ_change_plan_stale_then_fresh
    """
    set_clock(CLOCK_SEP_05)
    plan1 = create_plan(name="OC1")
    plan2 = create_plan(flat=False, name="OC2", jurisdiction_scope="NATIONAL", firm_size_tier="MID")
    account = create_account(org_name="OC Co")
    subscription = create_subscription(account["id"], plan1["id"], seats_total=2)
    sub_id = subscription["id"]
    v0 = get_subscription(sub_id)["version"]
    # An intervening seat ASSIGN bumps the subscription version past v0.
    assign_seat(sub_id, account["id"], email="o@oc.com", full_name="O")

    stale = api.change_plan(
        sub_id, {"new_plan_id": plan2["id"], "expected_subscription_version": v0}, _LICENSING,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)

    v1 = get_subscription(sub_id)["version"]
    fresh = api.change_plan(
        sub_id, {"new_plan_id": plan2["id"], "expected_subscription_version": v1}, _LICENSING,
    )
    data = validate_success(fresh, 200)
    assert data["plan_id"] == plan2["id"]
    assert data["version"] == v1 + 1


def test_subscription_create_body_fk_not_found(api):
    """PRD §3.4: "Both identifiers must resolve — an unknown plan yields
    `ERR_PLAN_NOT_FOUND` (HTTP 404) and an unknown account `ERR_ACCOUNT_NOT_FOUND`
    (HTTP 404)."

    Design: Corner/errors/subscription_create_body_fk_not_found
    """
    set_clock(CLOCK_SEP_05)
    plan = create_plan(name="FK Plan")
    account = create_account(org_name="FK Co")
    missing = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"

    bad_plan = api.create_subscription(
        subscription_payload(account["id"], missing), _LICENSING,
    )
    validate_error(bad_plan, ApiErrorId.ERR_PLAN_NOT_FOUND, 404)

    bad_account = api.create_subscription(
        subscription_payload(missing, plan["id"]), _LICENSING,
    )
    validate_error(bad_account, ApiErrorId.ERR_ACCOUNT_NOT_FOUND, 404)
