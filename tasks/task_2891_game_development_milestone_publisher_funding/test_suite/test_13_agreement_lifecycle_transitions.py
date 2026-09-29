"""Agreement-level transitions: what activation moves, which preconditions guard it,
which triggers the current state does not admit, and what a terminal deal refuses."""

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_AGREEMENT_HAS_NO_MILESTONES,
    ERR_AGREEMENT_NOT_ACTIVE,
    ERR_AGREEMENT_NOT_DRAFT,
    ERR_AGREEMENT_NOT_SUSPENDED,
    ERR_AGREEMENT_TERMINAL,
    ERR_FUNDING_ALLOCATION_INCOMPLETE,
    ERR_PAYMENT_NOT_PENDING,
)
from test_helpers.assertions import (
    assert_fields_equal,
    assert_ledger,
    assert_payment_components,
)
from test_helpers.fixtures import (
    DEFAULT_CRITERIA_1,
    accept_milestone,
    activate,
    add_milestone,
    authorize_payment,
    draft_agreement,
    payment_of_milestone,
    read_agreement,
    read_milestone,
    setup_registry,
    setup_single_alpha,
    setup_twinpeak,
)
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)


def test_activation_promotes_only_the_dependency_free_milestone(api):
    """PRD §3.2: "On success the agreement moves `DRAFT → ACTIVE` with `funding_posture`
    set to `OPEN`, and a two-step cascade runs. Step one promotes every milestone of this
    agreement that is still `DEFINED` and has no predecessor from `DEFINED →
    IN_DEVELOPMENT`, opening the front of the schedule for delivery." The ledger is
    untouched by the promotion, so committed still equals the pool.

    Design: Corner/state_machines/corner_activate_moves_draft_agreement_to_active_and_starts_the_first_milestone
    """
    scenario = setup_twinpeak(api, activate_agreement=False)
    reg = scenario.reg
    assert read_milestone(reg, scenario.m1["id"])["status"] == "DEFINED"
    assert read_milestone(reg, scenario.m2["id"])["status"] == "DEFINED"

    before_activate = read_agreement(reg, scenario.agreement_id)["version"]
    activated = validate_success(api.activate_agreement(scenario.agreement_id, reg.finance))
    assert_fields_equal(
        activated,
        {
            "status": "ACTIVE",
            "version": before_activate + 1,
            "funding_posture": "OPEN",
        },
        "agreement",
    )
    assert_ledger(activated, committed_cents=6000000, available_funding_cents=0,
                  funding_pool_cents=6000000, accepted_value_cents=0)

    assert read_milestone(reg, scenario.m1["id"])["status"] == "IN_DEVELOPMENT"
    assert read_milestone(reg, scenario.m2["id"])["status"] == "DEFINED"


def test_activation_needs_a_milestone_before_it_needs_exact_funding(api):
    """PRD §3.2: activation "requires at least one milestone in `DEFINED`, without which
    the answer is `ERR_AGREEMENT_HAS_NO_MILESTONES`. Then the schedule must exhaust the
    advance **exactly**: `committed_cents` has to equal `funding_pool_cents`, and any
    discrepancy in either direction — an under-allocated schedule that leaves headroom or
    an over-allocated one — is refused with `ERR_FUNDING_ALLOCATION_INCOMPLETE`."

    Design: Corner/state_machines/corner_activation_preconditions_reject_empty_and_underfunded_milestone_schedules
    """
    reg = setup_registry(api, with_reviewer=False)
    hollow = draft_agreement(reg, "Hollow", 3600000,
                             live_ops_quarterly_funding_cents=100000)
    shortfall = draft_agreement(reg, "Shortfall", 3600000,
                                live_ops_quarterly_funding_cents=100000)
    short_m1 = add_milestone(reg, shortfall["id"], 1, "Alpha", "ALPHA", 2000000, 0,
                             DEFAULT_CRITERIA_1)
    # PRD §2.8: "If any precondition of the triggering operation fails, nothing is
    # written at all" — so the version observed before the refused activation must
    # survive it untouched.
    shortfall_version = read_agreement(reg, shortfall["id"])["version"]

    validate_error(
        api.activate_agreement(hollow["id"], reg.finance),
        ERR_AGREEMENT_HAS_NO_MILESTONES, 409,
    )
    validate_error(
        api.activate_agreement(shortfall["id"], reg.finance),
        ERR_FUNDING_ALLOCATION_INCOMPLETE, 422,
    )

    assert_fields_equal(read_agreement(reg, hollow["id"]),
                        {"status": "DRAFT", "version": 1}, "hollow agreement")
    after = read_agreement(reg, shortfall["id"])
    assert_fields_equal(after, {"status": "DRAFT", "version": shortfall_version},
                        "shortfall agreement")
    assert_ledger(after, committed_cents=2000000, available_funding_cents=1600000)
    assert read_milestone(reg, short_m1["id"])["status"] == "DEFINED"


