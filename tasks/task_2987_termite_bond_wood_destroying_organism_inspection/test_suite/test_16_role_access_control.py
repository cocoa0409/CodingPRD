"""Role and ownership access control: peer licensees, registry exclusivity,
homeowner scoping, undeclared and empty identity headers, the one write two
roles share, and the disjoint underwriting and adjudication seats.
"""

from test_helpers import (
    ADJUDICATOR_HEADERS,
    CATEGORY_TERMITE_APPLICATOR,
    CATEGORY_WDO_INSPECTOR,
    CLAIM_SUBMITTED,
    CLAIM_WITHDRAWN,
    CLOCK_STARTUP_INSTANT_RENDERED,
    CONSTRUCTION_SLAB,
    ERR_DAMAGE_CLAIM_NOT_FOUND,
    ERR_NOT_RESOURCE_OWNER,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    LICENSE_STATUS_ACTIVE,
    LICENSE_STATUS_SUSPENDED,
    MANAGER_HEADERS,
    NON_EXISTENT_UUID,
    NO_HEADERS,
    OFFICER_HEADERS,
    PLAN_APPROVED,
    PURPOSE_REAL_ESTATE,
    REPORT_DRAFT,
    REPORT_ISSUED,
    TIER_REPAIR_AND_RETREAT,
    TIER_RETREAT_ONLY,
    application_payload,
    approve_plan,
    assert_instant_equals,
    assert_money,
    assert_page,
    assert_status,
    assert_version,
    bond_payload,
    clock_payload,
    complete_plan,
    denial_payload,
    file_claim,
    headers_without_role,
    headers_without_user_id,
    inspector_payload,
    issue_bond,
    license_status_payload,
    make_applicator_headers,
    make_field_inspector_headers,
    make_property_owner_headers,
    make_unknown_role_headers,
    open_graph,
    property_payload,
    propose_plan,
    real_estate_inspection_payload,
    record_application,
    register_inspector,
    register_property,
    reinstatement_payload,
    set_clock,
    sign_empty_graph,
    validate_error,
    validate_success,
    wdo_report_payload,
)

MARSH_LANE = {
    "address_line1": "9 Marsh Lane",
    "state_code": "FL",
    "construction_type": CONSTRUCTION_SLAB,
    "square_footage": 1800,
    "linear_footage": 160,
    "year_built": 2001,
}

FIRST_SLOT_START = "2026-08-01T13:00:00Z"
FIRST_SLOT_END = "2026-08-01T15:00:00Z"
SECOND_SLOT_START = "2026-08-02T13:00:00Z"
SECOND_SLOT_END = "2026-08-02T15:00:00Z"
THIRD_SLOT_START = "2026-08-03T13:00:00Z"
THIRD_SLOT_END = "2026-08-03T15:00:00Z"

SALE_CLOSING_DATE = "2026-09-30"


def _peer_roster(api):
    """One structure, two WDO inspectors, two applicators, one approved plan.

    The signed graph belongs to the first inspector and the approved plan
    names the first applicator, so the second holder of each role is a peer
    with the same role and a different identifier.
    """
    prop = register_property(api, **MARSH_LANE)
    first_inspector = register_inspector(
        api, full_name="Rosa Vance", license_categories=[CATEGORY_WDO_INSPECTOR]
    )
    peer_inspector = register_inspector(
        api, full_name="Ivan Reyes", license_categories=[CATEGORY_WDO_INSPECTOR]
    )
    first_applicator = register_inspector(
        api, full_name="Dale Ortiz", license_categories=[CATEGORY_TERMITE_APPLICATOR]
    )
    peer_applicator = register_inspector(
        api, full_name="Nia Fowler", license_categories=[CATEGORY_TERMITE_APPLICATOR]
    )
    graph = open_graph(
        api,
        prop["id"],
        first_inspector["id"],
        scheduled_start_at=FIRST_SLOT_START,
        scheduled_end_at=FIRST_SLOT_END,
    )
    sign_empty_graph(api, graph["id"], first_inspector["id"])
    plan = propose_plan(api, prop["id"], graph["id"], first_applicator["id"])
    plan = approve_plan(api, plan["id"])
    return {
        "property": prop,
        "inspector": first_inspector,
        "peer_inspector": peer_inspector,
        "applicator": first_applicator,
        "peer_applicator": peer_applicator,
        "inspection": graph,
        "plan": plan,
    }


