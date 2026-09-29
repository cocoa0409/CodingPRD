"""Two multi-entity cascades: a fine into delinquency, an escalation into suspension."""

from test_helpers import (
    api_client,
    assert_fine_amounts,
    assert_instant,
    assert_instants_equal,
    factories,
    fixtures,
    make_valet_headers,
    validate_success,
)


# --------------------------------------------------------------------------
# One scan -> fine -> resident balance -> community rollups
# --------------------------------------------------------------------------
def _one_prior_contamination_and_a_second_scannable_night(name="Laurel Court"):
    """2500 cents already on the ledger, with a live route waiting for scan two."""
    world = fixtures.build_active_community(
        name=name,
        unit_count=4,
        resident_units=(101,),
        resident_kwargs={101: {"move_in_date": "2026-08-01"}},
    )
    first_night, first_route = fixtures.add_scan_ready_night(world, "2026-09-01")
    fixtures.record_scan(
        first_route["id"],
        world["contractor"]["id"],
        world["residents"][101]["id"],
        scan_result="TAGGED_NOT_SERVICED",
        container_type="RECYCLING_BIN",
        non_compliance_type="RECYCLING_CONTAMINATION",
    )
    second_night, second_route = fixtures.add_scan_ready_night(world, "2026-09-02")
    world["first_night"] = first_night
    world["second_night"] = second_night
    world["second_route"] = second_route
    return world


def _second_contamination(world):
    return validate_success(
        api_client.record_scan(
            world["second_route"]["id"],
            factories.scan_payload(
                world["residents"][101]["id"],
                "TAGGED_NOT_SERVICED",
                "RECYCLING_BIN",
                "RECYCLING_CONTAMINATION",
            ),
            make_valet_headers(world["contractor"]["id"]),
        ),
        expected_status=201,
    )


def test_a_second_contamination_scan_writes_its_own_fine_in_the_same_request():
    """The scan opens a tag, prices it at the second-offence multiplier and fines it.

    PRD 3.6: "**Escalation.** `escalation_multiplier` is selected by the offence
    ordinal, with the ordinal first clamped down to a maximum of 3: a first
    offence multiplies by 0.5, a second by 1.5, and a third or any later one by
    2.0."

    Design: Difficulty/transitive_cascade/contamination_scan_cascades_through_fine_to_property_delinquency_rollup
    """
    world = _one_prior_contamination_and_a_second_scannable_night()

    scan = _second_contamination(world)

    assert scan["offense_ordinal"] == 2
    assert scan["tag_status"] == "FINED"
    fines = fixtures.list_fines({"scan_id": scan["id"]})
    assert len(fines) == 1
    assert_fine_amounts(
        fines[0],
        base_cents=5000,
        escalation_multiplier=1.5,
        amount_cents=7500,
        uncapped_amount_cents=7500,
    )
    assert fines[0]["origin"] == "AUTO"
    assert fines[0]["status"] == "ASSESSED"


def test_the_fine_pushes_the_resident_over_the_threshold_and_rolls_up_to_the_community():
    """Links three and four fire only because link two crossed 7500 cents.

    PRD 3.2: "`collections_status` reads `CURRENT` while
    `fines_outstanding_cents` is below the delinquency threshold of 7500 cents —
    that is, below seventy-five dollars of unresolved fines — and flips to
    `DELINQUENT` the moment the outstanding balance reaches or passes that
    threshold."

    Design: Difficulty/transitive_cascade/contamination_scan_cascades_through_fine_to_property_delinquency_rollup
    """
    world = _one_prior_contamination_and_a_second_scannable_night()
    resident_id = world["residents"][101]["id"]
    property_id = world["property"]["id"]
    before_resident = fixtures.read_resident(resident_id)
    before_property = fixtures.read_property(property_id)
    assert before_resident["fines_outstanding_cents"] == 2500
    assert before_resident["collections_status"] == "CURRENT"
    assert before_property["delinquent_resident_count"] == 0
    assert before_property["pending_fine_revenue_cents"] == 2500

    _second_contamination(world)

    after_resident = fixtures.read_resident(resident_id)
    assert after_resident["fines_outstanding_cents"] == 10000
    assert after_resident["collections_status"] == "DELINQUENT"
    after_property = fixtures.read_property(property_id)
    assert after_property["delinquent_resident_count"] == 1
    assert after_property["pending_fine_revenue_cents"] == 10000


