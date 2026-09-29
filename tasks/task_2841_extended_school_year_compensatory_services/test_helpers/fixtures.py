"""Composite setup helpers.

Each test starts against an empty database, so every precondition is built here
from scratch using only endpoints the PRD declares. All helpers use the lenient
`get_success_data` so that a setup failure surfaces as an explicit error id
rather than an opaque KeyError.
"""

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import ApiClient
from .constants import (
    CANON_DATE_MON_W1,
    CANON_DATE_TUE_W1,
    CANON_DATE_WED_W1,
    CLOCK_POST_SESSION,
    CLOCK_PRE_SESSION,
)
from .test_users import (
    make_case_manager_headers,
    make_compliance_officer_headers,
    make_parent_guardian_headers,
    make_program_coordinator_headers,
    make_related_service_provider_headers,
    make_sped_director_headers,
)

JsonDict = Dict[str, Any]

CM = make_case_manager_headers()
PC = make_program_coordinator_headers()
DIR = make_sped_director_headers()
DIR_ALT = make_sped_director_headers("dir-002")
CO = make_compliance_officer_headers()


# ------------------------------------------------------------------- tier 0
def set_clock(api: ApiClient, instant: str = CLOCK_PRE_SESSION) -> JsonDict:
    """Pin the server's logical clock to an explicit ISO-8601 instant."""
    return get_success_data(api.set_clock(instant, CM))


# ------------------------------------------------------------------- tier 1
def register_student(api: ApiClient, **overrides: Any) -> JsonDict:
    return get_success_data(
        api.create_student(factories.student_payload(**overrides), CM), 201
    )


def register_provider(api: ApiClient, **overrides: Any) -> JsonDict:
    return get_success_data(
        api.create_provider(factories.provider_payload(**overrides), PC), 201
    )


def create_program(api: ApiClient, **overrides: Any) -> JsonDict:
    return get_success_data(
        api.create_program(factories.program_payload(**overrides), PC), 201
    )


def authorize_allocation(
    api: ApiClient, program_id: str, **overrides: Any
) -> JsonDict:
    return get_success_data(
        api.create_fund_allocation(
            factories.fund_allocation_payload(program_id, **overrides), DIR
        ),
        201,
    )


def schedule_run(api: ApiClient, program_id: str, **overrides: Any) -> JsonDict:
    return get_success_data(
        api.create_transportation_run(
            factories.transportation_run_payload(program_id, **overrides), PC
        ),
        201,
    )


def file_due_process_record(
    api: ApiClient, student_id: str, record_type: str = "COMPLAINT", **overrides: Any
) -> JsonDict:
    return get_success_data(
        api.create_due_process_record(
            factories.due_process_record_payload(student_id, record_type, **overrides),
            CO,
        ),
        201,
    )


def close_due_process_record(
    api: ApiClient, record_id: str, status: str = "RESOLVED", **overrides: Any
) -> JsonDict:
    payload: JsonDict = {"status": status}
    payload.update(overrides)
    return get_success_data(api.patch_due_process_record(record_id, payload, CO))


# ------------------------------------------------------------------- tier 2
def make_eligible_student(
    api: ApiClient,
    student_overrides: Optional[JsonDict] = None,
    probes: Optional[List[JsonDict]] = None,
    analysis_variant: str = "PROBE_BASED",
    determination_overrides: Optional[JsonDict] = None,
    finalize: bool = True,
    analyst_headers: Optional[Dict[str, str]] = None,
    director_headers: Optional[Dict[str, str]] = None,
) -> JsonDict:
    """Register a student and walk one determination to FINALIZED.

    Returns {"student": ..., "determination": ...} with the student re-read so
    that its `esy_eligibility_status` reflects the finalization.
    """
    student = register_student(api, **(student_overrides or {}))
    det_payload = factories.determination_payload(
        student["id"],
        skill_probes=probes,
        analysis_variant=analysis_variant,
        **(determination_overrides or {}),
    )
    determination = get_success_data(
        api.create_determination(det_payload, analyst_headers or CM), 201
    )
    determination = get_success_data(
        api.analyze_determination(determination["id"], {}, analyst_headers or CM)
    )
    determination = get_success_data(
        api.determination_parent_response(
            determination["id"],
            {"response": "AGREE"},
            make_parent_guardian_headers(student["id"]),
        )
    )
    if finalize:
        determination = get_success_data(
            api.finalize_determination(
                determination["id"], {}, director_headers or DIR
            )
        )
    student = get_success_data(api.get_student(student["id"], CM))
    return {"student": student, "determination": determination}


def create_commitment(
    api: ApiClient, program_id: str, student_id: str, **overrides: Any
) -> JsonDict:
    return get_success_data(
        api.create_commitment(
            factories.commitment_payload(program_id, student_id, **overrides), CM
        ),
        201,
    )


