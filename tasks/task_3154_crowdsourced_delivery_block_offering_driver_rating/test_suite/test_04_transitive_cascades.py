"""Transitive cascades: deactivation cascade and completion cascade."""

from test_helpers import (
    TEST_USERS,
    set_clock,
    create_station,
    create_published_block,
    onboard_active_driver,
    warmup_clean_completion,
    accept_block,
    create_offer,
    deactivate_driver,
    get_driver,
    get_block,
    get_offer,
    list_driver_assignments,
    list_driver_rating_events,
    complete_block_flow,
    complete,
    forfeit,
    drive_assignment_to_in_delivery,
    deliver_package,
    list_assignment_packages,
)


def _setup_deactivation_scenario():
    """PREMIER driver holding two non-terminal assignments and one
    PREMIER-floor OFFERED offer. Returns the scenario parts."""
    set_clock()
    station = create_station()
    driver, vehicle, _s = onboard_active_driver()
    warmup_clean_completion(station, driver, vehicle)

    bx = create_published_block(
        station["id"],
        starts_at="2026-09-01T12:00:00Z",
        ends_at="2026-09-01T14:00:00Z",
        base_pay_cents=5000,
    )
    by = create_published_block(
        station["id"],
        starts_at="2026-09-01T14:00:00Z",
        ends_at="2026-09-01T16:00:00Z",
        base_pay_cents=5000,
    )
    ob = create_published_block(
        station["id"],
        starts_at="2026-09-02T10:00:00Z",
        ends_at="2026-09-02T12:00:00Z",
        base_pay_cents=7000,
    )
    set_clock("2026-09-01T08:00:00Z")
    ax = accept_block(bx["id"], driver["id"], vehicle["id"])
    ay = accept_block(by["id"], driver["id"], vehicle["id"])
    offer = create_offer(
        ob["id"],
        driver["id"],
        tier_floor="PREMIER",
        expires_at="2026-09-02T08:00:00Z",
    )
    return station, driver, vehicle, bx, by, ob, ax, ay, offer


class TestDeactivationCascade:
    def test_deactivation_cascades_forfeit_relist_reliability_tier_offer_revocation(self, api):
        """PRD §3.8: "Every assignment the driver holds in `ASSIGNED`, `CHECKED_IN`,
        `ROUTE_ASSIGNED`, or `IN_DELIVERY` is moved to `FORFEITED` with `forfeit_cause`
        `SYSTEM_DEACTIVATION`, `forfeited_at` stamped, and `strike_reversed` false. Each
        such forfeiture relists its block back to `PUBLISHED` with `assigned_driver_id`
        cleared — including blocks already `IN_PROGRESS`, which return to `PUBLISHED`
        only through this deactivation path. The strikes then recompute the driver's
        `reliability_score_bp` at 500 basis points per non-reversed forfeit inside the
        30-day window, the tier recompute follows, and any `OFFERED` offers whose
        `tier_floor` now exceeds the demoted tier are revoked."
        PRD §2.8: "otherwise `PLUS` when `rating_score_x100` is at least 430 and
        `reliability_score_bp` is at least 8500; otherwise `STANDARD`."

        Design: Difficulty/transitive_cascade/deactivation_cascades_forfeit_relist_reliability_tier_offer_revocation
        """
        station, driver, vehicle, bx, by, ob, ax, ay, offer = (
            _setup_deactivation_scenario()
        )

        deactivate_driver(driver["id"], reason="fraud investigation")

        profile = get_driver(driver["id"])
        block_x = get_block(bx["id"])
        block_y = get_block(by["id"])
        offer_after = get_offer(offer["id"])
        forfeited = list_driver_assignments(driver["id"], params={"status": "FORFEITED"})

        # hop 1: both assignments FORFEITED as SYSTEM_DEACTIVATION strikes
        assert profile["status"] == "DEACTIVATED"
        assert len(forfeited) == 2
        for row in forfeited:
            assert row["forfeit_cause"] == "SYSTEM_DEACTIVATION"
            assert row["strike_reversed"] is False
        # hop 2: both blocks relisted with assigned_driver_id cleared
        assert block_x["status"] == "PUBLISHED"
        assert block_x["assigned_driver_id"] is None
        assert block_y["status"] == "PUBLISHED"
        # hop 3: reliability 10000 - 2 * 500
        assert profile["reliability_score_bp"] == 9000
        # hop 4: tier demoted PREMIER -> PLUS (rating 500 >= 430, 9000 >= 8500)
        assert profile["rating_tier"] == "PLUS"
        # hop 5: PREMIER-floor offer revoked
        assert offer_after["status"] == "REVOKED"

    def test_deactivation_relists_blocks_and_drops_reliability(self, api):
        """PRD §3.8: "Each such forfeiture relists its block back to `PUBLISHED` with
        `assigned_driver_id` cleared — including blocks already `IN_PROGRESS`, which
        return to `PUBLISHED` only through this deactivation path."
        PRD §2.8: "it starts at 10000 when the driver registers, each non-reversed
        forfeiture within the last 30 days subtracts 500 basis points."

        Design: Difficulty/transitive_cascade/deactivation_cascades_forfeit_relist_reliability_tier_offer_revocation
        """
        station, driver, vehicle, bx, by, ob, ax, ay, offer = (
            _setup_deactivation_scenario()
        )

        deactivate_driver(driver["id"], reason="fraud investigation")

        assert get_block(bx["id"])["status"] == "PUBLISHED"
        assert get_block(bx["id"])["assigned_driver_id"] is None
        assert get_block(by["id"])["status"] == "PUBLISHED"
        profile = get_driver(driver["id"])
        assert profile["reliability_score_bp"] == 9000
        assert profile["status"] == "DEACTIVATED"


