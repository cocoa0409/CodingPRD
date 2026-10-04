"""Assignment and caseload: the CERTIFIED gate, the caseload cap boundary,
the neutrality-versus-caseload precedence pair, the conserved-caseload
invariant, and the optimistic concurrency guard on assignment."""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    assign_payload,
    assign_case,
    create_assigned_case,
    create_case,
    create_certified_ombudsman,
    create_employer,
    create_member,
    create_ombudsman,
    fill_caseload,
    make_service_member_headers,
    open_round,
    read_case,
    read_employer,
    read_ombudsman,
    resolve_case_informally,
    set_clock,
    setup_basic_world,
    transition_case,
    triage_case,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_OMBUDSMAN_ID = "00000000-0000-4000-8000-000000000009"


def test_assign_trainee_returns_ombudsman_not_certified(api: ApiClient, coordinator_headers: dict):
    """PRD §3.3: "The state gate comes first: the target ombudsman must exist and be currently `CERTIFIED` once lazy expiry has been applied, failing with `ERR_OMBUDSMAN_NOT_CERTIFIED` — a volunteer `ON_LEAVE` keeps existing assignments but fails this gate for any new one."
    PRD §3.1: "Volunteer ombudsmen likewise self-register as `Anonymous` callers, supplying `full_name`, `email`, and optionally an `employer_affiliation_id`; a new volunteer begins life in `TRAINEE` status."

    Design: Difficulty/cross_entity_state_dependency/assign_requires_ombudsman_certified
    """
    world = setup_basic_world(api)
    case = triage_case(api, create_case(api, world["member"]["id"], world["employer"]["id"])["id"])
    trainee = create_ombudsman(api, full_name="Un Trained", email="un@example.com")
    assert trainee["status"] == "TRAINEE"

    response = api.assign_case(case["id"], assign_payload(trainee["id"], case["version"]), coordinator_headers)
    validate_error(response, ApiErrorId.ERR_OMBUDSMAN_NOT_CERTIFIED)

    after = read_case(api, case["id"])
    assert after["status"] == "TRIAGE"
    assert after["assigned_ombudsman_id"] is None


def test_assign_expired_ombudsman_returns_ombudsman_not_certified(api: ApiClient, coordinator_headers: dict):
    """PRD §3.3: "The state gate comes first: the target ombudsman must exist and be currently `CERTIFIED` once lazy expiry has been applied, failing with `ERR_OMBUDSMAN_NOT_CERTIFIED`"
    PRD §2.4: "An ombudsman's certification flips from `CERTIFIED` to `EXPIRED` only when the logical clock is strictly later than `certification_expires_on`; at the exact expiry instant the volunteer is still `CERTIFIED`."

    Design: Difficulty/cross_entity_state_dependency/assign_requires_ombudsman_certified
    """
    world = setup_basic_world(api)
    case = triage_case(api, create_case(api, world["member"]["id"], world["employer"]["id"])["id"])

    set_clock(api, "2028-10-01T00:00:00Z")
    lapsed = read_ombudsman(api, world["ombudsman"]["id"])
    assert lapsed["status"] == "EXPIRED", "certified 2026-09-01 + 24 months lapses once the clock passes 2028-09-01"

    response = api.assign_case(case["id"], assign_payload(world["ombudsman"]["id"], case["version"]), coordinator_headers)
    validate_error(response, ApiErrorId.ERR_OMBUDSMAN_NOT_CERTIFIED)

    after = read_case(api, case["id"])
    assert after["status"] == "TRIAGE"
    assert after["assigned_ombudsman_id"] is None


def _setup_conflicted_full_ombudsman(api: ApiClient) -> dict:
    """Ombudsman affiliated with the first employer, certified, and already
    carrying four active cases against the second employer; a fifth TRIAGE
    case sits against the affiliated employer."""
    set_clock(api)
    employer = create_employer(api)
    other = create_employer(api, legal_name="Heartland Freight LLC", sector="LOGISTICS", size_tier="LARGE")
    ombudsman = create_certified_ombudsman(
        api, full_name="Gil Noar", email="gil@example.com", employer_affiliation_id=employer["id"]
    )
    fill_caseload(api, other["id"], ombudsman["id"], count=4)
    member = create_member(api, full_name="M Five", email="m5@example.com",
                           branch="ARMY", component="ARMY_GUARD")
    case = create_case(api, member["id"], employer["id"], issue_type="RETALIATION",
                       description="Conflict-case against the ombudsman's own employer")
    case = triage_case(api, case["id"])
    return {"employer": employer, "other": other, "ombudsman": ombudsman, "case": case}


