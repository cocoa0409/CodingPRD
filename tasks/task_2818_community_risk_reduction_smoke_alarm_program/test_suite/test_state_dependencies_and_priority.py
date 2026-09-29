"""Cross-aggregate state gates, and the order in which two simultaneously broken
rules are allowed to answer."""

from typing import Any, Dict

from test_helpers import factories as f
from test_helpers import get_success_data, validate_error
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_number_equals
from test_helpers.constants import (
    DeviceType,
    GrantStatus,
    HouseholdStatus,
    InstallStatus,
    LotStatus,
    PlacementLocation,
    PlanStatus,
    RiskTier,
    RouteStatus,
)
from test_helpers.fixtures import (
    arrive,
    assess_zone,
    book_visit,
    create_active_grant,
    create_assessed_zone,
    create_crew,
    create_grant,
    create_household,
    create_lot,
    create_partner,
    create_published_route,
    create_zone,
    defer_visit,
    deliver_education,
    pin_clock,
    read_grant,
    read_household,
    read_lot,
    read_visit,
    read_zone,
)
from test_helpers.test_users import COORDINATOR, OFFICER, make_crr_technician_headers


def test_01_a_route_cannot_be_planned_in_a_zone_that_has_never_been_scored(api):
    """An UNASSESSED zone has a null tier, so it is not targetable.

    PRD: "The named zone must be a `LEAF` zone whose `assessment_status` is
    `ASSESSED`, `TARGETED` or `SERVICE_ACTIVE` **and** whose `risk_tier` is `TIER_1`
    or `TIER_2`; a zone still at `UNASSESSED`, a zone whose `risk_tier` is null, and a
    zone that scored down into `TIER_3` are all rejected with
    `ERR_ZONE_NOT_TARGETABLE`."

    Design: Difficulty/cross_entity_state_dependency/route_creation_depends_on_riskzone_assessment_state
    """
    pin_clock(api)
    zone = create_zone(api)
    crew = create_crew(api)
    assert zone["assessment_status"] == "UNASSESSED"
    assert zone["risk_tier"] is None

    response = api.create_route(f.route_payload(zone["id"], crew["id"]), COORDINATOR)
    validate_error(response, ApiErrorId.ZONE_NOT_TARGETABLE, 409)


def test_02_scoring_the_zone_admits_the_identical_route_request(api):
    """The same payload succeeds once the zone carries a middle-tier score.

    PRD: "When the route being planned is the first route ever created for its zone,
    the zone advances `ASSESSED → TARGETED` and the zone's `version` increments by 1."

    Design: Difficulty/cross_entity_state_dependency/route_creation_depends_on_riskzone_assessment_state
    """
    pin_clock(api)
    zone = create_zone(api)
    crew = create_crew(api)
    validate_error(
        api.create_route(f.route_payload(zone["id"], crew["id"]), COORDINATOR),
        ApiErrorId.ZONE_NOT_TARGETABLE,
        409,
    )

    assessment = assess_zone(api, zone["id"], zone["version"])
    assert_number_equals(assessment["risk_score"], 54.52, "risk_score")
    assert assessment["risk_tier"] == RiskTier.TIER_2

    route = get_success_data(
        api.create_route(f.route_payload(zone["id"], crew["id"]), COORDINATOR), 201
    )
    assert route["status"] == RouteStatus.PLANNED

    scored = read_zone(api, zone["id"])
    assert scored["assessment_status"] == "TARGETED"
    assert scored["risk_tier"] == RiskTier.TIER_2


def test_03_a_lot_cannot_be_received_against_a_grant_still_in_draft(api):
    """Stock may not be booked in until the award is actually active.

    PRD: "A `GrantOfficer` records it with `funding_grant_id` - the referenced grant
    must be `ACTIVE`, or the request is rejected with `ERR_GRANT_NOT_ACTIVE`..."

    Design: Difficulty/cross_entity_state_dependency/device_lot_receipt_depends_on_partner_grant_activation_state
    """
    pin_clock(api)
    partner = create_partner(api)
    grant = create_grant(api, partner["id"], grant_code="G-DRAFT-1")
    assert grant["status"] == GrantStatus.DRAFT

    response = api.create_device_lot(f.device_lot_payload(grant["id"]), OFFICER)
    validate_error(response, ApiErrorId.GRANT_NOT_ACTIVE, 409)


