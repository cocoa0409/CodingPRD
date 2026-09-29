"""Endpoint surface and error-catalogue reachability (PRD §2.5, §2.11, §3.6, §3.7, §4, §5)."""
from test_helpers import *  # noqa: F401,F403

PD = TEST_USERS["program_director_headers"]
SM = TEST_USERS["sourcing_manager_headers"]
CA = TEST_USERS["contract_approver_headers"]
AN = TEST_USERS["sales_ops_analyst_headers"]
TD = TEST_USERS["travel_desk_headers"]
TAX = TEST_USERS["tax_officer_headers"]

# ── Canonical design-index fixture shapes ───────────────────────────────────
PLATINUM = dict(
    tier_code="PLATINUM", tier_rank=1, qualification_threshold=250_000_000,
    budget_per_qualifier_cents=2_500_000, guest_allowance=1,
    air_cabin_class="BUSINESS", upgrade_allowance_cents=150_000, service_load_bp=1275,
)
GOLD = dict(
    tier_code="GOLD", tier_rank=2, qualification_threshold=150_000_000,
    budget_per_qualifier_cents=1_600_000, guest_allowance=1,
    air_cabin_class="PREMIUM_ECONOMY", upgrade_allowance_cents=40_000, service_load_bp=800,
)
SILVER = dict(
    tier_code="SILVER", tier_rank=4, qualification_threshold=120_000_000,
    budget_per_qualifier_cents=400_000, guest_allowance=1,
    air_cabin_class="PREMIUM_ECONOMY", upgrade_allowance_cents=40_000, service_load_bp=800,
)
LISBON = dict(
    city="Lisbon", country_code="PT", per_person_cost_cents=431_757,
    risk_score=35, air_gateway_code="LIS",
)
SEVILLE = dict(
    city="Seville", country_code="ES", per_person_cost_cents=388_000,
    risk_score=28, air_gateway_code="SVQ",
)
HOTEL_TERMS = dict(
    supplier_name="Estoril Palace", supplier_kind="HOTEL", room_block_count=12,
    contracted_nights=5, stay_start_at="2026-11-08T00:00:00Z", nightly_rate_cents=38_500,
    attrition_allowance_bp=2000, force_majeure_clause="STANDARD",
    exposure_basis="ATTRITION_BASIS",
)
SCHEDULE = [
    dict(sequence=1, due_at="2026-08-15T00:00:00Z", amount_cents=577_500, refundable_bp=10000),
    dict(sequence=2, due_at="2026-09-15T00:00:00Z", amount_cents=577_500, refundable_bp=5000),
    dict(sequence=3, due_at="2026-10-15T00:00:00Z", amount_cents=1_155_000, refundable_bp=0),
]
ANA = dict(employee_code="S-1001", full_name="Ana Reyes",
           baseline_metric=180_000_000, actual_metric=260_000_000, guest_count=1)
BEN = dict(employee_code="S-2001", full_name="Ben Ortiz",
           baseline_metric=120_000_000, actual_metric=155_000_000, guest_count=0)
ZANE = dict(employee_code="S-5003", full_name="Zane Holt",
            baseline_metric=140_000_000, actual_metric=149_999_999, guest_count=0)
ARRIVAL = "2026-11-08T00:00:00Z"
DEPARTURE = "2026-11-13T00:00:00Z"


def _sourcing_base(tier_specs=(PLATINUM, GOLD), qualifier_specs=(), budget_total_cents=5_000_000):
    """Program at SOURCING: tier ladder, Lisbon SHORTLISTED, Seville untouched."""
    program = create_program(budget_total_cents=budget_total_cents)
    tiers = [create_award_tier(program["id"], **spec) for spec in tier_specs]
    lisbon = create_destination(program["id"], **LISBON)
    seville = create_destination(program["id"], **SEVILLE)
    inspect_destination(lisbon["id"], 82)
    shortlist_destination(lisbon["id"])
    qualifiers = []
    for spec in qualifier_specs:
        qualifier = create_qualifier(program["id"], **spec)
        review_qualifier(qualifier["id"])
        qualifiers.append(qualifier)
    advance_program(program["id"], "SOURCING")
    return {
        "program": read_program(program["id"]), "tiers": tiers,
        "lisbon": lisbon, "seville": seville, "qualifiers": qualifiers,
    }


def _contracted_base(with_schedule=False, **kwargs):
    """SOURCING program driven to CONTRACTED by executing one HOTEL contract."""
    base = _sourcing_base(**kwargs)
    contract = create_contract(base["program"]["id"], base["lisbon"]["id"], **HOTEL_TERMS)
    base["milestones"] = (
        [create_milestone(contract["id"], **spec) for spec in SCHEDULE] if with_schedule else []
    )
    propose_contract(contract["id"])
    execute_contract(contract["id"])
    base["contract"] = read_contract(contract["id"])
    base["program"] = read_program(base["program"]["id"])
    base["qualifiers"] = [read_qualifier(q["id"]) for q in base["qualifiers"]]
    return base


def _registration_open_base(gross_up_policy="FULL_GROSS_UP", **kwargs):
    """CONTRACTED program with every winner NOTIFIED and the window open."""
    base = _contracted_base(**kwargs)
    notify_qualifiers(base["program"]["id"])
    lock_gross_up_policy(base["program"]["id"], gross_up_policy)
    advance_program(base["program"]["id"], "REGISTRATION_OPEN")
    base["program"] = read_program(base["program"]["id"])
    base["qualifiers"] = [read_qualifier(q["id"]) for q in base["qualifiers"]]
    return base


def _enrol(base, qualifier, kind="WINNER", confirm=True, **overrides):
    """Enrol a NOTIFIED qualifier and walk the seat as far as asked."""
    registration = create_registration(
        qualifier["id"], program_id=base["program"]["id"],
        registration_kind=kind, arrival_date=ARRIVAL, departure_date=DEPARTURE,
        **overrides,
    )
    respond_registration(registration["id"], qualifier["id"], "ACCEPT", waiver_signed=True)
    if confirm:
        confirm_registration(registration["id"])
    return read_registration(registration["id"])


def test_design_stage_rows_read_back_identical_to_their_create_response():
    """A program, tier, destination and qualifier each read back unchanged by id.

    PRD §4: "Endpoints that mint a new resource return HTTP 201 with the created
    row in `data`; every other successful call returns HTTP 200, and endpoints
    that mutate an existing resource return the updated row."

    Design: Corner/endpoints/crud_surface_is_create_read_list_only_and_every_row_reads_back_unchanged
    """
    program = create_program(budget_total_cents=5_000_000)
    tier = create_award_tier(program["id"], **PLATINUM)
    destination = create_destination(program["id"], **LISBON)
    qualifier = create_qualifier(program["id"], **ANA)

    assert validate_success(api_client.get_program(program["id"], PD)) == program
    assert validate_success(api_client.get_award_tier(tier["id"], PD)) == tier
    assert validate_success(api_client.get_destination(destination["id"], SM)) == destination
    assert validate_success(api_client.get_qualifier(qualifier["id"], AN)) == qualifier
    assert_program(program)
    assert_award_tier(tier)
    assert_destination(destination)
    assert_qualifier(qualifier)


def test_award_tier_carries_no_updated_at_and_no_version_while_siblings_carry_both():
    """AwardTier is the one entity that opts out of the common mutable fields.

    PRD §2.4: "`AwardTier` is the single exception: a tier is immutable once
    created, has no update or state-change operation of any kind, and therefore
    carries only `id` and `created_at` — both `updated_at` and `version` are
    absent from an `AwardTier` payload entirely."

    Design: Corner/endpoints/crud_surface_is_create_read_list_only_and_every_row_reads_back_unchanged
    """
    program = create_program(budget_total_cents=5_000_000)
    tier = read_tier = validate_success(
        api_client.get_award_tier(create_award_tier(program["id"], **GOLD)["id"], PD)
    )
    assert "updated_at" not in read_tier
    assert "version" not in read_tier
    assert set(tier) >= {"id", "created_at", "tier_code", "tier_rank"}

    destination = create_destination(program["id"], **LISBON)
    qualifier = create_qualifier(program["id"], **BEN)
    for row, label in ((program, "Program"), (destination, "Destination"), (qualifier, "Qualifier")):
        assert "updated_at" in row and "version" in row, f"{label} must carry both common fields"
        assert_version_is(row, 1, label)


def test_sourcing_stage_rows_read_back_identical_to_their_create_response():
    """A DRAFT contract and a SCHEDULED milestone read back unchanged by id.

    PRD §3.4: "A new contract lands in `DRAFT` with `round_count` 0,
    `room_nights_blocked`, `room_nights_confirmed` and `room_nights_available`
    all 0, `attrition_posture` `CLEAR`, and null values for
    `last_proposed_by_user_id`, `last_countered_by_user_id`,
    `executed_by_user_id`, `executed_at` and `withdrawal_reason`."

    Design: Corner/endpoints/crud_surface_is_create_read_list_only_and_every_row_reads_back_unchanged
    """
    base = _sourcing_base()
    contract = create_contract(base["program"]["id"], base["lisbon"]["id"], **HOTEL_TERMS)
    milestone = create_milestone(contract["id"], **SCHEDULE[0])

    assert validate_success(api_client.get_supplier_contract(contract["id"], SM)) == contract
    assert validate_success(api_client.get_deposit_milestone(milestone["id"], CA)) == milestone
    assert_supplier_contract(contract)
    assert_deposit_milestone(milestone)
    assert_version_is(contract, 1, "SupplierContract")
    assert_version_is(milestone, 1, "DepositMilestone")


def test_registration_reads_back_identical_at_invited():
    """A freshly minted seat reads back byte-identical while still INVITED.

    PRD §3.6: "A fresh seat lands with `attendance_status` `INVITED`,
    `air_status` `NOT_REQUESTED`, `waiver_on_file` false, `room_nights` 0,
    `cost_cents` 0, a null `air_cabin_class`, `air_deviation_pre_days` and
    `air_deviation_post_days` both 0, `air_base_fare_cents`,
    `air_upgrade_cost_cents`, `air_deviation_fee_cents`, `air_change_count` and
    `air_change_fee_total_cents` all 0, and a null `satisfaction_score` and
    `cancellation_reason`."

    Design: Corner/endpoints/crud_surface_is_create_read_list_only_and_every_row_reads_back_unchanged
    """
    base = _registration_open_base(qualifier_specs=(ANA,))
    registration = create_registration(
        base["qualifiers"][0]["id"], program_id=base["program"]["id"],
        arrival_date=ARRIVAL, departure_date=DEPARTURE,
    )
    assert validate_success(api_client.get_registration(registration["id"], TD)) == registration
    assert_registration(registration)
    assert_version_is(registration, 1, "Registration")
    assert registration["attendance_status"] == "INVITED"
    assert registration["program_id"] == base["program"]["id"]


def test_activity_and_signup_read_back_identical_after_creation():
    """An OPEN activity and its first signup both read back unchanged.

    PRD §3.8: "A new activity lands `OPEN` with `booked_count` and
    `waitlist_count` both 0."

    Design: Corner/endpoints/crud_surface_is_create_read_list_only_and_every_row_reads_back_unchanged
    """
    base = _registration_open_base(qualifier_specs=(ANA,))
    registration = _enrol(base, base["qualifiers"][0])
    advance_program(base["program"]["id"], "ONSITE")

    activity = create_activity(base["program"]["id"], capacity=5, risk_level="LOW")
    assert validate_success(api_client.get_onsite_activity(activity["id"], TD)) == activity
    assert_onsite_activity(activity)
    assert_signup_counters(activity, 0, 0)

    signup = create_signup(activity["id"], registration["id"])
    assert validate_success(api_client.get_activity_signup(signup["id"], TD)) == signup
    assert_activity_signup(signup)
    assert_version_is(signup, 1, "ActivitySignup")


def test_tax_award_report_reads_back_identical_at_draft():
    """A DRAFT taxable award report reads back unchanged by id.

    PRD §3.9: "The report lands in `DRAFT` with a null `filed_by_user_id`,
    `filed_at`, `voided_by_user_id` and `void_reason`."

    Design: Corner/endpoints/crud_surface_is_create_read_list_only_and_every_row_reads_back_unchanged
    """
    base = _registration_open_base(qualifier_specs=(BEN,))
    _enrol(base, base["qualifiers"][0])
    advance_program(base["program"]["id"], "ONSITE")
    advance_program(base["program"]["id"], "RECONCILED")

    report = draft_tax_report(base["qualifiers"][0]["id"], 2026)
    assert validate_success(api_client.get_tax_award_report(report["id"], TAX)) == report
    assert_tax_award_report(report)
    assert report["status"] == "DRAFT"
    assert report["filed_by_user_id"] is None
    assert report["filed_at"] is None
    assert_reported_value_identity(report)


