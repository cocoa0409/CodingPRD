"""Default case lattice, suspension/resume cycle, and open_cure_count invariant."""
from test_helpers import (
    validate_success, get_success_data,
    setup_active_agreement, setup_suspended_agreement, open_default,
    TEST_USERS,
)

OPS = TEST_USERS["franchisor_ops_headers"]


def test_default_case_walks_open_curing_escalated_resolved(api):
    """PRD §3.8: "Starting the cure moves it `OPEN` → `CURING`. Escalation moves
    it from either `OPEN` or `CURING` to `ESCALATED`, stamping `escalated_at`"
    PRD §3.8: "Resolution closes the case to `RESOLVED` from any of `OPEN`,
    `CURING`, or `ESCALATED`."

    Design: Difficulty/non_linear_state_machine/default_case_branching_resolve_from_three_states
    """
    ctx = setup_active_agreement()
    ag_id = ctx["agreement"]["id"]
    case = open_default(ag_id, "PAYMENT")
    assert case["status"] == "OPEN"

    curing = get_success_data(api.start_cure_default_case(case["id"], OPS))
    assert curing["status"] == "CURING"

    escalated = get_success_data(api.escalate_default_case(case["id"], OPS))
    assert escalated["status"] == "ESCALATED"

    resolved = get_success_data(api.resolve_default_case(case["id"], OPS))
    assert resolved["status"] == "RESOLVED"

    agreement = get_success_data(api.get_agreement(ag_id, OPS))
    assert agreement["open_cure_count"] == 0


def test_resolution_directly_from_open_closes_case(api):
    """PRD §3.8: "Resolution closes the case to `RESOLVED` from any of `OPEN`,
    `CURING`, or `ESCALATED`. Every resolution recomputes `open_cure_count`"

    Design: Difficulty/non_linear_state_machine/default_case_branching_resolve_from_three_states
    """
    ctx = setup_active_agreement()
    ag_id = ctx["agreement"]["id"]
    case = open_default(ag_id, "REPORTING")
    agreement = get_success_data(api.get_agreement(ag_id, OPS))
    assert agreement["open_cure_count"] == 1

    resolved = get_success_data(api.resolve_default_case(case["id"], OPS))
    assert resolved["status"] == "RESOLVED"

    agreement = get_success_data(api.get_agreement(ag_id, OPS))
    assert agreement["open_cure_count"] == 0


def test_resolving_last_default_auto_resumes_suspended_agreement(api):
    """PRD §3.8: "Every resolution recomputes `open_cure_count`, and when the
    counter falls to zero while the agreement sits in `SUSPENDED`, the agreement
    resumes on its own — a system-driven `SUSPENDED` → `ACTIVE` hop that
    increments the agreement's `version`."

    Design: Difficulty/non_linear_state_machine/agreement_suspend_resume_cycle_via_default_resolution
    """
    ctx = setup_suspended_agreement()
    ag_id = ctx["agreement"]["id"]
    assert ctx["agreement"]["status"] == "SUSPENDED"

    get_success_data(api.resolve_default_case(ctx["default"]["id"], OPS))
    agreement = get_success_data(api.get_agreement(ag_id, OPS))
    assert agreement["status"] == "ACTIVE"
    assert agreement["open_cure_count"] == 0


def test_suspend_resume_cycle_repeats_on_second_default(api):
    """PRD §3.8: "Suspension is the franchisor's sanction short of termination:
    `FranchisorOps` moves an agreement `ACTIVE` → `SUSPENDED`, but only when at
    least one default case stands in `OPEN` or `CURING` — that is, when
    `open_cure_count` is at least 1."
    PRD §3.8: "when the counter falls to zero while the agreement sits in
    `SUSPENDED`, the agreement resumes on its own — a system-driven `SUSPENDED`
    → `ACTIVE` hop that increments the agreement's `version`."

    Design: Difficulty/non_linear_state_machine/agreement_suspend_resume_cycle_via_default_resolution
    """
    ctx = setup_suspended_agreement()
    ag_id = ctx["agreement"]["id"]
    get_success_data(api.resolve_default_case(ctx["default"]["id"], OPS))
    resumed = get_success_data(api.get_agreement(ag_id, OPS))
    assert resumed["status"] == "ACTIVE"

    # Second cycle: a new default permits another suspension, and resolving it
    # resumes the agreement again.
    second = open_default(ag_id, "REPORTING")
    suspended = get_success_data(api.suspend_agreement(ag_id, OPS))
    assert suspended["status"] == "SUSPENDED"
    get_success_data(api.resolve_default_case(second["id"], OPS))
    resumed_again = get_success_data(api.get_agreement(ag_id, OPS))
    assert resumed_again["status"] == "ACTIVE"