def _peer_graph_payload(roster):
    """A graph booked onto the first inspector's calendar by anybody."""
    return real_estate_inspection_payload(
        roster["property"]["id"],
        roster["inspector"]["id"],
        closing_date=SALE_CLOSING_DATE,
        scheduled_start_at=THIRD_SLOT_START,
        scheduled_end_at=THIRD_SLOT_END,
    )


def _peer_application_payload(expected_version):
    """One visit's worth of chemical, well inside the declared ranges."""
    return application_payload(
        expected_version,
        product_epa_number="432-1234",
        gallons_applied=50.00,
        concentration_pct=0.06,
    )


class TestPeerLicenseesCannotWriteToEachOthersRows:
    """Two holders of one role clear authorisation and part at ownership."""

    def test_an_inspector_cannot_open_a_graph_booked_to_a_peers_calendar(self, api):
        """A second inspector naming the first as the graph's inspector is refused.

        PRD 2.1: "Ownership is enforced on five write operations: opening a
        graph, adding a cell notation to a graph, signing a graph, recording a
        pesticide application, and recording a bait-station service visit. In
        the first three, the acting `FieldInspector`'s `X-User-ID` must equal
        the `inspector_id` carried by the graph." A mismatch "is
        `ERR_NOT_RESOURCE_OWNER` (HTTP 403)".

        Design: Corner/rbac/peer_inspectors_and_peer_applicators_cannot_write_to_each_others_rows
        """
        roster = _peer_roster(api)
        response = api.create_inspection(
            _peer_graph_payload(roster),
            make_field_inspector_headers(roster["peer_inspector"]["id"]),
        )
        validate_error(response, ERR_NOT_RESOURCE_OWNER, 403)
        assert_page(api.list_inspections(OFFICER_HEADERS), 1)

    def test_an_applicator_cannot_discharge_a_peers_plan(self, api):
        """A second applicator recording against another's approved plan is refused.

        PRD 2.1: "In the fourth, the acting `Applicator`'s `X-User-ID` must
        equal the `applicator_id` on the plan being discharged." "A mismatch in
        any of the five is `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/rbac/peer_inspectors_and_peer_applicators_cannot_write_to_each_others_rows
        """
        roster = _peer_roster(api)
        plan = roster["plan"]
        assert_status(plan, PLAN_APPROVED, "treatment plan")
        response = api.create_application(
            plan["id"],
            _peer_application_payload(plan["version"]),
            make_applicator_headers(roster["peer_applicator"]["id"]),
        )
        validate_error(response, ERR_NOT_RESOURCE_OWNER, 403)
        assert_page(api.list_applications(plan["id"], OFFICER_HEADERS), 0)

    def test_both_peers_may_still_read_the_rows_they_may_not_write(self, api):
        """Ownership gates writes; the reads stay open to every licensee.

        PRD 4: "Authorization is evaluated exactly as described in 2.1: a caller
        whose role is absent from the Authorized Role(s) column is refused
        before any other check, and the row-level ownership rules of 2.1 apply
        on top of the role check where the workflow sections say so."

        Design: Corner/rbac/peer_inspectors_and_peer_applicators_cannot_write_to_each_others_rows
        """
        roster = _peer_roster(api)
        graph = validate_success(
            api.get_inspection(
                roster["inspection"]["id"],
                make_field_inspector_headers(roster["peer_inspector"]["id"]),
            )
        )
        assert graph["id"] == roster["inspection"]["id"]
        plan = validate_success(
            api.get_treatment_plan(
                roster["plan"]["id"],
                make_applicator_headers(roster["peer_applicator"]["id"]),
            )
        )
        assert plan["id"] == roster["plan"]["id"]

    def test_the_named_applicator_records_the_very_same_application(self, api):
        """Only `X-User-ID` separated the refusal from the accepted write.

        PRD 2.1: "In the fourth, the acting `Applicator`'s `X-User-ID` must
        equal the `applicator_id` on the plan being discharged."

        Design: Corner/rbac/peer_inspectors_and_peer_applicators_cannot_write_to_each_others_rows
        """
        roster = _peer_roster(api)
        plan = roster["plan"]
        validate_success(
            api.create_application(
                plan["id"],
                _peer_application_payload(plan["version"]),
                make_applicator_headers(roster["applicator"]["id"]),
            ),
            201,
        )
        assert_page(api.list_applications(plan["id"], OFFICER_HEADERS), 1)

    def test_neither_refusal_advances_the_plans_version(self, api):
        """The version captured before both refusals still satisfies the guard.

        PRD 2.4: "`version`, an integer that starts at 1 when the row is created
        and increases by exactly 1 on every mutation of that row."

        Design: Corner/rbac/peer_inspectors_and_peer_applicators_cannot_write_to_each_others_rows
        """
        roster = _peer_roster(api)
        plan_id = roster["plan"]["id"]
        frozen = validate_success(api.get_treatment_plan(plan_id, MANAGER_HEADERS))
        frozen_version = frozen["version"]

        validate_error(
            api.create_inspection(
                _peer_graph_payload(roster),
                make_field_inspector_headers(roster["peer_inspector"]["id"]),
            ),
            ERR_NOT_RESOURCE_OWNER,
        )
        validate_error(
            api.create_application(
                plan_id,
                _peer_application_payload(frozen_version),
                make_applicator_headers(roster["peer_applicator"]["id"]),
            ),
            ERR_NOT_RESOURCE_OWNER,
        )

        unchanged = validate_success(api.get_treatment_plan(plan_id, MANAGER_HEADERS))
        assert_version(unchanged, frozen_version, "treatment plan")
        validate_success(
            api.create_application(
                plan_id,
                _peer_application_payload(frozen_version),
                make_applicator_headers(roster["applicator"]["id"]),
            ),
            201,
        )


