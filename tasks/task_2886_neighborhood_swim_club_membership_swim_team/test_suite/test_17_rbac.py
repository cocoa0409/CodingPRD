"""Role-based access control: who may call what, and which refusal fires first.

Every refusal in this module is paired with the identical request issued by the
office that owns the endpoint, so a 403 can never be explained away by a
malformed payload or a missing fixture. The ladder of PRD §2.9 is then walked
from the top: a missing header outranks a wrong role, and a wrong role outranks
an invalid body.
"""

from test_helpers import (
    AccessStatus,
    ApiErrorId,
    CaseSeverity,
    CaseStatus,
    DuesStatus,
    FindingSeverity,
    FindingStatus,
    HouseholdStanding,
    MembershipPaymentAllocation,
    ProjectKind,
    ProjectStatus,
    Role,
    SanctionType,
    SeasonStatus,
    WaitlistDecision,
    WaitlistStatus,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    case_transition_payload,
    finding_transition_payload,
    household_payload,
    inspection_finding_payload,
    membership_payload,
    membership_payment_payload,
    reserve_contribution_payload,
    season_payload,
    standing_transition_payload,
    transition_payload,
    waitlist_respond_payload,
)
from test_helpers.test_users import (
    BLANK_ROLE,
    BOARD_PRESIDENT,
    BOARD_PRESIDENT_2,
    BOARD_PRESIDENT_USER_ID,
    BOARD_PRESIDENT_USER_ID_2,
    HEALTH_INSPECTOR,
    HEALTH_INSPECTOR_2,
    HEALTH_INSPECTOR_USER_ID,
    HEALTH_INSPECTOR_USER_ID_2,
    MEMBERSHIP_CHAIR,
    POOL_MANAGER,
    SWIM_TEAM_COACH,
    SYSTEM_OPERATOR,
    TREASURER,
    TREASURER_USER_ID,
    UNKNOWN_ROLE,
    make_headers,
    make_member_headers,
)

RBAC_CLOCK = "2027-07-01T09:00:00Z"
LATER_CLOCK = "2027-07-02T09:00:00Z"
COUPLE_INVOICE_TOTAL = 31050
RESERVE_ASSESSMENT = 50000


def _clock_and_one_category(api):
    """The only shared fixture: the logical clock and one COUPLE category."""
    fx.set_clock(api, RBAC_CLOCK)
    return fx.create_couple_category(api)


def _rbac_household(api):
    return fx.create_household(api, primary_contact_name="Rbac Household",
                               address_line="341 Cedar Court", member_count=2)


def _seasons_of(api):
    rows, _ = validate_paginated(api.list_seasons(BOARD_PRESIDENT))
    return rows


def _households_of(api):
    rows, _ = validate_paginated(api.list_households(MEMBERSHIP_CHAIR))
    return rows