def test_resolving_escalated_default_does_not_decrement_open_cure_count(api):
    """PRD §3.8: "Each creation, escalation, and resolution recomputes the
    agreement's `open_cure_count`, which counts only cases in `OPEN` or `CURING`;
    `ESCALATED` cases do not count toward it (they gate termination instead), and
    `RESOLVED` cases never count."

    Design: Difficulty/compensating_invariant/open_cure_count_invariant_under_resolve_cycles
    """
    ctx = setup_active_agreement()
    ag_id = ctx["agreement"]["id"]
    d1 = open_default(ag_id, "PAYMENT")
    d2 = open_default(ag_id, "REPORTING")
    d3 = open_default(ag_id, "TERRITORY")
    get_success_data(api.start_cure_default_case(d2["id"], OPS))
    get_success_data(api.escalate_default_case(d3["id"], OPS))

    agreement = get_success_data(api.get_agreement(ag_id, OPS))
    assert agreement["open_cure_count"] == 2, "OPEN + CURING count; ESCALATED does not"

    get_success_data(api.resolve_default_case(d3["id"], OPS))
    agreement = get_success_data(api.get_agreement(ag_id, OPS))
    assert agreement["open_cure_count"] == 2, (
        "resolving the ESCALATED default must not decrement the counter — it never counted"
    )


def test_open_cure_count_reflects_open_and_curing_only(api):
    """PRD §3.8: "the agreement's `open_cure_count`, which counts only cases in
    `OPEN` or `CURING`; `ESCALATED` cases do not count toward it (they gate
    termination instead), and `RESOLVED` cases never count."

    Design: Difficulty/compensating_invariant/open_cure_count_invariant_under_resolve_cycles
    """
    ctx = setup_active_agreement()
    ag_id = ctx["agreement"]["id"]
    d1 = open_default(ag_id, "PAYMENT")
    d2 = open_default(ag_id, "REPORTING")
    agreement = get_success_data(api.get_agreement(ag_id, OPS))
    assert agreement["open_cure_count"] == 2

    get_success_data(api.resolve_default_case(d1["id"], OPS))
    agreement = get_success_data(api.get_agreement(ag_id, OPS))
    assert agreement["open_cure_count"] == 1

    get_success_data(api.escalate_default_case(d2["id"], OPS))
    agreement = get_success_data(api.get_agreement(ag_id, OPS))
    assert agreement["open_cure_count"] == 0, "ESCALATED drops out of open_cure_count"


def test_resolving_last_open_default_resumes_suspended_agreement(api):
    """PRD §3.8: "Every resolution recomputes `open_cure_count`, and when the
    counter falls to zero while the agreement sits in `SUSPENDED`, the agreement
    resumes on its own — a system-driven `SUSPENDED` → `ACTIVE` hop that
    increments the agreement's `version`."

    Design: Difficulty/transitive_cascade/default_resolve_auto_resumes_suspended_agreement
    """
    ctx = setup_suspended_agreement()
    ag_id = ctx["agreement"]["id"]
    get_success_data(api.resolve_default_case(ctx["default"]["id"], OPS))
    agreement = get_success_data(api.get_agreement(ag_id, OPS))
    assert agreement["open_cure_count"] == 0
    assert agreement["status"] == "ACTIVE"


def test_agreement_stays_suspended_while_any_default_remains_open(api):
    """PRD §3.8: "when the counter falls to zero while the agreement sits in
    `SUSPENDED`, the agreement resumes on its own — a system-driven `SUSPENDED`
    → `ACTIVE` hop that increments the agreement's `version`."
    PRD §3.8: "the agreement's `open_cure_count`, which counts only cases in
    `OPEN` or `CURING`"

    Design: Difficulty/transitive_cascade/default_resolve_auto_resumes_suspended_agreement
    """
    ctx = setup_suspended_agreement()
    ag_id = ctx["agreement"]["id"]
    second = open_default(ag_id, "REPORTING")
    get_success_data(api.resolve_default_case(ctx["default"]["id"], OPS))
    agreement = get_success_data(api.get_agreement(ag_id, OPS))
    assert agreement["open_cure_count"] == 1
    assert agreement["status"] == "SUSPENDED", (
        "one default still OPEN: counter not at zero, no auto-resume"
    )
    # Resolving the remaining default now resumes the agreement.
    get_success_data(api.resolve_default_case(second["id"], OPS))
    agreement = get_success_data(api.get_agreement(ag_id, OPS))
    assert agreement["status"] == "ACTIVE"
