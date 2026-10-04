"""Cascade unwinding on lot release and auto-recall dedupe on repeated FAIL."""
from test_helpers import (
    validate_success, TEST_USERS, setup_produced_batch, post_test,
    disposition_lot, get_lot, get_batch, get_recall_case, list_recall_cases,
)


def _setup_cascade(product_code):
    """Produced batch held by an adulterant FAIL on its first genealogy lot;
    one auto-created DRAFT recall case names that lot."""
    s = setup_produced_batch(product_code=product_code)
    la = s["lots"][0]
    post_test(la["id"], "ADULTERANT_SCREEN", 2.5, lab_code="LAB-B",
              analyst_id="qa-1")
    cases = list_recall_cases(params={"suspect_lot_id": la["id"]})
    assert len(cases) == 1
    return s, la, cases[0]


class TestLotReleaseReversesCascade:
    def test_release_unwinds_hold_and_auto_closes_recall(self, api):
        """PRD §3.7: "every finished batch held specifically because of that
        lot — `quality_hold_cause` `LOT_QUARANTINE` with `quality_hold_lot_id`
        equal to the released lot — and not covered by any `INITIATED` recall
        case returns to `CLEAR`, with `quality_hold_cause` reset to `NONE` and
        `quality_hold_lot_id` to null; and every `DRAFT` recall case with
        `source` `AUTO_QUARANTINE` naming the released lot auto-closes".
        PRD §3.2: "A test posted while the lot is `QUARANTINED` — a retest —
        moves it back to `IN_TEST`."

        An exonerating retest (latest ADULTERANT_SCREEN PASS) plus ACCEPT
        release unwinds the whole cascade.

        Design: Corner/state_machines/lot_release_reverses_adulterant_cascade
        """
        s, la, case = _setup_cascade("REL-1")
        batch = s["batch"]
        assert get_batch(batch["id"])["quality_status"] == "QUALITY_HOLD"
        assert case["status"] == "DRAFT"
        retest = post_test(la["id"], "ADULTERANT_SCREEN", 0.5,
                           lab_code="LAB-C", analyst_id="qa-1")
        assert retest["result"] == "PASS"
        released = disposition_lot(la["id"], "ACCEPT", manager_id="qm-1",
                                   reason="composite resample exonerates")
        assert released["status"] == "ACCEPTED"
        unwound = get_batch(batch["id"])
        assert unwound["quality_status"] == "CLEAR"
        assert unwound["quality_hold_cause"] == "NONE"
        assert unwound["quality_hold_lot_id"] is None
        closed = get_recall_case(case["id"])
        assert closed["status"] == "CLOSED"
        assert closed["affected_batch_ids"] == []
        assert closed["affected_quantity_kg"] == 0


class TestAutoRecallCaseDedupe:
    def test_repeated_fail_creates_no_second_case(self, api):
        """PRD §3.7: "If at least one batch was held and no recall case in
        `DRAFT` or `INITIATED` already names that lot as its `suspect_lot_id`,
        the system auto-creates a recall case". PRD §3.7: "Every finished
        batch whose `genealogy_lot_ids` contains that lot and whose
        `quality_status` is `CLEAR` moves to `QUALITY_HOLD`".

        A second ADULTERANT_SCREEN FAIL re-quarantines the lot but the open
        DRAFT case blocks a duplicate, and the already-held (non-CLEAR) batch
        is not re-touched.

        Design: Corner/state_machines/auto_recall_case_deduped_on_repeated_fail
        """
        s, la, case = _setup_cascade("DED-1")
        second = post_test(la["id"], "ADULTERANT_SCREEN", 3.1,
                           lab_code="LAB-C", analyst_id="qa-1")
        assert second["result"] == "FAIL"
        assert get_lot(la["id"])["status"] == "QUARANTINED"
        cases = list_recall_cases(params={"suspect_lot_id": la["id"]})
        assert len(cases) == 1
        assert cases[0]["id"] == case["id"]
        assert get_batch(s["batch"]["id"])["quality_status"] == "QUALITY_HOLD"
