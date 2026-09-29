"""Endpoint surfaces: read round trips, computed reads, action verbs and cross-links."""

from test_helpers import (
    BASIS_METERED_POUR,
    CELLAR,
    CHANNEL_EVENT,
    COMPLIANCE,
    CONTAINER_PINT_16OZ,
    DESTINATION_TAPROOM,
    ERR_EVENT_PERMIT_NOT_APPROVED,
    ERR_PERMIT_TRANSITION_INVALID,
    KEG_DEPLOYED,
    KEG_FILLED,
    KEG_SIZE_HALF_BBL,
    LICENSE_SELF_DISTRIBUTION,
    LICENSE_WHOLESALER_ONLY,
    MOVEMENT_DEPLOY_EVENT,
    NOTICE_ACTIVE,
    PACKAGE_HALF_BBL_KEG,
    PERMIT_APPROVED,
    PERMIT_DECISION_APPROVED,
    PERMIT_DECISION_INFO_REQUESTED,
    PERMIT_FESTIVAL,
    PERMIT_INFO_REQUESTED,
    PERMIT_SUBMITTED,
    REGULATOR,
    SCOPE_ALL_BRANDS,
    TANK_ACTION_RETURN_TO_SERVICE,
    TANK_ACTION_TAKE_OUT_OF_SERVICE,
    TANK_IDLE,
    TANK_OUT_OF_SERVICE,
    TANK_TYPE_BRITE,
    TANK_TYPE_FERMENTER,
    TAPROOM,
    assert_bbl,
    assert_instant_equals,
    assert_pagination_meta,
    keg_movement_payload,
    permit_decision_payload,
    pour_payload,
    tank_service_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    bootstrap_brewery,
    create_active_appointment,
    create_completed_run,
    create_conditioning_batch,
    create_exempt_beer,
    create_filled_keg,
    create_license,
    create_tank,
    create_tapped_keg,
    draft_and_file_report,
    draft_permit,
    set_clock,
    submit_permit,
)

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
EVENT_WINDOW_START = "2026-08-01T00:00:00Z"
EVENT_WINDOW_END = "2026-08-02T00:00:00Z"
INFO_NOTE = "supply the venue's dispense plan"


def _licensed_taproom_beer(api, venue_state_code="OR"):
    """An exempt brand, a licence covering the venue state, and a filled half barrel."""
    beer = create_exempt_beer(
        api, name="Ridgeline IPA", abv_pct=6.8, price_per_bbl_cents=42000
    )
    create_license(
        api,
        venue_state_code,
        LICENSE_SELF_DISTRIBUTION,
        annual_barrel_cap=1000.00,
        franchise_state=False,
        effective_from_utc="2026-01-01T00:00:00Z",
        expires_at_utc="2027-01-01T00:00:00Z",
    )
    return beer


def _taproom_run(api, beer_id):
    tank = create_tank(api, code="FV-01", capacity_bbl=30.00)
    batch = create_conditioning_batch(
        api,
        beer_id,
        tank["id"],
        actual_yield_bbl=16.000,
        batch_code="B-1001",
        planned_volume_bbl=16.00,
        brew_start_utc="2026-08-01T06:00:00Z",
        brew_end_utc="2026-08-08T06:00:00Z",
    )
    return create_completed_run(
        api,
        batch["id"],
        package_type=PACKAGE_HALF_BBL_KEG,
        destination=DESTINATION_TAPROOM,
        units_planned=10,
        run_code="R-TAP-1",
    )