class TestEachOfficeOwnsItsOwnEndpoints:
    """Seven endpoints, each refused to a plausible neighbour and granted to its owner."""

    def test_the_pool_manager_may_not_create_the_season_the_board_creates(self, api):
        """The facility's manager runs the pool; the board authorises the season.

        PRD §4: "| POST | `/swim-club/seasons` | Create a swim season in
        `PLANNED` status with its date window, dues due date, bather-load figures
        and the two policy switches | BoardPresident |"

        PRD §2.1: "If both headers are well formed but the named role is not one
        of the roles authorised for the endpoint being called, the request is
        rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/exclusive_operations_each_office_owns_its_own_endpoints
        """
        _clock_and_one_category(api)

        validate_error(api.create_season(season_payload(), POOL_MANAGER),
                       ApiErrorId.UNAUTHORIZED, 403)
        assert _seasons_of(api) == []

        season = validate_success(
            api.create_season(season_payload(), BOARD_PRESIDENT), 201
        )
        assert season["status"] == SeasonStatus.PLANNED
        assert len(_seasons_of(api)) == 1

    def test_the_board_that_created_the_season_may_not_open_it(self, api):
        """Creating a season and opening it are different offices.

        PRD §4: "| POST | `/swim-club/seasons/{id}/open` | Open the season for
        swimming and re-derive the facility posture from its open inspection
        findings | PoolManager |"

        PRD §2.1: "The `PoolManager` runs the facility day to day: opening and
        closing the season, hiring and certifying lifeguards, scheduling shifts,
        admitting guests at the gate, approving parties and reporting conduct
        incidents."

        Design: Corner/rbac/exclusive_operations_each_office_owns_its_own_endpoints
        """
        _clock_and_one_category(api)
        season = fx.create_season(api)

        validate_error(api.open_season(season["id"], BOARD_PRESIDENT),
                       ApiErrorId.UNAUTHORIZED, 403)
        assert fx.read_season(api, season["id"])["status"] == SeasonStatus.PLANNED

        opened = validate_success(api.open_season(season["id"], POOL_MANAGER), 200)
        assert opened["status"] == SeasonStatus.OPEN

    def test_the_pool_manager_may_not_register_a_household(self, api):
        """The membership book belongs to the chair alone.

        PRD §4: "| POST | `/swim-club/households` | Register a household,
        optionally carrying a departing household's paid bond forward |
        MembershipChair |"

        PRD §2.1: "The `MembershipChair` runs the membership book: categories,
        households, the waitlist and membership creation."

        Design: Corner/rbac/exclusive_operations_each_office_owns_its_own_endpoints
        """
        _clock_and_one_category(api)
        payload = household_payload(primary_contact_name="Rbac Household",
                                    address_line="341 Cedar Court",
                                    member_count=2)

        validate_error(api.create_household(payload, POOL_MANAGER),
                       ApiErrorId.UNAUTHORIZED, 403)
        assert _households_of(api) == []

        household = validate_success(
            api.create_household(payload, MEMBERSHIP_CHAIR), 201
        )
        assert household["standing"] == HouseholdStanding.GOOD_STANDING
        assert len(_households_of(api)) == 1

    def test_the_chair_that_sold_the_membership_may_not_invoice_it(self, api):
        """Selling the season and billing for it are two different offices.

        PRD §4: "| POST | `/swim-club/memberships/{id}/invoice` | Cut the season
        invoice once and once only, and flip access from `PENDING` to `ACTIVE` |
        Treasurer |"

        PRD §2.1: "The `Treasurer` runs the money: invoicing, payments,
        write-offs, the billing checkpoint, reserve contributions and
        capital-project funding."

        Design: Corner/rbac/exclusive_operations_each_office_owns_its_own_endpoints
        """
        category = _clock_and_one_category(api)
        season = fx.open_season(api, fx.create_season(api)["id"])
        household = _rbac_household(api)
        membership = fx.setup_membership(api, household["id"], category["id"],
                                         season["id"], join_date="2027-06-01")

        validate_error(api.invoice_membership(membership["id"], MEMBERSHIP_CHAIR),
                       ApiErrorId.UNAUTHORIZED, 403)
        untouched = fx.read_membership(api, membership["id"])
        assert untouched["dues_status"] == DuesStatus.UNBILLED
        assert untouched["access_status"] == AccessStatus.PENDING
        assert untouched["version"] == membership["version"]

        invoiced = validate_success(
            api.invoice_membership(membership["id"], TREASURER), 200
        )
        assert invoiced["dues_status"] == DuesStatus.INVOICED
        assert invoiced["access_status"] == AccessStatus.ACTIVE

    def test_only_the_board_may_move_a_household_standing(self, api):
        """The chair may not soften what the conduct pipeline hardened.

        PRD §4: "| POST | `/swim-club/households/{id}/standing-transitions` |
        Move a household's conduct standing explicitly; the only path that softens
        a standing | BoardPresident |"

        PRD §3.9: "The single path that softens a standing belongs to the
        `BoardPresident`, who names the `to_standing` the household is to hold and
        a `reason` for the record."

        PRD §3.9: "a household at `SUSPENDED` returns to `GOOD_STANDING`, and the
        board may equally place it at `PROBATION` rather than fully clearing it"

        Design: Corner/rbac/exclusive_operations_each_office_owns_its_own_endpoints
        """
        _clock_and_one_category(api)
        household = _rbac_household(api)
        fx.sanction_household(api, household["id"], CaseSeverity.MINOR,
                              SanctionType.SUSPENSION)
        assert fx.read_household(api, household["id"])["standing"] == (
            HouseholdStanding.SUSPENDED
        )

        payload = standing_transition_payload(
            to_standing=HouseholdStanding.PROBATION,
            reason="Chair attempts a standing change",
        )
        validate_error(
            api.create_standing_transition(household["id"], payload,
                                           MEMBERSHIP_CHAIR),
            ApiErrorId.UNAUTHORIZED, 403,
        )
        assert fx.read_household(api, household["id"])["standing"] == (
            HouseholdStanding.SUSPENDED
        )

        moved = validate_success(
            api.create_standing_transition(
                household["id"],
                standing_transition_payload(
                    to_standing=HouseholdStanding.PROBATION,
                    reason="Board places the household on probation",
                ),
                BOARD_PRESIDENT,
            ),
            200,
        )
        assert moved["standing"] == HouseholdStanding.PROBATION

    def test_no_business_office_may_drive_the_logical_clock(self, api):
        """The clock is an operational identity's only privilege.

        PRD §4: "| POST | `/swim-club/_clock/set_current_utc` | Set the server's
        logical UTC clock that every deadline, expiry, season-window and lookback
        rule reads | SystemOperator |"

        PRD §2.1: "The `SystemOperator` is an operational identity that exists only
        to drive the server's logical clock for deterministic testing; it carries no
        business authority of any kind."

        PRD §2.10: "the clock-setting call returns an empty object"

        Design: Corner/rbac/exclusive_operations_each_office_owns_its_own_endpoints
        """
        _clock_and_one_category(api)

        validate_error(api.set_clock(LATER_CLOCK, BOARD_PRESIDENT),
                       ApiErrorId.UNAUTHORIZED, 403)
        validate_error(api.set_clock(LATER_CLOCK, TREASURER),
                       ApiErrorId.UNAUTHORIZED, 403)

        assert validate_success(api.set_clock(LATER_CLOCK, SYSTEM_OPERATOR),
                                200) == {}

    def test_only_the_treasurer_may_book_a_reserve_contribution(self, api):
        """The board authorises spending; the treasurer books the money.

        PRD §4: "| POST | `/swim-club/seasons/{id}/reserve-contributions` | Book a
        lump capital-reserve contribution (a special assessment) onto the season |
        Treasurer |"

        PRD §3.10: "The `Treasurer` may book a lump special assessment against the
        season by naming an `amount_cents` and, optionally, a `note` explaining what
        the assessment is for; both `reserve_contributions_cents` and
        `reserve_unallocated_cents` rise by that amount and the season's `version`
        advances."

        Design: Corner/rbac/exclusive_operations_each_office_owns_its_own_endpoints
        """
        _clock_and_one_category(api)
        season = fx.open_season(api, fx.create_season(api)["id"])
        assert season["reserve_contributions_cents"] == 0

        validate_error(
            api.create_reserve_contribution(
                season["id"],
                reserve_contribution_payload(
                    amount_cents=RESERVE_ASSESSMENT,
                    note="Board tries to book the assessment itself",
                ),
                BOARD_PRESIDENT,
            ),
            ApiErrorId.UNAUTHORIZED, 403,
        )
        refused = fx.read_season(api, season["id"])
        assert refused["reserve_contributions_cents"] == 0
        assert refused["reserve_unallocated_cents"] == 0
        assert refused["version"] == season["version"]

        booked = validate_success(
            api.create_reserve_contribution(
                season["id"],
                reserve_contribution_payload(
                    amount_cents=RESERVE_ASSESSMENT,
                    note="Treasurer books the assessment",
                ),
                TREASURER,
            ),
            200,
        )
        assert booked["reserve_contributions_cents"] == RESERVE_ASSESSMENT
        assert booked["reserve_unallocated_cents"] == RESERVE_ASSESSMENT

    def test_every_refused_call_left_no_row_and_no_field_change_behind(self, api):
        """Five refusals in a row, then the club is exactly what its owners built.

        PRD §2.9: "**Endpoint authorisation.** The acting role appears in the
        endpoint's authorised list — otherwise `ERR_UNAUTHORIZED` (403)."

        PRD §2.10: "A successful create or modify returns the created or updated
        resource in the `data` field"

        Design: Corner/rbac/exclusive_operations_each_office_owns_its_own_endpoints
        """
        category = _clock_and_one_category(api)

        validate_error(api.create_season(season_payload(), POOL_MANAGER),
                       ApiErrorId.UNAUTHORIZED, 403)
        season = fx.create_season(api)
        validate_error(api.open_season(season["id"], BOARD_PRESIDENT),
                       ApiErrorId.UNAUTHORIZED, 403)
        fx.open_season(api, season["id"])
        validate_error(
            api.create_household(household_payload(member_count=2), POOL_MANAGER),
            ApiErrorId.UNAUTHORIZED, 403,
        )
        household = _rbac_household(api)
        # Join on the season's own open_date: PRD §3.3 charges "the category's
        # full `seasonal_dues_cents` with no proration whatsoever" when "the
        # effective start is at or before the season's `open_date`", which is the
        # figure COUPLE_INVOICE_TOTAL names.
        membership = fx.setup_membership(api, household["id"], category["id"],
                                         season["id"], join_date="2027-05-22")
        validate_error(api.invoice_membership(membership["id"], MEMBERSHIP_CHAIR),
                       ApiErrorId.UNAUTHORIZED, 403)
        fx.invoice_membership(api, membership["id"])
        validate_error(
            api.create_reserve_contribution(
                season["id"],
                reserve_contribution_payload(amount_cents=RESERVE_ASSESSMENT),
                BOARD_PRESIDENT,
            ),
            ApiErrorId.UNAUTHORIZED, 403,
        )
        fx.contribute_reserve(api, season["id"], RESERVE_ASSESSMENT)

        assert len(_seasons_of(api)) == 1
        assert len(_households_of(api)) == 1
        rows, meta = validate_paginated(api.list_memberships(MEMBERSHIP_CHAIR))
        assert meta["total_count"] == 1
        final_season = fx.read_season(api, season["id"])
        assert final_season["status"] == SeasonStatus.OPEN
        assert final_season["reserve_contributions_cents"] == RESERVE_ASSESSMENT
        final_membership = fx.read_membership(api, membership["id"])
        assert final_membership["dues_status"] == DuesStatus.INVOICED
        assert final_membership["access_status"] == AccessStatus.ACTIVE
        assert final_membership["balance_due_cents"] == COUPLE_INVOICE_TOTAL
        assert rows[0]["id"] == membership["id"]


