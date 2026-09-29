"""Validation corners: uniqueness scopes, ladder priority, temporal and aggregate gates (PRD §2.8, §3.3-§3.7)."""
from test_helpers import *  # noqa: F401,F403

PD_HEADERS = TEST_USERS["program_director_headers"]
SM_HEADERS = TEST_USERS["sourcing_manager_headers"]
CA_HEADERS = TEST_USERS["contract_approver_headers"]
AN_HEADERS = TEST_USERS["sales_ops_analyst_headers"]
TD_HEADERS = TEST_USERS["travel_desk_headers"]


def test_duplicate_employee_code_in_the_same_program_is_rejected():
    """A repeated employee_code inside one program reports ERR_DUPLICATE_EMPLOYEE_CODE.

    PRD §3.2: "the employer-assigned `employee_code` (non-empty, at most 40
    characters, unique within the program — a repeat reports
    `ERR_DUPLICATE_EMPLOYEE_CODE`)"

    Design: Corner/validations/uniqueness_violations_on_employee_code_tier_key_and_milestone_sequence
    """
    program = create_program()
    create_qualifier(program["id"], employee_code="S-1001", full_name="Ana Reyes")

    response = api_client.create_qualifier(
        create_qualifier_payload(
            program["id"], employee_code="S-1001", full_name="Ana Reyes Duplicate"
        ),
        AN_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_EMPLOYEE_CODE)

    rows, meta = validate_paginated(
        api_client.list_qualifiers(AN_HEADERS, params={"program_id": program["id"]})
    )
    assert meta["total_count"] == 1, "the rejected create must not have persisted a row"
    assert len(rows) == 1


def test_same_employee_code_is_accepted_under_a_different_program():
    """The employee_code uniqueness scope is the program, not the whole system.

    PRD §2.8 priority 22: "`employee_code` is unique per `program_id`; `tier_code`
    and `tier_rank` are each unique per `program_id`; `sequence` is unique per
    `contract_id`"

    Design: Corner/validations/uniqueness_violations_on_employee_code_tier_key_and_milestone_sequence
    """
    first = create_program()
    second = create_program(
        name="FY27 Chairmans Club",
        fiscal_year=2027,
        sales_period_start="2027-01-01T00:00:00Z",
        sales_period_end="2027-06-30T00:00:00Z",
    )
    create_qualifier(first["id"], employee_code="S-1001", full_name="Ana Reyes")

    response = api_client.create_qualifier(
        create_qualifier_payload(
            second["id"], employee_code="S-1001", full_name="Ana Reyes"
        ),
        AN_HEADERS,
    )
    twin = validate_success(response, 201)
    assert twin["employee_code"] == "S-1001"
    assert twin["program_id"] == second["id"]


def test_duplicate_tier_code_in_the_same_program_is_rejected():
    """A colliding tier_code reports ERR_DUPLICATE_TIER_KEY even when the rank is free.

    PRD §3.1: "Both `tier_code` and `tier_rank` are unique within a program, and a
    collision on either reports `ERR_DUPLICATE_TIER_KEY`."

    Design: Corner/validations/uniqueness_violations_on_employee_code_tier_key_and_milestone_sequence
    """
    program = create_program()
    create_award_tier(program["id"], tier_code="PLATINUM", tier_rank=1)

    response = api_client.create_award_tier(
        create_award_tier_payload(program["id"], tier_code="PLATINUM", tier_rank=9),
        PD_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_TIER_KEY)

    rows, meta = validate_paginated(
        api_client.list_award_tiers(PD_HEADERS, params={"program_id": program["id"]})
    )
    assert meta["total_count"] == 1


def test_duplicate_tier_rank_in_the_same_program_is_rejected():
    """A colliding tier_rank reports ERR_DUPLICATE_TIER_KEY even when the code is free.

    PRD §3.1: "Both `tier_code` and `tier_rank` are unique within a program, and a
    collision on either reports `ERR_DUPLICATE_TIER_KEY`."

    Design: Corner/validations/uniqueness_violations_on_employee_code_tier_key_and_milestone_sequence
    """
    program = create_program()
    create_award_tier(program["id"], tier_code="PLATINUM", tier_rank=1)

    response = api_client.create_award_tier(
        create_award_tier_payload(program["id"], tier_code="SILVER", tier_rank=1),
        PD_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_TIER_KEY)

    rows, meta = validate_paginated(
        api_client.list_award_tiers(PD_HEADERS, params={"program_id": program["id"]})
    )
    assert meta["total_count"] == 1


def test_identical_tier_key_is_accepted_under_a_different_program():
    """The tier_code/tier_rank uniqueness scope is the program.

    PRD §3.1: "Both `tier_code` and `tier_rank` are unique within a program, and a
    collision on either reports `ERR_DUPLICATE_TIER_KEY`."

    Design: Corner/validations/uniqueness_violations_on_employee_code_tier_key_and_milestone_sequence
    """
    first = create_program()
    second = create_program(
        name="FY27 Chairmans Club",
        fiscal_year=2027,
        sales_period_start="2027-01-01T00:00:00Z",
        sales_period_end="2027-06-30T00:00:00Z",
    )
    create_award_tier(first["id"], tier_code="PLATINUM", tier_rank=1)

    response = api_client.create_award_tier(
        create_award_tier_payload(second["id"], tier_code="PLATINUM", tier_rank=1),
        PD_HEADERS,
    )
    twin = validate_success(response, 201)
    assert twin["tier_code"] == "PLATINUM"
    assert twin["tier_rank"] == 1
    assert twin["program_id"] == second["id"]


def test_duplicate_milestone_sequence_is_scoped_to_one_contract():
    """A repeated sequence is rejected on its own contract yet free on a sibling contract.

    PRD §3.5: "The `sequence` is unique within a contract; a repeat reports
    `ERR_DUPLICATE_MILESTONE_SEQUENCE`."

    Design: Corner/validations/uniqueness_violations_on_employee_code_tier_key_and_milestone_sequence
    """
    base = setup_sourcing_program()
    first = create_contract(
        base["program"]["id"], base["destination"]["id"], supplier_name="Tivoli Lisboa"
    )
    second = create_contract(
        base["program"]["id"], base["destination"]["id"], supplier_name="Pestana Palace"
    )
    create_milestone(first["id"], sequence=1, amount_cents=577_500)

    response = api_client.create_deposit_milestone(
        create_deposit_milestone_payload(
            first["id"], sequence=1, amount_cents=577_500, due_at="2026-09-15T00:00:00Z"
        ),
        SM_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_MILESTONE_SEQUENCE)

    rows, meta = validate_paginated(
        api_client.list_deposit_milestones(
            SM_HEADERS, params={"contract_id": first["id"]}
        )
    )
    assert meta["total_count"] == 1

    twin = validate_success(
        api_client.create_deposit_milestone(
            create_deposit_milestone_payload(
                second["id"], sequence=1, amount_cents=577_500
            ),
            SM_HEADERS,
        ),
        201,
    )
    assert twin["sequence"] == 1
    assert twin["contract_id"] == second["id"]