def test_04_activating_the_grant_admits_the_byte_identical_lot_receipt(api):
    """Activation is the gate, and a fresh lot starts entirely on hand.

    PRD: "A new lot starts with `on_hand_qty` equal to `received_qty`, `reserved_qty`
    and `consumed_qty` at 0, and `status` `AVAILABLE`."

    Design: Difficulty/cross_entity_state_dependency/device_lot_receipt_depends_on_partner_grant_activation_state
    """
    pin_clock(api)
    partner = create_partner(api)
    grant = create_grant(api, partner["id"], grant_code="G-DRAFT-1")
    validate_error(
        api.create_device_lot(f.device_lot_payload(grant["id"]), OFFICER),
        ApiErrorId.GRANT_NOT_ACTIVE,
        409,
    )

    activated = get_success_data(api.activate_grant(grant["id"], OFFICER))
    assert activated["status"] == GrantStatus.ACTIVE
    assert activated["available_cents"] == 500000

    lot = get_success_data(
        api.create_device_lot(f.device_lot_payload(grant["id"]), OFFICER), 201
    )
    assert lot["status"] == LotStatus.AVAILABLE
    assert (lot["on_hand_qty"], lot["reserved_qty"], lot["consumed_qty"]) == (10, 0, 0)


def _two_household_zone(api) -> Dict[str, Any]:
    """One served household and one that was never booked, in the same zone."""
    pin_clock(api)
    zone = create_assessed_zone(api)
    crew = create_crew(api)
    served = create_household(api, zone["id"], address_line="1 Birch Road")
    queued = create_household(api, zone["id"], address_line="2 Birch Road")
    route = create_published_route(api, zone["id"], crew["id"], planned_slots=2)
    visit = book_visit(api, served["id"], route["id"])
    arrive(api, visit["id"], crew["id"], pre_existing_working_smoke_alarms=2)
    deliver_education(api, visit["id"], crew["id"])
    get_success_data(
        api.complete_visit(
            visit["id"], f.complete_payload(), make_crr_technician_headers(crew["id"])
        )
    )
    return {
        "zone": zone,
        "served": read_household(api, served["id"]),
        "queued": read_household(api, queued["id"]),
    }


def test_05_an_escape_plan_cannot_be_drafted_for_a_household_never_visited(api):
    """The version guard passes, so only the household's service state can refuse.

    PRD: "A `CanvassCoordinator` drafts an **escape plan** for a household that has
    reached the served stage - the household's `status` must be `VISIT_COMPLETED` or
    `REVISIT_REQUIRED`, and drafting for a household that has never got that far is
    rejected with `ERR_INVALID_HOUSEHOLD_STATE`."

    Design: Difficulty/cross_entity_state_dependency/escape_plan_drafting_depends_on_household_service_state
    """
    ctx = _two_household_zone(api)
    queued = ctx["queued"]
    assert queued["status"] == HouseholdStatus.INTAKE_QUEUED

    response = api.create_escape_plan(
        f.escape_plan_payload(queued["id"], queued["version"]), COORDINATOR
    )
    validate_error(response, ApiErrorId.INVALID_HOUSEHOLD_STATE, 409)
    assert response.json()["data"]["error_id"] != ApiErrorId.STALE_HOUSEHOLD_VERSION
    assert read_household(api, queued["id"])["status"] == HouseholdStatus.INTAKE_QUEUED