# --------------------------------------------------------------------------
# The second escalation suspends the community, then cancels nights, then routes
# --------------------------------------------------------------------------
def _two_jams_with_the_first_escalated(name="Foxglove Park"):
    """Two unacknowledged jams past their deadline, one of them already escalated."""
    world = fixtures.build_active_community(
        name=name, unit_count=4, resident_units=(), with_contractor=True
    )
    night_one = fixtures.schedule_night(world["contract"]["id"], "2026-09-01")
    night_two = fixtures.schedule_night(world["contract"]["id"], "2026-09-02")
    route = fixtures.assign_route(
        night_two["id"], world["contractor"]["id"], 101, 104
    )
    first = fixtures.report_incident(
        world["property"]["id"], "JAM", "chute jammed on tower A"
    )
    second = fixtures.report_incident(
        world["property"]["id"], "JAM", "ram stalled on tower B"
    )
    fixtures.set_clock("2026-09-01T04:00:00Z")
    fixtures.escalate_incident(first["id"])
    world["night_one"] = night_one
    world["night_two"] = night_two
    world["route"] = route
    world["first_incident"] = first
    world["second_incident"] = second
    return world


def test_the_first_escalation_alone_leaves_the_community_active_and_its_nights_scheduled():
    """One jam raises the level to one, which is short of the suspension trigger.

    PRD 3.7: "The community's `escalation_level`, which is always the count of
    its incidents currently in `ESCALATED`, rises by one. If that new level
    reaches two and the community's `status` is `ACTIVE`, the community is forced
    `ACTIVE → SUSPENDED`."

    Design: Difficulty/transitive_cascade/second_escalation_suspends_property_and_cancels_nights_then_routes
    """
    world = _two_jams_with_the_first_escalated()

    prop = fixtures.read_property(world["property"]["id"])

    assert prop["escalation_level"] == 1
    assert prop["status"] == "ACTIVE"
    for night in fixtures.list_nights({"contract_id": world["contract"]["id"]}):
        assert night["verification_status"] == "SCHEDULED"
    assert fixtures.read_route(world["route"]["id"])["status"] == "ASSIGNED"
    assert fixtures.read_night(world["night_two"]["id"])["assigned_unit_coverage_count"] == 4


def test_the_second_escalation_suspends_the_community_and_cancels_every_night():
    """Level two forces the suspension, which cancels both scheduled nights.

    PRD 3.7: "That suspension in turn cancels every service night of the
    community's active contract whose `verification_status` is `SCHEDULED`,
    leaving each such night's `reschedule_action` null — this is not a reschedule
    and must not be recorded as one."

    Design: Difficulty/transitive_cascade/second_escalation_suspends_property_and_cancels_nights_then_routes
    """
    world = _two_jams_with_the_first_escalated()

    escalated = fixtures.escalate_incident(world["second_incident"]["id"])

    assert escalated["status"] == "ESCALATED"
    assert_instant(escalated["escalated_at"], "escalated_at")
    assert_instants_equal(
        escalated["escalated_at"], "2026-09-01T04:00:00.000Z", "escalated_at"
    )
    prop = fixtures.read_property(world["property"]["id"])
    assert prop["escalation_level"] == 2
    assert prop["status"] == "SUSPENDED"
    nights = fixtures.list_nights({"contract_id": world["contract"]["id"]})
    assert len(nights) == 2
    for night in nights:
        assert night["verification_status"] == "CANCELLED"
        assert night["reschedule_action"] is None