def _setup_completion_cascade_scenario():
    """Driver with two clean completions (500 points each) and one
    driver-initiated forfeit (reliability 9500, still PREMIER); PREMIER-floor
    and PLUS-floor offers outstanding; a third block in delivery with two
    packages promised 11:00, both delivered late at 11:05 with compliant
    photos (each -100 rating points)."""
    set_clock("2026-08-10T00:00:00Z")
    station = create_station()
    driver, vehicle, _s = onboard_active_driver(clock="2026-08-10T00:00:00Z")

    warmup_clean_completion(
        station,
        driver,
        vehicle,
        starts_at="2026-08-12T02:00:00Z",
        ends_at="2026-08-12T04:00:00Z",
        promised_by="2026-08-12T03:00:00Z",
        deliver_at="2026-08-12T02:30:00Z",
        tracking_code="C1-1",
    )
    warmup_clean_completion(
        station,
        driver,
        vehicle,
        starts_at="2026-08-22T02:00:00Z",
        ends_at="2026-08-22T04:00:00Z",
        promised_by="2026-08-22T03:00:00Z",
        deliver_at="2026-08-22T02:30:00Z",
        tracking_code="C2-1",
    )

    # One forfeit: reliability 9500, still PREMIER.
    bf = create_published_block(
        station["id"],
        starts_at="2026-08-25T10:00:00Z",
        ends_at="2026-08-25T12:00:00Z",
        base_pay_cents=4000,
    )
    set_clock("2026-08-25T08:00:00Z")
    af = accept_block(bf["id"], driver["id"], vehicle["id"])
    forfeit(af["id"], driver["id"])

    b3 = create_published_block(
        station["id"],
        starts_at="2026-09-01T10:00:00Z",
        ends_at="2026-09-01T12:00:00Z",
        base_pay_cents=6000,
    )
    ob = create_published_block(
        station["id"],
        starts_at="2026-09-03T10:00:00Z",
        ends_at="2026-09-03T12:00:00Z",
        base_pay_cents=7000,
    )
    set_clock("2026-09-01T08:00:00Z")
    a3 = accept_block(b3["id"], driver["id"], vehicle["id"])
    of1 = create_offer(
        ob["id"], driver["id"], tier_floor="PREMIER", expires_at="2026-09-03T08:00:00Z"
    )
    of2 = create_offer(
        ob["id"], driver["id"], tier_floor="PLUS", expires_at="2026-09-03T08:00:00Z"
    )

    set_clock("2026-09-01T09:45:00Z")
    from test_helpers import check_in, load_packages, depart

    check_in(a3["id"], driver["id"])
    load_packages(
        a3["id"],
        [
            {
                "tracking_code": "C3-1",
                "billable_weight_kg": 1.0,
                "promised_by": "2026-09-01T11:00:00Z",
            },
            {
                "tracking_code": "C3-2",
                "billable_weight_kg": 1.0,
                "promised_by": "2026-09-01T11:00:00Z",
            },
        ],
    )
    depart(a3["id"], driver["id"])
    rows = {row["tracking_code"]: row for row in list_assignment_packages(a3["id"])}
    set_clock("2026-09-01T11:05:00Z")
    deliver_package(rows["C3-1"]["id"], driver["id"], "https://img.example/c31.jpg", True)
    deliver_package(rows["C3-2"]["id"], driver["id"], "https://img.example/c32.jpg", True)

    return station, driver, vehicle, a3, of1, of2