BAY_STREET = {
    "address_line1": "77 Bay Street",
    "state_code": "FL",
    "construction_type": CONSTRUCTION_SLAB,
    "square_footage": 1500,
    "linear_footage": 150,
    "year_built": 2010,
}

MALFORMED_STRUCTURE_BODY = {
    "address_line1": "77 Bay Street",
    "state_code": "ZZZ",
    "construction_type": "IGLOO",
    "square_footage": -5,
}


def _one_active_licensee(api):
    """A single ACTIVE licensee so the licence-status path resolves."""
    return register_inspector(
        api, full_name="Rosa Vance", license_categories=[CATEGORY_WDO_INSPECTOR]
    )


class TestComplianceOfficerRegistryOperationsAreExclusive:
    """The registry writes and the clock setter admit one role only."""

    def test_a_branch_manager_cannot_register_a_structure(self, api):
        """A well-formed structure body from an underwriter is still refused.

        PRD 2.1: "If `X-User-Role` is not one of the six declared roles, or is a
        declared role that the target operation does not admit, the rejection is
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/other_roles_cannot_perform_compliance_officer_registry_operations
        """
        _one_active_licensee(api)
        response = api.create_property(property_payload(**BAY_STREET), MANAGER_HEADERS)
        validate_error(response, ERR_UNAUTHORIZED, 403)
        assert_page(api.list_properties(OFFICER_HEADERS), 0)

    def test_a_grossly_malformed_owner_body_is_refused_on_the_role_check(self, api):
        """Authorisation outranks request shape, so the answer is 403 not 400.

        PRD 2.6: "the checks below are evaluated in exactly this order, and the
        first violated check determines the response. No later check is
        evaluated once one has failed." Authorisation is stage 2 and request
        shape is stage 5.

        Design: Corner/rbac/other_roles_cannot_perform_compliance_officer_registry_operations
        """
        _one_active_licensee(api)
        response = api.create_property(
            dict(MALFORMED_STRUCTURE_BODY),
            make_property_owner_headers(NON_EXISTENT_UUID),
        )
        validate_error(response, ERR_UNAUTHORIZED, 403)
        assert_page(api.list_properties(OFFICER_HEADERS), 0)

    def test_a_field_inspector_cannot_register_a_licensee(self, api):
        """A licensee cannot enrol another licensee into the registry.

        PRD 3.2: "A `ComplianceOfficer` registers each licensee, supplying
        `full_name`, `license_number`, `license_state`, `license_categories` and
        `license_expires_on`, optionally `fumigation_endorsement` and
        `ce_credits`."

        Design: Corner/rbac/other_roles_cannot_perform_compliance_officer_registry_operations
        """
        licensee = _one_active_licensee(api)
        response = api.create_inspector(
            inspector_payload(
                full_name="Sam Cole", license_categories=[CATEGORY_WDO_INSPECTOR]
            ),
            make_field_inspector_headers(licensee["id"]),
        )
        validate_error(response, ERR_UNAUTHORIZED, 403)
        assert_page(api.list_inspectors(OFFICER_HEADERS), 1)

    def test_a_branch_manager_cannot_drive_licence_status(self, api):
        """A refused suspension leaves the licence ACTIVE at its old version.

        PRD 3.2: "Licence status thereafter moves only through a compliance
        action that names the target `status`, and only along four declared
        paths."

        Design: Corner/rbac/other_roles_cannot_perform_compliance_officer_registry_operations
        """
        licensee = _one_active_licensee(api)
        response = api.set_license_status(
            licensee["id"],
            license_status_payload(LICENSE_STATUS_SUSPENDED),
            MANAGER_HEADERS,
        )
        validate_error(response, ERR_UNAUTHORIZED, 403)
        reread = validate_success(api.get_inspector(licensee["id"], OFFICER_HEADERS))
        assert_status(reread, LICENSE_STATUS_ACTIVE, "inspector")
        assert_version(reread, licensee["version"], "inspector")

    def test_an_adjudicator_cannot_move_the_logical_clock(self, api):
        """A refused setter is a true no-op: the clock never left its startup value.

        PRD 2.5: "The clock's mandatory startup value is exactly
        `2026-08-01T00:00:00Z`: before any client moves it, every read of the
        clock returns that instant." "A `ComplianceOfficer` may set the clock to
        any UTC instant by supplying `current_utc`."

        Design: Corner/rbac/other_roles_cannot_perform_compliance_officer_registry_operations
        """
        _one_active_licensee(api)
        response = api.set_clock(
            clock_payload("2027-01-01T00:00:00Z"), ADJUDICATOR_HEADERS
        )
        validate_error(response, ERR_UNAUTHORIZED, 403)
        clock = validate_success(api.get_clock(OFFICER_HEADERS))
        assert_instant_equals(clock["current_utc"], CLOCK_STARTUP_INSTANT_RENDERED)

    def test_the_registry_reads_stay_open_to_a_branch_manager(self, api):
        """Only the writes are exclusive; the matching reads list every role.

        PRD 2.5: "any caller may read the clock's present value without
        supplying authentication headers at all". PRD 4 lists every declared
        role on `GET /inspectors/{id}`.

        Design: Corner/rbac/other_roles_cannot_perform_compliance_officer_registry_operations
        """
        licensee = _one_active_licensee(api)
        reread = validate_success(api.get_inspector(licensee["id"], MANAGER_HEADERS))
        assert reread["id"] == licensee["id"]
        clock = validate_success(api.get_clock(MANAGER_HEADERS))
        assert_instant_equals(clock["current_utc"], CLOCK_STARTUP_INSTANT_RENDERED)