def test_06_the_same_draft_succeeds_for_the_household_that_was_served(api):
    """A served household accepts the plan, which starts as a first issue.

    PRD: "A new plan lands at `status` `DRAFT` with `reissue_count` at 0..."

    Design: Difficulty/cross_entity_state_dependency/escape_plan_drafting_depends_on_household_service_state
    """
    ctx = _two_household_zone(api)
    served = ctx["served"]
    assert served["status"] == HouseholdStatus.VISIT_COMPLETED

    plan = get_success_data(
        api.create_escape_plan(
            f.escape_plan_payload(served["id"], served["version"]), COORDINATOR
        ),
        201,
    )
    assert plan["status"] == PlanStatus.DRAFT
    assert plan["reissue_count"] == 0
    assert plan["household_id"] == served["id"]


def _closed_out_visit_with_a_broke_grant(api) -> Dict[str, Any]:
    """A visit already closed out as deferred, funded by a grant too poor to buy a
    single device: both the state rule and the fiscal rule are broken at once."""
    pin_clock(api)
    zone = create_assessed_zone(api)
    crew = create_crew(api)
    partner = create_partner(api)
    grant = create_active_grant(
        api,
        partner["id"],
        grant_code="G-LOW-1",
        authorized_cents=1000,
        allowed_device_types=[DeviceType.SMOKE_10YR],
        unit_rate_cents_by_type={DeviceType.SMOKE_10YR: 2195},
        reimbursement_pct=100.0,
        indirect_rate_pct=0.0,
        match_pct=0.0,
    )
    lot = create_lot(api, grant["id"], received_qty=5)
    household = create_household(api, zone["id"], address_line="8 Cedar Way")
    route = create_published_route(api, zone["id"], crew["id"], planned_slots=2)
    visit = book_visit(api, household["id"], route["id"])
    arrive(api, visit["id"], crew["id"])
    get_success_data(
        api.record_education(
            visit["id"],
            f.education_declined_payload(),
            make_crr_technician_headers(crew["id"]),
        )
    )
    defer_visit(api, visit["id"], crew["id"], deferral_reason="STOCK_UNAVAILABLE")
    return {"crew": crew, "grant": grant, "lot": lot, "visit": visit}


def test_07_the_visit_state_rule_answers_before_the_fiscal_rule(api):
    """A closed-out visit is refused with 409 even though the grant is also broke.

    PRD: "The visit must have `install_status` `SURVEYED` and must not be a
    `VIRTUAL_ASSESSMENT` appointment; a remote assessment cannot host a physical
    device."

    Design: Difficulty/priority_pair_validation_conflict/visit_state_check_precedes_grant_funds_check_on_installation
    """
    ctx = _closed_out_visit_with_a_broke_grant(api)
    assert read_grant(api, ctx["grant"]["id"])["available_cents"] == 1000

    response = api.create_installation(
        f.installation_payload(ctx["visit"]["id"], device_lot_id=ctx["lot"]["id"]),
        make_crr_technician_headers(ctx["crew"]["id"]),
    )
    validate_error(response, ApiErrorId.INVALID_VISIT_STATE, 409)
    assert response.json()["data"]["error_id"] != ApiErrorId.GRANT_FUNDS_EXHAUSTED


def test_08_the_refused_reservation_moves_neither_stock_nor_money(api):
    """Neither ledger may move on a rejected reservation.

    PRD: "On the lot, `reserved_qty` increments by 1 while `on_hand_qty` stays exactly
    where it was - a reserved unit is still physically on the shelf ... On the funding
    grant, `reserved_cents` increases by the installation's `reimbursable_cents`,
    `available_cents` decreases by the same amount..."

    Design: Difficulty/priority_pair_validation_conflict/visit_state_check_precedes_grant_funds_check_on_installation
    """
    ctx = _closed_out_visit_with_a_broke_grant(api)
    validate_error(
        api.create_installation(
            f.installation_payload(ctx["visit"]["id"], device_lot_id=ctx["lot"]["id"]),
            make_crr_technician_headers(ctx["crew"]["id"]),
        ),
        ApiErrorId.INVALID_VISIT_STATE,
        409,
    )

    lot = read_lot(api, ctx["lot"]["id"])
    assert (lot["on_hand_qty"], lot["reserved_qty"]) == (5, 0)
    grant = read_grant(api, ctx["grant"]["id"])
    assert grant["reserved_cents"] == 0
    assert grant["available_cents"] == 1000
    assert read_visit(api, ctx["visit"]["id"])["install_status"] == InstallStatus.INSTALL_DEFERRED


