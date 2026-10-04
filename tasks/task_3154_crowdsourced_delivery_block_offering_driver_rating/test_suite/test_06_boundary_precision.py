"""Boundary precision: on-time inclusive boundary; reliability PLUS-floor boundary."""

from test_helpers import (
    TEST_USERS,
    api_client,
    set_clock,
    create_station,
    create_published_block,
    onboard_active_driver,
    warmup_clean_completion,
    accept_block,
    check_in,
    load_packages,
    depart,
    forfeit,
    get_driver,
    list_assignment_packages,
    make_driver_headers,
    get_success_data,
)


class TestOnTimeBoundary:
    def test_delivered_exactly_at_promised_by_is_on_time_one_second_later_is_not(self, api):
        """PRD §3.5: "`on_time_delivery` is true exactly when the delivery instant is at
        or before `promised_by`, with equality counting as on time."
        PRD §3.4: "a `promised_by` instant — the promised delivery time whose boundary
        is inclusive."

        Design: Difficulty/boundary_precision_check/on_time_boundary_delivered_exactly_at_promised_by
        """
        set_clock()
        station = create_station()
        driver, vehicle, _s = onboard_active_driver()
        block = create_published_block(
            station["id"],
            starts_at="2026-09-01T02:00:00Z",
            ends_at="2026-09-01T04:00:00Z",
            base_pay_cents=4000,
        )
        assignment = accept_block(block["id"], driver["id"], vehicle["id"])
        set_clock("2026-09-01T01:45:00Z")
        check_in(assignment["id"], driver["id"])
        load_packages(
            assignment["id"],
            [
                {
                    "tracking_code": "B-1",
                    "billable_weight_kg": 1.0,
                    "promised_by": "2026-09-01T03:00:00Z",
                },
                {
                    "tracking_code": "B-2",
                    "billable_weight_kg": 1.0,
                    "promised_by": "2026-09-01T03:00:00Z",
                },
            ],
        )
        depart(assignment["id"], driver["id"])
        rows = {
            row["tracking_code"]: row
            for row in list_assignment_packages(assignment["id"])
        }

        # Delivered exactly at promised_by: inclusive boundary => on time.
        set_clock("2026-09-01T03:00:00Z")
        p1 = get_success_data(
            api_client.deliver_package(
                rows["B-1"]["id"],
                {"photo_url": "https://img.example/b1.jpg", "photo_gps_tagged": True},
                make_driver_headers(driver["id"]),
            )
        )
        # One second past: late.
        set_clock("2026-09-01T03:00:01Z")
        p2 = get_success_data(
            api_client.deliver_package(
                rows["B-2"]["id"],
                {"photo_url": "https://img.example/b2.jpg", "photo_gps_tagged": True},
                make_driver_headers(driver["id"]),
            )
        )

        assert p1["on_time_delivery"] is True
        assert p2["on_time_delivery"] is False

    def test_delivered_before_promised_by_is_on_time(self, api):
        """PRD §3.5: "`on_time_delivery` is true exactly when the delivery instant is at
        or before `promised_by`, with equality counting as on time."

        Design: Difficulty/boundary_precision_check/on_time_boundary_delivered_exactly_at_promised_by
        """
        set_clock()
        station = create_station()
        driver, vehicle, _s = onboard_active_driver()
        block = create_published_block(
            station["id"],
            starts_at="2026-09-01T02:00:00Z",
            ends_at="2026-09-01T04:00:00Z",
            base_pay_cents=4000,
        )
        assignment = accept_block(block["id"], driver["id"], vehicle["id"])
        set_clock("2026-09-01T01:45:00Z")
        check_in(assignment["id"], driver["id"])
        load_packages(
            assignment["id"],
            [
                {
                    "tracking_code": "B-1",
                    "billable_weight_kg": 1.0,
                    "promised_by": "2026-09-01T03:00:00Z",
                }
            ],
        )
        depart(assignment["id"], driver["id"])
        rows = list_assignment_packages(assignment["id"])

        set_clock("2026-09-01T02:59:59Z")
        p1 = get_success_data(
            api_client.deliver_package(
                rows[0]["id"],
                {"photo_url": "https://img.example/b1.jpg", "photo_gps_tagged": True},
                make_driver_headers(driver["id"]),
            )
        )
        assert p1["on_time_delivery"] is True


class TestReliabilityBoundary:
    def test_reliability_exactly_at_plus_threshold_retains_tier(self, api):
        """PRD §2.8: "otherwise `PLUS` when `rating_score_x100` is at least 430 and
        `reliability_score_bp` is at least 8500; otherwise `STANDARD`. Thresholds are
        inclusive, so exactly 8500 reliability with a qualifying rating remains `PLUS`."
        PRD §2.8: "it starts at 10000 when the driver registers, each non-reversed
        forfeiture within the last 30 days subtracts 500 basis points."

        Design: Difficulty/boundary_precision_check/reliability_exactly_at_plus_threshold_retains_tier
        """
        set_clock()
        station = create_station()
        driver, vehicle, _s = onboard_active_driver()
        # PREMIER: one clean completion => rating 500, reliability 10000.
        warmup_clean_completion(station, driver, vehicle)

        windows = [
            ("2026-09-01T12:00:00Z", "2026-09-01T14:00:00Z"),
            ("2026-09-01T14:00:00Z", "2026-09-01T16:00:00Z"),
            ("2026-09-01T16:00:00Z", "2026-09-01T18:00:00Z"),
            ("2026-09-01T18:00:00Z", "2026-09-01T20:00:00Z"),
        ]
        blocks = [
            create_published_block(
                station["id"], starts_at=s, ends_at=e, base_pay_cents=4000
            )
            for s, e in windows
        ]
        set_clock("2026-09-01T08:00:00Z")

        assignments = []
        for blk, (s, _e) in zip(blocks[:3], windows[:3]):
            set_clock(s)
            a = accept_block(blk["id"], driver["id"], vehicle["id"])
            forfeit(a["id"], driver["id"])
            assignments.append(a)

        profile3 = get_driver(driver["id"])
        assert profile3["reliability_score_bp"] == 8500  # 10000 - 3*500
        assert profile3["rating_tier"] == "PLUS"  # inclusive boundary keeps PLUS

        set_clock(windows[3][0])
        a4 = accept_block(blocks[3]["id"], driver["id"], vehicle["id"])
        forfeit(a4["id"], driver["id"])
        profile4 = get_driver(driver["id"])
        assert profile4["reliability_score_bp"] == 8000
        assert profile4["rating_tier"] == "STANDARD"

    def test_reliability_drops_500_per_forfeit(self, api):
        """PRD §2.8: "it starts at 10000 when the driver registers, each non-reversed
        forfeiture within the last 30 days subtracts 500 basis points, each non-reversed
        no-show within the last 30 days subtracts 1000 basis points, and the score never
        falls below 0."

        Design: Difficulty/boundary_precision_check/reliability_exactly_at_plus_threshold_retains_tier
        """
        set_clock()
        station = create_station()
        driver, vehicle, _s = onboard_active_driver()
        warmup_clean_completion(station, driver, vehicle)

        block = create_published_block(
            station["id"],
            starts_at="2026-09-01T12:00:00Z",
            ends_at="2026-09-01T14:00:00Z",
            base_pay_cents=4000,
        )
        set_clock("2026-09-01T08:00:00Z")
        a = accept_block(block["id"], driver["id"], vehicle["id"])
        forfeit(a["id"], driver["id"])

        profile = get_driver(driver["id"])
        assert profile["reliability_score_bp"] == 9500
        assert profile["rating_tier"] == "PREMIER"
