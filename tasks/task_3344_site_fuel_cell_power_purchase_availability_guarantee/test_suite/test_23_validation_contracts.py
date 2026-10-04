"""Which gate refuses a request, what a request that clears every gate
produces, and how a reconciliation picks its one accrual."""
from test_helpers import (
    api_client,
    build_user_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import create_site_payload, create_site_payload_without
from test_helpers.fixtures import (
    ANALYST,
    APPROVER,
    OPERATOR,
    get_customer,
    get_site,
    post_accrual,
    set_clock,
    setup_active_ppa,
    setup_approved_line,
)

# The monthly energy and fixed legs of a 200,000 kWh period priced at the
# 12.00 c/kWh base rate are small change against a 50,000,000-cent ceiling, so
# the ceiling test needs a charge base far larger than one ordinary period.
PORTFOLIO_BREAKING_ACCRUAL_CENTS = 300000000


def test_settle_is_refused_for_the_role_that_prepared_and_validated_the_line():
    """PRD §2.1: "A `SettlementAnalyst` prepares settlement lines and accruals, issues
    allowances and reconciles the ledger, but cannot approve or apply what it prepared; a
    `SettlementApprover` approves, settles and reverses lines, and cannot create them."
    PRD §2.1: "A request that is properly authenticated
    but whose role is not among the roles the addressed operation admits is refused with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/validations/unauthorized_settle_by_analyst_returns_unauthorized
    """
    ctx = setup_approved_line()
    assert ctx["line"]["status"] == "SETTLEMENT_APPROVED"
    reconcile_count_before = get_site(ctx["site_id"])["lifetime_settle_reconcile_count"]

    refused = api_client.settle_settlement_line(ctx["ppa_id"], ctx["line_id"], ANALYST)

    validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED)
    assert refused.status_code == 403, (
        f"a role absent from the settle endpoint's role list is a 403; got {refused.status_code}"
    )
    still_approved = validate_success(
        api_client.get_settlement_line(ctx["ppa_id"], ctx["line_id"], ANALYST)
    )
    assert still_approved["status"] == "SETTLEMENT_APPROVED", (
        "a refused settle leaves the line where it was; got " f"{still_approved['status']}"
    )
    assert (
        get_site(ctx["site_id"])["lifetime_settle_reconcile_count"] == reconcile_count_before
    ), "a refused settle reconciles nothing"

    applied = validate_success(
        api_client.settle_settlement_line(ctx["ppa_id"], ctx["line_id"], APPROVER)
    )
    assert applied["status"] == "SETTLEMENT_APPLIED", (
        "the identical request from the approving role applies the line; got "
        f"{applied['status']}"
    )


def test_a_create_carrying_no_identity_is_refused_before_the_authorization_check():
    """PRD §2.1: "Every request must carry two headers. `X-User-ID` identifies the acting party and
    `X-User-Role` names the operational capacity in which that party is acting. A request that
    omits either header, or that supplies a role string which does not name one of the seven
    declared roles, is refused with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.4: "Authentication is tested first: the two headers must be present, the role value must
    name a declared role, and an entity-backed role's identifier must match a real instance of the
    entity it speaks for, with any failure surfacing as `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_role_header_returns_unauthenticated
    """
    set_clock()
    payload = create_site_payload()

    for headers in (
        {},
        {"X-User-ID": "test-anonymous-1", "Content-Type": "application/json"},
        build_user_headers("test-anonymous-1", "PlatformAdmin"),
    ):
        response = api_client.create_site(payload, headers)
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)
        assert response.status_code == 401, (
            "an absent role header and an undeclared role string are both authentication "
            f"failures; got {response.status_code} for {headers!r}"
        )

    # A payload that is itself malformed must still be reported as an identity
    # failure, because field-level validation runs last of all.
    malformed = api_client.create_site(create_site_payload_without("name"), {})
    validate_error(malformed, ApiErrorId.ERR_UNAUTHENTICATED)

    rows, meta = validate_paginated(api_client.list_sites(OPERATOR))
    assert meta["total_count"] == 0, (
        f"no facility may be persisted by a refused create; found {meta['total_count']}"
    )


def test_a_resource_hold_inside_the_pool_is_created_and_draws_the_pool_down():
    """PRD §3.3: "A `SiteOperator` takes one by supplying `requested_therms` and the pair of window boundaries
    `window_start_iso8601` and `window_end_iso8601`; the server creates a delivery in
    `DELIVERY_SCHEDULED` with that volume, decrements the site's `draw_position_therms`, and
    moves the site's `lifecycle_state` to `RESOURCE_DRAWING`."

    Design: Corner/validations/satisfaction_passes_when_every_gate_holds
    """
    ctx = setup_active_ppa()
    opening = get_site(ctx["site_id"])["draw_position_therms"]
    assert opening == get_site(ctx["site_id"])["initial_fuel_inventory_therms"]

    response = api_client.take_resource_hold(
        ctx["site_id"],
        OPERATOR,
        {
            "requested_therms": 40000,
            "window_start_iso8601": "2026-04-01T00:00:00Z",
            "window_end_iso8601": "2026-04-05T00:00:00Z",
        },
    )
    hold = validate_success(response, expected_status=201)

    assert hold["lifecycle_state"] == "DELIVERY_SCHEDULED", (
        f"a hold is scheduled on creation; got {hold['lifecycle_state']}"
    )
    assert hold["volume_therms"] == 40000
    assert hold["hold_window_start_iso8601"] == "2026-04-01T00:00:00Z"
    assert hold["hold_window_end_iso8601"] == "2026-04-05T00:00:00Z"

    site = get_site(ctx["site_id"])
    assert site["draw_position_therms"] == opening - 40000, (
        "the requested volume is deducted from the pool on the spot; got "
        f"{site['draw_position_therms']}"
    )
    assert site["lifecycle_state"] == "RESOURCE_DRAWING"
    assert site["status"] == "SITE_ACTIVE", "the posture dimension is untouched by a hold"