def test_every_collection_lists_its_rows_through_the_array_envelope():
    """All ten collections answer a filtered list with the array envelope.

    PRD §2.3: "The `meta` object of a list response carries `limit` and `offset`
    as they were resolved for the request (defaults included), `total_count` as
    the number of rows matching the filters before pagination is applied, and
    `has_more` as true when the resolved `offset` plus the number of returned
    rows is less than `total_count`."

    Design: Corner/endpoints/crud_surface_is_create_read_list_only_and_every_row_reads_back_unchanged
    """
    base = _registration_open_base(qualifier_specs=(ANA,), with_schedule=True)
    program_id = base["program"]["id"]
    registration = _enrol(base, base["qualifiers"][0])
    advance_program(program_id, "ONSITE")
    activity = create_activity(program_id, capacity=5)
    signup = create_signup(activity["id"], registration["id"])
    close_activity(activity["id"])
    advance_program(program_id, "RECONCILED")
    report = draft_tax_report(base["qualifiers"][0]["id"], 2026)

    probes = [
        (api_client.list_programs(PD, {"fiscal_year": base["program"]["fiscal_year"]}), 1),
        (api_client.list_award_tiers(PD, {"program_id": program_id}), 2),
        (api_client.list_qualifiers(AN, {"program_id": program_id}), 1),
        (api_client.list_destinations(SM, {"program_id": program_id}), 2),
        (api_client.list_supplier_contracts(SM, {"program_id": program_id}), 1),
        (api_client.list_deposit_milestones(CA, {"contract_id": base["contract"]["id"]}), 3),
        (api_client.list_registrations(TD, {"program_id": program_id}), 1),
        (api_client.list_onsite_activities(TD, {"program_id": program_id}), 1),
        (api_client.list_activity_signups(TD, {"registration_id": registration["id"]}), 1),
        (api_client.list_tax_award_reports(TAX, {"qualifier_id": base["qualifiers"][0]["id"]}), 1),
    ]
    for response, expected_total in probes:
        rows, meta = validate_paginated(response)
        assert meta["total_count"] == expected_total, (
            f"expected total_count {expected_total}, got {meta['total_count']}"
        )
        assert meta["limit"] == 10 and meta["offset"] == 0
        assert meta["has_more"] is False
        assert len(rows) == expected_total
    assert signup["id"] in [r["id"] for r in validate_paginated(
        api_client.list_activity_signups(TD, {"activity_id": activity["id"]})
    )[0]]
    assert report["id"] in [r["id"] for r in validate_paginated(
        api_client.list_tax_award_reports(TAX, {"tax_year": 2026})
    )[0]]


def test_a_narrow_page_reports_has_more_and_orders_by_created_at_ascending():
    """A limit of 1 over three milestones pages in creation order.

    PRD §2.3: "List responses always return their rows sorted by `created_at`
    ascending, so that a page boundary is stable across repeated reads."

    Design: Corner/endpoints/crud_surface_is_create_read_list_only_and_every_row_reads_back_unchanged
    """
    base = _sourcing_base()
    contract = create_contract(base["program"]["id"], base["lisbon"]["id"], **HOTEL_TERMS)
    created = [create_milestone(contract["id"], **spec) for spec in SCHEDULE]

    seen = []
    for offset in (0, 1, 2):
        rows, meta = validate_paginated(api_client.list_deposit_milestones(
            CA, {"contract_id": contract["id"], "limit": 1, "offset": offset}
        ))
        assert meta["limit"] == 1 and meta["offset"] == offset
        assert meta["total_count"] == 3
        assert meta["has_more"] is (offset < 2)
        assert len(rows) == 1
        seen.append(rows[0])
    assert [row["id"] for row in seen] == [row["id"] for row in created]
    assert [row["sequence"] for row in seen] == [1, 2, 3]

    empty_rows, empty_meta = validate_paginated(api_client.list_deposit_milestones(
        CA, {"contract_id": contract["id"], "offset": 3}
    ))
    assert empty_rows == []
    assert empty_meta["total_count"] == 3
    assert empty_meta["has_more"] is False


def test_an_award_tier_has_no_edit_and_no_retire_operation():
    """PUT, PATCH and DELETE against a tier row change nothing about it.

    PRD §3.1: "A tier is **immutable**: there is no operation that edits or
    retires one, which is why an `AwardTier` payload has no `version` and no
    `updated_at` at all."

    Design: Corner/endpoints/crud_surface_is_create_read_list_only_and_every_row_reads_back_unchanged
    """
    program = create_program(budget_total_cents=5_000_000)
    tier = create_award_tier(program["id"], **PLATINUM)

    for method, payload in (
        ("PUT", {"tier_rank": 9}),
        ("PATCH", {"tier_rank": 9}),
        ("DELETE", None),
    ):
        response = api_client._request(method, f"/award-tiers/{tier['id']}", payload, PD)
        assert not (200 <= response.status_code < 300), (
            f"{method} /award-tiers/{{id}} must not be a routed success, got {response.status_code}"
        )

    assert validate_success(api_client.get_award_tier(tier["id"], PD)) == tier
    rows, meta = validate_paginated(api_client.list_award_tiers(PD, {"program_id": program["id"]}))
    assert meta["total_count"] == 1
    assert rows[0] == tier


def test_repeated_reads_never_mutate_the_row_they_return():
    """Three consecutive GETs of the same rows return identical bytes.

    PRD §2.4: "`version`, an integer that starts at 1 when the row is created and
    increases by exactly 1 on every mutation of that row, whether the mutation
    came from a direct request or from a cascade triggered elsewhere."

    Design: Corner/endpoints/crud_surface_is_create_read_list_only_and_every_row_reads_back_unchanged
    """
    base = _contracted_base(qualifier_specs=(ANA,))
    program_id = base["program"]["id"]
    reads = [
        (
            validate_success(api_client.get_program(program_id, PD)),
            validate_success(api_client.get_supplier_contract(base["contract"]["id"], SM)),
            validate_success(api_client.get_destination(base["lisbon"]["id"], SM)),
            validate_success(api_client.get_qualifier(base["qualifiers"][0]["id"], AN)),
        )
        for _ in range(3)
    ]
    assert reads[0] == reads[1] == reads[2]
    program, contract, destination, qualifier = reads[0]
    assert_budget_conserved(program)
    assert_room_nights_conserved(contract)
    assert destination["status"] == "SELECTED"
    assert qualifier["award_status"] == "QUALIFIED"


def test_site_inspection_stamps_the_acting_user_and_the_logical_clock():
    """The inspection stamps sm-01 and the instant the clock was standing at.

    PRD §3.3: "The sourcing manager supplies an `inspection_score` from 0 to 100;
    the destination moves `NOT_INSPECTED → INSPECTED`, the score is stored,
    `inspected_by_user_id` is stamped with the acting `X-User-ID`, `inspected_at`
    is stamped from the logical clock, and the destination's `version`
    increments."

    Design: Corner/endpoints/site_inspection_action_stamps_actor_and_clock_then_locks_out_repeats
    """
    set_logical_clock("2026-08-05T09:30:00Z")
    program = create_program(budget_total_cents=5_000_000)
    destination = create_destination(program["id"], **LISBON)
    assert destination["inspection_status"] == "NOT_INSPECTED"
    assert destination["inspection_score"] is None
    assert destination["inspected_by_user_id"] is None
    assert destination["inspected_at"] is None

    inspected = inspect_destination(destination["id"], 82)
    assert inspected["inspection_status"] == "INSPECTED"
    assert inspected["inspection_score"] == 82
    assert inspected["inspected_by_user_id"] == USER_IDS["SOURCING_MANAGER"]
    assert_instant_equals(inspected["inspected_at"], "2026-08-05T09:30:00Z", "inspected_at")
    assert_version_is(inspected, 2, "Destination")
    assert inspected["status"] == "CANDIDATE", "inspection must not touch the selection dimension"
    assert read_destination(destination["id"]) == inspected


def test_a_second_site_inspection_is_refused_and_overwrites_nothing():
    """The recorded score is not revisable by a second inspection call.

    PRD §3.3: "A second inspection of the same destination is rejected with
    `ERR_DESTINATION_STATE_INVALID` — the score is recorded once and is not
    revisable."

    Design: Corner/endpoints/site_inspection_action_stamps_actor_and_clock_then_locks_out_repeats
    """
    set_logical_clock("2026-08-05T09:30:00Z")
    program = create_program(budget_total_cents=5_000_000)
    destination = create_destination(program["id"], **LISBON)
    first = inspect_destination(destination["id"], 82)

    set_logical_clock("2026-08-06T11:00:00Z")
    response = api_client.site_inspect_destination(
        destination["id"], {"inspection_score": 95}, SM
    )
    validate_error(response, ApiErrorId.ERR_DESTINATION_STATE_INVALID)

    after = read_destination(destination["id"])
    assert after == first
    assert after["inspection_score"] == 82
    assert_instant_equals(after["inspected_at"], "2026-08-05T09:30:00Z", "inspected_at")
    assert_version_is(after, 2, "Destination")


def test_shortlisting_advances_only_the_selection_dimension():
    """A successful shortlist promotes selection and leaves inspection frozen.

    PRD §3.3: "On success the destination moves `CANDIDATE → SHORTLISTED` and its
    `version` increments."

    Design: Corner/endpoints/site_inspection_action_stamps_actor_and_clock_then_locks_out_repeats
    """
    set_logical_clock("2026-08-05T09:30:00Z")
    program = create_program(budget_total_cents=5_000_000)
    destination = create_destination(program["id"], **LISBON)
    inspected = inspect_destination(destination["id"], 82)

    set_logical_clock("2026-08-07T08:00:00Z")
    shortlisted = shortlist_destination(destination["id"])
    assert shortlisted["status"] == "SHORTLISTED"
    assert shortlisted["inspection_status"] == "INSPECTED"
    assert shortlisted["inspection_score"] == inspected["inspection_score"]
    assert shortlisted["inspected_by_user_id"] == inspected["inspected_by_user_id"]
    assert_instant_equals(shortlisted["inspected_at"], "2026-08-05T09:30:00Z", "inspected_at")
    assert_version_is(shortlisted, 3, "Destination")


def test_shortlisting_a_never_inspected_candidate_is_refused():
    """The inspection dimension gates the selection dimension, not the reverse.

    PRD §3.3: "It requires the program to be in `DESIGN` or `SOURCING`, the
    destination to still be a `CANDIDATE`, and its `inspection_status` to be
    `INSPECTED`; a destination that is not a candidate or has never been
    inspected reports `ERR_DESTINATION_STATE_INVALID`."

    Design: Corner/endpoints/site_inspection_action_stamps_actor_and_clock_then_locks_out_repeats
    """
    program = create_program(budget_total_cents=5_000_000)
    destination = create_destination(program["id"], **LISBON)

    validate_error(
        api_client.shortlist_destination(destination["id"], SM),
        ApiErrorId.ERR_DESTINATION_STATE_INVALID,
    )
    after = read_destination(destination["id"])
    assert after == destination
    assert_version_is(after, 1, "Destination")


def test_re_shortlisting_an_already_shortlisted_destination_is_refused():
    """`SHORTLISTED` is no longer a candidate, so the promotion cannot repeat.

    PRD §3.3: "It requires the program to be in `DESIGN` or `SOURCING`, the
    destination to still be a `CANDIDATE`, and its `inspection_status` to be
    `INSPECTED`; a destination that is not a candidate or has never been
    inspected reports `ERR_DESTINATION_STATE_INVALID`."

    Design: Corner/endpoints/site_inspection_action_stamps_actor_and_clock_then_locks_out_repeats
    """
    program = create_program(budget_total_cents=5_000_000)
    destination = create_destination(program["id"], **LISBON)
    inspect_destination(destination["id"], 82)
    shortlisted = shortlist_destination(destination["id"])

    validate_error(
        api_client.shortlist_destination(destination["id"], SM),
        ApiErrorId.ERR_DESTINATION_STATE_INVALID,
    )
    assert read_destination(destination["id"]) == shortlisted


def test_inspecting_an_unknown_destination_is_a_not_found():
    """Path existence is resolved before either destination state dimension.

    PRD §2.8: "**Path existence** — every templated id in the URL resolves to an
    existing row, validated strictly left to right, so the leftmost unresolvable
    segment decides the error."

    Design: Corner/endpoints/site_inspection_action_stamps_actor_and_clock_then_locks_out_repeats
    """
    validate_error(
        api_client.site_inspect_destination(NON_EXISTENT_UUID, {"inspection_score": 82}, SM),
        ApiErrorId.ERR_DESTINATION_NOT_FOUND,
    )
    validate_error(
        api_client.shortlist_destination(NON_EXISTENT_UUID, SM),
        ApiErrorId.ERR_DESTINATION_NOT_FOUND,
    )


