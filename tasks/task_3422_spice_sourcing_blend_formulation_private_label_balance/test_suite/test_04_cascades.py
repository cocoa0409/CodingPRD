"""Transitive cascades: adulterant FAIL depth-3 and run-completion depth-2."""
import pytest
from test_helpers import (
    api_client, validate_success, TEST_USERS, setup_accepted_lots,
    create_agreement, create_active_formula, create_committed_blend_run,
    create_line, schedule_run, complete_run, batch_for_run, setup_produced_batch,
    post_test, get_lot, get_batch, get_agreement, list_recall_cases,
    assert_lot_mass_invariant, CLOCK_DEFAULT_UTC,
)


def _fire_adulterant_fail(s):
    """Post ADULTERANT_SCREEN 2.50 (>= 2.00 action level) on the first lot."""
    la = s["lots"][0]
    t = post_test(la["id"], "ADULTERANT_SCREEN", 2.5, lab_code="LAB-B",
                  analyst_id="qa-2")
    return la, t


class TestAdulterantFailCascade:
    def test_fail_quarantines_lot_and_holds_batch(self, api):
        """PRD §3.7: "the moment an `ADULTERANT_SCREEN` test computes `FAIL`
        on a lot in `IN_TEST` or `ACCEPTED`, the lot auto-quarantines (§3.2)
        and, within the same request, the cascade fires. Every finished batch
        whose `genealogy_lot_ids` contains that lot and whose `quality_status`
        is `CLEAR` moves to `QUALITY_HOLD`, with `quality_hold_cause` set to
        `LOT_QUARANTINE` and `quality_hold_lot_id` set to the quarantined
        lot's id."

        Hop 1 lot ACCEPTED -> QUARANTINED; hop 2 batch CLEAR -> QUALITY_HOLD;
        the mass invariant holds through the cascade (60 + 40 + 0 == 100).

        Design: Difficulty/transitive_cascade/adulterant_fail_cascade_depth3
        """
        s = setup_produced_batch(product_code="TACO-9")
        batch = s["batch"]
        assert batch["quality_status"] == "CLEAR"
        la, t = _fire_adulterant_fail(s)
        assert t["result"] == "FAIL"
        lot_after = get_lot(la["id"])
        assert lot_after["status"] == "QUARANTINED"
        assert_lot_mass_invariant(lot_after)
        assert lot_after["quantity_remaining_kg"] == pytest.approx(60.0)
        assert lot_after["quantity_consumed_kg"] == pytest.approx(40.0)
        assert lot_after["quantity_wasted_kg"] == pytest.approx(0.0)
        held = get_batch(batch["id"])
        assert held["quality_status"] == "QUALITY_HOLD"
        assert held["quality_hold_cause"] == "LOT_QUARANTINE"
        assert held["quality_hold_lot_id"] == la["id"]

    def test_fail_auto_creates_single_draft_recall_case(self, api):
        """PRD §3.7: "If at least one batch was held and no recall case in
        `DRAFT` or `INITIATED` already names that lot as its `suspect_lot_id`,
        the system auto-creates a recall case with `trigger_type` `LOT_SUSPECT`,
        the quarantined lot as its suspect, `scope_policy` `PROVISIONAL`,
        `source` `AUTO_QUARANTINE`, and status `DRAFT`".

        Hop 3: exactly one auto-created DRAFT case names the quarantined lot.

        Design: Difficulty/transitive_cascade/adulterant_fail_cascade_depth3
        """
        s = setup_produced_batch(product_code="TACO-9")
        la, t = _fire_adulterant_fail(s)
        assert t["result"] == "FAIL"
        cases = list_recall_cases(params={"suspect_lot_id": la["id"]})
        assert len(cases) == 1
        case = cases[0]
        assert case["source"] == "AUTO_QUARANTINE"
        assert case["status"] == "DRAFT"
        assert case["scope_policy"] == "PROVISIONAL"
        assert case["trigger_type"] == "LOT_SUSPECT"


