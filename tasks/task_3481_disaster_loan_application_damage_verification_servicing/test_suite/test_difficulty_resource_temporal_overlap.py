"""Difficulty queue: resource_temporal_overlap — interval semantics per resource."""
from test_helpers import (
    EXPECTED_SUCCESS_STATUS,
    ApiErrorId,
    create_declaration_payload,
    new_context,
    read_loan,
    request_servicing_action,
    servicing_action_decision_payload,
    setup_active_loan,
    setup_declaration,
    validate_error,
    validate_success,
)


def test_servicing_action_half_open_adjacency_vs_overlap(api):
    """PRD §3.9: "The new window must not overlap any sibling action on the same loan that is `APPROVED` or `ACTIVE` — two half-open windows overlap when one's `start_date` falls before the other's `end_date` while its own `end_date` falls after the other's `start_date`, and mere adjacency, where one's `end_date` equals the other's `start_date`, is allowed; an overlap is rejected with `ERR_ACCOMMODATION_OVERLAP` (HTTP 409)."
    PRD §3.9: "An approval whose `start_date` has already been reached activates immediately within the same request: the action continues to `ACTIVE` and the loan's `servicing_status` flips to `DEFERRED` or `HARDSHIP` according to the action type."
    PRD §3.9: "Otherwise the clock sweep activates an `APPROVED` action once the current instant reaches its `start_date`, and expires an `ACTIVE` action once the current instant reaches its `end_date`, returning the loan's `servicing_status` to `CURRENT`; both sweep transitions increment the action's and the loan's versions."

    Design: Difficulty/resource_temporal_overlap/servicing_action_half_open_adjacency_vs_overlap
    """
    # Setup: homeowner loan ACTIVE (accepted 2026-11-01, clock held there).
    ctx = setup_active_loan()
    loan_id = ctx["loan"]["id"]

    # Action A: [2027-01-01, 2027-03-01) approved; start not reached, so it
    # stays APPROVED (sweep activates it later).
    act_a = request_servicing_action(ctx, action_type="DEFERMENT",
                                     start_date="2027-01-01T00:00:00Z",
                                     end_date="2027-03-01T00:00:00Z")
    resp = api.decide_servicing_action(
        act_a["id"], servicing_action_decision_payload(decision="APPROVED"),
        ctx["servicing_headers"])
    decided_a = validate_success(
        resp, EXPECTED_SUCCESS_STATUS["decide_servicing_action"])
    assert decided_a["status"] == "APPROVED"

    # Action B starts exactly at A's end_date: half-open adjacency, no overlap.
    act_b = request_servicing_action(ctx, action_type="DEFERMENT",
                                     start_date="2027-03-01T00:00:00Z",
                                     end_date="2027-05-01T00:00:00Z")
    resp = api.decide_servicing_action(
        act_b["id"], servicing_action_decision_payload(decision="APPROVED"),
        ctx["servicing_headers"])
    decided_b = validate_success(
        resp, EXPECTED_SUCCESS_STATUS["decide_servicing_action"])
    assert decided_b["status"] == "APPROVED"

    # Action C [2027-02-15, 2027-04-01) intersects A's interior: rejected.
    act_c = request_servicing_action(ctx, action_type="HARDSHIP",
                                     start_date="2027-02-15T00:00:00Z",
                                     end_date="2027-04-01T00:00:00Z")
    resp = api.decide_servicing_action(
        act_c["id"], servicing_action_decision_payload(decision="APPROVED"),
        ctx["servicing_headers"])
    validate_error(resp, ApiErrorId.ERR_ACCOMMODATION_OVERLAP)
    actions = validate_success(
        api.list_servicing_actions(loan_id, ctx["servicing_headers"]),
        EXPECTED_SUCCESS_STATUS["list_servicing_actions"])
    assert [a for a in actions if a["id"] == act_c["id"]][0]["status"] == "REQUESTED"

    # No window has started (clock is 2026-11-01): servicing stays CURRENT.
    loan = read_loan(ctx)
    assert loan["servicing_status"] == "CURRENT"


def test_declaration_incident_window_inclusive_overlap(api):
    """PRD §3.1: "Geography may not be double-declared for overlapping time. When a declaration is created, every county it names is checked against every other declaration: if another declaration covers the same `county_fips` with an incident window that intersects the new one — both window ends inclusive, so sharing a single boundary day counts as overlap — the create is rejected with `ERR_DECLARATION_WINDOW_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/declaration_incident_window_inclusive_overlap
    """
    # Setup: DR-4821 covers county 06037 with inclusive incident window
    # [2026-10-01, 2026-10-15].
    ctx = new_context()
    setup_declaration(ctx, counties=[{
        "county_fips": "06037",
        "eligible_purposes": ["PHYSICAL_DAMAGE", "ECONOMIC_INJURY"],
    }])

    # Shared boundary day 2026-10-15 on the same county: inclusive-closed
    # semantics treat end == start as overlap.
    resp = api.create_declaration(
        create_declaration_payload(
            declaration_number="DR-5000",
            disaster_type="FLOOD",
            incident_start_date="2026-10-15T00:00:00Z",
            incident_end_date="2026-10-20T00:00:00Z",
            declared_date="2026-11-01T00:00:00Z",
            counties=[{"county_fips": "06037",
                       "eligible_purposes": ["PHYSICAL_DAMAGE"]}]),
        ctx["admin_headers"])
    validate_error(resp, ApiErrorId.ERR_DECLARATION_WINDOW_OVERLAP)

    # One day after the existing window ends: no intersection, created.
    resp = api.create_declaration(
        create_declaration_payload(
            declaration_number="DR-5001",
            disaster_type="FLOOD",
            incident_start_date="2026-10-16T00:00:00Z",
            incident_end_date="2026-10-20T00:00:00Z",
            declared_date="2026-11-01T00:00:00Z",
            counties=[{"county_fips": "06037",
                       "eligible_purposes": ["PHYSICAL_DAMAGE"]}]),
        ctx["admin_headers"])
    validate_success(resp, EXPECTED_SUCCESS_STATUS["create_declaration"])

    # Same days that would overlap DR-4821's window, but a different county:
    # the conflict is per-county, so this is created.
    resp = api.create_declaration(
        create_declaration_payload(
            declaration_number="DR-5002",
            disaster_type="FLOOD",
            incident_start_date="2026-10-10T00:00:00Z",
            incident_end_date="2026-10-12T00:00:00Z",
            declared_date="2026-11-01T00:00:00Z",
            counties=[{"county_fips": "99999",
                       "eligible_purposes": ["PHYSICAL_DAMAGE"]}]),
        ctx["admin_headers"])
    validate_success(resp, EXPECTED_SUCCESS_STATUS["create_declaration"])
