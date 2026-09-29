"""Haul manifests: the roll-up window, the seal's five checks and the cap boundary."""

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_disposal_site,
    assert_waste_manifest,
    fixtures as fx,
    validate_error,
    validate_success,
)

DRIVER = TEST_USERS["driver_operator_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]

BLACKWATER = "BLACKWATER"
HAUL_DATE = "2026-08-10"


def _seal(manifest_id, expected_route_version, seal_note=None):
    """Raw seal call so a refusal can be inspected."""
    payload = {"expected_route_version": expected_route_version}
    if seal_note is not None:
        payload["seal_note"] = seal_note
    return api_client.seal_waste_manifest(manifest_id, payload, DRIVER)


def _thirteen_unit_route_with_a_seven_hundred_gallon_haul(route_code):
    """A 13-unit Monday route with one SERVICED visit reporting 700 gallons."""
    env = fx.setup_scheduled_contract(
        shape=fx.THIRTEEN_UNIT,
        route_code=route_code,
        truck_capacity_units=20,
        clock=fx.SECOND_MONDAY_EARLY,
        legal_name="Copperfield Sitework",
        site_label="Copperfield Phase 2",
        authority_ref="PL-7101",
        authority_decision_ref="AD-7101",
        site_overrides={
            "jurisdiction_code": "TX-TR-CITY",
            "access_class": "OPEN_LOT",
            "gate_open_minute": 360,
            "gate_close_minute": 1080,
            "max_truck_length_ft": 40,
        },
    )
    visit = fx.plan_visit(env["schedule"]["id"], HAUL_DATE, 480, 540)
    env["visit"] = fx.service_visit_fully(visit["id"], 700)
    return env


def _two_facilities_one_gallon_apart():
    """The same 700-gallon load offered to a 700-cap and a 699-cap facility."""
    env = _thirteen_unit_route_with_a_seven_hundred_gallon_haul("RT-MON-71")
    env["facility_at_cap"] = fx.register_disposal_site(
        "DS-700",
        daily_gallon_cap=700,
        accepted_waste_classes=[BLACKWATER],
        status="ACCEPTING",
    )
    env["facility_one_short"] = fx.register_disposal_site(
        "DS-699",
        daily_gallon_cap=699,
        accepted_waste_classes=[BLACKWATER],
        status="ACCEPTING",
    )
    env["manifest_at_cap"] = fx.open_manifest(
        env["route"]["id"], env["facility_at_cap"]["id"], HAUL_DATE, BLACKWATER
    )
    env["manifest_one_short"] = fx.open_manifest(
        env["route"]["id"], env["facility_one_short"]["id"], HAUL_DATE, BLACKWATER
    )
    env["route_version"] = fx.read_route(env["route"]["id"])["version"]
    return env


class TestDisposalCapBoundary:
    """700 gallons against a 700-gallon cap and against a 699-gallon cap."""

    def test_01_one_gallon_past_the_cap_is_refused_and_commits_nothing(self):
        """699 cannot take 700: the seal is refused and the facility stays at zero.

        PRD 3.7: "The cap gate, however, is keyed on the `manifest_date` of the
        manifest being sealed rather than on today: the already-committed gallons for
        that date — excluding the manifest now being sealed — plus that manifest's own
        `gallons_total` must not strictly exceed the facility's `daily_gallon_cap`."
        PRD 3.7: "A load that lands exactly on the cap is accepted; only a load that
        pushes the total strictly past it is refused, with `ERR_DISPOSAL_CAP_EXCEEDED`
        (HTTP 422)."
        PRD 3.7: "Manifests still `OPEN` never consume allowance."

        Design: Difficulty/boundary_precision_check/disposal_daily_cap_boundary_accepts_load_at_cap_and_rejects_one_gallon_over
        """
        env = _two_facilities_one_gallon_apart()

        assert env["visit"]["state"] == "SERVICED"
        assert env["visit"]["gallons_pumped"] == 700
        assert_waste_manifest(env["manifest_one_short"])
        assert env["manifest_one_short"]["gallons_total"] == 700
        assert env["manifest_at_cap"]["gallons_total"] == 700
        assert env["facility_one_short"]["daily_gallon_cap"] == 699
        assert env["facility_one_short"]["committed_gallons_today"] == 0

        validate_error(
            _seal(
                env["manifest_one_short"]["id"],
                env["route_version"],
                "one gallon over the 699 cap",
            ),
            "ERR_DISPOSAL_CAP_EXCEEDED",
            422,
        )

        refused = fx.read_manifest(env["manifest_one_short"]["id"])
        assert refused["state"] == "OPEN"
        assert refused["gallons_total"] == 700

        facility = fx.read_disposal_site(env["facility_one_short"]["id"])
        assert_disposal_site(facility)
        assert facility["committed_gallons_today"] == 0

        assert fx.read_route(env["route"]["id"])["version"] == env["route_version"]

    def test_02_a_load_landing_exactly_on_the_cap_seals_and_consumes_it_whole(self):
        """700 fits a 700 cap: SEALED at 700, committed 700, and the route version moves once.

        PRD 3.7: "A load that lands exactly on the cap is accepted; only a load that
        pushes the total strictly past it is refused, with `ERR_DISPOSAL_CAP_EXCEEDED`
        (HTTP 422)."
        PRD 3.7: "A successful seal freezes `gallons_total` at its rolled-up value,
        recomputes the facility's `committed_gallons_today`, and increments the route's
        `version` by one — which is what makes a second seal on the same route, replayed
        with the same `expected_route_version`, fail."
        PRD 3.7: "For any facility and calendar date, the gallons already committed there
        are the sum of `gallons_total` over the manifests at that facility whose
        `manifest_date` is that date and whose `state` is `SEALED` or `ACCEPTED`."

        Design: Difficulty/boundary_precision_check/disposal_daily_cap_boundary_accepts_load_at_cap_and_rejects_one_gallon_over
        """
        env = _two_facilities_one_gallon_apart()
        assert env["facility_at_cap"]["daily_gallon_cap"] == 700

        validate_error(
            _seal(env["manifest_one_short"]["id"], env["route_version"]),
            "ERR_DISPOSAL_CAP_EXCEEDED",
            422,
        )

        sealed = validate_success(
            _seal(
                env["manifest_at_cap"]["id"],
                env["route_version"],
                "exactly on the 700 cap",
            )
        )
        assert sealed["state"] == "SEALED"
        assert sealed["gallons_total"] == 700

        at_cap = fx.read_disposal_site(env["facility_at_cap"]["id"])
        assert at_cap["committed_gallons_today"] == 700
        assert at_cap["committed_gallons_today"] == at_cap["daily_gallon_cap"]

        one_short = fx.read_disposal_site(env["facility_one_short"]["id"])
        assert one_short["committed_gallons_today"] == 0

        assert fx.read_route(env["route"]["id"])["version"] == env["route_version"] + 1


def _one_closed_and_one_open_facility():
    """Two roomy facilities differing only in `status`, over one identical load."""
    env = _thirteen_unit_route_with_a_seven_hundred_gallon_haul("RT-MON-72")
    env["facility_closed"] = fx.register_disposal_site(
        "DS-CLOSED",
        daily_gallon_cap=5000,
        accepted_waste_classes=[BLACKWATER],
        status="CLOSED",
    )
    env["facility_open"] = fx.register_disposal_site(
        "DS-OPEN",
        daily_gallon_cap=5000,
        accepted_waste_classes=[BLACKWATER],
        status="ACCEPTING",
    )
    env["manifest_closed"] = fx.open_manifest(
        env["route"]["id"], env["facility_closed"]["id"], HAUL_DATE, BLACKWATER
    )
    env["manifest_open"] = fx.open_manifest(
        env["route"]["id"], env["facility_open"]["id"], HAUL_DATE, BLACKWATER
    )
    env["route_version"] = fx.read_route(env["route"]["id"])["version"]
    return env


class TestSealDependsOnFacilityStatus:
    """One manifest depends on another entity's status: the DisposalSite's."""

    def test_03_a_closed_facility_refuses_the_seal_of_an_otherwise_perfect_manifest(self):
        """Ample cap, accepted class, a SERVICED visit — and still refused for CLOSED.

        PRD 3.7: "it must clear five checks after the version match, in the precedence
        order of §2.11: the manifest must be `OPEN`; the receiving facility's `status`
        must be `ACCEPTING` rather than `CLOSED`, otherwise `ERR_DISPOSAL_SITE_CLOSED`
        (HTTP 409)"
        PRD 3.7: "Manifests still `OPEN` never consume allowance."

        Design: Difficulty/cross_entity_state_dependency/manifest_seal_depends_on_disposal_site_status_accepting
        """
        env = _one_closed_and_one_open_facility()

        assert env["visit"]["state"] == "SERVICED"
        assert env["manifest_closed"]["gallons_total"] == 700
        assert env["manifest_open"]["gallons_total"] == 700
        assert env["facility_closed"]["status"] == "CLOSED"
        assert env["facility_open"]["status"] == "ACCEPTING"
        assert env["facility_closed"]["daily_gallon_cap"] == 5000

        body = validate_error(
            _seal(env["manifest_closed"]["id"], env["route_version"]),
            "ERR_DISPOSAL_SITE_CLOSED",
            409,
        )
        assert body["error_id"] != "ERR_DISPOSAL_CAP_EXCEEDED"

        refused = fx.read_manifest(env["manifest_closed"]["id"])
        assert refused["state"] == "OPEN"
        assert fx.read_disposal_site(
            env["facility_closed"]["id"]
        )["committed_gallons_today"] == 0

    def test_04_the_identical_load_seals_at_the_accepting_twin(self):
        """The only difference is `status`, and the refused seal left the token unspent.

        PRD 3.7: "the receiving facility's `status` must be `ACCEPTING` rather than
        `CLOSED`, otherwise `ERR_DISPOSAL_SITE_CLOSED` (HTTP 409)"
        PRD 3.7: "A successful seal freezes `gallons_total` at its rolled-up value,
        recomputes the facility's `committed_gallons_today`, and increments the route's
        `version` by one — which is what makes a second seal on the same route, replayed
        with the same `expected_route_version`, fail."

        Design: Difficulty/cross_entity_state_dependency/manifest_seal_depends_on_disposal_site_status_accepting
        """
        env = _one_closed_and_one_open_facility()

        validate_error(
            _seal(env["manifest_closed"]["id"], env["route_version"]),
            "ERR_DISPOSAL_SITE_CLOSED",
            409,
        )

        sealed = validate_success(
            _seal(env["manifest_open"]["id"], env["route_version"])
        )
        assert sealed["state"] == "SEALED"
        assert sealed["gallons_total"] == 700

        assert fx.read_disposal_site(
            env["facility_open"]["id"]
        )["committed_gallons_today"] == 700
        assert fx.read_route(env["route"]["id"])["version"] == env["route_version"] + 1


class TestGallonsRollUp:
    """The roll-up filters on visit state and on the manifest's own date."""

    def test_05_only_serviced_visits_on_the_manifests_own_date_roll_up(self):
        """400 at open, 700 once the second stop completes, 0 for next Monday's manifest.

        PRD 3.7: "It is the sum of `gallons_pumped` over the service visits whose
        `route_id` equals the manifest's route and whose `scheduled_date` equals the
        manifest's `manifest_date` and whose `state` is `SERVICED`."
        PRD 3.7: "Visits in `PLANNED`, `EN_ROUTE`, `MISSED`, `CANCELLED` or
        `RERUN_SCHEDULED` contribute nothing."
        PRD 3.7: "The roll-up is computed when the manifest is opened, from whatever
        visits have already reached `SERVICED`, and it is refreshed on every subsequent
        completion on the same route and date — but only while the manifest is still
        `OPEN`."

        Design: Corner/calculations/manifest_gallons_total_counts_only_serviced_visits_on_the_matching_route_and_date
        """
        env = fx.setup_scheduled_contract(
            shape=fx.THIRTEEN_UNIT,
            route_code="RT-MON-52",
            truck_capacity_units=20,
            window_start_minute=480,
            window_end_minute=660,
            clock=fx.SECOND_MONDAY_EARLY,
            legal_name="Saltmarsh Utilities",
            site_label="Saltmarsh Trunk Line",
            authority_ref="PL-10401",
            authority_decision_ref="AD-10401",
            site_overrides={
                "jurisdiction_code": "MD-BA-CITY",
                "access_class": "OPEN_LOT",
                "gate_open_minute": 360,
                "gate_close_minute": 1080,
                "max_truck_length_ft": 40,
            },
        )
        assert env["schedule"]["units_on_route"] == 13

        facility = fx.register_disposal_site(
            "DS-52",
            daily_gallon_cap=5000,
            accepted_waste_classes=[BLACKWATER],
            status="ACCEPTING",
        )

        visit_a = fx.plan_visit(env["schedule"]["id"], HAUL_DATE, 480, 540)
        visit_b = fx.plan_visit(env["schedule"]["id"], HAUL_DATE, 560, 620)
        assert visit_b["state"] == "PLANNED"

        serviced_a = fx.service_visit_fully(visit_a["id"], 400)
        assert serviced_a["state"] == "SERVICED"
        assert serviced_a["gallons_pumped"] == 400
        assert serviced_a["units_serviced"] == 13

        manifest = fx.open_manifest(
            env["route"]["id"], facility["id"], HAUL_DATE, BLACKWATER
        )
        assert manifest["state"] == "OPEN"
        assert manifest["gallons_total"] == 400

        serviced_b = fx.service_visit_fully(visit_b["id"], 300)
        assert serviced_b["state"] == "SERVICED"

        refreshed = fx.read_manifest(manifest["id"])
        assert refreshed["gallons_total"] == 700
        assert refreshed["state"] == "OPEN"

        next_week = fx.open_manifest(
            env["route"]["id"], facility["id"], "2026-08-17", BLACKWATER
        )
        assert next_week["id"] != manifest["id"]
        assert next_week["route_id"] == manifest["route_id"]
        assert next_week["manifest_date"] == "2026-08-17"
        assert next_week["gallons_total"] == 0


class TestSealCheckPrecedence:
    """Two seal checks are violated at once; the accepted-class rule reports first."""

    def test_06_the_accepted_class_check_outranks_the_serviced_visit_check(self):
        """A GREYWATER-only facility reports the class error; its twin reports no visits.

        PRD 3.7: "the manifest's `waste_class` must be a member of that facility's
        `accepted_waste_classes`, otherwise `ERR_DISPOSAL_CLASS_NOT_ACCEPTED` (HTTP 422);
        at least one visit must exist on the manifest's route and date in `state`
        `SERVICED`, otherwise the roll-up input set is empty and the seal is refused with
        `ERR_MANIFEST_NO_SERVICED_VISITS` (HTTP 422)"
        PRD 2.11: "When several rules could reject the same request, the outcome is fully
        determined: the service evaluates checks in the fixed order below and returns the
        first failure it finds."

        Design: Corner/validations/manifest_seal_prefers_the_waste_class_check_over_the_serviced_visit_check
        """
        env = fx.setup_scheduled_contract(
            shape=fx.THIRTEEN_UNIT,
            route_code="RT-MON-107",
            truck_capacity_units=20,
            clock=fx.SECOND_MONDAY_EARLY,
            legal_name="Fernbrook Sanitation",
            site_label="Fernbrook Line 4",
            authority_ref="PL-11101",
            authority_decision_ref="AD-11101",
            site_overrides={
                "jurisdiction_code": "WA-KI-CITY",
                "access_class": "OPEN_LOT",
                "gate_open_minute": 360,
                "gate_close_minute": 1080,
                "max_truck_length_ft": 40,
            },
        )
        facility_x = fx.register_disposal_site(
            "DS-X",
            daily_gallon_cap=5000,
            accepted_waste_classes=["GREYWATER"],
            status="ACCEPTING",
        )
        facility_y = fx.register_disposal_site(
            "DS-Y",
            daily_gallon_cap=5000,
            accepted_waste_classes=[BLACKWATER, "GREYWATER"],
            status="ACCEPTING",
        )
        assert facility_x["accepted_waste_classes"] == ["GREYWATER"]
        assert facility_x["committed_gallons_today"] == 0

        visit = fx.plan_visit(env["schedule"]["id"], HAUL_DATE, 480, 540)
        assert visit["state"] == "PLANNED"

        manifest_x = fx.open_manifest(
            env["route"]["id"], facility_x["id"], HAUL_DATE, BLACKWATER
        )
        manifest_y = fx.open_manifest(
            env["route"]["id"], facility_y["id"], HAUL_DATE, BLACKWATER
        )
        assert manifest_x["gallons_total"] == 0

        route_version = fx.read_route(env["route"]["id"])["version"]

        validate_error(
            _seal(manifest_x["id"], route_version),
            "ERR_DISPOSAL_CLASS_NOT_ACCEPTED",
            422,
        )
        validate_error(
            _seal(manifest_y["id"], route_version),
            "ERR_MANIFEST_NO_SERVICED_VISITS",
            422,
        )

        assert fx.read_manifest(manifest_x["id"])["state"] == "OPEN"
        assert fx.read_manifest(manifest_y["id"])["state"] == "OPEN"
        assert fx.read_disposal_site(
            facility_x["id"]
        )["committed_gallons_today"] == 0
        assert fx.read_route(env["route"]["id"])["version"] == route_version


class TestAcceptanceGating:
    """Countersigning is reachable only from SEALED, and it never double-counts."""

    def test_07_accept_is_refused_from_open_and_succeeds_once_the_manifest_is_sealed(self):
        """OPEN cannot be accepted; the seal commits 380 gallons and the accept adds none.

        PRD 3.7: "Facility acceptance is the `ComplianceOfficer`'s countersignature and
        advances `SEALED → ACCEPTED`, with an optional `acceptance_note`."
        PRD 3.7: "Acceptance recomputes the facility's `committed_gallons_today`, though
        the value will not move, because both `SEALED` and `ACCEPTED` manifests are
        already inside the committed input set."
        PRD 3.7: "A successful seal freezes `gallons_total` at its rolled-up value,
        recomputes the facility's `committed_gallons_today`, and increments the route's
        `version` by one — which is what makes a second seal on the same route, replayed
        with the same `expected_route_version`, fail."

        Design: Corner/endpoints/manifest_accept_is_allowed_only_from_the_sealed_state
        """
        env = fx.setup_serviced_visit_with_manifest(
            gallons_pumped=380,
            disposal_site_code="DS-ASH",
            daily_gallon_cap=5000,
            accepted_waste_classes=[BLACKWATER],
            shape=fx.SEVEN_UNIT,
            route_code="RT-MON-129",
            truck_capacity_units=20,
            legal_name="Ashgrove Sanitation",
            site_label="Ashgrove Pad",
            authority_ref="PL-11801",
            authority_decision_ref="AD-11801",
            site_overrides={
                "jurisdiction_code": "OR-MU-CITY",
                "access_class": "OPEN_LOT",
                "gate_open_minute": 360,
                "gate_close_minute": 1080,
                "max_truck_length_ft": 40,
            },
        )
        assert env["visit"]["state"] == "SERVICED"
        assert env["manifest"]["state"] == "OPEN"
        assert env["manifest"]["gallons_total"] == 380

        facility_id = env["disposal_site"]["id"]
        manifest_id = env["manifest"]["id"]
        route_version = env["route_version_before_seal"]

        validate_error(
            api_client.accept_waste_manifest(
                manifest_id, OFFICER, {"acceptance_note": "too early"}
            ),
            "ERR_INVALID_STATE_TRANSITION",
            409,
        )
        assert fx.read_manifest(manifest_id)["state"] == "OPEN"
        assert fx.read_disposal_site(
            facility_id, OFFICER
        )["committed_gallons_today"] == 0

        sealed = validate_success(_seal(manifest_id, route_version))
        assert sealed["state"] == "SEALED"
        assert sealed["gallons_total"] == 380
        assert fx.read_disposal_site(
            facility_id, OFFICER
        )["committed_gallons_today"] == 380

        accepted = validate_success(
            api_client.accept_waste_manifest(
                manifest_id, OFFICER, {"acceptance_note": "weighed in at the gate"}
            )
        )
        assert accepted["state"] == "ACCEPTED"
        assert accepted["gallons_total"] == 380
        assert fx.read_disposal_site(
            facility_id, OFFICER
        )["committed_gallons_today"] == 380

        assert fx.read_route(env["route"]["id"])["version"] == route_version + 1