def _setup_pl_completion_scenario():
    """PRIVATE_LABEL formula PL-PEP-001, agreement with a 120 kg annual
    commitment, three ACCEPTED pepper lots, two COMMITTED 60 kg blend runs and
    a line — ready for two adjacent-week-37 completions."""
    supplier, lots = setup_accepted_lots(costs=(100, 200, 300))
    agr = create_agreement("Riverbend Foods", ["PL-PEP-001"], 120,
                           confidentiality_level="STANDARD",
                           development_nda_signed=True)
    formula = create_active_formula("PL-PEP-001", brand_type="PRIVATE_LABEL")
    br1 = create_committed_blend_run(formula["id"], "COST_MIN", 60)
    br2 = create_committed_blend_run(formula["id"], "COST_MIN", 60)
    line = create_line(name="Line-A")
    return {"supplier": supplier, "lots": lots, "agr": agr,
            "formula": formula, "br1": br1, "br2": br2, "line": line}


class TestProductionCompletionCascade:
    def test_completion_creates_batch_and_rolls_agreement(self, api):
        """PRD §3.6: "`produced_at` is the logical clock's value at completion;
        `shelf_life_days` is always 540; `best_by_date` is `produced_at` plus
        540 days; `genealogy_lot_ids` is the distinct list of raw-lot ids drawn
        from the blend run's `selected_allocations`, in allocation order".
        PRD §3.6: "the same completion adds the run's `quantity_kg` into the
        agreement's `produced_ytd_kg`".

        First completion: batch genealogy [la, lb, lc] (COST_MIN order), the
        clock was never set so produced_at is the default instant; agreement
        goes 0 -> 60, still below the 120 commitment.

        Design: Difficulty/transitive_cascade/production_completion_cascade_depth2
        """
        s = _setup_pl_completion_scenario()
        before = get_agreement(s["agr"]["id"])
        assert before["produced_ytd_kg"] == pytest.approx(0.0)
        assert before["commitment_met"] is False
        r1 = schedule_run(s["line"]["id"], s["formula"]["id"], s["br1"]["id"],
                          60, "2026-09-07T08:00:00Z", "2026-09-07T11:00:00Z",
                          private_label_agreement_id=s["agr"]["id"])
        complete_run(r1["id"])
        b1 = batch_for_run(r1["id"])
        assert [b1["genealogy_lot_ids"][i] for i in range(3)] == [
            s["lots"][0]["id"], s["lots"][1]["id"], s["lots"][2]["id"]]
        assert b1["produced_at"].startswith("2026-09-01")
        assert b1["best_by_date"].startswith("2028-02-23")
        after = get_agreement(s["agr"]["id"])
        assert after["produced_ytd_kg"] == pytest.approx(60.0)
        assert after["commitment_met"] is False

    def test_commitment_met_exactly_at_threshold(self, api):
        """PRD §3.6: "recomputes `commitment_met` as true exactly when
        `produced_ytd_kg` is greater than or equal to `annual_commitment_kg` —
        a year-to-date total landing exactly on the commitment counts as met."

        After the second 60 kg completion the total lands exactly on 120 kg
        and commitment_met flips to true.

        Design: Difficulty/transitive_cascade/production_completion_cascade_depth2
        """
        s = _setup_pl_completion_scenario()
        r1 = schedule_run(s["line"]["id"], s["formula"]["id"], s["br1"]["id"],
                          60, "2026-09-07T08:00:00Z", "2026-09-07T11:00:00Z",
                          private_label_agreement_id=s["agr"]["id"])
        complete_run(r1["id"])
        r2 = schedule_run(s["line"]["id"], s["formula"]["id"], s["br2"]["id"],
                          60, "2026-09-07T11:00:00Z", "2026-09-07T14:00:00Z",
                          private_label_agreement_id=s["agr"]["id"])
        complete_run(r2["id"])
        after = get_agreement(s["agr"]["id"])
        assert after["produced_ytd_kg"] == pytest.approx(120.0)
        assert after["commitment_met"] is True
