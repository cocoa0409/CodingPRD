"""Role authority and the entity-backed ownership rule. Queue B, section `rbac`."""
from test_helpers import (
    ADMIN,
    AUDITOR,
    ApiErrorId,
    UNKNOWN_ROLE_HEADERS,
    api_client,
    build_user_headers,
    create_schedule,
    create_station,
    get_success_data,
    make_station_manager_headers,
    set_clock,
    validate_error,
)

SCHEDULE_PAYLOAD = dict(
    schedule_code="FY2026C", fiscal_year=2026, base_fee_cents=1200000,
    revenue_rate_bps=250, market_size_multiplier_bps=12500,
    minimum_fee_cents=100000, maximum_fee_cents=5000000,
    annual_adjustment_bps=0, effective_from="2026-06-01T00:00:00Z",
    effective_to="2027-06-01T00:00:00Z",
)

FIRST_STATION = dict(
    call_sign="WKSU", licensee_name="Portage Licensee", state_code="OH",
    dma_market_rank=19, dma_households=1400000, coverage_population=95000,
    full_time_staff_count=7, newsroom_staff_count=4,
    annual_local_revenue_cents=4800000, board_seat_region="REGION_MIDWEST",
)

SECOND_STATION = dict(
    call_sign="WOSU", licensee_name="Scioto Licensee", state_code="OH",
    dma_market_rank=32, dma_households=950000, coverage_population=85000,
    full_time_staff_count=7, newsroom_staff_count=4,
    annual_local_revenue_cents=4800000, board_seat_region="REGION_MIDWEST",
)


def test_schedule_creation_is_reserved_to_the_platform_administrator():
    """PRD §2.1: "A request whose role is recognised but not permitted for the
    operation it attempts — or which impersonates a station it does not own — is
    refused with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: "POST | `/network/programming-fee-schedules` | Create a fiscal-year
    programming fee schedule | PlatformAdmin".

    Design: Corner/rbac/schedule_creation_rejected_for_auditor
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api_client.create_schedule(SCHEDULE_PAYLOAD, AUDITOR)

    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_nothing_is_persisted_by_a_role_refused_for_the_operation():
    """PRD §2.9: "Authority is settled first. A request lacking either `X-User-ID`
    or `X-User-Role`, or naming a role outside the seven-role matrix, fails
    immediately with `ERR_MISSING_AUTH` (401) before any body or path is
    inspected."

    The denied attempt must leave no schedule behind, so only the later
    administrator create is observable.

    Design: Corner/rbac/schedule_creation_rejected_for_auditor
    """
    set_clock("2026-09-01T00:00:00Z")
    api_client.create_schedule(SCHEDULE_PAYLOAD, AUDITOR)
    created = create_schedule(schedule_code="FY2026D")

    listed = get_success_data(api_client.list_schedules(ADMIN))
    assert [row["id"] for row in listed] == [created["id"]], (
        "the refused attempt must not have persisted a schedule"
    )


def test_a_station_manager_cannot_act_on_another_stations_record():
    """PRD §2.1: "A `StationManager` that files a candidacy for, supersedes a vote
    belonging to, or withdraws a candidacy filed by a station other than its own
    is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §2.1: "ownership checks on any resource that references a `MemberStation`
    compare the resource's foreign-key field — `station_id` on a window, a drive,
    a contribution, a candidacy, a slot or an underwriting agreement — to
    `X-User-ID`."

    Design: Corner/rbac/station_scope_rejected_for_non_owning_manager
    """
    set_clock("2026-09-01T00:00:00Z")
    actor = create_station(**FIRST_STATION)
    subject = create_station(**SECOND_STATION)

    resp = api_client.submit_eligibility(
        subject["id"], make_station_manager_headers(actor["id"]))

    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_the_owning_manager_may_act_on_its_own_station():
    """PRD §2.1: "When `X-User-Role` is `StationManager`, `X-User-ID` is the `id` of
    the acting `MemberStation`".

    Design: Corner/rbac/station_scope_rejected_for_non_owning_manager
    """
    set_clock("2026-09-01T00:00:00Z")
    station = create_station(**FIRST_STATION)

    data = get_success_data(api_client.submit_eligibility(
        station["id"], make_station_manager_headers(station["id"])))

    assert data["eligibility_status"] == "UNDER_REVIEW", (
        f"the owning manager's submission should be admitted, "
        f"got {data['eligibility_status']}"
    )


def test_a_role_outside_the_matrix_is_refused_at_authentication():
    """PRD §2.1: "A request missing either header, or carrying an `X-User-Role` that
    does not name one of the seven roles below, is refused with
    `ERR_MISSING_AUTH` (HTTP 401)."
    PRD §2.1: "Their names are spelled exactly as written here and are not
    case-insensitive aliases of one another."

    Design: Corner/rbac/schedule_creation_rejected_for_auditor
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api_client.create_schedule(
        dict(SCHEDULE_PAYLOAD, schedule_code="FY2026E"), UNKNOWN_ROLE_HEADERS)

    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH)


def test_a_recognised_but_unauthorised_capacity_is_refused_at_authority():
    """PRD §2.9: "When the headers are present but the acting role is not permitted
    for the operation — including the case where an entity-backed `StationManager`
    acts on a station it does not own, which applies to every endpoint variant
    that carries an acting-station attribution — the request fails with
    `ERR_FORBIDDEN_ROLE` (403)."

    The same operation under a different unrecognised capacity stays a
    missing-auth failure, which is what the two error identifiers separate.

    Design: Corner/rbac/schedule_creation_rejected_for_auditor
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api_client.create_schedule(
        dict(SCHEDULE_PAYLOAD, schedule_code="FY2026F"),
        build_user_headers("test-program-editor-1", "NationalProgramEditor"))

    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)