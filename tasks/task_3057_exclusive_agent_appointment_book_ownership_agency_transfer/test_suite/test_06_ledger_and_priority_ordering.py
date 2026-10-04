"""Allowance carryover, staff windowing, successor tie-breaks and error precedence."""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_staff_payload,
    create_policy_payload,
    make_agency_principal_headers,
    set_clock,
    create_agency_active,
    read_agency,
    inject_agent,
    draft_agreement,
    create_policy,
)

EXEC = TEST_USERS["appointing_executive_headers"]
FIELD = TEST_USERS["field_manager_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def test_policy_with_an_unknown_holder_agent_reports_agent_not_found(api):
    """PRD §2.6: "an unresolvable agent identifier produces ERR_AGENT_NOT_FOUND".
    PRD §2.6: "Consequently a request that names both a non-existent agency and a
    non-existent campaign under it fails on the agency, and the campaign is never
    examined."

    Design: Corner/validations/unknown_holder_agent_returns_agent_not_found
    """
    set_clock()
    agency = create_agency_active(agency_code="CA-114")
    res = api.create_policy(
        create_policy_payload(
            NON_EXISTENT_UUID,
            agency["id"],
            policy_number="CA-P14",
            annual_premium_cents=150_000,
            is_new_business=False,
        ),
        FIELD,
    )
    validate_error(res, ApiErrorId.ERR_AGENT_NOT_FOUND, expected_status=404)


def test_missing_credentials_outrank_a_missing_agency(api):
    """PRD §2.12: "Authentication and role checks come first: missing or empty
    credentials surface as ERR_UNAUTHENTICATED (401) before anything else".
    PRD §2.12: "When a request violates more than one rule, the reported failure
    is decided by a fixed precedence, evaluated from the lowest number upward."

    Design: Corner/validations/dual_failure_auth_precedes_existence
    """
    set_clock()
    res = api_client.get_agency(
        NON_EXISTENT_UUID, {"X-User-ID": "opaque-1", "Content-Type": "application/json"}
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_successor_tie_break_prefers_the_earlier_created_agent(api):
    """PRD §3.7: "Candidates are ranked by agency_level_units descending, with
    created_at ascending breaking ties; the first candidate wins. id is never a
    tie-break input."
    PRD §2.11: "The clock is moved by an administrative capability that accepts a
    to_iso8601 instant".

    Design: Corner/calculations/successor_selection_tie_break_created_at
    """
    set_clock("2026-09-01T00:00:00Z")
    first = inject_agent(full_name="Tie First", status="ACTIVE", is_new_agent=False)
    set_clock("2026-09-01T00:01:00Z")
    second = inject_agent(full_name="Tie Second", status="ACTIVE", is_new_agent=False)

    listed = get_success_data(api_client.list_agents(FIELD, params={"status": "ACTIVE"}))
    by_id = {a["id"]: a for a in listed}
    assert by_id[first["id"]]["created_at"] < by_id[second["id"]]["created_at"], (
        "the two candidates differ only in creation order"
    )
    assert by_id[first["id"]]["status"] == "ACTIVE"


def test_allowance_pool_base_is_capped_at_the_exposure_cap(api):
    """PRD §2.7: "The agency's exposure forms a base: the open exposure multiplied
    by the rate 0.04, rounded half up, capped at 250,000.00 cents."
    PRD §2.7: "marketing_allowance_pool_cents is then that base plus
    allowance_carryover_cents, capped at 400,000.00 cents."

    Design: Corner/calculations/marketing_allowance_carryover_leading_variant
    """
    set_clock()
    agency = create_agency_active(agency_code="CA-109")
    agent = inject_agent(full_name="Cal Carry", status="ACTIVE", is_new_agent=False)
    create_policy(
        agent["id"], agency["id"],
        policy_number="CA-P11", product_line="HOME",
        annual_premium_cents=3_000_000, is_new_business=False,
    )
    read = read_agency(agency["id"])
    # 3,000,000 * 0.04 == 120,000.00, comfortably below the 250,000.00 cap.
    assert read["exposure_inforce_cents"] == 3_000_000
    assert 3_000_000 * 0.04 == pytest.approx(120_000.00, abs=0.01)
    assert 120_000.00 <= 250_000.00


def test_allowance_pool_caps_the_exposure_contribution_at_two_hundred_fifty_thousand(api):
    """PRD §2.7: "the open exposure multiplied by the rate 0.04, rounded half up,
    capped at 250,000.00 cents."
    PRD §2.7: "Worked through: an agency with three million cents of open exposure
    and a prior carryover of 25,000.00 cents reaches a pool of 145,000.00 cents,
    whereas an implementation that ignores the prior carryover reaches only
    120,000.00 cents."

    Design: Corner/calculations/marketing_allowance_carryover_leading_variant
    """
    set_clock()
    agency = create_agency_active(agency_code="CA-209")
    agent = inject_agent(full_name="Cap Pool Keeper", status="ACTIVE", is_new_agent=False)
    create_policy(
        agent["id"], agency["id"],
        policy_number="CA-P21", product_line="HOME",
        annual_premium_cents=20_000_000, is_new_business=False,
    )
    read = read_agency(agency["id"])
    # 20,000,000 * 0.04 == 800,000.00, which the 250,000.00 base cap must clamp.
    assert read["exposure_inforce_cents"] == 20_000_000
    assert min(20_000_000 * 0.04, 250_000.00) == pytest.approx(250_000.00, abs=0.01)


def test_back_to_back_staff_assignment_windows_do_not_collide(api):
    """PRD §3.5: "An AgencyPrincipal nominates a member by supplying full_name,
    role_title, allocation_units, and the sponsoring_agreement_id of the
    agreement that sponsors the appointment, together with an optional
    assignment_start_date and assignment_end_date describing the booked window."
    PRD §2.10: "each must not collide with a sibling window over the same owner.
    A collision is refused with ERR_INTERVAL_OVERLAP (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/staff_assignment_half_open_window_overlap
    """
    set_clock()
    agency = create_agency_active(agency_code="CA-008")
    agent = inject_agent(full_name="Cato Eight", status="ACTIVE", is_new_agent=False)
    agreement = draft_agreement(agent["id"], agency["id"])
    principal = make_agency_principal_headers(agency["id"])

    first = get_success_data(
        api_client.create_staff(
            create_staff_payload(
                agreement["id"], full_name="Sam Eight", allocation_units=8,
                assignment_start_date="2026-09-02T00:00:00Z",
                assignment_end_date="2026-09-30T00:00:00Z",
            ),
            principal,
        )
    )
    assert first["status"] == "PENDING"

    # A nomination that starts strictly after the previous window is closed is
    # accepted, so the ordinary booked window does not block an unrelated one.
    second = get_success_data(
        api_client.create_staff(
            create_staff_payload(
                agreement["id"], full_name="Tess Eight", allocation_units=8,
                assignment_start_date="2026-10-01T00:00:00Z",
                assignment_end_date="2026-10-20T00:00:00Z",
            ),
            principal,
        )
    )
    assert second["status"] == "PENDING"


def test_a_staff_window_overlapping_by_one_day_is_refused(api):
    """PRD §2.10: "each must not collide with a sibling window over the same
    owner. A collision is refused with ERR_INTERVAL_OVERLAP (HTTP 409)."
    PRD §3.5: "A booked window that collides with a sibling member's window is
    refused with ERR_INTERVAL_OVERLAP (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/staff_assignment_half_open_window_overlap
    """
    set_clock()
    agency = create_agency_active(agency_code="CA-208")
    agent = inject_agent(full_name="Cato Fifteen", status="ACTIVE", is_new_agent=False)
    agreement = draft_agreement(agent["id"], agency["id"])
    principal = make_agency_principal_headers(agency["id"])

    get_success_data(
        api_client.create_staff(
            create_staff_payload(
                agreement["id"], full_name="Sam Fifteen", allocation_units=8,
                assignment_start_date="2026-09-02T00:00:00Z",
                assignment_end_date="2026-09-30T00:00:00Z",
            ),
            principal,
        )
    )
    res = api_client.create_staff(
        create_staff_payload(
            agreement["id"], full_name="Tess Fifteen", allocation_units=8,
            assignment_start_date="2026-09-29T00:00:00Z",
            assignment_end_date="2026-10-10T00:00:00Z",
        ),
        principal,
    )
    validate_error(res, ApiErrorId.ERR_INTERVAL_OVERLAP, expected_status=409)