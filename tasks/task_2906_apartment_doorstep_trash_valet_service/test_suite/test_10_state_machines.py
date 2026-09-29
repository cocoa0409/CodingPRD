"""State machines: declared transitions, refused transitions and their cascades."""

from test_helpers import (
    COMPLIANCE_SCREENER,
    OPERATORS,
    PLATFORM_ADMIN,
    VALET_OPS_MANAGER,
    ApiErrorId,
    api_client,
    assert_common_fields,
    assert_instants_equal,
    factories,
    fixtures,
    make_property_manager_headers,
    make_resident_headers,
    make_valet_headers,
    validate_error,
    validate_success,
)


# --------------------------------------------------------------------------
# Contractor onboarding: the screening fork and its precondition
# --------------------------------------------------------------------------
def test_a_clear_background_check_advances_the_applicant_to_cleared():
    """The clear branch moves BACKGROUND_PENDING to CLEARED and stamps the officer.

    PRD 3.3: "The officer records the outcome in `result`: a value of `CLEAR`
    advances the contractor `BACKGROUND_PENDING → CLEARED`, while a value of
    `FAIL` advances it `BACKGROUND_PENDING → REJECTED`. Both branches stamp the
    acting `X-User-ID` onto `background_checked_by_user_id` and increment
    `version`."

    Design: Corner/state_machines/background_check_clear_moves_contractor_to_cleared
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    contractor = fixtures.create_contractor(legal_name="Val Ito")
    fixtures.submit_documents(contractor["id"], "W9", True)

    cleared = validate_success(
        api_client.record_background_check(
            contractor["id"],
            factories.background_check_payload("CLEAR"),
            COMPLIANCE_SCREENER,
        )
    )

    assert cleared["onboarding_status"] == "CLEARED"
    assert cleared["background_checked_by_user_id"] == OPERATORS["COMPLIANCE_SCREENER"]
    assert cleared["classification"] == "UNCLASSIFIED", (
        "clearing the check is not the classification screen"
    )
    assert cleared["classification_basis"] is None
    assert cleared["control_score"] == 0


def test_running_the_control_screen_on_an_applicant_still_in_screening_is_refused():
    """The screen has a hard precondition, and a fresh applicant does not meet it.

    PRD 3.3: "The screen requires the contractor to be `CLEARED`; running it on an
    applicant still in screening, on a rejected applicant or on a deactivated one
    is refused as an invalid state transition."

    Design: Corner/state_machines/classification_before_documents_returns_invalid_state
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    contractor = fixtures.create_contractor(legal_name="Val Ito")
    assert contractor["onboarding_status"] == "APPLIED"

    response = api_client.run_classification(
        contractor["id"],
        factories.classification_payload("DECLARED"),
        COMPLIANCE_SCREENER,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    unchanged = fixtures.read_contractor(contractor["id"])
    assert unchanged["onboarding_status"] == "APPLIED"
    assert unchanged["control_score"] == 0
    assert unchanged["classification"] == "UNCLASSIFIED"
    assert unchanged["classification_basis"] is None


# --------------------------------------------------------------------------
# Contract lifecycle: one activation, one termination
# --------------------------------------------------------------------------
def test_activating_a_contract_that_is_already_active_is_refused():
    """Activation reads DRAFT as its only legal starting point.

    PRD 3.1: "Activation, reserved to a `PlatformAdmin`, moves it `DRAFT → ACTIVE`
    and is permitted only when the contract is still `DRAFT`, when its community
    is not `TERMINATED`, and when no other contract of the same community is
    already `ACTIVE`."

    Design: Corner/state_machines/second_activate_on_active_contract_returns_invalid_state
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    prop = fixtures.create_property(name="Cedar Ridge", unit_count=4)
    contract = fixtures.draft_contract(prop["id"])
    active = fixtures.activate_contract(contract["id"])
    assert active["status"] == "ACTIVE"

    response = api_client.activate_contract(contract["id"], PLATFORM_ADMIN)

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    unchanged = fixtures.read_contract(contract["id"])
    assert unchanged["status"] == "ACTIVE"
    assert unchanged["version"] == active["version"], (
        "a refused transition must not bump the row"
    )
    prop_after = fixtures.read_property(prop["id"])
    assert prop_after["status"] == "ACTIVE"
    assert prop_after["active_contract_id"] == contract["id"]


def test_terminating_a_contract_twice_reports_the_terminal_specialisation():
    """The second termination addresses a row that has already reached its end state.

    PRD 2.5: "**Declared transition.** The addressed resource must currently be in
    a state from which the requested transition is declared in this document —
    otherwise `ERR_INVALID_STATE` (409), or one of its two specialisations:
    `ERR_TAG_NOT_FINEABLE` (409) when a scan's tag is not `OPEN` at fine time, and
    `ERR_ALREADY_TERMINAL` (409) when the addressed resource has already reached a
    terminal state for its machine."

    PRD 3.1: "`TERMINATED` is terminal for both a contract and a community.
    Neither can be revived"

    Design: Corner/state_machines/terminate_twice_on_contract_returns_already_terminal
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    prop = fixtures.create_property(name="Cedar Ridge", unit_count=4)
    contract = fixtures.draft_contract(prop["id"])
    fixtures.activate_contract(contract["id"])
    terminated = fixtures.terminate_contract(contract["id"], "Community sold")
    assert terminated["status"] == "TERMINATED"
    property_after_first = fixtures.read_property(prop["id"])
    assert property_after_first["status"] == "TERMINATED"

    response = api_client.terminate_contract(
        contract["id"],
        PLATFORM_ADMIN,
        factories.terminate_contract_payload("Community sold again"),
    )

    validate_error(response, ApiErrorId.ERR_ALREADY_TERMINAL.value, 409)
    unchanged = fixtures.read_contract(contract["id"])
    assert unchanged["status"] == "TERMINATED"
    assert unchanged["version"] == terminated["version"]
    property_after_second = fixtures.read_property(prop["id"])
    assert property_after_second["status"] == "TERMINATED"
    assert property_after_second["version"] == property_after_first["version"], (
        "the community must not be re-bubbled by a refused termination"
    )


# --------------------------------------------------------------------------
# A night is born on both dimensions at once
# --------------------------------------------------------------------------
def test_a_new_night_is_born_scheduled_and_unbilled_with_zero_counters():
    """Both dimensions start at their first state and every counter starts at zero.

    PRD 3.4: "A new night is born with `verification_status` `SCHEDULED`,
    `billing_status` `UNBILLED`, `scanned_door_count` 0, `coverage_bps` 0,
    `assigned_unit_coverage_count` 0, `rescheduled_from_night_id` null and
    `reschedule_action` null. Its `expected_door_count` is computed immediately
    from the occupancy picture on its `service_date`: the number of the
    community's residents whose `fee_passthrough_enabled` is true and whose
    occupancy window (inclusive of `move_in_date`, exclusive of `move_out_date`)
    contains that date."

    PRD 3.4: "`seasonal_volume_index`, an integer between 50 and 300 inclusive
    that defaults to 100 and expresses how heavy the night's volume is expected to
    be, and `holiday_flag`, a boolean defaulting to false that marks a night
    falling on an observed holiday."

    Design: Corner/state_machines/new_service_night_starts_scheduled_with_zero_counters
    """
    world = fixtures.build_active_community(
        name="Cedar Ridge", unit_count=4, resident_units=(), with_contractor=False
    )

    night = validate_success(
        api_client.create_service_night(
            world["contract"]["id"],
            factories.service_night_payload("2026-09-01"),
            VALET_OPS_MANAGER,
        ),
        expected_status=201,
    )

    assert night["contract_id"] == world["contract"]["id"]
    assert night["verification_status"] == "SCHEDULED"
    assert night["billing_status"] == "UNBILLED"
    assert night["expected_door_count"] == 0, "the community has no residents yet"
    assert night["scanned_door_count"] == 0
    assert night["coverage_bps"] == 0
    assert night["assigned_unit_coverage_count"] == 0
    assert night["rescheduled_from_night_id"] is None
    assert night["reschedule_action"] is None
    assert night["seasonal_volume_index"] == 100
    assert night["holiday_flag"] is False
    assert_common_fields(night, "ServiceNight")
    assert night["version"] == 1


# --------------------------------------------------------------------------
# The close settles both dimensions and sweeps the open routes
# --------------------------------------------------------------------------
def test_closing_a_night_abandons_the_routes_still_open_at_close_time():
    """Nobody scanned, so the night closes MISSED and the live route is swept away.

    PRD 3.5: "Whichever of the three outcomes is selected, the same three things
    follow: the night's `verification_status` becomes that outcome; the billing
    dimension advances `UNBILLED → ACCRUED`; and every route assignment of the
    night still in `ASSIGNED`, `ACCEPTED` or `IN_PROGRESS` moves to `ABANDONED`
    with `abandon_reason` set to the literal string `NIGHT_CLOSED`, each
    recomputing the night's `assigned_unit_coverage_count` and incrementing its
    own `version`."

    Design: Corner/state_machines/night_close_abandons_routes_still_open_at_close_time
    """
    world = fixtures.build_active_community(
        name="Cedar Ridge",
        unit_count=4,
        resident_units=(101,),
        resident_kwargs={101: {"move_in_date": "2026-08-01"}},
    )
    night = fixtures.schedule_night(world["contract"]["id"], "2026-09-01")
    route = fixtures.assign_route(night["id"], world["contractor"]["id"], 101, 104)
    assert route["status"] == "ASSIGNED"

    closed = validate_success(
        api_client.close_service_night(night["id"], VALET_OPS_MANAGER)
    )

    assert closed["verification_status"] == "MISSED"
    assert closed["billing_status"] == "ACCRUED"
    assert closed["scanned_door_count"] == 0
    swept = fixtures.read_route(route["id"])
    assert swept["status"] == "ABANDONED"
    assert swept["abandon_reason"] == "NIGHT_CLOSED"
    assert fixtures.read_night(night["id"])["assigned_unit_coverage_count"] == 0


def test_the_first_scan_bubbles_the_route_and_the_night_to_in_progress():
    """One scan advances two rows on the verification dimension and neither on billing.

    PRD 3.5: "Three rollups follow every scan. The route's `scan_count` increments
    by one and, on the route's first scan, the route moves `ACCEPTED →
    IN_PROGRESS`. On the night's first scan from any of its routes, the night moves
    `SCHEDULED → IN_PROGRESS`."

    PRD 3.4: "An operation that advances one dimension leaves the other
    untouched."

    Design: Corner/state_machines/first_scan_bubbles_route_and_night_to_in_progress
    """
    world = fixtures.build_scan_ready_night(
        name="Cedar Ridge",
        unit_count=4,
        resident_units=(101, 102),
        resident_kwargs={
            101: {"move_in_date": "2026-08-01"},
            102: {"move_in_date": "2026-08-01"},
        },
        service_date="2026-09-01",
    )
    assert world["route"]["status"] == "ACCEPTED"
    assert world["night"]["verification_status"] == "SCHEDULED"

    validate_success(
        api_client.record_scan(
            world["route"]["id"],
            factories.scan_payload(world["residents"][101]["id"], "SERVICED", "TRASH_BIN"),
            make_valet_headers(world["contractor"]["id"]),
        ),
        expected_status=201,
    )

    route = fixtures.read_route(world["route"]["id"])
    assert route["status"] == "IN_PROGRESS"
    assert route["scan_count"] == 1
    night = fixtures.read_night(world["night"]["id"])
    assert night["verification_status"] == "IN_PROGRESS"
    assert night["billing_status"] == "UNBILLED", (
        "the scan drives verification only, never revenue recognition"
    )


# --------------------------------------------------------------------------
# Terminating the active contract cascades two levels down and one level up
# --------------------------------------------------------------------------
def test_terminating_the_active_contract_cancels_its_nights_and_their_routes():
    """One termination reaches the night, the route and the community itself.

    PRD 3.1: "When an active contract does terminate, three cascades fire in the
    same request: every service night of the contract that has not yet reached a
    terminal verification outcome (one still `SCHEDULED`, or one already
    `IN_PROGRESS` because scanning had begun) moves to `CANCELLED`, and each of
    those cancellations in turn cancels that night's route assignments still in
    `ASSIGNED`, `ACCEPTED` or `IN_PROGRESS`; and the community, provided no other
    contract of it remains in `DRAFT` or `ACTIVE`, has its `active_contract_id`
    cleared to null and its own `status` moved to `TERMINATED`."

    Design: Corner/state_machines/contract_terminate_cancels_scheduled_nights_and_their_routes
    """
    world = fixtures.build_active_community(
        name="Cedar Ridge", unit_count=4, resident_units=()
    )
    night = fixtures.schedule_night(world["contract"]["id"], "2026-09-01")
    route = fixtures.assign_route(night["id"], world["contractor"]["id"], 101, 104)

    terminated = validate_success(
        api_client.terminate_contract(
            world["contract"]["id"],
            PLATFORM_ADMIN,
            factories.terminate_contract_payload("Community sold"),
        )
    )

    assert terminated["status"] == "TERMINATED"
    cancelled_night = fixtures.read_night(night["id"])
    assert cancelled_night["verification_status"] == "CANCELLED"
    assert cancelled_night["assigned_unit_coverage_count"] == 0
    assert fixtures.read_route(route["id"])["status"] == "CANCELLED"
    prop = fixtures.read_property(world["property"]["id"])
    assert prop["status"] == "TERMINATED"
    assert prop["active_contract_id"] is None


# --------------------------------------------------------------------------
# The community's own status is a function of its contracts
# --------------------------------------------------------------------------
def test_a_community_comes_alive_only_when_its_first_contract_is_activated():
    """Drafting the terms is not enough; activation is what flips the community.

    PRD 3.1: "Activation is where the community itself comes alive: alongside
    setting the contract's `status` to `ACTIVE` and incrementing its `version`, the
    community's `active_contract_id` is set to that contract and its `status` moves
    `ONBOARDING → ACTIVE`, incrementing the community's `version` in the same
    request."

    Design: Corner/state_machines/property_status_derives_from_its_first_contract_activation
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    prop = fixtures.create_property(name="Cedar Ridge", unit_count=4)
    contract = fixtures.draft_contract(prop["id"])
    while_draft = fixtures.read_property(prop["id"])
    assert contract["status"] == "DRAFT"
    assert while_draft["status"] == "ONBOARDING"
    assert while_draft["active_contract_id"] is None

    activated = validate_success(
        api_client.activate_contract(contract["id"], PLATFORM_ADMIN)
    )

    assert activated["status"] == "ACTIVE"
    after = fixtures.read_property(prop["id"])
    assert after["status"] == "ACTIVE"
    assert after["active_contract_id"] == contract["id"]
    assert after["version"] > while_draft["version"], (
        "the community row is written in the same request"
    )


# --------------------------------------------------------------------------
# The fine machine's asymmetric terminal branch
# --------------------------------------------------------------------------
def test_waiving_a_disputed_fine_releases_the_balance_but_not_the_headroom():
    """The ledger is compensated, the monthly ceiling deliberately is not.

    PRD 3.6: "An `outcome` of `WAIVED` moves the fine `DISPUTED → WAIVED`, stamps
    `adjudicated_by_user_id`, and performs a compensating ledger action: the
    resident's `fines_outstanding_cents` and the community's
    `pending_fine_revenue_cents` each drop by the fine's `amount_cents` ...
    `fines_assessed_this_period_cents` is **not** reduced: cap headroom consumed by
    an assessment is not returned by a waiver, which is what stops a resident from
    farming waivers to reset their monthly ceiling. `WAIVED` is terminal, as is
    `VOIDED`."

    PRD 3.6: "`tag_status` reads `NONE` when no violation was recorded, `OPEN` once
    a tag has been left at the door, `FINED` once a fine rests on it, and `VOIDED`
    after the community's manager retracts it."

    Design: Corner/state_machines/waived_adjudication_releases_the_resident_fine_balance
    """
    world = fixtures.build_scan_ready_night(
        name="Cedar Ridge",
        unit_count=4,
        resident_units=(101,),
        resident_kwargs={101: {"move_in_date": "2026-08-01"}},
        service_date="2026-09-01",
    )
    resident_id = world["residents"][101]["id"]
    property_id = world["property"]["id"]
    scan = fixtures.record_scan(
        world["route"]["id"],
        world["contractor"]["id"],
        resident_id,
        scan_result="TAGGED_NOT_SERVICED",
        container_type="RECYCLING_BIN",
        non_compliance_type="RECYCLING_CONTAMINATION",
    )
    fine = fixtures.find_fine_for_scan(scan["id"])
    assert fine["amount_cents"] == 2500
    validate_success(
        api_client.dispute_fine(
            fine["id"],
            factories.dispute_payload("The bin was not mine"),
            make_resident_headers(resident_id),
        )
    )

    waived = validate_success(
        api_client.adjudicate_fine(
            fine["id"],
            factories.adjudicate_payload("WAIVED", "Photo evidence cleared the door"),
            make_property_manager_headers(property_id),
        )
    )

    assert waived["status"] == "WAIVED"
    assert waived["dispute_round"] == 1
    assert waived["adjudicated_by_user_id"] == property_id
    resident = fixtures.read_resident(resident_id)
    assert resident["fines_outstanding_cents"] == 0
    assert resident["collections_status"] == "CURRENT"
    assert resident["fines_assessed_this_period_cents"] == 2500
    prop = fixtures.read_property(property_id)
    assert prop["pending_fine_revenue_cents"] == 0
    assert prop["delinquent_resident_count"] == 0
    assert fixtures.read_scan(scan["id"])["tag_status"] == "FINED", (
        "a waiver is not a retraction of the tag"
    )


# --------------------------------------------------------------------------
# SHIFT cancels one night and creates its linked replacement
# --------------------------------------------------------------------------
def test_a_shift_cancels_the_night_and_creates_a_linked_makeup_off_schedule():
    """The round keeps its clock time, moves to a Friday, and is reachable only by filter.

    PRD 3.4: "In addition, a **makeup night** is created on the supplied
    `makeup_service_date`. The makeup night belongs to the same contract; its
    `rescheduled_from_night_id` points at the night it replaces; it starts
    `SCHEDULED` and `UNBILLED`; its `holiday_flag` is set to false regardless of
    the original night's flag; its `seasonal_volume_index` is copied verbatim from
    the original night; and its `service_window_start` and `service_window_end` are
    the original night's window instants shifted forward by exactly the whole-day
    difference between the two service dates, so the round keeps its clock time and
    only changes its date. A shifted makeup night is exempt from the weekday
    membership check"

    PRD 3.4: "The makeup night is **not** returned in the response body of the
    reschedule; the response describes the cancelled night."

    Design: Corner/state_machines/reschedule_shift_cancels_night_and_creates_linked_makeup_night
    """
    world = fixtures.build_active_community(
        name="Cedar Ridge", unit_count=4, resident_units=()
    )
    night = fixtures.schedule_night(world["contract"]["id"], "2026-09-01")
    route = fixtures.assign_route(night["id"], world["contractor"]["id"], 101, 104)

    cancelled = validate_success(
        api_client.reschedule_service_night(
            night["id"],
            factories.reschedule_payload("SHIFT", "2026-09-04", "Labour Day observed"),
            VALET_OPS_MANAGER,
        )
    )

    assert cancelled["id"] == night["id"], "the response describes the cancelled night"
    assert cancelled["verification_status"] == "CANCELLED"
    assert cancelled["reschedule_action"] == "SHIFT"
    assert cancelled["assigned_unit_coverage_count"] == 0
    assert fixtures.read_route(route["id"])["status"] == "CANCELLED"

    makeup = fixtures.find_makeup_night(night["id"])
    assert makeup is not None, "the makeup night is discoverable only by back-reference"
    assert makeup["id"] != night["id"]
    assert makeup["contract_id"] == world["contract"]["id"]
    assert makeup["service_date"] == "2026-09-04"
    assert makeup["rescheduled_from_night_id"] == night["id"]
    assert makeup["verification_status"] == "SCHEDULED"
    assert makeup["billing_status"] == "UNBILLED"
    assert makeup["holiday_flag"] is False
    assert makeup["seasonal_volume_index"] == 100
    assert_instants_equal(
        makeup["service_window_start"], "2026-09-04T18:00:00.000Z", "service_window_start"
    )
    assert_instants_equal(
        makeup["service_window_end"], "2026-09-04T22:00:00.000Z", "service_window_end"
    )