def test_assign_conflicted_and_full_ombudsman_conflict_wins(api: ApiClient, coordinator_headers: dict):
    """PRD §3.3: "Then the neutrality screen of §2.8 rejects an ombudsman whose `employer_affiliation_id` equals the case's employer with `ERR_CONFLICT_OF_INTEREST`. Last, the caseload cap: an ombudsman's `active_caseload` counts that volunteer's cases in `ASSIGNED`, `IN_MEDIATION`, `AWAITING_RESPONSE`, or `ESCALATION_PENDING` status, and assignment to a volunteer whose caseload has reached 4 is rejected with `ERR_CASELOAD_FULL` — exactly 4 blocks."
    PRD §2.7: "Every request is validated against the following categories in a fixed order, and when several violations coincide the earliest category determines the response."

    Design: Difficulty/priority_pair_validation_conflict/assign_conflicted_and_full_ombudsman_safety_wins
    """
    world = _setup_conflicted_full_ombudsman(api)
    response = api.assign_case(
        world["case"]["id"], assign_payload(world["ombudsman"]["id"], world["case"]["version"]), coordinator_headers
    )
    error_data = validate_error(response, ApiErrorId.ERR_CONFLICT_OF_INTEREST)
    assert response.status_code == 409
    assert error_data["error_id"] != "ERR_CASELOAD_FULL", \
        "the integrity screen (eighth) precedes the caseload constraint (tenth)"


def test_assign_conflicted_full_ombudsman_leaves_case_untouched(api: ApiClient, coordinator_headers: dict):
    """PRD §2.8: "Neutrality is a hard precondition of mediation, not a guideline. Every volunteer may declare an `employer_affiliation_id` at signup — a nullable reference to an `Employer` — and an ombudsman whose declared affiliation equals a case's employer may never be assigned to that case; the attempt is rejected with `ERR_CONFLICT_OF_INTEREST` (HTTP 409)."
    PRD §3.3: "an ombudsman's `active_caseload` counts that volunteer's cases in `ASSIGNED`, `IN_MEDIATION`, `AWAITING_RESPONSE`, or `ESCALATION_PENDING` status"

    Design: Difficulty/priority_pair_validation_conflict/assign_conflicted_and_full_ombudsman_safety_wins
    """
    world = _setup_conflicted_full_ombudsman(api)
    assert read_ombudsman(api, world["ombudsman"]["id"])["active_caseload"] == 4, \
        "setup precondition: the ombudsman sits at exactly the caseload cap"

    api.assign_case(
        world["case"]["id"], assign_payload(world["ombudsman"]["id"], world["case"]["version"]), coordinator_headers
    )
    after = read_case(api, world["case"]["id"])
    assert after["status"] == "TRIAGE"
    assert after["assigned_ombudsman_id"] is None
    assert read_ombudsman(api, world["ombudsman"]["id"])["active_caseload"] == 4, "a rejected assign moves nothing"


def test_caseload_exactly_four_blocks_fifth_assign(api: ApiClient, coordinator_headers: dict):
    """PRD §3.3: "Last, the caseload cap: an ombudsman's `active_caseload` counts that volunteer's cases in `ASSIGNED`, `IN_MEDIATION`, `AWAITING_RESPONSE`, or `ESCALATION_PENDING` status, and assignment to a volunteer whose caseload has reached 4 is rejected with `ERR_CASELOAD_FULL` — exactly 4 blocks."

    Design: Difficulty/boundary_precision_check/caseload_exactly_four_blocks_assign
    """
    world = setup_basic_world(api)
    fill_caseload(api, world["employer"]["id"], world["ombudsman"]["id"], count=4)

    member = create_member(api, full_name="C Five", email="c5@example.com",
                           branch="NAVY", component="NAVY_RESERVE")
    case = create_case(api, member["id"], world["employer"]["id"], description="Boundary case 5")
    case = triage_case(api, case["id"])

    response = api.assign_case(case["id"], assign_payload(world["ombudsman"]["id"], case["version"]), coordinator_headers)
    validate_error(response, ApiErrorId.ERR_CASELOAD_FULL)
    assert response.status_code == 409
    assert read_case(api, case["id"])["status"] == "TRIAGE"


