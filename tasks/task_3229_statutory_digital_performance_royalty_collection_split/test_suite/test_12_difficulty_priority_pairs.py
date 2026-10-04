"""Difficulty queue A: priority_pair_validation_conflict — distinct error
categories resolving to distinct errors on the same resource."""
from test_helpers import (
    ApiErrorId,
    create_active_licensee,
    create_effective_schedule,
    create_ownership_claim_payload,
    create_recording,
    create_report_with_lines,
    create_usage_report_payload,
    create_verified_artist,
    create_verified_rights_owner,
    create_rights_owner_payload,
    make_admin_headers,
    make_licensee_headers,
    make_payee_admin_headers,
    make_royalty_ops_headers,
    validate_error,
    validate_success,
)

ADMIN = make_admin_headers()
OPS = make_royalty_ops_headers()
PAYEE = make_payee_admin_headers()


class TestStateBeatsTemporalOnLiabilityRecompute:
    def test_compute_on_draft_report_rejected_invalid_state(self, api):
        """PRD §3.5: "A `RoyaltyOps` operator computes (or recomputes) the
        royalty liability for an ACCEPTED or AMENDED report."
        PRD §2.8: "sixth, state-machine legality of the requested transition
        (`ERR_INVALID_STATE`)"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_liability_recompute
        """
        create_effective_schedule()
        lic = create_active_licensee(legal_name="PrioCo")
        lh = make_licensee_headers(lic["id"])
        report, _ = create_report_with_lines(
            lic["id"],
            [{"isrc": "NM-2", "track_title": "t2", "artist_name": "a2",
              "performance_count": 10}],
            "2026-06-15T00:00:00Z",
            "2026-07-15T00:00:00Z",
        )
        report_now = validate_success(api.get_usage_report(report["id"], OPS))
        err = api.compute_liability(
            report["id"],
            {"expected_usage_report_version": report_now["version"]},
            OPS,
        )
        validate_error(err, ApiErrorId.ERR_INVALID_STATE.value)

    def test_submit_overlapping_window_rejected_usage_report_overlap(self, api):
        """PRD §2.7: "Usage reports collide under aggregate-coverage semantics.
        A usage report's proposed window from `period_start` through
        `period_end` may not share any single day — both ends inclusive — with
        any other usage report of the same licensee that is in SUBMITTED,
        ACCEPTED, or AMENDED status. The check runs when a report is created and
        again when it is submitted (on resubmission from AMENDED, the report
        itself is excluded from the comparison). A collision is rejected with
        `ERR_USAGE_REPORT_OVERLAP` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_liability_recompute
        """
        create_effective_schedule()
        lic = create_active_licensee(legal_name="PrioCo2")
        lh = make_licensee_headers(lic["id"])
        r1, _ = create_report_with_lines(
            lic["id"],
            [{"isrc": "NM-1", "track_title": "t", "artist_name": "a",
              "performance_count": 10}],
            "2026-06-01T00:00:00Z",
            "2026-06-30T00:00:00Z",
        )
        validate_success(api.submit_usage_report(r1["id"], lh))
        # r2's window shares days 2026-06-15..2026-06-30 with the SUBMITTED r1,
        # so creating r2 already collides under §2.7 aggregate coverage.
        err = api.create_usage_report(
            create_usage_report_payload(
                lic["id"],
                period_start="2026-06-15T00:00:00Z",
                period_end="2026-07-15T00:00:00Z",
            ),
            lh,
        )
        validate_error(err, ApiErrorId.ERR_USAGE_REPORT_OVERLAP.value)


class TestReferentialClaimGuards:
    def test_claim_on_withdrawn_recording_rejected(self, api):
        """PRD §3.7: "Two guards run at claim creation: the target recording must
        not be WITHDRAWN, else `ERR_RECORDING_WITHDRAWN` (HTTP 409), and the
        claimant's `registration_status` must be `VERIFIED`, else
        `ERR_PAYEE_NOT_VERIFIED` (HTTP 409) — a distinct error from the recording
        check."

        Design: Difficulty/priority_pair_validation_conflict/referential_recording_check_beats_payee_verification
        """
        ro1 = create_verified_rights_owner(legal_name="L1",
                                           contact_email="l1@example.com")
        # Unverified claimant rights owner.
        ro2 = validate_success(
            api.create_rights_owner(
                create_rights_owner_payload(legal_name="L2",
                                            contact_email="l2@example.com"),
                PAYEE,
            ),
            expected_status=201,
        )
        fa = create_verified_artist(stage_name="FA",
                                    contact_email="fa@example.com")
        rec_w = create_recording(ro1["id"], fa["id"], isrc="ISRC-WW",
                                 track_title="W")
        validate_success(api.withdraw_recording(rec_w["id"], ADMIN))
        err = api.create_ownership_claim(
            rec_w["id"],
            create_ownership_claim_payload(ro2["id"]),
            PAYEE,
        )
        validate_error(err, ApiErrorId.ERR_RECORDING_WITHDRAWN.value)

    def test_claim_by_unverified_claimant_rejected(self, api):
        """PRD §3.7: "Two guards run at claim creation: the target recording must
        not be WITHDRAWN, else `ERR_RECORDING_WITHDRAWN` (HTTP 409), and the
        claimant's `registration_status` must be `VERIFIED`, else
        `ERR_PAYEE_NOT_VERIFIED` (HTTP 409) — a distinct error from the recording
        check."

        Design: Difficulty/priority_pair_validation_conflict/referential_recording_check_beats_payee_verification
        """
        ro1 = create_verified_rights_owner(legal_name="L3",
                                           contact_email="l3@example.com")
        ro2 = validate_success(
            api.create_rights_owner(
                create_rights_owner_payload(legal_name="L4",
                                            contact_email="l4@example.com"),
                PAYEE,
            ),
            expected_status=201,
        )
        fa = create_verified_artist(stage_name="FA2",
                                    contact_email="fa2@example.com")
        rec_a = create_recording(ro1["id"], fa["id"], isrc="ISRC-AA2",
                                 track_title="A")
        err = api.create_ownership_claim(
            rec_a["id"],
            create_ownership_claim_payload(ro2["id"]),
            PAYEE,
        )
        validate_error(err, ApiErrorId.ERR_PAYEE_NOT_VERIFIED.value)
