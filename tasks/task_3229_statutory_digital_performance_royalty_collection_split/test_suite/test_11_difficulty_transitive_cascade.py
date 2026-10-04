"""Difficulty queue A: transitive_cascade — depth-N cascade chains triggered by
a single operation, each link caused by the previous link's mutation."""
from test_helpers import (
    ApiErrorId,
    create_active_licensee,
    create_effective_schedule,
    create_rate_proceeding_payload,
    create_rate_schedule_payload,
    create_report_with_lines,
    create_usage_report_payload,
    make_admin_headers,
    make_licensee_headers,
    make_royalty_auditor_headers,
    make_royalty_ops_headers,
    make_statutory_board_headers,
    setup_march_audit_scenario,
    submit_and_accept_report,
    validate_error,
    validate_success,
)

ADMIN = make_admin_headers()
OPS = make_royalty_ops_headers()
BOARD = make_statutory_board_headers()


class TestAuditShortfallCascade:
    def test_audit_shortfall_suspends_licensee_rejects_pipeline_reports(self, api):
        """PRD §3.8: "When a recovery is recorded with `final` set to true, the
        case moves `FINDINGS_ISSUED` → `SETTLED` and the settlement cascade
        fires: if the total recovered equals the assessment, the licensee is
        unaffected; if it falls short, cascade link 3 suspends the licensee —
        `ACTIVE` → `SUSPENDED` with `suspended_reason` set to
        `UNDERPAYMENT_SHORTFALL` — and cascade link 4 flips every SUBMITTED
        usage report of the licensee to REJECTED."
        PRD §3.1: "Suspension has two consequences beyond the status change: the
        licensee is blocked from submitting new usage reports while SUSPENDED,
        and every usage report of the licensee currently in SUBMITTED status
        auto-flips to REJECTED."
        PRD §3.1: "Only an `ACTIVE` licensee may create usage reports or submit
        them; a report creation or submission attempted against a licensee in
        any other status is rejected with `ERR_LICENSEE_NOT_ACTIVE` (HTTP 409)."

        Design: Difficulty/transitive_cascade/audit_shortfall_suspends_licensee_rejects_pipeline_reports
        """
        scenario = setup_march_audit_scenario(legal_name="CascadeCo")
        lic = scenario["licensee"]
        audit = scenario["audit"]
        lh = make_licensee_headers(lic["id"])

        # A second report sitting in SUBMITTED when the settlement lands.
        report_d, _ = create_report_with_lines(
            lic["id"],
            [{"isrc": "NO-MATCH-D", "track_title": "TD", "artist_name": "AD",
              "performance_count": 1000}],
            "2026-04-01T00:00:00Z",
            "2026-04-30T00:00:00Z",
        )
        validate_success(api.submit_usage_report(report_d["id"], lh))

        # A further DRAFT report created while the licensee is still ACTIVE;
        # only submission is attempted after the suspension lands (PRD §3.1:
        # both creation and submission require an ACTIVE licensee).
        report_e, _ = create_report_with_lines(
            lic["id"],
            [{"isrc": "NO-MATCH-E", "track_title": "TE", "artist_name": "AE",
              "performance_count": 5}],
            "2026-05-01T00:00:00Z",
            "2026-05-31T00:00:00Z",
        )

        # Settle with a partial recovery: 10000 < assessed.
        assessed = audit["assessed_underpayment_cents"]
        settled = validate_success(
            api.record_audit_recovery(
                audit["id"], {"amount_cents": 10000, "final": True},
                make_royalty_auditor_headers("auditor-two"),
            )
        )
        assert settled["audit_status"] == "SETTLED"
        assert settled["recovered_cents"] == 10000
        assert 10000 < assessed

        lic_now = validate_success(api.get_licensee(lic["id"], ADMIN))
        assert lic_now["license_status"] == "SUSPENDED"
        assert lic_now["suspended_reason"] == "UNDERPAYMENT_SHORTFALL"
        rep_d_now = validate_success(api.get_usage_report(report_d["id"], OPS))
        assert rep_d_now["report_status"] == "REJECTED"

        # Link 4: a new submission is refused while the licensee is SUSPENDED.
        err = api.submit_usage_report(report_e["id"], lh)
        validate_error(err, ApiErrorId.ERR_LICENSEE_NOT_ACTIVE.value)

    def test_audit_full_recovery_leaves_licensee_unaffected(self, api):
        """PRD §3.8: "When a recovery is recorded with `final` set to true, the
        case moves `FINDINGS_ISSUED` → `SETTLED` and the settlement cascade
        fires: if the total recovered equals the assessment, the licensee is
        unaffected; if it falls short, cascade link 3 suspends the licensee —
        `ACTIVE` → `SUSPENDED` with `suspended_reason` set to
        `UNDERPAYMENT_SHORTFALL` — and cascade link 4 flips every SUBMITTED
        usage report of the licensee to REJECTED."

        Design: Difficulty/transitive_cascade/audit_shortfall_suspends_licensee_rejects_pipeline_reports
        """
        scenario = setup_march_audit_scenario(legal_name="FullRecCo")
        lic = scenario["licensee"]
        audit = scenario["audit"]
        assessed = audit["assessed_underpayment_cents"]
        settled = validate_success(
            api.record_audit_recovery(
                audit["id"], {"amount_cents": assessed, "final": True},
                make_royalty_auditor_headers("auditor-two"),
            )
        )
        assert settled["audit_status"] == "SETTLED"
        assert settled["recovered_cents"] == assessed
        lic_now = validate_success(api.get_licensee(lic["id"], ADMIN))
        assert lic_now["license_status"] == "ACTIVE"