def test_duplicate_milestone_sequence_outranks_the_schedule_ceiling():
    """Uniqueness (priority 22) is reported before the deposit ceiling (priority 28).

    PRD §2.8 priority 22: "`sequence` is unique per `contract_id`"

    Design: Corner/validations/uniqueness_violations_on_employee_code_tier_key_and_milestone_sequence
    """
    base = setup_sourcing_program()
    contract = create_contract(base["program"]["id"], base["destination"]["id"])
    contract_value = (
        contract["room_block_count"]
        * contract["contracted_nights"]
        * contract["nightly_rate_cents"]
    )
    assert contract_value == 4_620_000
    create_milestone(contract["id"], sequence=1, amount_cents=577_500)

    response = api_client.create_deposit_milestone(
        create_deposit_milestone_payload(
            contract["id"], sequence=1, amount_cents=5_000_000
        ),
        SM_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_MILESTONE_SEQUENCE)


def test_second_non_cancelled_winner_seat_for_one_qualifier_is_rejected():
    """A qualifier may hold only one live WINNER seat.

    PRD §3.6: "Independently, a qualifier may hold at most one `WINNER` seat that
    is not `CANCELLED`; a second reports `ERR_DUPLICATE_WINNER_REGISTRATION`, and
    cancelling the first frees the slot for a legitimate re-enrolment."

    Design: Corner/validations/uniqueness_violations_on_winner_registration_and_activity_signup
    """
    base = setup_invited_registration()
    qualifier = base["qualifier"]
    program = base["program"]

    response = api_client.create_registration(
        create_registration_payload(
            qualifier["id"], program_version(program["id"]), registration_kind="WINNER"
        ),
        TD_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_WINNER_REGISTRATION)

    rows, meta = validate_paginated(
        api_client.list_registrations(
            TD_HEADERS, params={"qualifier_id": qualifier["id"]}
        )
    )
    assert meta["total_count"] == 1


def test_guest_seat_for_the_same_qualifier_is_not_a_duplicate_winner():
    """The uniqueness key covers WINNER seats only, so a GUEST seat is accepted.

    PRD §3.6: "Independently, a qualifier may hold at most one `WINNER` seat that
    is not `CANCELLED`; a second reports `ERR_DUPLICATE_WINNER_REGISTRATION`, and
    cancelling the first frees the slot for a legitimate re-enrolment."

    Design: Corner/validations/uniqueness_violations_on_winner_registration_and_activity_signup
    """
    base = setup_invited_registration()
    qualifier = base["qualifier"]
    winner = base["registration"]

    guest = validate_success(
        api_client.create_registration(
            create_registration_payload(
                qualifier["id"],
                program_version(base["program"]["id"]),
                registration_kind="GUEST",
                guest_of_registration_id=winner["id"],
            ),
            TD_HEADERS,
        ),
        201,
    )
    assert_registration(guest)
    assert guest["registration_kind"] == "GUEST"
    assert guest["guest_of_registration_id"] == winner["id"]
    assert guest["attendance_status"] == "INVITED"


def test_cancelling_the_winner_seat_frees_the_uniqueness_slot():
    """A CANCELLED WINNER seat no longer occupies the one-live-winner slot.

    PRD §3.6: "Independently, a qualifier may hold at most one `WINNER` seat that
    is not `CANCELLED`; a second reports `ERR_DUPLICATE_WINNER_REGISTRATION`, and
    cancelling the first frees the slot for a legitimate re-enrolment."

    Design: Corner/validations/uniqueness_violations_on_winner_registration_and_activity_signup
    """
    base = setup_invited_registration()
    qualifier = base["qualifier"]
    cancelled = cancel_registration(base["registration"]["id"], reason="Winner withdrew")
    assert cancelled["attendance_status"] == "CANCELLED"

    replacement = validate_success(
        api_client.create_registration(
            create_registration_payload(
                qualifier["id"],
                program_version(base["program"]["id"]),
                registration_kind="WINNER",
            ),
            TD_HEADERS,
        ),
        201,
    )
    assert replacement["registration_kind"] == "WINNER"
    assert replacement["attendance_status"] == "INVITED"
    assert replacement["id"] != base["registration"]["id"]


def test_second_live_signup_for_the_same_activity_and_registration_is_rejected():
    """A repeated activity-and-registration pair reports ERR_DUPLICATE_ACTIVITY_SIGNUP.

    PRD §3.8: "At most one signup that is not `CANCELLED` may exist for a given
    activity-and-registration pair; a second reports
    `ERR_DUPLICATE_ACTIVITY_SIGNUP`."

    Design: Corner/validations/uniqueness_violations_on_winner_registration_and_activity_signup
    """
    base = setup_onsite_with_activity()
    activity = base["activity"]
    registration = base["registration"]
    first = create_signup(activity["id"], registration["id"])
    assert first["status"] == "BOOKED"

    response = api_client.create_activity_signup(
        create_activity_signup_payload(
            activity["id"], registration["id"], activity_version(activity["id"])
        ),
        TD_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_ACTIVITY_SIGNUP)

    assert_signup_counters(read_activity(activity["id"]), 1, 0)


