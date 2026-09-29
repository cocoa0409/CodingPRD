"""Refinish time allocation and the approved-hours roll-up on a collision estimate.

Paint time is the most intricate arithmetic on a repair order: a loaded gun and a
masked booth do not cost full time on the second panel. The shop therefore keeps
two figures over the very same panels — the conservative provisional quote it
gives before the estimate is committed, and the ranked allocation it actually
bills at lock. These tests exercise both figures over identical rows, and then
follow the approved-hours roll-up through a supplement the adjuster denies, where
the roll-up has to come back to exactly the hours the order carried before.
"""

import pytest

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.test_users import ESTIMATOR_HEADERS

# The ceilings the requirements use in their own worked pass sit below every
# posted shop rate, so REFINISH bills at 5,800, BODY at 6,000 and FRAME at 8,000.
_DEDUCTIBLE_CENTS = 25000


def _order_with_the_illustrated_estimate(api):
    """One owner, one program and the five draft labor lines of the illustration.

    The three refinish panels are 2.8 hours two-stage, 2.2 hours adjacent and
    1.6 hours blended, written while the order is still at teardown so that the
    provisional variant has a draft input set to read when the blueprint is
    published.
    """
    world = fx.open_order_world(
        api, order_overrides={"deductible_cents": _DEDUCTIBLE_CENTS}
    )
    order_id = world["order_id"]
    finding = fx.add_finding(
        api,
        order_id,
        panel_code="LT-FENDER",
        severity="MODERATE",
        requires_blend=True,
    )
    damage_line_id = finding["id"]
    world["finding"] = finding
    world["major_panel"] = fx.add_estimate_line(
        api,
        order_id,
        damage_line_id=damage_line_id,
        operation_code="REF-A",
        labor_type="REFINISH",
        guide_hours=2.8,
        two_stage=True,
    )
    world["adjacent_panel"] = fx.add_estimate_line(
        api,
        order_id,
        damage_line_id=damage_line_id,
        operation_code="REF-B",
        labor_type="REFINISH",
        guide_hours=2.2,
        is_adjacent_panel=True,
    )
    world["blend_panel"] = fx.add_estimate_line(
        api,
        order_id,
        damage_line_id=damage_line_id,
        operation_code="REF-C",
        labor_type="REFINISH",
        guide_hours=1.6,
        is_blend=True,
    )
    world["body_line"] = fx.add_estimate_line(
        api,
        order_id,
        damage_line_id=damage_line_id,
        operation_code="BDY-1",
        labor_type="BODY",
        guide_hours=4.5,
    )
    world["frame_line"] = fx.add_estimate_line(
        api,
        order_id,
        damage_line_id=damage_line_id,
        operation_code="FRM-1",
        labor_type="FRAME",
        guide_hours=3.0,
    )
    return world


def _approved_hours_on_the_lines(api, order_id):
    """The hours the currently approved labor lines actually carry, and their count."""
    rows, meta = fx.page(
        api.list_estimate_lines(
            ESTIMATOR_HEADERS,
            {"repair_order_id": order_id, "line_status": "APPROVED"},
        )
    )
    return sum(row["allocated_hours"] for row in rows), meta["total_count"]