def test_caseload_frees_on_withdrawal_and_fifth_assign_succeeds(api: ApiClient, coordinator_headers: dict):
    """PRD §3.7: "From `ASSIGNED` onward it also decrements the assigned ombudsman's caseload and clears the case's `assigned_ombudsman_id`"
    PRD §3.3: "assignment to a volunteer whose caseload has reached 4 is rejected with `ERR_CASELOAD_FULL` — exactly 4 blocks."

    Design: Difficulty/boundary_precision_check/caseload_exactly_four_blocks_assign
    """
    world = setup_basic_world(api)
    assigned = fill_caseload(api, world["employer"]["id"], world["ombudsman"]["id"], count=4)

    member = create_member(api, full_name="C Five", email="c5@example.com",
                           branch="NAVY", component="NAVY_RESERVE")
    case = create_case(api, member["id"], world["employer"]["id"], description="Boundary case 5")
    case = triage_case(api, case["id"])
    blocked = api.assign_case(case["id"], assign_payload(world["ombudsman"]["id"], case["version"]), coordinator_headers)
    validate_error(blocked, ApiErrorId.ERR_CASELOAD_FULL)

    first = assigned[0]
    transition_case(api, first["case"]["id"], "CLOSED_WITHDRAWN", make_service_member_headers(first["member"]["id"]))
    assert read_ombudsman(api, world["ombudsman"]["id"])["active_caseload"] == 3, \
        "the withdrawal released one slot"

    retry = api.assign_case(case["id"], assign_payload(world["ombudsman"]["id"], case["version"]), coordinator_headers)
    reassigned = validate_success(retry)
    assert reassigned["status"] == "ASSIGNED"
    assert reassigned["assigned_ombudsman_id"] == world["ombudsman"]["id"]
    assert read_ombudsman(api, world["ombudsman"]["id"])["active_caseload"] == 4


def test_caseload_conserved_across_assign_and_resolve(api: ApiClient):
    """PRD §3.3: "When assignment succeeds, the case records the `assigned_ombudsman_id`, the case's `version` increments by 1, and the caseload arithmetic follows derivedly: the newly assigned volunteer's `active_caseload` rises by one, and on reassignment the previous volunteer's falls by one."
    PRD §3.4: "acceptance moves the round to `ACCEPTED` with `responded_at` stamped and resolves the case `AWAITING_RESPONSE → RESOLVED_INFORMAL`: the employer's `resolved_case_count` increases by 1 and its `open_case_count` decreases by 1, the assigned ombudsman's caseload drops by 1, and the case's `closed_at` is set to the logical clock."

    Design: Difficulty/compensating_invariant/caseload_conserved_across_assign_and_resolve
    """
    world = setup_basic_world(api)
    ombudsman_id = world["ombudsman"]["id"]
    assert read_ombudsman(api, ombudsman_id)["active_caseload"] == 0

    case = create_assigned_case(api, world["employer"], world["member"], world["ombudsman"])
    assert read_ombudsman(api, ombudsman_id)["active_caseload"] == 1, "assign incremented the derived caseload"

    resolved = resolve_case_informally(api, case["id"], ombudsman_id, employer_id=world["employer"]["id"])
    assert resolved["case"]["status"] == "RESOLVED_INFORMAL"
    assert resolved["round"]["status"] == "ACCEPTED"
    assert read_ombudsman(api, ombudsman_id)["active_caseload"] == 0, "the informal resolution compensated the assign"


def test_caseload_derived_field_matches_live_listing(api: ApiClient, coordinator_headers: dict):
    """PRD §3.3: "Because `active_caseload` is derived at read time from the cases themselves, these shifts need no separate bookkeeping — but they are observable immediately on the ombudsman's record."
    PRD §3.1: "Coordinators and ombudsmen browse the docket through a paginated case listing that can be narrowed by `member_id`, `employer_id`, `assigned_ombudsman_id`, `status`, the employer's `sector`, or `issue_type`."

    Design: Difficulty/compensating_invariant/caseload_conserved_across_assign_and_resolve
    """
    world = setup_basic_world(api)
    ombudsman_id = world["ombudsman"]["id"]
    case = create_assigned_case(api, world["employer"], world["member"], world["ombudsman"])
    resolve_case_informally(api, case["id"], ombudsman_id, employer_id=world["employer"]["id"])

    listing, meta = validate_paginated(
        api.list_cases(coordinator_headers, params={"assigned_ombudsman_id": ombudsman_id, "status": "ASSIGNED"})
    )
    assert listing == [] and meta["total_count"] == 0, \
        "no ASSIGNED rows remain for the ombudsman, matching the derived caseload of 0"
    assert read_ombudsman(api, ombudsman_id)["active_caseload"] == 0

    employer = read_employer(api, world["employer"]["id"])
    assert employer["resolved_case_count"] == 1
    assert employer["open_case_count"] == 0