BOND_ISSUE_INSTANT = "2026-09-01T00:00:00Z"
CLAIMED_DAMAGE_USD = 5000.00
FULL_TRENCH_GALLONS = 190.00


def _bonded_owner_and_a_neighbour(api):
    """An ACTIVE bond on one structure with a SUBMITTED claim, plus a neighbour.

    The neighbouring structure exists only so that a second homeowner identity
    is available: a `PropertyOwner`'s `X-User-ID` is a structure identifier.
    """
    owner_property = register_property(api, address_line1="411 Cypress Row")
    neighbour_property = register_property(
        api, address_line1="413 Cypress Row", year_built=1996
    )
    inspector = register_inspector(
        api, full_name="Rosa Vance", license_categories=[CATEGORY_WDO_INSPECTOR]
    )
    applicator = register_inspector(
        api, full_name="Dale Ortiz", license_categories=[CATEGORY_TERMITE_APPLICATOR]
    )
    graph = open_graph(
        api,
        owner_property["id"],
        inspector["id"],
        scheduled_start_at=FIRST_SLOT_START,
        scheduled_end_at=FIRST_SLOT_END,
    )
    sign_empty_graph(api, graph["id"], inspector["id"])
    plan = approve_plan(
        api,
        propose_plan(api, owner_property["id"], graph["id"], applicator["id"])["id"],
    )
    record_application(
        api,
        plan["id"],
        applicator["id"],
        plan["version"],
        product_epa_number="432-1234",
        gallons_applied=FULL_TRENCH_GALLONS,
        concentration_pct=0.06,
    )
    plan = complete_plan(api, plan["id"], applicator["id"])
    set_clock(api, BOND_ISSUE_INSTANT)
    bond = issue_bond(
        api,
        owner_property["id"],
        plan["id"],
        coverage_tier=TIER_REPAIR_AND_RETREAT,
    )
    claim = file_claim(api, bond, owner_property["id"], CLAIMED_DAMAGE_USD)
    return {
        "owner_property": owner_property,
        "neighbour_property": neighbour_property,
        "bond": bond,
        "claim": claim,
    }