class TestTheTwoRefinishFiguresOverIdenticalPanels:
    """The provisional quote and the billed allocation, read off the same three rows."""

    def test_the_provisional_quote_sums_raw_refinish_guide_hours(self, api):
        """Publishing the blueprint quotes 6.6 refinish hours, straight off the guide.

        PRD: "It runs the `PROVISIONAL` variant of the refinish allocation over the order's draft refinish lines, writing `refinish_hours_provisional`."
        PRD: "It applies no ranking, no overlap deduction, no blend factor and no clearcoat adder: it simply sums the `guide_hours` of the lines in its input set, each rounded half up to one decimal place, and writes the total to the order's `refinish_hours_provisional`."
        Design: Difficulty/dual_variant_calc/refinish_allocation_provisional_versus_final_on_identical_lines
        """
        world = _order_with_the_illustrated_estimate(api)
        order_id = world["order_id"]

        for key in ("major_panel", "adjacent_panel", "blend_panel"):
            assert world[key]["line_status"] == "DRAFT", (
                f"{key} must be DRAFT to sit in the provisional input set, "
                f"got {world[key]['line_status']}"
            )

        fx.publish_blueprint(api, order_id)
        order = fx.read_order(api, order_id)

        A.assert_stage(order, "BLUEPRINTED")
        A.assert_hours(
            order["refinish_hours_provisional"], 6.6, "refinish_hours_provisional"
        )

    def test_the_final_allocation_ranks_the_panels_and_lands_below_the_quote(self, api):
        """Committing the estimate bills 5.7 refinish hours where the quote said 6.6.

        PRD: "`refinish_hours_final` is therefore 3.1 plus 1.8 plus 0.8, which is 5.7, while `refinish_hours_provisional` over the identical rows is 2.8 plus 2.2 plus 1.6, which is 6.6."
        PRD: "Continuing the illustration above, three refinish lines at 3.1, 1.8 and 0.8 plus a 4.5-hour body line and a 3.0-hour frame line give 13.2."
        Design: Difficulty/dual_variant_calc/refinish_allocation_provisional_versus_final_on_identical_lines
        """
        world = _order_with_the_illustrated_estimate(api)
        order_id = world["order_id"]

        fx.publish_blueprint(api, order_id)
        fx.lock_estimate(api, order_id)
        order = fx.read_order(api, order_id)

        A.assert_stage(order, "ESTIMATE_LOCKED")
        A.assert_hours(
            order["refinish_hours_provisional"], 6.6, "refinish_hours_provisional"
        )
        A.assert_hours(order["refinish_hours_final"], 5.7, "refinish_hours_final")

        major = fx.read_estimate_line(api, world["major_panel"]["id"])
        adjacent = fx.read_estimate_line(api, world["adjacent_panel"]["id"])
        blend = fx.read_estimate_line(api, world["blend_panel"]["id"])
        body = fx.read_estimate_line(api, world["body_line"]["id"])
        frame = fx.read_estimate_line(api, world["frame_line"]["id"])

        # The 2.8 line ranks first, so it is the major panel and takes the
        # clearcoat adder; the adjacent panel loses the overlap; the blend halves.
        A.assert_hours(major["allocated_hours"], 3.1, "major panel allocated_hours")
        A.assert_hours(adjacent["allocated_hours"], 1.8, "adjacent panel allocated_hours")
        A.assert_hours(blend["allocated_hours"], 0.8, "blend panel allocated_hours")
        A.assert_hours(body["allocated_hours"], 4.5, "body line allocated_hours")
        A.assert_hours(frame["allocated_hours"], 3.0, "frame line allocated_hours")

        A.assert_hours(order["approved_labor_hours"], 13.2, "approved_labor_hours")
        A.assert_cents(order["labor_subtotal_cents"], 84060, "labor_subtotal_cents")


def _locked_order_with_one_approved_supplement(api):
    """A locked body-only estimate, then a first supplement approved for 4.0 hours.

    The baseline the compensation has to return to is therefore not the trivial
    one: 8.5 approved hours across two approved lines, and a settled money
    picture the adjuster has already signed for.
    """
    world = fx.locked_world(
        api,
        lines=[{"operation_code": "BDY-1", "labor_type": "BODY", "guide_hours": 4.5}],
        insurer_overrides={"supplement_round_limit": 2},
        order_overrides={"deductible_cents": _DEDUCTIBLE_CENTS},
    )
    order_id = world["order_id"]
    damage_line_id = world["findings"][0]["id"]

    world["first_supplement"] = fx.raise_supplement(
        api,
        order_id,
        reason_code="HIDDEN_DAMAGE",
        requested_amount_cents=24000,
    )
    world["first_supplement_line"] = fx.add_estimate_line(
        api,
        order_id,
        damage_line_id=damage_line_id,
        operation_code="BDY-2",
        labor_type="BODY",
        guide_hours=4.0,
        supplement_id=world["first_supplement"]["id"],
    )
    fx.decide_supplement(
        api,
        world["first_supplement"]["id"],
        world["insurer_id"],
        "APPROVE",
        note="confirmed",
    )
    world["damage_line_id"] = damage_line_id
    world["order"] = fx.read_order(api, order_id)
    return world


