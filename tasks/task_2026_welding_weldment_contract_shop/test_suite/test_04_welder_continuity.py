"""Welder continuity clock: prospective checks at weld-pass time versus
retrospective sweeps, the inclusive 183-day boundary, lapse-driven welder
suspension, and the requalify state gate."""
from datetime import timedelta

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equal,
    create_and_approve_wps,
    create_and_approve_pqr,
    create_qualification,
    create_shop,
    create_welder,
    get_success_data,
    make_welder_headers,
    parse_utc,
    record_weld_pass,
    set_clock,
    setup_fab_workspace,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["shop_admin_headers"]
QC_MANAGER = TEST_USERS["qc_manager_headers"]

# A qualification created at the startup clock expires 183 days later:
# 2026-08-01T00:00:00Z + 183 days = 2027-01-31T00:00:00Z.
BASELINE = "2026-08-01T00:00:00Z"
EXPIRY = "2027-01-31T00:00:00Z"
ONE_SECOND_BEFORE_EXPIRY = "2027-01-30T23:59:59Z"
AFTER_EXPIRY = "2027-02-01T00:00:00Z"


class TestContinuityDualVariant:
    """Same qualification row, two evaluation variants: prospective (checked
    at a new weld pass) and retrospective (system sweep at the clock)."""

    def test_prospective_pass_before_expiry_succeeds_and_refreshes(self, api):
        """PRD §3.5: "The qualification must be `QUALIFIED` with its
        `continuity_expires_at_utc` still in the future at the pass: a pass
        attempted at or after the expiry instant is rejected with
        `ERR_WELDER_CONTINUITY_LAPSED`."
        PRD §3.2: "Thereafter, every weld pass the welder records under that
        qualification refreshes `last_weld_at_utc` to the shop clock at pass
        time, which recomputes the expiry from that new baseline."

        Design: Difficulty/dual_variant_calc/continuity_expiry_prospective_vs_retrospective
        """
        ws = setup_fab_workspace(shop_name="Prospective Shop",
                                 qualified_at_utc=BASELINE)
        shop_id = ws["shop"]["id"]
        set_clock(ONE_SECOND_BEFORE_EXPIRY)

        weld_pass = record_weld_pass(
            shop_id, ws["joints"][0]["id"], ws["welder"]["id"],
            ws["qualification"]["id"], ws["lot"]["id"])
        assert weld_pass["id"], "Pass one second before expiry must succeed"
        assert_instant_equal(weld_pass["welded_at_utc"],
                             ONE_SECOND_BEFORE_EXPIRY, "welded_at_utc")

        qual = get_success_data(
            api.get_qualification(shop_id, ws["qualification"]["id"], ADMIN))
        assert qual["status"] == "QUALIFIED"
        assert_instant_equal(qual["last_weld_at_utc"],
                             ONE_SECOND_BEFORE_EXPIRY, "last_weld_at_utc")
        expected_expiry = parse_utc(ONE_SECOND_BEFORE_EXPIRY) + timedelta(
            days=183)
        assert_instant_equal(qual["continuity_expires_at_utc"],
                             expected_expiry.strftime("%Y-%m-%dT%H:%M:%SZ"),
                             "continuity_expires_at_utc")

        # Retrospective leg: advance past the ORIGINAL expiry (2027-01-31);
        # the sweep must not lapse the refreshed qualification.
        set_clock(AFTER_EXPIRY)
        qual_after = get_success_data(
            api.get_qualification(shop_id, ws["qualification"]["id"], ADMIN))
        assert qual_after["status"] == "QUALIFIED", (
            "Continuity was refreshed by the pass; the retrospective sweep "
            "must keep the qualification QUALIFIED")

    def test_retrospective_sweep_lapses_stale_qualification(self, api):
        """PRD §3.2: "Retrospectively, two sweeps re-evaluate every
        `QUALIFIED` row against the clock without any new weld activity:
        advancing the shop clock runs the continuity sweep"
        PRD §3.2: "A lapse increments the qualification's `version` and
        forces a recomputation of the welder's `status`: a welder left with
        no `QUALIFIED` qualification at all becomes `SUSPENDED`."

        Design: Difficulty/dual_variant_calc/continuity_expiry_prospective_vs_retrospective
        """
        ws = setup_fab_workspace(shop_name="Retrospective Shop",
                                 qualified_at_utc=BASELINE,
                                 start_joints=False)
        shop_id = ws["shop"]["id"]
        qual_id = ws["qualification"]["id"]

        set_clock(AFTER_EXPIRY)

        qual = get_success_data(api.get_qualification(shop_id, qual_id,
                                                      ADMIN))
        assert qual["status"] == "LAPSED", (
            f"Clock past the 183-day expiry must lapse the qualification, "
            f"got {qual['status']}")
        welder = get_success_data(
            api.get_welder(shop_id, ws["welder"]["id"], ADMIN))
        assert welder["status"] == "SUSPENDED", (
            "A welder left with no QUALIFIED qualification becomes SUSPENDED")

    def test_continuity_boundary_inclusive_at_expiry(self, api):
        """PRD §3.2: "Continuity lapse is evaluated at second granularity
        with an inclusive boundary: a qualification is lapsed when the shop's
        `current_utc` reaches or passes its `continuity_expires_at_utc` — it
        is lapsed *at* the expiry instant, not after it."

        Design: Difficulty/dual_variant_calc/continuity_expiry_prospective_vs_retrospective
        """
        ws = setup_fab_workspace(shop_name="Boundary Shop",
                                 qualified_at_utc=BASELINE,
                                 start_joints=False)
        shop_id = ws["shop"]["id"]
        qual_id = ws["qualification"]["id"]

        set_clock(ONE_SECOND_BEFORE_EXPIRY)
        qual = get_success_data(api.get_qualification(shop_id, qual_id,
                                                      ADMIN))
        assert qual["status"] == "QUALIFIED", (
            "Strictly before the expiry instant the qualification is valid")

        set_clock(EXPIRY)
        qual = get_success_data(api.get_qualification(shop_id, qual_id,
                                                      ADMIN))
        assert qual["status"] == "LAPSED", (
            "At the expiry instant exactly the qualification is lapsed "
            f"(inclusive boundary), got {qual['status']}")