class TestHomeownersAreScopedToTheirOwnBondAndClaims:
    """A homeowner identity is a structure, so two owners are peers."""

    def test_a_neighbouring_owner_cannot_withdraw_another_owners_claim(self, api):
        """The claim exists and is SUBMITTED, so this is neither a 404 nor a 409.

        PRD 3.10: "Withdrawal by a homeowner who is not the bond's
        `property_id` is `ERR_NOT_RESOURCE_OWNER`".

        Design: Corner/rbac/property_owners_cannot_reach_into_each_others_claims_or_the_inspector_registry
        """
        world = _bonded_owner_and_a_neighbour(api)
        response = api.withdraw_claim(
            world["claim"]["id"],
            {},
            make_property_owner_headers(world["neighbour_property"]["id"]),
        )
        validate_error(response, ERR_NOT_RESOURCE_OWNER, 403)
        reread = validate_success(
            api.get_damage_claim(world["claim"]["id"], OFFICER_HEADERS)
        )
        assert_status(reread, CLAIM_SUBMITTED, "damage claim")

    def test_the_licence_registry_list_is_the_one_read_an_owner_cannot_share(self, api):
        """The same role draws a different 403 code on a read it does not hold.

        PRD 2.1: "If `X-User-Role` is not one of the six declared roles, or is a
        declared role that the target operation does not admit, the rejection is
        `ERR_UNAUTHORIZED` (HTTP 403)." PRD 4 omits `PropertyOwner` from
        `GET /inspectors` alone.

        Design: Corner/rbac/property_owners_cannot_reach_into_each_others_claims_or_the_inspector_registry
        """
        world = _bonded_owner_and_a_neighbour(api)
        response = api.list_inspectors(
            make_property_owner_headers(world["owner_property"]["id"]),
            params={"limit": 10, "offset": 0},
        )
        validate_error(response, ERR_UNAUTHORIZED, 403)

    def test_a_neighbouring_owner_may_still_read_the_claim(self, api):
        """Claim reads are shared by every declared role; only writes are scoped.

        PRD 3.10: "Any caller with a stake in the bond may read one claim, with
        its exclusion basis and full money breakdown, or list claims."

        Design: Corner/rbac/property_owners_cannot_reach_into_each_others_claims_or_the_inspector_registry
        """
        world = _bonded_owner_and_a_neighbour(api)
        reread = validate_success(
            api.get_damage_claim(
                world["claim"]["id"],
                make_property_owner_headers(world["neighbour_property"]["id"]),
            )
        )
        assert reread["id"] == world["claim"]["id"]

    def test_the_bonded_owners_own_withdrawal_succeeds_and_moves_no_money(self, api):
        """The same call from the bond's own structure is accepted and is free.

        PRD 3.10: "Withdrawing from `SUBMITTED` simply moves it to `WITHDRAWN`
        and moves no money, because nothing had been reserved before
        verification."

        Design: Corner/rbac/property_owners_cannot_reach_into_each_others_claims_or_the_inspector_registry
        """
        world = _bonded_owner_and_a_neighbour(api)
        bond_at_issue = world["bond"]
        withdrawn = validate_success(
            api.withdraw_claim(
                world["claim"]["id"],
                {},
                make_property_owner_headers(world["owner_property"]["id"]),
            )
        )
        assert_status(withdrawn, CLAIM_WITHDRAWN, "damage claim")
        bond = validate_success(api.get_bond(bond_at_issue["id"], OFFICER_HEADERS))
        assert_money(bond["reserved_claim_amount_usd"], 0.00)
        assert_money(
            bond["remaining_repair_cap_usd"],
            bond_at_issue["remaining_repair_cap_usd"],
        )
        assert_money(bond["claims_paid_to_date_usd"], 0.00)


UNKNOWN_ROLE_USER_ID = "aud-1"
UNKNOWN_ROLE = "Auditor"

NOWHERE = {
    "address_line1": "1 Nowhere",
    "state_code": "FL",
    "construction_type": CONSTRUCTION_SLAB,
    "square_footage": 100,
    "linear_footage": 40,
    "year_built": 2000,
}