class TestTankReadSurface:
    def test_a_registered_vessel_is_reachable_by_id_and_by_type_filter(self, api):
        """The read surface is the only surface, and the filter excludes the brite tank.

        PRD §3.2: "A new vessel opens with `status` of `IDLE`, a `cip_cycle_count`
        of 0, a null `last_cip_utc`, and a null `occupying_batch_id`."

        PRD §2.10: "Tanks may be filtered by `status` or `tank_type`."

        Design: Corner/endpoints/tank_create_read_and_filtered_list_round_trip
        """
        bootstrap_brewery(api)
        fermenter = create_tank(
            api, code="FV-01", tank_type=TANK_TYPE_FERMENTER, capacity_bbl=30.00
        )
        brite = create_tank(
            api, code="BT-01", tank_type=TANK_TYPE_BRITE, capacity_bbl=20.00
        )

        stored = validate_success(api.get_tank(fermenter["id"], CELLAR))
        filtered, filtered_meta = validate_paginated(
            api.list_tanks(
                TAPROOM, {"tank_type": TANK_TYPE_FERMENTER, "limit": 10, "offset": 0}
            )
        )

        assert stored["id"] == fermenter["id"]
        assert stored["code"] == "FV-01"
        assert stored["tank_type"] == TANK_TYPE_FERMENTER
        assert_bbl(stored["capacity_bbl"], 30.00, "capacity_bbl")
        assert stored["status"] == TANK_IDLE
        assert stored["cip_cycle_count"] == 0
        assert stored["last_cip_utc"] is None
        assert stored["occupying_batch_id"] is None
        assert len(filtered) == 1
        assert filtered[0]["id"] == fermenter["id"]
        assert_pagination_meta(
            filtered_meta, total_count=1, has_more=False, limit=10, offset=0
        )
        assert brite["id"] not in [row["id"] for row in filtered]
        _, all_meta = validate_paginated(api.list_tanks(CELLAR))
        assert all_meta["total_count"] == 2


class TestTankServiceActions:
    def test_a_vessel_leaves_service_and_returns_without_recording_a_wash(self, api):
        """One endpoint drives two edges, and neither is a clean-in-place.

        PRD §3.2: "`TAKE_OUT_OF_SERVICE` is legal only from `IDLE` and moves the
        vessel to `OUT_OF_SERVICE`; `RETURN_TO_SERVICE` is legal only from
        `OUT_OF_SERVICE` and returns it to `IDLE`."

        PRD §3.2: "Each of the three increments the tank's `version` by 1."

        Design: Corner/endpoints/tank_taken_out_of_service_and_returned_round_trips_through_idle
        """
        bootstrap_brewery(api)
        tank = create_tank(api, code="FV-01", capacity_bbl=30.00)
        version_when_idle = tank["version"]

        withdrawn = validate_success(
            api.service_tank(
                tank["id"],
                tank_service_payload(TANK_ACTION_TAKE_OUT_OF_SERVICE),
                CELLAR,
            )
        )
        assert withdrawn["status"] == TANK_OUT_OF_SERVICE
        assert withdrawn["cip_cycle_count"] == 0
        assert withdrawn["last_cip_utc"] is None

        returned = validate_success(
            api.service_tank(
                tank["id"], tank_service_payload(TANK_ACTION_RETURN_TO_SERVICE), CELLAR
            )
        )

        assert returned["status"] == TANK_IDLE
        assert returned["cip_cycle_count"] == 0
        assert returned["last_cip_utc"] is None
        assert returned["occupying_batch_id"] is None
        assert returned["version"] == version_when_idle + 2
        stored = validate_success(api.get_tank(tank["id"], CELLAR))
        assert stored["status"] == TANK_IDLE
        assert stored["cip_cycle_count"] == 0
        assert stored["version"] == version_when_idle + 2


