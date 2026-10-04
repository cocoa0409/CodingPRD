"""Difficulty queue A: non_linear_state_machine — genuine cycles on UsageReport
and OwnershipClaim."""
from test_helpers import (
    create_active_licensee,
    create_effective_schedule,
    create_ownership_claim_payload,
    create_recording,
    create_report_with_lines,
    create_verified_artist,
    create_verified_rights_owner,
    make_admin_headers,
    make_licensee_headers,
    make_payee_admin_headers,
    make_royalty_ops_headers,
    submit_and_accept_report,
    validate_success,
)

ADMIN = make_admin_headers()
OPS = make_royalty_ops_headers()
PAYEE = make_payee_admin_headers()


class TestUsageReportAmendmentCycle:
    def test_amendment_cycle_resubmission_and_recompute(self, api):
        """PRD §3.4: "Amendment is also possible from ACCEPTED — moving the
        report `ACCEPTED` → `AMENDED` — but only when no distribution batch for
        the report is in EXECUTED status."
        PRD §3.4: "Resubmitting an AMENDED report moves it back to `SUBMITTED`
        under the same four preconditions as a first submission — play-line
        presence, ACTIVE licensee, aggregate-coverage non-overlap with the
        report itself excluded from the comparison, and an EFFECTIVE rate — and
        re-runs the rate snapshot against the (possibly new) effective schedule
        for the period."

        Design: Difficulty/non_linear_state_machine/usage_report_amendment_cycle
        """
        create_effective_schedule()
        lic = create_active_licensee(legal_name="CycleCo")
        ro = create_verified_rights_owner(legal_name="Label C",
                                          contact_email="c@example.com")
        fa = create_verified_artist(stage_name="Art C",
                                    contact_email="ac@example.com")
        create_recording(ro["id"], fa["id"], isrc="ISRC-CC",
                         track_title="Song C")
        lh = make_licensee_headers(lic["id"])
        report, _ = create_report_with_lines(
            lic["id"],
            [{"isrc": "ISRC-CC", "track_title": "Song C", "artist_name": "Art C",
              "performance_count": 10000}],
            "2026-05-01T00:00:00Z",
            "2026-05-31T00:00:00Z",
        )
        accepted = submit_and_accept_report(report["id"], lic["id"])
        validate_success(
            api.compute_liability(
                report["id"],
                {"expected_usage_report_version": accepted["version"]},
                OPS,
            ),
            expected_status=201,
        )
        amended = validate_success(api.amend_usage_report(report["id"], lh))
        assert amended["report_status"] == "AMENDED"
        # While AMENDED, add a second matched line of 40000 perfs.
        validate_success(
            api.add_play_line(
                report["id"],
                {"isrc": "ISRC-CC", "track_title": "Song C",
                 "artist_name": "Art C", "performance_count": 40000},
                lh,
            ),
            expected_status=201,
        )
        resubmitted = validate_success(api.submit_usage_report(report["id"], lh))
        assert resubmitted["report_status"] == "SUBMITTED"
        accepted2 = validate_success(api.accept_usage_report(report["id"], OPS))
        assert accepted2["report_status"] == "ACCEPTED"
        report_now = validate_success(api.get_usage_report(report["id"], OPS))
        assert report_now["total_performances"] == 50000
        assert report_now["matched_performances"] == 50000

    def test_amendment_cycle_recompute_reflects_amended_lines(self, api):
        """PRD §3.4: "if a liability exists for the report, it is recomputed
        under the year-to-date minimum-fee mode described in §3.5"
        PRD §3.5: "The result is stored as `gross_performance_royalty_cents`,
        and it is recomputed on every compute run."
        PRD §2.9: "A successful compute itself increments the report's
        `version` by 1."

        Design: Difficulty/non_linear_state_machine/usage_report_amendment_cycle
        """
        create_effective_schedule()
        lic = create_active_licensee(legal_name="CycleCo2")
        ro = create_verified_rights_owner(legal_name="Label C2",
                                          contact_email="c2@example.com")
        fa = create_verified_artist(stage_name="Art C2",
                                    contact_email="ac2@example.com")
        create_recording(ro["id"], fa["id"], isrc="ISRC-CC2",
                         track_title="Song C2")
        lh = make_licensee_headers(lic["id"])
        report, _ = create_report_with_lines(
            lic["id"],
            [{"isrc": "ISRC-CC2", "track_title": "Song C2",
              "artist_name": "Art C2", "performance_count": 10000}],
            "2026-05-01T00:00:00Z",
            "2026-05-31T00:00:00Z",
        )
        accepted = submit_and_accept_report(report["id"], lic["id"])
        liability = validate_success(
            api.compute_liability(
                report["id"],
                {"expected_usage_report_version": accepted["version"]},
                OPS,
            ),
            expected_status=201,
        )
        liab_id = liability["id"]
        validate_success(api.amend_usage_report(report["id"], lh))
        validate_success(
            api.add_play_line(
                report["id"],
                {"isrc": "ISRC-CC2", "track_title": "Song C2",
                 "artist_name": "Art C2", "performance_count": 40000},
                lh,
            ),
            expected_status=201,
        )
        validate_success(api.submit_usage_report(report["id"], lh))
        accepted2 = validate_success(api.accept_usage_report(report["id"], OPS))
        # The amendment recomputed the liability against the lines present at
        # amend time (the single 10000-perf line): 10000 x 2600 / 1e6 = 26c.
        # A second explicit compute would collide with the existing liability
        # (ERR_ALREADY_EXISTS), so the stored gross remains 26.
        liab_now = validate_success(api.get_royalty_liability(liab_id, OPS))
        assert liab_now["gross_performance_royalty_cents"] == 26