class TestUndeclaredRolesAndEmptyIdentityHeaders:
    """Emptiness is authentication; an unrecognised role is authorisation."""

    def test_an_undeclared_role_is_refused_as_authorisation_not_authentication(
        self, api
    ):
        """Both headers are present, so the refusal is 403 rather than 401.

        PRD 2.1: "If `X-User-Role` is not one of the six declared roles, or is a
        declared role that the target operation does not admit, the rejection is
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/unknown_role_and_missing_identity_headers_are_unauthorized_before_anything_else
        """
        prop = register_property(api, **MARSH_LANE)
        response = api.get_property(
            prop["id"], make_unknown_role_headers(UNKNOWN_ROLE_USER_ID, UNKNOWN_ROLE)
        )
        validate_error(response, ERR_UNAUTHORIZED, 403)

    def test_an_empty_role_header_is_unauthenticated(self, api):
        """An empty `X-User-Role` counts as absence and answers 401.

        PRD 2.1: "If either header is absent or empty, the request is rejected
        with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else about it is
        examined."

        Design: Corner/rbac/unknown_role_and_missing_identity_headers_are_unauthorized_before_anything_else
        """
        prop = register_property(api, **MARSH_LANE)
        response = api.get_property(prop["id"], headers_without_role())
        validate_error(response, ERR_UNAUTHENTICATED, 401)

    def test_an_empty_user_id_header_is_unauthenticated(self, api):
        """An empty `X-User-ID` draws the same 401 as an empty role.

        PRD 2.1: "Every request except the logical-clock read must carry two
        headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming
        the capacity in which the caller is acting. If either header is absent
        or empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)
        before anything else about it is examined."

        Design: Corner/rbac/unknown_role_and_missing_identity_headers_are_unauthorized_before_anything_else
        """
        prop = register_property(api, **MARSH_LANE)
        response = api.get_property(prop["id"], headers_without_user_id())
        validate_error(response, ERR_UNAUTHENTICATED, 401)

    def test_an_undeclared_role_is_refused_before_the_body_is_examined(self, api):
        """The unknown role's write is 403, not 400, and creates nothing.

        PRD 2.6: "the checks below are evaluated in exactly this order, and the
        first violated check determines the response. No later check is
        evaluated once one has failed." Authorisation is stage 2 and request
        shape is stage 5.

        Design: Corner/rbac/unknown_role_and_missing_identity_headers_are_unauthorized_before_anything_else
        """
        register_property(api, **MARSH_LANE)
        response = api.create_property(
            property_payload(**NOWHERE),
            make_unknown_role_headers(UNKNOWN_ROLE_USER_ID, UNKNOWN_ROLE),
        )
        validate_error(response, ERR_UNAUTHORIZED, 403)
        assert_page(api.list_properties(OFFICER_HEADERS), 1)

    def test_the_clock_read_is_the_single_endpoint_exempt_from_the_headers(self, api):
        """With no identity headers at all the clock still answers 200.

        PRD 2.5: "any caller may read the clock's present value without
        supplying authentication headers at all — the clock read is the single
        endpoint exempt from the header requirement." "The clock's mandatory
        startup value is exactly `2026-08-01T00:00:00Z`."

        Design: Corner/rbac/unknown_role_and_missing_identity_headers_are_unauthorized_before_anything_else
        """
        register_property(api, **MARSH_LANE)
        clock = validate_success(api.get_clock(NO_HEADERS))
        assert_instant_equals(clock["current_utc"], CLOCK_STARTUP_INSTANT_RENDERED)


def _two_signed_sale_graphs(api):
    """One FL structure carrying two signed REAL_ESTATE graphs."""
    prop = register_property(api, **MARSH_LANE)
    inspector = register_inspector(
        api, full_name="Rosa Vance", license_categories=[CATEGORY_WDO_INSPECTOR]
    )
    first = open_graph(
        api,
        prop["id"],
        inspector["id"],
        purpose=PURPOSE_REAL_ESTATE,
        closing_date=SALE_CLOSING_DATE,
        scheduled_start_at=FIRST_SLOT_START,
        scheduled_end_at=FIRST_SLOT_END,
    )
    sign_empty_graph(api, first["id"], inspector["id"])
    second = open_graph(
        api,
        prop["id"],
        inspector["id"],
        purpose=PURPOSE_REAL_ESTATE,
        closing_date=SALE_CLOSING_DATE,
        scheduled_start_at=SECOND_SLOT_START,
        scheduled_end_at=SECOND_SLOT_END,
    )
    sign_empty_graph(api, second["id"], inspector["id"])
    return {
        "property": prop,
        "inspector": inspector,
        "first": first,
        "second": second,
    }


