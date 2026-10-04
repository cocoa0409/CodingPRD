"""Cyclic state machines and the state dimensions that ride alongside them.

Both entities exercised here return to a state they already left, so a linear
pipeline implementation is caught by the round trip rather than by a single
forward transition.
"""

from test_helpers import (
    ANALYST,
    AFTERCARE,
    LOGICAL_CLOCK_START,
    MANAGER,
    api_client,
    get_success_data,
    reset_clock,
    setup_active_registration,
    setup_registration_awaiting_lapse,
    setup_plan_environment,
    validate_success,
)


def test_promotional_plan_defaults_and_restores_customer_posture(api, credit_analyst_headers):
    """PRD §3.7: "The first hop sets `plan_status` to `DEFAULTED`. The second suspends the cardholder: `account_status` becomes `SUSPENDED`, `credit_tier` is forced to `NO_FILE`, `standalone_credit_limit_cents` is zeroed, and `revolving_utilization_bps` is pinned at 10000."

    Design: Difficulty/non_linear_state_machine/promotional_plan_default_reinstate_cycle_and_parallel_status
    """
    reset_clock(LOGICAL_CLOCK_START)
    customer, store, purchase, plan = setup_plan_environment()
    reset_clock("2027-12-15T00:00:00Z")
    get_success_data(api.default_plans_due(credit_analyst_headers))

    plan_after = get_success_data(api.get_promotional_plan(plan["id"], credit_analyst_headers))
    customer_after = get_success_data(api.get_customer(customer["id"], credit_analyst_headers))
    assert plan_after["plan_status"] == "DEFAULTED"
    assert customer_after["account_status"] == "SUSPENDED"
    assert customer_after["standalone_credit_limit_cents"] == 0
    assert customer_after["credit_tier"] == "NO_FILE"


def test_defaulted_plan_can_be_reinstated_to_accruing_and_its_customer_reopened(
        api, credit_analyst_headers):
    """PRD §3.2: "Reinstating a defaulted plan is an analyst action. It requires `plan_status` of `DEFAULTED`, the account status to be `SUSPENDED`, and the client's `expected_plan_version`."
    PRD §3.2: "The plan returns to `ACCRUING` — the cycle `DEFAULTED` to `ACCRUING` and back is permitted — its `simplicity_expires_at` is reset to the current instant plus `simplicity_months` so the deferral clock restarts"

    Design: Difficulty/non_linear_state_machine/promotional_plan_default_reinstate_cycle_and_parallel_status
    """
    reset_clock(LOGICAL_CLOCK_START)
    customer, store, purchase, plan = setup_plan_environment()
    reset_clock("2027-12-15T00:00:00Z")
    get_success_data(api.default_plans_due(credit_analyst_headers))
    defaulted = get_success_data(api.get_promotional_plan(plan["id"], credit_analyst_headers))
    assert defaulted["plan_status"] == "DEFAULTED"

    reinstated = validate_success(api.reinstate_promotional_plan(
        plan["id"], {"expected_plan_version": defaulted["version"]}, credit_analyst_headers), 200)
    assert reinstated["plan_status"] == "ACCRUING", (
        "the cycle DEFAULTED -> ACCRUING is reachable"
    )
    customer_after = get_success_data(api.get_customer(customer["id"], credit_analyst_headers))
    assert customer_after["account_status"] == "OPEN"


def test_payoff_after_reinstatement_clears_the_settlement_amount(
        api, credit_analyst_headers, customer_service_headers):
    """PRD §3.2: "`plan_status` becomes `PAID` and `paid_at` is stamped with the current instant; `deferred_interest_accrued_cents` and `final_settlement_amount_cents` both fall to 0, which is the forgiveness the promo promised"
    PRD §3.2: "and `merchant_deferral_fee_cents` is zeroed, refunding the merchant's deferral fee."

    Design: Difficulty/non_linear_state_machine/promotional_plan_default_reinstate_cycle_and_parallel_status
    """
    reset_clock(LOGICAL_CLOCK_START)
    customer, store, purchase, plan = setup_plan_environment()
    reset_clock("2027-12-15T00:00:00Z")
    get_success_data(api.default_plans_due(credit_analyst_headers))
    defaulted = get_success_data(api.get_promotional_plan(plan["id"], credit_analyst_headers))
    reinstated = get_success_data(api.reinstate_promotional_plan(
        plan["id"], {"expected_plan_version": defaulted["version"]}, credit_analyst_headers))
    reset_clock("2027-10-20T00:00:00Z")

    settled = get_success_data(api.get_promotional_plan(plan["id"], credit_analyst_headers))
    amount = settled["principal_cents"] + settled["deferred_interest_accrued_cents"]
    paid = validate_success(api.payoff_promotional_plan(
        plan["id"],
        {"amount_cents": amount, "expected_plan_version": settled["version"]},
        customer_service_headers), 200)
    assert paid["plan_status"] == "PAID"
    assert paid["paid_at"] is not None
    assert paid["final_settlement_amount_cents"] == 0
    assert paid["deferred_interest_accrued_cents"] == 0
    assert paid["merchant_deferral_fee_cents"] == 0


