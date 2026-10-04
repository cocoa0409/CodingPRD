"""Agreement drafting/transcription, licensing gates, staffing and campaigns."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    validate_error,
    validate_error_is_one_of,
    ApiErrorId,
    TEST_USERS,
    COMMISSION_SCHEDULE_INCOMPLETE,
    create_staff_payload,
    create_campaign_payload,
    make_agency_principal_headers,
    set_clock,
    create_agency_active,
    read_agency,
    inject_agent,
    draft_agreement,
    setup_active_staff_member,
    setup_agency_with_allowance_pool,
    setup_agency_with_live_agreement,
    appoint_agent_via_application,
)

EXEC = TEST_USERS["appointing_executive_headers"]
FIELD = TEST_USERS["field_manager_headers"]


def test_agreement_draft_round_trips_the_commission_schedule(api):
    """PRD §3.3: "A schedule must cover all three product lines."
    PRD §3.3: "The schedule is the client's number, never the server's: it is an
    input object giving a new-business rate and a renewal rate for each product
    line".
    PRD §3.3: "Drafting moves the agreement from DRAFT to UNDER_REVIEW."

    Design: Corner/entities/agreement_get_round_trips_commission_schedule
    """
    set_clock()
    agency = create_agency_active(agency_code="CA-102")
    agent = inject_agent(full_name="Cal RT", status="ACTIVE", is_new_agent=False)
    agreement = draft_agreement(agent["id"], agency["id"])
    assert agreement["status"] == "UNDER_REVIEW"

    fetched = validate_success(api.get_agreement(agreement["id"], FIELD), 200)
    schedule = fetched["commission_schedule"]
    assert schedule["AUTO"] == {"new": 0.15, "renewal": 0.10}
    assert schedule["HOME"]["new"] == pytest.approx(0.12)
    assert schedule["LIFE"]["new"] == pytest.approx(0.25)
    assert fetched["status"] == "UNDER_REVIEW"


def test_agreement_draft_missing_a_product_line_pair_is_refused(api):
    """PRD §3.3: "If the supplied schedule is missing a {new, renewal} pair for
    AUTO, HOME, or LIFE, both drafting and transcription are refused with
    ERR_SCHEDULE_MISSING (HTTP 400)."

    Design: Corner/calculations/refusal_schedule_missing_line_on_agreement
    """
    set_clock()
    agency = create_agency_active(agency_code="CA-111")
    agent = inject_agent(full_name="Cal Sched", status="ACTIVE", is_new_agent=False)
    res = api.create_agreement(
        {
            "agent_id": agent["id"],
            "agency_id": agency["id"],
            "agreement_type": "EXCLUSIVE_AGENT",
            "commission_schedule": COMMISSION_SCHEDULE_INCOMPLETE,
        },
        FIELD,
    )
    validate_error(res, ApiErrorId.ERR_SCHEDULE_MISSING, expected_status=400)


def test_transcribing_an_unlicensed_agents_agreement_is_refused(api):
    """PRD §3.3: "It requires the acting agent's license_status to be LICENSED,
    the owner agent to be in TRANSITIONING".
    PRD §2.10: "Every duty that depends on an appointment or on a book transition
    requires license_status to be LICENSED; when it is not, the duty is refused
    with ERR_LICENSED_REQUIRED (HTTP 400)."
    PRD §3.3: "Transcription brings the agreement into force, moving it from
    UNDER_REVIEW to ACTIVE."

    Design: Corner/state_machines/agreement_transcribe_requires_license_and_transitioning_agent
    """
    set_clock()
    agency = create_agency_active(agency_code="CA-107")
    # A raw agent seeded onto the agency's book in TRANSITIONING but with no
    # license read, so the licensing gate is the only unmet precondition.
    agent = inject_agent(
        full_name="Vera Unlicensed", status="TRANSITIONING",
        license_status="NOT_LICENSED", is_new_agent=True,
    )
    agreement = draft_agreement(agent["id"], agency["id"])
    assert agreement["status"] == "UNDER_REVIEW"
    res = api.transcribe_agreement(
        agreement["id"], {"expected_agent_version": agent["version"]}, FIELD
    )
    validate_error(res, ApiErrorId.ERR_LICENSED_REQUIRED, expected_status=400)

    # Reading the license clears the gate, and transcription then succeeds.
    licensed = get_success_data(
        api_client.read_license(
            agent["id"],
            {"license_expiry_date": "2028-01-01T00:00:00Z", "product_lines": ["AUTO", "HOME", "LIFE"]},
            FIELD,
        )
    )
    transcribed = get_success_data(
        api_client.transcribe_agreement(
            agreement["id"], {"expected_agent_version": licensed["version"]}, FIELD
        )
    )
    assert transcribed["status"] == "ACTIVE"


def test_licensing_read_sets_licensed_and_stamps_the_agreement(api):
    """PRD §3.2: "Reading an agent's license calls the state board and upserts a
    LicenseRecord capturing full_name, state_code, product_lines, and
    license_expiry_date; it then sets the agent's license_status to LICENSED,
    refreshes license_expiry_date on the agent, and stamps license_verified_at on
    the agent's agreement with the current logical time. Until that first read,
    the agreement's license_verified_at is null."

    Design: Difficulty/cross_entity_state_dependency/staff_appointment_requires_sponsoring_agreement_active
    """
    set_clock()
    agency = create_agency_active(agency_code="CA-150")
    agent = appoint_agent_via_application()
    agreement = draft_agreement(agent["id"], agency["id"])
    assert agreement.get("license_verified_at") in (None, ""), (
        "license_verified_at is null until the first license read"
    )

    licensed = get_success_data(
        api_client.read_license(
            agent["id"],
            {"license_expiry_date": "2028-01-01T00:00:00Z", "product_lines": ["AUTO", "HOME", "LIFE"]},
            FIELD,
        )
    )
    assert licensed["license_status"] == "LICENSED"

    agreement_after = validate_success(api.get_agreement(agreement["id"], FIELD), 200)
    assert agreement_after["license_verified_at"], (
        "license_verified_at is stamped with the current logical time"
    )


def test_staff_appointment_is_refused_while_the_sponsoring_agreement_is_under_review(api):
    """PRD §3.5: "The sponsor gate applies to both nomination and appointment. The
    sponsoring agreement's owner agent must be in a live state — ACTIVE or
    TRANSITIONING. A nomination or appointment whose sponsor is not live is
    refused with ERR_SPONSOR_AGREEMENT_NOT_ACTIVE (HTTP 409)."
    PRD §3.5: "The nomination lands in PENDING".

    Design: Difficulty/cross_entity_state_dependency/staff_appointment_requires_sponsoring_agreement_active
    """
    set_clock()
    agency = create_agency_active(agency_code="OAK-05")
    agent = inject_agent(full_name="Cato Five", status="ACTIVE", is_new_agent=False)
    agreement = draft_agreement(agent["id"], agency["id"])
    assert agreement["status"] == "UNDER_REVIEW"

    staff = get_success_data(
        api_client.create_staff(
            create_staff_payload(agreement["id"], full_name="Sam Five", allocation_units=6),
            make_agency_principal_headers(agency["id"]),
        )
    )
    assert staff["status"] == "PENDING"
    res = api.appoint_staff(staff["id"], make_agency_principal_headers(agency["id"]))
    validate_error(res, ApiErrorId.ERR_SPONSOR_AGREEMENT_NOT_ACTIVE, expected_status=409)


def test_staff_appointment_succeeds_once_the_sponsoring_agreement_is_active(api):
    """PRD §3.5: "Appointment moves the member from PENDING to ACTIVE and is
    permitted only when three conditions hold together: the sponsoring agreement
    is ACTIVE, the sponsoring agreement's owner agent is ACTIVE, and the member's
    allocated_agent_id resolves to an agent whose license_status is LICENSED."
    PRD §3.5: "At the moment of appointment, allocated_agent_id is written with
    the agent that was allocated, fixing the attribution."

    Design: Difficulty/cross_entity_state_dependency/staff_appointment_requires_sponsoring_agreement_active
    """
    set_clock()
    agency, agent, agreement, staff = setup_active_staff_member()
    assert staff["status"] == "ACTIVE"
    assert staff["allocated_agent_id"] == agent["id"]


def test_nominated_member_keeps_its_allocation_units_within_bounds(api):
    """PRD §3.5: "allocation_units must be between 1 and 20 inclusive, where ten
    units represent one full-time equivalent."
    PRD §3.5: "An AgencyPrincipal nominates a member by supplying full_name,
    role_title, allocation_units, and the sponsoring_agreement_id of the
    agreement that sponsors the appointment".

    Design: Difficulty/combinatorial_formula/staffing_reimbursement_per_member_rounding_then_cap
    """
    set_clock()
    agency = create_agency_active(agency_code="CA-160")
    agent = inject_agent(full_name="Bound Owner", status="ACTIVE", is_new_agent=False)
    agreement = draft_agreement(agent["id"], agency["id"])

    nominated = get_success_data(
        api_client.create_staff(
            create_staff_payload(agreement["id"], full_name="Max Member", allocation_units=20),
            make_agency_principal_headers(agency["id"]),
        )
    )
    assert nominated["allocation_units"] == 20
    assert nominated["status"] == "PENDING"


def test_nomination_above_the_allocation_ceiling_is_refused(api):
    """PRD §3.5: "allocation_units must be between 1 and 20 inclusive, where ten
    units represent one full-time equivalent."
    PRD §2.10: "Team allocation itself is bounded per member: allocation_units
    must be between 1 and 20 inclusive, with ten units representing one
    full-time equivalent."

    Design: Difficulty/combinatorial_formula/staffing_reimbursement_per_member_rounding_then_cap
    """
    set_clock()
    agency = create_agency_active(agency_code="CA-161")
    agent = inject_agent(full_name="Ceil Owner", status="ACTIVE", is_new_agent=False)
    agreement = draft_agreement(agent["id"], agency["id"])

    res = api_client.create_staff(
        create_staff_payload(agreement["id"], full_name="Over Member", allocation_units=21),
        make_agency_principal_headers(agency["id"]),
    )
    assert res.status_code == 400, (
        f"allocation_units above 20 must be refused, got {res.status_code}"
    )


def test_re_appointing_a_terminated_member_is_refused(api):
    """PRD §2.12: "any attempt to leave a terminal state yields
    ERR_ALREADY_TERMINAL (409)."
    PRD §3.5: "Termination of a team member is not driven by a principal's request
    but by the agency's own status changes. When an agency agreement expires or
    the agency itself terminates, its ACTIVE staff members become TERMINATED."

    Design: Corner/state_machines/staff_appoint_from_terminated_returns_already_terminal
    """
    set_clock()
    agency, agent, agreement, staff = setup_active_staff_member()
    principal = make_agency_principal_headers(agency["id"])
    get_success_data(
        api_client.cessation(
            agent["id"], {"last_day_iso8601": "2026-08-31T00:00:00Z"}, principal
        )
    )
    get_success_data(api_client.terminate_agency(agency["id"], EXEC))

    terminated = get_success_data(api_client.get_staff(staff["id"], principal))
    assert terminated["status"] == "TERMINATED", (
        "agency termination cascades its ACTIVE staff members to TERMINATED"
    )

    res = api.appoint_staff(staff["id"], principal)
    validate_error_is_one_of(
        res,
        [ApiErrorId.ERR_ALREADY_TERMINAL, ApiErrorId.ERR_INVALID_STATE],
    )


def test_campaign_window_that_touches_a_sibling_is_refused(api):
    """PRD §2.10: "A campaign's start_date–end_date window and a team member's
    assignment_start_date–assignment_end_date window are closed intervals, and
    each must not collide with a sibling window over the same owner. A collision
    is refused with ERR_INTERVAL_OVERLAP (HTTP 409)."
    PRD §3.4: "A campaign window that collides with a sibling campaign window over
    the same agency is refused with ERR_INTERVAL_OVERLAP (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/campaign_window_closed_interval_overlap
    """
    set_clock()
    agency = create_agency_active(agency_code="CA-007")
    first = get_success_data(
        api_client.create_campaign(
            agency["id"],
            create_campaign_payload(
                campaign_type="LEAD_PROGRAM",
                start_date="2026-09-02T00:00:00Z",
                end_date="2026-09-30T00:00:00Z",
            ),
            make_agency_principal_headers(agency["id"]),
        )
    )
    assert first["status"] == "PLANNED"

    res = api.create_campaign(
        agency["id"],
        create_campaign_payload(
            campaign_type="BRAND",
            marketing_allowance_cents=5_000,
            expected_leads=5,
            start_date="2026-09-30T00:00:00Z",
            end_date="2026-10-15T00:00:00Z",
        ),
        make_agency_principal_headers(agency["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INTERVAL_OVERLAP, expected_status=409)


def test_campaign_window_starting_after_the_gap_is_accepted(api):
    """PRD §2.10: "A campaign's start_date–end_date window and a team member's
    assignment_start_date–assignment_end_date window are closed intervals, and
    each must not collide with a sibling window over the same owner."
    PRD §3.4: "An AgencyPrincipal creates a campaign by supplying campaign_type —
    one of LEAD_PROGRAM, BRAND, or COMMUNITY — a marketing_allowance_cents draw
    that must be zero or greater, an optimistic expected_leads projection, and
    the start_date and end_date of the campaign window."

    Design: Difficulty/resource_temporal_overlap/campaign_window_closed_interval_overlap
    """
    set_clock()
    agency = create_agency_active(agency_code="CA-171")
    get_success_data(
        api_client.create_campaign(
            agency["id"],
            create_campaign_payload(
                start_date="2026-09-02T00:00:00Z", end_date="2026-09-30T00:00:00Z"
            ),
            make_agency_principal_headers(agency["id"]),
        )
    )
    second = get_success_data(
        api_client.create_campaign(
            agency["id"],
            create_campaign_payload(
                campaign_type="COMMUNITY",
                marketing_allowance_cents=5_000,
                expected_leads=5,
                start_date="2026-10-01T00:00:00Z",
                end_date="2026-10-15T00:00:00Z",
            ),
            make_agency_principal_headers(agency["id"]),
        )
    )
    assert second["status"] == "PLANNED"


def test_editing_a_planned_campaign_ignores_a_client_supplied_posture(api):
    """PRD §3.4: "Its participation_posture is derived from the parent agency's
    status and is one of OPEN, RESTRICTED, or FROZEN; it gates every write to the
    campaign".
    PRD §3.4: "The editable fields are marketing_allowance_cents and
    expected_leads, both updated in place without leaving PLANNED."

    Design: Corner/endpoints/campaign_put_input_ignored_for_computed_posture
    """
    set_clock()
    agency = create_agency_active(agency_code="CA-115")
    campaign = get_success_data(
        api_client.create_campaign(
            agency["id"], create_campaign_payload(), make_agency_principal_headers(agency["id"])
        )
    )
    assert campaign["participation_posture"] == "OPEN"

    updated = get_success_data(
        api_client.update_campaign(
            agency["id"],
            campaign["id"],
            {
                "marketing_allowance_cents": 9_000,
                "expected_leads": 12,
                "participation_posture": "FROZEN",
            },
            make_agency_principal_headers(agency["id"]),
        )
    )
    assert updated["marketing_allowance_cents"] == 9_000
    assert updated["expected_leads"] == 12
    assert updated["participation_posture"] == "OPEN", (
        "the FROZEN input must be ignored; the posture is derived"
    )
    assert updated["status"] == "PLANNED"


def test_cancelling_a_planned_campaign_debits_no_allowance(api):
    """PRD §3.4: "Cancelling likewise applies to a PLANNED campaign and moves it
    to CANCELLED, which is terminal, and debits no allowance: cancelling a
    planned campaign costs the agency nothing."
    PRD §2.7: "allowance_carryover_cents is defined as the pool minus
    marketing_allowance_spent_cents, which is itself the sum of
    marketing_allowance_cents over every campaign that has reached PARTICIPATED
    for that agency."

    Design: Difficulty/boundary_precision_check/campaign_draw_boundary_pool_exact_vs_one_cent
    """
    set_clock()
    agency, _agent, _policy = setup_agency_with_allowance_pool(exposure_cents=2_000_000)
    campaign = get_success_data(
        api_client.create_campaign(
            agency["id"],
            create_campaign_payload(marketing_allowance_cents=10_000),
            make_agency_principal_headers(agency["id"]),
        )
    )
    before_exposure = read_agency(agency["id"])["exposure_inforce_cents"]

    res = api_client.delete_campaign(
        agency["id"], campaign["id"], make_agency_principal_headers(agency["id"])
    )
    assert res.status_code in (200, 204), (
        f"cancelling a planned campaign should succeed, got {res.status_code}"
    )
    after_exposure = read_agency(agency["id"])["exposure_inforce_cents"]
    assert after_exposure == before_exposure, (
        "cancellation debits no allowance and does not touch exposure"
    )

def test_unauthenticated_request_without_a_role_header_is_rejected(api):
    """PRD §2.1: "Every request must carry two headers. X-User-Role names the
    acting role and X-User-ID identifies the acting party. Either header missing
    or empty is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/validations/missing_x_user_role_returns_unauthenticated
    """
    set_clock()
    res = api_client.create_agency(
        {
            "agency_code": "CA-112",
            "name": "No Auth",
            "region_code": "W",
            "market_need_score": 55,
        },
        {"X-User-ID": "opaque-1", "Content-Type": "application/json"},
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_appointing_under_a_suspended_sponsoring_agreement_is_refused(api):
    """PRD §3.5: "The sponsor gate applies to both nomination and appointment. The
    sponsoring agreement's owner agent must be in a live state — ACTIVE or
    TRANSITIONING. A nomination or appointment whose sponsor is not live is
    refused with ERR_SPONSOR_AGREEMENT_NOT_ACTIVE (HTTP 409)."

    Design: Corner/errors/err_allowedness_insufficient_on_staff_appoint
    """
    set_clock()
    agency, agent, agreement = setup_agency_with_live_agreement()
    principal = make_agency_principal_headers(agency["id"])
    # Nominate while the sponsor is still live, so the nomination itself is
    # accepted and only the later appointment is blocked.
    staff = get_success_data(
        api_client.create_staff(
            create_staff_payload(agreement["id"], full_name="Sam Suspended", allocation_units=6),
            principal,
        )
    )
    assert staff["status"] == "PENDING"

    # Ceasing the owner agent suspends the sponsoring agreement, taking the
    # sponsor out of a live state before the member is appointed.
    get_success_data(
        api_client.cessation(
            agent["id"],
            {"last_day_iso8601": "2026-08-31T00:00:00Z"},
            principal,
        )
    )
    suspended = validate_success(api.get_agreement(agreement["id"], FIELD), 200)
    assert suspended["status"] == "SUSPENDED"

    res = api.appoint_staff(staff["id"], principal)
    validate_error(res, ApiErrorId.ERR_SPONSOR_AGREEMENT_NOT_ACTIVE, expected_status=409)
