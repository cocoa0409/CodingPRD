"""Composite setup helpers.

Every helper builds its preconditions from scratch through the public API
(the runner restarts the server before each test, so nothing carries over).
Setup calls use the lenient ``get_success_data`` so failures surface as clear
"Setup failed" errors. Ownership-gated calls thread entity-backed identities
through ``make_parent_headers`` / ``make_volunteer_headers`` (PRD §2.1).
"""
from datetime import date as _date, timedelta

from prd_bench_local_runner.testing import get_success_data

from . import constants
from .api_client import api_client
from .factories import (
    create_accommodation_plan_payload,
    create_child_payload,
    create_classroom_payload,
    create_family_payload,
    create_message_payload,
    create_program_day_payload,
    create_program_payload,
    create_registration_payload,
    create_role_assignment_payload,
    create_screening_check_payload,
    create_supply_distribution_payload,
    create_supply_item_payload,
    create_supply_order_payload,
    create_volunteer_payload,
)
from .test_users import (
    TEST_USERS,
    make_parent_headers,
    make_safety_officer_headers,
    make_volunteer_headers,
)

_ANON = TEST_USERS["anonymous_headers"]
_DIRECTOR = TEST_USERS["program_director_headers"]
_REGCOORD = TEST_USERS["registration_coordinator_headers"]
_VOLCOORD = TEST_USERS["volunteer_coordinator_headers"]
_OFFICER = TEST_USERS["safety_officer_headers"]
_DESK = TEST_USERS["check_in_staff_headers"]

CHECK_TYPES = ("BACKGROUND", "REFERENCE", "SAFE_MINISTRY_TRAINING")


def _day_date(start_date: str, offset: int) -> str:
    base = _date.fromisoformat(start_date)
    return (base + timedelta(days=offset)).isoformat()


# ---------------------------------------------------------------------------
# Tier 0: single-call builders (lenient)
# ---------------------------------------------------------------------------

def create_program(**overrides) -> dict:
    resp = api_client.create_program(create_program_payload(**overrides), _DIRECTOR)
    return get_success_data(resp, 201)


def open_registration(program_id) -> dict:
    return get_success_data(api_client.open_registration(program_id, _DIRECTOR))


def close_registration(program_id) -> dict:
    return get_success_data(api_client.close_registration(program_id, _DIRECTOR))


def start_session(program_id) -> dict:
    return get_success_data(api_client.start_session(program_id, _DIRECTOR))


def complete_program(program_id) -> dict:
    return get_success_data(api_client.complete_program(program_id, _DIRECTOR))


def archive_program(program_id) -> dict:
    return get_success_data(api_client.archive_program(program_id, _DIRECTOR))


def get_program(program_id) -> dict:
    return get_success_data(api_client.get_program(program_id, _DIRECTOR))


def set_clock(to_iso8601) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, _DIRECTOR))


def create_classroom(program_id, **overrides) -> dict:
    resp = api_client.create_classroom(
        create_classroom_payload(program_id, **overrides), _REGCOORD
    )
    return get_success_data(resp, 201)


def get_classroom(classroom_id) -> dict:
    return get_success_data(api_client.get_classroom(classroom_id, _REGCOORD))


def create_family(**overrides) -> dict:
    resp = api_client.create_family(create_family_payload(**overrides), _ANON)
    return get_success_data(resp, 201)


def archive_family(family_id) -> dict:
    return get_success_data(api_client.archive_family(family_id, _REGCOORD))


def get_family(family_id) -> dict:
    return get_success_data(api_client.get_family(family_id, _REGCOORD))


def create_child(family_id, **overrides) -> dict:
    """Create a child as the owning Parent (X-User-ID == family_id)."""
    resp = api_client.create_child(
        create_child_payload(family_id, **overrides), make_parent_headers(family_id)
    )
    return get_success_data(resp, 201)


def get_child(child_id) -> dict:
    return get_success_data(api_client.get_child(child_id, _REGCOORD))


