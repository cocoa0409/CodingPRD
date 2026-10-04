"""Competition cycle and host-country program configuration rules (PRD §3.1)."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    add_country_program,
    assert_country_program,
    assert_cycle,
    begin_screening,
    close_cycle,
    create_country_program_payload,
    create_cycle,
    create_cycle_payload,
    cycle_transition_payload,
    patch_country_program_payload,
    setup_open_cycle,
    setup_submitted_application,
    validate_error,
    validate_success,
)


def _instant(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp; a date-only or naive value reads as UTC."""
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def test_cycle_create_returns_draft_with_system_fields(api, platform_admin_headers):
    """PRD §3.1: "the cycle's `status` is born DRAFT."
    PRD §2.5: "The `version` field is an integer that increments by exactly
    one on every mutation of the resource"
    PRD §2.5: "The `id` is a server-minted UUID with no type prefix."

    Design: Corner/entities/cycle_create_returns_draft_with_system_fields
    """
    resp = api.create_cycle(
        create_cycle_payload(
            academic_year="2027-2028",
            application_deadline="2026-10-15T23:59:59Z",
        ),
        platform_admin_headers,
    )
    data = validate_success(resp, 201)
    assert_cycle(data)
    assert data["status"] == "DRAFT", f"new cycle must be DRAFT, got {data['status']}"
    assert data["version"] == 1, f"new cycle version must be 1, got {data['version']}"
    assert data["academic_year"] == "2027-2028"
    assert _instant(data["application_deadline"]) == _instant("2026-10-15T23:59:59Z"), (
        f"application_deadline must round-trip, got {data['application_deadline']}"
    )


def test_country_program_create_initializes_slots_remaining(
    api, platform_admin_headers, program_officer_headers,
):
    """PRD §3.1: "At creation the program's `slots_remaining` equals its
    `slot_quota`."
    PRD §3.4: "a program's `slots_remaining` is its `slot_quota` minus the
    number of that program's applications currently in the slot-consuming
    states SELECTED, PLACEMENT, GRANT_PENDING, or AWARDED"

    Design: Corner/entities/country_program_create_initializes_slots_remaining
    """
    cycle = create_cycle()
    resp = api.create_country_program(
        cycle["id"],
        create_country_program_payload(slot_quota=2),
        platform_admin_headers,
    )
    data = validate_success(resp, 201)
    assert_country_program(data)
    assert data["slots_remaining"] == 2, (
        f"slots_remaining must equal slot_quota at creation, got {data['slots_remaining']}"
    )

    fetched = validate_success(
        api.get_country_program(data["id"], program_officer_headers)
    )
    assert fetched["slots_remaining"] == 2, "computed slots_remaining must persist on read"
    assert fetched["language_requirement"] == "NONE"


def test_country_program_create_missing_required_quota_returns_invalid_request(
    api, platform_admin_headers,
):
    """PRD §2.7: "Structural validation (`ERR_VALIDATION`, 400): required
    fields present, enum members valid, scores within 0–100, `end_date` after
    `start_date`, a stay's end not before its start, orientation not in the
    future, no unknown request fields, and `country_program_id` belonging to
    the addressed cycle."

    Design: Corner/entities/country_program_create_missing_required_quota_returns_invalid_request
    """
    cycle = create_cycle()
    payload = create_country_program_payload()
    payload.pop("slot_quota")
    resp = api.create_country_program(cycle["id"], payload, platform_admin_headers)
    error = validate_error(resp, ApiErrorId.ERR_VALIDATION)
    assert error["message"].strip(), "error must carry a human-readable message"


def test_cycle_open_without_country_programs_rejected(api, platform_admin_headers):
    """PRD §3.1: "From DRAFT, `OPEN` opens the competition — but only if at
    least one country program exists for the cycle, otherwise
    `ERR_NO_COUNTRY_PROGRAMS`."

    Design: Corner/state_machines/cycle_open_without_country_programs_rejected
    """
    cycle = create_cycle()
    resp = api.transition_cycle(
        cycle["id"], cycle_transition_payload("OPEN"), platform_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_NO_COUNTRY_PROGRAMS)

    stayed = validate_success(api.get_cycle(cycle["id"], platform_admin_headers))
    assert stayed["status"] == "DRAFT", (
        f"a rejected OPEN must leave the cycle DRAFT, got {stayed['status']}"
    )


def test_cycle_finalize_with_applications_pending_rejected(api, platform_admin_headers):
    """PRD §3.1: "From SCREENING, `FINALIZE_AWARDS` is allowed only when no
    application of the cycle remains in CAMPUS_REVIEW, NATIONAL_SCREENING, or
    HOST_REVIEW (`ERR_APPLICATIONS_PENDING`), and it sweeps every lingering
    DRAFT application of the cycle to WITHDRAWN and every ALTERNATE
    application to NOT_SELECTED."

    Design: Corner/state_machines/cycle_finalize_with_applications_pending_rejected
    """
    bundle = setup_submitted_application()  # application in NATIONAL_SCREENING
    cycle = bundle["cycle"]
    close_cycle(cycle)
    cycle = begin_screening(cycle)
    assert cycle["status"] == "SCREENING"

    resp = api.transition_cycle(
        cycle["id"], cycle_transition_payload("FINALIZE_AWARDS"),
        platform_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_APPLICATIONS_PENDING)

    stayed = validate_success(api.get_cycle(cycle["id"], platform_admin_headers))
    assert stayed["status"] == "SCREENING", (
        f"a rejected FINALIZE_AWARDS must leave the cycle SCREENING, got {stayed['status']}"
    )


def test_patch_country_program_after_cycle_open_rejected(api, platform_admin_headers):
    """PRD §3.1: "Once the cycle has left DRAFT such edits are rejected with
    `ERR_CYCLE_PHASE_FORBIDS`."
    PRD §3.1: "the edit recomputes `slots_remaining` and increments the
    program's `version` by one"

    Design: Corner/state_machines/patch_country_program_after_cycle_open_rejected
    """
    base = setup_open_cycle()  # program slot_quota 1, cycle already OPEN
    program = base["program"]

    resp = api.patch_country_program(
        program["id"], patch_country_program_payload(slot_quota=5),
        platform_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CYCLE_PHASE_FORBIDS)

    fetched = validate_success(
        api.get_country_program(program["id"], platform_admin_headers)
    )
    assert fetched["slot_quota"] == 1, "a rejected edit must not change slot_quota"
    assert fetched["version"] == 1, "a rejected edit must not bump the version"