def test_cancelled_signup_frees_the_activity_and_registration_pair():
    """A CANCELLED signup no longer occupies the pair, so a re-signup is accepted.

    PRD §2.8 priority 22: "at most one non-`CANCELLED` signup exists per
    activity-and-registration pair"

    Design: Corner/validations/uniqueness_violations_on_winner_registration_and_activity_signup
    """
    base = setup_onsite_with_activity()
    activity = base["activity"]
    registration = base["registration"]
    first = create_signup(activity["id"], registration["id"])
    cancelled = cancel_signup(first["id"])
    assert cancelled["status"] == "CANCELLED"
    assert_signup_counters(read_activity(activity["id"]), 0, 0)

    replacement = validate_success(
        api_client.create_activity_signup(
            create_activity_signup_payload(
                activity["id"], registration["id"], activity_version(activity["id"])
            ),
            TD_HEADERS,
        ),
        201,
    )
    assert replacement["status"] == "BOOKED"
    assert replacement["id"] != first["id"]
    assert_signup_counters(read_activity(activity["id"]), 1, 0)


def test_shortlisting_passes_at_the_risk_ceiling_and_the_inspection_floor():
    """risk_score exactly 60 and inspection_score exactly 70 are both accepted.

    PRD §3.3: "The destination's `risk_score` must be at most 60 — a score of
    exactly 60 passes, 61 does not, and exceeding the ceiling reports
    `ERR_DESTINATION_RISK_TOO_HIGH`. Its `inspection_score` must be at least 70 —
    exactly 70 passes, 69 does not, and falling short reports
    `ERR_INSPECTION_SCORE_BELOW_MINIMUM`."

    Design: Corner/validations/boundary_satisfying_values_pass_risk_inspection_schedule_and_deviation_gates
    """
    program = create_program()
    destination = create_destination(program["id"], risk_score=60)
    assert destination["risk_score"] == 60
    inspected = inspect_destination(destination["id"], 70)
    assert inspected["inspection_score"] == 70

    shortlisted = validate_success(
        api_client.shortlist_destination(destination["id"], SM_HEADERS)
    )
    assert_destination(shortlisted)
    assert shortlisted["status"] == "SHORTLISTED"
    assert shortlisted["risk_score"] == 60
    assert shortlisted["inspection_score"] == 70


def test_deposit_schedule_summing_to_exactly_the_contract_value_executes():
    """A schedule equal to the contract value clears the ceiling on execution.

    PRD §3.5: "a schedule summing to exactly the contract value is accepted, and
    one cent more reports `ERR_DEPOSIT_SCHEDULE_EXCEEDS_CONTRACT_VALUE`."

    Design: Corner/validations/boundary_satisfying_values_pass_risk_inspection_schedule_and_deviation_gates
    """
    base = setup_proposed_contract(
        destination_overrides={"per_person_cost_cents": 431757},
        contract_overrides={
            "supplier_name": "Estoril Palace",
            "contracted_nights": 5,
            "stay_start_at": "2026-11-08T00:00:00Z",
        },
    )
    contract = base["contract"]
    contract_value = (
        contract["room_block_count"]
        * contract["contracted_nights"]
        * contract["nightly_rate_cents"]
    )
    assert contract_value == 2_310_000
    create_milestone(
        contract["id"], sequence=1, amount_cents=577_500, refundable_bp=10000
    )
    create_milestone(
        contract["id"],
        sequence=2,
        amount_cents=577_500,
        refundable_bp=5000,
        due_at="2026-09-15T00:00:00Z",
    )
    create_milestone(
        contract["id"],
        sequence=3,
        amount_cents=1_155_000,
        refundable_bp=0,
        due_at="2026-10-15T00:00:00Z",
    )

    executed = validate_success(
        api_client.execute_contract(contract["id"], CA_HEADERS)
    )
    assert_supplier_contract(executed)
    assert executed["status"] == "EXECUTED"
    assert executed["room_nights_blocked"] == 60
    program = read_program(base["program"]["id"])
    assert program["status"] == "CONTRACTED"
    assert program["per_person_cost_basis_cents"] == 431757


def test_air_request_at_the_seven_day_deviation_ceiling_is_accepted():
    """A deviation summing to exactly 7 days is priced rather than rejected.

    PRD §3.7: "The two deviation figures must sum to at most 7 days, both on the
    initial request and on the revised values of a change, and a longer deviation
    reports `ERR_DEVIATION_LIMIT_EXCEEDED`."

    Design: Corner/validations/boundary_satisfying_values_pass_risk_inspection_schedule_and_deviation_gates
    """
    base = setup_invited_registration(
        tier_overrides={
            "tier_code": "GOLD",
            "tier_rank": 2,
            "air_cabin_class": "PREMIUM_ECONOMY",
            "upgrade_allowance_cents": 40000,
            "service_load_bp": 800,
        }
    )
    response = api_client.air_registration(
        base["registration"]["id"],
        air_payload(
            "REQUEST",
            cabin_class="BUSINESS",
            deviation_pre_days=4,
            deviation_post_days=3,
            base_fare_cents=214000,
        ),
        TD_HEADERS,
    )
    seat = validate_success(response)
    assert seat["air_status"] == "REQUESTED"
    assert seat["air_deviation_pre_days"] == 4
    assert seat["air_deviation_post_days"] == 3
    assert seat["air_deviation_fee_cents"] == 47500
    assert seat["air_upgrade_cost_cents"] == 77000
    assert seat["air_change_fee_total_cents"] == 0
    assert seat["cost_cents"] == 124500


def test_a_single_night_stay_clears_the_strict_date_ordering_gate():
    """A departure exactly one day after arrival is strictly after it, so it passes.

    PRD §3.6: "The departure instant must be strictly after the arrival instant,
    or the request reports `ERR_INVALID_DATE_RANGE`."

    Design: Corner/validations/boundary_satisfying_values_pass_risk_inspection_schedule_and_deviation_gates
    """
    base = setup_registration_open_program()
    response = api_client.create_registration(
        create_registration_payload(
            base["qualifier"]["id"],
            program_version(base["program"]["id"]),
            arrival_date="2026-11-02T00:00:00Z",
            departure_date="2026-11-03T00:00:00Z",
        ),
        TD_HEADERS,
    )
    seat = validate_success(response, 201)
    assert_registration(seat)
    assert seat["attendance_status"] == "INVITED"
    assert_instant_equals(seat["arrival_date"], "2026-11-02T00:00:00Z", "arrival_date")
    assert_instant_equals(seat["departure_date"], "2026-11-03T00:00:00Z", "departure_date")