def test_member_role_cannot_assign_returns_unauthorized(api: ApiClient):
    """PRD §2.7: "Second, role authorization, including transition-level actor rules, failing with `ERR_UNAUTHORIZED_ROLE`."
    PRD §4: the assignment operation is listed with authorized role ProgramCoordinator.

    Design: Corner/validations/member_role_cannot_assign_returns_unauthorized
    """
    world = setup_basic_world(api)
    case = triage_case(api, create_case(api, world["member"]["id"], world["employer"]["id"])["id"])

    response = api.assign_case(
        case["id"],
        assign_payload(world["ombudsman"]["id"], case["version"]),
        make_service_member_headers(world["member"]["id"]),
    )
    error_data = validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    assert response.status_code == 403
    assert error_data["error_id"] != "ERR_OWNERSHIP_VIOLATION", \
        "role authorization (second) is evaluated before ownership (fifth)"
    assert read_case(api, case["id"])["status"] == "TRIAGE"


def test_assign_unknown_ombudsman_beats_state_check(api: ApiClient, coordinator_headers: dict):
    """PRD §2.7: "Fourth, existence: path identifiers are validated left to right, and body foreign keys are validated in the endpoint's declared input order — `member_id` before `employer_id`, and so on — each miss producing the corresponding 404 error."
    PRD §2.7: "Every request is validated against the following categories in a fixed order, and when several violations coincide the earliest category determines the response."

    Design: Corner/validations/assign_unknown_ombudsman_beats_state_check
    """
    world = setup_basic_world(api)
    case = create_case(api, world["member"]["id"], world["employer"]["id"])
    withdrawn = transition_case(
        api, case["id"], "CLOSED_WITHDRAWN", make_service_member_headers(world["member"]["id"])
    )

    response = api.assign_case(
        case["id"], assign_payload(UNKNOWN_OMBUDSMAN_ID, withdrawn["version"]), coordinator_headers
    )
    error_data = validate_error(response, ApiErrorId.ERR_OMBUDSMAN_NOT_FOUND)
    assert response.status_code == 404
    assert error_data["error_id"] != "ERR_INVALID_STATE", \
        "existence (fourth) precedes the state gate (sixth) even on a terminal case"


def test_occ_stale_version_on_assign_returns_412(api: ApiClient, coordinator_headers: dict):
    """PRD §2.6: "The case assignment operation and the eligibility-analysis recording operation each require the client to supply `expected_case_version`, a non-optional field carrying the case `version` the client last observed. If the case's current `version` has advanced beyond that observed value — because another coordinator has assigned the case, or a prior analysis has been recorded against it — the request is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412), forcing the client to re-read the case rather than overwrite work it has not seen."
    PRD §3.3: "A coordinator assigns a triaged case to a volunteer, moving it `TRIAGE → ASSIGNED`, and may later reassign an `ASSIGNED → ASSIGNED` case when coverage changes; reassignment supersedes the prior assignment rather than stacking on it."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_assign_returns_412
    """
    world = setup_basic_world(api)
    ombudsman_id = world["ombudsman"]["id"]
    case = triage_case(api, create_case(api, world["member"]["id"], world["employer"]["id"])["id"])
    assert case["version"] == 2

    first = api.assign_case(case["id"], assign_payload(ombudsman_id, 2), coordinator_headers)
    validate_success(first)
    assert read_ombudsman(api, ombudsman_id)["active_caseload"] == 1

    replay = api.assign_case(case["id"], assign_payload(ombudsman_id, 2), coordinator_headers)
    validate_error(replay, ApiErrorId.ERR_STALE_CASE_VERSION)
    assert replay.status_code == 412

    fresh = read_case(api, case["id"])
    assert fresh["version"] == 3
    reassign = api.assign_case(case["id"], assign_payload(ombudsman_id, fresh["version"]), coordinator_headers)
    validate_success(reassign)
    assert read_ombudsman(api, ombudsman_id)["active_caseload"] == 1, \
        "reassignment to the same ombudsman nets zero on the derived caseload"