def _a_live_club_for_the_auth_ladder(api):
    """One OPEN season, one category and one household, so every probe has a target."""
    fx.set_clock(api, RBAC_CLOCK)
    category = fx.create_couple_category(api)
    season = fx.open_season(api, fx.create_season(api)["id"])
    household = fx.create_household(api,
                                    primary_contact_name="Auth Order Household",
                                    address_line="351 Cedar Court",
                                    member_count=2)
    return {"category": category, "season": season, "household": household}


def _season_2029_payload():
    return season_payload(year=2029, open_date="2029-05-19",
                          close_date="2029-09-03", dues_due_date="2029-04-15")


def _membership_body_without_a_join_date(ctx):
    return membership_payload(
        household_id=ctx["household"]["id"],
        membership_category_id=ctx["category"]["id"],
        season_id=ctx["season"]["id"],
        join_date=Ellipsis,
        bond_payment_plan=Ellipsis,
    )


class TestAuthenticationOutranksAuthorisationAndValidation:
    """Bands 1, 2 and 5 of the ladder, each separated by construction."""

    def test_a_blank_role_is_refused_even_on_a_read_every_office_may_perform(self, api):
        """The header check happens before the endpoint's role list is consulted.

        PRD §2.1: "If either header is absent or empty, or if `X-User-Role` names a
        role outside the enumeration below, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        PRD §4: "| GET | `/swim-club/seasons/{id}` | Read one season, including its
        derived posture, open-finding counts and reserve counters | BoardPresident,
        Treasurer, PoolManager, MembershipChair, SwimTeamCoach, HealthInspector,
        Member |"

        Design: Corner/rbac/cross_role_denied_authentication_outranks_authorisation_and_validation
        """
        ctx = _a_live_club_for_the_auth_ladder(api)

        validate_error(api.get_season(ctx["season"]["id"], BLANK_ROLE),
                       ApiErrorId.UNAUTHENTICATED, 401)

        assert validate_success(
            api.get_season(ctx["season"]["id"], POOL_MANAGER), 200
        )["id"] == ctx["season"]["id"]

    def test_a_blank_role_beats_the_authorisation_refusal_it_would_also_have_earned(self, api):
        """401, not 403, on an endpoint no anonymous caller could ever have used.

        PRD §2.9: "Checks are evaluated strictly in the following order, and the
        first one that fails determines the response."

        PRD §2.9: "**Authentication.** Both headers present and non-empty, and
        `X-User-Role` naming a declared role — otherwise `ERR_UNAUTHENTICATED`
        (401)."

        Design: Corner/rbac/cross_role_denied_authentication_outranks_authorisation_and_validation
        """
        _a_live_club_for_the_auth_ladder(api)

        validate_error(api.create_season(_season_2029_payload(), BLANK_ROLE),
                       ApiErrorId.UNAUTHENTICATED, 401)
        assert len(_seasons_of(api)) == 1

    def test_an_undeclared_role_name_is_an_authentication_failure(self, api):
        """A syntactically fine role outside the enumeration is still a 401.

        PRD §2.1: "The system recognises exactly eight roles: `Member`,
        `MembershipChair`, `PoolManager`, `SwimTeamCoach`, `HealthInspector`,
        `Treasurer`, `BoardPresident`, and `SystemOperator`."

        PRD §2.9: "**Authentication.** Both headers present and non-empty, and
        `X-User-Role` naming a declared role — otherwise `ERR_UNAUTHENTICATED`
        (401)."

        Design: Corner/rbac/cross_role_denied_authentication_outranks_authorisation_and_validation
        """
        _a_live_club_for_the_auth_ladder(api)

        validate_error(api.create_season(_season_2029_payload(), UNKNOWN_ROLE),
                       ApiErrorId.UNAUTHENTICATED, 401)
        assert len(_seasons_of(api)) == 1

    def test_a_blank_user_id_with_a_perfectly_good_role_is_still_refused(self, api):
        """Both headers are required, not just the role.

        PRD §2.1: "Every request to the API must carry two headers: `X-User-ID`,
        identifying the caller, and `X-User-Role`, naming the capacity in which the
        caller is acting."

        PRD §2.1: "When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the
        acting `Household`"

        Design: Corner/rbac/cross_role_denied_authentication_outranks_authorisation_and_validation
        """
        ctx = _a_live_club_for_the_auth_ladder(api)

        validate_error(
            api.get_season(ctx["season"]["id"], make_headers("", Role.MEMBER)),
            ApiErrorId.UNAUTHENTICATED, 401,
        )

        owner = make_member_headers(ctx["household"]["id"])
        assert validate_success(api.get_season(ctx["season"]["id"], owner),
                                200)["id"] == ctx["season"]["id"]

    def test_the_wrong_role_is_reported_before_the_missing_required_field(self, api):
        """One body, two callers: 403 for the wrong office, 422 for the right one.

        PRD §2.9: "**Endpoint authorisation.** The acting role appears in the
        endpoint's authorised list — otherwise `ERR_UNAUTHORIZED` (403)."

        PRD §2.9: "**Payload shape.** Every required field present, of the declared
        JSON type and non-empty"

        PRD §3.3: "Creating a membership names the `household_id`, the
        `membership_category_id`, the `season_id` and the `join_date` on which the
        household's access begins"

        Design: Corner/rbac/cross_role_denied_authentication_outranks_authorisation_and_validation
        """
        ctx = _a_live_club_for_the_auth_ladder(api)
        body = _membership_body_without_a_join_date(ctx)
        assert "join_date" not in body

        validate_error(api.create_membership(body, POOL_MANAGER),
                       ApiErrorId.UNAUTHORIZED, 403)
        validate_error(api.create_membership(body, MEMBERSHIP_CHAIR),
                       ApiErrorId.VALIDATION, 422)

        _, meta = validate_paginated(api.list_memberships(MEMBERSHIP_CHAIR))
        assert meta["total_count"] == 0

    def test_a_list_read_is_role_checked_exactly_like_a_write(self, api):
        """The coach has no business with the guard registry.

        PRD §4: "| GET | `/swim-club/lifeguards` | List lifeguards, filterable by
        employment status and lifeguard-certification coverage | PoolManager,
        BoardPresident, HealthInspector |"

        PRD §2.1: "The `SwimTeamCoach` runs the swim team: registrations, squads,
        meet scheduling and volunteer rostering."

        Design: Corner/rbac/cross_role_denied_authentication_outranks_authorisation_and_validation
        """
        _a_live_club_for_the_auth_ladder(api)
        guard = fx.create_lifeguard(api, full_name="Auth Order Guard")

        validate_error(api.list_lifeguards(SWIM_TEAM_COACH),
                       ApiErrorId.UNAUTHORIZED, 403)

        rows, meta = validate_paginated(api.list_lifeguards(HEALTH_INSPECTOR))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == guard["id"]

    def test_the_pool_manager_may_not_file_the_inspectors_finding(self, api):
        """Only the health department's officer records a finding.

        PRD §4: "| POST | `/swim-club/inspection-findings` | Record a
        health-department inspection finding against a season, re-deriving the
        facility posture and firing the closure cascade where the posture turns
        `CLOSED` | HealthInspector |"

        PRD §2.1: "The `HealthInspector` is the health department's officer: the only
        role that may record an inspection finding, and the only role that may reopen
        or verify-close one."

        Design: Corner/rbac/cross_role_denied_authentication_outranks_authorisation_and_validation
        """
        ctx = _a_live_club_for_the_auth_ladder(api)
        body = inspection_finding_payload(
            season_id=ctx["season"]["id"], inspected_on="2027-06-28",
            inspector_name="Pool manager tries to file", finding_code="CHEM-04",
            severity=FindingSeverity.MINOR,
            narrative="Manager files his own finding.",
        )

        validate_error(api.create_inspection_finding(body, POOL_MANAGER),
                       ApiErrorId.UNAUTHORIZED, 403)

        _, meta = validate_paginated(
            api.list_inspection_findings(HEALTH_INSPECTOR,
                                         {"season_id": ctx["season"]["id"]})
        )
        assert meta["total_count"] == 0