def register_child(child_id, classroom_id, family_id) -> dict:
    """Create a registration as the owning Parent."""
    resp = api_client.create_registration(
        create_registration_payload(child_id, classroom_id),
        make_parent_headers(family_id),
    )
    return get_success_data(resp, 201)


def cancel_registration(registration_id, family_id) -> dict:
    return get_success_data(
        api_client.cancel_registration(registration_id, make_parent_headers(family_id))
    )


def accept_offer(registration_id, family_id) -> dict:
    return get_success_data(
        api_client.accept_registration(registration_id, make_parent_headers(family_id))
    )


def decline_offer(registration_id, family_id) -> dict:
    return get_success_data(
        api_client.decline_registration(registration_id, make_parent_headers(family_id))
    )


def get_registration(registration_id) -> dict:
    return get_success_data(api_client.get_registration(registration_id, _REGCOORD))


def create_volunteer(program_id, **overrides) -> dict:
    resp = api_client.create_volunteer(
        create_volunteer_payload(program_id, **overrides), _ANON
    )
    return get_success_data(resp, 201)


def get_volunteer(volunteer_id) -> dict:
    return get_success_data(api_client.get_volunteer(volunteer_id, _VOLCOORD))


def propose_assignment(volunteer_id, classroom_id, role) -> dict:
    resp = api_client.create_role_assignment(
        create_role_assignment_payload(volunteer_id, classroom_id, role), _VOLCOORD
    )
    return get_success_data(resp, 201)


def get_assignment(assignment_id) -> dict:
    return get_success_data(api_client.get_role_assignment(assignment_id, _VOLCOORD))


def submit_check(volunteer_id, check_type) -> dict:
    """Submit a screening check as the volunteer themselves."""
    resp = api_client.create_screening_check(
        create_screening_check_payload(volunteer_id, check_type),
        make_volunteer_headers(volunteer_id),
    )
    return get_success_data(resp, 201)


def decide_check(check_id, decision, notes=None, officer_id=None) -> dict:
    payload = {"decision": decision}
    if notes is not None:
        payload["decision_notes"] = notes
    headers = (
        make_safety_officer_headers(officer_id) if officer_id else _OFFICER
    )
    return get_success_data(
        api_client.decide_screening_check(check_id, payload, headers)
    )


def resubmit_check(check_id, volunteer_id, response_notes="Updated documents") -> dict:
    return get_success_data(
        api_client.resubmit_screening_check(
            check_id, {"response_notes": response_notes},
            make_volunteer_headers(volunteer_id),
        )
    )


def get_screening_check(check_id) -> dict:
    return get_success_data(api_client.get_screening_check(check_id, _VOLCOORD))


def clear_volunteer(volunteer_id, officer_id=None) -> dict:
    """Submit all three required check types and clear each; the volunteer
    flips to CLEARED on the third decision (PRD §3.4)."""
    for check_type in CHECK_TYPES:
        check = submit_check(volunteer_id, check_type)
        decide_check(check["id"], "CLEARED", officer_id=officer_id)
    return get_volunteer(volunteer_id)


def create_day(program_id, date_str) -> dict:
    resp = api_client.create_program_day(
        create_program_day_payload(program_id, date_str), _DIRECTOR
    )
    return get_success_data(resp, 201)


def make_days(program_id, count, start_date=None) -> list:
    """Append `count` sequential days starting at the program's start_date."""
    if start_date is None:
        start_date = get_program(program_id)["start_date"]
    return [create_day(program_id, _day_date(start_date, i)) for i in range(count)]


def open_day(day_id) -> dict:
    return get_success_data(api_client.open_program_day(day_id, _DIRECTOR))


def close_day(day_id) -> dict:
    return get_success_data(api_client.close_program_day(day_id, _DIRECTOR))


def get_day(day_id) -> dict:
    return get_success_data(api_client.get_program_day(day_id, _DIRECTOR))


def open_day_with_clock(day, time_of_day="08:30:00") -> dict:
    """Move the logical clock onto the day's date, then open it."""
    set_clock(f"{day['date']}T{time_of_day}Z")
    return open_day(day["id"])


