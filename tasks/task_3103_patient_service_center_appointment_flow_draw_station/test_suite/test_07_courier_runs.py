"""Courier runs: dispatch/deliver fan-out, count posture, cancel and multiplicity."""
import pytest

from test_helpers import (
    validate_success, validate_error, api_client, INTAKE, TEST_USERS,
    ApiErrorId, make_phlebotomist_headers,
)
from test_helpers.fixtures import (
    setup_windowed_assigned_specimen, setup_eligible_order, new_courier_run,
    new_tube_requirement, get_courier_run, get_specimen, new_center, new_patient,
    new_order, resolve_insurance, set_clock, seed_reference, book, check_in,
    api_client as _ac,
)
from test_helpers.factories import create_specimen_payload


def test_dispatch_and_deliver_move_the_run_and_every_specimen_on_it(api):
    """PRD §3.6: "Dispatching a run happens when the logical clock is exactly
    equal to the run's dispatch instant and at least one specimen is committed.
    The run moves to `DISPATCHED` and every specimen assigned to it moves to
    `IN_TRANSIT`."
    PRD §3.6: "delivery then moves the run to `DELIVERED` and moves every one of
    its in-transit specimens to `RECEIVED`, which is a terminal specimen status."

    Design: Corner/endpoints/dispatch_then_deliver_moves_the_whole_run_and_every_specimen_on_it
    """
    data = setup_windowed_assigned_specimen(dispatch_utc="2026-09-01T18:00:00Z")
    headers = TEST_USERS["lab_liaison_headers"]
    # A second specimen rides the same run.
    second = validate_success(api_client.create_specimen(
        create_specimen_payload(data["order"]["id"], tube_code="EDTA_LAVENDER",
                                volume_ml=4.0, order_of_draw=1),
        make_phlebotomist_headers(data["phlebotomist"]["id"])), 201)
    validate_success(api_client.assign_courier(second["id"], data["courier_run"]["id"],
                                               headers), 200)

    set_clock("2026-09-01T18:00:00Z")
    dispatched = validate_success(
        api_client.dispatch_courier_run(data["courier_run"]["id"], headers), 200)
    assert dispatched["status"] == "DISPATCHED"

    delivered = validate_success(
        api_client.deliver_courier_run(data["courier_run"]["id"], headers), 200)
    assert delivered["status"] == "DELIVERED"

    rows = api_client.list_specimens(
        headers, params={"courier_run_id": data["courier_run"]["id"]}).json()["data"]
    assert len(rows) == 2
    assert all(row["status"] == "RECEIVED" for row in rows)

    run = get_courier_run(data["courier_run"]["id"])
    assert run["committed_specimen_count"] == 2


def test_a_run_without_a_committed_specimen_cannot_be_cancelled_but_an_empty_one_can(api):
    """PRD §3.6: "An empty run — one whose committed count is zero — may be
    cancelled, and cancelling writes `CANCELLED`; a run holding even one
    specimen cannot be cancelled."

    Design: Corner/cross_cutting_complexity_layers/a_courier_run_may_be_cancelled_only_while_it_is_empty
    """
    data = setup_windowed_assigned_specimen(dispatch_utc="2026-09-01T18:00:00Z")
    headers = TEST_USERS["lab_liaison_headers"]
    empty = new_courier_run(data["center"]["id"], "2026-09-01T19:00:00Z")

    response = api_client.cancel_courier_run(data["courier_run"]["id"], headers)
    assert response.status_code >= 400, "an occupied run cannot be cancelled"
    assert get_courier_run(data["courier_run"]["id"])["status"] == "PLANNED"
    assert get_specimen(data["specimen"]["id"])["status"] == "ASSIGNED"

    cancelled = validate_success(api_client.cancel_courier_run(empty["id"], headers), 200)
    assert cancelled["status"] == "CANCELLED"


def test_a_dispatch_instant_already_occupied_by_a_live_run_is_refused(api):
    """PRD §2.9: "Two courier runs of the same center must not share an identical
    dispatch instant while either is still live, and that duplicate is also
    reported as `ERR_SLOT_ALREADY_TAKEN`."
    PRD §2.10: "a server-computed `cutoff_utc` equal to the run's `dispatch_utc`
    minus `COURIER.cutoff_before_dispatch_minutes`"

    Design: Difficulty/resource_temporal_overlap/courier_run_duplicate_dispatch_instant_rejected_on_distinct_resource
    """
    set_clock("2026-09-01T13:00:00Z")
    center = new_center()
    headers = TEST_USERS["lab_liaison_headers"]
    first = new_courier_run(center["id"], "2026-09-01T16:00:00Z")
    assert first["cutoff_utc"] == "2026-09-01T15:45:00.000Z", (
        "the cutoff is fifteen minutes before dispatch"
    )

    response = api_client.create_courier_run({
        "service_center_id": center["id"], "direction": "OUTBOUND",
        "dispatch_utc": "2026-09-01T16:00:00Z",
    }, headers)
    validate_error(response, ApiErrorId.ERR_SLOT_ALREADY_TAKEN.value)

    cancelled = validate_success(api_client.cancel_courier_run(first["id"], headers), 200)
    assert cancelled["status"] == "CANCELLED"
    listed = api_client.list_courier_runs(
        headers, params={"service_center_id": center["id"], "status": "PLANNED"}).json()["data"]
    assert listed == []