def test_missing_auth_headers_outrank_path_existence():
    """Priority 1 fires before priority 4, so an unauthenticated read never reveals ids.

    PRD §2.8 priority 1: "**Authentication headers** — `X-User-Role` and
    `X-User-ID` are both present and non-empty. Applies to every endpoint.
    Violation: `ERR_MISSING_AUTH_HEADERS`, HTTP 401."

    Design: Corner/validations/validation_priority_ladder_resolves_auth_before_existence_before_schema
    """
    create_program()

    blank = api_client.get_program(
        NON_EXISTENT_UUID, {"X-User-ID": "", "X-User-Role": ""}
    )
    validate_error(blank, ApiErrorId.ERR_MISSING_AUTH_HEADERS)

    authenticated = api_client.get_program(NON_EXISTENT_UUID, PD_HEADERS)
    validate_error(authenticated, ApiErrorId.ERR_PROGRAM_NOT_FOUND)


def test_unrecognised_role_outranks_path_existence():
    """Priority 2 fires before priority 4 even where the endpoint permits many roles.

    PRD §2.8 priority 2: "**Role recognition** — `X-User-Role` is one of the seven
    declared roles. Applies to every endpoint. Violation: `ERR_INVALID_ROLE`,
    HTTP 401."

    Design: Corner/validations/validation_priority_ladder_resolves_auth_before_existence_before_schema
    """
    create_program()

    response = api_client.get_program(
        NON_EXISTENT_UUID, headers_for_role("Auditor", "au-01")
    )
    validate_error(response, ApiErrorId.ERR_INVALID_ROLE)


def test_role_authorization_outranks_advance_prerequisites():
    """Priority 3 fires before priorities 10 and 33 on a declared-edge advance.

    PRD §2.8 priority 3: "**Role authorization** — the supplied role appears in the
    called endpoint's authorized-role list. Applies to every endpoint. Violation:
    `ERR_ROLE_NOT_PERMITTED`, HTTP 403."

    Design: Corner/validations/validation_priority_ladder_resolves_auth_before_existence_before_schema
    """
    base = setup_accepted_registration(num_qualifiers=2)
    program = base["program"]

    forbidden = api_client.advance_program(
        program["id"], advance_payload("ONSITE"), TD_HEADERS
    )
    validate_error(forbidden, ApiErrorId.ERR_ROLE_NOT_PERMITTED)

    permitted = api_client.advance_program(
        program["id"], advance_payload("ONSITE"), PD_HEADERS
    )
    validate_error(permitted, ApiErrorId.ERR_ADVANCE_PREREQUISITES_UNMET)

    assert read_program(program["id"])["status"] == "REGISTRATION_OPEN"


def test_role_authorization_outranks_path_existence():
    """A caller with the wrong role cannot probe which ids exist.

    PRD §2.8 priority 4: "**Path existence** — every templated id in the URL
    resolves to an existing row, validated strictly left to right, so the leftmost
    unresolvable segment decides the error."

    Design: Corner/validations/validation_priority_ladder_resolves_auth_before_existence_before_schema
    """
    create_program()

    forbidden = api_client.review_qualifier(NON_EXISTENT_UUID, TD_HEADERS)
    validate_error(forbidden, ApiErrorId.ERR_ROLE_NOT_PERMITTED)

    permitted = api_client.review_qualifier(NON_EXISTENT_UUID, AN_HEADERS)
    validate_error(permitted, ApiErrorId.ERR_QUALIFIER_NOT_FOUND)


def test_path_existence_outranks_request_schema():
    """A dangling path id is reported before the body's enum violation.

    PRD §2.8 priority 7: "**Request schema** — all required fields present, correct
    JSON types, enum values inside their declared sets and integers inside their
    declared ranges."

    Design: Corner/validations/validation_priority_ladder_resolves_auth_before_existence_before_schema
    """
    program = create_program()

    missing_program = api_client.set_gross_up_policy(
        NON_EXISTENT_UUID, gross_up_policy_payload("BANANA"), PD_HEADERS
    )
    validate_error(missing_program, ApiErrorId.ERR_PROGRAM_NOT_FOUND)

    bad_enum = api_client.set_gross_up_policy(
        program["id"], gross_up_policy_payload("BANANA"), PD_HEADERS
    )
    validate_error(bad_enum, ApiErrorId.ERR_INVALID_REQUEST)

    assert read_program(program["id"])["gross_up_policy_locked"] is False


