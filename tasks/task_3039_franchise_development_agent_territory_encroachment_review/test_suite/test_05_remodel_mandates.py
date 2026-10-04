"""Remodel mandates: closure windows, buffer rule, downtime charges, lazy
OVERDUE, DA_LOAN financing gate (PRD §3.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_franchisee,
    create_mandate,
    create_store,
    get_remodel_mandate,
    get_store,
    make_development_agent_headers,
    make_franchisee_headers,
    schedule_inspection,
    record_findings,
    finalize_inspection,
    set_clock,
    setup_agent_under_review,
    setup_assigned_territory,
    setup_scheduled_mandate,
    setup_territory_with_stores,
    validate_error,
    validate_success,
)


def test_remodel_closure_half_open_buffer_conflict(api):
    """PRD §3.5: "The proposed half-open closure window `closure_start` to
    `closure_end` (end exclusive) must not intersect any other `SCHEDULED` or
    `IN_PROGRESS` closure window of the same store — otherwise
    `ERR_CLOSURE_WINDOW_OVERLAP`. And the new `closure_start` must fall at
    least seven days after every prior `closure_end` of the same store ...
    otherwise `ERR_CLOSURE_BUFFER_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/remodel_closure_half_open_buffer_conflict
    """
    ctx = setup_scheduled_mandate(closure_start="2026-10-01T00:00:00Z",
                                  closure_end="2026-10-15T00:00:00Z")
    m2 = create_mandate(ctx["store"]["id"], estimated_cost_cents=3_000_000)
    m3 = create_mandate(ctx["store"]["id"], estimated_cost_cents=3_000_000)
    da_headers = make_development_agent_headers(ctx["agent"]["id"])
    # Starting exactly at the prior closure_end: no half-open overlap, but the
    # gap is 0 days, short of the 7-day buffer.
    resp = api.schedule_remodel_mandate(
        m2["id"], {"closure_start": "2026-10-15T00:00:00Z",
                   "closure_end": "2026-10-20T00:00:00Z"}, da_headers)
    error = validate_error(resp, ApiErrorId.ERR_CLOSURE_BUFFER_VIOLATION, 422)
    assert error["error_id"] != ApiErrorId.ERR_CLOSURE_WINDOW_OVERLAP


def test_remodel_schedule_at_exactly_end_plus_seven_days_succeeds(api):
    """PRD §3.5: "the new `closure_start` must fall at least seven days after
    every prior `closure_end` of the same store, giving the store a recovery
    buffer between closures" and "A successful schedule records the window,
    computes `downtime_days` as the whole days in the half-open interval, and
    moves the mandate to `SCHEDULED`."

    Design: Difficulty/resource_temporal_overlap/remodel_closure_half_open_buffer_conflict
    """
    ctx = setup_scheduled_mandate(closure_start="2026-10-01T00:00:00Z",
                                  closure_end="2026-10-15T00:00:00Z")
    m3 = create_mandate(ctx["store"]["id"], estimated_cost_cents=3_000_000)
    da_headers = make_development_agent_headers(ctx["agent"]["id"])
    resp = api.schedule_remodel_mandate(
        m3["id"], {"closure_start": "2026-10-22T00:00:00Z",
                   "closure_end": "2026-10-25T00:00:00Z"}, da_headers)
    scheduled = validate_success(resp, 200)
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["downtime_days"] == 3


def test_closure_window_strict_intersection_returns_overlap(api):
    """PRD §3.5: "The proposed half-open closure window `closure_start` to
    `closure_end` (end exclusive) must not intersect any other `SCHEDULED` or
    `IN_PROGRESS` closure window of the same store — otherwise
    `ERR_CLOSURE_WINDOW_OVERLAP`."

    Design: Corner/errors/closure_window_strict_intersection_returns_overlap
    """
    ctx = setup_scheduled_mandate(closure_start="2026-10-01T00:00:00Z",
                                  closure_end="2026-10-15T00:00:00Z")
    m2 = create_mandate(ctx["store"]["id"], estimated_cost_cents=3_000_000)
    da_headers = make_development_agent_headers(ctx["agent"]["id"])
    resp = api.schedule_remodel_mandate(
        m2["id"], {"closure_start": "2026-10-10T00:00:00Z",
                   "closure_end": "2026-10-30T00:00:00Z"}, da_headers)
    error = validate_error(resp, ApiErrorId.ERR_CLOSURE_WINDOW_OVERLAP, 422)
    assert error["error_id"] != ApiErrorId.ERR_CLOSURE_BUFFER_VIOLATION
    still = get_remodel_mandate(m2["id"])
    assert still["status"] == "ISSUED"


def test_remodel_downtime_charge_at_allowance_boundary(api):
    """PRD §3.5: "Days beyond the allowance are charged at 150,000 cents each,
    so `downtime_charge_cents` is the overage days multiplied by 150,000; a
    downtime exactly equal to the allowance is within allowance and charges
    zero." and "twenty-one days for `SELF_FINANCED`"

    Design: Corner/calculations/remodel_downtime_charge_at_allowance_boundary
    """
    ctx = setup_assigned_territory()
    owner1 = create_franchisee()
    s1 = create_store(ctx["territory"]["id"], owner1["id"])
    owner2 = create_franchisee()
    s2 = create_store(ctx["territory"]["id"], owner2["id"])
    m1 = create_mandate(s1["id"])
    m1 = schedule_via(api, m1, ctx, "2026-10-01T00:00:00Z", "2026-10-22T00:00:00Z")  # 21 days
    m2 = create_mandate(s2["id"])
    m2 = schedule_via(api, m2, ctx, "2026-10-01T00:00:00Z", "2026-10-25T00:00:00Z")  # 24 days
    set_clock("2026-10-05T00:00:00Z")
    validate_success(api.begin_remodel_mandate(m1["id"], make_franchisee_headers(owner1["id"])), 200)
    validate_success(api.begin_remodel_mandate(m2["id"], make_franchisee_headers(owner2["id"])), 200)
    done1 = validate_success(
        api.complete_remodel_mandate(m1["id"], make_franchisee_headers(owner1["id"])), 200)
    done2 = validate_success(
        api.complete_remodel_mandate(m2["id"], make_franchisee_headers(owner2["id"])), 200)
    assert done1["downtime_days"] == 21
    assert done1["downtime_charge_cents"] == 0
    assert done2["downtime_days"] == 24
    assert done2["downtime_charge_cents"] == 450_000  # 3 overage days x 150,000
    assert get_store(s1["id"])["status"] == "OPEN"
    assert get_store(s2["id"])["status"] == "OPEN"


def schedule_via(api, mandate, ctx, closure_start, closure_end):
    return validate_success(
        api.schedule_remodel_mandate(
            mandate["id"],
            {"closure_start": closure_start, "closure_end": closure_end},
            make_development_agent_headers(ctx["agent"]["id"]),
        ), 200)


def test_remodel_begin_flips_store_to_closed_for_remodel(api):
    """PRD §3.5: "Inside the closure window — the logical clock at or after
    `closure_start` and before `closure_end` — the store's owning franchisee
    begins the remodel, moving the mandate `SCHEDULED → IN_PROGRESS` and the
    store `OPEN → CLOSED_FOR_REMODEL`, incrementing the store's `version` by
    1."

    Design: Corner/state_machines/remodel_begin_flips_store_to_closed_for_remodel
    """
    ctx = setup_scheduled_mandate(closure_start="2026-10-01T00:00:00Z",
                                  closure_end="2026-10-15T00:00:00Z")
    set_clock("2026-10-05T00:00:00Z")
    begun = validate_success(
        api.begin_remodel_mandate(ctx["mandate"]["id"],
                                  make_franchisee_headers(ctx["owner"]["id"])), 200)
    assert begun["status"] == "IN_PROGRESS"
    store = get_store(ctx["store"]["id"])
    assert store["status"] == "CLOSED_FOR_REMODEL"


def test_mandate_lazy_overdue_transition_on_read(api, franchisor_ops_headers):
    """PRD §2.6: "a RemodelMandate still in `ISSUED` or `SCHEDULED` whose
    `due_by` has passed reads as `OVERDUE`."
    PRD §3.5: "An `OVERDUE` mandate may be rescheduled under exactly the same
    window and buffer rules, replacing the closure window."

    Design: Corner/cross_cutting_layers/mandate_lazy_overdue_transition_on_read
    """
    ctx = setup_assigned_territory()
    owner = create_franchisee()
    store = create_store(ctx["territory"]["id"], owner["id"])
    mandate = create_mandate(store["id"], due_by="2026-12-31T00:00:00Z")
    first = validate_success(api.get_remodel_mandate(mandate["id"], franchisor_ops_headers), 200)
    assert first["status"] == "ISSUED"
    set_clock("2026-12-31T00:00:00Z")
    second = validate_success(api.get_remodel_mandate(mandate["id"], franchisor_ops_headers), 200)
    assert second["status"] == "OVERDUE"
    rescheduled = validate_success(
        api.schedule_remodel_mandate(
            mandate["id"],
            {"closure_start": "2027-01-05T00:00:00Z", "closure_end": "2027-01-10T00:00:00Z"},
            make_development_agent_headers(ctx["agent"]["id"]),
        ), 200)
    assert rescheduled["status"] == "SCHEDULED"


def test_store_termination_waives_open_mandates(api, franchisor_ops_headers):
    """PRD §3.5: "when a store is terminated, every one of its mandates in
    those three statuses is waived automatically. `COMPLETED` and `WAIVED` are
    terminal."
    PRD §3.6: "A store in `TERMINATION_PENDING` is terminated by
    `FranchisorOps`, which recomputes the territory's `open_store_count`,
    waives the store's open mandates (§3.5)"

    Design: Corner/cross_cutting_layers/store_termination_waives_open_mandates
    """
    ctx = setup_scheduled_mandate(closure_start="2026-09-20T00:00:00Z",
                                  closure_end="2026-09-25T00:00:00Z")
    set_clock("2026-09-22T00:00:00Z")
    owner_headers = make_franchisee_headers(ctx["owner"]["id"])
    validate_success(api.begin_remodel_mandate(ctx["mandate"]["id"], owner_headers), 200)
    m1 = validate_success(api.complete_remodel_mandate(ctx["mandate"]["id"], owner_headers), 200)
    assert m1["status"] == "COMPLETED"
    m2 = create_mandate(ctx["store"]["id"], due_by="2027-06-30T00:00:00Z",
                        estimated_cost_cents=3_000_000)
    # Drive the store to TERMINATION_PENDING with a FAIL_CRITICAL inspection.
    insp = schedule_inspection(ctx["store"]["id"], inspector_ref="insp-1",
                               scheduled_on="2026-10-01T00:00:00Z")
    record_findings(insp["id"], "insp-1", food=50.0, cleanliness=50.0,
                    operations=50.0, critical_violations=3)
    finalize_inspection(insp["id"])
    terminated = validate_success(api.terminate_store(ctx["store"]["id"], franchisor_ops_headers), 200)
    assert terminated["status"] == "TERMINATED"
    waived = get_remodel_mandate(m2["id"])
    assert waived["status"] == "WAIVED"
    untouched = get_remodel_mandate(m1["id"])
    assert untouched["status"] == "COMPLETED"


def test_da_loan_financing_requires_active_agent(api, franchisor_ops_headers):
    """PRD §3.5: "Choosing `DA_LOAN` financing requires the store's territory's
    assigned agent to be `ACTIVE` — otherwise the create fails with
    `ERR_AGENT_NOT_ACTIVE`."

    Design: Corner/calculations/da_loan_financing_requires_active_agent
    """
    ctx = setup_agent_under_review()  # one strike -> UNDER_REVIEW
    owner1 = create_franchisee()
    s1 = create_store(ctx["territory"]["id"], owner1["id"])
    owner2 = create_franchisee()
    s2 = create_store(ctx["territory"]["id"], owner2["id"])
    from test_helpers.factories import create_remodel_mandate_payload
    resp = api.create_remodel_mandate(
        create_remodel_mandate_payload(s1["id"], financing_option="DA_LOAN"),
        franchisor_ops_headers,
    )
    validate_error(resp, ApiErrorId.ERR_AGENT_NOT_ACTIVE, 422)
    ok = api.create_remodel_mandate(
        create_remodel_mandate_payload(s2["id"], financing_option="SELF_FINANCED"),
        franchisor_ops_headers,
    )
    data = validate_success(ok, 201)
    assert data["status"] == "ISSUED"