def test_plan_settlement_amount_reads_principal_only_once_capitalized(api, credit_analyst_headers):
    """PRD §2.5: "The plan's contractual balance is `final_settlement_amount_cents`. While the plan is `ACCRUING` it is `principal_cents` plus `deferred_interest_accrued_cents`. Once the plan is `CAPITALIZED` it is the principal alone."
    PRD §3.2: "The plan's `principal_cents` is increased by the accrued interest, `deferred_interest_accrued_cents` falls back to 0, `final_settlement_amount_cents` becomes the new principal, `plan_status` becomes `CAPITALIZED`"

    Design: Difficulty/non_linear_state_machine/promotional_plan_default_reinstate_cycle_and_parallel_status
    """
    reset_clock(LOGICAL_CLOCK_START)
    customer, store, purchase, plan = setup_plan_environment()
    reset_clock("2027-09-02T00:00:00Z")
    before = get_success_data(api.get_promotional_plan(plan["id"], credit_analyst_headers))
    assert before["plan_status"] == "ACCRUING"
    assert before["final_settlement_amount_cents"] == (
        before["principal_cents"] + before["deferred_interest_accrued_cents"]
    )

    get_success_data(api.capitalize_plans_due(credit_analyst_headers))
    after = get_success_data(api.get_promotional_plan(plan["id"], credit_analyst_headers))
    assert after["plan_status"] == "CAPITALIZED"
    assert after["deferred_interest_accrued_cents"] == 0
    assert after["final_settlement_amount_cents"] == after["principal_cents"]
    assert after["principal_cents"] > before["principal_cents"], (
        "the accrued interest is folded into the principal"
    )


def test_registration_lapse_increments_counts_and_customer_streak(api, credit_analyst_headers):
    """PRD §3.3: "Any registration still in `PENDING_INSPECTION` or `REMINDER_ISSUED` at an instant strictly after its `cure_expires_at` becomes `LAPSED` with `is_valid` false; `missed_inspection_count` increments by one"
    PRD §3.3: "and the cardholder's `lost_inspection_streak` increments by one, after which the tier is recomputed on the post-increment streak."

    Design: Difficulty/non_linear_state_machine/registration_lapse_renew_relapse_cycle_with_branching_grace_path
    """
    customer, store, diamond, registration = setup_registration_awaiting_lapse()
    get_success_data(api.lapse_registrations_due(credit_analyst_headers))

    lapsed = get_success_data(api.get_registration(registration["id"], credit_analyst_headers))
    assert lapsed["coverage_status"] == "LAPSED"
    assert lapsed["missed_inspection_count"] == 1
    assert lapsed["is_valid"] is False
    customer_after = get_success_data(api.get_customer(customer["id"], credit_analyst_headers))
    assert customer_after["lost_inspection_streak"] == 1


def test_lapsed_registration_renews_and_the_reminder_sweep_closes_the_cycle(
        api, store_manager_headers):
    """PRD §3.3: "A renewal does not by itself restore coverage: the registration sits in `RENEWED`, with `is_valid` false, until the reminder sweep returns it to `PENDING_INSPECTION`."
    PRD §3.3: "The registration's `renewal_count` increments, `coverage_status` becomes `RENEWED`, `registered_at` is reset to the current instant so the inspection clock restarts"

    Design: Difficulty/non_linear_state_machine/registration_lapse_renew_relapse_cycle_with_branching_grace_path
    """
    customer, store, diamond, registration = setup_registration_awaiting_lapse()
    get_success_data(api.lapse_registrations_due(ANALYST))

    renewed = validate_success(
        api.renew_registration(registration["id"], store_manager_headers), 200)
    assert renewed["coverage_status"] == "RENEWED"
    assert renewed["renewal_count"] == 1
    assert renewed["is_valid"] is False
    customer_after = get_success_data(api.get_customer(customer["id"], store_manager_headers))
    assert customer_after["lost_inspection_streak"] == 0, "renewal resets the streak"

    get_success_data(api.run_inspection_reminders(store_manager_headers))
    closed = get_success_data(api.get_registration(registration["id"], store_manager_headers))
    assert closed["coverage_status"] == "PENDING_INSPECTION", (
        "the cycle LAPSED -> RENEWED -> PENDING_INSPECTION closes"
    )