class TestDenyingASupplementRestoresTheApprovedHours:
    """The hours roll-up is an invariant, so a denial has to undo itself exactly."""

    def test_denying_the_second_supplement_puts_the_hours_back_at_8_point_5(self, api):
        """A denied 2.0-hour operation leaves the order at exactly its prior figures.

        PRD: "Its cascade is a compensation rather than an approval: every labor line whose `supplement_id` is this supplement and whose `line_status` is `PENDING_SUPPLEMENT` becomes `REJECTED`, so its `allocated_hours` leaves the approved input set entirely."
        PRD: "The `FINAL` refinish allocation, the approved-hours roll-up and the eight-step totals then rerun, restoring `approved_labor_hours` to exactly the value it held before those lines were written, and the posture derivation reruns after them."
        Design: Difficulty/compensating_invariant/supplement_denial_restores_approved_labor_hours_to_the_prior_figure
        """
        world = _locked_order_with_one_approved_supplement(api)
        order_id = world["order_id"]

        before = fx.read_order(api, order_id)
        A.assert_hours(before["approved_labor_hours"], 8.5, "approved_labor_hours")
        A.assert_totals(
            before,
            labor_subtotal_cents=51000,
            supplies_fee_cents=2040,
            pre_tax_total_cents=53040,
            insurer_authorized_cents=28040,
            customer_pay_cents=25000,
        )
        A.assert_posture(before, "OPEN")

        second = fx.raise_supplement(
            api,
            order_id,
            reason_code="PROCEDURE_REQUIREMENT",
            requested_amount_cents=12000,
        )
        denied_line = fx.add_estimate_line(
            api,
            order_id,
            damage_line_id=world["damage_line_id"],
            operation_code="BDY-3",
            labor_type="BODY",
            guide_hours=2.0,
            supplement_id=second["id"],
        )

        decided = fx.decide_supplement(
            api, second["id"], world["insurer_id"], "DENY", note="not related to the loss"
        )
        assert decided["status"] == "DENIED", (
            f"supplement status: expected DENIED, got {decided['status']}"
        )
        A.assert_cents(decided["approved_amount_cents"], 0, "approved_amount_cents")

        rejected = fx.read_estimate_line(api, denied_line["id"])
        assert rejected["line_status"] == "REJECTED", (
            f"line_status: expected REJECTED, got {rejected['line_status']}"
        )

        after = fx.read_order(api, order_id)
        A.assert_hours(after["approved_labor_hours"], 8.5, "approved_labor_hours")
        A.assert_totals(
            after,
            labor_subtotal_cents=51000,
            supplies_fee_cents=2040,
            pre_tax_total_cents=53040,
            insurer_authorized_cents=28040,
            customer_pay_cents=25000,
        )
        A.assert_customer_pay_split(after)
        A.assert_posture(after, "OPEN")

        # Nothing drifted: every restored figure is byte-identical to the one the
        # order carried before the denied operation was ever written.
        for field in (
            "approved_labor_hours",
            "labor_subtotal_cents",
            "supplies_fee_cents",
            "pre_tax_total_cents",
            "insurer_authorized_cents",
            "customer_pay_cents",
        ):
            assert after[field] == before[field], (
                f"{field} drifted across the supplement: "
                f"{before[field]} became {after[field]}"
            )

    def test_the_hours_always_equal_the_sum_over_the_currently_approved_lines(self, api):
        """The roll-up matches its own line set before, during and after the supplement.

        PRD: "The **approved-hours roll-up** is simple but load-bearing: `approved_labor_hours` is the sum of `allocated_hours` over the order's labor lines whose `line_status` is `APPROVED` — every labor type, refinish and non-refinish alike — rounded half up to one decimal place."
        PRD: "This figure is an invariant rather than an accumulator: it always equals the sum over the currently approved lines, which is why a denied supplement that flips its lines from `APPROVED` to `REJECTED` restores exactly the figure the order held before those lines were written."
        Design: Difficulty/compensating_invariant/supplement_denial_restores_approved_labor_hours_to_the_prior_figure
        """
        world = _locked_order_with_one_approved_supplement(api)
        order_id = world["order_id"]

        # Checkpoint one: the two approved lines the adjuster has already signed for.
        order = fx.read_order(api, order_id)
        line_hours, approved_count = _approved_hours_on_the_lines(api, order_id)
        A.assert_count(approved_count, 2, "approved line count")
        assert order["approved_labor_hours"] == pytest.approx(line_hours, abs=0.01), (
            f"approved_labor_hours {order['approved_labor_hours']} does not match the "
            f"{line_hours} hours on the approved lines"
        )

        second = fx.raise_supplement(
            api,
            order_id,
            reason_code="PROCEDURE_REQUIREMENT",
            requested_amount_cents=12000,
        )
        pending_line = fx.add_estimate_line(
            api,
            order_id,
            damage_line_id=world["damage_line_id"],
            operation_code="BDY-3",
            labor_type="BODY",
            guide_hours=2.0,
            supplement_id=second["id"],
        )
        assert pending_line["line_status"] == "PENDING_SUPPLEMENT", (
            f"line_status: expected PENDING_SUPPLEMENT, got {pending_line['line_status']}"
        )

        # Checkpoint two: the 2.0 hours are on the order but outside the roll-up.
        order = fx.read_order(api, order_id)
        line_hours, approved_count = _approved_hours_on_the_lines(api, order_id)
        A.assert_count(approved_count, 2, "approved line count while the supplement waits")
        A.assert_hours(order["approved_labor_hours"], 8.5, "approved_labor_hours")
        assert order["approved_labor_hours"] == pytest.approx(line_hours, abs=0.01), (
            f"a pending line moved the roll-up: {order['approved_labor_hours']} "
            f"against {line_hours} hours on the approved lines"
        )

        fx.decide_supplement(
            api, second["id"], world["insurer_id"], "DENY", note="not related to the loss"
        )

        # Checkpoint three: the denial leaves the same two lines and the same sum.
        order = fx.read_order(api, order_id)
        line_hours, approved_count = _approved_hours_on_the_lines(api, order_id)
        A.assert_count(approved_count, 2, "approved line count after the denial")
        A.assert_hours(order["approved_labor_hours"], 8.5, "approved_labor_hours")
        assert order["approved_labor_hours"] == pytest.approx(line_hours, abs=0.01), (
            f"approved_labor_hours {order['approved_labor_hours']} does not match the "
            f"{line_hours} hours on the approved lines after the denial"
        )