class TestWeldPassDependsOnQualification:
    def test_weld_pass_rejected_after_continuity_lapse(self, api):
        """PRD §3.5: "The qualification must be `QUALIFIED` with its
        `continuity_expires_at_utc` still in the future at the pass: a pass
        attempted at or after the expiry instant is rejected with
        `ERR_WELDER_CONTINUITY_LAPSED`."

        Design: Difficulty/cross_entity_state_dependency/weld_pass_depends_on_qualification_state
        """
        ws = setup_fab_workspace(shop_name="Lapsed Pass Shop",
                                 qualified_at_utc=BASELINE)
        shop_id = ws["shop"]["id"]
        set_clock(AFTER_EXPIRY)  # sweep lapses the qualification

        qual = get_success_data(
            api.get_qualification(shop_id, ws["qualification"]["id"], ADMIN))
        assert qual["status"] == "LAPSED"

        resp = api.record_weld_pass(
            shop_id, ws["joints"][0]["id"],
            {"welder_id": ws["welder"]["id"],
             "qualification_id": ws["qualification"]["id"],
             "consumable_lot_id": ws["lot"]["id"],
             "consumable_used_kg": 1.0,
             "is_repair": False},
            # Welder role is entity-backed: X-User-ID is the Welder id.
            make_welder_headers(ws["welder"]["id"]))
        validate_error(resp, ApiErrorId.ERR_WELDER_CONTINUITY_LAPSED)

    def test_weld_pass_accepted_while_continuity_valid(self, api):
        """PRD §3.5: "The qualification must be `QUALIFIED` with its
        `continuity_expires_at_utc` still in the future at the pass: a pass
        attempted at or after the expiry instant is rejected with
        `ERR_WELDER_CONTINUITY_LAPSED`."
        PRD §3.2: "Thereafter, every weld pass the welder records under that
        qualification refreshes `last_weld_at_utc` to the shop clock at pass
        time, which recomputes the expiry from that new baseline."

        Design: Difficulty/cross_entity_state_dependency/weld_pass_depends_on_qualification_state
        """
        ws = setup_fab_workspace(shop_name="Valid Pass Shop",
                                 qualified_at_utc=BASELINE)
        shop_id = ws["shop"]["id"]

        weld_pass = record_weld_pass(
            shop_id, ws["joints"][0]["id"], ws["welder"]["id"],
            ws["qualification"]["id"], ws["lot"]["id"])
        assert weld_pass["id"]

        qual = get_success_data(
            api.get_qualification(shop_id, ws["qualification"]["id"], ADMIN))
        assert qual["status"] == "QUALIFIED"
        assert_instant_equal(qual["last_weld_at_utc"], BASELINE,
                             "last_weld_at_utc refreshed to the shop clock")


class TestRequalifyGate:
    def test_qual_requalify_from_qualified_returns_invalid_state(self, api):
        """PRD §3.2: "Requalification by a `QCManager` requires that the
        qualification currently be `LAPSED` (otherwise
        `ERR_QUAL_NOT_LAPSED`), that the welder not be `TERMINATED`
        (otherwise `ERR_WELDER_TERMINATED`), and that the WPS the
        qualification references still be `APPROVED` rather than
        `SUPERSEDED` (otherwise `ERR_WPS_NOT_APPROVED`)."

        Design: Corner/state_machines/qual_requalify_from_qualified_returns_invalid_state
        """
        shop = create_shop(shop_name="Requalify Shop")
        welder = create_welder(shop["id"])
        pqr = create_and_approve_pqr(shop["id"], pqr_number="PQR-Q5")
        wps = create_and_approve_wps(shop["id"], pqr["id"],
                                     wps_number="WPS-Q5")
        qual = create_qualification(shop["id"], welder["id"], wps["id"],
                                    qualified_at_utc=BASELINE)
        assert qual["status"] == "QUALIFIED"

        resp = api.requalify_qualification(shop["id"], qual["id"], QC_MANAGER)
        validate_error(resp, ApiErrorId.ERR_QUAL_NOT_LAPSED)