def test_body_foreign_key_existence_outranks_the_stale_version_guard():
    """Priority 5 fires before priority 9 on enrolment.

    PRD §2.8 priority 5: "**Body foreign-key existence** — every foreign key
    supplied in the request body resolves to an existing row, validated in the
    order the fields are listed in that endpoint's input."

    Design: Corner/validations/validation_priority_ladder_resolves_auth_before_existence_before_schema
    """
    base = setup_registration_open_program(num_qualifiers=2)
    stale_version = program_version(base["program"]["id"]) + 100

    dangling = api_client.create_registration(
        create_registration_payload(NON_EXISTENT_UUID, stale_version),
        TD_HEADERS,
    )
    validate_error(dangling, ApiErrorId.ERR_QUALIFIER_NOT_FOUND)

    resolvable = api_client.create_registration(
        create_registration_payload(base["qualifier"]["id"], stale_version),
        TD_HEADERS,
    )
    validate_error(resolvable, ApiErrorId.ERR_STALE_PROGRAM_VERSION)

    rows, meta = validate_paginated(
        api_client.list_registrations(
            TD_HEADERS, params={"program_id": base["program"]["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_participant_ownership_outranks_request_schema():
    """A non-owner Participant is rejected before the body's enum is examined.

    PRD §2.8 priority 6: "**Participant ownership** — when the role is
    `Participant`, `X-User-ID` equals the `id` of the `Qualifier` that owns the
    target resource."

    Design: Corner/validations/validation_priority_ladder_resolves_auth_before_existence_before_schema
    """
    base = setup_accepted_registration(num_qualifiers=2)
    registration = base["registration"]
    owner = base["qualifiers"][0]
    stranger = base["qualifiers"][1]
    version_before = read_program(base["program"]["id"])["version"]

    not_owner = api_client.respond_registration(
        registration["id"],
        respond_payload("BANANA"),
        make_participant_headers(stranger["id"]),
    )
    validate_error(not_owner, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

    owner_bad_enum = api_client.respond_registration(
        registration["id"],
        respond_payload("BANANA"),
        make_participant_headers(owner["id"]),
    )
    validate_error(owner_bad_enum, ApiErrorId.ERR_INVALID_REQUEST)

    assert read_registration(registration["id"])["attendance_status"] == "ACCEPTED"
    after = read_program(base["program"]["id"])
    assert after["status"] == "REGISTRATION_OPEN"
    assert after["version"] == version_before


def test_pagination_schema_rejects_a_limit_below_the_declared_range():
    """A limit of 0 is outside 1..100, so the list read is a schema failure.

    PRD §2.8 priority 8: "**Pagination schema** — `limit` is an integer from 1 to
    100 and `offset` is an integer of at least 0. Applies to all GET list
    endpoints. Violation: `ERR_INVALID_REQUEST`, HTTP 400."

    Design: Corner/validations/validation_priority_ladder_resolves_auth_before_existence_before_schema
    """
    create_program()

    response = api_client.list_programs(PD_HEADERS, params={"limit": 0})
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)


def test_air_request_beyond_seven_deviation_days_is_rejected():
    """A deviation total of 8 days is rejected and stores nothing.

    PRD §3.7: "The two deviation figures must sum to at most 7 days, both on the
    initial request and on the revised values of a change, and a longer deviation
    reports `ERR_DEVIATION_LIMIT_EXCEEDED`."

    Design: Corner/validations/temporal_gates_reject_deviation_overrun_stay_window_and_degenerate_ranges
    """
    base = setup_accepted_registration()
    registration = base["registration"]

    response = api_client.air_registration(
        registration["id"],
        air_payload(
            "REQUEST",
            cabin_class="BUSINESS",
            deviation_pre_days=4,
            deviation_post_days=4,
            base_fare_cents=214000,
        ),
        TD_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_DEVIATION_LIMIT_EXCEEDED)

    seat = read_registration(registration["id"])
    assert seat["air_status"] == "NOT_REQUESTED"
    assert seat["air_deviation_fee_cents"] == 0
    assert seat["air_deviation_pre_days"] == 0
    assert seat["air_deviation_post_days"] == 0


def test_air_change_re_checks_the_deviation_ceiling_on_the_revised_values():
    """An already-ticketed itinerary cannot be pushed over the 7-day ceiling.

    PRD §3.7: "The two deviation figures must sum to at most 7 days, both on the
    initial request and on the revised values of a change, and a longer deviation
    reports `ERR_DEVIATION_LIMIT_EXCEEDED`."

    Design: Corner/validations/temporal_gates_reject_deviation_overrun_stay_window_and_degenerate_ranges
    """
    base = setup_accepted_registration()
    registration = base["registration"]
    requested = air_action(
        registration["id"],
        "REQUEST",
        cabin_class="BUSINESS",
        deviation_pre_days=4,
        deviation_post_days=3,
        base_fare_cents=214000,
    )
    assert requested["air_status"] == "REQUESTED"
    assert requested["air_deviation_fee_cents"] == 47500
    ticketed = air_action(registration["id"], "TICKET")
    assert ticketed["air_status"] == "TICKETED"
    assert ticketed["air_change_count"] == 0

    response = api_client.air_registration(
        registration["id"],
        air_payload("CHANGE", deviation_pre_days=4, deviation_post_days=4),
        TD_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_DEVIATION_LIMIT_EXCEEDED)

    seat = read_registration(registration["id"])
    assert seat["air_status"] == "TICKETED"
    assert seat["air_deviation_pre_days"] == 4
    assert seat["air_deviation_post_days"] == 3
    assert seat["air_change_count"] == 0


def test_confirmation_rejects_a_seat_outside_the_contracted_stay_window():
    """Dates legal at creation are still unconfirmable against the stay window.

    PRD §3.7: "The seat must fall inside the **stay window**: `arrival_date` must be
    at or after the contract's `stay_start_at` and `departure_date` at or before its
    `stay_end_at`, and a seat outside those bounds reports
    `ERR_STAY_WINDOW_VIOLATION`."

    Design: Corner/validations/temporal_gates_reject_deviation_overrun_stay_window_and_degenerate_ranges
    """
    base = setup_accepted_registration(
        contract_overrides={
            "contracted_nights": 5,
            "stay_start_at": "2026-11-08T00:00:00Z",
        },
        registration_overrides={
            "arrival_date": "2026-11-07T00:00:00Z",
            "departure_date": "2026-11-14T00:00:00Z",
        },
    )
    registration = base["registration"]
    assert registration["attendance_status"] == "ACCEPTED"

    response = api_client.confirm_registration(registration["id"], TD_HEADERS)
    validate_error(response, ApiErrorId.ERR_STAY_WINDOW_VIOLATION)

    seat = read_registration(registration["id"])
    assert seat["attendance_status"] == "ACCEPTED"
    assert seat["room_nights"] == 0
    contract = read_contract(base["contract"]["id"])
    assert contract["room_nights_confirmed"] == 0
    assert_room_nights_conserved(contract)


def test_degenerate_date_pairs_are_rejected_on_all_three_endpoints():
    """A range whose end equals its start is rejected wherever the PRD declares one.

    PRD §2.8 priority 23: "**Ordered date pairs** — `sales_period_end` is strictly
    after `sales_period_start`, `end_at` is strictly after `start_at`, and
    `departure_date` is strictly after `arrival_date`. Applies to `POST /programs`,
    `POST /onsite-activities` and `POST /registrations`. Violation:
    `ERR_INVALID_DATE_RANGE`, HTTP 422."

    Design: Corner/validations/temporal_gates_reject_deviation_overrun_stay_window_and_degenerate_ranges
    """
    base = setup_registration_open_program()

    zero_length_activity = api_client.create_onsite_activity(
        create_onsite_activity_payload(
            base["program"]["id"],
            name="Sunset Cruise",
            start_at="2026-11-10T18:00:00Z",
            end_at="2026-11-10T18:00:00Z",
            capacity=10,
        ),
        TD_HEADERS,
    )
    validate_error(zero_length_activity, ApiErrorId.ERR_INVALID_DATE_RANGE)

    same_day_seat = api_client.create_registration(
        create_registration_payload(
            base["qualifier"]["id"],
            program_version(base["program"]["id"]),
            arrival_date="2026-11-10T00:00:00Z",
            departure_date="2026-11-10T00:00:00Z",
        ),
        TD_HEADERS,
    )
    validate_error(same_day_seat, ApiErrorId.ERR_INVALID_DATE_RANGE)

    zero_length_period = api_client.create_program(
        create_program_payload(
            name="FY27 Chairmans Club",
            fiscal_year=2027,
            sales_period_start="2027-01-01T00:00:00Z",
            sales_period_end="2027-01-01T00:00:00Z",
        ),
        PD_HEADERS,
    )
    validate_error(zero_length_period, ApiErrorId.ERR_INVALID_DATE_RANGE)


def _draft_contract_with_two_milestones():
    """SOURCING program with a DRAFT 12x5x38500 contract and 1155000 cents left to schedule."""
    base = setup_sourcing_program(
        destination_overrides={"per_person_cost_cents": 431757},
    )
    contract = create_contract(
        base["program"]["id"],
        base["destination"]["id"],
        supplier_name="Estoril Palace",
        contracted_nights=5,
        stay_start_at="2026-11-08T00:00:00Z",
    )
    create_milestone(
        contract["id"], sequence=1, amount_cents=577_500, refundable_bp=10000
    )
    create_milestone(
        contract["id"],
        sequence=2,
        amount_cents=577_500,
        refundable_bp=5000,
        due_at="2026-09-15T00:00:00Z",
    )
    base["contract"] = read_contract(contract["id"])
    return base


def test_appending_one_cent_over_the_cumulative_ceiling_is_rejected():
    """The append gate compares the cumulative schedule, not the single amount.

    PRD §3.5: "The cumulative `amount_cents` of the contract's non-`CANCELLED`
    milestones may not exceed the contract value of `room_block_count` multiplied by
    `contracted_nights` multiplied by `nightly_rate_cents`; a schedule summing to
    exactly the contract value is accepted, and one cent more reports
    `ERR_DEPOSIT_SCHEDULE_EXCEEDS_CONTRACT_VALUE`."

    Design: Corner/validations/deposit_schedule_aggregate_limit_is_checked_on_append_and_re_checked_at_execution
    """
    base = _draft_contract_with_two_milestones()
    contract = base["contract"]

    response = api_client.create_deposit_milestone(
        create_deposit_milestone_payload(
            contract["id"],
            sequence=3,
            due_at="2026-10-15T00:00:00Z",
            amount_cents=1_155_001,
            refundable_bp=0,
        ),
        SM_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_DEPOSIT_SCHEDULE_EXCEEDS_CONTRACT_VALUE)

    rows, meta = validate_paginated(
        api_client.list_deposit_milestones(
            SM_HEADERS, params={"contract_id": contract["id"]}
        )
    )
    assert meta["total_count"] == 2


def test_appending_up_to_exact_equality_with_the_contract_value_is_accepted():
    """The append gate is <=, so a schedule equal to the contract value passes.

    PRD §3.5: "a schedule summing to exactly the contract value is accepted, and one
    cent more reports `ERR_DEPOSIT_SCHEDULE_EXCEEDS_CONTRACT_VALUE`."

    Design: Corner/validations/deposit_schedule_aggregate_limit_is_checked_on_append_and_re_checked_at_execution
    """
    base = _draft_contract_with_two_milestones()
    contract = base["contract"]

    milestone = validate_success(
        api_client.create_deposit_milestone(
            create_deposit_milestone_payload(
                contract["id"],
                sequence=3,
                due_at="2026-10-15T00:00:00Z",
                amount_cents=1_155_000,
                refundable_bp=0,
            ),
            SM_HEADERS,
        ),
        201,
    )
    assert_deposit_milestone(milestone)
    assert milestone["amount_cents"] == 1_155_000
    assert milestone["status"] == "SCHEDULED"

    rows, meta = validate_paginated(
        api_client.list_deposit_milestones(
            SM_HEADERS, params={"contract_id": contract["id"]}
        )
    )
    assert meta["total_count"] == 3
    assert sum(row["amount_cents"] for row in rows) == 2_310_000


def test_execution_re_checks_the_schedule_against_the_renegotiated_terms():
    """A legally built schedule blocks execution once the rate drops beneath it.

    PRD §2.8 priority 28: "**Deposit schedule ceiling** — the sum of `amount_cents`
    over the contract's non-`CANCELLED` deposit milestones is at most the contract
    value. Applies to `POST /deposit-milestones` and `POST
    /supplier-contracts/{contract_id}/execute`."

    Design: Corner/validations/deposit_schedule_aggregate_limit_is_checked_on_append_and_re_checked_at_execution
    """
    base = _draft_contract_with_two_milestones()
    contract = base["contract"]
    create_milestone(
        contract["id"],
        sequence=3,
        amount_cents=1_155_000,
        refundable_bp=0,
        due_at="2026-10-15T00:00:00Z",
    )
    proposed = propose_contract(contract["id"], nightly_rate_cents=38000)
    assert proposed["status"] == "PROPOSED"
    assert proposed["round_count"] == 1
    assert proposed["nightly_rate_cents"] == 38000

    response = api_client.execute_contract(contract["id"], CA_HEADERS)
    validate_error(response, ApiErrorId.ERR_DEPOSIT_SCHEDULE_EXCEEDS_CONTRACT_VALUE)

    after = read_contract(contract["id"])
    assert after["status"] == "PROPOSED"
    assert after["executed_by_user_id"] is None
    assert after["room_nights_blocked"] == 0
    program = read_program(base["program"]["id"])
    assert program["status"] == "SOURCING"
    assert program["per_person_cost_basis_cents"] == 0


def test_restoring_the_rate_lets_the_same_schedule_execute():
    """Once the contract value is back at 2310000 the equal schedule passes again.

    PRD §3.5: "a schedule summing to exactly the contract value is accepted, and one
    cent more reports `ERR_DEPOSIT_SCHEDULE_EXCEEDS_CONTRACT_VALUE`."

    Design: Corner/validations/deposit_schedule_aggregate_limit_is_checked_on_append_and_re_checked_at_execution
    """
    base = _draft_contract_with_two_milestones()
    contract = base["contract"]
    create_milestone(
        contract["id"],
        sequence=3,
        amount_cents=1_155_000,
        refundable_bp=0,
        due_at="2026-10-15T00:00:00Z",
    )
    propose_contract(contract["id"], nightly_rate_cents=38000)
    validate_error(
        api_client.execute_contract(contract["id"], CA_HEADERS),
        ApiErrorId.ERR_DEPOSIT_SCHEDULE_EXCEEDS_CONTRACT_VALUE,
    )

    countered = counter_contract(contract["id"], nightly_rate_cents=38500)
    assert countered["status"] == "COUNTERED"
    assert countered["round_count"] == 2
    reproposed = propose_contract(contract["id"])
    assert reproposed["status"] == "PROPOSED"
    assert reproposed["round_count"] == 3
    assert reproposed["nightly_rate_cents"] == 38500

    executed = validate_success(api_client.execute_contract(contract["id"], CA_HEADERS))
    assert executed["status"] == "EXECUTED"
    assert executed["room_nights_blocked"] == 60
    program = read_program(base["program"]["id"])
    assert program["status"] == "CONTRACTED"
    assert program["per_person_cost_basis_cents"] == 431757


GUEST_LADDER = [
    {
        "tier_code": "PLATINUM",
        "tier_rank": 1,
        "qualification_threshold": 250_000_000,
        "guest_allowance": 1,
        "air_cabin_class": "BUSINESS",
    },
    {
        "tier_code": "GOLD",
        "tier_rank": 2,
        "qualification_threshold": 150_000_000,
        "guest_allowance": 1,
        "air_cabin_class": "PREMIUM_ECONOMY",
    },
    {
        "tier_code": "BRONZE",
        "tier_rank": 3,
        "qualification_threshold": 100_000_000,
        "guest_allowance": 0,
        "air_cabin_class": "ECONOMY",
        "upgrade_allowance_cents": 0,
        "service_load_bp": 500,
    },
]

GUEST_COHORT = [
    {
        "employee_code": "S-1001",
        "full_name": "Ana Reyes",
        "baseline_metric": 180_000_000,
        "actual_metric": 260_000_000,
        "guest_count": 1,
    },
    {
        "employee_code": "S-2001",
        "full_name": "Ben Ortiz",
        "baseline_metric": 120_000_000,
        "actual_metric": 155_000_000,
        "guest_count": 0,
    },
    {
        "employee_code": "S-3001",
        "full_name": "Cara Lund",
        "baseline_metric": 90_000_000,
        "actual_metric": 110_000_000,
        "guest_count": 0,
    },
]


def _guest_policy_program(platinum_guest_allowance=1):
    """REGISTRATION_OPEN program with a three-rung ladder and Ana/Ben/Cara notified.

    The winner seats are left at INVITED on purpose: confirming one moves its
    qualifier NOTIFIED -> REGISTERED (PRD §3.7), which would make every later
    enrolment fail the §3.6 award-status gate long before the guest rules run.
    """
    ladder = [dict(rung) for rung in GUEST_LADDER]
    ladder[0]["guest_allowance"] = platinum_guest_allowance
    base = setup_registration_open_program(
        tier_specs=ladder, qualifier_specs=[dict(spec) for spec in GUEST_COHORT]
    )
    base["ana"], base["ben"], base["cara"] = base["qualifiers"]
    return base


def _guest_seat_payload(qualifier_id, program_id, **overrides):
    payload = create_registration_payload(
        qualifier_id,
        program_version(program_id),
        registration_kind="GUEST",
        arrival_date="2026-11-02T00:00:00Z",
        departure_date="2026-11-06T00:00:00Z",
        rooms=1,
    )
    payload.update(overrides)
    return payload


def test_guest_seats_beyond_the_tier_allowance_are_rejected():
    """A second companion breaches a guest_allowance of 1.

    PRD §3.6: "**The allowance** caps how many companions a winner may bring: the
    number of that winner's guest seats that are not `CANCELLED` may never exceed the
    `guest_allowance` of the tier stamped on the qualifier's `assigned_tier_id`, and
    an enrolment that would breach it reports `ERR_GUEST_ALLOWANCE_EXCEEDED`."

    Design: Corner/validations/guest_policy_rules_apply_only_to_guest_rows_and_read_the_assigned_tier_allowance
    """
    base = _guest_policy_program()
    ana = base["ana"]
    winner = create_registration(ana["id"], program_id=base["program"]["id"])

    first = validate_success(
        api_client.create_registration(
            _guest_seat_payload(
                ana["id"], base["program"]["id"], guest_of_registration_id=winner["id"]
            ),
            TD_HEADERS,
        ),
        201,
    )
    assert first["registration_kind"] == "GUEST"
    assert first["qualifier_id"] == ana["id"]
    assert first["guest_of_registration_id"] == winner["id"]
    assert first["attendance_status"] == "INVITED"
    assert first["rooms"] == 1

    second = api_client.create_registration(
        _guest_seat_payload(
            ana["id"], base["program"]["id"], guest_of_registration_id=winner["id"]
        ),
        TD_HEADERS,
    )
    validate_error(second, ApiErrorId.ERR_GUEST_ALLOWANCE_EXCEEDED)

    rows, meta = validate_paginated(
        api_client.list_registrations(
            TD_HEADERS, params={"qualifier_id": ana["id"]}
        )
    )
    assert meta["total_count"] == 2


def test_guest_allowance_is_read_from_the_qualifiers_assigned_tier():
    """The same request shape passes on a one-guest rung and fails on a zero-guest rung.

    PRD §3.6: "the number of that winner's guest seats that are not `CANCELLED` may
    never exceed the `guest_allowance` of the tier stamped on the qualifier's
    `assigned_tier_id`"

    Design: Corner/validations/guest_policy_rules_apply_only_to_guest_rows_and_read_the_assigned_tier_allowance
    """
    base = _guest_policy_program()
    ana, cara = base["ana"], base["cara"]
    tiers = {tier["id"]: tier for tier in base["tiers"]}
    assert tiers[ana["assigned_tier_id"]]["tier_code"] == "PLATINUM"
    assert tiers[ana["assigned_tier_id"]]["guest_allowance"] == 1
    assert tiers[cara["assigned_tier_id"]]["tier_code"] == "BRONZE"
    assert tiers[cara["assigned_tier_id"]]["guest_allowance"] == 0

    ana_winner = create_registration(ana["id"], program_id=base["program"]["id"])
    cara_winner = create_registration(cara["id"], program_id=base["program"]["id"])

    permitted = validate_success(
        api_client.create_registration(
            _guest_seat_payload(
                ana["id"],
                base["program"]["id"],
                guest_of_registration_id=ana_winner["id"],
            ),
            TD_HEADERS,
        ),
        201,
    )
    assert permitted["registration_kind"] == "GUEST"

    refused = api_client.create_registration(
        _guest_seat_payload(
            cara["id"],
            base["program"]["id"],
            guest_of_registration_id=cara_winner["id"],
        ),
        TD_HEADERS,
    )
    validate_error(refused, ApiErrorId.ERR_GUEST_ALLOWANCE_EXCEEDED)


def test_winner_seats_are_not_gated_by_the_guest_allowance():
    """A zero-allowance rung still admits its own WINNER seat.

    PRD §2.8 priority 20: "**Guest allowance** — the qualifier's `guest_count` is at
    most the assigned tier's `guest_allowance` at review, and the count of
    non-`CANCELLED` guest registrations for a winner never exceeds that allowance."

    Design: Corner/validations/guest_policy_rules_apply_only_to_guest_rows_and_read_the_assigned_tier_allowance
    """
    base = _guest_policy_program()
    cara = base["cara"]

    seat = validate_success(
        api_client.create_registration(
            create_registration_payload(
                cara["id"],
                program_version(base["program"]["id"]),
                registration_kind="WINNER",
            ),
            TD_HEADERS,
        ),
        201,
    )
    assert_registration(seat)
    assert seat["registration_kind"] == "WINNER"
    assert seat["qualifier_id"] == cara["id"]
    assert seat["guest_of_registration_id"] is None
    assert seat["attendance_status"] == "INVITED"


def test_guest_link_must_name_a_live_winner_seat_of_the_same_qualifier():
    """A foreign winner seat and a cancelled winner seat are both invalid link targets.

    PRD §3.6: "a seat whose `registration_kind` is `GUEST` must supply a
    `guest_of_registration_id` naming a non-`CANCELLED` `WINNER` seat carrying the
    same `qualifier_id`"

    Design: Corner/validations/guest_policy_rules_apply_only_to_guest_rows_and_read_the_assigned_tier_allowance
    """
    base = _guest_policy_program()
    ana, ben = base["ana"], base["ben"]
    ana_winner = create_registration(ana["id"], program_id=base["program"]["id"])

    foreign = api_client.create_registration(
        _guest_seat_payload(
            ben["id"], base["program"]["id"], guest_of_registration_id=ana_winner["id"]
        ),
        TD_HEADERS,
    )
    validate_error(foreign, ApiErrorId.ERR_GUEST_LINK_INVALID)

    cancel_registration(ana_winner["id"], reason="Winner withdrew")
    cancelled_target = api_client.create_registration(
        _guest_seat_payload(
            ana["id"], base["program"]["id"], guest_of_registration_id=ana_winner["id"]
        ),
        TD_HEADERS,
    )
    validate_error(cancelled_target, ApiErrorId.ERR_GUEST_LINK_INVALID)


def test_guest_link_may_not_point_at_another_guest_seat():
    """Guest chains are impossible: the self-reference must terminate at a WINNER.

    PRD §3.6: "Omitting the link on a guest seat, pointing it at a cancelled seat, at
    another guest seat, or at a seat belonging to a different qualifier, or supplying
    a non-null link on a winner seat, all report `ERR_GUEST_LINK_INVALID`."

    Design: Corner/validations/guest_policy_rules_apply_only_to_guest_rows_and_read_the_assigned_tier_allowance
    """
    base = _guest_policy_program(platinum_guest_allowance=2)
    ana = base["ana"]
    winner = create_registration(ana["id"], program_id=base["program"]["id"])
    first_guest = validate_success(
        api_client.create_registration(
            _guest_seat_payload(
                ana["id"], base["program"]["id"], guest_of_registration_id=winner["id"]
            ),
            TD_HEADERS,
        ),
        201,
    )

    chained = api_client.create_registration(
        _guest_seat_payload(
            ana["id"],
            base["program"]["id"],
            guest_of_registration_id=first_guest["id"],
        ),
        TD_HEADERS,
    )
    validate_error(chained, ApiErrorId.ERR_GUEST_LINK_INVALID)


def test_the_linkage_rule_constrains_winner_rows_as_well_as_guest_rows():
    """A guest seat must carry the link and a winner seat must not.

    PRD §3.6: "a seat whose `registration_kind` is `WINNER` must supply either no
    `guest_of_registration_id` at all or an explicit null."

    Design: Corner/validations/guest_policy_rules_apply_only_to_guest_rows_and_read_the_assigned_tier_allowance
    """
    base = _guest_policy_program()
    ana, ben = base["ana"], base["ben"]
    ana_winner = create_registration(ana["id"], program_id=base["program"]["id"])

    unlinked_guest = api_client.create_registration(
        _guest_seat_payload(ana["id"], base["program"]["id"]),
        TD_HEADERS,
    )
    validate_error(unlinked_guest, ApiErrorId.ERR_GUEST_LINK_INVALID)

    linked_winner = api_client.create_registration(
        create_registration_payload(
            ben["id"],
            program_version(base["program"]["id"]),
            registration_kind="WINNER",
            guest_of_registration_id=ana_winner["id"],
        ),
        TD_HEADERS,
    )
    validate_error(linked_winner, ApiErrorId.ERR_GUEST_LINK_INVALID)

    rows, meta = validate_paginated(
        api_client.list_registrations(
            TD_HEADERS, params={"program_id": base["program"]["id"]}
        )
    )
    assert meta["total_count"] == 1


def test_the_guest_allowance_is_checked_before_the_guest_linkage():
    """A request breaching both rules reports the allowance failure.

    PRD §3.6: "The allowance is checked before the linkage."

    Design: Corner/validations/guest_policy_rules_apply_only_to_guest_rows_and_read_the_assigned_tier_allowance
    """
    base = _guest_policy_program()
    ana = base["ana"]
    winner = create_registration(ana["id"], program_id=base["program"]["id"])
    first_guest = validate_success(
        api_client.create_registration(
            _guest_seat_payload(
                ana["id"], base["program"]["id"], guest_of_registration_id=winner["id"]
            ),
            TD_HEADERS,
        ),
        201,
    )

    response = api_client.create_registration(
        _guest_seat_payload(
            ana["id"],
            base["program"]["id"],
            guest_of_registration_id=first_guest["id"],
        ),
        TD_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_GUEST_ALLOWANCE_EXCEEDED)
