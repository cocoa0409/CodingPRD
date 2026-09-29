"""Optimistic concurrency on the two supersede writes, and same-request visibility."""

from test_helpers import (
    ANALYST_DRAFTER,
    VALET_OPS_MANAGER,
    ApiErrorId,
    api_client,
    assert_resident_ledger,
    factories,
    fixtures,
    make_valet_headers,
    validate_error,
    validate_success,
)


# --------------------------------------------------------------------------
# The night's coverage map is guarded by its version, not by its ranges
# --------------------------------------------------------------------------
def test_a_second_dispatch_replaying_the_planned_night_version_is_refused():
    """The range 103-104 is free; only the observed version is out of date.

    PRD 2.8: "Creating a route assignment on a service night requires
    `expected_service_night_version` carrying the `version` of that `ServiceNight`
    as the client last observed it. If that value does not equal the night's current
    `version`, the request is rejected with `ERR_STALE_SERVICE_NIGHT_VERSION` at
    HTTP 412 and nothing is created."

    Design: Corner/cross_cutting_complexity_layers/stale_service_night_version_on_route_create_is_rejected
    """
    world = fixtures.build_active_community(
        name="Cedar Ridge",
        unit_count=4,
        resident_units=(101,),
        resident_kwargs={101: {"move_in_date": "2026-08-01"}},
        contractor_kwargs={"legal_name": "Ada Kim"},
    )
    second_valet = fixtures.create_eligible_contractor(legal_name="Bea Ryu")
    night = fixtures.schedule_night(world["contract"]["id"], "2026-09-01")
    planned_version = night["version"]
    fixtures.assign_route(night["id"], world["contractor"]["id"], 101, 102)

    response = api_client.create_route_assignment(
        night["id"],
        factories.route_payload(second_valet["id"], 103, 104, planned_version),
        VALET_OPS_MANAGER,
    )

    validate_error(response, ApiErrorId.ERR_STALE_SERVICE_NIGHT_VERSION.value, 412)
    refused = fixtures.read_night(night["id"])
    assert refused["assigned_unit_coverage_count"] == 2
    assert len(fixtures.list_routes({"service_night_id": night["id"]})) == 1
    retried = validate_success(
        api_client.create_route_assignment(
            night["id"],
            factories.route_payload(
                second_valet["id"], 103, 104, refused["version"]
            ),
            VALET_OPS_MANAGER,
        ),
        expected_status=201,
    )
    assert retried["status"] == "ASSIGNED", (
        "the range itself was never the obstacle"
    )
    assert fixtures.read_night(night["id"])["assigned_unit_coverage_count"] == 4