class TestBreweryComputedRead:
    def test_the_brewery_read_derives_its_ytd_position_and_franchise_locks(self, api):
        """Three filed pints move taproom barrels; only the appointed state is locked.

        PRD §3.1: "From them the brewery's three read-only aggregates are derived:
        `taproom_bbl_ytd` is `carry_in_taproom_bbl` plus the sum of `taproom_bbl`
        over every excise report whose `state` is `FILED` (reports in `SUPERSEDED`
        are excluded, as are drafts); `distribution_bbl_ytd` is
        `carry_in_distribution_bbl` plus the sum of `distribution_bbl` over the same
        filed set; and `total_bbl_ytd` is the sum of those two."

        PRD §3.1: "The brewery row also exposes `franchise_locked_state_codes`: the
        list of `state_code` values, sorted ascending, of every state licence that
        has at least one distributor appointment whose `state` is `ACTIVE`."

        Design: Corner/endpoints/brewery_read_returns_the_derived_ytd_position_and_franchise_locks
        """
        bootstrap_brewery(api, home_state_code="OR")
        beer = create_exempt_beer(
            api, name="Ridgeline IPA", abv_pct=6.8, price_per_bbl_cents=42000
        )
        run = _taproom_run(api, beer["id"])
        keg = create_tapped_keg(api, run["id"], KEG_SIZE_HALF_BBL, keg_serial="KEG-0001")
        for _ in range(3):
            validate_success(
                api.create_taproom_pour(
                    pour_payload(keg["id"], CONTAINER_PINT_16OZ, price_cents=700), TAPROOM
                ),
                201,
            )
        # §3.8: "The period must have closed: the logical clock must have reached
        # or passed `period_end_utc`", so the clock is advanced to the period's
        # exclusive end before the return is filed.
        set_clock(api, "2026-09-01T00:00:00Z")
        filed = draft_and_file_report(
            api,
            period_start_utc="2026-08-01T00:00:00Z",
            period_end_utc="2026-09-01T00:00:00Z",
            taproom_basis=BASIS_METERED_POUR,
        )
        washington = create_license(
            api,
            "WA",
            LICENSE_WHOLESALER_ONLY,
            annual_barrel_cap=0.00,
            franchise_state=True,
            effective_from_utc="2026-01-01T00:00:00Z",
            expires_at_utc="2027-01-01T00:00:00Z",
        )
        create_license(
            api,
            "ID",
            LICENSE_SELF_DISTRIBUTION,
            annual_barrel_cap=1000.00,
            franchise_state=False,
            effective_from_utc="2026-01-01T00:00:00Z",
            expires_at_utc="2027-01-01T00:00:00Z",
        )
        create_active_appointment(api, washington["id"], brand_scope=SCOPE_ALL_BRANDS)

        brewery = validate_success(api.get_brewery(REGULATOR))

        assert_bbl(filed["taproom_bbl"], 0.012, "report taproom_bbl")
        assert brewery["notice_status"] == NOTICE_ACTIVE
        assert_instant_equals(
            brewery["notice_effective_utc"], DEFAULT_CLOCK, "notice_effective_utc"
        )
        assert_bbl(brewery["taproom_bbl_ytd"], 0.012, "taproom_bbl_ytd")
        assert_bbl(brewery["distribution_bbl_ytd"], 0.000, "distribution_bbl_ytd")
        assert_bbl(brewery["total_bbl_ytd"], 0.012, "total_bbl_ytd")
        assert brewery["franchise_locked_state_codes"] == ["WA"]


class TestEventDeploymentLinksThePermit:
    def test_the_event_channel_opens_only_once_the_permit_is_approved(self, api):
        """The same movement is refused, then accepted, on the permit's own state.

        PRD §3.4: "A `DEPLOY_EVENT` movement is its sibling: likewise legal only
        from `FILLED`, likewise moving the keg to `DEPLOYED`, but with
        `deployment_channel` set to `EVENT`, and gated on a different authority — the
        filled beer must be the featured brand of an event permit whose `state` is
        `APPROVED` and whose event window covers the current logical instant,
        identified by the optional `event_permit_id` carried with the movement."

        PRD §3.9: "Once a permit reaches `APPROVED`, it unlocks exactly one
        downstream capability: filled kegs of the featured beer may be moved out of
        the cellar on the event channel, as §3.4 describes, with the movement naming
        that permit's identifier as its `event_permit_id`."

        Design: Corner/endpoints/keg_deployed_to_an_event_links_the_approved_permit
        """
        bootstrap_brewery(api, home_state_code="OR")
        beer = _licensed_taproom_beer(api, "OR")
        run = _taproom_run(api, beer["id"])
        keg = create_filled_keg(api, run["id"], KEG_SIZE_HALF_BBL, keg_serial="KEG-0001")
        permit = draft_permit(
            api,
            beer["id"],
            venue_state_code="OR",
            requested_bbl=2.00,
            event_start_utc=EVENT_WINDOW_START,
            event_end_utc=EVENT_WINDOW_END,
            permit_type=PERMIT_FESTIVAL,
            event_name="Riverfront Fest",
        )
        submitted = submit_permit(api, permit["id"])
        assert submitted["state"] == PERMIT_SUBMITTED

        validate_error(
            api.move_keg_asset(
                keg["id"],
                keg_movement_payload(MOVEMENT_DEPLOY_EVENT, event_permit_id=permit["id"]),
                CELLAR,
            ),
            ERR_EVENT_PERMIT_NOT_APPROVED,
            422,
        )
        refused = validate_success(api.get_keg_asset(keg["id"], CELLAR))
        assert refused["state"] == KEG_FILLED
        assert refused["deployment_channel"] is None

        approved = validate_success(
            api.decide_event_permit(
                permit["id"], permit_decision_payload(PERMIT_DECISION_APPROVED), REGULATOR
            )
        )
        deployed = validate_success(
            api.move_keg_asset(
                keg["id"],
                keg_movement_payload(MOVEMENT_DEPLOY_EVENT, event_permit_id=permit["id"]),
                CELLAR,
            )
        )

        assert approved["state"] == PERMIT_APPROVED
        assert approved["decided_at_utc"] is not None
        assert deployed["state"] == KEG_DEPLOYED
        assert deployed["deployment_channel"] == CHANNEL_EVENT
        _, meta = validate_paginated(
            api.list_keg_assets(CELLAR, {"deployment_channel": CHANNEL_EVENT})
        )
        assert meta["total_count"] == 1