def _two_households_with_a_membership_and_a_place_in_the_queue(api):
    """A and B are identical strangers: same category, same balance, same queue."""
    fx.set_clock(api, RBAC_CLOCK)
    couple = fx.create_couple_category(api)
    family = fx.create_family_category(api, waitlist_required=True)
    season = fx.open_season(api, fx.create_season(api)["id"])
    first = fx.create_household(api, primary_contact_name="Owner Household A",
                                address_line="361 Cedar Court", member_count=2)
    second = fx.create_household(api, primary_contact_name="Owner Household B",
                                 address_line="362 Cedar Court", member_count=2)
    first_membership = fx.invoice_membership(
        api,
        fx.setup_membership(api, first["id"], couple["id"], season["id"])["id"],
    )
    second_membership = fx.invoice_membership(
        api,
        fx.setup_membership(api, second["id"], couple["id"], season["id"])["id"],
    )
    first_entry = fx.join_waitlist(api, first["id"], family["id"])
    second_entry = fx.join_waitlist(api, second["id"], family["id"])
    offered = fx.extend_next_offer(api, family["id"])
    return {
        "season": season, "couple": couple, "family": family,
        "a": first, "b": second,
        "m_a": first_membership, "m_b": second_membership,
        "e_a": first_entry, "e_b": second_entry, "offered": offered,
    }


