"""Terminal states and repeated transitions across the platform's state machines.

Every machine in this service names states it can never leave, and several name a
specific 409 for the second attempt rather than a silent no-op. These tests drive
each such edge twice and check that the second call is refused while the record
keeps exactly the figures the first call froze.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_coaching_alert,
    assert_coaching_posture_ladder,
    assert_consignment,
    assert_corporate_rollup,
    assert_data_quality_finding,
    assert_hauler,
    assert_hauler_ticket,
    assert_recipe,
    assert_reduction_target,
    assert_settlement_breakdown,
    assert_shift,
    assert_site,
    assert_tracking_station,
    assert_version_bumped_by,
    factories,
    fixtures,
    make_corporate_lead_headers,
    make_hauler_operator_headers,
    make_kitchen_staff_headers,
    make_platform_admin_headers,
    make_shift_lead_headers,
    make_site_sustainability_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _instant(value):
    """Emitted timestamps carry three fractional digits; compare them as instants."""
    if isinstance(value, str):
        return value.replace(".000Z", "Z")
    return value


class TestCatalogTerminalApprovals:
    """Publication and approval each freeze a figure once and refuse a repeat."""

    def test_publishing_a_recipe_twice_is_rejected_on_the_second_call(self, api):
        """The first publish freezes the cost; the second is refused, never a re-freeze.

        PRD Coverage: "Publication, available only to a `PlatformAdmin`, advances `DRAFT →
        PUBLISHED`; it requires the recipe to currently be `DRAFT`, refusing anything else with
        `ERR_INVALID_RECIPE_STATE`, and requires the `ingredients` array to hold at least one
        element." "On success the recipe's freshly computed `cost_per_kg_cents` is frozen into
        `published_cost_per_kg_cents`, `published_at` is stamped with the current logical clock, and
        the recipe's `version` is incremented by 1."

        Design: Corner/state_machines/publishing_a_recipe_twice_is_rejected_on_the_second_call
        """
        fixtures.set_clock("2026-08-01T12:00:00Z")
        draft = fixtures.create_recipe(
            ingredients=[factories.recipe_ingredient("Stock Base", 2.0, 500, 0.00)],
            recipe_code="STK-PLN",
            name="Plain Stock",
        )
        assert draft["status"] == "DRAFT"

        published = validate_success(
            api.publish_recipe(draft["id"], make_platform_admin_headers("pa-1")), 200
        )
        assert_recipe(published)
        assert published["status"] == "PUBLISHED"
        assert published["published_cost_per_kg_cents"] == 500
        assert _instant(published["published_at"]) == "2026-08-01T12:00:00Z"
        assert_version_bumped_by(draft, published)

        again = api.publish_recipe(draft["id"], make_platform_admin_headers("pa-1"))
        validate_error(again, ApiErrorId.INVALID_RECIPE_STATE.value)

        after = fixtures.read_recipe(draft["id"])
        assert after["published_cost_per_kg_cents"] == 500
        assert after["version"] == published["version"]

    def test_approving_a_hauler_twice_is_rejected_on_the_second_call(self, api):
        """APPROVED is the end of the hauler ladder, so the repeat is a 409 and not a no-op 200.

        PRD Coverage: "Approval belongs to `CorporateSustainabilityLead`, advances `PENDING →
        APPROVED`, is refused with `ERR_INVALID_HAULER_STATE` when the hauler is already approved,
        makes every consignment already staged against that hauler dispatchable, and increments the
        hauler's `version` by 1."

        Design: Corner/state_machines/approving_a_hauler_twice_is_rejected_on_the_second_call
        """
        pending = fixtures.create_hauler(channels=["COMPOST", "ANIMAL_FEED"])
        assert pending["status"] == "PENDING"

        approved = validate_success(
            api.approve_hauler(pending["id"], make_corporate_lead_headers("csl-1")), 200
        )
        assert_hauler(approved)
        assert approved["status"] == "APPROVED"
        assert_version_bumped_by(pending, approved)

        again = api.approve_hauler(pending["id"], make_corporate_lead_headers("csl-1"))
        validate_error(again, ApiErrorId.INVALID_HAULER_STATE.value)

        after = fixtures.read_hauler(pending["id"])
        assert after["status"] == "APPROVED"
        assert after["version"] == approved["version"]


class TestServicePeriodAndStationLockdown:
    """A closed period and a retired station are both one-way doors."""

    def test_closing_a_shift_twice_is_rejected_from_the_terminal_state(self, api):
        """The second close is refused and `closed_at` keeps the instant of the first.

        PRD Coverage: "The period must currently be `OPEN`; closing an already-`CLOSED` period is
        refused with `ERR_INVALID_SHIFT_STATE`. Closure advances `OPEN → CLOSED`, stamps `closed_at`
        with the current logical clock, and increments the period's `version` by 1."

        Design: Corner/state_machines/closing_a_shift_twice_is_rejected_from_the_terminal_state
        """
        fixtures.set_clock("2026-08-01T12:00:00Z")
        site = fixtures.create_site()
        shift = fixtures.open_shift(site["id"], meals_served=250)
        assert shift["status"] == "OPEN"
        assert shift["closed_at"] is None

        closed = validate_success(api.close_shift(shift["id"], make_shift_lead_headers("sl-1")), 200)
        assert_shift(closed)
        assert closed["status"] == "CLOSED"
        assert _instant(closed["closed_at"]) == "2026-08-01T12:00:00Z"
        assert_version_bumped_by(shift, closed)

        again = api.close_shift(shift["id"], make_shift_lead_headers("sl-1"))
        validate_error(again, ApiErrorId.INVALID_SHIFT_STATE.value)

        after = fixtures.read_shift(shift["id"])
        assert after["status"] == "CLOSED"
        assert _instant(after["closed_at"]) == "2026-08-01T12:00:00Z"
        assert after["version"] == closed["version"]

    @pytest.mark.parametrize("requested_status", ["ACTIVE", "MAINTENANCE"])
    def test_retired_station_cannot_be_returned_to_service(self, api, requested_status):
        """Retirement is terminal, so neither availability state can be re-entered.

        PRD Coverage: "`ACTIVE → RETIRED` is permitted from either `ACTIVE` or `MAINTENANCE`, and
        `MAINTENANCE → RETIRED` from `MAINTENANCE`; both remove the station from the active-station
        denominator of the compliance figure and from missed-capture scanning altogether, and both
        increment `version` by 1." "Any status change not among these four — retiring is terminal, so
        `RETIRED` back to `ACTIVE` is impossible, and so is `ACTIVE` to `ACTIVE` — is refused with
        `ERR_INVALID_STATION_STATE`."

        Design: Corner/state_machines/retired_station_cannot_be_returned_to_active
        """
        site = fixtures.create_site()
        station = fixtures.create_station(site["id"])
        retired = fixtures.set_station_status(site["id"], station["id"], "RETIRED", note="scrapped")
        assert retired["status"] == "RETIRED"

        response = api.set_station_status(
            station["id"],
            factories.station_status_payload(requested_status),
            make_site_sustainability_manager_headers(site["id"]),
        )
        validate_error(response, ApiErrorId.INVALID_STATION_STATE.value)

        after = fixtures.read_station(station["id"])
        assert_tracking_station(after)
        assert after["status"] == "RETIRED"
        assert after["version"] == retired["version"]


class TestDataQualityAndReportingIdempotency:
    """A judged defect and a signed-off report are both closed to a second verdict."""

    def test_resolving_a_data_quality_finding_twice_is_rejected(self, api):
        """Once a human has judged the defect, a different verdict cannot be filed over it.

        PRD Coverage: "The `MISSED_CAPTURE` rule walks every pairing of an in-scope station with an
        in-scope shift, ordered by the station's `station_code` ascending and then by the shift's
        `shift_code` in the order `AM`, `PM`, `NIGHT`, and emits one finding for a pairing when no
        capture exists carrying that `station_id` and that `shift_id` with `status` `RECORDED`,
        `FLAGGED` or `SUPERSEDED` — a superseded capture still proves the station was used, so a
        corrected station is not also a missed one." "Either advances the finding out of `OPEN`,
        refusing any already-resolved finding with `ERR_INVALID_FINDING_STATE`, stamps
        `resolved_by_user_id` with the acting `X-User-ID`, and increments `version` by 1."

        Design: Corner/state_machines/resolving_a_data_quality_finding_twice_is_rejected
        """
        fixtures.set_clock("2026-08-01T12:00:00Z")
        site = fixtures.create_site()
        reporting_station = fixtures.create_station(site["id"], station_code="PREP-1")
        idle_station = fixtures.create_station(site["id"], station_code="PREP-2")
        food_type = fixtures.create_food_type()
        shift = fixtures.open_shift(site["id"], meals_served=250)
        fixtures.capture_entry(
            reporting_station["id"],
            shift["id"],
            food_type["id"],
            weight_grams=1000,
            loss_reason="TRIM",
            captured_at="2026-08-01T10:00:00Z",
        )

        findings = fixtures.run_scan(site["id"], "2026-08-01")
        assert len(findings) == 1
        finding = findings[0]
        assert_data_quality_finding(finding)
        assert finding["finding_type"] == "MISSED_CAPTURE"
        assert finding["station_id"] == idle_station["id"]
        assert finding["status"] == "OPEN"

        confirmed = validate_success(
            api.resolve_finding(
                finding["id"],
                factories.resolve_finding_payload("CONFIRMED", resolution_note="scale was unplugged"),
                make_site_sustainability_manager_headers(site["id"]),
            ),
            200,
        )
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["resolved_by_user_id"] == site["id"]
        assert_version_bumped_by(finding, confirmed)

        again = api.resolve_finding(
            finding["id"],
            factories.resolve_finding_payload("DISMISSED"),
            make_site_sustainability_manager_headers(site["id"]),
        )
        validate_error(again, ApiErrorId.INVALID_FINDING_STATE.value)

        after = fixtures.read_finding(finding["id"])
        assert after["status"] == "CONFIRMED"
        assert after["version"] == confirmed["version"]

    def test_publishing_a_rollup_twice_is_rejected_with_already_published(self, api):
        """The repeat publish names its own code rather than the generic invalid-state one.

        PRD Coverage: "The rollup must still be `DRAFT`, refused otherwise with
        `ERR_ROLLUP_ALREADY_PUBLISHED`." "`published_by_user_id` is stamped with the acting
        `X-User-ID`, `published_at` with the current logical clock, `status` advances `DRAFT →
        PUBLISHED`, and `version` is incremented by 1." "`PUBLISHED` is terminal: the frozen snapshot
        never moves again, whatever the underlying sites do afterwards." "From that count,
        `goal_attainment_state` is `ALL_ON_TRACK` when `sites_on_track_count` equals
        `in_scope_site_count`, `NONE_ON_TRACK` when `sites_on_track_count` is 0, and `PARTIAL` in every
        other case."

        Design: Corner/state_machines/publishing_a_rollup_twice_is_rejected_with_already_published
        """
        site = fixtures.create_site()
        draft = fixtures.prepare_rollup([site["id"]], user_id="csl-1")
        assert draft["status"] == "DRAFT"

        published = validate_success(
            api.publish_rollup(draft["id"], make_corporate_lead_headers("csl-2")), 200
        )
        assert_corporate_rollup(published)
        assert published["status"] == "PUBLISHED"
        assert published["published_by_user_id"] == "csl-2"
        assert published["in_scope_site_count"] == 1
        assert published["total_captured_weight_grams"] == 0
        assert published["diversion_rate_pct"] is None
        assert published["sites_on_track_count"] == 0
        assert published["goal_attainment_state"] == "NONE_ON_TRACK"
        assert_version_bumped_by(draft, published)

        again = api.publish_rollup(draft["id"], make_corporate_lead_headers("csl-2"))
        validate_error(again, ApiErrorId.ROLLUP_ALREADY_PUBLISHED.value)

        after = fixtures.read_rollup(draft["id"])
        assert after["status"] == "PUBLISHED"
        assert after["published_by_user_id"] == "csl-2"
        assert after["version"] == published["version"]


def _dispatched_compost_load(allocated_weight_grams=400):
    """A 1000 g capture with part of it staged and dispatched on a compost consignment."""
    fixtures.set_clock("2026-08-01T12:00:00Z")
    site = fixtures.create_site()
    station = fixtures.create_station(site["id"])
    food_type = fixtures.create_food_type()
    shift = fixtures.open_shift(site["id"], meals_served=250)
    entry = fixtures.capture_entry(
        station["id"],
        shift["id"],
        food_type["id"],
        weight_grams=1000,
        loss_reason="OVERPRODUCTION",
        captured_at="2026-08-01T10:00:00Z",
    )
    hauler = fixtures.create_approved_hauler(channels=["COMPOST"])
    consignment = fixtures.open_consignment(
        site["id"],
        hauler["id"],
        channel="COMPOST",
        pickup_window_start="2026-08-02T09:00:00Z",
        pickup_window_end="2026-08-02T11:00:00Z",
    )
    fixtures.add_line(site["id"], consignment["id"], entry["id"], allocated_weight_grams)
    fixtures.stage_consignment(site["id"], consignment["id"])
    fixtures.dispatch_consignment(site["id"], consignment["id"])
    return site, hauler, consignment


class TestWeighTicketLockdown:
    """An accepted ticket closes the dispute edge, and a live ticket blocks a second one."""

    def test_an_accepted_ticket_cannot_be_disputed_afterwards(self, api):
        """Acceptance has already settled the haul, so the dispute edge is gone.

        PRD Coverage: "Acceptance advances the ticket `SUBMITTED → ACCEPTED`, stamps `accepted_at`
        with the current logical clock, and increments the ticket's `version` by 1." "The first hop
        flips both consignment dimensions in the same request: `settlement_status` advances
        `TICKET_SUBMITTED → SETTLED` and `logistics_status` advances `DISPATCHED → COMPLETED`."
        "Disputing a ticket requires the ticket to be `SUBMITTED`, refused otherwise with
        `ERR_INVALID_TICKET_STATE`, and takes a `dispute_note`." "**Step three**:
        `base_haul_fee_cents` is `billable_tonnes` multiplied by the hauler's `rate_cents_per_tonne`,
        rounded half up to a whole number of cents, and then increased by the hauler's flat
        `stop_fee_cents`." "**Step seven**: `settlement_total_cents` is `settlement_subtotal_cents`
        minus `variance_credit_cents`."

        Design: Corner/state_machines/an_accepted_ticket_cannot_be_disputed_afterwards
        """
        site, hauler, consignment = _dispatched_compost_load()
        ticket = fixtures.submit_ticket(
            hauler["id"], consignment["id"], 400, ticket_number="TN-1", ticket_date="2026-08-02"
        )
        accepted = fixtures.accept_ticket(site["id"], ticket["id"])
        assert_hauler_ticket(accepted)
        assert accepted["status"] == "ACCEPTED"
        assert_settlement_breakdown(
            accepted,
            net_weight_grams=400,
            billable_tonnes=0.0004,
            base_haul_fee_cents=1821,
            fuel_surcharge_pct=0.00,
            fuel_surcharge_cents=0,
            settlement_subtotal_cents=1821,
            variance_pct=0.00,
            variance_credit_cents=0,
            settlement_total_cents=1821,
        )

        response = api.dispute_hauler_ticket(
            ticket["id"],
            factories.dispute_ticket_payload(dispute_note="weight looks light"),
            make_site_sustainability_manager_headers(site["id"]),
        )
        validate_error(response, ApiErrorId.INVALID_TICKET_STATE.value)

        after_ticket = fixtures.read_ticket(ticket["id"])
        assert after_ticket["status"] == "ACCEPTED"
        assert after_ticket["settlement_total_cents"] == 1821
        assert after_ticket["dispute_note"] is None
        assert after_ticket["version"] == accepted["version"]

        after_consignment = fixtures.read_consignment(consignment["id"])
        assert_consignment(after_consignment)
        assert after_consignment["settlement_status"] == "SETTLED"
        assert after_consignment["logistics_status"] == "COMPLETED"

    def test_a_second_ticket_on_a_consignment_already_carrying_one_is_rejected(self, api):
        """A consignment holds at most one ticket that is not disputed.

        PRD Coverage: "Its `settlement_status` must be `UNBILLED` or `DISPUTED`; filing against
        `TICKET_SUBMITTED` or `SETTLED` is refused with `ERR_TICKET_ALREADY_SUBMITTED`, which is also
        the error when the consignment already carries a ticket whose status is `SUBMITTED` or
        `ACCEPTED` — a consignment may hold at most one ticket that is not `DISPUTED`." "On success
        the ticket is created with `status` `SUBMITTED`, which may only ever hold `SUBMITTED`,
        `ACCEPTED` or `DISPUTED`, with `dispute_note` and `accepted_at` null, and the consignment's
        `settlement_status` advances to `TICKET_SUBMITTED` from either `UNBILLED` or `DISPUTED` while
        `logistics_status` stays `DISPATCHED` untouched; the consignment's `version` is incremented by
        1."

        Design: Corner/state_machines/a_second_ticket_on_a_consignment_already_carrying_one_is_rejected
        """
        site, hauler, consignment = _dispatched_compost_load()
        first = fixtures.submit_ticket(
            hauler["id"], consignment["id"], 400, ticket_number="TN-1", ticket_date="2026-08-02"
        )
        assert first["status"] == "SUBMITTED"
        assert first["settlement_total_cents"] == 1821

        response = api.create_hauler_ticket(
            factories.create_hauler_ticket_payload(
                consignment["id"], 380, ticket_number="TN-2", ticket_date="2026-08-02"
            ),
            make_hauler_operator_headers(hauler["id"]),
        )
        validate_error(response, ApiErrorId.TICKET_ALREADY_SUBMITTED.value)

        after_consignment = fixtures.read_consignment(consignment["id"])
        assert after_consignment["settlement_status"] == "TICKET_SUBMITTED"
        assert after_consignment["logistics_status"] == "DISPATCHED"

        tickets, meta = validate_paginated(
            api.list_hauler_tickets(
                make_hauler_operator_headers(hauler["id"]), consignment_id=consignment["id"]
            )
        )
        assert meta["total_count"] == 1
        assert tickets[0]["id"] == first["id"]
        assert tickets[0]["settlement_total_cents"] == 1821


def _site_with_certified_baseline():
    """A site whose single closed day has been frozen and certified as its baseline."""
    fixtures.set_clock("2026-08-01T12:00:00Z")
    site = fixtures.create_site()
    station = fixtures.create_station(site["id"])
    food_type = fixtures.create_food_type()
    shift = fixtures.open_shift(site["id"], meals_served=250)
    fixtures.capture_entry(
        station["id"],
        shift["id"],
        food_type["id"],
        weight_grams=1000,
        loss_reason="OVERPRODUCTION",
        captured_at="2026-08-01T10:00:00Z",
    )
    fixtures.close_shift(shift["id"])
    baseline = fixtures.open_baseline(site["id"], start_date="2026-08-01", end_date="2026-08-01")
    fixtures.submit_baseline(site["id"], baseline["id"])
    certified = fixtures.certify_baseline(baseline["id"])
    assert certified["status"] == "CERTIFIED"
    return site, baseline


class TestReductionTargetTransitions:
    """Activation happens once, and a re-proposal on the same window retires its predecessor."""

    def test_activating_an_already_active_target_is_rejected(self, api):
        """ACTIVE is reachable only from PROPOSED, so `activated_at` keeps the first instant.

        PRD Coverage: "Activation advances `PROPOSED → ACTIVE` and is refused from any other status
        with `ERR_INVALID_TARGET_STATE`." "On success `activated_at` is stamped with the current
        logical clock, the full attainment evaluation runs immediately, and `version` is incremented by
        1."

        Design: Corner/state_machines/activating_an_already_active_target_is_rejected
        """
        site, baseline = _site_with_certified_baseline()
        target = fixtures.propose_target(
            site["id"], baseline["id"], fixtures.read_site(site["id"])["version"]
        )
        assert target["status"] == "PROPOSED"
        assert target["activated_at"] is None

        activated = validate_success(
            api.activate_reduction_target(target["id"], make_corporate_lead_headers("csl-1")), 200
        )
        assert_reduction_target(activated)
        assert activated["status"] == "ACTIVE"
        assert _instant(activated["activated_at"]) == "2026-08-01T12:00:00Z"
        assert_version_bumped_by(target, activated)

        again = api.activate_reduction_target(target["id"], make_corporate_lead_headers("csl-1"))
        validate_error(again, ApiErrorId.INVALID_TARGET_STATE.value)

        after = fixtures.read_target(target["id"])
        assert after["status"] == "ACTIVE"
        assert _instant(after["activated_at"]) == "2026-08-01T12:00:00Z"
        assert after["version"] == activated["version"]

    def test_creating_a_second_target_on_the_same_site_and_window_supersedes_the_first(self, api):
        """The newcomer opens PROPOSED while its predecessor on the identical window is retired.

        PRD Coverage: "Proposing a target supersedes its predecessor. Any existing target on the same
        `site_id` with the identical `window_start` and `window_end` whose status is `PROPOSED` or
        `ACTIVE` transitions to `SUPERSEDED`, has `resolved_at` stamped with the current logical clock,
        and has `version` incremented by 1; from that moment it stops contributing to corporate
        on-track counting." "The new target itself opens in status `PROPOSED` with `activated_at` and
        `resolved_at` null, `performance_waste_grams` and `performance_meals_served` at 0, and
        `attainment_state` at `BEHIND`."

        Design: Corner/state_machines/creating_a_second_target_on_the_same_site_and_window_supersedes_the_first
        """
        site, baseline = _site_with_certified_baseline()
        first = fixtures.propose_target(
            site["id"], baseline["id"], fixtures.read_site(site["id"])["version"]
        )
        assert first["status"] == "PROPOSED"

        second = validate_success(
            api.create_reduction_target(
                factories.create_reduction_target_payload(
                    site["id"],
                    baseline["id"],
                    fixtures.read_site(site["id"])["version"],
                    basis="INTENSITY",
                    target_reduction_pct=15.0,
                    window_start="2026-08-02",
                    window_end="2026-08-31",
                ),
                make_corporate_lead_headers("csl-1"),
            ),
            201,
        )
        assert_reduction_target(second)
        assert second["status"] == "PROPOSED"
        assert second["basis"] == "INTENSITY"
        assert second["target_reduction_pct"] == pytest.approx(15.0, abs=0.01)
        assert second["activated_at"] is None
        assert second["resolved_at"] is None
        assert second["attainment_state"] == "BEHIND"

        superseded = fixtures.read_target(first["id"])
        assert superseded["status"] == "SUPERSEDED"
        assert _instant(superseded["resolved_at"]) == "2026-08-01T12:00:00Z"
        assert_version_bumped_by(first, superseded)


def _site_with_one_high_intensity_alert(api):
    """A 6000 g trim loss over 250 meals raises exactly one HIGH intensity breach."""
    fixtures.set_clock("2026-08-01T12:00:00Z")
    site = fixtures.create_site()
    station = fixtures.create_station(site["id"])
    food_type = fixtures.create_food_type()
    shift = fixtures.open_shift(site["id"], meals_served=250)
    fixtures.capture_entry(
        station["id"],
        shift["id"],
        food_type["id"],
        weight_grams=6000,
        loss_reason="TRIM",
        captured_at="2026-08-01T10:00:00Z",
    )
    alerts, meta = validate_paginated(
        api.list_alerts(make_shift_lead_headers("sl-1"), shift_id=shift["id"])
    )
    assert meta["total_count"] == 1
    alert = alerts[0]
    assert_coaching_alert(alert)
    assert alert["alert_type"] == "INTENSITY_BREACH"
    assert alert["severity"] == "HIGH"
    assert alert["observed_intensity"] == pytest.approx(24.000, abs=0.01)
    assert alert["status"] == "OPEN"
    return site, shift, alert


class TestAlertLadderTransitions:
    """Acknowledgement holds the posture; resolution is what walks it back down."""

    def test_acknowledging_an_alert_leaves_the_site_open_alert_count_unchanged(self, api):
        """Tapping the screen records the cook but must not soften the site's posture.

        PRD Coverage: "Acknowledgement is the cook's action and is open to `KitchenStaff` and
        `ShiftLead` alike; it advances `OPEN → ACKNOWLEDGED`, stamps `acknowledged_by_user_id` with the
        acting `X-User-ID`, and increments the alert's `version` by 1. Crucially, the site's
        `open_alert_count` **does not change** on acknowledgement — an acknowledged alert still counts,
        because acknowledging a problem is not fixing it, and the posture must not soften just because
        someone tapped the screen." "Its `observed_intensity` records the intensity value at the instant
        it was raised, to 3 decimal places, and its `severity` is `HIGH` when that observed intensity
        has reached 18.000 or more and `MEDIUM` otherwise." "`open_alert_count` is the number of
        coaching alerts at the site whose status is `OPEN` or `ACKNOWLEDGED`; and `coaching_posture` is
        derived purely from that count — `MONITORING` when the count is exactly 0, `ESCALATED` when the
        count is 3 or more, and `INTERVENTION` for every count in between."

        Design: Corner/state_machines/acknowledging_an_alert_deliberately_leaves_the_site_open_alert_count_unchanged
        """
        site, _shift, alert = _site_with_one_high_intensity_alert(api)
        before_site = fixtures.read_site(site["id"])
        assert before_site["open_alert_count"] == 1
        assert before_site["coaching_posture"] == "INTERVENTION"

        acknowledged = validate_success(
            api.acknowledge_alert(alert["id"], make_kitchen_staff_headers("ks-1")), 200
        )
        assert_coaching_alert(acknowledged)
        assert acknowledged["status"] == "ACKNOWLEDGED"
        assert acknowledged["acknowledged_by_user_id"] == "ks-1"
        assert_version_bumped_by(alert, acknowledged)

        after_site = fixtures.read_site(site["id"])
        assert_site(after_site)
        assert after_site["open_alert_count"] == 1
        assert after_site["coaching_posture"] == "INTERVENTION"
        assert_coaching_posture_ladder(after_site)

    def test_resolving_the_last_acknowledged_alert_returns_the_site_to_monitoring(self, api):
        """Resolution drops the alert out of the counting set, so the posture falls to the floor.

        PRD Coverage: "Resolution is the supervisor's action and belongs exclusively to `ShiftLead`: it
        advances `ACKNOWLEDGED → RESOLVED`, requires a `resolution_note`, stamps `resolved_by_user_id`
        with the acting `X-User-ID` and `resolved_at` with the current logical clock, decrements the
        site's `open_alert_count` by 1, recomputes `coaching_posture`, and increments both the alert's
        `version` and the site's `version` by 1." "`total_captured_weight_grams` is the sum of
        `weight_grams` over the site's captures whose status is either `RECORDED` or `FLAGGED`"
        "`open_alert_count` is the number of coaching alerts at the site whose status is `OPEN` or
        `ACKNOWLEDGED`; and `coaching_posture` is derived purely from that count — `MONITORING` when the
        count is exactly 0, `ESCALATED` when the count is 3 or more, and `INTERVENTION` for every count
        in between."

        Design: Corner/state_machines/resolving_the_last_acknowledged_alert_returns_the_site_to_monitoring
        """
        site, _shift, alert = _site_with_one_high_intensity_alert(api)
        acknowledged = fixtures.acknowledge_alert(alert["id"], user_id="ks-1")
        assert acknowledged["status"] == "ACKNOWLEDGED"

        resolved = validate_success(
            api.resolve_alert(
                alert["id"],
                factories.resolve_alert_payload(resolution_note="batch cooking split into two pans"),
                make_shift_lead_headers("sl-1"),
            ),
            200,
        )
        assert_coaching_alert(resolved)
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolved_by_user_id"] == "sl-1"
        assert _instant(resolved["resolved_at"]) == "2026-08-01T12:00:00Z"
        assert_version_bumped_by(acknowledged, resolved)

        after_site = fixtures.read_site(site["id"])
        assert_site(after_site)
        assert after_site["open_alert_count"] == 0
        assert after_site["coaching_posture"] == "MONITORING"
        assert_coaching_posture_ladder(after_site)
        assert after_site["total_captured_weight_grams"] == 6000
