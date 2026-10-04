"""Limited-release allocations: waterfall, assignment decisions, gating."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_case_ledger_conserved,
    get_assignment,
    get_success_data,
    make_event,
    make_wholesaler_headers,
    request_allocation,
    setup_awarded_territory,
    setup_locked_event_single_requester,
    setup_suspended_wholesaler,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


@pytest.fixture
def waterfall_event(api):
    """Three tiers (GOLD/SILVER/BRONZE) request 500/400/300 of a 1000-case
    event with default knobs; locked."""
    parties = []
    for name, tier in (("Gold", "GOLD"), ("Silver", "SILVER"),
                       ("Bronze", "BRONZE")):
        _, wholesaler, _ = setup_awarded_territory(
            territory_name=f"Alloc {name}",
            wholesaler_overrides={"tier": tier},
            agreement_overrides={"brand_scope": ["BUD-LTD"]},
        )
        parties.append(wholesaler)
    event = make_event(brand_code="BUD-LTD", total_qty_cases=1000)
    for wholesaler, qty in zip(parties, (500, 400, 300)):
        resp = request_allocation(event["id"], wholesaler["id"], qty)
        if resp.status_code != 201:
            raise AssertionError(f"Setup failed at request: {resp.text[:300]}")
    locked = api.lock_event(event["id"], ADMIN)
    if locked.status_code != 200:
        raise AssertionError(f"Setup failed at lock: {locked.text[:300]}")
    return {"event": get_success_data(locked),
            "gold": parties[0], "silver": parties[1], "bronze": parties[2]}


class TestWaterfallAssignment:
    def test_waterfall_assignments_per_tier_and_cap(self, api, waterfall_event):
        """PRD §3.5: "Phase one, the guarantee phase, assigns each request the
        smallest of three quantities: the number of cases it requested, the
        event's `min_guarantee_cases`, and its cap."
        PRD §3.5: "each request that still has capacity is given a weight equal
        to its remaining capacity multiplied by its wholesaler's tier
        multiplier — 1.2 for `GOLD`, 1.0 for `SILVER`, 0.8 for `BRONZE`"

        Design: Difficulty/combinatorial_formula/allocation_waterfall_tier_cap_iteration
        """
        event = waterfall_event["event"]
        assert event["status"] == "LOCKED"

        gold = get_assignment(event, waterfall_event["gold"]["id"])
        silver = get_assignment(event, waterfall_event["silver"]["id"])
        bronze = get_assignment(event, waterfall_event["bronze"]["id"])

        assert gold["assigned_qty"] == 400, "phase-1 100 + phase-2 capped at 400"
        assert silver["assigned_qty"] == 360, "256 proportional + 4 remainder"
        assert bronze["assigned_qty"] == 240, "136 proportional + 4 remainder"
        assert gold["tier_snapshot"] == "GOLD"
        assert silver["tier_snapshot"] == "SILVER"
        assert bronze["tier_snapshot"] == "BRONZE"
        for a in (gold, silver, bronze):
            assert a["status"] == "PENDING"
        assert 400 + 360 + 240 == event["total_qty_cases"] == 1000

    def test_waterfall_freezes_ledger_at_lock(self, api, waterfall_event):
        """PRD §3.5: "The event's `unassigned_remainder` — `total_qty_cases`
        minus the sum of all assigned cases — and its `pending_qty` — the sum
        of assigned cases, equal to the whole assigned volume at this moment —
        are computed and frozen at lock, while `committed_qty` and
        `released_qty` remain at zero."

        Design: Difficulty/combinatorial_formula/allocation_waterfall_tier_cap_iteration
        """
        event = waterfall_event["event"]
        assert event["unassigned_remainder"] == 0
        assert event["pending_qty"] == 1000
        assert event["committed_qty"] == 0
        assert event["released_qty"] == 0
        assert_case_ledger_conserved(event)


@pytest.fixture
def ledger_snapshots(api):
    """Event total 500; GOLD wholesaler requests 300; locked; then CONFIRM,
    then RELEASE. Returns the event snapshot after each step."""
    wholesaler, _, after_lock = setup_locked_event_single_requester(
        total_qty_cases=500, requested_qty_cases=300,
        territory_name="Ledger Territory", tier="GOLD")
    confirm = api.assignment_decision(
        after_lock["id"], wholesaler["id"], {"decision": "CONFIRM"},
        make_wholesaler_headers(wholesaler["id"]))
    if confirm.status_code != 200:
        raise AssertionError(f"Setup failed at CONFIRM: {confirm.text[:300]}")
    after_confirm = get_success_data(confirm)
    release = api.assignment_decision(
        after_lock["id"], wholesaler["id"], {"decision": "RELEASE"},
        make_wholesaler_headers(wholesaler["id"]))
    if release.status_code != 200:
        raise AssertionError(f"Setup failed at RELEASE: {release.text[:300]}")
    return {"wholesaler": wholesaler, "after_lock": after_lock,
            "after_confirm": after_confirm,
            "after_release": get_success_data(release)}


class TestConfirmReleaseConservation:
    def test_confirm_conserves_case_ledger(self, api, ledger_snapshots):
        """PRD §3.5: "`CONFIRM` moves a `PENDING` assignment to `CONFIRMED`:
        `pending_qty` decreases by the assignment's `assigned_qty`, and
        `committed_qty` increases by the same amount."
        PRD §3.5: "A conservation invariant holds after every decision:
        `committed_qty`, `pending_qty`, `released_qty`, and
        `unassigned_remainder` always sum to `total_qty_cases`."

        Design: Difficulty/compensating_invariant/confirm_release_conserves_case_ledger
        """
        snap = ledger_snapshots
        lock = snap["after_lock"]
        assert lock["committed_qty"] == 0
        assert lock["pending_qty"] == 200
        assert lock["released_qty"] == 0
        assert lock["unassigned_remainder"] == 300
        assert_case_ledger_conserved(lock)

        confirmed = snap["after_confirm"]
        assignment = get_assignment(confirmed, snap["wholesaler"]["id"])
        assert assignment["status"] == "CONFIRMED"
        assert confirmed["committed_qty"] == 200
        assert confirmed["pending_qty"] == 0
        assert_case_ledger_conserved(confirmed)
        assert confirmed["status"] == "CLOSED", (
            "pending_qty reached 0 in the same request"
        )

    def test_release_after_confirm_restores_baseline(self, api, ledger_snapshots):
        """PRD §3.5: "`RELEASE` moves an assignment from `PENDING` or
        `CONFIRMED` to `RELEASED`: `released_qty` increases by the assigned
        quantity, and `pending_qty` or `committed_qty` decreases accordingly."
        PRD §3.5: "Both decisions remain legal while the event is `LOCKED` or
        `CLOSED`."

        Design: Difficulty/compensating_invariant/confirm_release_conserves_case_ledger
        """
        snap = ledger_snapshots
        released = snap["after_release"]
        assignment = get_assignment(released, snap["wholesaler"]["id"])
        assert assignment["status"] == "RELEASED"
        assert assignment["assigned_qty"] == 200, "assigned_qty is unchanged"
        assert released["committed_qty"] == 0
        assert released["released_qty"] == 200
        assert released["pending_qty"] == 0
        assert released["unassigned_remainder"] == 300
        assert released["total_qty_cases"] == 500
        assert_case_ledger_conserved(released)


@pytest.fixture
def suspended_request_gate(api):
    """A wholesaler suspended by three CRITICAL_FAIL audits, plus an OPEN
    BUD-LTD event created after the suspension."""
    wholesaler, _, _ = setup_suspended_wholesaler(
        territory_name="Gated Territory")
    event = make_event(brand_code="BUD-LTD", total_qty_cases=200)
    return {"wholesaler": wholesaler, "event": event}


class TestAllocationRequestGatedOnWholesalerStatus:
    def test_suspended_wholesaler_request_rejected(
        self, api, suspended_request_gate
    ):
        """PRD §3.6: "while `SUSPENDED` its allocation requests, its transfer
        applications as seller, its appointment to new agreements, and its
        promotion opt-ins are all rejected with `ERR_WHOLESALER_NOT_ELIGIBLE`."

        Design: Difficulty/cross_entity_state_dependency/allocation_request_gated_on_wholesaler_status
        """
        env = suspended_request_gate
        wholesaler = validate_success(
            api.get_wholesaler(env["wholesaler"]["id"], ADMIN))
        assert wholesaler["status"] == "SUSPENDED"

        resp = request_allocation(env["event"]["id"], env["wholesaler"]["id"], 50)
        validate_error(resp, ApiErrorId.ERR_WHOLESALER_NOT_ELIGIBLE)

    def test_rejected_request_leaves_no_residue(self, api, suspended_request_gate):
        """PRD §3.5: "An admitted request is appended to the event with its
        `requested_qty_cases` and a logical-clock `created_at`."
        PRD §3.6: "while `SUSPENDED` its allocation requests, its transfer
        applications as seller, its appointment to new agreements, and its
        promotion opt-ins are all rejected with `ERR_WHOLESALER_NOT_ELIGIBLE`."

        Design: Difficulty/cross_entity_state_dependency/allocation_request_gated_on_wholesaler_status
        """
        env = suspended_request_gate
        resp = request_allocation(env["event"]["id"], env["wholesaler"]["id"], 50)
        validate_error(resp, ApiErrorId.ERR_WHOLESALER_NOT_ELIGIBLE)

        event = validate_success(api.get_allocation_event(env["event"]["id"], ADMIN))
        assert event["requests"] == [], "the rejected request left no residue"
        assert event["status"] == "OPEN"


class TestRequestValidations:
    def test_duplicate_allocation_request_rejected(self, api, admin_headers):
        """PRD §3.5: "Each wholesaler files at most one request per event: a
        second request is rejected with `ERR_DUPLICATE_REQUEST`."

        Design: Corner/validations/duplicate_allocation_request_rejected
        """
        _, wholesaler, _ = setup_awarded_territory(
            territory_name="Req Territory", wholesaler_overrides={"tier": "GOLD"},
            agreement_overrides={"brand_scope": ["BUD-LTD"]})
        event = make_event(brand_code="BUD-LTD", total_qty_cases=400)
        first = request_allocation(event["id"], wholesaler["id"], 50)
        validate_success(first, 201)

        resp = request_allocation(event["id"], wholesaler["id"], 75)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REQUEST)

        current = validate_success(api.get_allocation_event(event["id"], ADMIN))
        assert len(current["requests"]) == 1
        assert current["requests"][0]["requested_qty_cases"] == 50
        assert current["status"] == "OPEN"

    def test_allocation_request_outside_brand_scope_rejected(self, api):
        """PRD §3.5: "the event's brand must appear in the `brand_scope` of one
        of the requester's `ACTIVE` agreements, else
        `ERR_BRAND_SCOPE_MISMATCH`."

        Design: Corner/validations/allocation_request_outside_brand_scope_rejected
        """
        _, wholesaler, _ = setup_awarded_territory(
            territory_name="Scope Territory",
            wholesaler_overrides={"tier": "GOLD"},
            agreement_overrides={"brand_scope": ["BUD"]})
        event = make_event(brand_code="MIC", total_qty_cases=400)

        resp = request_allocation(event["id"], wholesaler["id"], 50)
        validate_error(resp, ApiErrorId.ERR_BRAND_SCOPE_MISMATCH)

        current = validate_success(api.get_allocation_event(event["id"], ADMIN))
        assert current["requests"] == []


class TestEventClosure:
    def test_event_closes_when_last_pending_assignment_confirmed(self, api):
        """PRD §3.5: "When a decision leaves no `PENDING` assignments —
        `pending_qty` has reached zero — the event moves `LOCKED` → `CLOSED`."

        Design: Corner/state_machines/event_closes_when_last_pending_assignment_confirmed
        """
        wholesaler, _, locked = setup_locked_event_single_requester(
            total_qty_cases=100, requested_qty_cases=50,
            territory_name="Close Territory", tier="GOLD")
        assignment = get_assignment(locked, wholesaler["id"])
        assert assignment["assigned_qty"] == 40
        assert locked["pending_qty"] == 40
        assert locked["unassigned_remainder"] == 60

        resp = api.assignment_decision(
            locked["id"], wholesaler["id"], {"decision": "CONFIRM"},
            make_wholesaler_headers(wholesaler["id"]))
        closed = validate_success(resp, 200)
        assert closed["status"] == "CLOSED"
        assert closed["committed_qty"] == 40
        assert closed["pending_qty"] == 0
        assert closed["unassigned_remainder"] == 60
        final_assignment = get_assignment(closed, wholesaler["id"])
        assert final_assignment["status"] == "CONFIRMED"
        assert final_assignment["assigned_qty"] == 40