def create_assignment(
    api: ApiClient,
    commitment_id: str,
    provider_id: str,
    expected_commitment_version: Optional[int] = None,
    **overrides: Any,
) -> JsonDict:
    """Assign a provider, reading the commitment's current version when not given."""
    if expected_commitment_version is None:
        commitment = get_success_data(api.get_commitment(commitment_id, PC))
        expected_commitment_version = commitment["version"]
    return get_success_data(
        api.create_provider_assignment(
            factories.assignment_payload(
                commitment_id, provider_id, expected_commitment_version, **overrides
            ),
            PC,
        ),
        201,
    )


def open_program(api: ApiClient, program_id: str) -> JsonDict:
    """Drive PLANNING -> STAFFING_LOCKED -> OPEN."""
    get_success_data(api.set_program_status(program_id, "STAFFING_LOCKED", PC))
    return get_success_data(api.set_program_status(program_id, "OPEN", PC))


def activate_commitment(api: ApiClient, commitment_id: str) -> JsonDict:
    return get_success_data(api.set_commitment_status(commitment_id, "ACTIVE", PC))


def log_service(
    api: ApiClient,
    payload: JsonDict,
    headers: Optional[Dict[str, str]] = None,
) -> JsonDict:
    return get_success_data(api.create_service_log(payload, headers or CM), 201)


def void_service_log(api: ApiClient, log_id: str, reason: str = "Data entry error") -> JsonDict:
    return get_success_data(
        api.void_service_log(log_id, {"void_reason": reason}, CO)
    )


def canonical_log_set(commitment_id: str, provider_id: str) -> List[Tuple[JsonDict, Optional[Dict[str, str]]]]:
    """The canonical three logs: 60 district-missed, 45/20 partial, 60 parent-missed.

    District-fault deficit is 60 + 25 = 85 minutes; the parent cancellation is
    excluded from the award input set.
    """
    return [
        (
            factories.missed_district_log_payload(commitment_id, CANON_DATE_MON_W1, 60),
            None,
        ),
        (
            factories.partial_log_payload(
                commitment_id, CANON_DATE_TUE_W1, 45, 20, provider_id=provider_id
            ),
            make_related_service_provider_headers(provider_id),
        ),
        (
            factories.missed_parent_log_payload(commitment_id, CANON_DATE_WED_W1, 60),
            None,
        ),
    ]


# ------------------------------------------------------------------- tier 3
def setup_baseline(
    api: ApiClient,
    clock: str = CLOCK_PRE_SESSION,
    student_overrides: Optional[JsonDict] = None,
    probes: Optional[List[JsonDict]] = None,
    analysis_variant: str = "PROBE_BASED",
    program_overrides: Optional[JsonDict] = None,
    allocation_overrides: Optional[JsonDict] = None,
    extra_allocations: Optional[Sequence[JsonDict]] = None,
    provider_overrides: Optional[JsonDict] = None,
    commitment_overrides: Optional[JsonDict] = None,
    assignment_overrides: Optional[JsonDict] = None,
    with_assignment: bool = True,
    with_open_program: bool = True,
    with_active_commitment: bool = True,
    logs: Optional[Iterable[Any]] = None,
    with_canonical_logs: bool = True,
) -> JsonDict:
    """Build the full canonical precondition chain.

    Clock -> eligible student -> program -> fund allocation -> provider ->
    service commitment -> provider assignment -> program OPEN -> commitment
    ACTIVE -> service logs.

    Returns a context dict whose keys are `student`, `determination`, `program`,
    `allocation`, `allocations`, `provider`, `commitment`, `assignment` and
    `logs`. Every entity is the freshest read available at the end of setup.
    """
    set_clock(api, clock)

    eligibility = make_eligible_student(
        api,
        student_overrides=student_overrides,
        probes=probes,
        analysis_variant=analysis_variant,
    )
    student = eligibility["student"]

    program = create_program(api, **(program_overrides or {}))
    allocations = [
        authorize_allocation(api, program["id"], **(allocation_overrides or {}))
    ]
    for extra in extra_allocations or []:
        allocations.append(authorize_allocation(api, program["id"], **extra))

    provider = register_provider(api, **(provider_overrides or {}))

    commitment = create_commitment(
        api, program["id"], student["id"], **(commitment_overrides or {})
    )

    assignment = None
    if with_assignment:
        assignment = create_assignment(
            api,
            commitment["id"],
            provider["id"],
            **(assignment_overrides or {}),
        )

    if with_open_program:
        program = open_program(api, program["id"])
    if with_active_commitment and with_open_program and with_assignment:
        commitment = activate_commitment(api, commitment["id"])

    created_logs: List[JsonDict] = []
    entries: List[Any]
    if logs is not None:
        entries = list(logs)
    elif with_canonical_logs:
        entries = canonical_log_set(commitment["id"], provider["id"])
    else:
        entries = []
    for entry in entries:
        if isinstance(entry, tuple):
            payload, headers = entry
        else:
            payload, headers = entry, None
        created_logs.append(log_service(api, payload, headers))

    return {
        "student": get_success_data(api.get_student(student["id"], CM)),
        "determination": eligibility["determination"],
        "program": get_success_data(api.get_program(program["id"], PC)),
        "allocation": refresh_allocation(api, program["id"], allocations[0]["id"])
        if allocations
        else None,
        "allocations": allocations,
        "provider": get_success_data(api.get_provider(provider["id"], PC)),
        "commitment": get_success_data(api.get_commitment(commitment["id"], PC)),
        "assignment": assignment,
        "logs": created_logs,
    }


