"""Composite setup helpers.

Every fixture builds its preconditions from scratch through the PRD-declared
endpoints, because the harness restarts the server (and therefore empties the
database) before every individual test.  Setup calls use the lenient
`get_success_data` validator so a broken precondition surfaces as a clear
"Setup failed" message rather than a confusing assertion error.
"""
from .api_client import api_client
from .test_users import TEST_USERS, make_client_headers
from .constants import TEST_DEFAULTS, IRS_VOLUNTEER_HOUR_RATE_CENTS
from .factories import (
    create_funder_payload,
    create_program_payload,
    create_grant_payload,
    create_client_payload,
    create_intake_assessment_payload,
    create_eligibility_screen_payload,
    create_enrollment_payload,
    create_service_authorization_payload,
    create_service_delivery_payload,
    create_in_kind_donation_payload,
    create_outcome_report_payload,
)
from prd_bench_local_runner.testing import get_success_data

INTAKE = TEST_USERS["intake_specialist_headers"]
PROGRAM = TEST_USERS["program_manager_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]

DEFAULT_CLOCK = "2026-09-01T00:00:00Z"


def _setup(response, what):
    assert response.status_code < 300, (
        f"Setup failed: {what} returned {response.status_code}: {response.text}"
    )
    return get_success_data(response)


# --------------------------------------------------------------------------
# Tier 0 — primitives
# --------------------------------------------------------------------------

def set_clock(to_iso8601: str = DEFAULT_CLOCK) -> dict:
    """Drive the agency logical clock to a supplied instant."""
    return _setup(
        api_client.set_current_utc({"to_iso8601": to_iso8601}, ADMIN), "set_current_utc"
    )


def create_funder(**overrides) -> dict:
    return _setup(api_client.create_funder(create_funder_payload(**overrides), COMPLIANCE),
                  "create_funder")


def create_program(**overrides) -> dict:
    return _setup(api_client.create_program(create_program_payload(**overrides), COMPLIANCE),
                  "create_program")


def create_grant(funder_id, program_id, **overrides) -> dict:
    payload = create_grant_payload(funder_id, program_id, **overrides)
    return _setup(api_client.create_grant(payload, FINANCE), "create_grant")


def create_client(**overrides) -> dict:
    return _setup(api_client.create_client(create_client_payload(**overrides), INTAKE),
                  "create_client")


def open_assessment(client_id, **overrides) -> dict:
    payload = create_intake_assessment_payload(**overrides)
    return _setup(
        api_client.create_intake_assessment(client_id, payload, INTAKE),
        "create_intake_assessment",
    )


def open_screen(assessment_id, program_id, grant_id, **overrides) -> dict:
    payload = create_eligibility_screen_payload(program_id, grant_id, **overrides)
    return _setup(
        api_client.create_eligibility_screen(assessment_id, payload, INTAKE),
        "create_eligibility_screen",
    )


def verify_screen(screen_id, determination: str = "ELIGIBLE") -> dict:
    """Fire the verification hop: verification_state UNVERIFIED -> VERIFIED
    while the determination dimension is left untouched.

    PRD §3.4: "the operation always performs the verification hop first", and
    the branch that follows is "chosen by the `determination` value the reviewer
    supplies" — a value the PRD declares as `ELIGIBLE` or `INELIGIBLE` only, so
    the payload never carries `PENDING`.  The hop is fired while the parent
    assessment is still being assembled (routing itself requires an
    already-VERIFIED screen, §3.3), so the branch that follows is refused — with
    `ERR_INTAKE_NOT_ROUTED` for an unrouted parent, or with whatever later-tier
    refusal the screen's own state trips — and the hop's state change is what
    persists.
    """
    response = api_client.determine_eligibility_screen(
        screen_id, {"determination": determination}, COMPLIANCE
    )
    if response.status_code >= 300:
        assert response.status_code < 500, (
            f"Setup failed: determine (verification hop) returned "
            f"{response.status_code}: {response.text}"
        )
    screen = refresh_screen(screen_id)
    assert screen["verification_state"] == "VERIFIED", (
        "the verification hop must persist even when the determination branch "
        "that follows it is refused"
    )
    return screen


def submit_assessment(assessment_id) -> dict:
    return _setup(api_client.submit_intake_assessment(assessment_id, INTAKE),
                  "submit_intake_assessment")


def route_assessment(assessment_id) -> dict:
    return _setup(api_client.route_intake_assessment(assessment_id, INTAKE),
                  "route_intake_assessment")


def determine_screen(screen_id, determination: str, denial_reason_code=None) -> dict:
    payload = {"determination": determination}
    if denial_reason_code is not None:
        payload["denial_reason_code"] = denial_reason_code
    return _setup(
        api_client.determine_eligibility_screen(screen_id, payload, COMPLIANCE),
        "determine_eligibility_screen",
    )


def find_enrollment(client_id, program_id) -> dict:
    data = _setup(
        api_client.list_enrollments(PROGRAM, {"client_id": client_id, "program_id": program_id}),
        "list_enrollments",
    )
    assert data, f"Setup failed: no enrollment for client {client_id} in program {program_id}"
    return data[0]


def activate_enrollment(enrollment_id) -> dict:
    return _setup(api_client.activate_enrollment(enrollment_id, PROGRAM), "activate_enrollment")


def authorize_units(enrollment_id, grant_id, expected_enrollment_version, **overrides) -> dict:
    payload = create_service_authorization_payload(
        enrollment_id, grant_id, expected_enrollment_version, **overrides
    )
    return _setup(
        api_client.create_service_authorization(payload, PROGRAM), "create_service_authorization"
    )


def record_delivery(authorization_id, grant_id, client_id,
                    expected_service_authorization_version, **overrides) -> dict:
    payload = create_service_delivery_payload(
        authorization_id, grant_id, client_id, expected_service_authorization_version,
        **overrides,
    )
    return _setup(
        api_client.create_service_delivery(payload, PROGRAM), "create_service_delivery"
    )


def document_delivery(delivery_id) -> dict:
    return _setup(api_client.document_service_delivery(delivery_id, PROGRAM),
                  "document_service_delivery")


def bill_delivery(delivery_id) -> dict:
    return _setup(api_client.bill_service_delivery(delivery_id, FINANCE),
                  "bill_service_delivery")


def void_delivery(delivery_id) -> dict:
    return _setup(api_client.void_service_delivery(delivery_id, FINANCE),
                  "void_service_delivery")


def record_in_kind(grant_id, **overrides) -> dict:
    payload = create_in_kind_donation_payload(grant_id, **overrides)
    return _setup(api_client.create_in_kind_donation(payload, PROGRAM), "create_in_kind_donation")


def open_outcome_report(grant_id, **overrides) -> dict:
    payload = create_outcome_report_payload(grant_id, **overrides)
    return _setup(api_client.create_outcome_report(payload, PROGRAM), "create_outcome_report")


# --------------------------------------------------------------------------
# Tier 1 — state progression: walk a screen to ELIGIBLE and the enrollment live
# --------------------------------------------------------------------------

def setup_landscape(funder=None, program=None, grants=None, clock=DEFAULT_CLOCK):
    """Create a funder, one program and one or more grants. Returns a context
    dict with keys `funder`, `program`, `grants` (list) and the flat aliases
    `grant`, `grant2`."""
    set_clock(clock)
    funder = create_funder(**(funder or {}))
    program = create_program(**(program or {}))
    specs = grants if grants is not None else [{}]
    made = []
    for spec in specs:
        made.append(create_grant(funder["id"], program["id"], **spec))
    ctx = {"funder": funder, "program": program, "grants": made, "grant": made[0]}
    if len(made) > 1:
        ctx["grant2"] = made[1]
    return ctx


def walk_screen_to_eligible(client_id, program_id, grant_id,
                            screen_overrides=None, assessment_overrides=None,
                            determine=True):
    """Open an assessment and a screen, run the verification hop, submit and
    route the assessment, then (by default) record the ELIGIBLE determination.

    Returns a context dict with `client`, `assessment`, `screen` and, when the
    determination ran, `enrollment`.
    """
    assessment = open_assessment(client_id, **(assessment_overrides or {}))
    screen = open_screen(assessment["id"], program_id, grant_id, **(screen_overrides or {}))
    verify_screen(screen["id"])
    submit_assessment(assessment["id"])
    route_assessment(assessment["id"])
    ctx = {"assessment": assessment, "screen": screen}
    if determine:
        determine_screen(screen["id"], "ELIGIBLE")
        ctx["enrollment"] = find_enrollment(client_id, program_id)
    return ctx


def setup_active_enrollment(program_overrides=None, grant_overrides=None,
                            client_overrides=None, screen_overrides=None,
                            funder_overrides=None, clock=DEFAULT_CLOCK,
                            authorize=False, authorization_overrides=None):
    """The canonical composite: funder + program + grant + client + assessment +
    verified screen + ROUTED assessment + ELIGIBLE determination + ACTIVE
    enrollment, optionally with an ACTIVE service authorization.

    Returns a context dict keyed by entity name.
    """
    landscape = setup_landscape(funder=funder_overrides, program=program_overrides,
                                grants=[grant_overrides or {}], clock=clock)
    client = create_client(**(client_overrides or {}))
    walked = walk_screen_to_eligible(
        client["id"], landscape["program"]["id"], landscape["grant"]["id"],
        screen_overrides=screen_overrides,
    )
    enrollment = walked["enrollment"]
    activated = activate_enrollment(enrollment["id"])
    ctx = dict(landscape)
    ctx.update({
        "client": client,
        "assessment": walked["assessment"],
        "screen": walked["screen"],
        "enrollment": activated,
    })
    if authorize:
        authorization = authorize_units(
            activated["id"], landscape["grant"]["id"], activated["version"],
            **(authorization_overrides or {}),
        )
        ctx["authorization"] = authorization
    return ctx


def setup_draft_delivery(units_delivered=1, unit_rate_cents=None, service_date=None,
                         grant_key="grant", **setup_kwargs):
    """Active enrollment + ACTIVE authorization + one DRAFT delivery."""
    ctx = setup_active_enrollment(authorize=True, **setup_kwargs)
    overrides = {
        "units_delivered": units_delivered,
        "unit_rate_cents": unit_rate_cents or TEST_DEFAULTS["UNIT_RATE_CENTS"],
    }
    if service_date is not None:
        overrides["service_date"] = service_date
    ctx["delivery"] = record_delivery(
        ctx["authorization"]["id"], ctx[grant_key]["id"], ctx["client"]["id"],
        ctx["authorization"]["version"], **overrides,
    )
    return ctx


def setup_documented_delivery(units_delivered=1, unit_rate_cents=None,
                              service_date=None, grant_key="grant", **setup_kwargs):
    ctx = setup_draft_delivery(units_delivered=units_delivered,
                               unit_rate_cents=unit_rate_cents,
                               service_date=service_date, grant_key=grant_key,
                               **setup_kwargs)
    ctx["delivery"] = document_delivery(ctx["delivery"]["id"])
    return ctx


def setup_billed_delivery(units_delivered=1, unit_rate_cents=None,
                          service_date=None, grant_key="grant", **setup_kwargs):
    ctx = setup_documented_delivery(units_delivered=units_delivered,
                                    unit_rate_cents=unit_rate_cents,
                                    service_date=service_date, grant_key=grant_key,
                                    **setup_kwargs)
    ctx["delivery"] = bill_delivery(ctx["delivery"]["id"])
    return ctx


def setup_frozen_grant(units_delivered=1, unit_rate_cents=None, **setup_kwargs):
    """Document a delivery large enough to drive the governing grant to FROZEN,
    suspending the enrollment that produced it. Returns the pipeline context
    with `grant`, `enrollment`, `authorization` and `delivery` refreshed."""
    ctx = setup_documented_delivery(units_delivered=units_delivered,
                                    unit_rate_cents=unit_rate_cents, **setup_kwargs)
    ctx["grant"] = _setup(api_client.get_grant(ctx["grant"]["id"], FINANCE), "get_grant")
    ctx["enrollment"] = _setup(
        api_client.get_enrollment(ctx["enrollment"]["id"], PROGRAM), "get_enrollment"
    )
    ctx["authorization"] = _setup(
        api_client.get_service_authorization(ctx["authorization"]["id"], PROGRAM),
        "get_service_authorization",
    )
    return ctx


def refresh_grant(ctx, key="grant") -> dict:
    return _setup(api_client.get_grant(ctx[key]["id"], FINANCE), "get_grant")


def refresh_delivery(ctx, key="delivery") -> dict:
    return _setup(api_client.get_service_delivery(ctx[key]["id"], FINANCE),
                  "get_service_delivery")


def refresh_screen(screen_id) -> dict:
    return _setup(api_client.get_eligibility_screen(screen_id, COMPLIANCE),
                  "get_eligibility_screen")


def refresh_authorization(authorization_id) -> dict:
    """Re-read an authorization. PRD §3.6: recording a delivery "increments the
    authorization's `version` by one", so a caller that records several
    deliveries against one authorization must re-read it to obtain the current
    `expected_service_authorization_version`."""
    return _setup(api_client.get_service_authorization(authorization_id, PROGRAM),
                  "get_service_authorization")


def delivery_lines(delivery_id) -> list:
    return _setup(
        api_client.list_cost_allocations(FINANCE, {"service_delivery_id": delivery_id}),
        "list_cost_allocations",
    )


def grant_lines(grant_id) -> list:
    return _setup(api_client.list_cost_allocations(FINANCE, {"grant_id": grant_id}),
                  "list_cost_allocations")


def list_enrollments_for(client_id) -> list:
    return _setup(api_client.list_enrollments(PROGRAM, {"client_id": client_id}),
                  "list_enrollments")


def list_deliveries_for_authorization(authorization_id) -> list:
    return _setup(
        api_client.list_service_deliveries(PROGRAM, {"service_authorization_id": authorization_id}),
        "list_service_deliveries",
    )


def list_authorizations_for(enrollment_id) -> list:
    return _setup(
        api_client.list_service_authorizations(PROGRAM, {"enrollment_id": enrollment_id}),
        "list_service_authorizations",
    )


# --------------------------------------------------------------------------
# Tier 2 — entity hierarchy and multi-client capacity scenarios
# --------------------------------------------------------------------------

def walk_screen_to_routed(client_id, program_id, grant_id, verify=True,
                          screen_overrides=None, assessment_overrides=None):
    """Assessment ROUTED with one screen at determination PENDING; the screen's
    verification dimension is VERIFIED when `verify` is true."""
    assessment = open_assessment(client_id, **(assessment_overrides or {}))
    screen = open_screen(assessment["id"], program_id, grant_id, **(screen_overrides or {}))
    if verify:
        verify_screen(screen["id"])
    submit_assessment(assessment["id"])
    route_assessment(assessment["id"])
    return {"assessment": assessment, "screen": screen}


def setup_capacity_pair(capacity_slots=1, first_activate=True,
                        second_verify=True, second_route=True, second_submit=True,
                        first_client_overrides=None, second_client_overrides=None,
                        program_overrides=None, grant_overrides=None,
                        clock=DEFAULT_CLOCK, clock_after=None):
    """Client One consumes the program's slot(s); Client Two is left one step
    short of its own determination.

    Returns a context with `program`, `grant`, `client_one`, `client_two`,
    `enrollment` (Client One's), `assessment_two` and `screen_two`.
    """
    prog = {"capacity_slots": capacity_slots}
    prog.update(program_overrides or {})
    landscape = setup_landscape(program=prog, grants=[grant_overrides or {}], clock=clock)

    client_one = create_client(full_name="Client One", **(first_client_overrides or {}))
    walked_one = walk_screen_to_eligible(
        client_one["id"], landscape["program"]["id"], landscape["grant"]["id"]
    )
    enrollment = walked_one["enrollment"]
    if first_activate:
        enrollment = activate_enrollment(enrollment["id"])

    client_two = create_client(full_name="Client Two", **(second_client_overrides or {}))
    assessment_two = open_assessment(client_two["id"])
    screen_two = open_screen(assessment_two["id"], landscape["program"]["id"],
                             landscape["grant"]["id"])
    if second_verify:
        verify_screen(screen_two["id"])
    if second_submit:
        submit_assessment(assessment_two["id"])
    if second_route:
        route_assessment(assessment_two["id"])
    if clock_after is not None:
        set_clock(clock_after)

    ctx = dict(landscape)
    ctx.update({
        "client_one": client_one,
        "client_two": client_two,
        "enrollment": enrollment,
        "assessment_one": walked_one["assessment"],
        "screen_one": walked_one["screen"],
        "assessment_two": assessment_two,
        "screen_two": screen_two,
    })
    return ctx


def setup_eligibility_blocked_direct_enrollment(program_overrides=None, grant_overrides=None,
                                                clock=DEFAULT_CLOCK):
    """Client, program and grant exist with no eligibility screen at all."""
    landscape = setup_landscape(program=program_overrides, grants=[grant_overrides or {}],
                                clock=clock)
    client = create_client()
    ctx = dict(landscape)
    ctx["client"] = client
    return ctx


# --------------------------------------------------------------------------
# Tier 3 — braiding scenarios across several grants
# --------------------------------------------------------------------------

def setup_two_grant_braiding(grant_a_overrides, grant_b_overrides, units_delivered,
                             unit_rate_cents, enrollment_grant="grant_a",
                             authorization_grant="grant_b", client_overrides=None,
                             program_overrides=None, funder_overrides=None,
                             clock=DEFAULT_CLOCK, document=False, service_date=None):
    """Two grants on one program, one ACTIVE enrollment funded by `grant_a` and
    one ACTIVE authorization bearing `grant_b`; a DRAFT delivery of the given
    size.  This is the candidate set the braiding waterfall orders."""
    landscape = setup_landscape(
        funder=funder_overrides, program=program_overrides,
        grants=[grant_a_overrides, grant_b_overrides], clock=clock,
    )
    # setup_landscape keys the grants it made by position (`grants[0]` is
    # created first); the two-grant scenarios address them as grant_a/grant_b.
    named_grants = {"grant_a": landscape["grants"][0], "grant_b": landscape["grants"][1]}
    client = create_client(**(client_overrides or {}))
    walked = walk_screen_to_eligible(
        client["id"], landscape["program"]["id"], named_grants[enrollment_grant]["id"]
    )
    enrollment = activate_enrollment(walked["enrollment"]["id"])
    authorization = authorize_units(
        enrollment["id"], named_grants[authorization_grant]["id"], enrollment["version"],
        authorized_units=max(units_delivered, 1), unit_rate_cents=unit_rate_cents,
    )
    delivery_overrides = {"units_delivered": units_delivered,
                          "unit_rate_cents": unit_rate_cents}
    if service_date is not None:
        delivery_overrides["service_date"] = service_date
    delivery = record_delivery(
        authorization["id"], named_grants[authorization_grant]["id"], client["id"],
        authorization["version"], **delivery_overrides,
    )
    if document:
        delivery = document_delivery(delivery["id"])
    ctx = dict(landscape)
    ctx.update({
        "client": client,
        "enrollment": enrollment,
        "authorization": authorization,
        "delivery": delivery,
        "grant_a": landscape["grants"][0],
        "grant_b": landscape["grants"][1],
    })
    return ctx


def setup_same_day_duplicate_deliveries(units_sequence, unit_rate_cents=5000,
                                        authorized_units=30, service_date="2026-09-02T01:00:00Z",
                                        clock="2026-09-02T00:00:00Z", document=True):
    """One ACTIVE enrollment/authorization with several same-day deliveries under
    one service code. Returns the context plus `deliveries` in creation order."""
    landscape = setup_landscape(clock=clock)
    client = create_client()
    walked = walk_screen_to_eligible(
        client["id"], landscape["program"]["id"], landscape["grant"]["id"]
    )
    enrollment = activate_enrollment(walked["enrollment"]["id"])
    authorization = authorize_units(
        enrollment["id"], landscape["grant"]["id"], enrollment["version"],
        authorized_units=authorized_units, unit_rate_cents=unit_rate_cents,
        period_start="2026-09-01T00:00:00Z", period_end="2026-10-01T00:00:00Z",
    )
    deliveries = []
    for index, units in enumerate(units_sequence):
        stamp = service_date.replace("T01:", f"T{index + 1:02d}:")
        current = _setup(
            api_client.get_service_authorization(authorization["id"], PROGRAM),
            "get_service_authorization",
        )
        delivery = record_delivery(
            authorization["id"], landscape["grant"]["id"], client["id"],
            current["version"],
            units_delivered=units, unit_rate_cents=unit_rate_cents, service_date=stamp,
        )
        if document:
            delivery = document_delivery(delivery["id"])
        deliveries.append(delivery)
    ctx = dict(landscape)
    ctx.update({
        "client": client,
        "enrollment": enrollment,
        "authorization": authorization,
        "deliveries": deliveries,
        "delivery": deliveries[0],
    })
    return ctx


def setup_donor_window_scenario(hours_first=40, donor_reference="PARISH-01",
                                grant_overrides=None, program_overrides=None,
                                clock=DEFAULT_CLOCK):
    """A match-eligible grant plus one already-accepted 40-hour donation from a
    single donor_reference on the first day of the window."""
    prog = {"match_eligible": True}
    prog.update(program_overrides or {})
    grants = {"max_in_kind_rate_cents": TEST_DEFAULTS["MAX_IN_KIND_RATE_CENTS"],
              "matching_requirement_pct": 0.25}
    grants.update(grant_overrides or {})
    landscape = setup_landscape(program=prog, grants=[grants], clock=clock)
    donation = record_in_kind(
        landscape["grant"]["id"], donor_reference=donor_reference,
        donation_date=clock, hours=hours_first, valuation_method="APPRAISAL",
        rate_cents=TEST_DEFAULTS["MAX_IN_KIND_RATE_CENTS"],
    )
    ctx = dict(landscape)
    ctx["donation"] = donation
    return ctx


def setup_match_eligible_grant(grant_overrides=None, program_overrides=None,
                               clock=DEFAULT_CLOCK):
    """A grant whose program is match-eligible and whose matching requirement is
    a quarter of a 200000-cent award (50000 cents)."""
    prog = {"match_eligible": True}
    prog.update(program_overrides or {})
    grants = {"total_award_cents": 200_000, "admin_rate_pct": 0.10,
              "max_in_kind_rate_cents": TEST_DEFAULTS["MAX_IN_KIND_RATE_CENTS"],
              "matching_requirement_pct": 0.25,
              "period_start": "2026-01-01T00:00:00Z",
              "period_end": "2027-09-30T00:00:00Z"}
    grants.update(grant_overrides or {})
    return setup_landscape(program=prog, grants=[grants], clock=clock)


def setup_outcome_window(completed_exits=0, window_start="2026-09-01T00:00:00Z",
                         window_end="2026-09-30T00:00:00Z",
                         grant_overrides=None, program_overrides=None,
                         clock="2026-09-02T00:00:00Z"):
    """A grant whose reporting window already holds one documented delivery, with
    an optional COMPLETED exit for the client."""
    prog = {"capacity_slots": 40}
    prog.update(program_overrides or {})
    grants = {"total_award_cents": 500_000, "admin_rate_pct": 0.05,
              "matching_requirement_pct": 0.0,
              "period_start": "2026-01-01T00:00:00Z",
              "period_end": "2027-12-31T00:00:00Z"}
    grants.update(grant_overrides or {})
    ctx = setup_documented_delivery(
        units_delivered=1, unit_rate_cents=5000,
        service_date="2026-09-02T01:00:00Z",
        program_overrides=prog, grant_overrides=grants, clock=clock,
    )
    if completed_exits:
        ctx["enrollment"] = _setup(
            api_client.exit_enrollment(ctx["enrollment"]["id"], {"exit_reason": "COMPLETED"},
                                       PROGRAM),
            "exit_enrollment",
        )
    ctx["report"] = open_outcome_report(
        ctx["grant"]["id"], reporting_period_start=window_start,
        reporting_period_end=window_end, numerator=4, denominator=10,
    )
    return ctx