class TestRatePublishCascade:
    def _setup_publish_cascade(self, api):
        """S1 EFFECTIVE for PREEXISTING_SUBSCRIPTION (2026-01-01..2026-12-31,
        2600 microcents, min 100000); licensee P ACTIVE; old report (June 2026,
        10000 perfs) with liability computed under S1; draft S2 (2027, 3000
        microcents) adopted by a DECIDED proceeding. S2's window starts the day
        after S1's effective_end — back-to-back adjacency is allowed under the
        half-open semantics of PRD §2.7."""
        s1 = validate_success(
            api.create_rate_schedule(
                create_rate_schedule_payload(
                    proceeding_ref="D-2024-99",
                    effective_start="2026-01-01T00:00:00Z",
                    effective_end="2026-12-31T00:00:00Z",
                    category="PREEXISTING_SUBSCRIPTION",
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        validate_success(api.activate_rate_schedule(s1["id"], ADMIN))
        lic = create_active_licensee(
            legal_name="PubCo", service_category="PREEXISTING_SUBSCRIPTION",
        )
        report_old, _ = create_report_with_lines(
            lic["id"],
            [{"isrc": "NO-MATCH-P", "track_title": "TP", "artist_name": "AP",
              "performance_count": 10000}],
            "2026-06-01T00:00:00Z",
            "2026-06-30T00:00:00Z",
        )
        accepted_old = submit_and_accept_report(report_old["id"], lic["id"])
        liability_old = validate_success(
            api.compute_liability(
                report_old["id"],
                {"expected_usage_report_version": accepted_old["version"]},
                OPS,
            ),
            expected_status=201,
        )
        s2 = validate_success(
            api.create_rate_schedule(
                create_rate_schedule_payload(
                    proceeding_ref="D-2026-01",
                    effective_start="2027-01-01T00:00:00Z",
                    effective_end="2027-12-31T00:00:00Z",
                    rate_per_performance_microcents=3000,
                    min_fee_cents=120000,
                    category="PREEXISTING_SUBSCRIPTION",
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        proc = validate_success(
            api.create_rate_proceeding(
                create_rate_proceeding_payload(docket_no="DKT-2026-01"), BOARD,
            ),
            expected_status=201,
        )
        validate_success(
            api.decide_rate_proceeding(proc["id"],
                                       {"new_schedule_id": s2["id"]}, BOARD)
        )
        return {
            "s1": s1, "s2": s2, "proc": proc, "lic": lic,
            "report_old": report_old, "liability_old": liability_old,
        }

    def test_rate_publish_supersedes_schedule_future_reports_use_new_rate(self, api):
        """PRD §3.2: "Publishing a DECIDED proceeding moves it `DECIDED` →
        `PUBLISHED` and fires the schedule cascade: the decided RateSchedule
        flips `DRAFT` → `EFFECTIVE`, the previously EFFECTIVE schedule of the
        same category flips `EFFECTIVE` → `SUPERSEDED`, and the category's rate
        cache is invalidated so the next submission resolves the new schedule."
        PRD §2.6: "The resolved schedule's rates are stored as a snapshot on the
        report and govern every later computation for that report — even if the
        schedule is subsequently SUPERSEDED by a newer one."

        Design: Difficulty/transitive_cascade/rate_publish_supersedes_schedule_future_reports_use_new_rate
        """
        env = self._setup_publish_cascade(api)
        published = validate_success(
            api.publish_rate_proceeding(env["proc"]["id"], BOARD)
        )
        assert published["proceeding_status"] == "PUBLISHED"
        s2_now = validate_success(api.get_rate_schedule(env["s2"]["id"], ADMIN))
        assert s2_now["schedule_status"] == "EFFECTIVE"
        s1_now = validate_success(api.get_rate_schedule(env["s1"]["id"], ADMIN))
        assert s1_now["schedule_status"] == "SUPERSEDED"

        lic = env["lic"]
        report_new, _ = create_report_with_lines(
            lic["id"],
            [{"isrc": "NO-MATCH-P2", "track_title": "TP2", "artist_name": "AP2",
              "performance_count": 10000}],
            "2027-01-01T00:00:00Z",
            "2027-01-31T00:00:00Z",
        )
        accepted_new = submit_and_accept_report(report_new["id"], lic["id"])
        liability_new = validate_success(
            api.compute_liability(
                report_new["id"],
                {"expected_usage_report_version": accepted_new["version"]},
                OPS,
            ),
            expected_status=201,
        )
        # New rate 3000 microcents: 10000 x 3000 / 1e6 = 30c gross.
        assert liability_new["gross_performance_royalty_cents"] == 30

    def test_rate_publish_leaves_existing_liability_snapshot_unrecomputed(self, api):
        """PRD §2.6: "Past periods keep their original rates; a supersession
        never recomputes liabilities already COMPUTED."
        PRD §3.2: "Liabilities already COMPUTED for past periods keep their
        snapshot rates and are not recomputed."

        Design: Difficulty/transitive_cascade/rate_publish_supersedes_schedule_future_reports_use_new_rate
        """
        env = self._setup_publish_cascade(api)
        validate_success(api.publish_rate_proceeding(env["proc"]["id"], BOARD))
        liab_old = validate_success(
            api.get_royalty_liability(env["liability_old"]["id"], OPS)
        )
        # Old snapshot rate 2600 microcents: 10000 x 2600 / 1e6 = 26c gross,
        # min fee binds at 100000.
        assert liab_old["gross_performance_royalty_cents"] == 26
        assert liab_old["amount_due_cents"] == 100000