def test_a_reconciliation_moves_exactly_the_earliest_open_accrual():
    """PRD §3.3: "An accrual may also be reconciled
    without a settlement: a `SettlementAnalyst` may run a reconciliation against a contract,
    optionally naming the `accrual_id` to target, and the server reconciles the earliest `OPEN`
    accrual of that contract by `created_at`, requiring the logical clock to have reached that
    accrual's creation instant plus `ACCRUAL_RECONCILE_SLA_DAYS` and requiring the earliest accrual
    to be unambiguous. Each reconciliation increments the site's
    `lifetime_settle_reconcile_count` and recomputes the customer's `reconcile_cadence_slots`."

    Design: Corner/validations/many_open_accruals_leave_one_reconcilable_pointer
    """
    ctx = setup_active_ppa()
    first = post_accrual(
        ctx["ppa_id"],
        ctx["site_id"],
        amount_cents=100000,
        period_anchor_iso8601="2026-01-01T00:00:00Z",
    )
    set_clock("2026-03-11T00:00:00Z")
    second = post_accrual(
        ctx["ppa_id"],
        ctx["site_id"],
        amount_cents=100000,
        period_anchor_iso8601="2026-02-01T00:00:00Z",
    )
    set_clock("2026-03-12T00:00:00Z")
    third = post_accrual(
        ctx["ppa_id"],
        ctx["site_id"],
        amount_cents=100000,
        period_anchor_iso8601="2026-03-01T00:00:00Z",
    )

    # The clock must have reached the targeted accrual's creation instant plus
    # ACCRUAL_RECONCILE_SLA_DAYS, so give every plausible tolerance ample room.
    set_clock("2027-03-10T00:00:00Z")

    reconciled = validate_success(
        api_client.reconcile_accruals(
            ctx["ppa_id"], ANALYST, {"accrual_id": first["id"]}
        )
    )

    assert reconciled["id"] == first["id"], (
        "the earliest open accrual by created_at is the one reconciled"
    )
    assert reconciled["lifecycle_state"] == "ACCRUAL_RECONCILED"
    assert (
        validate_success(api_client.get_accrual(second["id"], ANALYST))["lifecycle_state"]
        == "ACCRUAL_OPEN"
    ), "the later accruals are left alone by a single reconciliation"
    assert (
        validate_success(api_client.get_accrual(third["id"], ANALYST))["lifecycle_state"]
        == "ACCRUAL_OPEN"
    )

    open_rows, open_meta = validate_paginated(
        api_client.list_accruals(
            ANALYST, {"ppa_id": ctx["ppa_id"], "lifecycle_state": "ACCRUAL_OPEN"}
        )
    )
    assert open_meta["total_count"] == 2, (
        f"two of the three accruals stay open; found {open_meta['total_count']}"
    )
    assert {row["id"] for row in open_rows} == {second["id"], third["id"]}

    assert get_site(ctx["site_id"])["lifetime_settle_reconcile_count"] == 1, (
        "one reconciliation adds exactly one to the site's reconcile count"
    )


def test_a_settle_that_breaches_the_portfolio_credit_ceiling_is_refused():
    """PRD §2.9: "On settlement,
    `net_charge_cents` minus `output_guarantee_credit_cents` must not exceed the customer's
    lifetime billable base as recorded in `lifetime_customer_billable_cents` plus
    `SETTLEMENT_CREDIT_CAP_CENTS`, which is 50,000,000 cents. A settlement that would exceed that
    ceiling is refused with `ERR_BUMPER_EXCEEDED` (HTTP 422)."
    PRD §3.4: "A `SettlementApprover` applies an approved line, and
    before anything is written the ceiling from §2.9 is tested: the line's `net_charge_cents`
    minus its `output_guarantee_credit_cents` may not exceed the customer's
    `lifetime_customer_billable_cents` plus `SETTLEMENT_CREDIT_CAP_CENTS`, on pain of
    `ERR_BUMPER_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/aggregate_credit_cap_is_checked_across_the_customer_portfolio
    """
    ctx = setup_approved_line(accrual_amount_cents=PORTFOLIO_BREAKING_ACCRUAL_CENTS)
    assert ctx["line"]["status"] == "SETTLEMENT_APPROVED"
    assert get_site(ctx["site_id"])["lifetime_customer_billable_cents"] == 0, (
        "nothing has been billed yet, so the ceiling is the cap alone"
    )
    assert (
        ctx["line"]["net_charge_cents"]
        > get_site(ctx["site_id"])["lifetime_customer_billable_cents"] + 50000000
    ), "the setup must present a charge the ceiling cannot absorb"

    refused = api_client.settle_settlement_line(ctx["ppa_id"], ctx["line_id"], APPROVER)

    validate_error(refused, ApiErrorId.ERR_BUMPER_EXCEEDED)
    assert refused.status_code == 422, (
        f"the portfolio ceiling is a 422 refusal; got {refused.status_code}"
    )
    assert (
        validate_success(
            api_client.get_settlement_line(ctx["ppa_id"], ctx["line_id"], APPROVER)
        )["status"]
        == "SETTLEMENT_APPROVED"
    ), "a refused apply persists nothing"
    assert get_customer(ctx["customer_id"])["outstanding_balance_cents"] == 0, (
        "no balance may be carried by a settle that never happened"
    )