class TestStatutoryReportCreationIsSharedByExactlyTwoRoles:
    """Requesting a statutory form is shared; signing it is not."""

    def test_a_compliance_officer_may_open_a_statutory_report(self, api):
        """The officer's request lands in DRAFT stamped with the clock instant.

        PRD 3.4: "When a sale is pending, either the homeowner or a
        `ComplianceOfficer` opens a statutory wood-destroying-organism report
        against a `REAL_ESTATE` graph, naming it through `inspection_id` and
        declaring the `form_code` being filed. The report is created in status
        `DRAFT`, its `requested_at` stamped with the current clock instant".

        Design: Corner/rbac/wdo_report_creation_is_shared_by_two_roles_and_rejects_the_third
        """
        world = _two_signed_sale_graphs(api)
        report = validate_success(
            api.create_wdo_report(
                wdo_report_payload(world["first"]["id"], state_code="FL"),
                OFFICER_HEADERS,
            ),
            201,
        )
        assert_status(report, REPORT_DRAFT, "statutory report")
        assert_instant_equals(
            report["requested_at"], CLOCK_STARTUP_INSTANT_RENDERED
        )

    def test_the_homeowner_may_also_open_a_statutory_report(self, api):
        """The other admitted role reaches the identical DRAFT outcome.

        PRD 3.4: "either the homeowner or a `ComplianceOfficer` opens a
        statutory wood-destroying-organism report against a `REAL_ESTATE`
        graph". The report "is created in status `DRAFT`, its `requested_at`
        stamped with the current clock instant".

        Design: Corner/rbac/wdo_report_creation_is_shared_by_two_roles_and_rejects_the_third
        """
        world = _two_signed_sale_graphs(api)
        report = validate_success(
            api.create_wdo_report(
                wdo_report_payload(world["second"]["id"], state_code="FL"),
                make_property_owner_headers(world["property"]["id"]),
            ),
            201,
        )
        assert_status(report, REPORT_DRAFT, "statutory report")
        assert_instant_equals(
            report["requested_at"], CLOCK_STARTUP_INSTANT_RENDERED
        )

    def test_a_branch_manager_cannot_open_a_statutory_report(self, api):
        """Sharing is between exactly two roles, not between all of them.

        PRD 2.1: "If `X-User-Role` is not one of the six declared roles, or is a
        declared role that the target operation does not admit, the rejection is
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/wdo_report_creation_is_shared_by_two_roles_and_rejects_the_third
        """
        world = _two_signed_sale_graphs(api)
        response = api.create_wdo_report(
            wdo_report_payload(world["first"]["id"], state_code="FL"), MANAGER_HEADERS
        )
        validate_error(response, ERR_UNAUTHORIZED, 403)
        assert_page(api.list_wdo_reports(OFFICER_HEADERS), 0)

    def test_a_field_inspector_cannot_open_a_statutory_report(self, api):
        """The licensee who signed the graph still cannot file the form.

        PRD 2.1: "If `X-User-Role` is not one of the six declared roles, or is a
        declared role that the target operation does not admit, the rejection is
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/wdo_report_creation_is_shared_by_two_roles_and_rejects_the_third
        """
        world = _two_signed_sale_graphs(api)
        response = api.create_wdo_report(
            wdo_report_payload(world["first"]["id"], state_code="FL"),
            make_field_inspector_headers(world["inspector"]["id"]),
        )
        validate_error(response, ERR_UNAUTHORIZED, 403)
        assert_page(api.list_wdo_reports(OFFICER_HEADERS), 0)

    def test_the_homeowner_cannot_issue_the_report_they_requested(self, api):
        """Creation is shared but issuance stays with the compliance operator.

        PRD 3.4: "Issuance, which a `ComplianceOfficer` performs, moves the
        report `DRAFT → ISSUED`."

        Design: Corner/rbac/wdo_report_creation_is_shared_by_two_roles_and_rejects_the_third
        """
        world = _two_signed_sale_graphs(api)
        owner_headers = make_property_owner_headers(world["property"]["id"])
        report = validate_success(
            api.create_wdo_report(
                wdo_report_payload(world["second"]["id"], state_code="FL"),
                owner_headers,
            ),
            201,
        )
        response = api.issue_wdo_report(report["id"], {}, owner_headers)
        validate_error(response, ERR_UNAUTHORIZED, 403)
        reread = validate_success(api.get_wdo_report(report["id"], OFFICER_HEADERS))
        assert_status(reread, REPORT_DRAFT, "statutory report")

    def test_the_officer_issues_the_owners_report_with_a_zero_hour_turnaround(
        self, api
    ):
        """Issued in the same clock instant it was requested, so nothing elapsed.

        PRD 3.4: "A successful issuance sets `status` to `ISSUED` and stamps
        `issued_at` with the clock instant of that issuance." "`turnaround_hours`,
        the number of whole hours from `requested_at` to `issued_at` rounded up
        so that any partial hour counts as a full one".

        Design: Corner/rbac/wdo_report_creation_is_shared_by_two_roles_and_rejects_the_third
        """
        world = _two_signed_sale_graphs(api)
        report = validate_success(
            api.create_wdo_report(
                wdo_report_payload(world["second"]["id"], state_code="FL"),
                make_property_owner_headers(world["property"]["id"]),
            ),
            201,
        )
        issued = validate_success(api.issue_wdo_report(report["id"], {}, OFFICER_HEADERS))
        assert_status(issued, REPORT_ISSUED, "statutory report")
        assert issued["turnaround_hours"] == 0, (
            "expected turnaround_hours 0, got %r" % (issued["turnaround_hours"],)
        )
        assert_instant_equals(issued["issued_at"], CLOCK_STARTUP_INSTANT_RENDERED)