def test_dispatching_before_the_dispatch_instant_is_a_state_rejection(api):
    """PRD §3.6: "Dispatching a run happens when the logical clock is exactly
    equal to the run's dispatch instant and at least one specimen is committed."

    Design: Corner/state_machines/courier_dispatch_before_its_dispatch_instant_returns_invalid_state
    """
    data = setup_windowed_assigned_specimen(dispatch_utc="2026-09-01T18:00:00Z")
    headers = TEST_USERS["lab_liaison_headers"]

    set_clock("2026-09-01T17:59:00Z")
    validate_error(api_client.dispatch_courier_run(data["courier_run"]["id"], headers),
                   ApiErrorId.ERR_INVALID_STATE.value)

    run = get_courier_run(data["courier_run"]["id"])
    assert run["status"] == "PLANNED"
    assert run["committed_specimen_count"] == 1
    assert get_specimen(data["specimen"]["id"])["status"] == "ASSIGNED"


def test_the_eligible_read_returns_the_empty_set_sentinel_rather_than_an_error(api):
    """PRD §3.6: "When no such run exists, the selection fails with
    `ERR_NO_ELIGIBLE_COURIER_RUN` (HTTP 422); the published eligible-runs read, by
    contrast, returns an empty set as a declared sentinel rather than an error."

    Design: Difficulty/boundary_precision_check/empty_candidate_set_on_courier_selector_returns_declared_sentinel
    """
    set_clock("2026-09-01T13:00:00Z")
    center = new_center()
    plan_id = api_client.seed_reference(TEST_USERS["supervisor_headers"]).json()["data"]["insurance_plan_id"]
    # The only run dispatches far outside the commit interval for this visit.
    far_run = new_courier_run(center["id"], "2026-09-01T14:00:00Z")
    patient = new_patient()
    order = new_order(center["id"], patient["id"], plan_id)
    order = resolve_insurance(order["id"])
    specimen = validate_success(api_client.create_specimen(
        create_specimen_payload(order["id"]), TEST_USERS["phlebotomist_headers"]), 201)

    headers = TEST_USERS["lab_liaison_headers"]
    response = api_client.list_eligible_courier_runs(headers, specimen_id=specimen["id"])
    assert response.status_code == 200, "the empty candidate set is a declared sentinel"
    assert response.json()["data"] == []

    write = api_client.assign_courier(specimen["id"], far_run["id"], headers)
    validate_error(write, ApiErrorId.ERR_NO_ELIGIBLE_COURIER_RUN.value)

    assert get_specimen(specimen["id"])["status"] == "UNASSIGNED"
    assert get_courier_run(far_run["id"])["committed_specimen_count"] == 0


def test_commit_all_never_commits_a_specimen_whose_deadline_precedes_dispatch(api):
    """PRD §3.6: "The specimens left over stay unassigned and no error is
    surfaced for them; the cap is a silent stop, not a failure."
    PRD §2.10: "the specimen's stability deadline is no later than that same
    `dispatch_utc`"

    Design: Corner/endpoints/bulk_commit_all_assigns_only_what_the_window_admits
    """
    data = setup_windowed_assigned_specimen(dispatch_utc="2026-09-01T18:00:00Z")
    headers = TEST_USERS["lab_liaison_headers"]
    # A short-lived tube collected far in advance cannot survive to a run that
    # dispatches a day later.
    new_tube_requirement("LACTATE", "SODIUM_CITRATE_BLUE", stability_minutes=60,
                         max_urgency_hours=4, order_of_draw=5,
                         is_recollection_eligible=True)
    late_run = new_courier_run(data["center"]["id"], "2026-09-02T07:00:00Z")

    validate_success(api_client.commit_all(late_run["id"], headers), 200)
    assert get_courier_run(late_run["id"])["committed_specimen_count"] == 0, (
        "the out-of-window specimen must simply stay put"
    )
    assert get_specimen(data["specimen"]["id"])["status"] == "ASSIGNED"