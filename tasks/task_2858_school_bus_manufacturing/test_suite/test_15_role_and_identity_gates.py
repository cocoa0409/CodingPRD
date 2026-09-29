"""Who may act: header authentication, exclusive writes, identity and ownership."""

from test_helpers import (
    COMPLIANCE,
    CONTRACTS,
    CONTRACTS_2,
    PLANT,
    QUALITY,
    SALES,
    TEST_USERS,
    TX_BID_CONFIG,
    ApiErrorId,
    api_client,
    assert_kit_pool_conserved,
    bid_payload,
    bus_model_payload,
    create_bus_model,
    create_campaign,
    create_dealer,
    create_legacy_unit,
    create_profile,
    dealer_payload,
    headers_with_undeclared_role,
    headers_without_role,
    headers_without_user_id,
    launch_campaign,
    list_tasks,
    make_contracts_admin_headers,
    make_dealer_agent_headers,
    make_sales_engineer_headers,
    production_line_payload,
    read_campaign,
    read_dealer,
    read_task,
    read_unit,
    set_clock,
    setup_tx_catalogue,
    solicitation_payload,
    test_bay_payload,
    tx_profile_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

DEALER_FALLBACK = TEST_USERS["dealer_agent_headers"]
# One operator holding two roles legitimately, used for the segregation check.
DUAL_USER_ID = "dual-01"
SEPTEMBER_CLOCK = "2026-09-01T00:00:00Z"


class TestHeaderAuthentication:
    """Authentication is header-shaped, and it is decided before anything else."""

    def test_a_missing_header_or_an_undeclared_role_is_unauthenticated(self):
        """Omitting either header, and naming a role the system does not declare, all
        report the same authentication failure — even on a read, and even when the
        payload is unusable.

        PRD: "Authentication — both headers present and `X-User-Role` naming a declared
        role: `ERR_UNAUTHENTICATED` (401), on every endpoint."
        PRD: "The six roles are `SalesEngineer`, `ContractsAdmin`, `PlantScheduler`,
        `QualityInspector`, `ComplianceOfficer` and `DealerAgent`."

        Design: Corner/rbac/absent_or_undeclared_role_headers_are_unauthenticated
        """
        model = create_bus_model()

        validate_error(
            api_client.get_bus_model(model["id"], headers_without_role("compliance-01")),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            401,
        )
        validate_error(
            api_client.get_bus_model(
                model["id"], headers_without_user_id("ComplianceOfficer")
            ),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            401,
        )
        outsider = headers_with_undeclared_role("outsider-01", "FleetOwner")
        # An undeclared role is not a role that merely lacks permission.
        validate_error(
            api_client.get_bus_model(model["id"], outsider),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            401,
        )
        # Authentication also precedes request-shape validation.
        validate_error(
            api_client.create_bus_model({"model_code": "TYPE_D_TRANSIT"}, outsider),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            401,
        )

        # The row and the route were fine all along.
        allowed = validate_success(api_client.get_bus_model(model["id"], DEALER_FALLBACK))
        assert allowed["model_code"] == "TYPE_C_CONV"
        assert allowed["version"] == 1


class TestExclusiveWriteVerbs:
    """Five registries, five owning roles, and no hierarchy between them."""

    def test_each_registry_creation_refuses_every_role_but_its_own(self):
        """A scheduler cannot register a body, an inspector cannot open a line, a
        dealer agent cannot register a bay and a sales engineer cannot register a
        dealer, while the denial outranks even an empty payload.

        PRD: "Read access is uniform: every one of the six roles may call every
        retrieval endpoint, and every one of the six may set the logical clock. Write
        access is exclusive to a single role per operation".
        PRD: "Authorisation — the acting role appears in the target operation's
        authorised list: `ERR_ROLE_NOT_PERMITTED` (403), on every endpoint."

        Design: Corner/rbac/wrong_role_calls_are_rejected_on_every_exclusive_operation
        """
        denied = [
            api_client.create_bus_model(bus_model_payload(), PLANT),
            api_client.create_production_line(production_line_payload(), QUALITY),
            api_client.create_test_bay(test_bay_payload(), DEALER_FALLBACK),
            api_client.create_dealer(dealer_payload(), SALES),
        ]
        for response in denied:
            validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

        # An empty body would be a shape failure, but the role gate is reached first.
        validate_error(
            api_client.create_solicitation({}, COMPLIANCE),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
            403,
        )

        permitted = validate_success(
            api_client.create_bus_model(bus_model_payload(), COMPLIANCE), 201
        )
        assert permitted["model_code"] == "TYPE_C_CONV"

        # Nothing the denials attempted was written.
        _, model_meta = validate_paginated(api_client.list_bus_models(DEALER_FALLBACK))
        assert model_meta["total_count"] == 1
        for listing in (
            api_client.list_production_lines(DEALER_FALLBACK),
            api_client.list_test_bays(DEALER_FALLBACK),
            api_client.list_dealers(DEALER_FALLBACK),
            api_client.list_solicitations(DEALER_FALLBACK),
        ):
            _, meta = validate_paginated(listing)
            assert meta["total_count"] == 0


class TestSegregationOfDutiesOnTheAward:
    """The bar is on the identity, and it sits below the solicitation-state gate."""

    def test_the_submitter_cannot_award_its_own_bid_but_a_colleague_can(self):
        """One operator holding both roles is refused the award of the bid it
        submitted, while the still-open solicitation is reported first and a second
        contracts administrator awards the same bid straight afterwards.

        PRD: "The acting `X-User-ID` must differ from the bid's `submitted_by_user_id`,
        or the award is refused with `ERR_SEGREGATION_OF_DUTIES`."
        PRD: "Its solicitation must have reached `CLOSED` — a still-open solicitation
        cannot be awarded, and the refusal is `ERR_SOLICITATION_NOT_CLOSED`."
        PRD: "The solicitation is `OPEN`: `ERR_SOLICITATION_NOT_OPEN` (409), on
        drafting a bid, appending a bid revision, submitting a bid, requesting a
        revision and closing the solicitation."

        Design: Corner/rbac/same_user_cannot_submit_and_award_the_same_bid
        """
        set_clock(SEPTEMBER_CLOCK)
        catalogue = setup_tx_catalogue()
        dual_sales = make_sales_engineer_headers(DUAL_USER_ID)
        dual_contracts = make_contracts_admin_headers(DUAL_USER_ID)

        solicitation = validate_success(
            api_client.create_solicitation(
                solicitation_payload(
                    catalogue["profile"]["id"],
                    solicitation_code="SOL-TX-123",
                    required_delivery_date="2026-12-01",
                    price_cap_cents_per_unit=40_000_000,
                ),
                dual_sales,
            ),
            201,
        )
        bid = validate_success(
            api_client.create_bid(
                bid_payload(
                    solicitation["id"], catalogue["model"]["id"],
                    catalogue["package"]["id"], **TX_BID_CONFIG,
                ),
                dual_sales,
            ),
            201,
        )
        submitted = validate_success(api_client.submit_bid(bid["id"], dual_sales))
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_by_user_id"] == DUAL_USER_ID

        # Both rules are broken; the solicitation gate is the higher rung.
        validate_error(
            api_client.award_bid(bid["id"], "2026-11-20", dual_contracts),
            ApiErrorId.ERR_SOLICITATION_NOT_CLOSED.value,
            409,
        )
        closed = validate_success(
            api_client.close_solicitation(solicitation["id"], CONTRACTS)
        )
        assert closed["status"] == "CLOSED"

        # Role-permitted on both calls, and still refused: the bar is on the identity.
        validate_error(
            api_client.award_bid(bid["id"], "2026-11-20", dual_contracts),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            403,
        )

        order = validate_success(
            api_client.award_bid(bid["id"], "2026-11-20", CONTRACTS_2), 201
        )
        assert order["status"] == "ACTIVE"
        assert validate_success(api_client.get_bid(bid["id"], SALES))["status"] == "AWARDED"

        # Resubmitting breaks two rungs at once — the solicitation is no longer OPEN
        # and the bid is no longer DRAFT — and rung 22 outranks rung 24.
        validate_error(
            api_client.submit_bid(bid["id"], dual_sales),
            ApiErrorId.ERR_SOLICITATION_NOT_OPEN.value,
            409,
        )


class TestDealerAgentOwnership:
    """Two dealer agents are peers, and the stranger learns nothing about the row."""

    def _one_open_task_at_the_texas_dealer(self) -> dict:
        """A launched campaign holding a single open task on the one historical bus of
        a Texas dealer, with an unrelated Nevada dealer standing by."""
        set_clock(SEPTEMBER_CLOCK)
        catalogue = setup_tx_catalogue()
        texas = create_dealer(
            dealer_code="D-TX", licensed_state_codes=["TX"],
            training_capacity_per_month=12,
        )
        nevada = create_dealer(
            dealer_code="D-NV", dealer_name="Silver State Bus",
            licensed_state_codes=["NV"], training_capacity_per_month=6,
        )
        unit = create_legacy_unit(
            texas["id"], catalogue["model"]["id"], catalogue["package"]["id"],
            catalogue["profile"]["id"], "1TXDSL0000000901", "2026-05-10T00:00:00Z",
        )
        campaign = create_campaign(catalogue["model"]["id"], total_kits=4)
        launched = launch_campaign(campaign["id"])
        assert launched["affected_unit_count"] == 1
        assert launched["reserved_kits"] == 1

        tasks = list_tasks(recall_campaign_id=campaign["id"])
        assert len(tasks) == 1
        assert tasks[0]["status"] == "OPEN"
        assert tasks[0]["dealer_id"] == texas["id"]
        return {
            "texas": texas, "nevada": nevada, "unit": unit,
            "campaign": campaign, "task": tasks[0],
        }

    def test_the_stranger_is_refused_ahead_of_both_the_role_and_the_state_check(self):
        """A Nevada agent's start is refused on ownership while the task is startable,
        a scheduler's start is refused earlier still on role, and after the owner has
        started the task the stranger's second attempt reports ownership again rather
        than the state.

        PRD: "This ownership check runs after the target row has been located — the
        owner is unknown until the row is loaded — and before any state precondition is
        examined, so a dealer agent probing another dealer's remedy task learns nothing
        about that task's status."
        PRD: "the acting `X-User-ID` must equal the task's `dealer_id`, otherwise
        `ERR_NOT_ASSIGNED_DEALER`, and the task must be `OPEN`, otherwise
        `ERR_TASK_STATE_INVALID`."

        Design: Corner/rbac/dealer_agent_touching_another_dealers_remedy_task_is_rejected
        """
        scenario = self._one_open_task_at_the_texas_dealer()
        task_id = scenario["task"]["id"]
        stranger = make_dealer_agent_headers(scenario["nevada"]["id"])
        owner = make_dealer_agent_headers(scenario["texas"]["id"])

        validate_error(
            api_client.start_remedy_task(task_id, stranger),
            ApiErrorId.ERR_NOT_ASSIGNED_DEALER.value,
            403,
        )
        # The role gate sits above the ownership gate.
        validate_error(
            api_client.start_remedy_task(task_id, PLANT),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
            403,
        )
        assert read_task(task_id)["status"] == "OPEN"

        started = validate_success(api_client.start_remedy_task(task_id, owner))
        assert started["status"] == "IN_PROGRESS"
        assert started["kits_reserved"] == 1
        in_progress = read_campaign(scenario["campaign"]["id"])
        assert in_progress["reserved_kits"] == 1
        assert in_progress["consumed_kits"] == 0

        validate_error(
            api_client.start_remedy_task(task_id, owner),
            ApiErrorId.ERR_TASK_STATE_INVALID.value,
            409,
        )
        # The same call, the same state, a different error for the stranger.
        validate_error(
            api_client.start_remedy_task(task_id, stranger),
            ApiErrorId.ERR_NOT_ASSIGNED_DEALER.value,
            403,
        )
        assert read_task(task_id)["status"] == "IN_PROGRESS"

    def test_the_owner_closes_the_task_and_the_officer_cannot_cancel_it_afterwards(self):
        """Completion by the owning agent consumes the kit and clears the dealer's
        exposure, and the compliance officer's cancellation of the closed task is
        refused without disturbing the kit ledger.

        PRD: "A `DealerAgent` starting or completing a remedy task, completing driver
        training for a bus, or delivering a bus must own the target: the `dealer_id` of
        the remedy task or of the bus must equal `X-User-ID`".
        PRD: "the campaign's `consumed_kits` increases by the task's `kits_reserved`
        and `reserved_kits` decreases by exactly the same amount, so `available_kits`
        does not move."

        Design: Corner/rbac/dealer_agent_touching_another_dealers_remedy_task_is_rejected
        """
        scenario = self._one_open_task_at_the_texas_dealer()
        task_id = scenario["task"]["id"]
        owner = make_dealer_agent_headers(scenario["texas"]["id"])
        stranger = make_dealer_agent_headers(scenario["nevada"]["id"])
        validate_success(api_client.start_remedy_task(task_id, owner))

        validate_error(
            api_client.complete_remedy_task(task_id, stranger),
            ApiErrorId.ERR_NOT_ASSIGNED_DEALER.value,
            403,
        )
        completed = validate_success(api_client.complete_remedy_task(task_id, owner))
        assert completed["status"] == "COMPLETED"

        campaign = read_campaign(scenario["campaign"]["id"])
        assert campaign["consumed_kits"] == 1
        assert campaign["reserved_kits"] == 0
        assert campaign["available_kits"] == 3
        assert_kit_pool_conserved(campaign)
        assert read_unit(scenario["unit"]["id"])["service_status"] == "RECALL_CLOSED"
        dealer = read_dealer(scenario["texas"]["id"])
        assert dealer["open_recall_unit_count"] == 0
        assert dealer["certification_standing"] == "GOOD"

        # Cancellation is the officer's verb, but not on a closed task.
        validate_error(
            api_client.cancel_remedy_task(task_id, COMPLIANCE),
            ApiErrorId.ERR_TASK_STATE_INVALID.value,
            409,
        )
        assert read_task(task_id)["status"] == "COMPLETED"
        assert read_campaign(scenario["campaign"]["id"])["consumed_kits"] == 1


class TestSharedReads:
    """Reads are role-blind, publication-blind and ownership-blind."""

    def test_three_roles_read_one_body_and_a_draft_profile_is_visible_to_all(self):
        """A sales engineer, an inspector and a dealer agent get byte-identical bodies
        for the same model, an unpublished profile is listed to a scheduler, and no read
        moves a version.

        PRD: "every read endpoint in the system is open to all of them, and every write
        endpoint is restricted."
        PRD: "Retrieval endpoints never recompute anything".

        Design: Corner/rbac/shared_read_operations_are_open_to_every_declared_role
        """
        model = create_bus_model()
        draft = create_profile(tx_profile_payload(), publish=False)
        dealer = create_dealer(
            dealer_code="D-TX", licensed_state_codes=["TX"],
            training_capacity_per_month=12,
        )
        agent = make_dealer_agent_headers(dealer["id"])

        bodies = [
            validate_success(api_client.get_bus_model(model["id"], headers))
            for headers in (SALES, QUALITY, agent)
        ]
        for body in bodies:
            assert body == bodies[0]
            assert body["model_code"] == "TYPE_C_CONV"
            assert body["body_joint_strength_kn"] == 58.0
            assert body["version"] == 1

        drafts, draft_meta = validate_paginated(
            api_client.list_state_spec_profiles(PLANT, {"status": "DRAFT"})
        )
        # Publication status governs what may be cited, not who may look.
        assert draft_meta["total_count"] == 1
        assert drafts[0]["id"] == draft["id"]
        assert drafts[0]["status"] == "DRAFT"

        dealers, dealer_meta = validate_paginated(
            api_client.list_dealers(agent, {"certification_standing": "GOOD"})
        )
        assert dealer_meta["total_count"] == 1
        assert dealers[0]["id"] == dealer["id"]

        # Five reads later, nothing has moved.
        assert read_dealer(dealer["id"])["version"] == dealer["version"]
        assert read_dealer(dealer["id"])["updated_at"] == dealer["updated_at"]
        final = validate_success(api_client.get_bus_model(model["id"], COMPLIANCE))
        assert final["version"] == 1
        assert final["updated_at"] == model["updated_at"]