# --------------------------------------------------------------- re-read helpers
def refresh_allocation(
    api: ApiClient, program_id: str, allocation_id: str
) -> JsonDict:
    """Re-read one allocation through the program's allocation list."""
    rows = get_success_data(
        api.list_program_fund_allocations(program_id, DIR, {"limit": 100})
    )
    for row in rows:
        if row["id"] == allocation_id:
            return row
    raise AssertionError(
        f"allocation {allocation_id} is not listed under program {program_id}"
    )


def refresh_run(api: ApiClient, program_id: str, run_id: str) -> JsonDict:
    """Re-read one transportation run through the program's run list."""
    rows = get_success_data(
        api.list_program_transportation_runs(program_id, PC, {"limit": 100})
    )
    for row in rows:
        if row["id"] == run_id:
            return row
    raise AssertionError(f"run {run_id} is not listed under program {program_id}")


def refresh_student(api: ApiClient, student_id: str) -> JsonDict:
    return get_success_data(api.get_student(student_id, CM))


def refresh_program(api: ApiClient, program_id: str) -> JsonDict:
    return get_success_data(api.get_program(program_id, PC))


def refresh_commitment(api: ApiClient, commitment_id: str) -> JsonDict:
    return get_success_data(api.get_commitment(commitment_id, PC))


def refresh_provider(api: ApiClient, provider_id: str) -> JsonDict:
    return get_success_data(api.get_provider(provider_id, PC))


def refresh_award(api: ApiClient, award_id: str) -> JsonDict:
    return get_success_data(api.get_award(award_id, CM))


def refresh_session(api: ApiClient, session_id: str) -> JsonDict:
    return get_success_data(api.get_makeup_session(session_id, CM))


def refresh_determination(api: ApiClient, determination_id: str) -> JsonDict:
    return get_success_data(api.get_determination(determination_id, CM))


def refresh_service_log(api: ApiClient, log_id: str) -> JsonDict:
    return get_success_data(api.get_service_log(log_id, CM))


def assignments_of_commitment(api: ApiClient, commitment_id: str) -> List[JsonDict]:
    return get_success_data(
        api.list_provider_assignments_for_commitment(
            commitment_id, PC, {"limit": 100}
        )
    )


# ------------------------------------------------------------------- tier 4
def open_award(
    api: ApiClient,
    student_id: str,
    source_program_id: str,
    calculation_variant: str = "MINUTE_FOR_MINUTE",
) -> JsonDict:
    return get_success_data(
        api.create_award(
            factories.award_payload(
                student_id, source_program_id, calculation_variant
            ),
            CM,
        ),
        201,
    )


def setup_agreed_award(
    api: ApiClient,
    baseline: Optional[JsonDict] = None,
    calculation_variant: str = "MINUTE_FOR_MINUTE",
    proposed_minutes: int = 85,
    agreement_clock: str = CLOCK_POST_SESSION,
    **baseline_kwargs: Any,
) -> JsonDict:
    """Extend a baseline to an award sitting at AGREED / NOT_STARTED.

    Opens the award, proposes `proposed_minutes`, advances the clock past the
    session so that makeup dates are bookable, and records the parent's AGREE.
    """
    context = baseline if baseline is not None else setup_baseline(api, **baseline_kwargs)
    award = open_award(
        api,
        context["student"]["id"],
        context["program"]["id"],
        calculation_variant,
    )
    award = get_success_data(
        api.propose_award(award["id"], {"proposed_minutes": proposed_minutes}, CM)
    )
    set_clock(api, agreement_clock)
    award = get_success_data(
        api.award_parent_response(
            award["id"],
            {"response": "AGREE"},
            make_parent_guardian_headers(context["student"]["id"]),
        )
    )
    context = dict(context)
    context["award"] = award
    context["student"] = refresh_student(api, context["student"]["id"])
    return context


def setup_scheduled_session(
    api: ApiClient,
    context: Optional[JsonDict] = None,
    minutes_planned: int = 60,
    session_date: str = "2027-09-13",
    start_time: str = "15:00",
    end_time: str = "16:00",
    **award_kwargs: Any,
) -> JsonDict:
    """Extend an agreed-award context with one SCHEDULED makeup session."""
    ctx = context if context is not None else setup_agreed_award(api, **award_kwargs)
    award = refresh_award(api, ctx["award"]["id"])
    session = get_success_data(
        api.create_makeup_session(
            factories.makeup_session_payload(
                award["id"],
                ctx["provider"]["id"],
                award["version"],
                session_date=session_date,
                start_time=start_time,
                end_time=end_time,
                minutes_planned=minutes_planned,
            ),
            CM,
        ),
        201,
    )
    ctx = dict(ctx)
    ctx["session"] = session
    ctx["award"] = refresh_award(api, award["id"])
    return ctx
