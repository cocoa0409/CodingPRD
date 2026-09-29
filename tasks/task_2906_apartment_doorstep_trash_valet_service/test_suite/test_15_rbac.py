"""Access control: role grants, entity-backed ownership and peer-operator duties."""

from test_helpers import (
    ANALYST_DRAFTER,
    COMPLIANCE_AUDITOR,
    COMPLIANCE_SCREENER,
    OPERATORS,
    ApiErrorId,
    api_client,
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
# Rung 2: the role is simply not on the endpoint's list
# --------------------------------------------------------------------------
def test_the_valet_who_walked_the_round_still_cannot_close_the_night():
    """Closing is the ops manager's exclusive act, so the walker is refused.

    PRD 2.1: "`ValetOpsManager` is the regional valet operations manager. It alone
    closes a service night and reschedules a service night."

    PRD 2.5: "**Authorization.** The acting role appears in the endpoint's
    authorized-role list in §4 — otherwise `ERR_UNAUTHORIZED` (403). Applies to
    every endpoint."

    Design: Corner/rbac/valet_cannot_close_a_service_night_returns_unauthorized
    """
    world = fixtures.build_scan_ready_night(
        name="Cedar Ridge",
        unit_count=4,
        resident_units=(101,),
        resident_kwargs={101: {"move_in_date": "2026-08-01"}},
        service_date="2026-09-01",
    )
    before = fixtures.read_night(world["night"]["id"])

    response = api_client.close_service_night(
        world["night"]["id"], make_valet_headers(world["contractor"]["id"])
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    after = fixtures.read_night(world["night"]["id"])
    assert after["verification_status"] == "SCHEDULED"
    assert after["billing_status"] == "UNBILLED"
    assert after["version"] == before["version"]


def test_the_on_site_manager_cannot_activate_its_own_communitys_contract():
    """Activation is reserved to the platform operator, ownership notwithstanding.

    PRD 2.1: "`PlatformAdmin` is the Valet Living platform operator. It alone
    registers a property, activates a service contract, terminates a service
    contract, voids a monthly statement, and repositions the logical clock."

    Design: Corner/rbac/property_manager_cannot_activate_a_contract_returns_unauthorized
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    prop = fixtures.create_property(name="Cedar Ridge", unit_count=4)
    contract = fixtures.draft_contract(prop["id"])

    response = api_client.activate_contract(
        contract["id"], make_property_manager_headers(prop["id"])
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    assert fixtures.read_contract(contract["id"])["status"] == "DRAFT"
    unchanged = fixtures.read_property(prop["id"])
    assert unchanged["status"] == "ONBOARDING"
    assert unchanged["active_contract_id"] is None


def test_a_billing_analyst_cannot_report_a_compactor_incident():
    """Incident reporting is open to four roles, and the analyst is not one of them.

    PRD 4: "| POST | `/valet/properties/{property_id}/compactor-incidents` | Report
    a compactor jam or overflow. The acknowledgement deadline is stamped from the
    incident type's window: four hours for a jam, twenty-four for an overflow. |
    PlatformAdmin, ValetOpsManager, PropertyManager, Valet |"

    Design: Corner/rbac/billing_analyst_cannot_report_a_compactor_incident_returns_unauthorized
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    prop = fixtures.create_property(name="Cedar Ridge", unit_count=4)

    response = api_client.create_compactor_incident(
        prop["id"],
        factories.incident_payload("JAM", "ram jammed on a mattress"),
        ANALYST_DRAFTER,
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    assert fixtures.list_incidents({"property_id": prop["id"]}) == []
    assert fixtures.read_property(prop["id"])["escalation_level"] == 0


def test_the_on_site_manager_cannot_reschedule_a_night_of_its_own_community():
    """Schedule adjustment is refused at rung 2, before any makeup-date arithmetic.

    PRD 2.1: "`ValetOpsManager` is the regional valet operations manager. It alone
    closes a service night and reschedules a service night."

    PRD 2.5: "**Makeup date validity.** On a shift reschedule,
    `makeup_service_date` must be present, strictly later than the original
    `service_date`, no more than fourteen days after it, inside the contract's
    closed effective period, and not already occupied by a non-cancelled night of
    the same contract — otherwise `ERR_INVALID_MAKEUP_DATE` (422). Applies to
    service-night rescheduling."

    Design: Corner/rbac/property_manager_cannot_reschedule_a_service_night_returns_unauthorized
    """
    world = fixtures.build_active_community(
        name="Cedar Ridge",
        unit_count=4,
        resident_units=(101,),
        resident_kwargs={101: {"move_in_date": "2026-08-01"}},
        with_contractor=False,
    )
    night = fixtures.schedule_night(world["contract"]["id"], "2026-09-01")

    response = api_client.reschedule_service_night(
        night["id"],
        factories.reschedule_payload("SKIP", reason="Labor Day holiday"),
        make_property_manager_headers(world["property"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    after = fixtures.read_night(night["id"])
    assert after["verification_status"] == "SCHEDULED"
    assert after["reschedule_action"] is None
    assert after["version"] == night["version"]


def test_a_resident_is_refused_the_roster_list_but_still_reads_its_own_record():
    """The denial is endpoint-scoped: no filtered one-row list is substituted.

    PRD 2.1: "`Resident` is the apartment resident who pays the pass-through fee.
    It alone disputes a resident fine, and otherwise reads only its own resident
    record, scans and fines."

    PRD 4: "| GET | `/valet/residents` | List residents, filterable by community,
    lifecycle status and collections status. | PlatformAdmin, PropertyManager,
    BillingAnalyst, ComplianceOfficer |"

    Design: Corner/rbac/resident_cannot_list_the_property_roster_returns_unauthorized
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    prop = fixtures.create_property(name="Cedar Ridge", unit_count=4)
    resident = fixtures.create_resident(
        prop["id"], 101, full_name="Rosa One", move_in_date="2026-08-01"
    )
    headers = make_resident_headers(resident["id"])

    listing = api_client.list_residents(headers, params={"property_id": prop["id"]})

    validate_error(listing, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    own = validate_success(api_client.get_resident(resident["id"], headers))
    assert own["id"] == resident["id"]
    assert own["unit_number"] == 101


# --------------------------------------------------------------------------
# Rung 4: peers of the same role, separated by X-User-ID
# --------------------------------------------------------------------------
def test_one_valet_cannot_accept_the_route_assigned_to_another():
    """Both callers hold the Valet role, so only the identity header differs.

    PRD 2.1: "When `X-User-Role` is `Valet`, `X-User-ID` is the `id` of the acting
    `ValetContractor`. Ownership checks on a route assignment compare
    `contractor_id` to `X-User-ID`, and a scan is owned through the route it is
    recorded against."

    PRD 3.5: "Acceptance belongs exclusively to the `Valet`. The route moves
    `ASSIGNED → ACCEPTED` and `accepted_at` is stamped from the logical clock. Four
    conditions hold: the route must still be `ASSIGNED`, the acting `X-User-ID` must
    equal the route's `contractor_id`, the valet's `onboarding_status` must still be
    `CLEARED`, and the community must still be `ACTIVE`."

    Design: Corner/rbac/valet_cannot_accept_another_valets_route_returns_not_resource_owner
    """
    world = fixtures.build_active_community(
        name="Cedar Ridge",
        unit_count=4,
        resident_units=(101,),
        resident_kwargs={101: {"move_in_date": "2026-08-01"}},
        contractor_kwargs={"legal_name": "Ada Kim"},
    )
    intruder = fixtures.create_eligible_contractor(legal_name="Bea Ryu")
    night = fixtures.schedule_night(world["contract"]["id"], "2026-09-01")
    route = fixtures.assign_route(night["id"], world["contractor"]["id"], 101, 104)

    response = api_client.accept_route(route["id"], make_valet_headers(intruder["id"]))

    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
    assert response.status_code != 401, "the intruder does hold a declared role"
    refused = fixtures.read_route(route["id"])
    assert refused["status"] == "ASSIGNED"
    assert refused["accepted_at"] is None
    accepted = validate_success(
        api_client.accept_route(
            route["id"], make_valet_headers(world["contractor"]["id"])
        )
    )
    assert accepted["status"] == "ACCEPTED", (
        "the only difference is the identity header"
    )


def test_a_resident_reads_its_own_auto_assessed_fine():
    """The fined resident is on the read row's authorized-role list.

    The negative half of the original scenario — a neighbour resident reading
    this fine — has been removed: PRD 2.1 and PRD 2.5 rung 4 both scope
    `ERR_NOT_RESOURCE_OWNER` to *write* endpoints ("Applies to every write
    endpoint reachable by `Valet`, `Resident` or `PropertyManager`"), so the
    refusal on a read endpoint is not uniquely derivable from the PRD.

    PRD 4: "| GET | `/valet/resident-fines/{fine_id}` | Read one resident fine,
    including the capped and uncapped amounts and the dispute round counter. |
    PlatformAdmin, PropertyManager, BillingAnalyst, ComplianceOfficer, Resident |"

    Design: Corner/rbac/resident_cannot_read_another_residents_fine_returns_not_resource_owner
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
    scan = fixtures.record_scan(
        world["route"]["id"],
        world["contractor"]["id"],
        world["residents"][101]["id"],
        scan_result="TAGGED_NOT_SERVICED",
        container_type="RECYCLING_BIN",
        non_compliance_type="RECYCLING_CONTAMINATION",
    )
    fine = fixtures.find_fine_for_scan(scan["id"])
    assert fine is not None, "a recycling contamination auto-fines on the first offense"

    own = validate_success(
        api_client.get_fine(
            fine["id"], make_resident_headers(world["residents"][101]["id"])
        )
    )

    assert own["id"] == fine["id"]
    assert own["resident_id"] == world["residents"][101]["id"]
    assert own["amount_cents"] == 2500
    assert own["origin"] == "AUTO"
    assert own["dispute_round"] == 0


def test_a_property_manager_reads_its_own_community():
    """X-User-ID is a property id and that community's row is readable by it.

    The negative half of the original scenario — the same manager reading a
    sibling community — has been removed: PRD 2.1 and PRD 2.5 rung 4 both scope
    `ERR_NOT_RESOURCE_OWNER` to *write* endpoints ("Applies to every write
    endpoint reachable by `Valet`, `Resident` or `PropertyManager`"), so the
    refusal on a read endpoint is not uniquely derivable from the PRD.

    PRD 4: "| GET | `/valet/properties/{property_id}` | Read one community,
    including its derived escalation and collections rollups. | PlatformAdmin,
    ValetOpsManager, ComplianceOfficer, BillingAnalyst, PropertyManager |"

    Design: Corner/rbac/property_manager_cannot_read_another_property_returns_not_resource_owner
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    willow = fixtures.create_property(name="Willow Court", unit_count=6)
    headers = make_property_manager_headers(willow["id"])

    own = validate_success(api_client.get_property(willow["id"], headers))

    assert own["id"] == willow["id"]
    assert own["name"] == "Willow Court"
    assert own["unit_count"] == 6
    assert own["status"] == "ONBOARDING"


# --------------------------------------------------------------------------
# Rung 13: two operators of the same role, separated by duty
# --------------------------------------------------------------------------
def test_the_analyst_who_drafted_the_statement_cannot_issue_it():
    """The comparison is purely on X-User-ID, and the draft survives the refusal.

    PRD 2.11: "First, the analyst who drafts a monthly statement may not be the
    analyst who issues it. The drafting operator's identifier is retained as
    `created_by_user_id`, and at issue time the acting `X-User-ID` is compared
    against it; if they match, the issue is refused with
    `ERR_SEGREGATION_OF_DUTIES` at HTTP 403."

    Design: Corner/rbac/drafting_analyst_cannot_issue_their_own_statement
    """
    world = fixtures.build_active_community(
        name="Cedar Ridge",
        unit_count=4,
        resident_units=(101,),
        resident_kwargs={101: {"move_in_date": "2026-08-01"}},
        with_contractor=False,
    )
    night = fixtures.schedule_night(world["contract"]["id"], "2026-09-01")
    fixtures.close_night(night["id"])
    statement = fixtures.draft_statement(world["contract"]["id"], "2026-09")
    assert statement["created_by_user_id"] == OPERATORS["ANALYST_DRAFTER"]

    response = api_client.issue_statement(statement["id"], ANALYST_DRAFTER)

    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    refused = fixtures.read_statement(statement["id"])
    assert refused["status"] == "DRAFT"
    assert refused["variant"] == "PROVISIONAL"
    assert refused["issued_by_user_id"] is None
    assert fixtures.read_night(night["id"])["billing_status"] == "ACCRUED"
    assert fixtures.read_contract(world["contract"]["id"])["last_invoiced_period"] is None


def test_the_screening_officer_may_run_the_declared_screen_but_not_the_observed_audit():
    """The duty rule binds the audit only, and the refused run writes nothing.

    PRD 2.11: "Second, the compliance officer who recorded a contractor's
    background check may not perform that contractor's `OBSERVED` reclassification
    audit. The screening operator's identifier is retained as
    `background_checked_by_user_id`, and an `OBSERVED` classification run whose
    `X-User-ID` matches it is refused with the same `ERR_SEGREGATION_OF_DUTIES` at
    HTTP 403. A `DECLARED` classification run is deliberately **not** subject to
    this restriction: the declared screen simply reads the onboarding packet and
    carries no audit independence requirement, so the same officer who cleared the
    background check may run it."

    PRD 3.3: "A `DECLARED` run does not write `observed_weekly_hours`; whatever
    value that field already held is left exactly as it was."

    Design: Corner/rbac/screening_officer_cannot_run_the_observed_reclassification
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    contractor = fixtures.create_contractor(
        legal_name="Val Ito",
        equipment_provided_by_company=True,
        sets_own_schedule=True,
        works_exclusively=False,
        weekly_committed_hours=20,
    )
    fixtures.submit_documents(contractor["id"], "W9", True)
    fixtures.record_background_check(contractor["id"], "CLEAR")
    declared = fixtures.classify_contractor(contractor["id"], "DECLARED")
    assert declared["control_score"] == 30
    assert declared["classification"] == "CONTRACTOR_1099"
    before = fixtures.read_contractor(contractor["id"])

    response = api_client.run_classification(
        contractor["id"],
        factories.classification_payload("OBSERVED"),
        COMPLIANCE_SCREENER,
    )

    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    refused = fixtures.read_contractor(contractor["id"])
    assert refused["classification_basis"] == "DECLARED"
    assert refused["control_score"] == 30
    assert refused["classification"] == "CONTRACTOR_1099"
    assert float(refused["observed_weekly_hours"]) == 0.0
    assert refused["version"] == before["version"]
    audited = validate_success(
        api_client.run_classification(
            contractor["id"],
            factories.classification_payload("OBSERVED"),
            COMPLIANCE_AUDITOR,
        )
    )
    assert audited["classification_basis"] == "OBSERVED", (
        "a second officer may run the very same audit"
    )
    assert audited["control_score"] == 30


# --------------------------------------------------------------------------
# The positive half of the contract
# --------------------------------------------------------------------------
def test_the_assigned_valet_accepts_and_then_completes_its_own_route():
    """Both exclusive route operations succeed in sequence for the owning valet.

    PRD 3.5: "The valet closes out their own range by completing it, which is
    permitted from `ACCEPTED` or from `IN_PROGRESS` and requires the acting
    `X-User-ID` to equal the route's `contractor_id`. The route moves to
    `COMPLETED`, `completed_at` is stamped from the logical clock, and the night's
    `assigned_unit_coverage_count` is recomputed — completed routes remain inside
    the live sum."

    Design: Corner/rbac/valet_can_accept_and_then_complete_its_own_route
    """
    world = fixtures.build_active_community(
        name="Cedar Ridge",
        unit_count=4,
        resident_units=(),
        clock="2026-09-01T18:00:00Z",
    )
    night = fixtures.schedule_night(world["contract"]["id"], "2026-09-01")
    route = fixtures.assign_route(night["id"], world["contractor"]["id"], 101, 104)
    headers = make_valet_headers(world["contractor"]["id"])

    accepted = validate_success(api_client.accept_route(route["id"], headers))
    completed = validate_success(api_client.complete_route(route["id"], headers))

    assert accepted["status"] == "ACCEPTED"
    assert completed["status"] == "COMPLETED"
    assert_instants_equal(
        accepted["accepted_at"], "2026-09-01T18:00:00.000Z", "accepted_at"
    )
    assert_instants_equal(
        completed["completed_at"], "2026-09-01T18:00:00.000Z", "completed_at"
    )
    assert completed["scan_count"] == 0
    assert completed["unit_coverage_count"] == 4
    after = fixtures.read_night(night["id"])
    assert after["assigned_unit_coverage_count"] == 4
    assert after["verification_status"] == "SCHEDULED", (
        "no scan was recorded, so nothing bubbled up"
    )