# --------------------------------------------------------------------------
# The contract's terms are guarded the same way
# --------------------------------------------------------------------------
def test_a_draft_replaying_the_pre_activation_contract_version_is_refused():
    """Activation moved the contract on, so the analyst's read is stale.

    PRD 2.8: "Drafting a monthly statement on a contract requires
    `expected_contract_version` carrying the `version` of that `ServiceContract` as
    the client last observed it. If that value does not equal the contract's current
    `version`, the request is rejected with `ERR_STALE_CONTRACT_VERSION` at HTTP 412
    and no draft is created."

    Design: Corner/cross_cutting_complexity_layers/stale_contract_version_on_statement_draft_is_rejected
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    prop = fixtures.create_property(name="Cedar Ridge", unit_count=4)
    contract = fixtures.draft_contract(prop["id"])
    drafted_version = contract["version"]
    fixtures.activate_contract(contract["id"])

    response = api_client.create_statement(
        contract["id"],
        factories.statement_payload("2026-09", drafted_version),
        ANALYST_DRAFTER,
    )

    validate_error(response, ApiErrorId.ERR_STALE_CONTRACT_VERSION.value, 412)
    assert fixtures.list_statements({"contract_id": contract["id"]}) == []
    after = fixtures.read_contract(contract["id"])
    assert after["version"] == drafted_version + 1, (
        "only the activation bumped it; the rejected write did not"
    )
    assert after["last_invoiced_period"] is None


# --------------------------------------------------------------------------
# Versions count writes, including bubbled ones, and never count reads
# --------------------------------------------------------------------------
def test_a_bubbled_activation_bumps_the_community_while_reads_never_do():
    """Creating the child left the parent alone; activating it did not.

    PRD 2.4: "`version` (integer): a counter that starts at 1 on creation and
    increases by exactly 1 on every mutation of that row. A cascade that mutates a
    parent or sibling row increments that row's `version` too — cascades are
    mutations, not bookkeeping."

    PRD 3.1: "Activation is where the community itself comes alive: alongside
    setting the contract's `status` to `ACTIVE` and incrementing its `version`, the
    community's `active_contract_id` is set to that contract and its `status` moves
    `ONBOARDING → ACTIVE`, incrementing the community's `version` in the same
    request."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_write_and_never_on_a_read
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    prop = fixtures.create_property(name="Cedar Ridge", unit_count=4)
    property_version = prop["version"]
    contract = fixtures.draft_contract(prop["id"])
    contract_version = contract["version"]
    assert fixtures.read_property(prop["id"])["version"] == property_version, (
        "creating a child contract did not bump the parent community"
    )

    fixtures.activate_contract(contract["id"])

    assert fixtures.read_contract(contract["id"])["version"] == contract_version + 1
    first_read = fixtures.read_property(prop["id"])
    second_read = fixtures.read_property(prop["id"])
    assert first_read["version"] == property_version + 1
    assert second_read["version"] == first_read["version"], "a read is not a write"
    assert second_read["status"] == "ACTIVE"
    assert second_read["active_contract_id"] == contract["id"]


# --------------------------------------------------------------------------
# One request, every derived total already reconciled
# --------------------------------------------------------------------------
def test_the_auto_fine_cascade_is_fully_visible_without_a_second_write():
    """The scan response and the reads that follow it need no reconciliation step.

    PRD 2.9: "A cascade is not an optional convenience: when this document says a
    transition cancels its children, that cancellation is part of the same request
    and its effects are visible in the very next read."

    PRD 2.9: "A resident's `fines_outstanding_cents` must equal the sum of
    `amount_cents` over that resident's fines whose `status` is `ASSESSED`,
    `DISPUTED` or `UPHELD`; and a property's `pending_fine_revenue_cents` must equal
    the sum of that quantity across all of the property's residents, regardless of
    each resident's own `status`."

    Design: Corner/consistency_model/derived_resident_and_property_totals_are_visible_in_the_same_response
    """
    world = fixtures.build_scan_ready_night(
        name="Cedar Ridge",
        unit_count=4,
        resident_units=(101,),
        resident_kwargs={101: {"move_in_date": "2026-08-01"}},
        service_date="2026-09-01",
    )
    resident_id = world["residents"][101]["id"]

    scan = validate_success(
        api_client.record_scan(
            world["route"]["id"],
            factories.scan_payload(
                resident_id,
                "TAGGED_NOT_SERVICED",
                "RECYCLING_BIN",
                non_compliance_type="RECYCLING_CONTAMINATION",
            ),
            make_valet_headers(world["contractor"]["id"]),
        ),
        expected_status=201,
    )

    assert scan["tag_status"] == "FINED", "the AUTO cascade is inside the same request"
    assert scan["offense_ordinal"] == 1
    fines = fixtures.list_fines({"scan_id": scan["id"]})
    assert len(fines) == 1
    assert fines[0]["amount_cents"] == 2500
    assert fines[0]["origin"] == "AUTO"
    assert_resident_ledger(
        fixtures.read_resident(resident_id),
        outstanding_cents=2500,
        assessed_this_period_cents=2500,
        collections_status="CURRENT",
    )
    prop = fixtures.read_property(world["property"]["id"])
    assert prop["pending_fine_revenue_cents"] == 2500
    assert prop["delinquent_resident_count"] == 0