def _arrived_visit_with_both_lots(api) -> Dict[str, Any]:
    """A mid-survey visit with a smoke lot and a CO lot both available."""
    pin_clock(api)
    zone = create_assessed_zone(api)
    crew = create_crew(api)
    partner = create_partner(api)
    grant = create_active_grant(api, partner["id"])
    smoke_lot = create_lot(api, grant["id"])
    co_lot = create_lot(
        api,
        grant["id"],
        sku="CO-A",
        device_type=DeviceType.CO_ALARM,
        unit_cost_cents=2990,
        received_qty=5,
    )
    household = create_household(
        api, zone["id"], address_line="8 Cedar Way", fuel_burning_appliance=True
    )
    route = create_published_route(api, zone["id"], crew["id"], planned_slots=2)
    visit = book_visit(api, household["id"], route["id"])
    arrive(api, visit["id"], crew["id"])
    return {
        "crew": crew,
        "grant": grant,
        "smoke_lot": smoke_lot,
        "co_lot": co_lot,
        "visit": visit,
    }


def test_09_the_forbidden_location_answers_before_the_lot_family_mismatch(api):
    """A kitchen placement pointing at the wrong lot family gets the safety error.

    PRD: "The first layer rejects three locations outright, for every device family
    without exception: `KITCHEN`, `BATHROOM` and `GARAGE` are recognised request values
    that are always refused with `ERR_PLACEMENT_LOCATION_FORBIDDEN`, and consequently no
    stored installation ever holds one of them."

    Design: Difficulty/priority_pair_validation_conflict/placement_safety_check_precedes_lot_type_mismatch_check
    """
    ctx = _arrived_visit_with_both_lots(api)

    response = api.create_installation(
        f.installation_payload(
            ctx["visit"]["id"],
            device_type=DeviceType.SMOKE_10YR,
            placement_location=PlacementLocation.KITCHEN,
            device_lot_id=ctx["co_lot"]["id"],
        ),
        make_crr_technician_headers(ctx["crew"]["id"]),
    )
    validate_error(response, ApiErrorId.PLACEMENT_LOCATION_FORBIDDEN, 422)
    assert response.json()["data"]["error_id"] != ApiErrorId.LOT_TYPE_MISMATCH


def test_10_the_forbidden_placement_leaves_both_lots_and_the_grant_untouched(api):
    """The safety refusal happens before any lot or grant bookkeeping.

    PRD: "When `device_lot_id` is supplied it is used exactly as given, and its own
    `device_type` must equal the requested `device_type` - a mismatch is rejected with
    `ERR_LOT_TYPE_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/placement_safety_check_precedes_lot_type_mismatch_check
    """
    ctx = _arrived_visit_with_both_lots(api)
    validate_error(
        api.create_installation(
            f.installation_payload(
                ctx["visit"]["id"],
                device_type=DeviceType.SMOKE_10YR,
                placement_location=PlacementLocation.KITCHEN,
                device_lot_id=ctx["co_lot"]["id"],
            ),
            make_crr_technician_headers(ctx["crew"]["id"]),
        ),
        ApiErrorId.PLACEMENT_LOCATION_FORBIDDEN,
        422,
    )

    co_lot = read_lot(api, ctx["co_lot"]["id"])
    assert (co_lot["on_hand_qty"], co_lot["reserved_qty"]) == (5, 0)
    assert read_lot(api, ctx["smoke_lot"]["id"])["on_hand_qty"] == 10
    assert read_grant(api, ctx["grant"]["id"])["available_cents"] == 500000