def test_cycle_records_exactly_one_visit_per_round(api, store_manager_headers):
    """PRD §3.3: "A registration in `RENEWED` also returns to `PENDING_INSPECTION` on this sweep, with `is_valid` false and a fresh scheduled visit for its due instant."
    PRD §3.3: "`missed_inspection_count` increments by one; every visit of the registration still in `SCHEDULED` becomes `NO_SHOW`"

    Design: Difficulty/non_linear_state_machine/registration_lapse_renew_relapse_cycle_with_branching_grace_path
    """
    customer, store, diamond, registration = setup_registration_awaiting_lapse()
    get_success_data(api.lapse_registrations_due(ANALYST))
    get_success_data(api.renew_registration(registration["id"], store_manager_headers))
    get_success_data(api.run_inspection_reminders(store_manager_headers))

    visits = validate_success(api.list_registration_inspection_visits(
        registration["id"], store_manager_headers), 200)
    assert len(visits) == 2, "one reminder-spawned visit per inspection cycle"
    assert sum(1 for v in visits if v["inspection_status"] == "NO_SHOW") == 1, (
        "the lapse marked the first cycle's scheduled visit a no-show"
    )


def test_timed_claim_closes_the_cycle_and_frees_the_open_inspection_slot(
        api, store_manager_headers):
    """PRD §3.3: "A visit claimed at or before the registration's `inspection_due_at` is timely: the registration's `coverage_status` becomes `ACTIVE` and `is_valid` becomes true."
    PRD §3.3: "On the timely path only, every other visit of that registration still in `SCHEDULED` becomes `NO_SHOW`, the store's `open_inspection_count` decrements by one, and the cardholder's `lost_inspection_streak` resets to 0"

    Design: Difficulty/non_linear_state_machine/registration_lapse_renew_relapse_cycle_with_branching_grace_path
    """
    customer, store, diamond, registration = setup_registration_awaiting_lapse()
    get_success_data(api.lapse_registrations_due(ANALYST))
    get_success_data(api.renew_registration(registration["id"], store_manager_headers))
    get_success_data(api.run_inspection_reminders(store_manager_headers))

    refreshed = get_success_data(api.get_registration(registration["id"], store_manager_headers))
    due = refreshed["inspection_due_at"]
    timed = validate_success(api.log_inspection_exam(
        registration["id"], {"visit_at": due, "result": "CLAIMED"}, store_manager_headers), 200)
    assert timed["coverage_status"] == "ACTIVE"
    assert timed["is_valid"] is True
    assert timed["last_inspection_at"] == due


def test_late_claim_within_the_cure_window_yields_grace_period_not_lapse(
        api, store_manager_headers):
    """PRD §3.3: "A visit claimed strictly after `inspection_due_at` but at or before `cure_expires_at` is late but cured: `coverage_status` becomes `GRACE_PERIOD`, and `is_valid` is true there as well — a cured gap is not a miss."
    PRD §3.3: "On the cured path the streak is deliberately left unchanged and the other scheduled visits are left alone."

    Design: Difficulty/non_linear_state_machine/registration_lapse_renew_relapse_cycle_with_branching_grace_path
    """
    customer, store, diamond, registration = setup_registration_awaiting_lapse()
    get_success_data(api.lapse_registrations_due(ANALYST))
    get_success_data(api.renew_registration(registration["id"], store_manager_headers))
    get_success_data(api.run_inspection_reminders(store_manager_headers))

    refreshed = get_success_data(api.get_registration(registration["id"], store_manager_headers))
    late = refreshed["cure_expires_at"]
    cured = validate_success(api.log_inspection_exam(
        registration["id"], {"visit_at": late, "result": "CLAIMED"}, store_manager_headers), 200)
    assert cured["coverage_status"] == "GRACE_PERIOD"
    assert cured["is_valid"] is True, "a cured gap is not a miss"
    customer_after = get_success_data(api.get_customer(customer["id"], store_manager_headers))
    assert customer_after["lost_inspection_streak"] == 0