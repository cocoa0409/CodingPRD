"""Repair-rate arithmetic and the REPAIR_REVIEW posture gate: weldment-scoped
aggregation, divide-then-round-half-up ordering, the inclusive boundary, and
fabrication lockout while the review is active."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_pct,
    get_success_data,
    make_welder_headers,
    record_normals_then_repairs,
    record_passes,
    record_weld_pass,
    setup_fab_workspace,
    setup_weldment_at_repair_rate,
    start_fabrication,
    validate_error,
)

ADMIN = TEST_USERS["shop_admin_headers"]
WELD_LEAD = TEST_USERS["weld_lead_headers"]


class TestRepairRateWeldmentScope:
    """The contractual gate aggregates across every joint on the weldment —
    the same is_repair flag produces one weldment-scoped number regardless of
    which joint carries the repair."""

    def test_repair_rate_aggregates_across_joints_same_weldment(self, api):
        """PRD §3.7: "Independently, the repair-rate gate watches
        `repair_rate_pct` — computed as one hundred times the weldment's
        `repair_pass_count` divided by its `total_pass_count`, rounded
        half-up to two decimal places, and defined as 0 when no passes
        exist."
        PRD §3.7: "The rate is recomputed on every weld-pass insert or
        removal, and the gate's boundary is inclusive: the moment the
        weldment-scoped `repair_rate_pct` reaches or exceeds the shop's
        `repair_rate_limit_pct`, an `OPEN` weldment moves to
        `REPAIR_REVIEW`."

        Joint A carries 1 normal + 1 repair, joint B carries 18 normals:
        20 total passes, 1 repair → 5.00 at the limit → REPAIR_REVIEW.

        Design: Difficulty/dual_variant_calc/repair_rate_weldment_vs_joint_scope
        """
        ws = setup_fab_workspace(shop_name="Scope Shop A",
                                 repair_rate_limit_pct=5,
                                 lot_received_kg=200.0, issued_kg=100.0,
                                 create_joint_count=2)
        shop_id = ws["shop"]["id"]
        joint_a, joint_b = ws["joints"]

        record_passes(ws, joint_a, 1, is_repair=False)
        record_passes(ws, joint_b, 18, is_repair=False)
        # Repair pass last: the gate trips as soon as the rate reaches 5.00.
        record_passes(ws, joint_a, 1, is_repair=True)

        wm = get_success_data(
            api.get_weldment(shop_id, ws["weldment"]["id"], ADMIN))
        assert wm["total_pass_count"] == 20
        assert wm["repair_pass_count"] == 1
        assert_pct(wm["repair_rate_pct"], 5.00)
        assert wm["posture"] == "REPAIR_REVIEW", (
            "5.00 reaches the 5 percent limit (inclusive) → REPAIR_REVIEW")

    def test_repair_rate_driven_by_weldment_totals_not_joint_share(self, api):
        """PRD §3.7: "Independently, the repair-rate gate watches
        `repair_rate_pct` — computed as one hundred times the weldment's
        `repair_pass_count` divided by its `total_pass_count`, rounded
        half-up to two decimal places, and defined as 0 when no passes
        exist."
        PRD §3.7: "The rate is recomputed on every weld-pass insert or
        removal, and the gate's boundary is inclusive: the moment the
        weldment-scoped `repair_rate_pct` reaches or exceeds the shop's
        `repair_rate_limit_pct`, an `OPEN` weldment moves to
        `REPAIR_REVIEW`."

        The repair lives on joint B while joint A carries all 19 normals —
        the weldment-scoped aggregate is unchanged: 20 total, 1 repair.

        Design: Difficulty/dual_variant_calc/repair_rate_weldment_vs_joint_scope
        """
        ws = setup_fab_workspace(shop_name="Scope Shop B",
                                 repair_rate_limit_pct=5,
                                 lot_received_kg=200.0, issued_kg=100.0,
                                 create_joint_count=2)
        shop_id = ws["shop"]["id"]
        joint_a, joint_b = ws["joints"]

        record_passes(ws, joint_a, 19, is_repair=False)
        record_passes(ws, joint_b, 1, is_repair=True)

        wm = get_success_data(
            api.get_weldment(shop_id, ws["weldment"]["id"], ADMIN))
        assert wm["total_pass_count"] == 20
        assert wm["repair_pass_count"] == 1
        assert_pct(wm["repair_rate_pct"], 5.00)
        assert wm["posture"] == "REPAIR_REVIEW"


class TestRepairRateRoundingOrder:
    """round_half_up(100.0 * 1/3, 2) == 33.33: division first, rounding
    after, at the weldment aggregate."""

    def test_repair_rate_divide_then_round_half_up(self, api):
        """PRD §3.7: "Independently, the repair-rate gate watches
        `repair_rate_pct` — computed as one hundred times the weldment's
        `repair_pass_count` divided by its `total_pass_count`, rounded
        half-up to two decimal places, and defined as 0 when no passes
        exist."
        PRD §2.9: "All percentages in the system — above all the weldment
        `repair_rate_pct` — are stored at exactly two decimal places, rounded
        half-up."

        Design: Difficulty/combinatorial_formula/repair_rate_rounding_order
        """
        ws, _ = setup_weldment_at_repair_rate(
            normal_count=2, repair_count=1, repair_rate_limit_pct=30,
            shop_name="Rounding Shop")

        wm = get_success_data(
            api.get_weldment(ws["shop"]["id"], ws["weldment"]["id"], ADMIN))
        assert wm["total_pass_count"] == 3
        assert wm["repair_pass_count"] == 1
        assert_pct(wm["repair_rate_pct"], 33.33), (
            "100.0 * 1/3 rounds half-up to 33.33 after division")

    def test_weldment_gate_uses_aggregate_rate(self, api):
        """PRD §3.7: "The rate is recomputed on every weld-pass insert or
        removal, and the gate's boundary is inclusive: the moment the
        weldment-scoped `repair_rate_pct` reaches or exceeds the shop's
        `repair_rate_limit_pct`, an `OPEN` weldment moves to
        `REPAIR_REVIEW`."

        The shop limit of 30 sits between the weldment aggregate (33.33) and
        any per-joint averaging, so the posture proves the weldment-scoped
        variant drives the gate.

        Design: Difficulty/combinatorial_formula/repair_rate_rounding_order
        """
        ws = setup_fab_workspace(shop_name="Rounding Gate Shop",
                                 repair_rate_limit_pct=30,
                                 create_joint_count=2)
        shop_id = ws["shop"]["id"]
        joint_a, joint_b = ws["joints"]
        record_passes(ws, joint_a, 1, is_repair=False)
        record_passes(ws, joint_b, 1, is_repair=False)
        record_passes(ws, joint_a, 1, is_repair=True)

        wm = get_success_data(
            api.get_weldment(shop_id, ws["weldment"]["id"], ADMIN))
        assert_pct(wm["repair_rate_pct"], 33.33)
        assert wm["posture"] == "REPAIR_REVIEW", (
            "33.33 reaches the 30 percent limit → REPAIR_REVIEW")


class TestRepairRateBoundary:
    def test_rate_exactly_at_limit_enters_repair_review(self, api):
        """PRD §3.7: "The rate is recomputed on every weld-pass insert or
        removal, and the gate's boundary is inclusive: the moment the
        weldment-scoped `repair_rate_pct` reaches or exceeds the shop's
        `repair_rate_limit_pct`, an `OPEN` weldment moves to
        `REPAIR_REVIEW`."

        1 repair in 20 total passes is exactly 5.00 at a limit of 5.

        Design: Difficulty/boundary_precision_check/repair_rate_boundary_exactly_at_limit
        """
        ws, _ = setup_weldment_at_repair_rate(
            normal_count=19, repair_count=1, repair_rate_limit_pct=5,
            shop_name="Boundary At Shop")

        wm = get_success_data(
            api.get_weldment(ws["shop"]["id"], ws["weldment"]["id"], ADMIN))
        assert wm["total_pass_count"] == 20
        assert wm["repair_pass_count"] == 1
        assert_pct(wm["repair_rate_pct"], 5.00)
        assert wm["posture"] == "REPAIR_REVIEW", (
            "The gate boundary is inclusive (>=), so exactly 5.00 enters "
            "REPAIR_REVIEW")

    def test_rate_just_below_limit_stays_open(self, api):
        """PRD §3.7: "The rate is recomputed on every weld-pass insert or
        removal, and the gate's boundary is inclusive: the moment the
        weldment-scoped `repair_rate_pct` reaches or exceeds the shop's
        `repair_rate_limit_pct`, an `OPEN` weldment moves to
        `REPAIR_REVIEW`."

        1 repair in 21 total passes rounds half-up to 4.76, below the limit.

        Design: Difficulty/boundary_precision_check/repair_rate_boundary_exactly_at_limit
        """
        ws, _ = setup_weldment_at_repair_rate(
            normal_count=20, repair_count=1, repair_rate_limit_pct=5,
            shop_name="Boundary Below Shop")

        wm = get_success_data(
            api.get_weldment(ws["shop"]["id"], ws["weldment"]["id"], ADMIN))
        assert wm["total_pass_count"] == 21
        assert wm["repair_pass_count"] == 1
        assert_pct(wm["repair_rate_pct"], 4.76)
        assert wm["posture"] == "OPEN", (
            "4.76 is below the 5 percent limit, so the weldment stays OPEN")


class TestRepairReviewBlocksFabrication:
    def _reviewed_weldment(self, api):
        """Weldment in REPAIR_REVIEW (5.00 at limit 5) with joint A
        IN_PROGRESS and joint B still PENDING."""
        ws = setup_fab_workspace(shop_name="Review Block Shop",
                                 repair_rate_limit_pct=5,
                                 lot_received_kg=200.0, issued_kg=100.0,
                                 create_joint_count=2,
                                 start_joints=False)
        shop_id = ws["shop"]["id"]
        joint_a, joint_b = ws["joints"]
        joint_a = start_fabrication(shop_id, joint_a["id"])
        ws["joints"][0] = joint_a
        record_normals_then_repairs(ws, joint_a, 19, 1)
        wm = get_success_data(
            api.get_weldment(shop_id, ws["weldment"]["id"], ADMIN))
        assert wm["posture"] == "REPAIR_REVIEW"
        return ws, joint_a, joint_b

    def test_start_fabrication_blocked_in_repair_review(self, api):
        """PRD §3.5: "Its parent weldment's `posture` must be `OPEN`: a
        weldment in `RESTRICTED`, `REPAIR_REVIEW`, or `FROZEN` posture blocks
        the start with `ERR_WELDMENT_NOT_OPEN`."
        PRD §3.7: "While a weldment sits in `REPAIR_REVIEW`, no joint may
        newly enter `IN_PROGRESS` fabrication — start-fabrication, weld-pass
        recording, and weld-out are all rejected with
        `ERR_WELDMENT_NOT_OPEN`."

        Design: Difficulty/cross_entity_state_dependency/joint_fab_depends_on_weldment_posture
        """
        ws, _, joint_b = self._reviewed_weldment(api)

        resp = api.start_fabrication(
            ws["shop"]["id"], joint_b["id"],
            {"expected_joint_version": joint_b["version"]},
            WELD_LEAD)
        validate_error(resp, ApiErrorId.ERR_WELDMENT_NOT_OPEN)

    def test_weld_pass_blocked_in_repair_review(self, api):
        """PRD §3.7: "While a weldment sits in `REPAIR_REVIEW`, no joint may
        newly enter `IN_PROGRESS` fabrication — start-fabrication, weld-pass
        recording, and weld-out are all rejected with
        `ERR_WELDMENT_NOT_OPEN`."

        Design: Difficulty/cross_entity_state_dependency/joint_fab_depends_on_weldment_posture
        """
        ws, joint_a, _ = self._reviewed_weldment(api)

        resp = api.record_weld_pass(
            ws["shop"]["id"], joint_a["id"],
            {"welder_id": ws["welder"]["id"],
             "qualification_id": ws["qualification"]["id"],
             "consumable_lot_id": ws["lot"]["id"],
             "consumable_used_kg": 1.0,
             "is_repair": False},
            make_welder_headers(ws["welder"]["id"]))
        validate_error(resp, ApiErrorId.ERR_WELDMENT_NOT_OPEN)


class TestImmediateConsistency:
    def test_weld_pass_immediately_visible_in_weldment_aggregates(self, api):
        """PRD §3.5: "A recorded pass is stamped with `welded_at_utc` from
        the shop clock and fans out: the qualification's `last_weld_at_utc`
        advances to the clock and its continuity expiry is recomputed; the
        lot's `remaining_kg` is drawn down by `consumable_used_kg`; the
        weldment's `total_pass_count` increments by one, and its
        `repair_pass_count` increments by one when `is_repair` is true; the
        weldment's `repair_rate_pct` is recomputed (see §3.7) and the
        repair-review gate evaluated; and the first pass recorded on a joint
        moves that joint's `inspection_status` from `NOT_READY` to
        `READY_FOR_VT`."

        Design: Corner/consistency_model/weld_pass_immediately_visible_in_weldment_aggregates
        """
        ws = setup_fab_workspace(shop_name="Immediate Shop",
                                 repair_rate_limit_pct=50)
        shop_id = ws["shop"]["id"]
        joint = ws["joints"][0]

        record_weld_pass(shop_id, joint["id"], ws["welder"]["id"],
                         ws["qualification"]["id"], ws["lot"]["id"],
                         is_repair=True)

        wm = get_success_data(
            api.get_weldment(shop_id, ws["weldment"]["id"], ADMIN))
        assert wm["total_pass_count"] == 1
        assert wm["repair_pass_count"] == 1
        assert_pct(wm["repair_rate_pct"], 100.00), (
            "The very next read reflects the recomputed aggregates — no lag")