def test_the_two_destination_state_dimensions_filter_independently():
    """Selection and inspection are separate filterable axes on the collection.

    PRD §2.3: "Destinations may be filtered by `program_id`, `status` and
    `inspection_status`."

    Design: Corner/endpoints/site_inspection_action_stamps_actor_and_clock_then_locks_out_repeats
    """
    program = create_program(budget_total_cents=5_000_000)
    lisbon = create_destination(program["id"], **LISBON)
    seville = create_destination(program["id"], **SEVILLE)
    inspect_destination(lisbon["id"], 82)
    shortlist_destination(lisbon["id"])
    inspect_destination(seville["id"], 74)

    def ids(**params):
        rows, _ = validate_paginated(
            api_client.list_destinations(SM, dict(program_id=program["id"], **params))
        )
        return sorted(row["id"] for row in rows)

    assert ids(inspection_status="INSPECTED") == sorted([lisbon["id"], seville["id"]])
    assert ids(inspection_status="NOT_INSPECTED") == []
    assert ids(status="SHORTLISTED") == [lisbon["id"]]
    assert ids(status="CANDIDATE") == [seville["id"]]
    assert ids(status="CANDIDATE", inspection_status="INSPECTED") == [seville["id"]]
    assert ids(status="SHORTLISTED", inspection_status="NOT_INSPECTED") == []


def test_notification_reports_partial_counts_instead_of_failing_on_ineligible_rows():
    """Two winners and one disqualified salesperson give 2 notified, 1 skipped.

    PRD §3.6: "Qualifiers in any other award state — still `PENDING_REVIEW`,
    already `NOTIFIED`, `DISQUALIFIED`, `REGISTERED`, `TRAVELLED` or `WITHDRAWN`
    — are **skipped, not errored**, so a second notification run is harmless."

    Design: Corner/endpoints/notify_qualifiers_bulk_action_reports_partial_skip_counts_and_never_errors
    """
    base = _contracted_base(qualifier_specs=(ANA, BEN, ZANE))
    ana, ben, zane = base["qualifiers"]
    assert [q["award_status"] for q in (ana, ben, zane)] == [
        "QUALIFIED", "QUALIFIED", "DISQUALIFIED",
    ]

    summary = validate_success(api_client.notify_qualifiers(base["program"]["id"], PD))
    assert summary["notified_count"] == 2
    assert summary["skipped_count"] == 1
    assert sorted(summary["notified_qualifier_ids"]) == sorted([ana["id"], ben["id"]])
    assert summary["skipped_qualifier_ids"] == [zane["id"]]
    assert read_qualifier(ana["id"])["award_status"] == "NOTIFIED"
    assert read_qualifier(ben["id"])["award_status"] == "NOTIFIED"
    assert read_qualifier(zane["id"])["award_status"] == "DISQUALIFIED"


def test_every_qualifier_lands_in_exactly_one_notification_array_in_created_at_order():
    """The two arrays partition the cohort and each is in creation order.

    PRD §3.6: "The response reports `notified_count` and `skipped_count` as
    integers and `notified_qualifier_ids` and `skipped_qualifier_ids` as arrays of
    qualifier ids; every qualifier of the program appears in exactly one of the
    two arrays, and both arrays are ordered by the qualifiers' `created_at`
    ascending."

    Design: Corner/endpoints/notify_qualifiers_bulk_action_reports_partial_skip_counts_and_never_errors
    """
    base = _contracted_base(qualifier_specs=(ZANE, ANA, BEN))
    zane, ana, ben = base["qualifiers"]

    summary = validate_success(api_client.notify_qualifiers(base["program"]["id"], PD))
    assert summary["notified_qualifier_ids"] == [ana["id"], ben["id"]]
    assert summary["skipped_qualifier_ids"] == [zane["id"]]
    partition = summary["notified_qualifier_ids"] + summary["skipped_qualifier_ids"]
    assert sorted(partition) == sorted([zane["id"], ana["id"], ben["id"]])
    assert len(partition) == len(set(partition)) == 3
    assert summary["notified_count"] == len(summary["notified_qualifier_ids"])
    assert summary["skipped_count"] == len(summary["skipped_qualifier_ids"])


def test_notification_stamps_notified_at_from_the_clock_and_leaves_skipped_rows_null():
    """Only the notified rows take the stamp and the version bump.

    PRD §3.6: "Every qualifier of the program whose `award_status` is `QUALIFIED`
    moves `QUALIFIED → NOTIFIED`, has `notified_at` stamped from the logical
    clock, and has its `version` incremented."

    Design: Corner/endpoints/notify_qualifiers_bulk_action_reports_partial_skip_counts_and_never_errors
    """
    base = _contracted_base(qualifier_specs=(ANA, ZANE))
    ana, zane = base["qualifiers"]
    assert ana["notified_at"] is None and zane["notified_at"] is None

    set_logical_clock("2026-08-20T14:05:00Z")
    validate_success(api_client.notify_qualifiers(base["program"]["id"], PD))

    notified = read_qualifier(ana["id"])
    skipped = read_qualifier(zane["id"])
    assert_instant_equals(notified["notified_at"], "2026-08-20T14:05:00Z", "notified_at")
    assert notified["version"] == ana["version"] + 1
    assert skipped["notified_at"] is None
    assert skipped["version"] == zane["version"], "a skipped row is not re-versioned"


def test_a_fully_redundant_notification_run_succeeds_with_nothing_left_to_notify():
    """A second run reports 0 notified and 2 skipped rather than an error.

    PRD §3.6: "**Notification is a bulk operation with skip semantics**,
    permitted while the program is `CONTRACTED` or `REGISTRATION_OPEN`."

    Design: Corner/endpoints/notify_qualifiers_bulk_action_reports_partial_skip_counts_and_never_errors
    """
    base = _contracted_base(qualifier_specs=(ANA, ZANE))
    ana, zane = base["qualifiers"]
    validate_success(api_client.notify_qualifiers(base["program"]["id"], PD))
    after_first = read_qualifier(ana["id"])

    second = validate_success(api_client.notify_qualifiers(base["program"]["id"], PD))
    assert second["notified_count"] == 0
    assert second["skipped_count"] == 2
    assert second["notified_qualifier_ids"] == []
    assert sorted(second["skipped_qualifier_ids"]) == sorted([ana["id"], zane["id"]])
    assert read_qualifier(ana["id"]) == after_first, "a redundant run restamps nothing"


def test_a_redundant_notification_run_does_not_restamp_an_already_notified_winner():
    """Moving the clock and re-running leaves the original stamp in place.

    PRD §3.6: "Qualifiers in any other award state — still `PENDING_REVIEW`,
    already `NOTIFIED`, `DISQUALIFIED`, `REGISTERED`, `TRAVELLED` or `WITHDRAWN`
    — are **skipped, not errored**, so a second notification run is harmless."

    Design: Corner/endpoints/notify_qualifiers_bulk_action_reports_partial_skip_counts_and_never_errors
    """
    base = _contracted_base(qualifier_specs=(ANA,))
    ana = base["qualifiers"][0]
    set_logical_clock("2026-08-20T14:05:00Z")
    validate_success(api_client.notify_qualifiers(base["program"]["id"], PD))
    first_read = read_qualifier(ana["id"])

    set_logical_clock("2026-09-01T09:00:00Z")
    validate_success(api_client.notify_qualifiers(base["program"]["id"], PD))
    second_read = read_qualifier(ana["id"])

    assert second_read == first_read
    assert_instant_equals(second_read["notified_at"], "2026-08-20T14:05:00Z", "notified_at")


def test_notification_is_reserved_to_the_program_director():
    """A sourcing manager cannot run the bulk notification.

    PRD §2.8: "**Role authorization** — the supplied role appears in the called
    endpoint's authorized-role list. Applies to every endpoint. Violation:
    `ERR_ROLE_NOT_PERMITTED`, HTTP 403."

    Design: Corner/endpoints/notify_qualifiers_bulk_action_reports_partial_skip_counts_and_never_errors
    """
    base = _contracted_base(qualifier_specs=(ANA,))
    ana = base["qualifiers"][0]

    for headers in (SM, CA, AN, TD, TAX):
        validate_error(
            api_client.notify_qualifiers(base["program"]["id"], headers),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        )
    assert read_qualifier(ana["id"]) == ana


def test_notification_is_still_permitted_once_registration_is_open():
    """The bulk action spans both permitted program statuses.

    PRD §3.6: "**Notification is a bulk operation with skip semantics**,
    permitted while the program is `CONTRACTED` or `REGISTRATION_OPEN`."

    Design: Corner/endpoints/notify_qualifiers_bulk_action_reports_partial_skip_counts_and_never_errors
    """
    base = _contracted_base(qualifier_specs=(ANA, BEN, ZANE))
    ana, ben, zane = base["qualifiers"]
    lock_gross_up_policy(base["program"]["id"], "FULL_GROSS_UP")
    advance_program(base["program"]["id"], "REGISTRATION_OPEN")

    summary = validate_success(api_client.notify_qualifiers(base["program"]["id"], PD))
    assert summary["notified_count"] == 2
    assert summary["skipped_count"] == 1
    assert sorted(summary["notified_qualifier_ids"]) == sorted([ana["id"], ben["id"]])
    assert read_program(base["program"]["id"])["status"] == "REGISTRATION_OPEN"


def test_a_contract_may_not_name_a_destination_from_another_program():
    """A cross-program destination link is a scope mismatch, not a 404.

    PRD §2.11: "A supplier contract's `destination_id` must name a destination
    belonging to the same program as the contract's `program_id`."

    Design: Corner/endpoints/cross_reference_links_require_both_rows_and_scope_agreement_across_aggregates
    """
    home = _sourcing_base()
    other = _sourcing_base()

    response = api_client.create_supplier_contract(
        create_supplier_contract_payload(
            home["program"]["id"], other["lisbon"]["id"], **HOTEL_TERMS
        ),
        SM,
    )
    validate_error(response, ApiErrorId.ERR_PROGRAM_SCOPE_MISMATCH)

    _, meta = validate_paginated(
        api_client.list_supplier_contracts(SM, {"program_id": home["program"]["id"]})
    )
    assert meta["total_count"] == 0, "a refused create must persist no row"
    contract = create_contract(home["program"]["id"], home["lisbon"]["id"], **HOTEL_TERMS)
    assert contract["destination_id"] == home["lisbon"]["id"]


def test_a_dangling_destination_link_is_a_not_found_before_it_is_a_scope_mismatch():
    """Body foreign-key existence (priority 5) outranks scope agreement (31).

    PRD §2.8: "**Body foreign-key existence** — every foreign key supplied in the
    request body resolves to an existing row, validated in the order the fields
    are listed in that endpoint's input."

    Design: Corner/endpoints/cross_reference_links_require_both_rows_and_scope_agreement_across_aggregates
    """
    home = _sourcing_base()

    validate_error(
        api_client.create_supplier_contract(
            create_supplier_contract_payload(
                home["program"]["id"], NON_EXISTENT_UUID, **HOTEL_TERMS
            ),
            SM,
        ),
        ApiErrorId.ERR_DESTINATION_NOT_FOUND,
    )
    validate_error(
        api_client.create_supplier_contract(
            create_supplier_contract_payload(
                NON_EXISTENT_UUID, home["lisbon"]["id"], **HOTEL_TERMS
            ),
            SM,
        ),
        ApiErrorId.ERR_PROGRAM_NOT_FOUND,
    )
    _, meta = validate_paginated(
        api_client.list_supplier_contracts(SM, {"program_id": home["program"]["id"]})
    )
    assert meta["total_count"] == 0


