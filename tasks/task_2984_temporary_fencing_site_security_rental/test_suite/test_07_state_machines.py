"""Declared transitions, their side effects, and the edges that are not declared.

Covers the quote machine of PRD §3.2 and §3.3, the visit machine of PRD §3.5 and
§3.6, the permit machine of PRD §3.4, the terminal contract states of PRD §3.9
and the single finalization edge of PRD §3.7.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers import test_users as U
from test_helpers.api_errors import (
    ERR_CONTRACT_STATE,
    ERR_QUOTE_STATE,
    ERR_RECONCILIATION_STATE,
    ERR_WORK_ORDER_STATE,
)
from test_helpers.assertions import (
    assert_cents,
    assert_days_apart,
    assert_fleet_counts,
    assert_freshly_created,
    assert_instant,
    assert_integer,
    assert_labor_hours,
    ids_of,
)


def test_issuing_a_draft_quote_stamps_a_fourteen_day_validity_window(api):
    """PRD §3.3: "Issuance takes no request body. It stamps `issued_at_utc` with
    the logical clock and sets `valid_through_utc` to exactly fourteen days — two
    weeks — after that instant, then advances the quote's `version` by 1."

    Design: Corner/state_machines/issue_quote_from_draft_stamps_validity_window
    """
    world = FX.seed_world(api, jobsite={"phase_count": 4})
    quote = FX.seed_quote(api, world["jobsite"]["id"], linear_feet=500)
    assert quote["status"] == C.QUOTE_DRAFT
    assert_freshly_created(quote)

    issued = validate_success(api.issue_quote(quote["id"], U.ACCOUNT_MANAGER))

    assert issued["status"] == C.QUOTE_ISSUED
    assert_instant(issued["issued_at_utc"], C.CLOCK_AUG_01, "issued_at_utc")
    assert_instant(
        issued["valid_through_utc"], "2026-08-15T00:00:00Z", "valid_through_utc"
    )
    assert_days_apart(
        issued["valid_through_utc"],
        issued["issued_at_utc"],
        C.QUOTE_VALIDITY_DAYS,
        "validity window",
    )
    assert_integer(issued["version"], 2, "version")

    # Issuance re-prices nothing.
    assert_cents(issued["monthly_recurring_cents"], 27000, "monthly_recurring_cents")
    assert_cents(issued["one_time_cents"], 78500, "one_time_cents")
    assert_cents(issued["install_labor_cents"], 47500, "install_labor_cents")


def test_completing_a_never_dispatched_visit_is_refused(api):
    """PRD §3.6: "Only a `SCHEDULED` visit may be reported; anything else is
    `ERR_WORK_ORDER_STATE`." The precondition is checked at rung 9 of PRD §2.7,
    so a perfectly valid footage report does not get past it.

    Design: Corner/state_machines/complete_a_planned_work_order_rejected
    """
    world = FX.seed_world(api, jobsite={"phase_count": 4})
    contract, _quote = FX.seed_contract(
        api, world["jobsite"]["id"], world["account"]["id"], linear_feet=500
    )
    planned = FX.plan_work_order(api, contract["id"], C.WO_DELIVERY_INSTALL, 500)
    assert planned["status"] == C.WO_PLANNED

    validate_error(
        api.complete_work_order(
            planned["id"], F.complete_payload(500), U.DISPATCH_COORDINATOR
        ),
        ERR_WORK_ORDER_STATE,
        409,
    )

    unmoved = FX.read_work_order(api, planned["id"])
    assert unmoved["status"] == C.WO_PLANNED
    assert_integer(unmoved["completed_linear_feet"], 0, "completed_linear_feet")
    assert unmoved["completed_by_user_id"] is None

    reread = FX.read_contract(api, contract["id"])
    assert reread["lifecycle_status"] == C.LIFECYCLE_PENDING_MOBILIZATION
    assert reread["billing_status"] == C.BILLING_NOT_BILLED
    assert FX.invoices_for(api, contract["id"]) == []

    account = FX.read_account(api, world["account"]["id"])
    assert_cents(account["open_balance_cents"], 0, "open_balance_cents")


def test_one_dispatch_applies_crew_hours_and_reservation_together(api):
    """PRD §3.5: "Dispatch ... records the `crew_id`, computes and stores
    `estimated_labor_hours` and `scheduled_end_utc`, moves the panel units of the
    visit into `reserved_count`" — 500 feet on soil at 120 feet an hour rounds up
    to 4.25 hours.

    Design: Corner/state_machines/dispatch_sets_crew_reservation_and_scheduled_end
    """
    world = FX.seed_world(api, jobsite={"phase_count": 4})
    contract, _quote = FX.seed_contract(
        api, world["jobsite"]["id"], world["account"]["id"], linear_feet=500
    )
    install = FX.plan_work_order(api, contract["id"], C.WO_DELIVERY_INSTALL, 500)
    crew_id = world["crew"]["id"]

    scheduled = validate_success(
        api.dispatch_work_order(
            install["id"],
            F.dispatch_payload(crew_id, "2026-08-03T08:00:00Z"),
            U.DISPATCH_COORDINATOR,
        )
    )

    assert scheduled["status"] == C.WO_SCHEDULED
    assert scheduled["crew_id"] == crew_id
    assert_instant(
        scheduled["scheduled_start_utc"], "2026-08-03T08:00:00Z", "scheduled_start_utc"
    )
    assert_labor_hours(scheduled["estimated_labor_hours"], 4.25)
    assert_instant(
        scheduled["scheduled_end_utc"], "2026-08-03T12:15:00Z", "scheduled_end_utc"
    )
    assert scheduled["reserved_unit_counts"] == [
        {"product_code": C.PANEL_CODE, "unit_count": 50}
    ]
    assert_integer(scheduled["version"], 2, "version")

    panel = FX.read_product(api, world["panel"]["id"])
    assert_fleet_counts(panel, available=350, reserved=50, deployed=0, damaged=0, lost=0)
    assert_integer(panel["owned_count"], C.PANEL_OWNED_COUNT, "owned_count")


def test_reissuing_an_accepted_quote_is_refused_and_leaves_validity_alone(api):
    """PRD §3.3: "Attempting to issue a quote that is not in `DRAFT` is refused
    with `ERR_QUOTE_STATE`." Nothing about the refused call re-stamps the
    fourteen-day window.

    Design: Corner/state_machines/issue_an_already_accepted_quote_rejected
    """
    world = FX.seed_world(api, jobsite={"phase_count": 4})
    accepted = FX.seed_accepted_quote(
        api, world["jobsite"]["id"], world["account"]["id"], linear_feet=500
    )
    assert accepted["status"] == C.QUOTE_ACCEPTED
    assert_integer(accepted["version"], 3, "version")
    assert_instant(
        accepted["valid_through_utc"], "2026-08-15T00:00:00Z", "valid_through_utc"
    )

    validate_error(
        api.issue_quote(accepted["id"], U.ACCOUNT_MANAGER), ERR_QUOTE_STATE, 409
    )

    reread = FX.read_quote(api, accepted["id"])
    assert reread["status"] == C.QUOTE_ACCEPTED
    assert_instant(
        reread["valid_through_utc"], "2026-08-15T00:00:00Z", "valid_through_utc"
    )
    assert_instant(reread["issued_at_utc"], C.CLOCK_AUG_01, "issued_at_utc")
    assert_integer(reread["version"], 3, "version")


def test_a_new_permit_opens_in_draft_holding_no_corridor_footage(api):
    """PRD §3.4: "The application is created in `DRAFT` with `revision_round` 0,
    and it holds no corridor footage yet; `submitted_at_utc`, `decided_at_utc`,
    `reviewer_note` and `required_change_summary` all start null."

    Design: Corner/state_machines/new_permit_starts_in_draft_with_zero_revision_round
    """
    world = FX.seed_world(api, jobsite={"requires_sidewalk_closure": True})

    permit = validate_success(
        api.create_permit(
            F.permit_payload(world["jobsite"]["id"]), U.MUNICIPAL_LIAISON
        ),
        expected_status=201,
    )

    assert permit["status"] == C.PERMIT_DRAFT
    assert_integer(permit["revision_round"], 0, "revision_round")
    assert permit["submitted_at_utc"] is None
    assert permit["decided_at_utc"] is None
    assert permit["reviewer_note"] is None
    assert permit["required_change_summary"] is None
    assert_integer(permit["closure_linear_feet"], 300, "closure_linear_feet")
    assert_freshly_created(permit)

    municipality = FX.read_municipality(api, world["municipality"]["id"])
    assert_integer(
        municipality["committed_closure_linear_feet"],
        0,
        "committed_closure_linear_feet",
    )


def test_a_cancelled_contract_refuses_planning_cancelling_and_billing(api):
    """PRD §3.9: "Both `CLOSED` and `CANCELLED` are terminal in the mobilization
    dimension: no further visit may be planned or dispatched, no phase move
    ordered, and no billing period run against a contract in either." With no
    install visit ever planned, "the `cancellation_fee_cents` is 0" and "no invoice
    is created at all".

    Design: Corner/state_machines/cancelled_contract_refuses_every_further_operation
    """
    world = FX.seed_world(api, jobsite={"phase_count": 4})
    contract, _quote = FX.seed_contract(
        api, world["jobsite"]["id"], world["account"]["id"], linear_feet=500
    )

    cancelled = validate_success(
        api.cancel_contract(
            contract["id"], F.cancel_payload("CUSTOMER_WITHDREW"), U.ACCOUNT_MANAGER
        )
    )
    assert cancelled["lifecycle_status"] == C.LIFECYCLE_CANCELLED
    assert_cents(cancelled["cancellation_fee_cents"], 0, "cancellation_fee_cents")
    assert cancelled["billing_status"] == C.BILLING_NOT_BILLED

    validate_error(
        api.create_work_order(
            contract["id"],
            F.work_order_payload(C.WO_DELIVERY_INSTALL, 500),
            U.DISPATCH_COORDINATOR,
        ),
        ERR_CONTRACT_STATE,
        409,
    )

    validate_error(
        api.cancel_contract(
            contract["id"], F.cancel_payload("DUPLICATE"), U.ACCOUNT_MANAGER
        ),
        ERR_CONTRACT_STATE,
        409,
    )

    # The window is itself invalid — its end is past the clock — but rung 9 of
    # PRD §2.7 answers before rung 16 ever runs.
    validate_error(
        api.create_billing_run(
            contract["id"],
            F.billing_run_payload(C.CLOCK_AUG_01, "2026-08-29T00:00:00Z"),
            U.ACCOUNT_MANAGER,
        ),
        ERR_CONTRACT_STATE,
        409,
    )

    assert FX.invoices_for(api, contract["id"]) == []
    account = FX.read_account(api, world["account"]["id"])
    assert_cents(account["open_balance_cents"], 0, "open_balance_cents")
    assert account["credit_hold_flag"] is False


def test_replaying_the_finalize_call_is_refused_and_re_applies_nothing(api):
    """PRD §2.7 rung 9: "repeating a transition that has already been applied,
    fails here with the owning entity's state error" — `ERR_RECONCILIATION_STATE`.
    PRD §3.7: with loss and damage both zero "no `FINAL` invoice is issued at all".

    Design: Corner/state_machines/second_finalize_of_reconciliation_rejected
    """
    world = FX.seed_world(api)
    state = FX.seed_demobilizing_contract(api, world, linear_feet=500)
    reconciliation = state["reconciliation"]
    assert reconciliation["status"] == C.REC_OPEN

    clean_return = [F.unit_return(C.PANEL_CODE, returned=50)]
    finalized = validate_success(
        api.finalize_reconciliation(
            reconciliation["id"],
            F.finalize_payload(clean_return, auditor_note="clean return, full count"),
            U.YARD_AUDITOR,
        )
    )
    assert finalized["status"] == C.REC_FINALIZED
    assert finalized["assessment_variant"] == C.VARIANT_REPLACEMENT_COST
    assert_cents(finalized["loss_charge_cents"], 0, "loss_charge_cents")
    assert_cents(finalized["damage_charge_cents"], 0, "damage_charge_cents")
    assert finalized["finalized_by_user_id"] == U.YARD_AUDITOR_ID

    validate_error(
        api.finalize_reconciliation(
            reconciliation["id"], F.finalize_payload(clean_return), U.YARD_AUDITOR
        ),
        ERR_RECONCILIATION_STATE,
        409,
    )

    replayed = FX.read_reconciliation(api, reconciliation["id"])
    assert replayed["status"] == C.REC_FINALIZED
    assert_integer(replayed["version"], finalized["version"], "version")
    assert_cents(replayed["loss_charge_cents"], 0, "loss_charge_cents")
    assert_cents(replayed["damage_charge_cents"], 0, "damage_charge_cents")

    assert FX.invoices_for(api, state["contract"]["id"], invoice_kind=C.KIND_FINAL) == []
    assert_fleet_counts(
        FX.read_product(api, world["panel"]["id"]),
        available=C.PANEL_OWNED_COUNT,
        reserved=0,
        deployed=0,
        damaged=0,
        lost=0,
    )


def test_a_partial_install_forks_a_remainder_visit_and_frees_the_spare_panels(api):
    """PRD §3.6: "only the panels actually erected move out of reserve ... and the
    untouched remainder of the reservation is returned from `reserved_count` to
    `available_count`" while "a follow-up visit is created in `PLANNED`" carrying
    "a `predecessor_relation` of `REMAINDER_OF`", and the contract mobilizes
    "exactly as the complete branch does".

    Design: Corner/state_machines/partial_install_creates_remainder_order_and_releases_reservation
    """
    world = FX.seed_world(api, jobsite={"phase_count": 4})
    contract, _quote = FX.seed_contract(
        api, world["jobsite"]["id"], world["account"]["id"], linear_feet=500
    )
    install = FX.plan_work_order(api, contract["id"], C.WO_DELIVERY_INSTALL, 500)
    FX.dispatch(api, install["id"], world["crew"]["id"], "2026-08-03T08:00:00Z")

    partial = validate_success(
        api.complete_work_order(
            install["id"], F.complete_payload(300), U.DISPATCH_COORDINATOR
        )
    )
    assert partial["status"] == C.WO_PARTIAL
    assert_integer(partial["completed_linear_feet"], 300, "completed_linear_feet")
    assert partial["completed_by_user_id"] == U.DISPATCH_COORDINATOR_ID

    followups = api.list_work_orders(
        U.DISPATCH_COORDINATOR,
        params={"predecessor_work_order_id": install["id"], "limit": C.MAX_LIMIT},
    ).json()
    remainders = followups["data"]
    assert len(remainders) == 1, remainders
    assert_integer(followups["meta"]["total_count"], 1, "total_count")
    remainder = remainders[0]
    assert remainder["work_order_type"] == C.WO_DELIVERY_INSTALL
    assert_integer(remainder["ordered_linear_feet"], 200, "ordered_linear_feet")
    assert remainder["status"] == C.WO_PLANNED
    assert remainder["crew_id"] is None
    assert remainder["reserved_unit_counts"] == []
    assert remainder["predecessor_relation"] == C.RELATION_REMAINDER_OF
    assert remainder["predecessor_work_order_id"] == install["id"]

    # 300 feet of ten-foot panels is 30 erected; the other 20 leave reserve.
    assert_fleet_counts(
        FX.read_product(api, world["panel"]["id"]),
        available=370,
        reserved=0,
        deployed=30,
        damaged=0,
        lost=0,
    )

    mobilized = FX.read_contract(api, contract["id"])
    assert mobilized["lifecycle_status"] == C.LIFECYCLE_ACTIVE
    assert_integer(mobilized["deployed_linear_feet"], 300, "deployed_linear_feet")
    assert mobilized["billing_status"] == C.BILLING_CURRENT
    assert_instant(mobilized["billing_anchor_utc"], C.CLOCK_AUG_01, "billing_anchor_utc")

    account = FX.read_account(api, world["account"]["id"])
    assert_cents(account["open_balance_cents"], 85487, "open_balance_cents")


def test_a_new_quote_supersedes_open_siblings_and_expires_the_elapsed_one(api):
    """PRD §3.2: "Every quote on that same jobsite whose `status` is `DRAFT` moves
    to `SUPERSEDED`. Every quote on that jobsite whose `status` is `ISSUED` is
    examined against the logical clock ... if the clock is strictly past its
    `valid_through_utc` it moves to `EXPIRED` instead. Quotes already in
    `CONVERTED`, `EXPIRED` or `SUPERSEDED` are left entirely alone."

    Design: Corner/state_machines/new_quote_supersedes_only_open_quotes_and_expires_elapsed_ones
    """
    world = FX.seed_world(api, jobsite={"phase_count": 4})
    jobsite_id = world["jobsite"]["id"]

    contract, converted = FX.seed_contract(
        api, jobsite_id, world["account"]["id"], linear_feet=500
    )
    assert FX.read_quote(api, converted["id"])["status"] == C.QUOTE_CONVERTED

    draft = FX.seed_quote(api, jobsite_id, linear_feet=400)
    issued = FX.issue_quote(api, FX.seed_quote(api, jobsite_id, linear_feet=300)["id"])
    assert_instant(
        issued["valid_through_utc"], "2026-08-15T00:00:00Z", "valid_through_utc"
    )
    assert FX.read_quote(api, draft["id"])["status"] == C.QUOTE_SUPERSEDED

    FX.set_clock(api, "2026-08-16T00:00:00Z")
    newest = FX.seed_quote(api, jobsite_id, linear_feet=250)

    assert newest["status"] == C.QUOTE_DRAFT
    assert FX.read_quote(api, converted["id"])["status"] == C.QUOTE_CONVERTED
    assert FX.read_quote(api, draft["id"])["status"] == C.QUOTE_SUPERSEDED
    assert FX.read_quote(api, issued["id"])["status"] == C.QUOTE_EXPIRED

    body = api.list_quotes(
        U.ACCOUNT_MANAGER, params={"jobsite_id": jobsite_id, "limit": C.MAX_LIMIT}
    ).json()
    assert_integer(body["meta"]["total_count"], 4, "total_count")
    assert sorted(row["status"] for row in body["data"]) == sorted(
        [C.QUOTE_CONVERTED, C.QUOTE_SUPERSEDED, C.QUOTE_EXPIRED, C.QUOTE_DRAFT]
    )
    assert ids_of(body["data"]) == [
        converted["id"],
        draft["id"],
        issued["id"],
        newest["id"],
    ]

    reread = FX.read_contract(api, contract["id"])
    assert_integer(
        reread["pinned_quote_version"],
        contract["pinned_quote_version"],
        "pinned_quote_version",
    )
