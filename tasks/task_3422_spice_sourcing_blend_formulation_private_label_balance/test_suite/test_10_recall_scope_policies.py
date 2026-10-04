"""Recall scope dual variant: FINAL direct genealogy vs PROVISIONAL cohort."""
import pytest
from test_helpers import (
    api_client, validate_success, TEST_USERS, create_supplier,
    create_accepted_lot, create_active_formula, create_committed_blend_run,
    create_line, schedule_run, complete_run, batch_for_run,
    recall_case_payload,
)


def _setup_two_cohort_batches():
    """B1 genealogy {l1, la, lb} (dearer lots, committed first); B2 genealogy
    {l2, lc, ld} (cheaper lots accepted only after the first commit). All six
    lots share supplier, BLACK_PEPPER and crop year 2025."""
    supplier = create_supplier(name="Andes Spice Co", origin_country="PE")
    l1 = create_accepted_lot(supplier["id"], cost_per_kg_cents=900)
    la = create_accepted_lot(supplier["id"], cost_per_kg_cents=910)
    lb = create_accepted_lot(supplier["id"], cost_per_kg_cents=920)
    formula = create_active_formula("PEP-C")
    br1 = create_committed_blend_run(formula["id"], "COST_MIN", 50)
    l2 = create_accepted_lot(supplier["id"], cost_per_kg_cents=100)
    lc = create_accepted_lot(supplier["id"], cost_per_kg_cents=110)
    ld = create_accepted_lot(supplier["id"], cost_per_kg_cents=120)
    br2 = create_committed_blend_run(formula["id"], "COST_MIN", 50)
    line = create_line(name="Line-R")
    r1 = schedule_run(line["id"], formula["id"], br1["id"], 50,
                      "2026-09-07T08:00:00Z", "2026-09-07T11:00:00Z")
    complete_run(r1["id"])
    b1 = batch_for_run(r1["id"])
    r2 = schedule_run(line["id"], formula["id"], br2["id"], 50,
                      "2026-09-07T11:00:00Z", "2026-09-07T14:00:00Z")
    complete_run(r2["id"])
    b2 = batch_for_run(r2["id"])
    return {"l1": l1, "la": la, "lb": lb, "l2": l2, "lc": lc, "ld": ld,
            "b1": b1, "b2": b2}


def _open_and_initiate(scope_policy, suspect_lot_id):
    resp = api_client.create_recall_case(
        recall_case_payload(trigger_type="LOT_SUSPECT",
                            scope_policy=scope_policy,
                            suspect_lot_id=suspect_lot_id),
        TEST_USERS["recall_coordinator_headers"])
    case = validate_success(resp, 201)
    return validate_success(api_client.initiate_recall_case(
        case["id"], TEST_USERS["recall_coordinator_headers"]), 200)


class TestRecallScopePolicies:
    def test_final_scope_uses_direct_genealogy_only(self, api):
        """PRD §3.7: "The base suspect set is the suspect lot alone when
        `suspect_lot_id` was given". PRD §3.7: "Under the `FINAL` policy — the
        confirmed legal scope — the affected batches are exactly those whose
        `genealogy_lot_ids` intersect that base set."

        Suspect l1 reached only B1: FINAL freezes affected_batch_ids to [B1]
        and 50 kg.

        Design: Difficulty/dual_variant_calc/recall_scope_provisional_vs_final
        """
        s = _setup_two_cohort_batches()
        # B1 genealogy proves the second batch never touched the suspect lot:
        assert s["b1"]["genealogy_lot_ids"] == [
            s["l1"]["id"], s["la"]["id"], s["lb"]["id"]]
        assert s["l1"]["id"] not in s["b2"]["genealogy_lot_ids"]
        fin = _open_and_initiate("FINAL", s["l1"]["id"])
        assert fin["affected_batch_ids"] == [s["b1"]["id"]]
        assert fin["affected_quantity_kg"] == pytest.approx(50.0)

    def test_provisional_scope_widens_by_cohort(self, api):
        """PRD §3.7: "Under the `PROVISIONAL` policy — forward-looking cohort
        suspicion used while an investigation is open — the base set is first
        widened by a cohort: for each suspect lot, every raw lot in any status
        except `REJECTED` that shares the suspect's `supplier_id`,
        `spice_code`, and `crop_year` joins the suspect set". PRD §3.7:
        "`PROVISIONAL` is therefore always a superset of `FINAL`, and the two
        diverge whenever a cohort lot reached a different batch."

        Same suspect, same database: PROVISIONAL sweeps in the cohort lots
        l2/lc/ld and therefore B2 — 2 batches, 100 kg, a strict superset of
        the FINAL scope.

        Design: Difficulty/dual_variant_calc/recall_scope_provisional_vs_final
        """
        s = _setup_two_cohort_batches()
        fin = _open_and_initiate("FINAL", s["l1"]["id"])
        pro = _open_and_initiate("PROVISIONAL", s["l1"]["id"])
        assert len(pro["affected_batch_ids"]) == 2
        assert s["b1"]["id"] in pro["affected_batch_ids"]
        assert s["b2"]["id"] in pro["affected_batch_ids"]
        assert pro["affected_quantity_kg"] == pytest.approx(100.0)
        assert set(fin["affected_batch_ids"]) < set(pro["affected_batch_ids"])
