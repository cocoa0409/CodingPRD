"""Authentication, per-endpoint authorisation, household ownership isolation and
path-identifier resolution — the checks that run ahead of every domain rule, in the order
the specification fixes for them."""

from test_helpers import (
    ASSET_MANAGER_ALT_USER_ID,
    ASSET_MANAGER_USER_ID,
    BLANK_ROLE_HEADERS,
    BLANK_USER_ID_HOUSEHOLD_HEADERS,
    NON_EXISTENT_UUID,
    NO_ROLE_HEADERS,
    NO_USER_ID_HOUSEHOLD_HEADERS,
    UNKNOWN_ROLE_HEADERS,
    ApiErrorId,
    concession_decision_payload,
    create_community,
    create_community_payload,
    create_concession_program,
    create_homesite_payload,
    create_household,
    create_phase,
    create_plat_approved_community,
    draft_lease,
    get_success_data,
    halt_payload,
    make_asset_manager_headers,
    make_household_headers,
    occupancy_certificate_payload,
    publish_schedule,
    publish_schedule_payload,
    read_community,
    read_homesite,
    read_lease,
    read_phase,
    read_program,
    request_concession,
    section_release_payload,
    setup_draft_lease,
    setup_released_community,
    signature_payload,
    submit_lease,
    validate_error,
    validate_paginated,
    validate_success,
)

BASE_RENT_CENTS = 285_000
MIX_FOUR_DETACHED = {"DETACHED": 4, "COTTAGE": 0, "TOWNHOME": 0}
MIX_TWO_DETACHED = {"DETACHED": 2, "COTTAGE": 0, "TOWNHOME": 0}


def test_entitlement_officer_cannot_create_a_community(api, entitlement_officer_headers, developer_principal_headers):
    """The municipal reviewer owns plat decisions and nothing on the site-setup side, so its
    attempt to register a community is refused before any community exists.

    "Once authenticated, the caller's role is checked against the set of roles authorised for the endpoint it is invoking, listed in the table in §4."
    "A role outside that set receives `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/an_entitlement_officer_cannot_create_a_community_or_read_leases
    """
    refusal = api.create_community(
        create_community_payload(
            name="Larkmead",
            market_code="ID-BOI",
            total_planned_units=4,
            product_mix=MIX_FOUR_DETACHED,
            concession_budget_cents=1_000_000,
            facility_commitment_cents=20_000_000,
        ),
        entitlement_officer_headers,
    )
    validate_error(refusal, ApiErrorId.ERR_UNAUTHORIZED.value)

    _, meta = validate_paginated(api.list_communities(developer_principal_headers))
    assert meta["total_count"] == 0


def test_entitlement_officer_may_list_communities_but_not_leases(api, entitlement_officer_headers):
    """Read access is enumerated endpoint by endpoint rather than granted wholesale: the same
    caller is allowed on the community list and refused on the lease list.

    "Once authenticated, the caller's role is checked against the set of roles authorised for the endpoint it is invoking, listed in the table in §4."
    "A role outside that set receives `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/an_entitlement_officer_cannot_create_a_community_or_read_leases
    """
    validate_error(api.list_leases(entitlement_officer_headers), ApiErrorId.ERR_UNAUTHORIZED.value)

    data, meta = validate_paginated(api.list_communities(entitlement_officer_headers))
    assert data == []
    assert meta["total_count"] == 0


def test_property_manager_cannot_publish_a_market_rent_schedule(api, property_manager_headers):
    """Pricing is an asset-management exclusive, and the refusal comes back even though the
    request carries the community version the caller correctly observed.

    "A role outside that set receives `ERR_UNAUTHORIZED` (HTTP 403)."
    "**Authorisation** — the role is on the endpoint's list (`ERR_UNAUTHORIZED`)."
    "**Optimistic concurrency** — `expected_community_version` matches, on the two endpoints that carry it (`ERR_STALE_COMMUNITY_VERSION`)."

    Design: Corner/rbac/a_property_manager_cannot_publish_a_market_rent_schedule
    """
    community = create_plat_approved_community(
        name="Mereview",
        market_code="ID-IDA",
        total_planned_units=4,
        product_mix=MIX_FOUR_DETACHED,
        concession_budget_cents=1_000_000,
        facility_commitment_cents=20_000_000,
    )
    observed_version = community["version"]

    refusal = api.publish_market_rent_schedule(
        publish_schedule_payload(
            community["id"], observed_version, asking_rent_cents=BASE_RENT_CENTS
        ),
        property_manager_headers,
    )
    validate_error(refusal, ApiErrorId.ERR_UNAUTHORIZED.value)

    assert read_community(community["id"])["version"] == observed_version