def _pay(api, membership_id, headers, amount_cents=COUPLE_INVOICE_TOTAL):
    return api.create_membership_payment(
        membership_id,
        membership_payment_payload(amount_cents=amount_cents,
                                   allocation=MembershipPaymentAllocation.DUES),
        headers,
    )


class TestAMemberIsScopedToItsOwnHousehold:
    """Ownership reached directly, one hop through a membership, and on a queue entry."""

    def test_the_two_strangers_start_from_the_same_position(self, api):
        """Both households are invoiced for the same amount and A holds the offer.

        PRD §3.4: "`balance_due_cents` is at all times the membership's
        `invoice_total_cents` plus its `volunteer_buyout_cents` minus its
        `amount_paid_cents`, floored at 0 so it never goes negative."

        PRD §3.2: "The winning entry moves `WAITING → OFFERED`, `offered_at` is
        stamped with the logical clock, and `offer_expires_at` is set to fourteen days
        after that instant."

        Design: Corner/rbac/not_resource_owner_a_member_is_scoped_to_its_own_household
        """
        ctx = _two_households_with_a_membership_and_a_place_in_the_queue(api)

        assert ctx["m_a"]["balance_due_cents"] == COUPLE_INVOICE_TOTAL
        assert ctx["m_b"]["balance_due_cents"] == COUPLE_INVOICE_TOTAL
        assert ctx["m_a"]["dues_status"] == DuesStatus.INVOICED
        assert ctx["m_b"]["dues_status"] == DuesStatus.INVOICED
        assert ctx["offered"]["id"] == ctx["e_a"]["id"]
        assert ctx["offered"]["status"] == WaitlistStatus.OFFERED
        assert fx.read_waitlist_entry(api, ctx["e_b"]["id"])["status"] == (
            WaitlistStatus.WAITING
        )

    def test_a_member_reading_a_foreign_household_is_refused(self, api):
        """The comparison on a household is direct: the path id against the header.

        PRD §2.1: "A `Member` that addresses a resource owned by a different
        household is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        PRD §2.1: "That comparison is direct for a `Household` or a `WaitlistEntry`
        (whose `household_id` is compared), it runs through the addressed membership's
        `household_id` for a `Membership`, `GuestVisit`, `SwimTeamRegistration` or
        `PartyReservation`"

        Design: Corner/rbac/not_resource_owner_a_member_is_scoped_to_its_own_household
        """
        ctx = _two_households_with_a_membership_and_a_place_in_the_queue(api)
        owner = make_member_headers(ctx["a"]["id"])

        validate_error(api.get_household(ctx["b"]["id"], owner),
                       ApiErrorId.NOT_RESOURCE_OWNER, 403)

        mine = validate_success(api.get_household(ctx["a"]["id"], owner), 200)
        assert mine["primary_contact_name"] == "Owner Household A"

    def test_a_member_paying_a_foreign_membership_is_refused_one_hop_away(self, api):
        """Ownership is resolved through the addressed membership's household.

        PRD §2.9: "**Resource ownership.** For a `Member` addressing an owned
        resource, `X-User-ID` matches the owning household — otherwise
        `ERR_NOT_RESOURCE_OWNER` (403)."

        PRD §4: "| POST | `/swim-club/memberships/{id}/payments` | Record a dues or
        bond payment against the membership | Treasurer, Member |"

        Design: Corner/rbac/not_resource_owner_a_member_is_scoped_to_its_own_household
        """
        ctx = _two_households_with_a_membership_and_a_place_in_the_queue(api)

        validate_error(_pay(api, ctx["m_b"]["id"],
                            make_member_headers(ctx["a"]["id"])),
                       ApiErrorId.NOT_RESOURCE_OWNER, 403)

        untouched = fx.read_membership(api, ctx["m_b"]["id"])
        assert untouched["dues_status"] == DuesStatus.INVOICED
        assert untouched["balance_due_cents"] == COUPLE_INVOICE_TOTAL
        assert untouched["amount_paid_cents"] == 0
        assert untouched["version"] == ctx["m_b"]["version"]

    def test_the_same_endpoint_settles_the_members_own_membership(self, api):
        """Only the identity was wrong: the endpoint works for its owner.

        PRD §3.4: "a payment equal to the balance — driving `balance_due_cents` to 0
        — moves `INVOICED → PAID` or `DELINQUENT → PAID`"

        PRD §2.1: "When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the
        acting `Household`"

        Design: Corner/rbac/not_resource_owner_a_member_is_scoped_to_its_own_household
        """
        ctx = _two_households_with_a_membership_and_a_place_in_the_queue(api)

        settled = validate_success(
            _pay(api, ctx["m_a"]["id"], make_member_headers(ctx["a"]["id"])), 200
        )
        assert settled["dues_status"] == DuesStatus.PAID
        assert settled["balance_due_cents"] == 0
        assert settled["amount_paid_cents"] == COUPLE_INVOICE_TOTAL

    def test_only_the_charged_household_may_answer_its_own_offer(self, api):
        """The ACCEPTED edge carries the ownership precondition in its own right.

        PRD §3.2: "Only the charged household may respond, so `X-User-ID` must equal
        the entry's `household_id`."

        PRD §3.2: "Accepting moves `OFFERED → ACCEPTED` and is the entry a membership
        creation later consumes"

        Design: Corner/rbac/not_resource_owner_a_member_is_scoped_to_its_own_household
        """
        ctx = _two_households_with_a_membership_and_a_place_in_the_queue(api)
        body = waitlist_respond_payload(decision=WaitlistDecision.ACCEPT)

        validate_error(
            api.respond_waitlist_entry(ctx["e_a"]["id"], body,
                                       make_member_headers(ctx["b"]["id"])),
            ApiErrorId.NOT_RESOURCE_OWNER, 403,
        )
        assert fx.read_waitlist_entry(api, ctx["e_a"]["id"])["status"] == (
            WaitlistStatus.OFFERED
        )

        accepted = validate_success(
            api.respond_waitlist_entry(ctx["e_a"]["id"], body,
                                       make_member_headers(ctx["a"]["id"])),
            200,
        )
        assert accepted["status"] == WaitlistStatus.ACCEPTED
        assert fx.read_waitlist_entry(api, ctx["e_b"]["id"])["status"] == (
            WaitlistStatus.WAITING
        )

    def test_the_treasurer_may_send_the_very_payment_the_foreign_member_was_refused(self, api):
        """Band 3 constrains Members; it is not a blanket ownership filter.

        PRD §2.9: "**Resource ownership.** For a `Member` addressing an owned
        resource, `X-User-ID` matches the owning household — otherwise
        `ERR_NOT_RESOURCE_OWNER` (403)."

        PRD §2.1: "`X-User-ID` is an opaque operator identifier not tied to any
        persisted entity"

        Design: Corner/rbac/not_resource_owner_a_member_is_scoped_to_its_own_household
        """
        ctx = _two_households_with_a_membership_and_a_place_in_the_queue(api)
        validate_error(_pay(api, ctx["m_b"]["id"],
                            make_member_headers(ctx["a"]["id"])),
                       ApiErrorId.NOT_RESOURCE_OWNER, 403)

        settled = validate_success(_pay(api, ctx["m_b"]["id"], TREASURER), 200)
        assert settled["dues_status"] == DuesStatus.PAID
        assert settled["balance_due_cents"] == 0

    def test_an_unowned_collection_refuses_the_member_on_the_role_check(self, api):
        """The finding list is nobody's property, so band 2 answers first.

        PRD §4: "| GET | `/swim-club/inspection-findings` | List inspection findings,
        filterable by season, severity and status | HealthInspector, PoolManager,
        BoardPresident |"

        PRD §2.9: "**Endpoint authorisation.** The acting role appears in the
        endpoint's authorised list — otherwise `ERR_UNAUTHORIZED` (403)."

        Design: Corner/rbac/not_resource_owner_a_member_is_scoped_to_its_own_household
        """
        ctx = _two_households_with_a_membership_and_a_place_in_the_queue(api)

        validate_error(
            api.list_inspection_findings(make_member_headers(ctx["a"]["id"]),
                                         {"season_id": ctx["season"]["id"]}),
            ApiErrorId.UNAUTHORIZED, 403,
        )


