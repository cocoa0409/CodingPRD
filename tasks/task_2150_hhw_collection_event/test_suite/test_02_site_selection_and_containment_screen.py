"""Site nomination, the three-threshold containment screen, suspension and its
cascade, retirement, and the site list."""

from test_helpers import (
    COORDINATOR,
    SITE_APPROVER,
    SITE_APPROVER_USER_ID,
    TECH,
    ApiErrorId,
    assert_containment_finding,
    assert_no_write,
    assert_site,
    create_approved_site,
    create_event,
    create_program,
    create_site,
    create_site_payload,
    read_appointment,
    read_event,
    read_program,
    read_resident,
    read_site,
    setup_canon,
    site_action,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_new_site_is_stored_as_a_candidate_with_its_containment_attributes(api):
    """PRD §3.2: "An `EventCoordinator` nominates a candidate location by
    registering it against a `program_id` with a `name` such as "Arvada Public Works
    Yard", an `address`, and the three physical attributes that decide whether it is
    legally usable as an unload pad: `impervious_surface`, a boolean that is true
    only when the unload pad is fully asphalt or concrete;
    `secondary_containment_liters`, the rated containment volume of the pad; and
    `storm_drain_distance_m`, the distance in metres from the pad edge to the
    nearest storm-drain inlet."
    PRD §3.2: "Every new site lands in `CANDIDATE` status with a null
    `approved_by_user_id` and no `last_inspection_result`."

    Design: Corner/entities/get_site_returns_stored_containment_attributes
    """
    program = create_program(eligible_jurisdiction_codes=["CO-DEN"])
    site = create_site(program["id"])

    response = api.get_site(site["id"], COORDINATOR)
    fetched = validate_success(response, 200)

    assert_site(fetched)
    assert fetched["status"] == "CANDIDATE"
    assert fetched["secondary_containment_liters"] == 2000
    assert fetched["storm_drain_distance_m"] == 15.0
    assert fetched["lane_count"] == 4
    assert fetched["approved_by_user_id"] is None


def test_site_list_filters_by_program_and_pages_in_creation_order(api):
    """PRD §2.3: "`limit` controls page size: it defaults to 10 when omitted, may
    be no smaller than 1, and may be no larger than 100."
    PRD §2.3: "List results are always ordered by `created_at` ascending."
    PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` is the number of rows matching
    the filter before pagination is applied and `has_more` indicates whether any rows
    remain beyond the current page."

    Design: Corner/entities/list_sites_filters_by_program_and_paginates
    """
    program = create_program(eligible_jurisdiction_codes=["CO-DEN"])
    create_site(program["id"], name="Site One", address="1 A Street")
    create_site(
        program["id"],
        name="Site Two",
        address="2 B Street",
        secondary_containment_liters=2400,
        storm_drain_distance_m=22.0,
        lane_count=3,
    )
    create_site(
        program["id"],
        name="Site Three",
        address="3 C Street",
        impervious_surface=False,
        secondary_containment_liters=900,
        storm_drain_distance_m=8.0,
        lane_count=2,
    )

    response = api.list_sites(
        COORDINATOR, params={"program_id": program["id"], "limit": 2, "offset": 0}
    )
    rows, meta = validate_paginated(response)

    assert len(rows) == 2, "limit=2 must return exactly two rows"
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert rows[0]["name"] == "Site One", "Rows are ordered by created_at ascending"


def test_site_list_with_limit_above_the_maximum_is_rejected(api):
    """PRD §2.3: "A `limit` outside the range 1 through 100, or a negative `offset`,
    is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400)
    rather than being silently clamped."

    Design: Corner/validations/list_sites_with_limit_above_max_returns_invalid_request
    """
    program = create_program(eligible_jurisdiction_codes=["CO-DEN"])
    create_site(program["id"])

    response = api.list_sites(COORDINATOR, params={"program_id": program["id"], "limit": 500})
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_site_creation_missing_a_containment_attribute_is_rejected(api):
    """PRD §2.5: "Request shape: every required body field present and of the
    declared type, every enum value a declared member, every required array
    non-empty, every numeric range satisfied, and — for event scheduling —
    `window_end_utc` strictly after `window_start_utc` and falling on the same UTC
    calendar date. Violations return `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_site_missing_required_field_returns_invalid_request
    """
    program = create_program(eligible_jurisdiction_codes=["CO-DEN"])
    payload = create_site_payload(program["id"], name="Broken Site", address="9 Z Street")
    payload.pop("storm_drain_distance_m")

    response = api.create_site(payload, COORDINATOR)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    _, meta = validate_paginated(api.list_sites(COORDINATOR, params={"program_id": program["id"]}))
    assert meta["total_count"] == 0, "A rejected creation writes nothing"


def test_unload_tech_may_not_nominate_a_site(api):
    """PRD §2.1: "Once the headers are accepted, the role is matched against the
    endpoint's authorised role list; a role that is not listed for the endpoint is
    rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/roles/unload_tech_cannot_create_a_site_returns_unauthorized_role
    """
    program = create_program(eligible_jurisdiction_codes=["CO-DEN"])

    response = api.create_site(
        create_site_payload(program["id"], name="Sneaky Yard", address="1 Backdoor Road"),
        TECH,
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)

    _, meta = validate_paginated(api.list_sites(COORDINATOR, params={"program_id": program["id"]}))
    assert meta["total_count"] == 0


def test_site_approval_passes_on_the_exact_containment_floors(api):
    """PRD §3.2: "Approval — the transition `CANDIDATE → APPROVED` — is granted only
    when all three containment thresholds hold at once: the surface must be
    impervious, `secondary_containment_liters` must be at least 2000, and
    `storm_drain_distance_m` must be at least 15.0 metres. All three are inclusive
    floors: a pad rated at exactly 2000 litres passes, and a drain inlet at exactly
    15.0 metres passes."
    PRD §3.2: "A successful approval writes three things: `status` becomes
    `APPROVED`, `approved_by_user_id` is stamped with the `X-User-ID` of the acting
    inspector, and `last_inspection_result` becomes `PASS`."

    Design: Corner/validations/site_approval_at_exact_containment_thresholds_succeeds
    """
    program = create_program(eligible_jurisdiction_codes=["CO-DEN"])
    site = create_site(
        program["id"],
        name="Edge Case Yard",
        address="15 Threshold Road",
        secondary_containment_liters=2000,
        storm_drain_distance_m=15.0,
        lane_count=2,
    )

    response = api.site_transition(
        site["id"], {"action": "APPROVE", "finding_code": "PAD-OK"}, SITE_APPROVER
    )
    approved = validate_success(response, 200)

    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == SITE_APPROVER_USER_ID
    assert approved["last_inspection_result"] == "PASS"


def test_failed_containment_screen_writes_nothing_at_all(api):
    """PRD §3.2: "If any one of the three fails, the request is rejected with
    `ERR_CONTAINMENT_REQUIREMENTS_NOT_MET` and — this is the part implementations
    most often get wrong — **nothing is written**. The site stays in `CANDIDATE`,
    `last_inspection_result` is left exactly as it was, and the site's `version` does
    not move."

    Design: Corner/validations/site_approval_below_storm_drain_threshold_returns_containment_error
    """
    program = create_program(eligible_jurisdiction_codes=["CO-DEN"])
    site = create_site(
        program["id"],
        name="Too Close Yard",
        address="14 Drain Road",
        secondary_containment_liters=2000,
        storm_drain_distance_m=14.9,
        lane_count=2,
    )

    response = api.site_transition(
        site["id"], {"action": "APPROVE", "finding_code": "DRAIN-SETBACK"}, SITE_APPROVER
    )
    validate_error(response, ApiErrorId.ERR_CONTAINMENT_REQUIREMENTS_NOT_MET, 422)

    after = read_site(site["id"])
    assert after["status"] == "CANDIDATE"
    assert after["last_inspection_result"] is None, "A failed screen is a non-event"
    assert after["approved_by_user_id"] is None
    assert_no_write(site, after, "Site")


def test_retiring_a_site_that_still_hosts_a_planned_event_is_refused(api):
    """PRD §3.2: "It is permitted only when the site has no live commitments: no
    collection event at that site may currently sit in `PLANNED`, `SITE_CONFIRMED`,
    `OPEN_FOR_REGISTRATION` or `IN_PROGRESS`."
    PRD §2.5: "The requested action is a declared transition out of the target row's
    current state on the relevant axis — otherwise `ERR_INVALID_STATE_TRANSITION`
    (HTTP 409)."

    Design: Corner/state_machines/retire_site_with_planned_event_returns_invalid_state
    """
    program = create_program(eligible_jurisdiction_codes=["CO-DEN"])
    site = create_approved_site(program["id"])
    create_event(program["id"], site["id"])

    response = api.site_transition(site["id"], {"action": "RETIRE"}, COORDINATOR)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

    assert read_site(site["id"])["status"] == "APPROVED"


def test_replacement_site_is_reachable_by_filtering_on_its_predecessor(api):
    """PRD §3.2: "When the new site is intended to take over from a location the
    county is retiring, the payload names that predecessor as `replaces_site_id`; the
    field is null for a first-generation site."
    PRD §2.3: "Sites may be filtered by `program_id`, by `replaces_site_id`, and by
    `status`."

    Design: Corner/entities/self_referential_site_replacement_is_reverse_listable
    """
    program = create_program(eligible_jurisdiction_codes=["CO-DEN"])
    old_site = create_approved_site(
        program["id"],
        name="Old Yard",
        address="1 Legacy Road",
        storm_drain_distance_m=16.0,
        lane_count=3,
    )
    retired = site_action(old_site["id"], "RETIRE", COORDINATOR)
    assert retired["status"] == "RETIRED"

    successor = create_site(
        program["id"],
        name="New Yard",
        address="2 Successor Road",
        secondary_containment_liters=2600,
        storm_drain_distance_m=19.0,
        lane_count=5,
        replaces_site_id=old_site["id"],
    )

    rows, meta = validate_paginated(
        api.list_sites(COORDINATOR, params={"replaces_site_id": old_site["id"]})
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["id"] == successor["id"]
    assert rows[0]["replaces_site_id"] == old_site["id"]


def test_site_suspension_forces_its_open_event_deficient_and_sheds_reservations(api):
    """PRD §3.2: "The site's `last_inspection_result` becomes `FAIL`, and every
    collection event at that site whose lifecycle axis currently reads
    `SITE_CONFIRMED` or `OPEN_FOR_REGISTRATION` has its containment axis forced to
    `DEFICIENT`, with an entry recording an origin of `SITE` and a result of `FAIL`
    appended to that event's `containment_findings`."
    PRD §3.2: "Because those events have just become deficient, the full containment
    cascade described in §3.6 fires for each of them — every one of their confirmed
    appointments drops to the waitlist and gives back its reservation."

    Design: Corner/state_machines/site_suspend_cascades_open_event_to_deficient_containment
    """
    ctx = setup_canon(14, appointment={"declared_total_kg": 11.0})

    response = api.site_transition(
        ctx["site_id"], {"action": "SUSPEND", "finding_code": "PAD-SPALLING"}, SITE_APPROVER
    )
    suspended = validate_success(response, 200)
    assert suspended["status"] == "SUSPENDED"
    assert suspended["last_inspection_result"] == "FAIL"

    event = read_event(ctx["event_id"])
    assert event["containment_status"] == "DEFICIENT"
    assert event["lifecycle_status"] == "OPEN_FOR_REGISTRATION", (
        "The containment axis moves without the lifecycle axis"
    )
    site_findings = [
        entry for entry in event["containment_findings"] if entry.get("origin") == "SITE"
    ]
    assert site_findings, "The suspension cascade appends a SITE-origin finding"
    assert_containment_finding(site_findings[-1], "SITE", "FAIL")

    appointment = read_appointment(ctx["appointment_id"])
    assert appointment["status"] == "WAITLISTED"
    assert appointment["waitlist_reason"] == "CONTAINMENT_DEFICIENCY"
    assert read_resident(ctx["resident_id"])["annual_quantity_reserved_kg"] == 0
    assert read_program(ctx["program_id"])["open_containment_deficiency_count"] == 1


def test_site_confirmation_is_refused_once_the_pad_has_been_suspended(api):
    """PRD §3.3: "Confirming the site moves `PLANNED → SITE_CONFIRMED` and requires
    that the site is still `APPROVED` and the program is not frozen."
    PRD §2.5: "The event's site is approved, when scheduling an event or confirming
    its site — otherwise `ERR_SITE_NOT_APPROVED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/event_site_confirmation_depends_on_site_status
    """
    program = create_program()
    site = create_approved_site(program["id"])
    event = create_event(program["id"], site["id"])

    suspended = site_action(site["id"], "SUSPEND", SITE_APPROVER, finding_code="PAD-SPALLING")
    assert suspended["status"] == "SUSPENDED"
    assert suspended["last_inspection_result"] == "FAIL"

    response = api.event_transition(event["id"], {"action": "CONFIRM_SITE"}, COORDINATOR)
    validate_error(response, ApiErrorId.ERR_SITE_NOT_APPROVED, 409)

    assert read_event(event["id"])["lifecycle_status"] == "PLANNED"


def test_suspension_leaves_a_planned_event_outside_the_containment_cascade(api):
    """PRD §3.2: "The site's `last_inspection_result` becomes `FAIL`, and every
    collection event at that site whose lifecycle axis currently reads
    `SITE_CONFIRMED` or `OPEN_FOR_REGISTRATION` has its containment axis forced to
    `DEFICIENT`, with an entry recording an origin of `SITE` and a result of `FAIL`
    appended to that event's `containment_findings`."

    Design: Difficulty/cross_entity_state_dependency/event_site_confirmation_depends_on_site_status
    """
    program = create_program()
    site = create_approved_site(program["id"])
    event = create_event(program["id"], site["id"])
    assert event["lifecycle_status"] == "PLANNED"

    site_action(site["id"], "SUSPEND", SITE_APPROVER, finding_code="PAD-SPALLING")

    after = read_event(event["id"])
    assert after["containment_status"] == "PENDING_INSPECTION", (
        "A PLANNED event is outside the suspension cascade set"
    )
    assert after["lifecycle_status"] == "PLANNED"