def test_a_trigger_the_current_state_does_not_admit_is_refused(api):
    """PRD §3.3: "Only an agreement whose `status` is `SUSPENDED` may be reinstated —
    otherwise `ERR_AGREEMENT_NOT_SUSPENDED`" and "A `PublisherFinance` operator may
    suspend an agreement whose `status` is `ACTIVE`, optionally recording a free-text
    `reason`; anything other than `ACTIVE` is `ERR_AGREEMENT_NOT_ACTIVE`."

    Design: Corner/state_machines/corner_triggers_absent_from_the_active_transition_list_are_refused
    """
    scenario = setup_single_alpha(api, title="Aurora Solo", advance_total_cents=3600000,
                                 contractor_budget_cents=0,
                                 acceptance_criteria=DEFAULT_CRITERIA_1,
                                 live_ops_quarterly_funding_cents=100000)
    reg = scenario.reg
    sketchbook = draft_agreement(reg, "Sketchbook", 1000000, 2000, "2028-01-31",
                                 live_ops_quarterly_funding_cents=0)
    add_milestone(reg, sketchbook["id"], 1, "Alpha", "ALPHA", 1000000, 0,
                  DEFAULT_CRITERIA_1)
    # PRD §2.8: a refused trigger writes nothing, so both versions must be unchanged
    # across the two rejections below.
    active_version = scenario.read_agreement()["version"]
    sketchbook_version = read_agreement(reg, sketchbook["id"])["version"]

    validate_error(
        api.reinstate_agreement(scenario.agreement_id, reg.finance,
                                {"reason": "Nothing to reinstate"}),
        ERR_AGREEMENT_NOT_SUSPENDED, 409,
    )
    validate_error(
        api.suspend_agreement(sketchbook["id"], reg.finance, {"reason": "Premature"}),
        ERR_AGREEMENT_NOT_ACTIVE, 409,
    )

    assert_fields_equal(scenario.read_agreement(),
                        {"status": "ACTIVE", "version": active_version},
                        "active agreement")
    assert_fields_equal(read_agreement(reg, sketchbook["id"]),
                        {"status": "DRAFT", "version": sketchbook_version},
                        "draft agreement")


def test_a_terminated_agreement_admits_neither_termination_nor_new_scope(api):
    """PRD §3.9: "an already-`TERMINATED` or `COMPLETED` agreement answers
    `ERR_AGREEMENT_TERMINAL`." PRD §3.2: "an agreement whose `status` is `TERMINATED` or
    `COMPLETED` refuses new milestones with `ERR_AGREEMENT_TERMINAL`."

    Design: Corner/state_machines/corner_terminated_agreement_accepts_no_further_transitions_or_scope
    """
    scenario = setup_single_alpha(api, title="Aurora Solo", advance_total_cents=3600000,
                                 contractor_budget_cents=0,
                                 acceptance_criteria=DEFAULT_CRITERIA_1,
                                 live_ops_quarterly_funding_cents=100000)
    reg = scenario.reg
    terminated = validate_success(
        api.terminate_agreement(scenario.agreement_id, reg.finance,
                                {"reason": "Studio insolvency"})
    )
    assert terminated["status"] == "TERMINATED"
    terminated_version = terminated["version"]

    validate_error(
        api.terminate_agreement(scenario.agreement_id, reg.finance, {"reason": "Again"}),
        ERR_AGREEMENT_TERMINAL, 409,
    )
    validate_error(
        api.create_milestone(
            f.milestone_payload(scenario.agreement_id, 2, "Post-mortem work", "BETA",
                                100000, 0, ["Wrap-up"]),
            reg.dev,
        ),
        ERR_AGREEMENT_TERMINAL, 409,
    )

    assert_fields_equal(scenario.read_agreement(),
                        {"status": "TERMINATED", "version": terminated_version},
                        "agreement")
    assert read_milestone(reg, scenario.m1["id"])["status"] == "CANCELLED"
    rows, meta = validate_paginated(
        api.list_milestones(reg.finance, {"agreement_id": scenario.agreement_id})
    )
    assert len(rows) == 1 and meta["total_count"] == 1