def check_in_child(child_id, program_day_id, desk_id=None) -> dict:
    """Check a child in; returns the attendance record (carries tag_code)."""
    headers = _DESK
    if desk_id is not None:
        from prd_bench_local_runner.testing import build_user_headers
        headers = build_user_headers(desk_id, "CheckInStaff")
    resp = api_client.check_in(
        {"child_id": child_id, "program_day_id": program_day_id}, headers
    )
    return get_success_data(resp, 201)


def check_out_child(child_id, program_day_id, tag_code, pickup_person="Pickup Parent") -> dict:
    resp = api_client.check_out(
        {
            "child_id": child_id,
            "program_day_id": program_day_id,
            "tag_code": tag_code,
            "pickup_person": pickup_person,
        },
        _DESK,
    )
    return get_success_data(resp)


def create_plan(child_id, family_id, **overrides) -> dict:
    resp = api_client.create_accommodation_plan(
        create_accommodation_plan_payload(child_id, **overrides),
        make_parent_headers(family_id),
    )
    return get_success_data(resp, 201)


def submit_plan(plan_id, family_id) -> dict:
    return get_success_data(
        api_client.submit_accommodation_plan(plan_id, make_parent_headers(family_id))
    )


def approve_plan(plan_id, expected_child_version, officer_id=None) -> dict:
    headers = make_safety_officer_headers(officer_id) if officer_id else _OFFICER
    return get_success_data(
        api_client.approve_accommodation_plan(
            plan_id, {"expected_child_version": expected_child_version}, headers
        )
    )


def create_order(program_id, **overrides) -> dict:
    resp = api_client.create_supply_order(
        create_supply_order_payload(program_id, **overrides), _DIRECTOR
    )
    return get_success_data(resp, 201)


def patch_order(order_id, **fields) -> dict:
    return get_success_data(api_client.patch_supply_order(order_id, fields, _DIRECTOR))


def submit_order(order_id) -> dict:
    return get_success_data(api_client.submit_supply_order(order_id, _DIRECTOR))


def approve_order(order_id) -> dict:
    return get_success_data(api_client.approve_supply_order(order_id, _DIRECTOR))


def cancel_order(order_id) -> dict:
    return get_success_data(api_client.cancel_supply_order(order_id, _DIRECTOR))


def get_order(order_id) -> dict:
    return get_success_data(api_client.get_supply_order(order_id, _DIRECTOR))


def get_supply_plan(program_id) -> dict:
    return get_success_data(api_client.get_supply_plan(program_id, _DIRECTOR))


def create_item(program_id, **overrides) -> dict:
    resp = api_client.create_supply_item(
        create_supply_item_payload(program_id, **overrides), _DIRECTOR
    )
    return get_success_data(resp, 201)


def get_item(item_id) -> dict:
    return get_success_data(api_client.get_supply_item(item_id, _DIRECTOR))


def create_distribution(supply_item_id, classroom_id, program_day_id, quantity) -> dict:
    resp = api_client.create_supply_distribution(
        create_supply_distribution_payload(
            supply_item_id, classroom_id, program_day_id, quantity=quantity
        ),
        _DIRECTOR,
    )
    return get_success_data(resp, 201)


def issue_distribution(distribution_id) -> dict:
    return get_success_data(api_client.issue_supply_distribution(distribution_id, _DIRECTOR))


def cancel_distribution(distribution_id) -> dict:
    return get_success_data(api_client.cancel_supply_distribution(distribution_id, _DIRECTOR))


def create_message(program_id, **overrides) -> dict:
    resp = api_client.create_message(
        create_message_payload(program_id, **overrides), _DIRECTOR
    )
    return get_success_data(resp, 201)


def send_message(message_id) -> dict:
    return get_success_data(api_client.send_message(message_id, _DIRECTOR))


def generate_retention(program_id, force=None) -> dict:
    payload = {} if force is None else {"force": force}
    resp = api_client.generate_retention_list(program_id, payload, _DIRECTOR)
    return get_success_data(resp, 201)


# ---------------------------------------------------------------------------
# Tier 1-2: program + classroom + enrollment composites
# ---------------------------------------------------------------------------

