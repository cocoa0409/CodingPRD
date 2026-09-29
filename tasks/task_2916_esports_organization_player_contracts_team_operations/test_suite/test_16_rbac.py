"""Who may call, who may be addressed, and who may sign off.

Three separate gates share the same 4xx family and must not be confused: the role
must appear on the endpoint, the identity headers must be populated at all, and an
entity-backed identity must own the resource it names. The fourth gate keys on the
identifier alone and refuses a user who signs off its own paperwork.
"""

from test_helpers import (
    ApiErrorId,
    MISSING_UUID,
    SECOND_PLAYER,
    api_client,
    factories,
    fixtures,
    headers_without_role,
    headers_without_user_id,
    make_coaching_staff_headers,
    make_finance_officer_headers,
    make_general_manager_headers,
    make_guardian_representative_headers,
    make_headers,
    make_league_admin_headers,
    make_ops_manager_headers,
    make_player_agent_headers,
    make_scout_headers,
    make_sponsorship_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_seven_writes_by_the_wrong_role_are_all_refused_at_the_authorization_band():
    """An unlisted role, and an unrecognised one, are refused before any state check runs.

    PRD: "If `X-User-Role` carries a value that is not one of the ten recognised role names, or
    carries a recognised role that is not authorised for the endpoint being addressed, the request is
    refused with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD: "The authoritative role-to-endpoint mapping is the table in §4."
    PRD: "The ten roles are `LeagueAdmin`, `GeneralManager`, `PlayerAgent`, `Scout`,
    `CoachingStaff`, `PerformanceSupport`, `SponsorshipManager`, `FinanceOfficer`, `OpsManager` and
    `GuardianRepresentative`."
    PRD: "Checks are grouped into thirteen precedence bands, evaluated in ascending order; **the
    first violated band determines the response, and no later band runs**."
    PRD: "**Authorization** — `X-User-Role` recognised and permitted on the endpoint, else
    `ERR_UNAUTHORIZED`."
    PRD: "A distribution must be in `CALCULATED`, or `ERR_DISTRIBUTION_NOT_CALCULATED` (HTTP 409) is
    returned, and the approving `X-User-ID` must differ from the recorded `calculated_by_user_id`, or
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) is returned."

    Design: Corner/rbac/role_exclusive_operations_are_refused_to_every_other_role
    """
    ctx = fixtures.setup_league_and_org()
    org_id = ctx["org"]["id"]
    player = fixtures.create_player()
    distribution = fixtures.create_distribution(org_id, ctx["league"]["id"])
    assert distribution["distribution_status"] == "DRAFT"

    unauthorized = ApiErrorId.ERR_UNAUTHORIZED.value

    validate_error(
        api_client.set_current_utc(
            factories.set_clock_payload("2026-09-20T00:00:00Z"), make_scout_headers()
        ),
        unauthorized,
        403,
    )
    validate_error(
        api_client.create_player(
            factories.create_player_payload(full_name="Iris Vale", birth_date="2003-02-02"),
            make_general_manager_headers(org_id),
        ),
        unauthorized,
        403,
    )
    validate_error(
        api_client.create_contract_offer(
            factories.create_contract_offer_payload(org_id, player["id"]),
            make_player_agent_headers(player["id"]),
        ),
        unauthorized,
        403,
    )
    validate_error(
        api_client.create_team_house(
            org_id,
            factories.create_team_house_payload(name="Rogue House"),
            make_coaching_staff_headers(),
        ),
        unauthorized,
        403,
    )
    deal_payload = factories.create_sponsorship_deal_payload(
        org_id,
        sponsor_name="Volt Surge",
        exclusivity_category="ENERGY_DRINK",
        total_fee_cents=1000000,
        deliverable_count_required=2,
    )
    validate_error(
        api_client.create_sponsorship_deal(deal_payload, make_general_manager_headers(org_id)),
        unauthorized,
        403,
    )
    validate_error(
        api_client.approve_prize_distribution(
            distribution["id"], make_finance_officer_headers()
        ),
        unauthorized,
        403,
    )
    validate_error(
        api_client.create_league(
            factories.create_minimal_league_payload(name="Rogue League"),
            make_headers("PitCrew", "admin-1"),
        ),
        unauthorized,
        403,
    )

    permitted = validate_success(
        api_client.create_sponsorship_deal(
            deal_payload, make_sponsorship_manager_headers(org_id)
        ),
        201,
    )
    assert permitted["deal_status"] == "DRAFT"
    assert permitted["organization_id"] == org_id

    for shared_reader in (make_general_manager_headers(org_id), make_scout_headers()):
        rows, meta = validate_paginated(
            api_client.list_players(shared_reader, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [player["id"]]

    untouched = validate_success(
        api_client.get_prize_distribution(distribution["id"], make_finance_officer_headers())
    )
    assert untouched["distribution_status"] == "DRAFT"
    assert untouched["version"] == distribution["version"]


def test_an_empty_identity_header_is_refused_before_the_role_or_the_path_is_read():
    """Blank id, blank role and both blank against a missing player all return the same 401.

    PRD: "Every request to every endpoint, including read-only ones, must carry two headers:
    `X-User-ID` and `X-User-Role`."
    PRD: "If either header is absent or its value is an empty string, the request is refused with
    `ERR_UNAUTHENTICATED` (HTTP 401) before anything else about the request is examined."
    PRD: "Checks are grouped into thirteen precedence bands, evaluated in ascending order; **the
    first violated band determines the response, and no later band runs**."
    PRD: "**Authentication** — both headers present and non-empty, else `ERR_UNAUTHENTICATED`."
    PRD: "An unresolvable league yields `ERR_LEAGUE_NOT_FOUND`, an organization
    `ERR_ORGANIZATION_NOT_FOUND`, a player `ERR_PLAYER_NOT_FOUND`, a contract offer
    `ERR_OFFER_NOT_FOUND`, a player contract `ERR_CONTRACT_NOT_FOUND`, a team house
    `ERR_TEAM_HOUSE_NOT_FOUND`, a practice block `ERR_PRACTICE_BLOCK_NOT_FOUND`, a sponsorship deal
    `ERR_DEAL_NOT_FOUND`, a deliverable assignment `ERR_DELIVERABLE_NOT_FOUND`, a prize distribution
    `ERR_DISTRIBUTION_NOT_FOUND` and a roster move `ERR_ROSTER_MOVE_NOT_FOUND`."

    Design: Corner/rbac/empty_identity_headers_are_refused_before_any_other_check
    """
    unauthenticated = ApiErrorId.ERR_UNAUTHENTICATED.value
    league_payload = factories.create_minimal_league_payload()

    validate_error(
        api_client.create_league(league_payload, headers_without_user_id("LeagueAdmin")),
        unauthenticated,
        401,
    )
    validate_error(
        api_client.create_league(league_payload, headers_without_role("admin-1")),
        unauthenticated,
        401,
    )
    validate_error(
        api_client.get_player(MISSING_UUID, make_headers("", "")),
        unauthenticated,
        401,
    )

    admin_headers = make_league_admin_headers()
    league = validate_success(
        api_client.create_league(league_payload, admin_headers), 201
    )
    assert league["version"] == 1

    rows, meta = validate_paginated(
        api_client.list_leagues(admin_headers, params={"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [league["id"]]


def test_an_entity_backed_caller_may_only_reach_its_own_organization_or_player():
    """Five cross-tenant calls and one cross-tenant read are refused; the owners and the scout succeed.

    PRD: "Three of those roles are **entity-backed on an Organization**."
    PRD: "When `X-User-Role` is `GeneralManager`, `SponsorshipManager` or `OpsManager`, `X-User-ID` is
    the `id` of the acting `Organization`; ownership checks on any resource that references an
    `Organization` compare that resource's organization foreign-key field to `X-User-ID`."
    PRD: "When `X-User-Role` is `PlayerAgent` or `GuardianRepresentative`, `X-User-ID` is the `id` of
    the acting `Player`; ownership checks compare `X-User-ID` to the player the addressed resource
    resolves to — directly for a player resource, and through the `ContractOffer`, `PlayerContract`
    or `DeliverableAssignment` that names that player for the others."
    PRD: "An entity-backed caller that addresses a resource belonging to a different `Organization`
    or a different `Player` is refused with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    PRD: "When `X-User-Role` is `LeagueAdmin`, `Scout`, `CoachingStaff`, `PerformanceSupport` or
    `FinanceOfficer`, `X-User-ID` is an operator identifier that is not tied to any persisted entity
    and is never compared to an entity's `id`."
    PRD: "It applies to every endpoint whose target resource resolves to an `Organization` or to a
    `Player`."

    Design: Corner/rbac/entity_backed_callers_are_scoped_to_their_own_organization_or_player
    """
    ctx = fixtures.setup_signed_player()
    org_a = ctx["org"]["id"]
    org_b = fixtures.create_organization(ctx["league"]["id"], name="Solstice Union")["id"]
    player_p = ctx["player"]["id"]
    player_q = fixtures.create_player(**SECOND_PLAYER)["id"]
    offer_q = fixtures.create_offer(
        org_a,
        player_q,
        base_salary_cents=4000000,
        prize_split_player_pct_bp=4000,
        streaming_hours_per_week=20,
    )
    deal_a = fixtures.setup_active_deal(
        org_a,
        sponsor_name="Voltcharge Energy",
        exclusivity_category="ENERGY_DRINK",
        total_fee_cents=1000000,
        deliverable_count_required=2,
    )
    not_owner = ApiErrorId.ERR_NOT_RESOURCE_OWNER.value

    validate_error(
        api_client.create_contract_offer(
            factories.create_contract_offer_payload(
                org_a, player_q, base_salary_cents=4000000
            ),
            make_general_manager_headers(org_b),
        ),
        not_owner,
        403,
    )
    validate_error(
        api_client.accept_contract_offer(
            offer_q["id"],
            factories.accept_offer_payload("2026-08-05T00:00:00Z"),
            make_player_agent_headers(player_p),
        ),
        not_owner,
        403,
    )
    assert fixtures.read_offer(offer_q["id"], org_a)["offer_status"] == "SENT"

    validate_error(
        api_client.create_team_house(
            org_a,
            factories.create_team_house_payload(name="Poached House"),
            make_ops_manager_headers(org_b),
        ),
        not_owner,
        403,
    )
    validate_error(
        api_client.create_deliverable_assignment(
            deal_a["id"],
            factories.create_deliverable_payload(
                ctx["contract"]["id"],
                fixtures.current_deal_version(deal_a["id"], org_a),
                deliverable_type="STREAM_SEGMENT",
                due_at="2026-08-20T00:00:00Z",
            ),
            make_sponsorship_manager_headers(org_b),
        ),
        not_owner,
        403,
    )
    assert fixtures.read_deal(deal_a["id"], org_a)["assigned_count"] == 0

    validate_error(
        api_client.update_player(
            player_q,
            {"guardian_weekly_cap_minutes": 600},
            make_guardian_representative_headers(player_p),
        ),
        not_owner,
        403,
    )
    validate_error(
        api_client.get_organization_cap_summary(org_a, make_general_manager_headers(org_b)),
        not_owner,
        403,
    )

    accepted = validate_success(
        api_client.accept_contract_offer(
            offer_q["id"],
            factories.accept_offer_payload("2026-08-05T00:00:00Z"),
            make_player_agent_headers(player_q),
        ),
        201,
    )
    assert accepted["contract_status"] == "ACTIVE"
    assert accepted["provisional_cap_charge_cents"] == 3945205

    own_house = validate_success(
        api_client.create_team_house(
            org_b,
            factories.create_team_house_payload(name="Hive House"),
            make_ops_manager_headers(org_b),
        ),
        201,
    )
    assert own_house["organization_id"] == org_b

    placed = validate_success(
        api_client.create_deliverable_assignment(
            deal_a["id"],
            factories.create_deliverable_payload(
                ctx["contract"]["id"],
                fixtures.current_deal_version(deal_a["id"], org_a),
                deliverable_type="STREAM_SEGMENT",
                due_at="2026-08-20T00:00:00Z",
            ),
            make_sponsorship_manager_headers(org_a),
        ),
        201,
    )
    assert placed["fee_share_cents"] == 500000
    assert placed["assignment_status"] == "ASSIGNED"

    patched_by_scout = validate_success(
        api_client.update_player(player_q, {"region_code": "CA"}, make_scout_headers())
    )
    assert patched_by_scout["region_code"] == "CA"

    cap = validate_success(
        api_client.get_organization_cap_summary(org_a, make_general_manager_headers(org_a))
    )
    assert cap["committed_salary_cents"] == 12328767 + 3945205
    assert cap["active_roster_count"] == 2


def test_the_same_identifier_may_not_sign_off_the_paperwork_it_filed():
    """One user id is refused wearing a second hat; a different administrator completes both steps.

    PRD: "The server does, however, record it where the workflow demands an audit trail: a scout's
    identifier lands in `scouted_by_user_id` on the player they register, a coach's identifier in
    `coach_user_id` on the block they book, a finance officer's identifier in `calculated_by_user_id`
    on the distribution they compute, and a league administrator's identifier in
    `approved_by_user_id` on the distribution or roster move they decide."
    PRD: "Because those recorded identifiers are the anchors of duty segregation, two operations
    additionally compare identifiers and refuse with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403): a prize
    distribution may not be approved by the same `X-User-ID` that calculated it, and a roster move
    may not be decided by the same `X-User-ID` recorded in its `requested_by_user_id`."
    PRD: "A distribution must be in `CALCULATED`, or `ERR_DISTRIBUTION_NOT_CALCULATED` (HTTP 409) is
    returned, and the approving `X-User-ID` must differ from the recorded `calculated_by_user_id`, or
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) is returned."
    PRD: "Both require `move_status` to be `PENDING`, or `ERR_MOVE_NOT_PENDING` (HTTP 409) is
    returned; both require the deciding `X-User-ID` to differ from the recorded
    `requested_by_user_id`, or `ERR_SEGREGATION_OF_DUTIES` is returned; both require the league's
    roster lock to be inactive, or `ERR_ROSTER_LOCK_ACTIVE` is returned; both take a mandatory
    `decision` of `APPROVE` or `REJECT` and an optional `decision_note`; and both stamp
    `approved_by_user_id` with the deciding administrator and record the note."
    PRD: "**Referential exclusivity and duty segregation** — `ERR_EXCLUSIVITY_CONFLICT` and
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/segregation_of_duties_blocks_one_user_from_signing_off_its_own_figures
    """
    ctx = fixtures.setup_signed_player()
    org_id = ctx["org"]["id"]
    segregation = ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value
    fixtures.set_clock("2026-08-25T00:00:00Z")

    distribution = fixtures.create_distribution(
        org_id, ctx["league"]["id"], finance_user_id="shared-1"
    )
    calculated = fixtures.calculate_distribution(distribution["id"], finance_user_id="shared-1")
    assert calculated["distribution_status"] == "CALCULATED"
    assert calculated["calculated_by_user_id"] == "shared-1"

    validate_error(
        api_client.approve_prize_distribution(
            distribution["id"], make_league_admin_headers("shared-1")
        ),
        segregation,
        403,
    )
    still_calculated = validate_success(
        api_client.get_prize_distribution(
            distribution["id"], make_finance_officer_headers("shared-1")
        )
    )
    assert still_calculated["distribution_status"] == "CALCULATED"
    assert still_calculated["version"] == calculated["version"]
    assert still_calculated["approved_by_user_id"] is None

    approved = fixtures.approve_distribution(distribution["id"], admin_user_id="admin-9")
    assert approved["distribution_status"] == "APPROVED"
    assert approved["approved_by_user_id"] == "admin-9"
    assert approved["calculated_by_user_id"] == "shared-1"

    move = fixtures.file_roster_move(
        org_id,
        ctx["player"]["id"],
        "RELEASE",
        ctx["contract"]["id"],
        effective_at="2026-08-26T00:00:00Z",
    )
    assert move["requested_by_user_id"] == org_id

    validate_error(
        api_client.decide_roster_move(
            move["id"],
            factories.move_decision_payload("APPROVE", decision_note="Self approval attempt"),
            make_league_admin_headers(org_id),
        ),
        segregation,
        403,
    )
    still_pending = fixtures.read_roster_move(move["id"], org_id)
    assert still_pending["move_status"] == "PENDING"
    assert still_pending["decision_note"] is None
    assert still_pending["approved_by_user_id"] is None
    assert still_pending["version"] == move["version"]

    decided = fixtures.decide_roster_move(
        move["id"], "APPROVE", "admin-9", decision_note="Independent approval"
    )
    assert decided["move_status"] == "APPROVED"
    assert decided["approved_by_user_id"] == "admin-9"

    final = validate_success(
        api_client.get_roster_move(move["id"], make_league_admin_headers())
    )
    assert final["move_status"] == "APPROVED"
    assert final["decision_note"] == "Independent approval"