def test_a_tax_report_year_must_match_the_programs_fiscal_year():
    """The report's `tax_year` is scope-checked against the owning program.

    PRD §2.11: "A tax award report's `tax_year` must equal the `fiscal_year` of
    the program behind the referenced qualifier."

    Design: Corner/endpoints/cross_reference_links_require_both_rows_and_scope_agreement_across_aggregates
    """
    base = _registration_open_base(qualifier_specs=(BEN,), gross_up_policy="FLAT_SUPPLEMENTAL")
    ben = base["qualifiers"][0]
    _enrol(base, ben)
    advance_program(base["program"]["id"], "ONSITE")
    advance_program(base["program"]["id"], "RECONCILED")
    assert base["program"]["fiscal_year"] == 2026

    validate_error(
        api_client.create_tax_award_report(
            create_tax_award_report_payload(ben["id"], tax_year=2027), TAX
        ),
        ApiErrorId.ERR_PROGRAM_SCOPE_MISMATCH,
    )
    validate_error(
        api_client.create_tax_award_report(
            create_tax_award_report_payload(NON_EXISTENT_UUID, tax_year=2026), TAX
        ),
        ApiErrorId.ERR_QUALIFIER_NOT_FOUND,
    )
    _, meta = validate_paginated(api_client.list_tax_award_reports(TAX, {"qualifier_id": ben["id"]}))
    assert meta["total_count"] == 0

    report = validate_success(
        api_client.create_tax_award_report(
            create_tax_award_report_payload(ben["id"], tax_year=2026), TAX
        ),
        expected_status=201,
    )
    assert report["tax_year"] == 2026
    assert report["status"] == "DRAFT"


def test_a_signup_may_not_pair_an_activity_and_a_seat_from_different_programs():
    """Both sides of a signup must live in the same program.

    PRD §2.11: "An activity signup's activity and registration must belong to the
    same program."

    Design: Corner/endpoints/cross_reference_links_require_both_rows_and_scope_agreement_across_aggregates
    """
    first = _registration_open_base(qualifier_specs=(ANA,))
    first_seat = _enrol(first, first["qualifiers"][0])
    advance_program(first["program"]["id"], "ONSITE")
    first_activity = create_activity(first["program"]["id"], capacity=5)

    second = _registration_open_base(qualifier_specs=(BEN,))
    second_seat = _enrol(second, second["qualifiers"][0])
    advance_program(second["program"]["id"], "ONSITE")

    validate_error(
        api_client.create_activity_signup(
            create_activity_signup_payload(
                first_activity["id"], second_seat["id"], activity_version(first_activity["id"])
            ),
            TD,
        ),
        ApiErrorId.ERR_PROGRAM_SCOPE_MISMATCH,
    )
    assert_signup_counters(read_activity(first_activity["id"]), 0, 0)

    signup = create_signup(first_activity["id"], first_seat["id"])
    assert signup["status"] == "BOOKED"
    assert_signup_counters(read_activity(first_activity["id"]), 1, 0)


