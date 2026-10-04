"""Temporal intervals: half-open fine-schedule adjacency and the consolidation
freeze window around effective_at."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_association, create_member, create_fine_schedule, set_clock,
    create_citation,
    TEST_USERS, api_client,
)

STAFF = TEST_USERS["staff_headers"]


def test_fine_schedule_half_open_adjacency(api):
    """PRD §3.5: "Rows for the same association and `rule_code` must never
    overlap under half-open semantics — a row applies to citations assessed at
    or after `effective_from` and strictly before `effective_to`, so a citation
    assessed exactly at one row's `effective_to` belongs to the next row, and
    adjacent rows (the second row's `effective_from` equal to the first row's
    `effective_to`) neither overlap nor gap. An overlapping submission is
    rejected with `ERR_SCHEDULE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/fine_schedule_half_open_adjacency
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="TO1")
    member = create_member(assoc["id"], member_nr="MB", full_name="Broker")
    s1 = create_fine_schedule(assoc["id"], rule_code="INACCURACY",
                              fine_amount_cents=30000,
                              effective_from="2026-01-01T00:00:00Z",
                              effective_to="2026-10-01T00:00:00Z")
    # Adjacent row: effective_from == S1.effective_to is legal.
    s2 = validate_success(api.create_fine_schedule(
        assoc["id"],
        {"rule_code": "INACCURACY", "fine_amount_cents": 45000,
         "effective_from": "2026-10-01T00:00:00Z"},
        STAFF), expected_status=201)
    assert s2["id"]
    # One second before S1.effective_to overlaps -> rejected.
    resp = api.create_fine_schedule(
        assoc["id"],
        {"rule_code": "INACCURACY", "fine_amount_cents": 99000,
         "effective_from": "2026-09-30T23:59:59Z"},
        STAFF)
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_OVERLAP)
    # Citation assessed exactly at the shared boundary resolves to S2's amount.
    set_clock("2026-10-01T00:00:00Z")
    cit = create_citation(assoc["id"], member["id"], rule_code="INACCURACY")
    assert cit["fine_amount_cents"] == 45000, \
        "boundary instant belongs to the next row under half-open semantics"


def test_fine_schedule_boundary_citation_before_uses_prior_row(api):
    """PRD §3.5: "a row applies to citations assessed at or after
    `effective_from` and strictly before `effective_to`".

    Design: Difficulty/resource_temporal_overlap/fine_schedule_half_open_adjacency
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="TO1B")
    member = create_member(assoc["id"], member_nr="MB", full_name="Broker")
    create_fine_schedule(assoc["id"], rule_code="INACCURACY", fine_amount_cents=30000,
                         effective_from="2026-01-01T00:00:00Z",
                         effective_to="2026-10-01T00:00:00Z")
    validate_success(api.create_fine_schedule(
        assoc["id"],
        {"rule_code": "INACCURACY", "fine_amount_cents": 45000,
         "effective_from": "2026-10-01T00:00:00Z"},
        STAFF), expected_status=201)
    # One second before the boundary: still covered by the first row.
    set_clock("2026-09-30T23:59:59Z")
    cit = create_citation(assoc["id"], member["id"], rule_code="INACCURACY")
    assert cit["fine_amount_cents"] == 30000


def test_consolidated_association_mutation_freeze_window(api):
    """PRD §3.10: "Executing the event requires the current logical instant to
    be at or after `effective_at`, else `ERR_CONSOLIDATION_NOT_DUE`, and
    requires the absorbed association to be in `MERGING`. Execution transitions
    the event to `EXECUTED`, moves the absorbed association to `MERGED` with
    `consolidated_into_id` pointing at the survivor, re-points every member of
    the absorbed association to the survivor while preserving each member's
    `membership_state`".
    PRD §2.8: "Mutating endpoints scoped under a `MERGED` association are
    rejected with `ERR_ASSOCIATION_MERGED` (reads remain allowed)."

    Design: Difficulty/resource_temporal_overlap/consolidated_association_mutation_freeze_window
    """
    set_clock("2026-09-01T00:00:00Z")
    survivor = create_association(association_code="AS1", membership_dues_cents=120000)
    absorbed = create_association(association_code="AA1", membership_dues_cents=90000,
                                  late_fee_tier1_cents=4000, late_fee_tier2_cents=12000)
    mx = create_member(absorbed["id"], member_nr="MX", full_name="Member X")
    event = get_success_data(api.create_consolidation(
        survivor["id"], {"absorbed_association_id": absorbed["id"],
                         "effective_at": "2026-10-01T00:00:00Z"}, STAFF))
    set_clock("2026-09-30T23:59:59Z")
    # One second before effective_at -> not due.
    resp = api.execute_consolidation(survivor["id"], event["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_CONSOLIDATION_NOT_DUE)
    # MERGING absorbed association still accepts member-facing mutations.
    my = validate_success(api.create_member(
        absorbed["id"], {"member_nr": "MY", "full_name": "Member Y"}, STAFF),
        expected_status=201)
    # Exactly at effective_at the execution succeeds and freezes the absorbed.
    set_clock("2026-10-01T00:00:00Z")
    executed = validate_success(
        api.execute_consolidation(survivor["id"], event["id"], STAFF))
    assert executed["status"] == "EXECUTED"
    absorbed_now = get_success_data(api.get_association(absorbed["id"], STAFF))
    assert absorbed_now["consolidation_state"] == "MERGED"
    assert absorbed_now["consolidated_into_id"] == survivor["id"]
    resp = api.create_member(
        absorbed["id"], {"member_nr": "MZ", "full_name": "Member Z"}, STAFF)
    validate_error(resp, ApiErrorId.ERR_ASSOCIATION_MERGED)
    # Member re-pointed to the survivor: read under the survivor's scope.
    mx_now = get_success_data(api.get_member(survivor["id"], mx["id"], STAFF))
    assert mx_now["association_id"] == survivor["id"]


def test_consolidation_cancel_returns_absorbed_to_active(api):
    """PRD §3.10: "Cancelling the event — permitted only before `effective_at`
    — transitions it to `CANCELLED` and returns the absorbed association to
    `ACTIVE`."

    Design: Difficulty/resource_temporal_overlap/consolidated_association_mutation_freeze_window
    """
    set_clock("2026-09-01T00:00:00Z")
    survivor = create_association(association_code="AS1C")
    absorbed = create_association(association_code="AA1C", membership_dues_cents=90000,
                                  late_fee_tier1_cents=4000, late_fee_tier2_cents=12000)
    event = get_success_data(api.create_consolidation(
        survivor["id"], {"absorbed_association_id": absorbed["id"],
                         "effective_at": "2026-10-01T00:00:00Z"}, STAFF))
    absorbed_mid = get_success_data(api.get_association(absorbed["id"], STAFF))
    assert absorbed_mid["consolidation_state"] == "MERGING"
    cancelled = validate_success(
        api.cancel_consolidation(survivor["id"], event["id"], STAFF))
    assert cancelled["status"] == "CANCELLED"
    absorbed_now = get_success_data(api.get_association(absorbed["id"], STAFF))
    assert absorbed_now["consolidation_state"] == "ACTIVE"