def test_asset_manager_publishes_the_identical_body_the_property_manager_was_refused(
    api, asset_manager_headers, property_manager_headers
):
    """Swapping only the acting role turns the refused publication into a published schedule,
    which proves the rejection was about the role and nothing else.

    "A role outside that set receives `ERR_UNAUTHORIZED` (HTTP 403)."
    "the server records it where a rule requires an actor to be remembered — as `plat_submitted_by_user_id` and `published_by_user_id` on a community and a rent schedule"

    Design: Corner/rbac/a_property_manager_cannot_publish_a_market_rent_schedule
    """
    community = create_plat_approved_community(
        name="Mereview",
        market_code="ID-IDA",
        total_planned_units=4,
        product_mix=MIX_FOUR_DETACHED,
        concession_budget_cents=1_000_000,
        facility_commitment_cents=20_000_000,
    )
    payload = publish_schedule_payload(
        community["id"], community["version"], asking_rent_cents=BASE_RENT_CENTS
    )

    validate_error(
        api.publish_market_rent_schedule(payload, property_manager_headers),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    published = validate_success(
        api.publish_market_rent_schedule(payload, asset_manager_headers),
        expected_status=201,
    )
    assert published["status"] == "PUBLISHED"
    assert published["published_by_user_id"] == ASSET_MANAGER_USER_ID
    assert published["asking_rent_cents"] == BASE_RENT_CENTS

    _, meta = validate_paginated(
        api.list_market_rent_schedules(asset_manager_headers, {"community_id": community["id"]})
    )
    assert meta["total_count"] == 1


def test_leasing_agent_cannot_decide_the_concession_it_requested(api, leasing_agent_headers):
    """The agent that raised the concession request has no standing to decide it at all, and
    the refusal is the role check rather than the identity check that would follow it.

    "**`LeasingAgent`** — registers households, drafts and submits leases, and raises concession requests. May never decide a concession."
    "**Authorisation** — the role is on the endpoint's list (`ERR_UNAUTHORIZED`)."
    "**Segregation of duties** — the decider is the submitter or requester (`ERR_SEGREGATION_OF_DUTIES`)."

    Design: Corner/rbac/a_leasing_agent_cannot_decide_the_concession_it_requested
    """
    scenario = setup_draft_lease(
        homesite_count=1,
        total_planned_units=4,
        product_mix=MIX_FOUR_DETACHED,
        asking_rent_cents=BASE_RENT_CENTS,
        market_code="UT-SLC",
        concession_budget_cents=2_000_000,
        facility_commitment_cents=25_000_000,
    )
    program = create_concession_program(
        scenario["community"]["id"],
        tier="LIGHT",
        free_weeks=2,
        eligible_product_types=["DETACHED"],
        max_budget_cents=1_000_000,
    )
    request_concession(scenario["lease"]["id"], program["id"])

    refusal = api.decide_concession(
        scenario["lease"]["id"],
        concession_decision_payload("APPROVE", decision_note="self-approval attempt"),
        leasing_agent_headers,
    )
    validate_error(refusal, ApiErrorId.ERR_UNAUTHORIZED.value)

    lease = read_lease(scenario["lease"]["id"])
    assert lease["concession_status"] == "REQUESTED"
    assert lease["concession_decided_by_user_id"] is None
    assert read_community(scenario["community"]["id"])["committed_concession_cents"] == 0
    assert read_program(program["id"])["committed_cents"] == 0


def test_an_independent_asset_manager_closes_the_concession_decision(api, leasing_agent_headers):
    """An asset manager whose operator id differs from the requester's approves the same
    concession, and both ledgers grow by the single rounded total.

    "On approval `concession_status` becomes `APPROVED`, `concession_decided_by_user_id` records the deciding `X-User-ID`, and both ledgers grow by `total_concession_cents` — the community's `committed_concession_cents` and the program's `committed_cents`."
    "First, `total_concession_cents` is the lease's `gross_monthly_charge_cents` multiplied by the program's `free_weeks`, multiplied by 12 and divided by 52 — the weeks-per-month conversion that turns a weekly allowance into monthly charges — rounded half up to whole cents."

    Design: Corner/rbac/a_leasing_agent_cannot_decide_the_concession_it_requested
    """
    scenario = setup_draft_lease(
        homesite_count=1,
        total_planned_units=4,
        product_mix=MIX_FOUR_DETACHED,
        asking_rent_cents=BASE_RENT_CENTS,
        market_code="UT-SLC",
        concession_budget_cents=2_000_000,
        facility_commitment_cents=25_000_000,
    )
    program = create_concession_program(
        scenario["community"]["id"],
        tier="LIGHT",
        free_weeks=2,
        eligible_product_types=["DETACHED"],
        max_budget_cents=1_000_000,
    )
    request_concession(scenario["lease"]["id"], program["id"])
    validate_error(
        api.decide_concession(
            scenario["lease"]["id"],
            concession_decision_payload("APPROVE", decision_note="self-approval attempt"),
            leasing_agent_headers,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    decided = validate_success(
        api.decide_concession(
            scenario["lease"]["id"],
            concession_decision_payload("APPROVE", decision_note="independent review"),
            make_asset_manager_headers(ASSET_MANAGER_ALT_USER_ID),
        ),
        expected_status=201,
    )
    assert decided["concession_status"] == "APPROVED"
    assert decided["concession_decided_by_user_id"] == ASSET_MANAGER_ALT_USER_ID
    assert decided["total_concession_cents"] == 137562

    assert read_community(scenario["community"]["id"])["committed_concession_cents"] == 137562
    assert read_program(program["id"])["committed_cents"] == 137562


def test_a_household_reads_its_own_lease_but_not_its_neighbours(api):
    """Two residents in the same community hold one lease each. The same endpoint answers the
    owner and refuses the neighbour, and it refuses on ownership rather than on role, because
    the resident role is permitted there.

    "Ownership checks compare a resource's household foreign key to `X-User-ID`: a `Household` caller may read or act on a lease only when that lease's `household_id` equals its own `X-User-ID`, and may read a household record only when that record is its own."
    "A mismatch is rejected with `ERR_OWNERSHIP_VIOLATION` (HTTP 403)."
    "A Household caller may only read its own lease."

    Design: Corner/rbac/a_household_cannot_read_another_households_lease
    """
    scenario = setup_released_community(
        homesite_count=2,
        total_planned_units=4,
        product_mix=MIX_FOUR_DETACHED,
        asking_rent_cents=BASE_RENT_CENTS,
        market_code="UT-PRV",
        concession_budget_cents=1_000_000,
        facility_commitment_cents=25_000_000,
    )
    first_household = create_household(primary_applicant_name="Ola Mere")
    first_lease = draft_lease(scenario["homesites"][0]["id"], first_household["id"])
    second_household = create_household(
        primary_applicant_name="Otto Nash", household_size=2, credit_tier="B"
    )
    second_lease = draft_lease(scenario["homesites"][1]["id"], second_household["id"])

    own = validate_success(
        api.get_lease(first_lease["id"], make_household_headers(first_household["id"]))
    )
    assert own["id"] == first_lease["id"]
    assert own["household_id"] == first_household["id"]

    neighbour = api.get_lease(second_lease["id"], make_household_headers(first_household["id"]))
    validate_error(neighbour, ApiErrorId.ERR_OWNERSHIP_VIOLATION.value)


def test_a_household_cannot_sign_its_neighbours_lease(api):
    """A resident who reaches for the neighbour's pending contract is refused, and none of the
    signature cascade fires: the contract, the home and the community counters all stand.

    "The signing `X-User-ID` must equal the lease's `household_id`, or the request is `ERR_OWNERSHIP_VIOLATION`."
    "**Ownership** — a `Household` caller acting on someone else's lease (`ERR_OWNERSHIP_VIOLATION`)."
    "Hop one, caused by hop zero, moves the home `AVAILABLE → LEASED`."

    Design: Corner/rbac/a_household_cannot_read_another_households_lease
    """
    scenario = setup_released_community(
        homesite_count=2,
        total_planned_units=4,
        product_mix=MIX_FOUR_DETACHED,
        asking_rent_cents=BASE_RENT_CENTS,
        market_code="UT-PRV",
        concession_budget_cents=1_000_000,
        facility_commitment_cents=25_000_000,
    )
    first_household = create_household(primary_applicant_name="Ola Mere")
    draft_lease(scenario["homesites"][0]["id"], first_household["id"])
    second_household = create_household(
        primary_applicant_name="Otto Nash", household_size=2, credit_tier="B"
    )
    second_lease = draft_lease(scenario["homesites"][1]["id"], second_household["id"])
    submit_lease(second_lease["id"])

    intrusion = api.sign_lease(
        second_lease["id"],
        signature_payload("Ola Mere"),
        make_household_headers(first_household["id"]),
    )
    validate_error(intrusion, ApiErrorId.ERR_OWNERSHIP_VIOLATION.value)

    assert read_lease(second_lease["id"])["lease_status"] == "PENDING_SIGNATURE"
    assert read_homesite(scenario["homesites"][1]["id"])["status"] == "AVAILABLE"
    assert read_community(scenario["community"]["id"])["leased_unit_count"] == 0


def test_the_construction_manager_runs_every_construction_operation_on_one_phase(
    api, construction_manager_headers
):
    """The construction role walks a two-home section from ground-breaking to phase
    completion — start, two homes, two certificates, an incremental release, a halt, a
    resume, the second release and completion — with no authorisation failure anywhere.

    "**`ConstructionManager`** — runs construction phasing, records certificates of occupancy, performs incremental section releases, and halts and resumes phases."
    "On the very first release anywhere in the community, two further things happen in the same request: the community's `lifecycle_status` moves `CONSTRUCTION → LEASE_UP`, and its `facility_status` moves `CONSTRUCTION_DRAW → ADVANCE_ELIGIBLE`, because a community with rentable inventory can start drawing against the facility on an advance basis."
    "The zeroth hop touches the phase itself: `status` becomes `CONSTRUCTION_HALTED`, `pre_halt_status` records the status the phase held immediately before the halt — `UNDER_CONSTRUCTION` for a phase halted mid-build, `SECTIONS_RELEASED` for a phase that had already released sections — and `halt_count` increases by 1."
    "Every homesite of the community whose `status` is `AVAILABLE`, taken in `created_at` ascending order, moves `AVAILABLE → OFF_MARKET` with `off_market_reason` set to `POSTURE_FREEZE`."
    "The phase returns to whatever `pre_halt_status` holds, which is either `CONSTRUCTION_HALTED → UNDER_CONSTRUCTION` or `CONSTRUCTION_HALTED → SECTIONS_RELEASED`, and `pre_halt_status` is then cleared to null; `halt_count` is a running total and is never decremented."
    "Completing a `HOUSING` phase requires that its `status` is `SECTIONS_RELEASED` and that its `released_homesite_count` equals its `planned_unit_count` — every planned home in the phase must have been released — and a completion attempted from any other state, or with homes still unreleased, is `ERR_INVALID_PHASE_STATE`."

    Design: Corner/rbac/the_construction_manager_can_run_every_construction_exclusive_operation
    """
    community = create_plat_approved_community(
        name="Pellingham",
        market_code="NM-ABQ",
        total_planned_units=2,
        product_mix=MIX_TWO_DETACHED,
        concession_budget_cents=1_000_000,
        facility_commitment_cents=20_000_000,
    )
    community_id = community["id"]
    publish_schedule(community_id, asking_rent_cents=BASE_RENT_CENTS)
    phase = create_phase(community_id, planned_unit_count=2)
    phase_id = phase["id"]

    started = get_success_data(api.start_construction(phase_id, {}, construction_manager_headers))
    assert started["status"] == "UNDER_CONSTRUCTION"

    first_home = get_success_data(
        api.create_homesite(
            create_homesite_payload(
                phase_id, lot_number="P1", product_type="DETACHED", bedrooms=4, square_feet=2100
            ),
            construction_manager_headers,
        )
    )
    second_home = get_success_data(
        api.create_homesite(
            create_homesite_payload(
                phase_id, lot_number="P2", product_type="DETACHED", bedrooms=3, square_feet=1950
            ),
            construction_manager_headers,
        )
    )
    get_success_data(
        api.record_occupancy_certificate(
            first_home["id"],
            occupancy_certificate_payload(occupancy_certificate_number="CO-PG-P1"),
            construction_manager_headers,
        )
    )
    get_success_data(
        api.record_occupancy_certificate(
            second_home["id"],
            occupancy_certificate_payload(occupancy_certificate_number="CO-PG-P2"),
            construction_manager_headers,
        )
    )

    get_success_data(
        api.release_section(
            phase_id, section_release_payload([first_home["id"]]), construction_manager_headers
        )
    )
    assert read_phase(phase_id)["status"] == "SECTIONS_RELEASED"
    after_release = read_community(community_id)
    assert after_release["lifecycle_status"] == "LEASE_UP"
    assert after_release["facility_status"] == "ADVANCE_ELIGIBLE"

    get_success_data(
        api.halt_phase(
            phase_id,
            halt_payload(halt_reason="utility tie-in delay"),
            construction_manager_headers,
        )
    )
    halted = read_phase(phase_id)
    assert halted["status"] == "CONSTRUCTION_HALTED"
    assert halted["pre_halt_status"] == "SECTIONS_RELEASED"
    assert halted["halt_count"] == 1
    assert read_community(community_id)["posture"] == "FROZEN"
    assert read_homesite(first_home["id"])["status"] == "OFF_MARKET"

    get_success_data(api.resume_phase(phase_id, {}, construction_manager_headers))
    resumed = read_phase(phase_id)
    assert resumed["status"] == "SECTIONS_RELEASED"
    assert resumed["pre_halt_status"] is None
    assert resumed["halt_count"] == 1
    assert read_community(community_id)["posture"] == "OPEN"
    assert read_homesite(first_home["id"])["status"] == "AVAILABLE"

    get_success_data(
        api.release_section(
            phase_id, section_release_payload([second_home["id"]]), construction_manager_headers
        )
    )
    fully_released = read_phase(phase_id)
    assert fully_released["released_homesite_count"] == 2
    assert fully_released["released_homesite_count"] == fully_released["planned_unit_count"]
    assert read_community(community_id)["released_unit_count"] == 2

    get_success_data(api.complete_phase(phase_id, {}, construction_manager_headers))
    assert read_phase(phase_id)["status"] == "COMPLETE"
    assert read_community(community_id)["lifecycle_status"] == "LEASE_UP"


def test_blank_unknown_and_identityless_callers_are_unauthenticated(api):
    """Three header shapes fail authentication: a blank role, a role that is not in the
    catalogue, and a resident call with no identity. The last one addresses an id that does
    not exist and still comes back as an authentication failure, never as a lookup failure.

    "If `X-User-Role` is absent, blank, or names something outside the role catalogue below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); the same rejection applies when the caller's role is `Household` and `X-User-ID` is absent or blank."
    "**Authentication** — headers present and role recognised (`ERR_UNAUTHENTICATED`)."
    "**Path existence** — every path identifier resolves (the family of `..._NOT_FOUND` codes)."

    Design: Corner/errors/requests_missing_auth_headers_return_unauthenticated
    """
    validate_error(
        api.list_communities(BLANK_ROLE_HEADERS), ApiErrorId.ERR_UNAUTHENTICATED.value
    )
    validate_error(
        api.list_communities(UNKNOWN_ROLE_HEADERS), ApiErrorId.ERR_UNAUTHENTICATED.value
    )
    validate_error(
        api.get_lease(NON_EXISTENT_UUID, BLANK_USER_ID_HOUSEHOLD_HEADERS),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )


def test_requests_that_omit_the_auth_headers_are_unauthenticated(api):
    """An absent role header and an absent resident identity are refused exactly as their
    blank counterparts are.

    "Every request to the service — reads included — must carry two headers."
    "If `X-User-Role` is absent, blank, or names something outside the role catalogue below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); the same rejection applies when the caller's role is `Household` and `X-User-ID` is absent or blank."

    Design: Corner/errors/requests_missing_auth_headers_return_unauthenticated
    """
    validate_error(api.list_communities(NO_ROLE_HEADERS), ApiErrorId.ERR_UNAUTHENTICATED.value)
    validate_error(
        api.get_lease(NON_EXISTENT_UUID, NO_USER_ID_HOUSEHOLD_HEADERS),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )


def test_unknown_path_ids_return_the_entity_specific_not_found_error(api, asset_manager_headers):
    """Seven reads carrying the same unknown identifier each name the collection actually
    addressed rather than one generic not-found code, and the community that does exist is
    untouched by any of them.

    "Path parameters are resolved strictly left to right, and the first identifier that fails to resolve determines the error."
    "A request addressed at a community that does not exist fails with `ERR_COMMUNITY_NOT_FOUND` (HTTP 404) before anything nested under it is considered; the same pattern gives `ERR_PHASE_NOT_FOUND`, `ERR_HOMESITE_NOT_FOUND`, `ERR_RENT_SCHEDULE_NOT_FOUND`, `ERR_CONCESSION_PROGRAM_NOT_FOUND`, `ERR_HOUSEHOLD_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_TURN_WORK_ORDER_NOT_FOUND` and `ERR_ABSORPTION_REVIEW_NOT_FOUND`, each at HTTP 404, for the collection actually addressed."

    Design: Corner/validations/unknown_path_ids_return_the_entity_specific_not_found_error
    """
    community = create_community(
        name="Cobbleford",
        market_code="TX-AUS",
        total_planned_units=2,
        product_mix=MIX_TWO_DETACHED,
        concession_budget_cents=1_000_000,
        facility_commitment_cents=20_000_000,
    )

    validate_error(
        api.get_phase(NON_EXISTENT_UUID, asset_manager_headers),
        ApiErrorId.ERR_PHASE_NOT_FOUND.value,
    )
    validate_error(
        api.get_market_rent_schedule(NON_EXISTENT_UUID, asset_manager_headers),
        ApiErrorId.ERR_RENT_SCHEDULE_NOT_FOUND.value,
    )
    validate_error(
        api.get_concession_program(NON_EXISTENT_UUID, asset_manager_headers),
        ApiErrorId.ERR_CONCESSION_PROGRAM_NOT_FOUND.value,
    )
    validate_error(
        api.get_household(NON_EXISTENT_UUID, asset_manager_headers),
        ApiErrorId.ERR_HOUSEHOLD_NOT_FOUND.value,
    )
    validate_error(
        api.get_lease(NON_EXISTENT_UUID, asset_manager_headers),
        ApiErrorId.ERR_LEASE_NOT_FOUND.value,
    )
    validate_error(
        api.get_turn_work_order(NON_EXISTENT_UUID, asset_manager_headers),
        ApiErrorId.ERR_TURN_WORK_ORDER_NOT_FOUND.value,
    )
    validate_error(
        api.get_absorption_review(NON_EXISTENT_UUID, asset_manager_headers),
        ApiErrorId.ERR_ABSORPTION_REVIEW_NOT_FOUND.value,
    )

    assert read_community(community["id"])["version"] == 1