class TestCompletionCascade:
    def test_completion_cascades_event_rating_tier_offer_revocation(self, api):
        """PRD §3.6: "A single `RatingEvent` is created for the driver — exactly one per
        assignment completion — with `event_type` `COMPLETION_SCORE` (the only event
        type in this version of the platform), `event_at` stamped with the logical
        clock, and `points` computed from the assignment's package outcomes."
        PRD §3.6: "This event then feeds the recomputes of §2.8: the rolling 90-day
        `rating_score_x100`, the recency-weighted `lifetime_rating_x100`, and then the
        tier derivation, with any resulting demotion revoking now-unqualified `OFFERED`
        offers."
        PRD §2.8: "Whenever a tier recompute demotes a driver, every reserved offer
        addressed to that driver still in `OFFERED` status whose `tier_floor` ranks
        strictly above the driver's new tier is automatically moved to `REVOKED`."

        Design: Difficulty/transitive_cascade/completion_cascades_event_rating_tier_offer_revocation
        """
        station, driver, vehicle, a3, of1, of2 = _setup_completion_cascade_scenario()

        complete(a3["id"])

        events = list_driver_rating_events(driver["id"])
        profile = get_driver(driver["id"])
        offer1 = get_offer(of1["id"])
        offer2 = get_offer(of2["id"])

        # hop 1: exactly 3 rating events; the newest scores 500 - 2*100 = 300
        assert len(events) == 3
        assert events[-1]["points"] == 300
        # hop 2: rolling rating round_half_up((500 + 500 + 300) / 3) == 433
        assert profile["rating_score_x100"] == 433
        # reliability unchanged by completion
        assert profile["reliability_score_bp"] == 9500
        # hop 3: tier demoted PREMIER -> PLUS (433 in [430, 470), 9500)
        assert profile["rating_tier"] == "PLUS"
        # hop 4: PREMIER-floor offer revoked; PLUS-floor offer survives
        assert offer1["status"] == "REVOKED"
        assert offer2["status"] == "OFFERED"

    def test_completion_recomputes_rating_and_revokes_only_unqualified_offers(self, api):
        """PRD §3.6: "The rating points for a completion start from a perfect 500 and
        subtract for each defect: 100 points for each delivered package that was late
        (`on_time_delivery` false), 50 points for each delivered package whose photo was
        non-compliant (`photo_compliant` false), and 200 points for each package that
        ended the assignment `RETURNED_TO_STATION`."
        PRD §2.8: "Whenever a tier recompute demotes a driver, every reserved offer
        addressed to that driver still in `OFFERED` status whose `tier_floor` ranks
        strictly above the driver's new tier is automatically moved to `REVOKED`."

        Design: Difficulty/transitive_cascade/completion_cascades_event_rating_tier_offer_revocation
        """
        station, driver, vehicle, a3, of1, of2 = _setup_completion_cascade_scenario()

        complete(a3["id"])

        events = list_driver_rating_events(driver["id"])
        assert events[-1]["points"] == 300  # 500 - 2 late deliveries * 100
        assert get_driver(driver["id"])["rating_tier"] == "PLUS"
        assert get_offer(of1["id"])["status"] == "REVOKED"
        assert get_offer(of2["id"])["status"] == "OFFERED"