def test_replaying_an_applied_trigger_disburses_nothing_further(api):
    """PRD §2.10 rule 22: "The agreement is `DRAFT`, on activation —
    `ERR_AGREEMENT_NOT_DRAFT`." PRD §3.6: "The payment must be in
    `PENDING_AUTHORIZATION`, and a payment already `AUTHORIZED`, `HELD_PENDING_CURE` or
    `WITHHELD` is refused with `ERR_PAYMENT_NOT_PENDING`."

    Design: Corner/state_machines/corner_repeating_an_applied_trigger_is_refused_the_second_time
    """
    scenario = setup_single_alpha(api, title="Aurora Solo", advance_total_cents=3600000,
                                 contractor_budget_cents=0,
                                 acceptance_criteria=DEFAULT_CRITERIA_1,
                                 live_ops_quarterly_funding_cents=100000)
    reg = scenario.reg
    accept_milestone(reg, scenario.m1["id"], 1, end_hour=12)
    payment = payment_of_milestone(reg, scenario.m1["id"])
    authorize_payment(reg, payment["id"], "First authorization")

    validate_error(
        api.activate_agreement(scenario.agreement_id, reg.finance),
        ERR_AGREEMENT_NOT_DRAFT, 409,
    )
    validate_error(
        api.authorize_payment(payment["id"], reg.finance, {"memo": "Second authorization"}),
        ERR_PAYMENT_NOT_PENDING, 409,
    )

    settled = validate_success(api.get_payment(payment["id"], reg.finance))
    assert settled["status"] == "AUTHORIZED"
    assert_payment_components(settled, scheduled=3600000, overrun=0, gross=3600000,
                              holdback_bps=500, holdback=180000, net=3420000)
    assert_ledger(scenario.read_agreement(), advance_disbursed_cents=3420000,
                  holdback_reserve_cents=180000)
    assert scenario.read_agreement()["recoupment_state"] == "RECOUPING"


def test_the_funding_ledger_is_re_derived_after_every_milestone_insert(api):
    """PRD §2.6: "`committed_cents` is the sum, over every milestone of the agreement
    whose `status` is anything other than `CANCELLED`, of that milestone's
    `funded_amount_cents` plus its `uplift_cents`. `available_funding_cents` is
    `funding_pool_cents` minus `committed_cents`."

    Design: Corner/state_machines/corner_agreement_funding_ledger_reconciles_as_milestones_are_added
    """
    reg = setup_registry(api, with_reviewer=False)
    agreement = draft_agreement(reg, "Aurora Drift", 12000000,
                                live_ops_quarterly_funding_cents=500000)

    m1 = add_milestone(reg, agreement["id"], 1, "Alpha", "ALPHA", 3600000, 800000,
                       DEFAULT_CRITERIA_1)
    assert_ledger(read_agreement(reg, agreement["id"]), committed_cents=3600000,
                  available_funding_cents=8400000)

    m2 = add_milestone(reg, agreement["id"], 2, "Beta", "BETA", 5400000, 600000,
                       DEFAULT_CRITERIA_1, m1["id"])
    assert_ledger(read_agreement(reg, agreement["id"]), committed_cents=9000000,
                  available_funding_cents=3000000)

    add_milestone(reg, agreement["id"], 3, "Gold", "GOLD", 3000000, 400000,
                  DEFAULT_CRITERIA_1, m2["id"])
    assert_ledger(read_agreement(reg, agreement["id"]), committed_cents=12000000,
                  available_funding_cents=0, funding_pool_cents=12000000,
                  uplift_funded_cents=0)

    assert activate(reg, agreement["id"])["status"] == "ACTIVE"
    summary = validate_success(api.get_recoupment_summary(agreement["id"], reg.finance))
    assert_fields_equal(summary,
                        {"funding_pool_cents": 12000000, "advance_disbursed_cents": 0},
                        "recoupment summary")
