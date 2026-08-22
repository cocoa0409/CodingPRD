"""Grievance intake: server-minted fields, referential bars and the filing window."""

from test_helpers import (
    ApiErrorId,
    assert_grievance,
    assert_instant,
    create_bargaining_unit,
    create_contract_clause,
    create_employee,
    file_grievance,
    grievance_payload,
    hold_step,
    schedule_step,
    set_clock,
    setup_base,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_intake_mints_the_case_number_and_stamps_the_filing_steward(api):
    """PRD §3.2: "Its `case_number` is minted as the literal prefix `GR-`, then the
    agreement's `local_number`, then another hyphen, then a four-digit zero-padded ordinal
    counting this grievance's position among the grievances of that same unit in ascending
    `created_at` order, starting at `0001`."
    PRD §3.2: "Its `filed_at` records the clock's current instant, and
    `filed_by_steward_employee_id` records the `X-User-ID` of the filing steward — the
    value that every later union-side act on this case is checked against."

    Design: Corner/entities/grievance_system_fields_are_server_minted_and_ignore_client_input
    """
    ctx = setup_base()

    grievance = validate_success(
        api.create_grievance(
            grievance_payload(
                ctx["unit"]["id"], ctx["grievant"]["id"], ctx["supervisor"]["id"],
                ctx["clause"]["id"],
                statement="Suspension without just cause",
                remedy_requested_cents=200_000,
                back_pay_hours_claimed=24,
            ),
            ctx["steward_headers"],
        ),
        201,
    )
    assert_grievance(grievance)

    assert grievance["case_number"] == "GR-L2100-0001"
    assert_instant(grievance["filed_at"], "2026-08-01T00:00:00Z", "filed_at")
    assert grievance["filed_by_steward_employee_id"] == ctx["steward"]["id"]
    assert grievance["version"] == 1


def test_intake_initialises_the_procedural_and_cost_posture(api):
    """PRD §3.2: "Its `current_step` starts at 1 and only ever reads 1, 2 or 3; its
    `status` starts at `FILED`; its `timeliness_state` starts at `TIMELY`; its
    `settled_amount_cents` starts at 0; and `consolidated_into_id` starts null."
    PRD §3.3: "From those, `appeal_deadline_at` is the latest step's resolution instant
    plus the agreement's `appeal_window_days`, and is null while no step is resolved;
    `arbitration_deadline_at` is the step-3 record's resolution instant plus the
    agreement's `arbitration_demand_days`, and is null unless `current_step` is 3 and that
    step is resolved."

    Design: Corner/entities/grievance_system_fields_are_server_minted_and_ignore_client_input
    """
    ctx = setup_base()
    grievance = file_grievance(ctx)

    assert grievance["current_step"] == 1
    assert grievance["status"] == "FILED"
    assert grievance["timeliness_state"] == "TIMELY"
    assert grievance["settled_amount_cents"] == 0
    assert grievance["consolidated_into_id"] is None
    assert grievance["appeal_deadline_at"] is None
    assert grievance["arbitration_deadline_at"] is None
    assert grievance["total_cost_cents"] == 0
    assert grievance["union_cost_share_cents"] == 0
    assert grievance["employer_cost_share_cents"] == 0
    assert grievance["cost_posture"] == "COST_OK"


def test_intake_without_the_cited_clause_is_rejected(api, analyst_headers):
    """PRD §3.2: "The intake payload names the agreement it is filed under through
    `bargaining_unit_id`, the aggrieved member through `grievant_id`, the supervisor whose
    action is grieved through `respondent_supervisor_id`, and the contract clause alleged
    to have been violated through `clause_id`."
    PRD §2.10: "The request body conforms to the operation's input schema — otherwise
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/grievance_intake_missing_required_field_returns_invalid_request
    """
    ctx = setup_base()
    payload = grievance_payload(
        ctx["unit"]["id"], ctx["grievant"]["id"], ctx["supervisor"]["id"], ctx["clause"]["id"],
        statement="Missing the clause reference",
    )
    payload.pop("clause_id")

    response = api.create_grievance(payload, ctx["steward_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    _, meta = validate_paginated(
        api.list_grievances(analyst_headers, params={"bargaining_unit_id": ctx["unit"]["id"]})
    )
    assert meta["total_count"] == 0


def test_grievance_listing_orders_by_created_at_and_paginates(api, analyst_headers):
    """PRD §2.3: "- Grievances: ascending `created_at`, then ascending `case_number`."
    PRD §2.3: "Both are echoed back in the `meta` object of the response envelope
    alongside `total_count` (the number of rows matching the filters before pagination is
    applied) and `has_more` (true when rows remain beyond the current page)."

    Design: Corner/entities/grievance_list_filters_by_status_and_paginates
    """
    ctx = setup_base()
    file_grievance(ctx, statement="First")
    second = file_grievance(ctx, statement="Second")
    file_grievance(ctx, statement="Third")
    validate_success(
        api.withdraw_grievance(
            second["id"], {"reason": "Grievant withdrew the complaint"}, ctx["steward_headers"]
        ),
        200,
    )

    page_one, meta_one = validate_paginated(
        api.list_grievances(
            analyst_headers,
            params={"bargaining_unit_id": ctx["unit"]["id"], "limit": 2, "offset": 0},
        )
    )
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert [row["case_number"] for row in page_one] == ["GR-L2100-0001", "GR-L2100-0002"]

    page_two, meta_two = validate_paginated(
        api.list_grievances(
            analyst_headers,
            params={"bargaining_unit_id": ctx["unit"]["id"], "limit": 2, "offset": 2},
        )
    )
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False
    assert [row["case_number"] for row in page_two] == ["GR-L2100-0003"]


def test_grievance_listing_filters_by_status_and_the_unit_drops_the_withdrawn_case(
    api, analyst_headers
):
    """PRD §3.2: "Grievances may be listed with filters that cover every foreign key on the
    record — `bargaining_unit_id`, `grievant_id`, `respondent_supervisor_id`, `clause_id`
    and the self-referential `consolidated_into_id` — plus `status` and `timeliness_state`."
    PRD §3.1: "A registered agreement reports two derived fields: its `status`, which reads
    `ACTIVE` while the logical clock is before `contract_expiry_date` and `EXPIRED` from
    that instant onward, evaluated afresh at every read and at every write that names the
    unit; and `open_grievance_count`, the number of grievances filed under it whose status
    is not one of `SETTLED`, `WITHDRAWN`, `CONSOLIDATED` or `CLOSED`."

    Design: Corner/entities/grievance_list_filters_by_status_and_paginates
    """
    ctx = setup_base()
    file_grievance(ctx, statement="First")
    second = file_grievance(ctx, statement="Second")
    file_grievance(ctx, statement="Third")
    validate_success(
        api.withdraw_grievance(
            second["id"], {"reason": "Grievant withdrew the complaint"}, ctx["steward_headers"]
        ),
        200,
    )

    rows, meta = validate_paginated(
        api.list_grievances(
            analyst_headers,
            params={"bargaining_unit_id": ctx["unit"]["id"], "status": "WITHDRAWN"},
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == second["id"]

    unit = validate_success(api.get_bargaining_unit(ctx["unit"]["id"], analyst_headers), 200)
    assert unit["open_grievance_count"] == 2


def test_discovery_date_outside_its_range_is_rejected(api, analyst_headers):
    """PRD §3.2: "The dates must be ordered: `incident_date` at or before
    `discovery_date`, and `discovery_date` at or before the logical clock's current
    instant. A discovery that precedes the incident, or one that lies in the future, is
    rejected with `ERR_INVALID_DISCOVERY_DATE`."

    Design: Corner/validations/discovery_date_before_incident_date_rejected
    """
    ctx = setup_base()

    before_incident = api.create_grievance(
        grievance_payload(
            ctx["unit"]["id"], ctx["grievant"]["id"], ctx["supervisor"]["id"], ctx["clause"]["id"],
            statement="Discovered before it happened",
            incident_date="2026-07-10T00:00:00Z",
            discovery_date="2026-07-05T00:00:00Z",
        ),
        ctx["steward_headers"],
    )
    validate_error(before_incident, ApiErrorId.ERR_INVALID_DISCOVERY_DATE.value)

    in_the_future = api.create_grievance(
        grievance_payload(
            ctx["unit"]["id"], ctx["grievant"]["id"], ctx["supervisor"]["id"], ctx["clause"]["id"],
            statement="Discovered in the future",
            incident_date="2026-07-10T00:00:00Z",
            discovery_date="2026-08-02T00:00:00Z",
        ),
        ctx["steward_headers"],
    )
    validate_error(in_the_future, ApiErrorId.ERR_INVALID_DISCOVERY_DATE.value)

    _, meta = validate_paginated(
        api.list_grievances(analyst_headers, params={"bargaining_unit_id": ctx["unit"]["id"]})
    )
    assert meta["total_count"] == 0


def test_cross_unit_grievant_and_cross_unit_clause_are_rejected(api, analyst_headers):
    """PRD §3.2: "The grievant and the respondent supervisor must both belong to the
    bargaining unit named in the body, or the filing is rejected with
    `ERR_UNIT_MEMBERSHIP_MISMATCH`; the cited clause must belong to that same unit, or the
    rejection is `ERR_CLAUSE_UNIT_MISMATCH`; and the agreement itself must derive to
    `ACTIVE`, or the rejection is `ERR_AGREEMENT_EXPIRED`."

    Design: Corner/validations/cross_unit_grievant_and_cross_unit_clause_rejected
    """
    ctx = setup_base()
    other_unit = create_bargaining_unit(name="Transit Local 2200", local_number="L2200")
    other_clause = create_contract_clause(other_unit["id"])
    other_member = create_employee(
        other_unit["id"], full_name="Omar Silva", employee_number="EMP-9",
        hire_date="2020-09-14T00:00:00Z", seniority_date="2020-09-14T00:00:00Z",
        hourly_rate_cents=3_300,
    )

    foreign_grievant = api.create_grievance(
        grievance_payload(
            ctx["unit"]["id"], other_member["id"], ctx["supervisor"]["id"], ctx["clause"]["id"],
            statement="Grievant from another local",
        ),
        ctx["steward_headers"],
    )
    validate_error(foreign_grievant, ApiErrorId.ERR_UNIT_MEMBERSHIP_MISMATCH.value)

    foreign_clause = api.create_grievance(
        grievance_payload(
            ctx["unit"]["id"], ctx["grievant"]["id"], ctx["supervisor"]["id"], other_clause["id"],
            statement="Clause from another local",
        ),
        ctx["steward_headers"],
    )
    validate_error(foreign_clause, ApiErrorId.ERR_CLAUSE_UNIT_MISMATCH.value)

    _, meta = validate_paginated(
        api.list_grievances(analyst_headers, params={"bargaining_unit_id": ctx["unit"]["id"]})
    )
    assert meta["total_count"] == 0


def test_expedited_clause_halves_the_filing_window_with_ceiling_rounding(api):
    """PRD §3.2: "The window begins as the agreement's `filing_window_days`; if the cited
    clause is `expedited`, that figure is halved and rounded up to a whole day, so a
    thirty-day window becomes fifteen days and a twenty-one-day window becomes eleven."

    Design: Corner/calculations/expedited_clause_halves_filing_and_step_windows
    """
    ctx = setup_base(
        clause_overrides={
            "clause_number": "ART-19", "title": "Safety and Health",
            "category": "SAFETY", "expedited": True,
        }
    )

    too_late = api.create_grievance(
        grievance_payload(
            ctx["unit"]["id"], ctx["grievant"]["id"], ctx["supervisor"]["id"], ctx["clause"]["id"],
            statement="Guard removed from press",
            incident_date="2026-07-10T00:00:00Z",
            discovery_date="2026-07-16T00:00:00Z",
        ),
        ctx["steward_headers"],
    )
    validate_error(too_late, ApiErrorId.ERR_GRIEVANCE_UNTIMELY.value)

    inside = validate_success(
        api.create_grievance(
            grievance_payload(
                ctx["unit"]["id"], ctx["grievant"]["id"], ctx["supervisor"]["id"],
                ctx["clause"]["id"],
                statement="Guard removed from press",
                incident_date="2026-07-10T00:00:00Z",
                discovery_date="2026-07-25T00:00:00Z",
            ),
            ctx["steward_headers"],
        ),
        201,
    )
    assert inside["timeliness_state"] == "TIMELY"


def test_expedited_clause_halves_the_step_response_window(api):
    """PRD §3.3: "If the cited clause is `expedited`, that window is halved and rounded
    **up** to a whole day, so ten days become five, fifteen days become eight and twenty
    days become ten."
    PRD §3.3: "The result is added as whole days to `meeting_held_at` — the scheduled
    meeting instant is irrelevant to the deadline, only the instant the meeting was
    recorded as held anchors it."

    Design: Corner/calculations/expedited_clause_halves_filing_and_step_windows
    """
    ctx = setup_base(
        clause_overrides={
            "clause_number": "ART-19", "title": "Safety and Health",
            "category": "SAFETY", "expedited": True,
        }
    )
    ctx["grievance"] = file_grievance(ctx, discovery_date="2026-07-25T00:00:00Z")

    step = schedule_step(ctx["grievance"]["id"], "2026-08-05T00:00:00Z")
    set_clock("2026-08-05T00:00:00Z")
    held = hold_step(step["id"])

    assert held["status"] == "HELD"
    assert_instant(held["response_due_at"], "2026-08-10T00:00:00Z", "response_due_at")

    grievance = validate_success(
        api.get_grievance(ctx["grievance"]["id"], ctx["steward_headers"]), 200
    )
    assert grievance["status"] == "AWAITING_RESPONSE"


def test_filing_on_the_last_day_of_the_window_is_timely(api, analyst_headers):
    """PRD §3.2: "The elapsed time is the number of whole calendar days from
    `discovery_date` to the clock's current instant. The filing is rejected with
    `ERR_GRIEVANCE_UNTIMELY` only when the elapsed days are **strictly greater** than the
    window — filing on exactly the last day of the window is timely."

    Design: Difficulty/boundary_precision_check/filing_window_exact_day_boundary
    """
    ctx = setup_base()

    grievance = validate_success(
        api.create_grievance(
            grievance_payload(
                ctx["unit"]["id"], ctx["grievant"]["id"], ctx["supervisor"]["id"],
                ctx["clause"]["id"],
                statement="Discipline discovered exactly thirty days ago",
                incident_date="2026-06-25T00:00:00Z",
                discovery_date="2026-07-02T00:00:00Z",
            ),
            ctx["steward_headers"],
        ),
        201,
    )

    assert grievance["status"] == "FILED"
    assert grievance["timeliness_state"] == "TIMELY"
    assert grievance["case_number"] == "GR-L2100-0001"

    unit = validate_success(api.get_bargaining_unit(ctx["unit"]["id"], analyst_headers), 200)
    assert unit["open_grievance_count"] == 1


def test_filing_one_day_past_the_window_is_barred_and_persists_nothing(api, analyst_headers):
    """PRD §3.2: "The elapsed time is the number of whole calendar days from
    `discovery_date` to the clock's current instant. The filing is rejected with
    `ERR_GRIEVANCE_UNTIMELY` only when the elapsed days are **strictly greater** than the
    window — filing on exactly the last day of the window is timely."

    Design: Difficulty/boundary_precision_check/filing_window_exact_day_boundary
    """
    ctx = setup_base()

    timely = validate_success(
        api.create_grievance(
            grievance_payload(
                ctx["unit"]["id"], ctx["grievant"]["id"], ctx["supervisor"]["id"],
                ctx["clause"]["id"],
                statement="Discipline discovered exactly thirty days ago",
                incident_date="2026-06-25T00:00:00Z",
                discovery_date="2026-07-02T00:00:00Z",
            ),
            ctx["steward_headers"],
        ),
        201,
    )

    late = api.create_grievance(
        grievance_payload(
            ctx["unit"]["id"], ctx["grievant"]["id"], ctx["supervisor"]["id"], ctx["clause"]["id"],
            statement="Discipline discovered thirty-one days ago",
            incident_date="2026-06-25T00:00:00Z",
            discovery_date="2026-07-01T00:00:00Z",
        ),
        ctx["steward_headers"],
    )
    validate_error(late, ApiErrorId.ERR_GRIEVANCE_UNTIMELY.value)

    rows, meta = validate_paginated(
        api.list_grievances(analyst_headers, params={"bargaining_unit_id": ctx["unit"]["id"]})
    )
    assert meta["total_count"] == 1, "the refused intake must persist nothing"
    assert rows[0]["id"] == timely["id"]


def test_intake_is_accepted_while_the_agreement_is_still_in_force(api, director_headers):
    """PRD §3.1: "A registered agreement reports two derived fields: its `status`, which
    reads `ACTIVE` while the logical clock is before `contract_expiry_date` and `EXPIRED`
    from that instant onward, evaluated afresh at every read and at every write that names
    the unit; and `open_grievance_count`, the number of grievances filed under it whose
    status is not one of `SETTLED`, `WITHDRAWN`, `CONSOLIDATED` or `CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/grievance_intake_blocked_by_expired_agreement
    """
    ctx = setup_base(unit_overrides={"contract_expiry_date": "2026-08-20T00:00:00Z"})
    set_clock("2026-08-19T00:00:00Z")

    grievance = validate_success(
        api.create_grievance(
            grievance_payload(
                ctx["unit"]["id"], ctx["grievant"]["id"], ctx["supervisor"]["id"],
                ctx["clause"]["id"],
                statement="Filed one day before contract expiry",
                incident_date="2026-08-14T00:00:00Z",
                discovery_date="2026-08-15T00:00:00Z",
            ),
            ctx["steward_headers"],
        ),
        201,
    )
    assert grievance["status"] == "FILED"

    unit = validate_success(api.get_bargaining_unit(ctx["unit"]["id"], director_headers), 200)
    assert unit["status"] == "ACTIVE"


def test_intake_is_blocked_once_the_agreement_derives_to_expired(api, director_headers, analyst_headers):
    """PRD §3.1: "An agreement that has derived to `EXPIRED` cannot be the subject of new
    procedural activity, and the four acts guarded by that rule are rejected with
    `ERR_AGREEMENT_EXPIRED`."
    PRD §3.2: "The grievant and the respondent supervisor must both belong to the
    bargaining unit named in the body, or the filing is rejected with
    `ERR_UNIT_MEMBERSHIP_MISMATCH`; the cited clause must belong to that same unit, or the
    rejection is `ERR_CLAUSE_UNIT_MISMATCH`; and the agreement itself must derive to
    `ACTIVE`, or the rejection is `ERR_AGREEMENT_EXPIRED`."

    Design: Difficulty/cross_entity_state_dependency/grievance_intake_blocked_by_expired_agreement
    """
    ctx = setup_base(unit_overrides={"contract_expiry_date": "2026-08-20T00:00:00Z"})
    set_clock("2026-08-19T00:00:00Z")
    intake = grievance_payload(
        ctx["unit"]["id"], ctx["grievant"]["id"], ctx["supervisor"]["id"], ctx["clause"]["id"],
        statement="Filed one day before contract expiry",
        incident_date="2026-08-14T00:00:00Z",
        discovery_date="2026-08-15T00:00:00Z",
    )
    validate_success(api.create_grievance(intake, ctx["steward_headers"]), 201)

    set_clock("2026-08-21T00:00:00Z")
    blocked = api.create_grievance(intake, ctx["steward_headers"])
    validate_error(blocked, ApiErrorId.ERR_AGREEMENT_EXPIRED.value)

    unit = validate_success(api.get_bargaining_unit(ctx["unit"]["id"], director_headers), 200)
    assert unit["status"] == "EXPIRED"

    _, meta = validate_paginated(
        api.list_grievances(analyst_headers, params={"bargaining_unit_id": ctx["unit"]["id"]})
    )
    assert meta["total_count"] == 1