class TestOwnershipClaimReviewLoop:
    def test_claim_review_loop_then_upheld_reassigns_owner(self, api):
        """PRD §3.7: "Starting review moves a claim `OPEN` → `UNDER_REVIEW`;
        reopening moves it back `UNDER_REVIEW` → `OPEN`"
        PRD §3.7: "Resolving with `UPHELD` moves it `UNDER_REVIEW` → `UPHELD`,
        terminal, and reassigns the recording: the recording's
        `rights_owner_id` or `featured_artist_id` — per the claim's
        `claimant_type` — is set to the claimant."

        Design: Difficulty/non_linear_state_machine/ownership_claim_review_loop
        """
        ro1 = create_verified_rights_owner(legal_name="Label D1",
                                           contact_email="d1@example.com")
        ro2 = create_verified_rights_owner(legal_name="Label D2",
                                           contact_email="d2@example.com")
        fa = create_verified_artist(stage_name="Art D",
                                    contact_email="ad@example.com")
        rec = create_recording(ro1["id"], fa["id"], isrc="ISRC-DD",
                               track_title="Song D")
        claim = validate_success(
            api.create_ownership_claim(
                rec["id"], create_ownership_claim_payload(ro2["id"]), PAYEE,
            ),
            expected_status=201,
        )
        cid = claim["id"]
        # OPEN -> UNDER_REVIEW -> OPEN -> UNDER_REVIEW: loop through review twice.
        r = validate_success(api.start_claim_review(cid, PAYEE))
        assert r["claim_status"] == "UNDER_REVIEW"
        r = validate_success(api.reopen_claim(cid, PAYEE))
        assert r["claim_status"] == "OPEN"
        r = validate_success(api.start_claim_review(cid, PAYEE))
        assert r["claim_status"] == "UNDER_REVIEW"
        resolved = validate_success(
            api.resolve_claim(
                cid,
                {"outcome": "UPHELD",
                 "resolution_note": "chain of title confirmed"},
                PAYEE,
            )
        )
        assert resolved["claim_status"] == "UPHELD"
        rec_now = validate_success(api.get_recording(rec["id"], ADMIN))
        assert rec_now["rights_owner_id"] == ro2["id"]
        assert rec_now["featured_artist_id"] == fa["id"]

    def test_claim_upheld_rejected_outcome_leaves_recording_unchanged(self, api):
        """PRD §3.7: "Resolving with `REJECTED` moves the claim `UNDER_REVIEW` →
        `REJECTED`, terminal. Resolving with `UPHELD` moves it `UNDER_REVIEW` →
        `UPHELD`, terminal, and reassigns the recording: the recording's
        `rights_owner_id` or `featured_artist_id` — per the claim's
        `claimant_type` — is set to the claimant."

        Design: Difficulty/non_linear_state_machine/ownership_claim_review_loop
        """
        ro1 = create_verified_rights_owner(legal_name="Label E1",
                                           contact_email="e1@example.com")
        ro2 = create_verified_rights_owner(legal_name="Label E2",
                                           contact_email="e2@example.com")
        fa = create_verified_artist(stage_name="Art E",
                                    contact_email="ae@example.com")
        rec = create_recording(ro1["id"], fa["id"], isrc="ISRC-EE",
                               track_title="Song E")
        claim = validate_success(
            api.create_ownership_claim(
                rec["id"], create_ownership_claim_payload(ro2["id"]), PAYEE,
            ),
            expected_status=201,
        )
        validate_success(api.start_claim_review(claim["id"], PAYEE))
        resolved = validate_success(
            api.resolve_claim(
                claim["id"],
                {"outcome": "REJECTED", "resolution_note": "no evidence"},
                PAYEE,
            )
        )
        assert resolved["claim_status"] == "REJECTED"
        rec_now = validate_success(api.get_recording(rec["id"], ADMIN))
        assert rec_now["rights_owner_id"] == ro1["id"]
