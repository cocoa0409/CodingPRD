"""The layers that cut across the whole surface.

Covers the optimistic-concurrency token of PRD §2.8 on the quote-create write,
the all-or-nothing character of the five-hop mobilization cascade of PRD §3.6
under a rung-3 refusal, and the strict-inequality credit gate of PRD §3.5 read
on all three sides of its threshold.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers import test_users as U
from test_helpers.api_errors import (
    ERR_ACCOUNT_CREDIT_HOLD,
    ERR_STALE_VERSION,
    ERR_VALIDATION,
)
from test_helpers.assertions import (
    assert_cents,
    assert_credit_hold,
    assert_fleet_counts,
    assert_instant,
    assert_integer,
    assert_invoice_rollup,
    assert_labor_hours,
)


def test_the_jobsite_token_is_spent_by_the_accepted_quote_and_not_by_the_refused_one(api):
    """PRD §2.8: "If that value does not equal the jobsite's current `version`, the
    create is rejected with `ERR_STALE_VERSION` and HTTP 412, and nothing is
    written", and PRD §3.2: "Creating it also advances the jobsite's own `version` by
    1." One accepted create therefore invalidates the token the client held, while a
    refused create consumes nothing.

    Design: Corner/cross_cutting_complexity_layers/stale_expected_jobsite_version_on_quote_create_rejected
    """
    world = FX.seed_world(api)
    jobsite_id = world["jobsite"]["id"]
    stale_version = world["jobsite"]["version"]
    assert_integer(stale_version, 1, "version")

    first = validate_success(
        api.create_quote(
            jobsite_id,
            F.quote_payload(stale_version, linear_feet=500),
            U.ACCOUNT_MANAGER,
        ),
        expected_status=201,
    )
    assert first["status"] == C.QUOTE_DRAFT

    # The very token that was correct one call ago is now one behind.
    validate_error(
        api.create_quote(
            jobsite_id,
            F.quote_payload(stale_version, linear_feet=400),
            U.ACCOUNT_MANAGER,
        ),
        ERR_STALE_VERSION,
        412,
    )

    held = FX.read_quote(api, first["id"])
    assert held["status"] == C.QUOTE_DRAFT
    body = api.list_quotes(
        U.ACCOUNT_MANAGER, params={"jobsite_id": jobsite_id, "limit": C.MAX_LIMIT}
    ).json()
    assert_integer(body["meta"]["total_count"], 1, "total_count")
    assert [row["linear_feet"] for row in body["data"]] == [500], body

    fresh_version = FX.read_jobsite(api, jobsite_id)["version"]
    assert_integer(fresh_version, stale_version + 1, "version")

    second = validate_success(
        api.create_quote(
            jobsite_id,
            F.quote_payload(fresh_version, linear_feet=400),
            U.ACCOUNT_MANAGER,
        ),
        expected_status=201,
    )
    assert_integer(second["linear_feet"], 400, "linear_feet")
    assert second["id"] != first["id"]

    # Two accepted writes, two increments: the refusal in between cost nothing.
    assert_integer(
        FX.read_jobsite(api, jobsite_id)["version"], stale_version + 2, "version"
    )
    # And the newer configuration closed out the older one (PRD §3.2).
    assert FX.read_quote(api, first["id"])["status"] == C.QUOTE_SUPERSEDED


def test_a_refused_completion_leaves_none_of_its_five_side_effects(api):
    """PRD §3.6 fires five hops from one completion, and it refuses the report
    outright when "`completed_linear_feet` ... must be strictly greater than zero and
    at most the visit's `ordered_linear_feet`, and anything outside that range is
    `ERR_VALIDATION`" at rung 3 — so no hop may be half-applied.

    Design: Corner/cross_cutting_complexity_layers/a_refused_completion_leaves_none_of_its_five_side_effects
    """
    world = FX.seed_world(api)
    account_id = world["account"]["id"]
    panel_id = world["panel"]["id"]
    state = FX.seed_scheduled_install(
        api,
        world,
        linear_feet=500,
        dispatch_clock=C.CLOCK_AUG_01,
        scheduled_start="2026-08-03T08:00:00Z",
    )
    contract_id = state["contract"]["id"]
    install_id = state["install"]["id"]

    assert state["install"]["status"] == C.WO_SCHEDULED
    assert_fleet_counts(
        FX.read_product(api, panel_id), available=350, reserved=50, deployed=0
    )

    validate_error(
        api.complete_work_order(
            install_id, F.complete_payload(600), U.DISPATCH_COORDINATOR
        ),
        ERR_VALIDATION,
        400,
    )

    # Hop one did not happen.
    refused = FX.read_work_order(api, install_id)
    assert refused["status"] == C.WO_SCHEDULED
    assert refused["completed_by_user_id"] is None
    # PRD §3.5 creates a planned visit with `completed_linear_feet` 0.
    assert_integer(refused["completed_linear_feet"], 0, "completed_linear_feet")

    # Hops two and four did not happen.
    unmoved = FX.read_contract(api, contract_id)
    assert unmoved["lifecycle_status"] == C.LIFECYCLE_PENDING_MOBILIZATION
    assert unmoved["billing_status"] == C.BILLING_NOT_BILLED
    assert unmoved["billing_anchor_utc"] is None
    assert FX.invoices_for(api, contract_id) == []

    # Hop three did not happen: the reservation still stands where dispatch put it.
    assert_fleet_counts(
        FX.read_product(api, panel_id), available=350, reserved=50, deployed=0
    )

    # Hop five did not happen.
    quiet = FX.read_account(api, account_id)
    assert_cents(quiet["open_balance_cents"], 0, "open_balance_cents")

    completed = validate_success(
        api.complete_work_order(
            install_id, F.complete_payload(500), U.DISPATCH_COORDINATOR
        )
    )

    assert completed["status"] == C.WO_COMPLETED
    assert_integer(completed["completed_linear_feet"], 500, "completed_linear_feet")

    activated = FX.read_contract(api, contract_id)
    assert activated["lifecycle_status"] == C.LIFECYCLE_ACTIVE
    assert activated["billing_status"] == C.BILLING_CURRENT
    assert_instant(activated["billing_anchor_utc"], C.CLOCK_AUG_01, "billing_anchor_utc")
    assert_integer(activated["deployed_linear_feet"], 500, "deployed_linear_feet")

    assert_fleet_counts(
        FX.read_product(api, panel_id), available=350, reserved=0, deployed=50
    )

    invoices = FX.invoices_for(api, contract_id)
    assert len(invoices) == 1, invoices
    assert invoices[0]["invoice_kind"] == C.KIND_MOBILIZATION
    assert invoices[0]["status"] == C.INVOICE_ISSUED
    assert_invoice_rollup(invoices[0], subtotal=78500, tax=6987, late_fee=0, total=85487)

    # The balance moved exactly once, on the accepted call.
    settled = FX.read_account(api, account_id)
    assert_cents(settled["open_balance_cents"], 85487, "open_balance_cents")
    assert_credit_hold(settled)


def test_the_credit_gate_is_a_strict_inequality_that_never_latches(api):
    """PRD §3.5: "Dispatch is refused with `ERR_ACCOUNT_CREDIT_HOLD`, carrying HTTP
    402, while the contract's owning account has `credit_hold_flag` true — that is,
    while its `open_balance_cents` is strictly greater than its `credit_limit_cents`",
    and the gate "comes sixth and last" among the dispatch rules, so it is recomputed
    on every request rather than latched.

    Design: Corner/cross_cutting_complexity_layers/credit_hold_fires_only_strictly_above_the_limit_and_clears_on_payment
    """
    world = FX.seed_world(
        api,
        account={"credit_limit_cents": 85487},
        jobsite={"site_label": "Foundry Road North Pad", "address_line": "402 Foundry Road"},
    )
    account_id = world["account"]["id"]
    panel_id = world["panel"]["id"]
    crew_id = world["crew"]["id"]
    assert_cents(world["account"]["credit_limit_cents"], 85487, "credit_limit_cents")

    north = FX.seed_installed_contract(
        api,
        world,
        linear_feet=500,
        install_clock=C.CLOCK_AUG_01,
        install_start="2026-08-03T08:00:00Z",
    )
    first_invoice = north["mobilization_invoice"]
    assert first_invoice is not None, "the mobilization cascade must issue an invoice"
    assert_invoice_rollup(first_invoice, subtotal=78500, tax=6987, late_fee=0, total=85487)

    # The balance now sits exactly on the limit, which the strict rule admits.
    at_the_limit = FX.read_account(api, account_id)
    assert_cents(at_the_limit["open_balance_cents"], 85487, "open_balance_cents")
    assert at_the_limit["credit_hold_flag"] is False
    assert_credit_hold(at_the_limit)

    south = FX.add_jobsite(
        world, api, site_label="Foundry Road South Pad", address_line="406 Foundry Road"
    )
    second_contract, _quote = FX.seed_contract(
        api, south["id"], account_id, linear_feet=200
    )
    second_install = FX.plan_work_order(
        api, second_contract["id"], C.WO_DELIVERY_INSTALL, 200
    )

    admitted = validate_success(
        api.dispatch_work_order(
            second_install["id"],
            F.dispatch_payload(crew_id, "2026-08-04T08:00:00Z"),
            U.DISPATCH_COORDINATOR,
        )
    )
    assert admitted["status"] == C.WO_SCHEDULED
    assert admitted["reserved_unit_counts"] == [
        {"product_code": C.PANEL_CODE, "unit_count": 20}
    ]

    FX.complete(api, second_install["id"], 200)
    second_invoices = FX.invoices_for(api, second_contract["id"])
    assert len(second_invoices) == 1, second_invoices
    # 200 feet at the 62-cent tier, labor floored to 35000, so 66000 plus 890 bp.
    assert_invoice_rollup(
        second_invoices[0], subtotal=66000, tax=5874, late_fee=0, total=71874
    )

    on_hold = FX.read_account(api, account_id)
    assert_cents(on_hold["open_balance_cents"], 157361, "open_balance_cents")
    assert on_hold["credit_hold_flag"] is True
    assert_credit_hold(on_hold)

    removal = FX.plan_work_order(api, second_contract["id"], C.WO_REMOVAL, 200)

    # Every earlier gate is clear — the site needs no permit, the removal reserves
    # nothing, the crew is free on 2026-08-06 and well under its 12-hour day.
    validate_error(
        api.dispatch_work_order(
            removal["id"],
            F.dispatch_payload(crew_id, "2026-08-06T08:00:00Z"),
            U.DISPATCH_COORDINATOR,
        ),
        ERR_ACCOUNT_CREDIT_HOLD,
        402,
    )

    barred = FX.read_work_order(api, removal["id"])
    assert barred["status"] == C.WO_PLANNED
    assert barred["crew_id"] is None
    assert barred["reserved_unit_counts"] == []
    assert_fleet_counts(
        FX.read_product(api, panel_id), available=330, reserved=0, deployed=70
    )

    # A payment that lands the balance back exactly on the limit. PRD §4 makes
    # paying an operation on an existing resource, so it answers 200, and PRD §3.8
    # allocates it oldest-due first — both invoices fell due on 2026-08-31, so the
    # earlier-created one absorbs the whole amount.
    paid = validate_success(
        api.create_payment(account_id, F.payment_payload(71874), U.ACCOUNT_MANAGER)
    )
    assert_cents(paid["open_balance_cents"], 85487, "open_balance_cents")
    assert paid["credit_hold_flag"] is False
    assert_credit_hold(paid)
    absorbed = FX.read_invoice(api, first_invoice["id"])
    assert absorbed["status"] == C.INVOICE_PARTIALLY_PAID
    assert_cents(absorbed["amount_paid_cents"], 71874, "amount_paid_cents")

    # The identical call now succeeds, so the hold was recomputed and not latched.
    released = validate_success(
        api.dispatch_work_order(
            removal["id"],
            F.dispatch_payload(crew_id, "2026-08-06T08:00:00Z"),
            U.DISPATCH_COORDINATOR,
        )
    )
    assert released["status"] == C.WO_SCHEDULED
    assert released["crew_id"] == crew_id
    assert_labor_hours(released["estimated_labor_hours"], 2.00)
    assert released["reserved_unit_counts"] == []
    assert_fleet_counts(
        FX.read_product(api, panel_id), available=330, reserved=0, deployed=70
    )