DUTIES_RESERVE = 300000
DUTIES_BUDGET = 250000


def _three_decisions_awaiting_a_second_pair_of_eyes(api):
    """A project, a case and a finding, each raised by a first pair of eyes."""
    season = fx.setup_open_season(api, clock_iso=RBAC_CLOCK)
    funded_season = fx.contribute_reserve(api, season["id"], DUTIES_RESERVE)
    household = fx.create_household(api,
                                    primary_contact_name="Duties Household",
                                    address_line="371 Cedar Court",
                                    member_count=2)
    project = fx.propose_project(api, season["id"], DUTIES_BUDGET,
                                 title="Resurface the main tank",
                                 project_kind=ProjectKind.POOL_RESURFACING)
    reported = fx.report_case(api, household["id"], CaseSeverity.MINOR,
                              headers=BOARD_PRESIDENT,
                              subject_name="Guest of the household")
    case = fx.transition_case(api, reported["id"], CaseStatus.UNDER_REVIEW,
                              BOARD_PRESIDENT)
    filed = fx.file_finding(api, season["id"], FindingSeverity.MINOR,
                            headers=HEALTH_INSPECTOR, inspected_on="2027-06-28",
                            finding_code="SIGN-02")
    finding = fx.transition_finding(
        api, filed["id"], FindingStatus.REMEDIATION_SUBMITTED, POOL_MANAGER,
        remediation_note="Depth markings repainted on 2027-06-30.",
    )
    return {
        "season": funded_season, "household": household, "project": project,
        "reported": reported, "case": case, "filed": filed, "finding": finding,
    }


