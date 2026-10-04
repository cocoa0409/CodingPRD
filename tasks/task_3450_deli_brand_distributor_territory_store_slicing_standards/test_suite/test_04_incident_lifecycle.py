"""Food-safety incidents: cyclic lifecycle, quarantine cascade, scope (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_incident,
    create_plant,
    create_product,
    create_production_run_payload,
    create_delivery,
    get_lot_for_run,
    get_order,
    get_success_data,
    make_plant_scheduler_headers,
    setup_confirmed_delivery,
    setup_delivery_chain,
    transition_incident,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["brand_admin_headers"]


def _setup_incident_at_contained():
    """Plant + incident walked REPORTED -> TRIAGED -> CONFIRMED_RECALL -> CONTAINED
    with no implicated runs. Returns (plant, incident_id)."""
    plant = create_plant()
    incident = create_incident(plant, affected_run_ids=[])
    transition_incident(incident["id"], "TRIAGED")
    transition_incident(incident["id"], "CONFIRMED_RECALL")
    transition_incident(incident["id"], "CONTAINED")
    return plant, incident["id"]


def test_contained_incident_reopens_to_triage(api):
    """PRD §3.8: "And a contained incident may reopen on new evidence, `CONTAINED` →
    `TRIAGED`; the loop back through `CONFIRMED_RECALL` may repeat any number of
    times, and every cascade is idempotent on entities already in the target state,
    so a repeated loop never double-applies an effect."

    The reopen succeeds, the incident re-enters CONFIRMED_RECALL a second time, and
    the already-SHUTDOWN plant stays SHUTDOWN (idempotent cascade).

    Design: Difficulty/non_linear_state_machine/incident_contained_reopen_cycle
    """
    plant, incident_id = _setup_incident_at_contained()
    reopened = transition_incident(incident_id, "TRIAGED")
    assert reopened["status"] == "TRIAGED", (
        "the CONTAINED -> TRIAGED reopen on new evidence must succeed"
    )
    recalled = transition_incident(incident_id, "CONFIRMED_RECALL")
    assert recalled["status"] == "CONFIRMED_RECALL", "cycle re-entry must succeed"
    plant_now = get_success_data(api.get_plant(plant["id"], ADMIN))
    assert plant_now["status"] == "SHUTDOWN", (
        "second confirm-recall is idempotent: the plant was already SHUTDOWN"
    )


def test_reopened_incident_resolves_false_alarm_and_reopens_plant(api):
    """PRD §3.8: "A false alarm exonerates: every `QUARANTINED` lot returns to
    `AVAILABLE`; those incident-suspended authorizations return to `AUTHORIZED` with
    `suspension_source` cleared to `NONE`; every `SUSPENDED` promo program of an
    affected product returns to `AUTHORIZED`; and the plant returns to `ACTIVE`." and
    "From `RESOLVED`, a final transition moves the incident to the terminal `CLOSED`."

    After one full reopen loop, RESOLVED with FALSE_ALARM returns the plant to
    ACTIVE, and the incident closes recording the FALSE_ALARM outcome.

    Design: Difficulty/non_linear_state_machine/incident_contained_reopen_cycle
    """
    plant, incident_id = _setup_incident_at_contained()
    transition_incident(incident_id, "TRIAGED")
    transition_incident(incident_id, "CONFIRMED_RECALL")
    transition_incident(incident_id, "CONTAINED")
    resolved = transition_incident(incident_id, "RESOLVED", resolution_outcome="FALSE_ALARM")
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution_outcome"] == "FALSE_ALARM"
    plant_now = get_success_data(api.get_plant(plant["id"], ADMIN))
    assert plant_now["status"] == "ACTIVE", "false-alarm resolution reopens the plant"
    closed = transition_incident(incident_id, "CLOSED")
    assert closed["status"] == "CLOSED"
    assert closed["resolution_outcome"] == "FALSE_ALARM"


def test_confirm_recall_quarantines_lot_and_rejects_pending_delivery(api):
    """PRD §3.8: "Every lot whose run appears in `affected_run_ids` and whose
    `status` is `AVAILABLE` moves to `QUARANTINED`. That quarantine propagates in
    turn: every `PENDING` delivery whose lines contain a newly quarantined lot moves
    to `REJECTED`, its goods returned from delivered to allocated per §3.5, and its
    order's `fulfillment_status` becomes `REJECTED`."

    Link 1 (lot quarantine) is asserted together with link 2 it causes (the pending
    delivery's rejection), a depth-2 chain from the confirm-recall trigger.

    Design: Difficulty/transitive_cascade/incident_quarantine_rejects_pending_delivery
    """
    chain = setup_delivery_chain(qty=10)
    delivery = create_delivery(chain, qty=5)
    assert delivery["status"] == "PENDING"
    incident = create_incident(
        chain["plant"], affected_run_ids=[chain["run"]["id"]],
        title="Listeria in run", severity="CRITICAL",
    )
    transition_incident(incident["id"], "TRIAGED")
    transition_incident(incident["id"], "CONFIRMED_RECALL")

    lot = get_lot_for_run(chain["run"]["id"])
    assert lot["status"] == "QUARANTINED", "link 1: affected run's lot quarantined"
    delivery_now = get_success_data(api.get_delivery(delivery["id"], ADMIN))
    assert delivery_now["status"] == "REJECTED", (
        "link 2: the PENDING delivery containing the quarantined lot is rejected"
    )
    order_now = get_order(chain["order"]["id"])
    assert order_now["fulfillment_status"] == "REJECTED"


def test_quarantine_compensation_restores_allocated_pool(api):
    """PRD §3.8: "Rejected deliveries are excluded, because their goods returned to
    the pool." and PRD §3.5: "the same `RetailManager` moves `PENDING` → `REJECTED`,
    every line's units return from the lot's `delivered_units` to its
    `allocated_units` — goods back into the allocated pool".

    The five delivered units are compensated back into the allocated pool
    (10 allocated / 0 delivered), and with the only delivery now REJECTED the
    incident's live scope projection reports zero affected accounts.

    Design: Difficulty/transitive_cascade/incident_quarantine_rejects_pending_delivery
    """
    chain = setup_delivery_chain(qty=10)
    create_delivery(chain, qty=5)
    incident = create_incident(
        chain["plant"], affected_run_ids=[chain["run"]["id"]],
        title="Listeria in run", severity="CRITICAL",
    )
    transition_incident(incident["id"], "TRIAGED")
    transition_incident(incident["id"], "CONFIRMED_RECALL")

    lot = get_lot_for_run(chain["run"]["id"])
    assert lot["allocated_units"] == 10 and lot["delivered_units"] == 0, (
        f"delivered 5 must return to the allocated pool: got "
        f"{lot['allocated_units']}/{lot['delivered_units']}"
    )
    incident_now = get_success_data(api.get_incident(incident["id"], ADMIN))
    assert incident_now["affected_account_count"] == 0, (
        "rejected deliveries drop out of the scope projection"
    )


def test_closed_incident_rejects_further_transitions(api):
    """PRD §3.8: "An incident that proves groundless during triage may close early,
    `TRIAGED` → `CLOSED`, recording `resolution_outcome` as `FALSE_ALARM`." and
    PRD §2.8: "an entity already in a terminal state (`TERMINATED`, `REJECTED`,
    `CLOSED`, `SETTLED`, `RECALLED`, `EXHAUSTED`, `CONFIRMED`, `DELIVERED`,
    `PULLED_ON_TIME`, `PULLED_LATE`, `FORCE_PULLED`, `DECOMMISSIONED`, `EXPIRED`,
    `REVOKED`) rejects every further transition with `ERR_ALREADY_TERMINAL`."

    Design: Corner/state_machines/closed_incident_rejects_all_transitions
    """
    plant = create_plant()
    incident = create_incident(plant, title="Spoilage report", severity="LOW")
    transition_incident(incident["id"], "TRIAGED")
    closed = transition_incident(incident["id"], "CLOSED")
    assert closed["status"] == "CLOSED"
    resp = api.transition_incident(incident["id"], "TRIAGED", TEST_USERS["safety_officer_headers"])
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


def test_plant_shutdown_blocks_new_run_scheduling(api):
    """PRD §3.4: "No run may be scheduled at a plant in `SHUTDOWN`; the attempt fails
    with `ERR_INCIDENT_ACTIVE`." and PRD §3.8: "The originating plant's `status`
    becomes `SHUTDOWN`, which immediately blocks new run scheduling and run
    completion there with `ERR_INCIDENT_ACTIVE`".

    Design: Corner/validations/run_create_blocked_while_plant_shutdown
    """
    plant = create_plant()
    product = create_product(code="P1", name="Item")
    incident = create_incident(plant, title="Salmonella", severity="CRITICAL")
    transition_incident(incident["id"], "TRIAGED")
    transition_incident(incident["id"], "CONFIRMED_RECALL")
    plant_now = get_success_data(api.get_plant(plant["id"], ADMIN))
    assert plant_now["status"] == "SHUTDOWN"
    resp = api.create_production_run(
        create_production_run_payload(
            plant["id"], product["id"],
            window_start="2026-09-02T06:00:00Z", window_end="2026-09-02T12:00:00Z",
            capacity_units=100, planned_units=50,
        ),
        make_plant_scheduler_headers(plant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INCIDENT_ACTIVE)


def test_incident_scope_counts_confirmed_delivery_accounts(api):
    """PRD §3.8: "Every read of an incident reports a live `affected_account_count`:
    replaying the delivery log, the system collects the lots whose runs appear in
    `affected_run_ids`, finds the distinct accounts on deliveries in `PENDING` or
    `CONFIRMED` whose lines reference any of those lots, and counts them."

    One CONFIRMED delivery carrying the affected run's lot projects exactly one
    account into the incident's scope.

    Design: Corner/calculations/incident_scope_counts_confirmed_delivery_accounts
    """
    chain = setup_confirmed_delivery(qty=10)
    incident = create_incident(
        chain["plant"], affected_run_ids=[chain["run"]["id"]],
        title="Foreign material", severity="HIGH",
    )
    incident_now = get_success_data(api.get_incident(incident["id"], ADMIN))
    assert incident_now["affected_account_count"] == 1, (
        f"the CONFIRMED delivery to the account projects into scope: "
        f"expected 1, got {incident_now['affected_account_count']}"
    )
