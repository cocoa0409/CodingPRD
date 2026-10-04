"""Calculation and derived-field claims (queue B, calculations section)."""
from test_helpers import (
    create_active_licensee,
    create_effective_schedule,
    create_pool,
    create_recording,
    create_report_with_lines,
    create_verified_artist,
    create_verified_rights_owner,
    make_admin_headers,
    make_licensee_headers,
    make_matching_agent_headers,
    make_royalty_ops_headers,
    set_clock,
    setup_standard_paid_scenario,
    submit_and_accept_report,
    validate_paginated,
    validate_success,
)

ADMIN = make_admin_headers()
OPS = make_royalty_ops_headers()
MATCHER = make_matching_agent_headers()


class TestReportCounters:
    def test_report_counters_recompute_after_line_add_and_delete(self, api):
        """PRD §3.3: "The report keeps three computed counters, refreshed on
        every play-line addition or removal and on every matching-campaign
        completion: `total_performances` is the sum of `performance_count` over
        every play line of the report regardless of identification status;
        `matched_performances` is the sum over lines whose
        `identification_status` is `MATCHED`; and `unmatched_performances` is
        the difference between the two."

        Design: Corner/calculations/report_counters_recompute_after_line_add_and_delete
        """
        lic = create_active_licensee(legal_name="CtrCo")
        ro = create_verified_rights_owner(legal_name="RC",
                                          contact_email="rc@example.com")
        fa = create_verified_artist(stage_name="FC",
                                    contact_email="fc@example.com")
        create_recording(ro["id"], fa["id"], isrc="ISRC-CT", track_title="ct")
        lh = make_licensee_headers(lic["id"])
        report, lines = create_report_with_lines(
            lic["id"],
            [
                {"isrc": "ISRC-CT", "track_title": "ct", "artist_name": "fc",
                 "performance_count": 100},
                {"isrc": "NM-CT", "track_title": "u", "artist_name": "u",
                 "performance_count": 50},
            ],
            "2026-01-01T00:00:00Z",
            "2026-01-31T00:00:00Z",
        )
        resp = api.delete_play_line(lines[1]["id"], lh)
        assert resp.status_code == 204
        got = validate_success(api.get_usage_report(report["id"], OPS))
        assert got["total_performances"] == 100
        assert got["matched_performances"] == 100
        assert got["unmatched_performances"] == 0


class TestCampaignRematching:
    def test_identification_flips_to_matched_when_recording_registered(self, api):
        """PRD §3.9: "Completion increments the pool's `campaign_count` by 1 and
        re-attempts identification: every UNMATCHED play line whose report's
        period lies inside the pool window is re-checked against the current
        catalog, each line's `match_attempt_count` reflecting the campaigns that
        have attempted it, and a line whose `isrc` now resolves to exactly one
        ACTIVE recording flips `UNMATCHED` → `MATCHED`, with its proportional
        unmatched cents moved out of `accrued_unmatched_cents` and its report's
        matched and unmatched counters recomputed."
        PRD §3.3: "The line also carries a `match_attempt_count`, starting at 0,
        recording how many matching campaigns have attempted it."

        Design: Corner/calculations/identification_flips_to_matched_when_recording_registered
        """
        scenario = setup_standard_paid_scenario(
            legal_name="LateCo",
            lines=[{"isrc": "ISRC-LATE", "track_title": "late",
                    "artist_name": "fl", "performance_count": 5000}],
        )
        report = scenario["report"]
        pool = create_pool()
        batch = validate_success(
            api.create_distribution_batch(
                report["id"], {"scheduled_for": "2026-10-01T00:00:00Z"}, OPS,
            ),
            expected_status=201,
        )
        # Advance the logical clock to exactly scheduled_for so the batch is due.
        set_clock("2026-10-01T00:00:00Z")
        validate_success(
            api.execute_distribution_batch(
                batch["id"],
                {"expected_distribution_batch_version": batch["version"]},
                OPS,
            )
        )
        pool_after_exec = validate_success(api.get_unclaimed_pool(pool["id"], OPS))
        assert pool_after_exec["accrued_unmatched_cents"] == 100000

        ro = create_verified_rights_owner(legal_name="RL",
                                          contact_email="rl@example.com")
        fa = create_verified_artist(stage_name="FL",
                                    contact_email="fl@example.com")
        create_recording(ro["id"], fa["id"], isrc="ISRC-LATE",
                         track_title="late")

        validate_success(api.start_pool_campaign(pool["id"], MATCHER))
        validate_success(api.complete_pool_campaign(pool["id"], MATCHER))

        lines, _ = validate_paginated(api.list_play_lines(report["id"], OPS))
        assert len(lines) == 1
        line = lines[0]
        assert line["identification_status"] == "MATCHED"
        assert line["match_attempt_count"] == 1
        pool_after = validate_success(api.get_unclaimed_pool(pool["id"], OPS))
        assert pool_after["accrued_unmatched_cents"] == 0
        report_after = validate_success(api.get_usage_report(report["id"], OPS))
        assert report_after["matched_performances"] == 5000


def _compute_single_line_liability(api, legal_name, performance_count):
    """NS-1 schedule + ACTIVE licensee + ACCEPTED report -> computed liability."""
    create_effective_schedule()
    lic = create_active_licensee(legal_name=legal_name)
    report, _ = create_report_with_lines(
        lic["id"],
        [{"isrc": "NM-CALC", "track_title": "c", "artist_name": "c",
          "performance_count": performance_count}],
        "2026-01-01T00:00:00Z",
        "2026-01-31T00:00:00Z",
    )
    accepted = submit_and_accept_report(report["id"], lic["id"])
    return validate_success(
        api.compute_liability(
            report["id"],
            {"expected_usage_report_version": accepted["version"]},
            OPS,
        ),
        expected_status=201,
    )


class TestAdminFee:
    def test_admin_fee_zero_when_minimum_binds(self, api):
        """PRD §3.5: "When the gross is at least the minimum fee,
        `admin_fee_cents` is 5 percent of the gross, rounded half-up to whole
        cents. When the minimum fee binds — the gross is below the minimum fee —
        `admin_fee_cents` is zero: the collective retains nothing extra from a
        floor-borne amount."
        PRD §3.5: "Step three sets `amount_due_cents` to the greater of the
        gross and the minimum fee."
        PRD §3.5: "Step five sets `distributable_pool_cents` to the amount due
        minus the admin fee."

        Design: Corner/calculations/admin_fee_zero_when_minimum_binds
        """
        liability = _compute_single_line_liability(api, "AdmCo", 10000)
        assert liability["gross_performance_royalty_cents"] == 26
        assert liability["amount_due_cents"] == 100000
        assert liability["admin_fee_cents"] == 0
        assert liability["distributable_pool_cents"] == 100000

    def test_admin_fee_applies_when_gross_binds(self, api):
        """PRD §3.5: "When the gross is at least the minimum fee,
        `admin_fee_cents` is 5 percent of the gross, rounded half-up to whole
        cents."
        PRD §3.5: "Step three sets `amount_due_cents` to the greater of the
        gross and the minimum fee."
        PRD §3.5: "Step five sets `distributable_pool_cents` to the amount due
        minus the admin fee."

        Design: Corner/calculations/admin_fee_applies_when_gross_binds
        """
        liability = _compute_single_line_liability(api, "GrCo", 40000000)
        assert liability["gross_performance_royalty_cents"] == 104000
        assert liability["amount_due_cents"] == 104000
        assert liability["admin_fee_cents"] == 5200
        assert liability["distributable_pool_cents"] == 98800