class TestARefinishLineWaitingOnItsAdjuster:
    """Paint time nobody has authorised yet is outside every hours figure."""

    def test_a_refinish_line_awaiting_its_supplement_stays_out_of_both_figures(self, api):
        """A 2.0-hour paint operation under an open supplement moves no hours at all.

        PRD: "A line created under a supplement is born `PENDING_SUPPLEMENT` and is invisible to every total until the adjuster decides its fate."
        PRD: "Lines sitting at `PENDING_SUPPLEMENT`, `REJECTED` or `VOID` are excluded from both variants."
        Design: Corner/calculations/refinish_hours_ignore_a_line_awaiting_its_supplement
        """
        world = fx.locked_world(
            api,
            lines=[{"operation_code": "BDY-1", "labor_type": "BODY", "guide_hours": 4.5}],
            order_overrides={"deductible_cents": _DEDUCTIBLE_CENTS},
        )
        order_id = world["order_id"]

        # A body-only estimate never had a refinish line to allocate.
        locked = fx.read_order(api, order_id)
        A.assert_hours(locked["refinish_hours_provisional"], 0.0, "refinish_hours_provisional")
        A.assert_hours(locked["refinish_hours_final"], 0.0, "refinish_hours_final")
        A.assert_hours(locked["approved_labor_hours"], 4.5, "approved_labor_hours")
        A.assert_cents(locked["labor_subtotal_cents"], 27000, "labor_subtotal_cents")

        supplement = fx.raise_supplement(
            api,
            order_id,
            reason_code="PROCEDURE_REQUIREMENT",
            requested_amount_cents=12000,
        )
        refinish_line = fx.add_estimate_line(
            api,
            order_id,
            damage_line_id=world["findings"][0]["id"],
            operation_code="RFN-1",
            labor_type="REFINISH",
            guide_hours=2.0,
            supplement_id=supplement["id"],
        )
        assert refinish_line["line_status"] == "PENDING_SUPPLEMENT", (
            f"line_status: expected PENDING_SUPPLEMENT, got {refinish_line['line_status']}"
        )

        waiting = fx.read_order(api, order_id)
        A.assert_hours(waiting["refinish_hours_provisional"], 0.0, "refinish_hours_provisional")
        A.assert_hours(waiting["refinish_hours_final"], 0.0, "refinish_hours_final")
        A.assert_hours(waiting["approved_labor_hours"], 4.5, "approved_labor_hours")
        A.assert_cents(waiting["labor_subtotal_cents"], 27000, "labor_subtotal_cents")

        fx.decide_supplement(
            api, supplement["id"], world["insurer_id"], "DENY", note="not related to the loss"
        )

        rejected = fx.read_estimate_line(api, refinish_line["id"])
        assert rejected["line_status"] == "REJECTED", (
            f"line_status: expected REJECTED, got {rejected['line_status']}"
        )

        # A denial has nothing to restore here: the figures never moved.
        denied_order = fx.read_order(api, order_id)
        A.assert_hours(denied_order["refinish_hours_final"], 0.0, "refinish_hours_final")
        A.assert_hours(
            denied_order["refinish_hours_provisional"], 0.0, "refinish_hours_provisional"
        )
        A.assert_hours(denied_order["approved_labor_hours"], 4.5, "approved_labor_hours")
        A.assert_cents(denied_order["labor_subtotal_cents"], 27000, "labor_subtotal_cents")

        rows, meta = fx.page(
            api.list_estimate_lines(
                ESTIMATOR_HEADERS,
                {"repair_order_id": order_id, "line_status": "REJECTED"},
            )
        )
        A.assert_page(meta, total_count=1)
        A.assert_ids(rows, [refinish_line["id"]])