def setup_open_program_with_classroom(capacity=10, age_min=4, age_max=6,
                                      program_overrides=None, **classroom_over):
    """Program + one classroom, walked DRAFT -> REGISTRATION_OPEN so the
    classroom stands ACCEPTING (PRD §3.1)."""
    program = create_program(**(program_overrides or {}))
    classroom = create_classroom(
        program["id"], age_min=age_min, age_max=age_max, capacity=capacity,
        **classroom_over,
    )
    open_registration(program["id"])
    return program, get_classroom(classroom["id"])


def setup_family_with_children(count=1, birth_date=None, grade=None,
                               special_needs=False, family_overrides=None):
    """One ACTIVE family with `count` children. Returns (family, children)."""
    family = create_family(**(family_overrides or {}))
    children = []
    for _ in range(count):
        kwargs = {"has_special_needs": special_needs}
        if birth_date:
            kwargs["birth_date"] = birth_date
        if grade:
            kwargs["grade_completed"] = grade
        children.append(create_child(family["id"], **kwargs))
    return family, children


def setup_classroom_with_queue(capacity=2, waitlisted=2, birth_date=None,
                               program_overrides=None):
    """Classroom holding `capacity` ENROLLED children plus `waitlisted`
    WAITLISTED ones (one shared family; all children fit the default 4-6
    band). Returns a context dict."""
    program, classroom = setup_open_program_with_classroom(
        capacity=capacity, program_overrides=program_overrides
    )
    total = capacity + waitlisted
    family, children = setup_family_with_children(count=total, birth_date=birth_date)
    registrations = [
        register_child(c["id"], classroom["id"], family["id"]) for c in children
    ]
    return {
        "program": program,
        "classroom": get_classroom(classroom["id"]),
        "family": family,
        "children": children,
        "registrations": registrations,
    }


def setup_program_with_enrollment(classroom_specs, birth_dates_per_classroom,
                                  program_overrides=None):
    """Program in REGISTRATION_OPEN with children enrolled across classrooms.

    classroom_specs: list of classroom kwargs dicts.
    birth_dates_per_classroom: list (aligned with classroom_specs) of lists of
    birth dates; one shared family; every child is registered into its
    classroom. Returns a context dict."""
    program = create_program(**(program_overrides or {}))
    classrooms = [create_classroom(program["id"], **spec) for spec in classroom_specs]
    open_registration(program["id"])
    family = create_family()
    children_by_classroom = []
    for classroom, birth_dates in zip(classrooms, birth_dates_per_classroom):
        kids = []
        for bd in birth_dates:
            child = create_child(family["id"], birth_date=bd)
            register_child(child["id"], classroom["id"], family["id"])
            kids.append(child)
        children_by_classroom.append(kids)
    return {
        "program": program,
        "classrooms": [get_classroom(c["id"]) for c in classrooms],
        "family": family,
        "children_by_classroom": children_by_classroom,
    }


# ---------------------------------------------------------------------------
# Tier 3: volunteer staffing composites
# ---------------------------------------------------------------------------

def create_volunteer_with_assignment(program_id, classroom_id, role,
                                     decide_count=0, **volunteer_over):
    """Volunteer + PROPOSED assignment + all three screening checks submitted;
    the first `decide_count` checks are decided CLEARED. When decide_count is
    3 the volunteer flips CLEARED and the assignment auto-confirms (PRD §3.4).
    Returns a context dict."""
    volunteer = create_volunteer(program_id, **volunteer_over)
    assignment = propose_assignment(volunteer["id"], classroom_id, role)
    checks = [submit_check(volunteer["id"], t) for t in CHECK_TYPES]
    for check in checks[:decide_count]:
        decide_check(check["id"], "CLEARED")
    return {
        "volunteer": get_volunteer(volunteer["id"]),
        "assignment": get_assignment(assignment["id"]),
        "checks": checks,
    }