def test_a_guest_seat_links_to_its_winner_and_inherits_the_programs_scope():
    """The guest link is navigable from both ends and never crosses a program.

    PRD §3.6: "The seat's `program_id` is not a client input: it is denormalised
    from the referenced qualifier's own `program_id`, and any value the client
    sends for it is ignored."

    Design: Corner/endpoints/cross_reference_links_require_both_rows_and_scope_agreement_across_aggregates
    """
    base = _registration_open_base(qualifier_specs=(ANA,))
    other = _registration_open_base(qualifier_specs=(BEN,))
    ana = base["qualifiers"][0]

    payload = create_registration_payload(
        ana["id"], program_version(base["program"]["id"]),
        arrival_date=ARRIVAL, departure_date=DEPARTURE,
        program_id=other["program"]["id"],
    )
    winner = validate_success(api_client.create_registration(payload, TD), expected_status=201)
    assert winner["program_id"] == base["program"]["id"], "client-supplied program_id is ignored"
    guest = create_registration(
        ana["id"], program_id=base["program"]["id"], registration_kind="GUEST",
        guest_of_registration_id=winner["id"], arrival_date=ARRIVAL, departure_date=DEPARTURE,
    )
    assert guest["program_id"] == base["program"]["id"]
    assert guest["guest_of_registration_id"] == winner["id"]
    assert winner["guest_of_registration_id"] is None

    rows, meta = validate_paginated(
        api_client.list_registrations(TD, {"guest_of_registration_id": winner["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == guest["id"]
    _, other_meta = validate_paginated(
        api_client.list_registrations(TD, {"program_id": other["program"]["id"]})
    )
    assert other_meta["total_count"] == 0


def test_a_body_foreign_key_that_names_no_program_is_a_program_not_found():
    """Every body FK is resolved before the endpoint's own rules run.

    PRD §2.8: "**Body foreign-key existence** — every foreign key supplied in the
    request body resolves to an existing row, validated in the order the fields
    are listed in that endpoint's input."

    Design: Corner/endpoints/cross_reference_links_require_both_rows_and_scope_agreement_across_aggregates
    """
    validate_error(
        api_client.create_award_tier(create_award_tier_payload(NON_EXISTENT_UUID, **PLATINUM), PD),
        ApiErrorId.ERR_PROGRAM_NOT_FOUND,
    )
    validate_error(
        api_client.create_qualifier(create_qualifier_payload(NON_EXISTENT_UUID, **ANA), AN),
        ApiErrorId.ERR_PROGRAM_NOT_FOUND,
    )
    validate_error(
        api_client.create_destination(create_destination_payload(NON_EXISTENT_UUID, **LISBON), SM),
        ApiErrorId.ERR_PROGRAM_NOT_FOUND,
    )
    validate_error(
        api_client.create_onsite_activity(
            create_onsite_activity_payload(NON_EXISTENT_UUID), TD
        ),
        ApiErrorId.ERR_PROGRAM_NOT_FOUND,
    )
    validate_error(
        api_client.create_deposit_milestone(
            create_deposit_milestone_payload(NON_EXISTENT_UUID), SM
        ),
        ApiErrorId.ERR_CONTRACT_NOT_FOUND,
    )


def _onsite_one_traveller_one_bystander():
    """ONSITE program: Ana notified but never enrolled, Ben confirmed and surveyed."""
    base = _registration_open_base(
        qualifier_specs=(ANA, BEN), gross_up_policy="FLAT_SUPPLEMENTAL"
    )
    ana, ben = base["qualifiers"]
    seat = _enrol(base, ben)
    advance_program(base["program"]["id"], "ONSITE")
    survey_registration(seat["id"], 8)
    base["ana"] = read_qualifier(ana["id"])
    base["ben"] = read_qualifier(ben["id"])
    base["seat"] = read_registration(seat["id"])
    base["program"] = read_program(base["program"]["id"])
    return base


def test_measurement_at_onsite_reports_no_travelling_cohort_yet():
    """Sales lift stays null until somebody is actually `TRAVELLED`.

    PRD §3.9: "If the cohort is empty, or if the baseline total is 0,
    `sales_lift_pct` is null."

    Design: Corner/endpoints/closing_a_program_is_conditional_on_every_taxable_award_being_reported
    """
    base = _onsite_one_traveller_one_bystander()

    measurement = validate_success(
        api_client.get_program_measurement(base["program"]["id"], PD)
    )
    assert measurement["program_id"] == base["program"]["id"]
    assert measurement["sales_lift_pct"] is None
    assert measurement["travelled_count"] == 0
    assert measurement["qualified_count"] == 2
    assert measurement["satisfaction_index"] == 8.0
    assert measurement["survey_count"] == 1
    assert measurement["committed_budget_cents"] == 1443174
    assert measurement["budget_headroom_cents"] == 3556826
    assert measurement["budget_posture"] == "OK"
    assert measurement["reported_award_total_cents"] == 0
    assert base["program"]["sales_lift_pct"] is None
    assert base["program"]["satisfaction_index"] is None


def test_a_program_cannot_jump_from_onsite_straight_to_closed():
    """`ONSITE → CLOSED` is not a declared edge, so the state gate answers first.

    PRD §3.1: "The declared director-driven edges are `DESIGN → SOURCING`,
    `CONTRACTED → REGISTRATION_OPEN`, `REGISTRATION_OPEN → ONSITE`, `ONSITE →
    RECONCILED` and `RECONCILED → CLOSED`."

    Design: Corner/endpoints/closing_a_program_is_conditional_on_every_taxable_award_being_reported
    """
    base = _onsite_one_traveller_one_bystander()

    validate_error(
        api_client.advance_program(base["program"]["id"], advance_payload("CLOSED"), PD),
        ApiErrorId.ERR_PROGRAM_STATE_INVALID,
    )
    validate_error(
        api_client.advance_program(base["program"]["id"], advance_payload("CONTRACTED"), PD),
        ApiErrorId.ERR_PROGRAM_STATE_INVALID,
    )
    assert read_program(base["program"]["id"])["status"] == "ONSITE"


def test_reconciliation_settles_the_travelling_cohort_and_stamps_the_measurement():
    """The single advance moves the seat, the winner and both measurement figures.

    PRD §3.9: "Two travellers with baselines of 180000000 and 120000000 against
    actuals of 260000000 and 155000000 give 3833 basis points and therefore a
    `sales_lift_pct` of 38.33."

    Design: Corner/endpoints/closing_a_program_is_conditional_on_every_taxable_award_being_reported
    """
    base = _onsite_one_traveller_one_bystander()
    advance_program(base["program"]["id"], "RECONCILED")

    ben = read_qualifier(base["ben"]["id"])
    assert ben["award_status"] == "TRAVELLED"
    assert ben["taxable_award_cents"] == 443198
    assert ben["tax_status"] == "PENDING_REPORT"
    assert read_registration(base["seat"]["id"])["attendance_status"] == "TRAVELLED"

    ana = read_qualifier(base["ana"]["id"])
    assert ana["award_status"] == "NOTIFIED"
    assert ana["taxable_award_cents"] == 0
    assert ana["tax_status"] == "NOT_APPLICABLE"

    program = read_program(base["program"]["id"])
    assert program["status"] == "RECONCILED"
    assert program["sales_lift_pct"] == 29.17
    assert program["satisfaction_index"] == 8.0
    assert program["travelled_count"] == 1
    assert program["qualified_count"] == 2
    measurement = validate_success(api_client.get_program_measurement(program["id"], AN))
    assert measurement["baseline_metric_total"] == 120_000_000
    assert measurement["actual_metric_total"] == 155_000_000
    assert measurement["sales_lift_pct"] == 29.17


def test_closing_is_blocked_while_a_taxable_award_is_still_unreported():
    """The completeness gate reports its own error, not the generic one.

    PRD §3.1: "Moving into `CLOSED` requires that every qualifier of the program
    whose `taxable_award_cents` is greater than 0 carries `tax_status`
    `REPORTED`, and a program with an unreported taxable award reports
    `ERR_TAX_REPORTING_INCOMPLETE` rather than the generic prerequisite error."

    Design: Corner/endpoints/closing_a_program_is_conditional_on_every_taxable_award_being_reported
    """
    base = _onsite_one_traveller_one_bystander()
    advance_program(base["program"]["id"], "RECONCILED")

    validate_error(
        api_client.advance_program(base["program"]["id"], advance_payload("CLOSED"), PD),
        ApiErrorId.ERR_TAX_REPORTING_INCOMPLETE,
    )
    assert read_program(base["program"]["id"])["status"] == "RECONCILED"


def test_a_drafted_but_unfiled_report_does_not_unblock_closing():
    """Only a `REPORTED` tax dimension satisfies the completeness gate.

    PRD §3.9: "a program may only reach `CLOSED` when every qualifier whose
    `taxable_award_cents` is greater than 0 sits at `tax_status` `REPORTED`."

    Design: Corner/endpoints/closing_a_program_is_conditional_on_every_taxable_award_being_reported
    """
    base = _onsite_one_traveller_one_bystander()
    advance_program(base["program"]["id"], "RECONCILED")
    report = draft_tax_report(base["ben"]["id"], 2026)
    assert report["status"] == "DRAFT"
    assert report["award_value_cents"] == 443198
    assert report["gross_up_method"] == "FLAT_SUPPLEMENTAL"
    assert read_qualifier(base["ben"]["id"])["tax_status"] == "PENDING_REPORT"

    validate_error(
        api_client.advance_program(base["program"]["id"], advance_payload("CLOSED"), PD),
        ApiErrorId.ERR_TAX_REPORTING_INCOMPLETE,
    )
    assert read_program(base["program"]["id"])["status"] == "RECONCILED"


def test_closing_succeeds_once_every_taxable_award_has_been_filed():
    """Filing the one taxable award is exactly what unblocks `CLOSED`.

    PRD §3.9: "Filing stamps `filed_by_user_id` with the acting `X-User-ID` and
    `filed_at` from the logical clock, moves the qualifier's `tax_status`
    `PENDING_REPORT → REPORTED`, and adds the report's `reported_value_cents` to
    the program's `reported_award_total_cents`."

    Design: Corner/endpoints/closing_a_program_is_conditional_on_every_taxable_award_being_reported
    """
    base = _onsite_one_traveller_one_bystander()
    advance_program(base["program"]["id"], "RECONCILED")
    report = draft_tax_report(base["ben"]["id"], 2026)
    assert report["combined_rate_bp"] == 2200
    assert report["gross_up_cents"] == 97504
    assert report["reported_value_cents"] == 540702

    filed = file_tax_report(report["id"])
    assert filed["status"] == "FILED"
    assert read_qualifier(base["ben"]["id"])["tax_status"] == "REPORTED"
    assert read_program(base["program"]["id"])["reported_award_total_cents"] == 540702

    closed = advance_program(base["program"]["id"], "CLOSED")
    assert closed["status"] == "CLOSED"
    assert read_qualifier(base["ana"]["id"])["tax_status"] == "NOT_APPLICABLE", (
        "a zero taxable award never needed a report"
    )


def test_a_closed_program_can_no_longer_be_cancelled_or_advanced():
    """`CLOSED` is terminal on both the advance and the cancel paths.

    PRD §3.9: "A `RECONCILED` or `CLOSED` program cannot be cancelled — the trip
    has already happened — and that attempt reports `ERR_PROGRAM_STATE_INVALID`,
    as does cancelling an already-`CANCELLED` program."

    Design: Corner/endpoints/closing_a_program_is_conditional_on_every_taxable_award_being_reported
    """
    base = _onsite_one_traveller_one_bystander()
    advance_program(base["program"]["id"], "RECONCILED")
    report = draft_tax_report(base["ben"]["id"], 2026)
    file_tax_report(report["id"])
    closed = advance_program(base["program"]["id"], "CLOSED")

    validate_error(
        api_client.cancel_program(
            base["program"]["id"], {"cancellation_reason": "Too late"}, PD
        ),
        ApiErrorId.ERR_PROGRAM_STATE_INVALID,
    )
    validate_error(
        api_client.advance_program(base["program"]["id"], advance_payload("RECONCILED"), PD),
        ApiErrorId.ERR_PROGRAM_STATE_INVALID,
    )
    assert read_program(base["program"]["id"]) == closed


JSON = {"Content-Type": "application/json"}


def test_an_absent_auth_header_is_rejected_before_anything_else_is_examined():
    """Priority 1: either header missing is `ERR_MISSING_AUTH_HEADERS`.

    PRD §2.1: "If either header is absent or empty, the request is rejected with
    `ERR_MISSING_AUTH_HEADERS` (HTTP 401) before anything else about the request
    is examined."

    Design: Corner/errors/auth_schema_and_existence_errors_are_all_triggerable_in_priority_order
    """
    payload = create_program_payload()
    for headers in (
        dict(JSON, **{"X-User-Role": "ProgramDirector"}),
        dict(JSON, **{"X-User-ID": USER_IDS["PROGRAM_DIRECTOR"]}),
        dict(JSON),
    ):
        validate_error(
            api_client.create_program(payload, headers), ApiErrorId.ERR_MISSING_AUTH_HEADERS
        )
    _, meta = validate_paginated(api_client.list_programs(PD))
    assert meta["total_count"] == 0


def test_an_empty_auth_header_counts_as_absent():
    """An empty string is not an identity, on either header.

    PRD §2.1: "If either header is absent or empty, the request is rejected with
    `ERR_MISSING_AUTH_HEADERS` (HTTP 401) before anything else about the request
    is examined."

    Design: Corner/errors/auth_schema_and_existence_errors_are_all_triggerable_in_priority_order
    """
    for headers in (
        dict(JSON, **{"X-User-ID": USER_IDS["PROGRAM_DIRECTOR"], "X-User-Role": ""}),
        dict(JSON, **{"X-User-ID": "", "X-User-Role": "ProgramDirector"}),
        dict(JSON, **{"X-User-ID": "", "X-User-Role": ""}),
    ):
        validate_error(
            api_client.create_program(create_program_payload(), headers),
            ApiErrorId.ERR_MISSING_AUTH_HEADERS,
        )


def test_the_auth_header_gate_outranks_the_request_schema_gate():
    """A missing header beats a malformed body (priority 1 before 7).

    PRD §2.8: "When a single request would fail more than one check, the check
    with the lowest priority number below wins and its error is the one
    returned."

    Design: Corner/errors/auth_schema_and_existence_errors_are_all_triggerable_in_priority_order
    """
    broken = create_program_payload(fiscal_year="not-a-year", budget_total_cents=-1)
    validate_error(
        api_client.create_program(broken, dict(JSON)),
        ApiErrorId.ERR_MISSING_AUTH_HEADERS,
    )
    validate_error(api_client.create_program(broken, PD), ApiErrorId.ERR_INVALID_REQUEST)


def test_an_unrecognised_role_name_is_an_invalid_role():
    """Priority 2: only the seven declared role names are recognised.

    PRD §2.1: "If both headers are present but `X-User-Role` is not one of the
    seven role names below, the request is rejected with `ERR_INVALID_ROLE` (HTTP
    401)."

    Design: Corner/errors/auth_schema_and_existence_errors_are_all_triggerable_in_priority_order
    """
    for role in ("ProgramManager", "Administrator", "programdirector", "PROGRAMDIRECTOR"):
        validate_error(
            api_client.create_program(create_program_payload(), headers_for_role(role, "u-1")),
            ApiErrorId.ERR_INVALID_ROLE,
        )
    program = validate_success(
        api_client.create_program(create_program_payload(), headers_for_role("ProgramDirector")),
        expected_status=201,
    )
    assert program["status"] == "DESIGN"


def test_role_recognition_outranks_path_and_body_existence():
    """An unknown role wins over a dangling id (priority 2 before 4 and 5).

    PRD §2.8: "**Role recognition** — `X-User-Role` is one of the seven declared
    roles. Applies to every endpoint. Violation: `ERR_INVALID_ROLE`, HTTP 401."

    Design: Corner/errors/auth_schema_and_existence_errors_are_all_triggerable_in_priority_order
    """
    bogus = headers_for_role("ProgramManager", "u-1")
    validate_error(
        api_client.get_program(NON_EXISTENT_UUID, bogus), ApiErrorId.ERR_INVALID_ROLE
    )
    validate_error(
        api_client.create_award_tier(
            create_award_tier_payload(NON_EXISTENT_UUID, **PLATINUM), bogus
        ),
        ApiErrorId.ERR_INVALID_ROLE,
    )


def test_a_recognised_but_unauthorized_role_is_refused_before_the_body_is_read():
    """Priority 3 beats priority 7: bad role first, malformed body second.

    PRD §2.1: "If the role is valid but is not listed among the authorized roles
    for the endpoint being called (see the table in §4), the request is rejected
    with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/errors/auth_schema_and_existence_errors_are_all_triggerable_in_priority_order
    """
    broken = create_program_payload(name="")
    validate_error(api_client.create_program(broken, SM), ApiErrorId.ERR_ROLE_NOT_PERMITTED)
    validate_error(api_client.create_program(broken, TD), ApiErrorId.ERR_ROLE_NOT_PERMITTED)
    validate_error(api_client.create_program(broken, PD), ApiErrorId.ERR_INVALID_REQUEST)
    _, meta = validate_paginated(api_client.list_programs(PD))
    assert meta["total_count"] == 0


def test_every_request_schema_violation_reports_the_same_invalid_request_error():
    """Missing fields, wrong types, bad enums and out-of-range integers all 400.

    PRD §2.8: "**Request schema** — all required fields present, correct JSON
    types, enum values inside their declared sets and integers inside their
    declared ranges."

    Design: Corner/errors/auth_schema_and_existence_errors_are_all_triggerable_in_priority_order
    """
    program = create_program(budget_total_cents=5_000_000)
    missing_rank = create_award_tier_payload(program["id"], **PLATINUM)
    missing_rank.pop("tier_rank")

    for payload in (
        missing_rank,
        create_award_tier_payload(program["id"], **dict(PLATINUM, tier_rank="3")),
        create_award_tier_payload(program["id"], **dict(PLATINUM, air_cabin_class="FIRST")),
        create_award_tier_payload(
            program["id"], **dict(PLATINUM, budget_per_qualifier_cents=-1)
        ),
        create_award_tier_payload(program["id"], **dict(PLATINUM, guest_allowance=3)),
        create_award_tier_payload(program["id"], **dict(PLATINUM, service_load_bp=5001)),
    ):
        validate_error(
            api_client.create_award_tier(payload, PD), ApiErrorId.ERR_INVALID_REQUEST
        )

    _, meta = validate_paginated(api_client.list_award_tiers(PD, {"program_id": program["id"]}))
    assert meta["total_count"] == 0, "no rejected tier may have been persisted"


def test_an_unknown_body_field_is_ignored_rather_than_rejected():
    """A field the endpoint does not accept never fails the request.

    PRD §2.8: "An unknown field carrying a value the endpoint does not accept is
    ignored, not rejected."

    Design: Corner/errors/auth_schema_and_existence_errors_are_all_triggerable_in_priority_order
    """
    program = create_program(budget_total_cents=5_000_000)
    payload = create_award_tier_payload(program["id"], **PLATINUM)
    payload["colour"] = "gold-leaf"
    payload["tier_notes"] = "ignore me"

    tier = validate_success(api_client.create_award_tier(payload, PD), expected_status=201)
    assert "colour" not in tier
    assert "tier_notes" not in tier
    assert tier["tier_code"] == "PLATINUM"
    assert validate_success(api_client.get_award_tier(tier["id"], PD)) == tier


def test_pagination_parameters_outside_their_declared_range_are_rejected():
    """Priority 8 rejects a bad `limit` or `offset` on any list endpoint.

    PRD §2.3: "A `limit` that is not an integer, is below 1 or is above 100, and
    an `offset` that is not an integer or is negative, are rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/errors/auth_schema_and_existence_errors_are_all_triggerable_in_priority_order
    """
    create_program(budget_total_cents=5_000_000)
    for params in (
        {"limit": 0},
        {"limit": 101},
        {"limit": -1},
        {"limit": "abc"},
        {"offset": -1},
        {"offset": "abc"},
    ):
        validate_error(api_client.list_programs(PD, params), ApiErrorId.ERR_INVALID_REQUEST)

    for params in ({"limit": 1}, {"limit": 100}, {"offset": 0}):
        validate_paginated(api_client.list_programs(PD, params))
    _, meta = validate_paginated(api_client.list_programs(PD))
    assert meta["limit"] == 10 and meta["offset"] == 0


def test_the_pagination_gate_applies_to_every_collection():
    """The same rejection reaches all ten list endpoints.

    PRD §2.3: "Every collection endpoint accepts two optional pagination
    parameters. `limit` defaults to 10 when omitted, has a minimum of 1 and a
    maximum of 100."

    Design: Corner/errors/auth_schema_and_existence_errors_are_all_triggerable_in_priority_order
    """
    for lister, headers in (
        (api_client.list_programs, PD),
        (api_client.list_award_tiers, PD),
        (api_client.list_qualifiers, AN),
        (api_client.list_destinations, SM),
        (api_client.list_supplier_contracts, SM),
        (api_client.list_deposit_milestones, CA),
        (api_client.list_registrations, TD),
        (api_client.list_onsite_activities, TD),
        (api_client.list_activity_signups, TD),
        (api_client.list_tax_award_reports, TAX),
    ):
        validate_error(lister(headers, {"limit": 0}), ApiErrorId.ERR_INVALID_REQUEST)
        validate_error(lister(headers, {"offset": -1}), ApiErrorId.ERR_INVALID_REQUEST)
        rows, meta = validate_paginated(lister(headers))
        assert rows == [] and meta["total_count"] == 0


def test_the_error_envelope_carries_only_the_two_meta_fields_and_the_error_pair():
    """An error body is `meta` + `response_type` + a two-key `data`.

    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/errors/auth_schema_and_existence_errors_are_all_triggerable_in_priority_order
    """
    response = api_client.get_program(NON_EXISTENT_UUID, PD)
    validate_error(response, ApiErrorId.ERR_PROGRAM_NOT_FOUND)

    body = response.json()
    assert body["response_type"] == "error"
    assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}
    assert body["data"]["error_id"] == ApiErrorId.ERR_PROGRAM_NOT_FOUND.value
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])


def test_each_single_row_read_has_its_own_not_found_error_id():
    """All ten templated reads answer an unknown id with their own 404 code.

    PRD §2.8: "Violation: `ERR_PROGRAM_NOT_FOUND` for `program_id`,
    `ERR_TIER_NOT_FOUND` for `tier_id`, `ERR_QUALIFIER_NOT_FOUND` for
    `qualifier_id`, `ERR_DESTINATION_NOT_FOUND` for `destination_id`,
    `ERR_CONTRACT_NOT_FOUND` for `contract_id`, `ERR_MILESTONE_NOT_FOUND` for
    `milestone_id`, `ERR_REGISTRATION_NOT_FOUND` for `registration_id`,
    `ERR_ACTIVITY_NOT_FOUND` for `activity_id`, `ERR_SIGNUP_NOT_FOUND` for
    `signup_id`, `ERR_TAX_REPORT_NOT_FOUND` for `report_id` — all HTTP 404."

    Design: Corner/errors/auth_schema_and_existence_errors_are_all_triggerable_in_priority_order
    """
    probes = (
        (api_client.get_program, PD, ApiErrorId.ERR_PROGRAM_NOT_FOUND),
        (api_client.get_award_tier, PD, ApiErrorId.ERR_TIER_NOT_FOUND),
        (api_client.get_qualifier, AN, ApiErrorId.ERR_QUALIFIER_NOT_FOUND),
        (api_client.get_destination, SM, ApiErrorId.ERR_DESTINATION_NOT_FOUND),
        (api_client.get_supplier_contract, SM, ApiErrorId.ERR_CONTRACT_NOT_FOUND),
        (api_client.get_deposit_milestone, CA, ApiErrorId.ERR_MILESTONE_NOT_FOUND),
        (api_client.get_registration, TD, ApiErrorId.ERR_REGISTRATION_NOT_FOUND),
        (api_client.get_onsite_activity, TD, ApiErrorId.ERR_ACTIVITY_NOT_FOUND),
        (api_client.get_activity_signup, TD, ApiErrorId.ERR_SIGNUP_NOT_FOUND),
        (api_client.get_tax_award_report, TAX, ApiErrorId.ERR_TAX_REPORT_NOT_FOUND),
    )
    for reader, headers, error_id in probes:
        validate_error(reader(NON_EXISTENT_UUID, headers), error_id)


def test_each_action_endpoint_resolves_its_path_id_before_doing_anything():
    """An unknown id on an action endpoint is the entity's own 404, never a 409.

    PRD §2.8: "**Path existence** — every templated id in the URL resolves to an
    existing row, validated strictly left to right, so the leftmost unresolvable
    segment decides the error."

    Design: Corner/errors/auth_schema_and_existence_errors_are_all_triggerable_in_priority_order
    """
    validate_error(
        api_client.advance_program(NON_EXISTENT_UUID, advance_payload("SOURCING"), PD),
        ApiErrorId.ERR_PROGRAM_NOT_FOUND,
    )
    validate_error(
        api_client.review_qualifier(NON_EXISTENT_UUID, AN), ApiErrorId.ERR_QUALIFIER_NOT_FOUND
    )
    validate_error(
        api_client.execute_contract(NON_EXISTENT_UUID, CA), ApiErrorId.ERR_CONTRACT_NOT_FOUND
    )
    validate_error(
        api_client.pay_deposit_milestone(NON_EXISTENT_UUID, CA),
        ApiErrorId.ERR_MILESTONE_NOT_FOUND,
    )
    validate_error(
        api_client.confirm_registration(NON_EXISTENT_UUID, TD),
        ApiErrorId.ERR_REGISTRATION_NOT_FOUND,
    )
    validate_error(
        api_client.close_onsite_activity(NON_EXISTENT_UUID, TD),
        ApiErrorId.ERR_ACTIVITY_NOT_FOUND,
    )
    validate_error(
        api_client.cancel_activity_signup(NON_EXISTENT_UUID, TD),
        ApiErrorId.ERR_SIGNUP_NOT_FOUND,
    )
    validate_error(
        api_client.file_tax_award_report(NON_EXISTENT_UUID, TAX),
        ApiErrorId.ERR_TAX_REPORT_NOT_FOUND,
    )


def test_a_participant_may_not_read_another_winners_rows():
    """Priority 6 refuses a participant acting outside their own aggregate.

    PRD §2.8: "**Participant ownership** — when the role is `Participant`,
    `X-User-ID` equals the `id` of the `Qualifier` that owns the target resource."

    Design: Corner/errors/auth_schema_and_existence_errors_are_all_triggerable_in_priority_order
    """
    base = _registration_open_base(qualifier_specs=(ANA, BEN))
    ana, ben = base["qualifiers"]
    ana_seat = _enrol(base, ana, confirm=False)
    intruder = make_participant_headers(ben["id"])

    validate_error(
        api_client.get_registration(ana_seat["id"], intruder), ApiErrorId.ERR_NOT_RESOURCE_OWNER
    )
    validate_error(
        api_client.get_qualifier(ana["id"], intruder), ApiErrorId.ERR_NOT_RESOURCE_OWNER
    )
    validate_error(
        api_client.respond_registration(ana_seat["id"], respond_payload("ACCEPT"), intruder),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
    )
    owner = make_participant_headers(ana["id"])
    assert validate_success(api_client.get_registration(ana_seat["id"], owner)) == ana_seat


def test_path_existence_outranks_participant_ownership():
    """An unknown row is a 404 even when the caller could never own it.

    PRD §2.8: "When a single request would fail more than one check, the check
    with the lowest priority number below wins and its error is the one
    returned."

    Design: Corner/errors/auth_schema_and_existence_errors_are_all_triggerable_in_priority_order
    """
    base = _registration_open_base(qualifier_specs=(ANA,))
    stranger = make_participant_headers(base["qualifiers"][0]["id"])

    validate_error(
        api_client.get_registration(NON_EXISTENT_UUID, stranger),
        ApiErrorId.ERR_REGISTRATION_NOT_FOUND,
    )
    validate_error(
        api_client.get_activity_signup(NON_EXISTENT_UUID, stranger),
        ApiErrorId.ERR_SIGNUP_NOT_FOUND,
    )


def test_the_program_axis_refuses_a_new_qualifier_once_the_group_is_onsite():
    """The lifecycle gate closes the qualifier-loading window at `ONSITE`.

    PRD §3.2: "Loading is permitted while the program is in `DESIGN`,
    `SOURCING` or `CONTRACTED`; anywhere else the program gate reports
    `ERR_PROGRAM_STATE_INVALID`."

    Design: Corner/errors/state_errors_for_every_entity_axis_are_each_reachable_from_one_onsite_program
    """
    base = _onsite_one_traveller_one_bystander()

    validate_error(
        api_client.create_qualifier(
            create_qualifier_payload(
                base["program"]["id"], employee_code=next_employee_code("LATE"),
                full_name="Late Arrival", baseline_metric=1, actual_metric=2,
            ),
            AN,
        ),
        ApiErrorId.ERR_PROGRAM_STATE_INVALID,
    )
    rows, meta = validate_paginated(
        api_client.list_qualifiers(AN, {"program_id": base["program"]["id"]})
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2


def test_the_qualifier_award_axis_refuses_a_second_adjudication():
    """Adjudication is a one-shot move off `PENDING_REVIEW`.

    PRD §3.2: "It is permitted only while the program is in `DESIGN`,
    `SOURCING` or `CONTRACTED` and only from `PENDING_REVIEW`; a qualifier that
    has already been adjudicated reports `ERR_QUALIFIER_STATE_INVALID`."

    Design: Corner/errors/state_errors_for_every_entity_axis_are_each_reachable_from_one_onsite_program
    """
    base = _contracted_base(qualifier_specs=(ANA,))
    ana = base["qualifiers"][0]
    assert ana["award_status"] == "QUALIFIED"
    before = read_qualifier(ana["id"])

    validate_error(
        api_client.review_qualifier(ana["id"], AN),
        ApiErrorId.ERR_QUALIFIER_STATE_INVALID,
    )

    after = read_qualifier(ana["id"])
    assert after["award_status"] == "QUALIFIED"
    assert after["version"] == before["version"]
    assert after["assigned_tier_id"] == before["assigned_tier_id"]
    assert after["committed_cost_cents"] == before["committed_cost_cents"]


def test_the_destination_selection_axis_blocks_a_shortlisted_row_from_being_re_inspected():
    """Once promoted off `CANDIDATE` a destination is closed to inspection.

    PRD §3.3: "Inspection is permitted only while the destination is still a
    `CANDIDATE` and the program is in `DESIGN` or `SOURCING`."

    Design: Corner/errors/state_errors_for_every_entity_axis_are_each_reachable_from_one_onsite_program
    """
    base = _sourcing_base()
    seville = base["seville"]
    inspect_destination(seville["id"], 85)
    shortlist_destination(seville["id"])
    promoted = read_destination(seville["id"])
    assert promoted["status"] == "SHORTLISTED"
    assert promoted["inspection_status"] == "INSPECTED"

    validate_error(
        api_client.site_inspect_destination(
            seville["id"], {"inspection_score": 91}, SM
        ),
        ApiErrorId.ERR_DESTINATION_STATE_INVALID,
    )

    after = read_destination(seville["id"])
    assert after["inspection_score"] == 85
    assert after["version"] == promoted["version"]


def test_the_contract_axis_refuses_another_negotiation_round_after_execution():
    """An `EXECUTED` contract has left the negotiation machine for good.

    PRD §3.4: "Any other pairing of current status and action — countering a
    `DRAFT`, proposing from `PROPOSED`, negotiating an `EXECUTED` or
    `WITHDRAWN` contract — is rejected with `ERR_CONTRACT_STATE_INVALID`."

    Design: Corner/errors/state_errors_for_every_entity_axis_are_each_reachable_from_one_onsite_program
    """
    base = _contracted_base()
    contract = base["contract"]
    assert contract["status"] == "EXECUTED"

    validate_error(
        api_client.negotiate_contract(
            contract["id"], negotiate_payload("PROPOSE", nightly_rate_cents=30_000), SM
        ),
        ApiErrorId.ERR_CONTRACT_STATE_INVALID,
    )
    validate_error(
        api_client.negotiate_contract(
            contract["id"], negotiate_payload("COUNTER", nightly_rate_cents=30_000), CA
        ),
        ApiErrorId.ERR_CONTRACT_STATE_INVALID,
    )

    after = read_contract(contract["id"])
    assert after["nightly_rate_cents"] == 38_500
    assert after["round_count"] == contract["round_count"]
    assert after["version"] == contract["version"]


def test_the_milestone_axis_refuses_a_second_payment_of_the_same_milestone():
    """Payment is the milestone's only request-driven move, and it happens once.

    PRD §3.5: "A milestone that is not `SCHEDULED` when payment is attempted
    reports `ERR_MILESTONE_STATE_INVALID`."

    Design: Corner/errors/state_errors_for_every_entity_axis_are_each_reachable_from_one_onsite_program
    """
    base = _contracted_base(with_schedule=True)
    first = base["milestones"][0]
    paid = pay_milestone(first["id"])
    assert paid["status"] == "PAID"

    validate_error(
        api_client.pay_deposit_milestone(first["id"], CA),
        ApiErrorId.ERR_MILESTONE_STATE_INVALID,
    )

    after = read_milestone(first["id"])
    assert after["status"] == "PAID"
    assert after["version"] == paid["version"]
    assert_instant_equals(after["paid_at"], paid["paid_at"], "milestone.paid_at")


def test_the_attendance_axis_refuses_a_second_invitation_response():
    """The invitation is answered once, off `INVITED` and never again.

    PRD §3.6: "Responding to a seat that is no longer `INVITED` reports
    `ERR_REGISTRATION_STATE_INVALID`."

    Design: Corner/errors/state_errors_for_every_entity_axis_are_each_reachable_from_one_onsite_program
    """
    base = _registration_open_base(qualifier_specs=(ANA,))
    ana = base["qualifiers"][0]
    seat = _enrol(base, ana, confirm=False)
    assert seat["attendance_status"] == "ACCEPTED"
    owner = make_participant_headers(ana["id"])

    validate_error(
        api_client.respond_registration(seat["id"], respond_payload("DECLINE"), owner),
        ApiErrorId.ERR_REGISTRATION_STATE_INVALID,
    )
    validate_error(
        api_client.respond_registration(
            seat["id"], respond_payload("ACCEPT", waiver_signed=True), owner
        ),
        ApiErrorId.ERR_REGISTRATION_STATE_INVALID,
    )

    after = read_registration(seat["id"], owner)
    assert after["attendance_status"] == "ACCEPTED"
    assert after["version"] == seat["version"]


def test_the_air_axis_refuses_every_pairing_outside_its_declared_ladder():
    """Ticketing before requesting, and requesting twice, are both air-state errors.

    PRD §3.7: "Any other pairing — requesting twice, ticketing straight from
    `NOT_REQUESTED`, changing a record that is not `TICKETED`, or acting on a
    `VOIDED` record at all — reports `ERR_AIR_STATE_INVALID`."

    Design: Corner/errors/state_errors_for_every_entity_axis_are_each_reachable_from_one_onsite_program
    """
    base = _registration_open_base(qualifier_specs=(ANA,))
    ana = base["qualifiers"][0]
    seat = _enrol(base, ana, confirm=False)
    assert seat["air_status"] == "NOT_REQUESTED"

    validate_error(
        api_client.air_registration(seat["id"], air_payload("TICKET"), TD),
        ApiErrorId.ERR_AIR_STATE_INVALID,
    )
    validate_error(
        api_client.air_registration(seat["id"], air_payload("CHANGE"), TD),
        ApiErrorId.ERR_AIR_STATE_INVALID,
    )
    assert read_registration(seat["id"])["air_status"] == "NOT_REQUESTED"

    requested = air_action(seat["id"], "REQUEST")
    assert requested["air_status"] == "REQUESTED"
    validate_error(
        api_client.air_registration(seat["id"], air_payload("REQUEST"), TD),
        ApiErrorId.ERR_AIR_STATE_INVALID,
    )
    validate_error(
        api_client.air_registration(seat["id"], air_payload("CHANGE"), TD),
        ApiErrorId.ERR_AIR_STATE_INVALID,
    )
    assert read_registration(seat["id"])["air_status"] == "REQUESTED"


def test_the_signup_axis_refuses_releasing_an_already_cancelled_slot():
    """`CANCELLED` is terminal for a signup, so the release cannot be repeated.

    PRD §3.8: "an activity that is no longer `OPEN` reports
    `ERR_ACTIVITY_STATE_INVALID`, and a signup that is already `CANCELLED`
    reports `ERR_SIGNUP_STATE_INVALID`."

    Design: Corner/errors/state_errors_for_every_entity_axis_are_each_reachable_from_one_onsite_program
    """
    base = _registration_open_base(qualifier_specs=(BEN,))
    ben = base["qualifiers"][0]
    seat = _enrol(base, ben)
    advance_program(base["program"]["id"], "ONSITE")
    activity = create_activity(base["program"]["id"], capacity=4, risk_level="LOW")
    signup = create_signup(activity["id"], seat["id"])
    assert signup["status"] == "BOOKED"
    released = cancel_signup(signup["id"])
    assert released["status"] == "CANCELLED"

    validate_error(
        api_client.cancel_activity_signup(signup["id"], TD),
        ApiErrorId.ERR_SIGNUP_STATE_INVALID,
    )

    after = read_signup(signup["id"])
    assert after["status"] == "CANCELLED"
    assert after["version"] == released["version"]
    assert_signup_counters(read_activity(activity["id"]), booked=0, waitlisted=0)


def test_the_activity_axis_refuses_a_second_close_and_any_further_signup():
    """A `CLOSED` activity is terminal for closing and for admission alike.

    PRD §3.8: "Closing an activity that is not `OPEN` reports
    `ERR_ACTIVITY_STATE_INVALID`."

    Design: Corner/errors/state_errors_for_every_entity_axis_are_each_reachable_from_one_onsite_program
    """
    base = _registration_open_base(qualifier_specs=(BEN,))
    ben = base["qualifiers"][0]
    seat = _enrol(base, ben)
    advance_program(base["program"]["id"], "ONSITE")
    activity = create_activity(base["program"]["id"], capacity=4, risk_level="LOW")
    closed = close_activity(activity["id"])
    assert closed["status"] == "CLOSED"

    validate_error(
        api_client.close_onsite_activity(activity["id"], TD),
        ApiErrorId.ERR_ACTIVITY_STATE_INVALID,
    )
    validate_error(
        api_client.create_activity_signup(
            create_activity_signup_payload(
                activity["id"], seat["id"], closed["version"]
            ),
            TD,
        ),
        ApiErrorId.ERR_ACTIVITY_STATE_INVALID,
    )

    after = read_activity(activity["id"])
    assert after["status"] == "CLOSED"
    assert after["version"] == closed["version"]
    assert_signup_counters(after, booked=0, waitlisted=0)


def test_the_gross_up_decision_is_accepted_exactly_once():
    """The policy lock is its own state axis on the program row.

    PRD §3.1: "The decision is accepted exactly once — a second submission,
    whatever value it carries, is rejected with `ERR_GROSS_UP_POLICY_LOCKED`."

    Design: Corner/errors/state_errors_for_every_entity_axis_are_each_reachable_from_one_onsite_program
    """
    program = create_program()
    assert program["gross_up_policy_locked"] is False
    locked = lock_gross_up_policy(program["id"], "FLAT_SUPPLEMENTAL")
    assert locked["gross_up_policy"] == "FLAT_SUPPLEMENTAL"
    assert locked["gross_up_policy_locked"] is True

    for value in ("FULL_GROSS_UP", "NONE", "FLAT_SUPPLEMENTAL"):
        validate_error(
            api_client.set_gross_up_policy(
                program["id"], gross_up_policy_payload(value), PD
            ),
            ApiErrorId.ERR_GROSS_UP_POLICY_LOCKED,
        )

    after = read_program(program["id"])
    assert after["gross_up_policy"] == "FLAT_SUPPLEMENTAL"
    assert after["gross_up_policy_locked"] is True
    assert after["version"] == locked["version"]


def test_the_tax_report_axis_admits_filing_only_from_draft_and_voiding_only_from_filed():
    """Each tax-report move has exactly one legal origin status.

    PRD §3.9: "filing anything that is not a `DRAFT` reports
    `ERR_TAX_REPORT_STATE_INVALID`."

    Design: Corner/errors/state_errors_for_every_entity_axis_are_each_reachable_from_one_onsite_program
    """
    base = _onsite_one_traveller_one_bystander()
    advance_program(base["program"]["id"], "RECONCILED")
    ben = read_qualifier(base["ben"]["id"])
    assert ben["award_status"] == "TRAVELLED"
    report = draft_tax_report(ben["id"])
    assert report["status"] == "DRAFT"

    validate_error(
        api_client.void_tax_award_report(
            report["id"], {"void_reason": "Too early to void"},
            make_tax_officer_headers(USER_IDS["TAX_OFFICER_ALT"]),
        ),
        ApiErrorId.ERR_TAX_REPORT_STATE_INVALID,
    )
    filed = file_tax_report(report["id"])
    assert filed["status"] == "FILED"
    validate_error(
        api_client.file_tax_award_report(report["id"], TAX),
        ApiErrorId.ERR_TAX_REPORT_STATE_INVALID,
    )
    voided = void_tax_report(report["id"])
    assert voided["status"] == "VOIDED"
    validate_error(
        api_client.void_tax_award_report(
            report["id"], {"void_reason": "Already voided"},
            make_tax_officer_headers(USER_IDS["TAX_OFFICER_ALT"]),
        ),
        ApiErrorId.ERR_TAX_REPORT_STATE_INVALID,
    )
    validate_error(
        api_client.file_tax_award_report(report["id"], TAX),
        ApiErrorId.ERR_TAX_REPORT_STATE_INVALID,
    )
    assert read_tax_report(report["id"])["status"] == "VOIDED"


def test_the_program_lifecycle_gate_answers_before_the_target_entity_state_gate():
    """A qualifier that is doubly ineligible reports the program gate's error.

    PRD §2.8: "10. **Program lifecycle gate** — the program's `status` permits
    the operation, and any requested advance is a declared edge out of the
    current status."

    Design: Corner/errors/state_errors_for_every_entity_axis_are_each_reachable_from_one_onsite_program
    """
    base = _onsite_one_traveller_one_bystander()
    ana = read_qualifier(base["ana"]["id"])
    assert ana["award_status"] == "NOTIFIED"

    validate_error(
        api_client.review_qualifier(ana["id"], AN),
        ApiErrorId.ERR_PROGRAM_STATE_INVALID,
    )
    validate_error(
        api_client.site_inspect_destination(
            base["seville"]["id"], {"inspection_score": 90}, SM
        ),
        ApiErrorId.ERR_PROGRAM_STATE_INVALID,
    )
    assert read_qualifier(ana["id"])["award_status"] == "NOTIFIED"
    assert read_destination(base["seville"]["id"])["inspection_status"] == "NOT_INSPECTED"


CARTAGENA = dict(
    city="Cartagena", country_code="CO", per_person_cost_cents=300_000,
    risk_score=61, air_gateway_code="CTG",
)
NAPLES = dict(
    city="Naples", country_code="IT", per_person_cost_cents=360_000,
    risk_score=40, air_gateway_code="NAP",
)


def _commercial_gate_base():
    """SOURCING program with one clean shortlist and two deliberately failing candidates."""
    program = create_program(budget_total_cents=5_000_000)
    tiers = [create_award_tier(program["id"], **spec) for spec in (PLATINUM, GOLD, SILVER)]
    lisbon = create_destination(program["id"], **LISBON)
    inspect_destination(lisbon["id"], 82)
    shortlist_destination(lisbon["id"])
    cartagena = create_destination(program["id"], **CARTAGENA)
    inspect_destination(cartagena["id"], 88)
    naples = create_destination(program["id"], **NAPLES)
    inspect_destination(naples["id"], 69)
    ana = create_qualifier(program["id"], **ANA)
    review_qualifier(ana["id"])
    advance_program(program["id"], "SOURCING")
    return {
        "program": read_program(program["id"]), "tiers": tiers, "lisbon": lisbon,
        "cartagena": read_destination(cartagena["id"]), "naples": read_destination(naples["id"]),
        "ana": read_qualifier(ana["id"]),
    }


def _underfunded_tier_base():
    """The same program driven to CONTRACTED, then handed a SILVER-bound qualifier."""
    base = _commercial_gate_base()
    contract = create_contract(base["program"]["id"], base["lisbon"]["id"], **HOTEL_TERMS)
    propose_contract(contract["id"])
    execute_contract(contract["id"])
    base["contract"] = read_contract(contract["id"])
    base["tess"] = create_qualifier(
        base["program"]["id"], employee_code="S-4001", full_name="Tess Ward",
        baseline_metric=110_000_000, actual_metric=130_000_000, guest_count=0,
    )
    base["program"] = read_program(base["program"]["id"])
    base["ana"] = read_qualifier(base["ana"]["id"])
    return base


def test_shortlisting_is_refused_one_point_above_the_risk_ceiling():
    """Cartagena's risk of 61 fails the ceiling although its inspection cleared.

    PRD §3.3: "The destination's `risk_score` must be at most 60 — a score of
    exactly 60 passes, 61 does not, and exceeding the ceiling reports
    `ERR_DESTINATION_RISK_TOO_HIGH`."

    Design: Corner/errors/business_rule_errors_unreachable_from_any_other_instance_are_triggered_directly
    """
    base = _commercial_gate_base()
    cartagena = base["cartagena"]
    assert cartagena["risk_score"] == 61
    assert cartagena["inspection_score"] == 88

    validate_error(
        api_client.shortlist_destination(cartagena["id"], SM),
        ApiErrorId.ERR_DESTINATION_RISK_TOO_HIGH,
    )

    after = read_destination(cartagena["id"])
    assert after["status"] == "CANDIDATE"
    assert after["inspection_status"] == "INSPECTED"
    assert after["version"] == cartagena["version"]


def test_shortlisting_is_refused_one_point_below_the_inspection_floor():
    """Naples' inspection of 69 fails the floor although its risk cleared.

    PRD §3.3: "Its `inspection_score` must be at least 70 — exactly 70 passes,
    69 does not, and falling short reports `ERR_INSPECTION_SCORE_BELOW_MINIMUM`."

    Design: Corner/errors/business_rule_errors_unreachable_from_any_other_instance_are_triggered_directly
    """
    base = _commercial_gate_base()
    naples = base["naples"]
    assert naples["risk_score"] == 40
    assert naples["inspection_score"] == 69

    validate_error(
        api_client.shortlist_destination(naples["id"], SM),
        ApiErrorId.ERR_INSPECTION_SCORE_BELOW_MINIMUM,
    )

    after = read_destination(naples["id"])
    assert after["status"] == "CANDIDATE"
    assert after["inspection_status"] == "INSPECTED"
    assert after["version"] == naples["version"]


def test_the_risk_ceiling_is_evaluated_before_the_inspection_floor():
    """A doubly failing candidate reports the risk error, and both boundaries pass.

    PRD §3.3: "The risk ceiling is evaluated before the inspection floor, so a
    destination that is both too risky and under-inspected reports the risk
    failure."

    Design: Corner/errors/business_rule_errors_unreachable_from_any_other_instance_are_triggered_directly
    """
    base = _commercial_gate_base()
    doomed = create_destination(
        base["program"]["id"], city="Bogota", country_code="CO",
        per_person_cost_cents=280_000, risk_score=75, air_gateway_code="BOG",
    )
    inspect_destination(doomed["id"], 50)

    validate_error(
        api_client.shortlist_destination(doomed["id"], SM),
        ApiErrorId.ERR_DESTINATION_RISK_TOO_HIGH,
    )
    assert read_destination(doomed["id"])["status"] == "CANDIDATE"

    borderline = create_destination(
        base["program"]["id"], city="Malta", country_code="MT",
        per_person_cost_cents=310_000, risk_score=60, air_gateway_code="MLA",
    )
    inspect_destination(borderline["id"], 70)
    promoted = validate_success(api_client.shortlist_destination(borderline["id"], SM))
    assert promoted["status"] == "SHORTLISTED"


def test_adjudication_is_refused_when_the_selected_tier_cannot_fund_the_award():
    """Tess lands on SILVER, whose 400000-cent budget cannot carry a 521409-cent award.

    PRD §3.2: "Second, the computed `committed_cost_cents` must be at most the
    chosen tier's `budget_per_qualifier_cents`; exceeding it is rejected with
    `ERR_TIER_BUDGET_EXCEEDED`."

    Design: Corner/errors/business_rule_errors_unreachable_from_any_other_instance_are_triggered_directly
    """
    base = _underfunded_tier_base()
    assert base["contract"]["status"] == "EXECUTED"
    assert base["program"]["per_person_cost_basis_cents"] == 431757
    assert base["program"]["committed_budget_cents"] == 921765
    tess = base["tess"]

    validate_error(
        api_client.review_qualifier(tess["id"], AN),
        ApiErrorId.ERR_TIER_BUDGET_EXCEEDED,
    )

    after = read_qualifier(tess["id"])
    assert after["award_status"] == "PENDING_REVIEW"
    assert after["assigned_tier_id"] is None
    assert after["committed_cost_cents"] == 0
    assert after["version"] == tess["version"]
    program = read_program(base["program"]["id"])
    assert program["committed_budget_cents"] == 921765
    assert_budget_conserved(program)


def test_the_advance_to_registration_open_is_refused_while_its_prerequisites_stand():
    """A declared edge with an unreviewed qualifier is a prerequisite failure.

    PRD §3.1: "Moving into `REGISTRATION_OPEN` requires that no qualifier of the
    program is still `PENDING_REVIEW` and that `gross_up_policy_locked` is true."

    Design: Corner/errors/business_rule_errors_unreachable_from_any_other_instance_are_triggered_directly
    """
    base = _underfunded_tier_base()
    program_id = base["program"]["id"]
    assert base["program"]["gross_up_policy_locked"] is False

    validate_error(
        api_client.advance_program(program_id, advance_payload("REGISTRATION_OPEN"), PD),
        ApiErrorId.ERR_ADVANCE_PREREQUISITES_UNMET,
    )
    assert read_program(program_id)["status"] == "CONTRACTED"

    lock_gross_up_policy(program_id, "FULL_GROSS_UP")
    validate_error(
        api_client.advance_program(program_id, advance_payload("REGISTRATION_OPEN"), PD),
        ApiErrorId.ERR_ADVANCE_PREREQUISITES_UNMET,
    )
    still = read_program(program_id)
    assert still["status"] == "CONTRACTED"
    assert still["gross_up_policy_locked"] is True


def test_an_undeclared_edge_is_a_state_error_rather_than_a_prerequisite_error():
    """`CONTRACTED → ONSITE` never reaches the prerequisite check at all.

    PRD §2.8: "10. **Program lifecycle gate** — the program's `status` permits
    the operation, and any requested advance is a declared edge out of the
    current status."

    Design: Corner/errors/business_rule_errors_unreachable_from_any_other_instance_are_triggered_directly
    """
    base = _underfunded_tier_base()
    program_id = base["program"]["id"]

    validate_error(
        api_client.advance_program(program_id, advance_payload("ONSITE"), PD),
        ApiErrorId.ERR_PROGRAM_STATE_INVALID,
    )
    validate_error(
        api_client.advance_program(program_id, advance_payload("RECONCILED"), PD),
        ApiErrorId.ERR_PROGRAM_STATE_INVALID,
    )
    assert read_program(program_id)["status"] == "CONTRACTED"


def test_a_brand_new_program_cannot_enter_sourcing_without_a_tier_and_a_shortlist():
    """Both halves of the `SOURCING` prerequisite are required, one at a time.

    PRD §3.1: "Moving into `SOURCING` requires at least one award tier to exist
    for the program and at least one of its destinations to be `SHORTLISTED` —
    sourcing cannot begin until both the tier ladder and an inspected,
    shortlisted destination exist."

    Design: Corner/errors/business_rule_errors_unreachable_from_any_other_instance_are_triggered_directly
    """
    program = create_program(
        name="FY28 Chairmans Club", fiscal_year=2028, budget_total_cents=1_000_000,
        sales_period_start="2028-01-01T00:00:00Z", sales_period_end="2028-06-30T00:00:00Z",
    )
    validate_error(
        api_client.advance_program(program["id"], advance_payload("SOURCING"), PD),
        ApiErrorId.ERR_ADVANCE_PREREQUISITES_UNMET,
    )
    assert read_program(program["id"])["status"] == "DESIGN"

    create_award_tier(program["id"], **GOLD)
    validate_error(
        api_client.advance_program(program["id"], advance_payload("SOURCING"), PD),
        ApiErrorId.ERR_ADVANCE_PREREQUISITES_UNMET,
    )
    assert read_program(program["id"])["status"] == "DESIGN"

    destination = create_destination(program["id"], **SEVILLE)
    inspect_destination(destination["id"], 85)
    validate_error(
        api_client.advance_program(program["id"], advance_payload("SOURCING"), PD),
        ApiErrorId.ERR_ADVANCE_PREREQUISITES_UNMET,
    )

    shortlist_destination(destination["id"])
    advanced = validate_success(
        api_client.advance_program(program["id"], advance_payload("SOURCING"), PD)
    )
    assert advanced["status"] == "SOURCING"


def _two_executed_hotel_contracts_base():
    """REGISTRATION_OPEN program carrying two EXECUTED HOTEL contracts and one ACCEPTED seat."""
    base = _contracted_base(qualifier_specs=(ANA, BEN))
    program_id = base["program"]["id"]
    annex = create_contract(
        program_id, base["lisbon"]["id"],
        **dict(HOTEL_TERMS, supplier_name="Estoril Palace Annex"),
    )
    propose_contract(annex["id"], proposer_user_id=USER_IDS["SOURCING_MANAGER_ALT"])
    execute_contract(annex["id"], executor_user_id=USER_IDS["CONTRACT_APPROVER"])
    notify_qualifiers(program_id)
    lock_gross_up_policy(program_id, "FULL_GROSS_UP")
    advance_program(program_id, "REGISTRATION_OPEN")
    ana = read_qualifier(base["qualifiers"][0]["id"])
    seat = create_registration(
        ana["id"], program_id=program_id, registration_kind="WINNER",
        arrival_date=ARRIVAL, departure_date=DEPARTURE, rooms=1,
    )
    respond_registration(seat["id"], ana["id"], "ACCEPT")
    base["annex"] = read_contract(annex["id"])
    base["seat"] = read_registration(seat["id"])
    base["ana"] = read_qualifier(ana["id"])
    base["program"] = read_program(program_id)
    return base


def test_confirmation_is_refused_when_two_hotel_contracts_are_executed():
    """Two executed hotel contracts leave the room-night basis ambiguous.

    PRD §3.7: "If there is none at all, or if there are two or more — which
    would leave the room-night basis ambiguous — confirmation reports
    `ERR_NO_EXECUTED_HOTEL_CONTRACT`."

    Design: Corner/errors/confirmation_is_blocked_when_the_room_night_basis_is_ambiguous
    """
    base = _two_executed_hotel_contracts_base()
    seat = base["seat"]
    assert seat["attendance_status"] == "ACCEPTED"

    validate_error(
        api_client.confirm_registration(seat["id"], TD),
        ApiErrorId.ERR_NO_EXECUTED_HOTEL_CONTRACT,
    )

    after = read_registration(seat["id"])
    assert after["attendance_status"] == "ACCEPTED"
    assert after["room_nights"] == 0
    assert after["version"] == seat["version"]
    ana = read_qualifier(base["ana"]["id"])
    assert ana["award_status"] == "NOTIFIED"


def test_both_hotel_contracts_hold_their_own_room_night_ledger():
    """The ambiguity is visible as two EXECUTED HOTEL rows, each with its own ledger.

    PRD §3.7: "Confirmation books room-nights against exactly one contract, so
    the program must have **exactly one** supplier contract whose
    `supplier_kind` is `HOTEL` and whose `status` is `EXECUTED`."

    Design: Corner/errors/confirmation_is_blocked_when_the_room_night_basis_is_ambiguous
    """
    base = _two_executed_hotel_contracts_base()

    rows, meta = validate_paginated(
        api_client.list_supplier_contracts(
            SM,
            {
                "program_id": base["program"]["id"],
                "supplier_kind": "HOTEL",
                "status": "EXECUTED",
            },
        )
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {base["contract"]["id"], base["annex"]["id"]}

    annex = read_contract(base["annex"]["id"])
    assert annex["status"] == "EXECUTED"
    assert annex["executed_by_user_id"] == USER_IDS["CONTRACT_APPROVER"]
    assert annex["room_nights_blocked"] == 60
    assert annex["room_nights_confirmed"] == 0
    assert_room_nights_conserved(annex)
    first = read_contract(base["contract"]["id"])
    assert first["room_nights_blocked"] == 60
    assert_room_nights_conserved(first)


def test_the_second_hotel_execution_does_not_re_run_the_program_cascade():
    """Level 4 of the execution cascade is skipped once the program has left `SOURCING`.

    PRD §3.4: "When the program is already `CONTRACTED` — a second hotel
    contract, or a `DMC` contract executed after the hotel one — this level is
    skipped entirely and the per-person basis is left as it stands."

    Design: Corner/errors/confirmation_is_blocked_when_the_room_night_basis_is_ambiguous
    """
    base = _two_executed_hotel_contracts_base()
    program = base["program"]

    assert program["status"] == "REGISTRATION_OPEN"
    assert program["per_person_cost_basis_cents"] == 431757
    assert program["committed_budget_cents"] == 1443174
    assert program["budget_headroom_cents"] == 3556826
    assert_budget_conserved(program)
    assert read_destination(base["lisbon"]["id"])["status"] == "SELECTED"
    assert read_destination(base["seville"]["id"])["status"] == "REJECTED"


def test_the_onsite_advance_is_blocked_while_the_ambiguity_stops_every_confirmation():
    """No seat can be confirmed, so the `ONSITE` prerequisite can never be met.

    PRD §3.1: "Moving into `ONSITE` requires at least one registration of the
    program to be `CONFIRMED`."

    Design: Corner/errors/confirmation_is_blocked_when_the_room_night_basis_is_ambiguous
    """
    base = _two_executed_hotel_contracts_base()
    program_id = base["program"]["id"]
    validate_error(
        api_client.confirm_registration(base["seat"]["id"], TD),
        ApiErrorId.ERR_NO_EXECUTED_HOTEL_CONTRACT,
    )

    validate_error(
        api_client.advance_program(program_id, advance_payload("ONSITE"), PD),
        ApiErrorId.ERR_ADVANCE_PREREQUISITES_UNMET,
    )
    assert read_program(program_id)["status"] == "REGISTRATION_OPEN"


def test_confirmation_succeeds_against_exactly_one_executed_hotel_contract():
    """With a single executed hotel contract the same seat books its room-nights.

    PRD §3.7: "Confirmation books room-nights against exactly one contract, so
    the program must have **exactly one** supplier contract whose
    `supplier_kind` is `HOTEL` and whose `status` is `EXECUTED`."

    Design: Corner/errors/confirmation_is_blocked_when_the_room_night_basis_is_ambiguous
    """
    base = _registration_open_base(qualifier_specs=(ANA, BEN))
    ana = base["qualifiers"][0]
    seat = create_registration(
        ana["id"], program_id=base["program"]["id"], registration_kind="WINNER",
        arrival_date=ARRIVAL, departure_date=DEPARTURE, rooms=1,
    )
    respond_registration(seat["id"], ana["id"], "ACCEPT")

    confirmed = validate_success(api_client.confirm_registration(seat["id"], TD))
    assert confirmed["attendance_status"] == "CONFIRMED"
    assert confirmed["room_nights"] == 5
    assert read_qualifier(ana["id"])["award_status"] == "REGISTERED"
    contract = read_contract(base["contract"]["id"])
    assert contract["room_nights_confirmed"] == 5
    assert contract["room_nights_available"] == 55
    assert_room_nights_conserved(contract)
    advanced = validate_success(
        api_client.advance_program(base["program"]["id"], advance_payload("ONSITE"), PD)
    )
    assert advanced["status"] == "ONSITE"
