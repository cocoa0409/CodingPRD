"""Termination for cause, de-identification, closure, and brokerage wind-down."""
from test_helpers import (
    validate_error, validate_paginated, get_success_data,
    setup_active_agreement, setup_deidentifying_agreement, setup_closed_agreement,
    open_default, create_agent_payload,
    ApiErrorId, DEIDENTIFICATION_CATEGORIES, TEST_USERS, make_franchisee_admin_headers,
)

OPS = TEST_USERS["franchisor_ops_headers"]


def test_verify_of_last_task_closes_agreement_terminates_brokerage_and_deactivates_agents(api):
    """PRD §3.9: "When the final task is verified and no default case of the
    agreement remains in `OPEN`, `CURING`, or `ESCALATED`, the agreement closes,
    `DEIDENTIFYING` → `CLOSED`, with its `version` incremented."
    PRD §3.9: "if no agreement of the brokerage remains in any non-terminal state
    — nothing left in `DRAFT`, `ACTIVE`, `SUSPENDED`, `TERMINATED`, or
    `DEIDENTIFYING` — the brokerage itself transitions `FRANCHISED` →
    `TERMINATED`, its `version` increments, and every one of its agents still
    `ACTIVE` flips to `INACTIVE` as the final cascade of the lifecycle."

    Design: Difficulty/transitive_cascade/verify_last_task_closes_agreement_terminates_brokerage_deactivates_agents
    """
    ctx = setup_active_agreement()
    ag_id = ctx["agreement"]["id"]
    brokerage_id = ctx["brokerage"]["id"]
    agent = get_success_data(
        api.create_agent(brokerage_id, create_agent_payload(), OPS)
    )
    assert agent["status"] == "ACTIVE"

    default = open_default(ag_id, "BRAND_STANDARDS")
    get_success_data(api.escalate_default_case(default["id"], OPS))
    get_success_data(api.terminate_agreement(ag_id, OPS))
    get_success_data(api.resolve_default_case(default["id"], OPS))

    tasks, _meta = validate_paginated(api.list_deidentification_tasks(ag_id, OPS))
    assert len(tasks) == 5
    admin = make_franchisee_admin_headers(brokerage_id)
    for task in tasks:
        get_success_data(api.complete_deidentification_task(task["id"], admin))
        get_success_data(api.verify_deidentification_task(task["id"], OPS))

    agreement = get_success_data(api.get_agreement(ag_id, OPS))
    assert agreement["status"] == "CLOSED"

    brokerage = get_success_data(api.get_brokerage(brokerage_id, OPS))
    assert brokerage["status"] == "TERMINATED"

    agents, _meta = validate_paginated(api.list_agents(brokerage_id, OPS))
    assert all(a["status"] == "INACTIVE" for a in agents)


def test_agreement_stays_deidentifying_until_final_task_verified(api):
    """PRD §3.9: "The `due_at` of each task is advisory rather than a gate: the
    agreement cannot transition `DEIDENTIFYING` → `CLOSED` until every task is
    `VERIFIED`, regardless of whether the 60-day window has passed, and a
    late-but-verified task still closes the file."

    Design: Difficulty/transitive_cascade/verify_last_task_closes_agreement_terminates_brokerage_deactivates_agents
    """
    ctx = setup_deidentifying_agreement()
    ag_id = ctx["agreement"]["id"]
    brokerage_id = ctx["brokerage"]["id"]
    get_success_data(api.resolve_default_case(ctx["default"]["id"], OPS))

    admin = make_franchisee_admin_headers(brokerage_id)
    for task in ctx["tasks"][:4]:
        get_success_data(api.complete_deidentification_task(task["id"], admin))
        get_success_data(api.verify_deidentification_task(task["id"], OPS))

    agreement = get_success_data(api.get_agreement(ag_id, OPS))
    assert agreement["status"] == "DEIDENTIFYING", (
        "one unverified task must hold the agreement in DEIDENTIFYING"
    )
    brokerage = get_success_data(api.get_brokerage(brokerage_id, OPS))
    assert brokerage["status"] == "FRANCHISED"


def test_termination_spawns_one_pending_task_per_category(api):
    """PRD §3.9: "Each task's `category` is one of the five de-identification
    categories — `SIGNAGE_REMOVAL`, `MARKETING_WITHDRAWAL`, `DATA_PURGE`,
    `DOMAIN_RELEASE`, and `DIRECTORY_REMOVAL` — and every terminated agreement
    spawns exactly one task per `category`."
    PRD §3.8: "the system then creates five `DeidentificationTask` rows, one in
    `PENDING` status for each category, each with `due_at` set to the termination
    timestamp plus 60 days; and the agreement immediately hops `TERMINATED` →
    `DEIDENTIFYING` within the same request once the tasks exist"

    Design: Difficulty/cross_entity_state_dependency/agent_reactivate_gated_by_brokerage_state
    """
    ctx = setup_deidentifying_agreement()
    assert ctx["agreement"]["status"] == "DEIDENTIFYING"
    categories = sorted(t["category"] for t in ctx["tasks"])
    assert categories == sorted(DEIDENTIFICATION_CATEGORIES)
    assert all(t["status"] == "PENDING" for t in ctx["tasks"])


def test_reactivate_agent_of_terminated_brokerage_rejected(api):
    """PRD §3.4: "reactivation back to `ACTIVE` is likewise the owning admin's
    call, but only while the brokerage is `FRANCHISED` — reactivating under a
    `TERMINATED` brokerage fails with the same `ERR_BROKERAGE_TERMINATED`."

    Design: Difficulty/cross_entity_state_dependency/agent_reactivate_gated_by_brokerage_state
    """
    ctx = setup_active_agreement()
    brokerage_id = ctx["brokerage"]["id"]
    agent = get_success_data(
        api.create_agent(brokerage_id, create_agent_payload(), OPS)
    )
    admin = make_franchisee_admin_headers(brokerage_id)

    # Wind the only agreement down to CLOSED so the brokerage terminates and the
    # agent is cascade-deactivated.
    default = open_default(ctx["agreement"]["id"], "PAYMENT")
    get_success_data(api.escalate_default_case(default["id"], OPS))
    get_success_data(api.terminate_agreement(ctx["agreement"]["id"], OPS))
    get_success_data(api.resolve_default_case(default["id"], OPS))
    tasks, _meta = validate_paginated(
        api.list_deidentification_tasks(ctx["agreement"]["id"], OPS)
    )
    for task in tasks:
        get_success_data(api.complete_deidentification_task(task["id"], admin))
        get_success_data(api.verify_deidentification_task(task["id"], OPS))

    brokerage = get_success_data(api.get_brokerage(brokerage_id, OPS))
    assert brokerage["status"] == "TERMINATED"
    agents, _meta = validate_paginated(api.list_agents(brokerage_id, OPS))
    assert agents[0]["status"] == "INACTIVE"

    resp = api.reactivate_agent(agent["id"], admin)
    validate_error(resp, ApiErrorId.ERR_BROKERAGE_TERMINATED)

    agents, _meta = validate_paginated(api.list_agents(brokerage_id, OPS))
    assert agents[0]["status"] == "INACTIVE", "rejected reactivation must not change status"
