"""Refusals: the codes themselves, and the rung that owns each one.

Covers the four remaining not-found codes of PRD §2.7 rungs 4 and 5, registry
uniqueness and product-category integrity at rungs 20 and 21, fleet availability
at rung 19, the yard conservation rule at rung 23, the invoice state lock of
PRD §3.8 and the permit state lock of PRD §3.4, and the billing-window fence of
rung 16 against the inverted-window shape rule of rung 3.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers import test_users as U
from test_helpers.api_errors import (
    ERR_BILLING_PERIOD_INVALID,
    ERR_DUPLICATE_CODE,
    ERR_INSUFFICIENT_FLEET,
    ERR_INVALID_ADDON_CATEGORY,
    ERR_INVOICE_NOT_FOUND,
    ERR_INVOICE_STATE,
    ERR_PANEL_COUNT_MISMATCH,
    ERR_PERMIT_NOT_FOUND,
    ERR_PERMIT_STATE,
    ERR_QUOTE_NOT_FOUND,
    ERR_RECONCILIATION_NOT_FOUND,
    ERR_VALIDATION,
)
from test_helpers.assertions import (
    assert_cents,
    assert_fleet_counts,
    assert_instant,
    assert_integer,
    assert_invoice_rollup,
)

UNRESOLVABLE_ID = "00000000-0000-4000-8000-0000000000a1"


def _assert_error_envelope(response):
    """Every refusal wears the same three-key envelope of PRD §2.2."""
    body = response.json()
    assert set(body) == {"meta", "response_type", "data"}, body
    assert body["response_type"] == "error", body
    # "The `meta` object for error responses contains only `api_request_id` and
    # `api_request_timestamp`."
    assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}, body
    assert body["meta"]["api_request_id"].startswith("req_"), body
    assert body["data"]["message"], body
    return body


def test_each_collection_reports_its_own_not_found_code_for_the_same_id(api):
    """PRD §2.7: "(4) resolution of every `{id}` path segment to a stored row of
    the expected type, answered with that type's not-found error", and "Rungs 4 and
    5 share a family of not-found errors, one per resource type", naming
    `ERR_QUOTE_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND` and
    `ERR_RECONCILIATION_NOT_FOUND` among them.

    Design: Corner/errors/unknown_quote_permit_invoice_and_reconciliation_ids_not_found
    """
    FX.set_clock(api, C.CLOCK_AUG_01)

    probes = (
        (api.get_quote(UNRESOLVABLE_ID, U.ACCOUNT_MANAGER), ERR_QUOTE_NOT_FOUND),
        (api.get_permit(UNRESOLVABLE_ID, U.MUNICIPAL_LIAISON), ERR_PERMIT_NOT_FOUND),
        (api.get_invoice(UNRESOLVABLE_ID, U.ACCOUNT_MANAGER), ERR_INVOICE_NOT_FOUND),
        (
            api.get_reconciliation(UNRESOLVABLE_ID, U.YARD_AUDITOR),
            ERR_RECONCILIATION_NOT_FOUND,
        ),
    )

    for response, expected_error_id in probes:
        validate_error(response, expected_error_id, 404)
        _assert_error_envelope(response)

    # The four codes are distinct, so no endpoint answered with a generic one.
    assert len({expected for _r, expected in probes}) == 4


def test_repeated_codes_and_swapped_product_categories_are_all_refused(api):
    """PRD §3.1: "A jurisdiction's `jurisdiction_code` must be unique across all
    jurisdictions, and a product's `code` must be unique across all products ... a
    collision is refused with `ERR_DUPLICATE_CODE`." PRD §3.2: at rung 21
    "`panel_product_code` must reference a product whose `category` is
    `FENCE_PANEL` and every `addon_lines[].product_code` must reference a product
    whose `category` is `GATE`, `BARRICADE` or `WATER_BARRIER`; a panel listed as an
    add-on, or a gate nominated as the panel product, is refused with
    `ERR_INVALID_ADDON_CATEGORY`."

    Design: Corner/errors/duplicate_codes_and_miscategorised_products_rejected
    """
    world = FX.seed_world(api, addons=(C.GATE_CODE,))
    jobsite_id = world["jobsite"]["id"]
    assert world["products"][C.GATE_CODE]["category"] == C.CATEGORY_GATE
    assert world["panel"]["category"] == C.CATEGORY_FENCE_PANEL

    # A different jurisdiction under an already-registered code.
    validate_error(
        api.create_municipality(
            F.municipality_payload(
                name="Harbor Point Annex",
                permit_lead_time_days=7,
                max_concurrent_closure_linear_feet=400,
                rental_tax_rate_bp=500,
            ),
            U.PLATFORM_ADMIN,
        ),
        ERR_DUPLICATE_CODE,
        409,
    )

    # A different fleet batch under an already-registered product code.
    validate_error(
        api.create_product(
            F.panel_product_payload(
                description="duplicate panel registration",
                fleet_age_months=1,
                owned_count=10,
            ),
            U.PLATFORM_ADMIN,
        ),
        ERR_DUPLICATE_CODE,
        409,
    )

    # A gate nominated as the panel product.
    validate_error(
        api.create_quote(
            jobsite_id,
            F.quote_payload(1, linear_feet=500, panel_product_code=C.GATE_CODE),
            U.ACCOUNT_MANAGER,
        ),
        ERR_INVALID_ADDON_CATEGORY,
        409,
    )

    # And the same collision in the other direction: a panel listed as an add-on.
    validate_error(
        api.create_quote(
            jobsite_id,
            F.quote_payload(
                1,
                linear_feet=500,
                addon_lines=[F.addon_line(C.PANEL_CODE, 2)],
            ),
            U.ACCOUNT_MANAGER,
        ),
        ERR_INVALID_ADDON_CATEGORY,
        409,
    )

    assert_integer(FX.read_jobsite(api, jobsite_id)["version"], 1, "version")
    body = api.list_quotes(
        U.ACCOUNT_MANAGER, params={"jobsite_id": jobsite_id, "limit": C.MAX_LIMIT}
    ).json()
    assert body["data"] == [], body
    assert_integer(body["meta"]["total_count"], 0, "total_count")

    # Neither duplicate registration was stored either.
    municipalities = api.list_municipalities(
        U.PLATFORM_ADMIN, params={"limit": C.MAX_LIMIT}
    ).json()
    assert_integer(municipalities["meta"]["total_count"], 1, "total_count")
    products = api.list_products(
        U.PLATFORM_ADMIN, params={"limit": C.MAX_LIMIT}
    ).json()
    assert_integer(products["meta"]["total_count"], 2, "total_count")


def test_a_reservation_held_by_another_visit_starves_the_second_dispatch(api):
    """PRD §3.5: "**Fleet availability** comes fifth, and it is judged against the
    yard's `available_count` alone; units already held in `reserved_count` by
    another `SCHEDULED` visit are not available. Dispatching a `DELIVERY_INSTALL`
    visit requires the panel product's `available_count` to be at least the visit's
    `ordered_linear_feet` divided by that product's `panel_length_ft` and rounded up
    to the next whole panel."

    Design: Corner/errors/dispatch_short_of_available_panels_rejected
    """
    world = FX.seed_world(
        api,
        panel={"owned_count": 60},
        jobsite={
            "site_label": "Foundry Road North Pad",
            "address_line": "402 Foundry Road",
        },
    )
    account_id = world["account"]["id"]
    crew_id = world["crew"]["id"]
    south = FX.add_jobsite(
        world, api, site_label="Foundry Road South Pad", address_line="406 Foundry Road"
    )

    north_contract, _q1 = FX.seed_contract(
        api, world["jobsite"]["id"], account_id, linear_feet=500
    )
    south_contract, _q2 = FX.seed_contract(api, south["id"], account_id, linear_feet=200)

    first = FX.plan_work_order(api, north_contract["id"], C.WO_DELIVERY_INSTALL, 500)
    FX.dispatch(api, first["id"], crew_id, "2026-08-03T08:00:00Z")
    second = FX.plan_work_order(api, south_contract["id"], C.WO_DELIVERY_INSTALL, 200)

    # 200 feet of ten-foot panels is 20 panels; the yard owns 60 but only 10 are
    # free. The crew's calendar and its day cap are both clear on 2026-08-04, so
    # neither rung 14 nor rung 15 masks the fleet answer at rung 19.
    validate_error(
        api.dispatch_work_order(
            second["id"],
            F.dispatch_payload(crew_id, "2026-08-04T08:00:00Z"),
            U.DISPATCH_COORDINATOR,
        ),
        ERR_INSUFFICIENT_FLEET,
        409,
    )

    refused = FX.read_work_order(api, second["id"])
    assert refused["status"] == C.WO_PLANNED
    assert refused["crew_id"] is None
    assert refused["reserved_unit_counts"] == []

    # The refusal left the first visit's hold entirely alone.
    panel = FX.read_product(api, world["panel"]["id"])
    assert_fleet_counts(panel, available=10, reserved=50, deployed=0, damaged=0, lost=0)
    assert_integer(panel["owned_count"], 60, "owned_count")


def test_the_yard_count_must_balance_entry_by_entry_against_the_snapshot(api):
    """PRD §3.7: "`unit_returns` must cover precisely the product codes present in
    `deployed_snapshot` — no code missing, no code extra, no code repeated — and for
    every entry the sum of `returned`, `damaged` and `missing` must equal that
    product's `unit_count` ... Any deviation is refused with
    `ERR_PANEL_COUNT_MISMATCH`."

    Design: Corner/errors/unit_returns_must_account_for_every_deployed_panel_rejected
    """
    world = FX.seed_world(api, addons=(C.GATE_CODE,))
    state = FX.seed_demobilizing_contract(
        api,
        world,
        linear_feet=500,
        install_clock=C.CLOCK_AUG_01,
        install_start="2026-08-03T08:00:00Z",
        removal_clock=C.CLOCK_AUG_01,
        removal_start="2026-08-05T08:00:00Z",
    )
    reconciliation = state["reconciliation"]
    assert reconciliation is not None, "the removal must open a reconciliation"
    assert reconciliation["status"] == C.REC_OPEN
    assert reconciliation["deployed_snapshot"] == [
        {"product_code": C.PANEL_CODE, "unit_count": 50}
    ]

    # 49 + 0 + 0 does not reach the 50 panels in the snapshot.
    validate_error(
        api.finalize_reconciliation(
            reconciliation["id"],
            F.finalize_payload([F.unit_return(C.PANEL_CODE, returned=49)]),
            U.YARD_AUDITOR,
        ),
        ERR_PANEL_COUNT_MISMATCH,
        409,
    )

    # A gate that was never deployed is an extra code, even at a zero count.
    validate_error(
        api.finalize_reconciliation(
            reconciliation["id"],
            F.finalize_payload(
                [
                    F.unit_return(C.PANEL_CODE, returned=48, damaged=1, missing=1),
                    F.unit_return(C.GATE_CODE, returned=0),
                ]
            ),
            U.YARD_AUDITOR,
        ),
        ERR_PANEL_COUNT_MISMATCH,
        409,
    )

    held = FX.read_reconciliation(api, reconciliation["id"])
    assert held["status"] == C.REC_OPEN
    assert_integer(held["version"], reconciliation["version"], "version")

    finalized = validate_success(
        api.finalize_reconciliation(
            reconciliation["id"],
            F.finalize_payload(
                [F.unit_return(C.PANEL_CODE, returned=48, damaged=1, missing=1)],
                auditor_note="one panel bent, one missing",
            ),
            U.YARD_AUDITOR,
        )
    )

    assert finalized["status"] == C.REC_FINALIZED
    assert finalized["assessment_variant"] == C.VARIANT_REPLACEMENT_COST
    assert_cents(finalized["loss_charge_cents"], 24000, "loss_charge_cents")
    assert_cents(finalized["damage_charge_cents"], 8400, "damage_charge_cents")

    finals = FX.invoices_for(
        api, state["contract"]["id"], invoice_kind=C.KIND_FINAL
    )
    assert len(finals) == 1, finals
    assert_invoice_rollup(finals[0], subtotal=32400, tax=2884, late_fee=0, total=35284)

    panel = FX.read_product(api, world["panel"]["id"])
    assert_fleet_counts(panel, available=398, reserved=0, deployed=0, damaged=1, lost=1)
    assert_integer(panel["owned_count"], C.PANEL_OWNED_COUNT, "owned_count")


def test_both_terminal_invoice_states_lock_the_void_and_the_credit_lands_once(api):
    """PRD §3.8: "A void accepts an invoice whose `status` is `ISSUED` or
    `PARTIALLY_PAID` ... an invoice already `PAID` or already `VOID` is refused with
    `ERR_INVOICE_STATE`." PRD §2.10: "a void lowers it by exactly the amount that
    was still open at the moment of the void, and raises `lifetime_credited_cents`
    by that same amount ... a void never moves `amount_paid_cents`."

    Design: Corner/errors/void_of_a_paid_invoice_and_of_a_voided_invoice_rejected
    """
    world = FX.seed_world(api)
    account_id = world["account"]["id"]
    state = FX.seed_installed_contract(
        api,
        world,
        linear_feet=500,
        install_clock=C.CLOCK_AUG_01,
        install_start="2026-08-03T08:00:00Z",
    )
    mobilization = state["mobilization_invoice"]
    assert mobilization is not None, "the mobilization cascade must issue an invoice"
    assert_invoice_rollup(mobilization, subtotal=78500, tax=6987, late_fee=0, total=85487)
    assert mobilization["issued_by_user_id"] == U.DISPATCH_COORDINATOR_ID

    settled = FX.pay_account(api, account_id, 85487)
    assert_cents(settled["open_balance_cents"], 0, "open_balance_cents")
    assert FX.read_invoice(api, mobilization["id"])["status"] == C.INVOICE_PAID

    FX.set_clock(api, "2026-08-29T00:00:00Z")
    periodic = validate_success(
        api.create_billing_run(
            state["contract"]["id"],
            F.billing_run_payload(C.CLOCK_AUG_01, "2026-08-29T00:00:00Z"),
            U.ACCOUNT_MANAGER,
        ),
        expected_status=201,
    )
    assert_invoice_rollup(periodic, subtotal=27000, tax=2403, late_fee=0, total=29403)
    assert periodic["issued_by_user_id"] == U.ACCOUNT_MANAGER_ID

    # am-001 is not the mobilization invoice's issuer, so the four-eyes rule of
    # rung 7 stands aside and rung 9 reports the terminal PAID state.
    validate_error(
        api.void_invoice(mobilization["id"], F.void_payload(), U.ACCOUNT_MANAGER),
        ERR_INVOICE_STATE,
        409,
    )

    kept = FX.read_invoice(api, mobilization["id"])
    assert kept["status"] == C.INVOICE_PAID
    assert_cents(kept["amount_paid_cents"], 85487, "amount_paid_cents")
    assert kept["void_reason_code"] is None

    voided = validate_success(
        api.void_invoice(periodic["id"], F.void_payload(), U.ACCOUNT_MANAGER_2)
    )
    assert voided["status"] == C.INVOICE_VOID
    assert_cents(voided["amount_paid_cents"], 0, "amount_paid_cents")

    credited = FX.read_account(api, account_id)
    assert_cents(credited["open_balance_cents"], 0, "open_balance_cents")
    assert_cents(credited["lifetime_credited_cents"], 29403, "lifetime_credited_cents")

    validate_error(
        api.void_invoice(periodic["id"], F.void_payload(), U.ACCOUNT_MANAGER_2),
        ERR_INVOICE_STATE,
        409,
    )

    after_replay = FX.read_account(api, account_id)
    assert_cents(
        after_replay["lifetime_credited_cents"], 29403, "lifetime_credited_cents"
    )
    assert_cents(after_replay["open_balance_cents"], 0, "open_balance_cents")
    replayed = FX.read_invoice(api, periodic["id"])
    assert replayed["status"] == C.INVOICE_VOID
    assert_integer(replayed["version"], voided["version"], "version")


def test_the_permit_machine_refuses_a_decision_too_early_and_a_resubmit_too_late(api):
    """PRD §3.4: submission moves a `DRAFT` application to `SUBMITTED` and the
    municipal decision acts on a `SUBMITTED` one; PRD §2.7 rung 9 answers "the state
    check confirming the path entity is in the from-set of the transition being
    triggered" with `ERR_PERMIT_STATE` for permit applications.

    Design: Corner/errors/decision_on_a_draft_permit_and_resubmit_of_an_approved_permit_rejected
    """
    world = FX.seed_world(
        api,
        jobsite={
            "site_label": "Dock Street North",
            "address_line": "8 Dock Street",
            "site_condition": C.CONDITION_ASPHALT,
            "requires_sidewalk_closure": True,
        },
    )
    permit = FX.seed_permit(api, world["jobsite"]["id"])
    assert permit["status"] == C.PERMIT_DRAFT

    validate_error(
        api.decide_permit(
            permit["id"],
            F.decision_payload(C.DECISION_APPROVE, reviewer_note="premature decision"),
            U.MUNICIPAL_LIAISON,
        ),
        ERR_PERMIT_STATE,
        409,
    )

    too_early = FX.read_permit(api, permit["id"])
    assert too_early["status"] == C.PERMIT_DRAFT
    assert too_early["decided_at_utc"] is None
    assert too_early["reviewer_note"] is None

    submitted = validate_success(
        api.submit_permit(permit["id"], U.MUNICIPAL_LIAISON, F.submit_payload())
    )
    assert submitted["status"] == C.PERMIT_SUBMITTED

    approved = validate_success(
        api.decide_permit(
            permit["id"],
            F.decision_payload(C.DECISION_APPROVE, reviewer_note="closure cleared"),
            U.MUNICIPAL_LIAISON,
        )
    )
    assert approved["status"] == C.PERMIT_APPROVED
    assert_instant(approved["decided_at_utc"], C.CLOCK_AUG_01, "decided_at_utc")

    # An approved application is out of the submit transition's from-set, so the
    # 250-foot revision never reaches the corridor or the revision counter.
    validate_error(
        api.submit_permit(
            permit["id"], U.MUNICIPAL_LIAISON, F.submit_payload(closure_linear_feet=250)
        ),
        ERR_PERMIT_STATE,
        409,
    )

    too_late = FX.read_permit(api, permit["id"])
    assert too_late["status"] == C.PERMIT_APPROVED
    assert_integer(too_late["closure_linear_feet"], 300, "closure_linear_feet")
    assert_integer(too_late["revision_round"], 0, "revision_round")


def test_the_billing_window_is_fenced_on_three_sides_and_the_shape_rule_outranks_it(api):
    """PRD §3.8: at rung 16 "`period_end_utc` must be strictly after
    `period_start_utc`; `period_start_utc` must be at or after the contract's
    `billing_anchor_utc`; `period_end_utc` must be at or before the logical clock
    ... and `period_start_utc` must be at or after the `period_end_utc` of the
    contract's most recent `PERIODIC` invoice ... Any of the four failing is
    `ERR_BILLING_PERIOD_INVALID`." PRD §2.7 rung 3 answers first when "an instant is
    malformed or a window is inverted", with `ERR_VALIDATION`.

    Design: Corner/errors/billing_period_outside_the_anchor_and_the_clock_rejected
    """
    world = FX.seed_world(api)
    state = FX.seed_installed_contract(
        api,
        world,
        linear_feet=500,
        install_clock=C.CLOCK_AUG_01,
        install_start="2026-08-03T08:00:00Z",
    )
    contract_id = state["contract"]["id"]
    anchored = FX.read_contract(api, contract_id)
    assert_instant(anchored["billing_anchor_utc"], C.CLOCK_AUG_01, "billing_anchor_utc")

    FX.set_clock(api, "2026-08-29T00:00:00Z")
    assert FX.read_contract(api, contract_id)["billing_status"] == C.BILLING_CURRENT

    # A week before the anchor.
    validate_error(
        api.create_billing_run(
            contract_id,
            F.billing_run_payload("2026-07-25T00:00:00Z", "2026-08-29T00:00:00Z"),
            U.ACCOUNT_MANAGER,
        ),
        ERR_BILLING_PERIOD_INVALID,
        409,
    )

    # A week past the clock.
    validate_error(
        api.create_billing_run(
            contract_id,
            F.billing_run_payload(C.CLOCK_AUG_01, "2026-09-05T00:00:00Z"),
            U.ACCOUNT_MANAGER,
        ),
        ERR_BILLING_PERIOD_INVALID,
        409,
    )

    # Inverted, which is a shape failure at rung 3 rather than a billing failure.
    validate_error(
        api.create_billing_run(
            contract_id,
            F.billing_run_payload("2026-08-29T00:00:00Z", C.CLOCK_AUG_01),
            U.ACCOUNT_MANAGER,
        ),
        ERR_VALIDATION,
        400,
    )

    assert FX.invoices_for(api, contract_id, invoice_kind=C.KIND_PERIODIC) == []

    periodic = validate_success(
        api.create_billing_run(
            contract_id,
            F.billing_run_payload(C.CLOCK_AUG_01, "2026-08-29T00:00:00Z"),
            U.ACCOUNT_MANAGER,
        ),
        expected_status=201,
    )
    assert periodic["invoice_kind"] == C.KIND_PERIODIC
    assert_integer(periodic["billable_days"], 28, "billable_days")
    assert_invoice_rollup(periodic, subtotal=27000, tax=2403, late_fee=0, total=29403)

    # The fourth fence: the next period may not reach back inside the one just
    # billed, even though it clears the anchor and the clock.
    validate_error(
        api.create_billing_run(
            contract_id,
            F.billing_run_payload("2026-08-15T00:00:00Z", "2026-08-29T00:00:00Z"),
            U.ACCOUNT_MANAGER,
        ),
        ERR_BILLING_PERIOD_INVALID,
        409,
    )

    billed = FX.invoices_for(api, contract_id, invoice_kind=C.KIND_PERIODIC)
    assert len(billed) == 1, billed
    assert billed[0]["id"] == periodic["id"]