REINSTATEMENT_PAYMENT_USD = 500.00


class TestUnderwritingAndAdjudicationSeatsAreDisjoint:
    """The role gate fires on an empty system, ahead of the path lookup."""

    def test_a_branch_manager_cannot_adjudicate_even_an_unknown_claim(self, api):
        """The role gate answers before the path segment is ever resolved.

        PRD 2.6: "the checks below are evaluated in exactly this order, and the
        first violated check determines the response. No later check is
        evaluated once one has failed." Authorisation is stage 2 and path
        existence is stage 4.

        Design: Corner/rbac/underwriting_and_adjudication_seats_cannot_be_swapped_between_roles
        """
        response = api.adjudicate_claim(
            NON_EXISTENT_UUID, denial_payload(), MANAGER_HEADERS
        )
        validate_error(response, ERR_UNAUTHORIZED, 403)

    def test_an_adjudicator_cannot_underwrite_a_bond(self, api):
        """Underwriting belongs to the branch, not to the claims desk.

        PRD 2.1: "A `BranchManager` performs underwriting and authorisation:
        proposing, approving and abandoning treatment plans, issuing bonds,
        opening and completing renewals, and reinstating lapsed bonds."

        Design: Corner/rbac/underwriting_and_adjudication_seats_cannot_be_swapped_between_roles
        """
        response = api.create_bond(
            bond_payload(
                NON_EXISTENT_UUID,
                NON_EXISTENT_UUID,
                coverage_tier=TIER_RETREAT_ONLY,
            ),
            ADJUDICATOR_HEADERS,
        )
        validate_error(response, ERR_UNAUTHORIZED, 403)

    def test_the_term_review_sweep_is_closed_to_a_branch_manager(self, api):
        """Sweeping a bond against the clock is a compliance action.

        PRD 2.1: "A `ComplianceOfficer` is the state-compliance operator: it
        owns the registry of structures and inspectors, drives licence status,
        files and issues statutory reports, runs the bond term-review sweep, and
        sets the logical clock."

        Design: Corner/rbac/underwriting_and_adjudication_seats_cannot_be_swapped_between_roles
        """
        response = api.term_review(NON_EXISTENT_UUID, {}, MANAGER_HEADERS)
        validate_error(response, ERR_UNAUTHORIZED, 403)

    def test_reinstatement_is_closed_to_a_compliance_officer(self, api):
        """The two bond-lifecycle seats are disjoint in both directions.

        PRD 2.1: "A `BranchManager` performs underwriting and authorisation:
        proposing, approving and abandoning treatment plans, issuing bonds,
        opening and completing renewals, and reinstating lapsed bonds."

        Design: Corner/rbac/underwriting_and_adjudication_seats_cannot_be_swapped_between_roles
        """
        response = api.reinstate_bond(
            NON_EXISTENT_UUID,
            reinstatement_payload(NON_EXISTENT_UUID, REINSTATEMENT_PAYMENT_USD),
            OFFICER_HEADERS,
        )
        validate_error(response, ERR_UNAUTHORIZED, 403)

    def test_the_adjudicator_reaches_the_path_check_the_manager_never_saw(self, api):
        """The admitted role gets the 404, proving the 403 came from the role gate.

        PRD 2.6: "Every identifier segment in the request path resolves to a
        persisted row of that segment's type, validated left to right; the
        leftmost segment that fails to resolve reports its own type's not-found
        code — ... or `ERR_DAMAGE_CLAIM_NOT_FOUND` — all at HTTP 404."

        Design: Corner/rbac/underwriting_and_adjudication_seats_cannot_be_swapped_between_roles
        """
        validate_error(
            api.adjudicate_claim(NON_EXISTENT_UUID, denial_payload(), MANAGER_HEADERS),
            ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.adjudicate_claim(
                NON_EXISTENT_UUID, denial_payload(), ADJUDICATOR_HEADERS
            ),
            ERR_DAMAGE_CLAIM_NOT_FOUND,
            404,
        )