class TestPermitApprovalWhileInformationIsOutstanding:
    def test_approval_waits_for_the_resubmission_that_answers_the_regulator(self, api):
        """APPROVED is reachable only from SUBMITTED, and the loop counts the asks.

        PRD §3.9: "A `decision` of `APPROVED` is legal only from `SUBMITTED`, stamps
        `decided_at_utc`, and moves the permit to `APPROVED`."

        PRD §3.9: "Every submission increments `submission_count` by 1 and clears any
        `info_request_note`, so the counter records how many times the regulator has
        been asked, including re-submissions after an information request."

        Design: Corner/endpoints/permit_approval_is_refused_while_an_information_request_is_outstanding
        """
        bootstrap_brewery(api, home_state_code="OR")
        beer = _licensed_taproom_beer(api, "OR")
        permit = draft_permit(
            api,
            beer["id"],
            venue_state_code="OR",
            requested_bbl=2.00,
            event_start_utc="2026-09-10T12:00:00Z",
            event_end_utc="2026-09-10T18:00:00Z",
            permit_type=PERMIT_FESTIVAL,
            event_name="Riverfront Fest",
        )
        first_submission = submit_permit(api, permit["id"])
        assert first_submission["submission_count"] == 1
        queried = validate_success(
            api.decide_event_permit(
                permit["id"],
                permit_decision_payload(PERMIT_DECISION_INFO_REQUESTED, note=INFO_NOTE),
                REGULATOR,
            )
        )
        assert queried["state"] == PERMIT_INFO_REQUESTED

        validate_error(
            api.decide_event_permit(
                permit["id"], permit_decision_payload(PERMIT_DECISION_APPROVED), REGULATOR
            ),
            ERR_PERMIT_TRANSITION_INVALID,
            409,
        )
        blocked = validate_success(api.get_event_permit(permit["id"], COMPLIANCE))
        assert blocked["state"] == PERMIT_INFO_REQUESTED
        assert blocked["submission_count"] == 1
        assert blocked["decided_at_utc"] is None
        assert blocked["info_request_note"] == INFO_NOTE

        resubmitted = submit_permit(api, permit["id"])
        approved = validate_success(
            api.decide_event_permit(
                permit["id"], permit_decision_payload(PERMIT_DECISION_APPROVED), REGULATOR
            )
        )

        assert resubmitted["state"] == PERMIT_SUBMITTED
        assert resubmitted["submission_count"] == 2
        assert resubmitted["info_request_note"] is None
        assert approved["state"] == PERMIT_APPROVED
        assert approved["submission_count"] == 2
        assert approved["decided_at_utc"] is not None
        assert approved["denial_reason"] is None