def _approve(api, project_id, headers):
    return api.transition_capital_project(
        project_id, transition_payload(ProjectStatus.APPROVED), headers
    )


def _sanction(api, case_id, headers):
    return api.transition_conduct_case(
        case_id,
        case_transition_payload(CaseStatus.SANCTIONED,
                                sanction_type=SanctionType.WARNING),
        headers,
    )


def _verify_close(api, finding_id, headers):
    return api.transition_inspection_finding(
        finding_id, finding_transition_payload(FindingStatus.VERIFIED_CLOSED),
        headers,
    )


class TestNoOfficeMayDecideItsOwnPaperwork:
    """Two-person control on all three entities that carry it."""

    def test_the_fixture_records_who_raised_each_item(self, api):
        """Every raised item carries its author, and no decider yet.

        PRD §3.10: "It opens at `PROPOSED` with `funded_cents` at 0 and the
        proposer's identity in `requested_by_user_id`."

        PRD §3.9: "The case opens at `REPORTED` with the reporter's identity captured
        in `reported_by_user_id`, `points_assessed` at 0 and `appeal_count` at 0;
        `decided_by_user_id`, `sanction_type` and `sanctioned_at` are all null until
        the board decides."

        PRD §3.1: "A new finding is born `OPEN`, its `recorded_by_user_id` stamped
        from `X-User-ID`, its `reopen_count` at 0, its `remediation_note`,
        `remediation_submitted_at` and `verified_by_user_id` all null."

        Design: Corner/rbac/segregation_of_duties_no_office_may_decide_its_own_paperwork
        """
        ctx = _three_decisions_awaiting_a_second_pair_of_eyes(api)

        assert ctx["project"]["requested_by_user_id"] == TREASURER_USER_ID
        assert ctx["project"]["status"] == ProjectStatus.PROPOSED
        assert ctx["project"]["approved_by_user_id"] is None
        assert ctx["project"]["funded_cents"] == 0

        assert ctx["reported"]["reported_by_user_id"] == BOARD_PRESIDENT_USER_ID
        assert ctx["reported"]["status"] == CaseStatus.REPORTED
        assert ctx["reported"]["decided_by_user_id"] is None
        assert ctx["case"]["status"] == CaseStatus.UNDER_REVIEW

        assert ctx["filed"]["recorded_by_user_id"] == HEALTH_INSPECTOR_USER_ID
        assert ctx["filed"]["status"] == FindingStatus.OPEN
        assert ctx["filed"]["verified_by_user_id"] is None
        assert ctx["finding"]["status"] == FindingStatus.REMEDIATION_SUBMITTED

    def test_the_proposing_treasurer_may_not_approve_its_own_project(self, api):
        """The Treasurer is on the endpoint's role list, so this is not a role 403.

        PRD §2.8: "Approving or rejecting a capital project requires that `X-User-ID`
        differ from the project's `requested_by_user_id`."

        PRD §4: "| POST | `/swim-club/capital-projects/{id}/transitions` | Approve,
        reject, start, complete or cancel a capital project | BoardPresident,
        Treasurer |"

        Design: Corner/rbac/segregation_of_duties_no_office_may_decide_its_own_paperwork
        """
        ctx = _three_decisions_awaiting_a_second_pair_of_eyes(api)

        validate_error(_approve(api, ctx["project"]["id"], TREASURER),
                       ApiErrorId.SEGREGATION_OF_DUTIES, 403)

        untouched = fx.read_project(api, ctx["project"]["id"])
        assert untouched["status"] == ProjectStatus.PROPOSED
        assert untouched["approved_by_user_id"] is None
        assert untouched["version"] == ctx["project"]["version"]

    def test_a_board_president_who_proposed_nothing_approves_and_is_recorded(self, api):
        """The rule compares against `requested_by_user_id` and nothing else.

        PRD §3.10: "From `PROPOSED` the `BoardPresident` either approves the project —
        which records their own `X-User-ID` in `approved_by_user_id` — or rejects it"

        PRD §2.8: "A violation of any of the three is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and the check is an authorisation
        concern evaluated before any state or business rule on the same request."

        Design: Corner/rbac/segregation_of_duties_no_office_may_decide_its_own_paperwork
        """
        ctx = _three_decisions_awaiting_a_second_pair_of_eyes(api)

        approved = validate_success(
            _approve(api, ctx["project"]["id"], BOARD_PRESIDENT_2), 200
        )
        assert approved["status"] == ProjectStatus.APPROVED
        assert approved["approved_by_user_id"] == BOARD_PRESIDENT_USER_ID_2
        assert approved["requested_by_user_id"] == TREASURER_USER_ID
        assert approved["funded_cents"] == 0

    def test_the_reporting_president_may_not_sanction_its_own_case(self, api):
        """bp-001 holds exactly the role the SANCTIONED edge requires, and is refused.

        PRD §2.8: "Sanctioning or dismissing a conduct case requires that `X-User-ID`
        differ from the case's `reported_by_user_id`."

        PRD §3.9: "Both decisions are subject to two-person control: the deciding
        `X-User-ID` may not equal the case's own `reported_by_user_id`, and a board
        president who tries to decide the case they themselves reported is
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/segregation_of_duties_no_office_may_decide_its_own_paperwork
        """
        ctx = _three_decisions_awaiting_a_second_pair_of_eyes(api)

        validate_error(_sanction(api, ctx["case"]["id"], BOARD_PRESIDENT),
                       ApiErrorId.SEGREGATION_OF_DUTIES, 403)

        untouched = fx.read_case(api, ctx["case"]["id"])
        assert untouched["status"] == CaseStatus.UNDER_REVIEW
        assert untouched["decided_by_user_id"] is None
        assert untouched["points_assessed"] == 0
        assert untouched["version"] == ctx["case"]["version"]

    def test_a_second_board_user_sanctions_the_case_and_is_stamped(self, api):
        """Same role, different user, and the decider is recorded.

        PRD §3.9: "Sanctioning from `UNDER_REVIEW` requires the `sanction_type` to be
        present and stamps it alongside `decided_by_user_id` and a `sanctioned_at` set
        to the logical clock, then sets `points_assessed` to the point value of the
        case's `severity`."

        PRD §3.9: "The point values are two for a `MINOR` incident, four for a `MAJOR`
        one and eight for a `SEVERE` one, all integers"

        Design: Corner/rbac/segregation_of_duties_no_office_may_decide_its_own_paperwork
        """
        ctx = _three_decisions_awaiting_a_second_pair_of_eyes(api)

        sanctioned = validate_success(
            _sanction(api, ctx["case"]["id"], BOARD_PRESIDENT_2), 200
        )
        assert sanctioned["status"] == CaseStatus.SANCTIONED
        assert sanctioned["decided_by_user_id"] == BOARD_PRESIDENT_USER_ID_2
        assert sanctioned["sanction_type"] == SanctionType.WARNING
        assert sanctioned["reported_by_user_id"] == BOARD_PRESIDENT_USER_ID
        assert sanctioned["points_assessed"] == 2

    def test_the_recording_inspector_may_not_verify_close_its_own_finding(self, api):
        """An inspector may never sign off its own paperwork.

        PRD §2.8: "Verify-closing an inspection finding requires that `X-User-ID`
        differ from the finding's `recorded_by_user_id`."

        PRD §3.1: "Only the inspector may verify-close: moving `REMEDIATION_SUBMITTED
        → VERIFIED_CLOSED` requires that `X-User-ID` differ from the finding's
        `recorded_by_user_id`, stamps `verified_by_user_id` with the acting user"

        Design: Corner/rbac/segregation_of_duties_no_office_may_decide_its_own_paperwork
        """
        ctx = _three_decisions_awaiting_a_second_pair_of_eyes(api)

        validate_error(_verify_close(api, ctx["finding"]["id"], HEALTH_INSPECTOR),
                       ApiErrorId.SEGREGATION_OF_DUTIES, 403)

        untouched = fx.read_finding(api, ctx["finding"]["id"])
        assert untouched["status"] == FindingStatus.REMEDIATION_SUBMITTED
        assert untouched["verified_by_user_id"] is None
        assert untouched["version"] == ctx["finding"]["version"]

    def test_a_second_inspector_closes_it_and_both_halves_of_the_record_survive(self, api):
        """The filer and the closer are both readable off the closed finding.

        PRD §3.1: "Only the inspector may verify-close: moving `REMEDIATION_SUBMITTED
        → VERIFIED_CLOSED` requires that `X-User-ID` differ from the finding's
        `recorded_by_user_id`, stamps `verified_by_user_id` with the acting user"

        PRD §3.1: "`VERIFIED_CLOSED` is the finding's only terminal state."

        Design: Corner/rbac/segregation_of_duties_no_office_may_decide_its_own_paperwork
        """
        ctx = _three_decisions_awaiting_a_second_pair_of_eyes(api)

        closed = validate_success(
            _verify_close(api, ctx["finding"]["id"], HEALTH_INSPECTOR_2), 200
        )
        assert closed["status"] == FindingStatus.VERIFIED_CLOSED
        assert closed["verified_by_user_id"] == HEALTH_INSPECTOR_USER_ID_2
        assert closed["recorded_by_user_id"] == HEALTH_INSPECTOR_USER_ID

    def test_none_of_these_decisions_moved_a_cent_of_the_reserve(self, api):
        """Three refusals and one approval later, the reserve is where it started.

        PRD §3.10: "Projects in `PROPOSED`, `APPROVED` or `REJECTED` contribute nothing
        to the allocated side because they hold no money"

        PRD §3.10: "`reserve_contributions_cents` is append-only in the strictest
        sense: it never decreases."

        Design: Corner/rbac/segregation_of_duties_no_office_may_decide_its_own_paperwork
        """
        ctx = _three_decisions_awaiting_a_second_pair_of_eyes(api)
        assert ctx["season"]["reserve_unallocated_cents"] == DUTIES_RESERVE

        validate_error(_approve(api, ctx["project"]["id"], TREASURER),
                       ApiErrorId.SEGREGATION_OF_DUTIES, 403)
        validate_error(_sanction(api, ctx["case"]["id"], BOARD_PRESIDENT),
                       ApiErrorId.SEGREGATION_OF_DUTIES, 403)
        validate_error(_verify_close(api, ctx["finding"]["id"], HEALTH_INSPECTOR),
                       ApiErrorId.SEGREGATION_OF_DUTIES, 403)
        approved = validate_success(
            _approve(api, ctx["project"]["id"], BOARD_PRESIDENT_2), 200
        )

        assert approved["funded_cents"] == 0
        season = fx.read_season(api, ctx["season"]["id"])
        assert season["reserve_contributions_cents"] == DUTIES_RESERVE
        assert season["reserve_unallocated_cents"] == DUTIES_RESERVE