def test_the_night_cancellations_cascade_once_more_into_the_live_routes():
    """The assigned route is cancelled and the night's coverage falls back to zero.

    PRD 3.7: "And each of those night cancellations cascades once more: every
    route assignment of that night whose `status` is `ASSIGNED`, `ACCEPTED` or
    `IN_PROGRESS` moves to `CANCELLED`, and the night's
    `assigned_unit_coverage_count` is recomputed, necessarily to 0."

    Design: Difficulty/transitive_cascade/second_escalation_suspends_property_and_cancels_nights_then_routes
    """
    world = _two_jams_with_the_first_escalated()

    fixtures.escalate_incident(world["second_incident"]["id"])

    routes = fixtures.list_routes({"service_night_id": world["night_two"]["id"]})
    assert len(routes) == 1
    assert routes[0]["id"] == world["route"]["id"]
    assert routes[0]["status"] == "CANCELLED"
    night = fixtures.read_night(world["night_two"]["id"])
    assert night["assigned_unit_coverage_count"] == 0


# --------------------------------------------------------------------------
# escalation_level is a conserved count, and status is re-derived from it
# --------------------------------------------------------------------------
def _suspended_by_two_escalated_jams(name="Foxglove Park"):
    world = fixtures.build_active_community(
        name=name, unit_count=4, resident_units=(), with_contractor=False
    )
    night = fixtures.schedule_night(world["contract"]["id"], "2026-09-02")
    first = fixtures.report_incident(
        world["property"]["id"], "JAM", "chute jammed on tower A"
    )
    second = fixtures.report_incident(
        world["property"]["id"], "JAM", "ram stalled on tower B"
    )
    fixtures.set_clock("2026-09-01T04:00:00Z")
    fixtures.escalate_incident(first["id"])
    fixtures.escalate_incident(second["id"])
    world["night"] = night
    world["first_incident"] = first
    world["second_incident"] = second
    return world


def test_resolving_one_of_two_escalations_decrements_the_count_and_lifts_the_suspension():
    """The stored level tracks the live ESCALATED count, and status follows it.

    PRD 3.7: "Resolving from `ESCALATED` decrements `escalation_level` by one. If
    the decremented level is then below two and the community's `status` is
    `SUSPENDED`, the community is reinstated `SUSPENDED → ACTIVE`."

    Design: Difficulty/compensating_invariant/property_escalation_level_always_equals_live_escalated_incident_count
    """
    world = _suspended_by_two_escalated_jams()
    before = fixtures.read_property(world["property"]["id"])
    assert before["escalation_level"] == 2
    assert before["status"] == "SUSPENDED"

    resolved = fixtures.resolve_incident(
        world["second_incident"]["id"], "tower B ram replaced"
    )

    assert resolved["status"] == "RESOLVED"
    assert fixtures.read_incident(world["first_incident"]["id"])["status"] == "ESCALATED"
    after = fixtures.read_property(world["property"]["id"])
    assert after["escalation_level"] == 1
    assert after["status"] == "ACTIVE"
    incidents = fixtures.list_incidents({"property_id": world["property"]["id"]})
    assert sorted(incident["status"] for incident in incidents) == [
        "ESCALATED",
        "RESOLVED",
    ]


def test_reinstatement_does_not_resurrect_the_nights_the_suspension_cancelled():
    """The compensation is deliberately partial: the counter recovers, the night does not.

    PRD 3.7: "Reinstatement is deliberately **not** symmetrical with suspension:
    the service nights and route assignments that the suspension cancelled are
    gone for good and are never restored."

    Design: Difficulty/compensating_invariant/property_escalation_level_always_equals_live_escalated_incident_count
    """
    world = _suspended_by_two_escalated_jams()
    assert fixtures.read_night(world["night"]["id"])["verification_status"] == "CANCELLED"

    fixtures.resolve_incident(world["second_incident"]["id"], "tower B ram replaced")

    night = fixtures.read_night(world["night"]["id"])
    assert night["verification_status"] == "CANCELLED"
    assert fixtures.read_property(world["property"]["id"])["status"] == "ACTIVE"