def staff_classroom_adequate(program_id, classroom_id):
    """Two cleared, confirmed adult teachers (LEAD + ASSISTANT) — enough for
    any classroom whose requirement is the two-adult minimum (PRD §3.4)."""
    lead = create_volunteer_with_assignment(
        program_id, classroom_id, "LEAD_TEACHER", decide_count=3,
        birth_date=constants.ADULT_BIRTH_DATE_1,
    )
    assistant = create_volunteer_with_assignment(
        program_id, classroom_id, "ASSISTANT_TEACHER", decide_count=3,
        birth_date=constants.ADULT_BIRTH_DATE_2,
    )
    return [lead, assistant]


# ---------------------------------------------------------------------------
# Tier 4-5: in-session and completed-program composites
# ---------------------------------------------------------------------------

def setup_in_session_program(child_count=1, n_days=5, one_family=True,
                             special_needs=False, capacity=10,
                             program_overrides=None, staff=True):
    """Full flow up to IN_SESSION: program + classroom + `n_days` appended
    days -> open registration -> families/children/registrations -> staffing
    -> close registration -> start session. Returns a context dict."""
    program = create_program(**(program_overrides or {}))
    classroom = create_classroom(program["id"], capacity=capacity)
    days = make_days(program["id"], n_days, start_date=program["start_date"])
    open_registration(program["id"])

    families, children, registrations = [], [], []
    if one_family:
        family, kids = setup_family_with_children(
            count=child_count, special_needs=special_needs
        )
        families = [family]
        children = kids
    else:
        for _ in range(child_count):
            family, kids = setup_family_with_children(
                count=1, special_needs=special_needs
            )
            families.append(family)
            children.extend(kids)
    for child in children:
        fam = families[0] if one_family else next(
            f for f in families if f["id"] == child["family_id"]
        )
        registrations.append(register_child(child["id"], classroom["id"], fam["id"]))

    volunteers = []
    if staff:
        volunteers = staff_classroom_adequate(program["id"], classroom["id"])

    close_registration(program["id"])
    start_session(program["id"])
    return {
        "program": get_program(program["id"]),
        "classroom": get_classroom(classroom["id"]),
        "days": days,
        "families": families,
        "children": children,
        "registrations": registrations,
        "volunteers": volunteers,
    }


def run_program_day(day, attending_child_ids, checkout_time="11:00:00"):
    """Open one day, check every attending child in and out, then close it.

    attending_child_ids: iterable of child ids. Checkouts run at
    `checkout_time` on the day's date (before the 12:00 default cutoff).
    """
    open_day_with_clock(day)
    records = {
        cid: check_in_child(cid, day["id"]) for cid in attending_child_ids
    }
    if attending_child_ids:
        set_clock(f"{day['date']}T{checkout_time}Z")
        for cid, record in records.items():
            check_out_child(cid, day["id"], record["tag_code"])
    close_day(day["id"])
    return records


def run_session_days(ctx, attendance_by_day, checkout_time="11:00:00"):
    """Run each day of the session; attendance_by_day[i] lists the child ids
    attending ctx['days'][i]. Days missing from the list are left untouched."""
    for day, attendees in zip(ctx["days"], attendance_by_day):
        run_program_day(day, list(attendees), checkout_time=checkout_time)


def complete_program_and_generate(ctx, force=None) -> dict:
    """Complete the program (every day must be CLOSED) and generate the
    retention list (PRD §3.8)."""
    complete_program(ctx["program"]["id"])
    return generate_retention(ctx["program"]["id"], force=force)


def list_attendance_for(child_id=None, program_day_id=None) -> list:
    params = {}
    if child_id:
        params["child_id"] = child_id
    if program_day_id:
        params["program_day_id"] = program_day_id
    resp = api_client.list_attendance(_DIRECTOR, params=params)
    return get_success_data(resp)


def list_security_tags_for(child_id=None, program_day_id=None, status=None) -> list:
    params = {}
    if child_id:
        params["child_id"] = child_id
    if program_day_id:
        params["program_day_id"] = program_day_id
    if status:
        params["status"] = status
    resp = api_client.list_security_tags(_DESK, params=params)
    return get_success_data(resp)
