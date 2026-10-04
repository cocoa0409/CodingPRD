"""Validation priority pairs: state-over-safety and referential-over-temporal."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, create_supplier, create_received_lot, post_test,
    disposition_lot, setup_accepted_lots, create_active_formula,
    create_blend_run, create_committed_blend_run, commit_blend_run,
    create_line, schedule_run, get_line_version, production_run_payload,
    get_lot,
)


def _setup_rejected_lot():
    """Lot moved RECEIVED -> IN_TEST -> REJECTED; all 100 kg written off."""
    supplier = create_supplier(name="Gilroy Garlic", origin_country="US")
    lot = create_received_lot(supplier["id"], spice_code="GARLIC_POWDER",
                              origin_region="Gilroy", quantity_kg=100,
                              flavor_intensity_units=70.0, moisture_pct=7.0,
                              cost_per_kg_cents=120)
    post_test(lot["id"], "MICRO", 80000)
    rejected = disposition_lot(lot["id"], "REJECT", reason="off-spec color")
    return lot["id"], rejected


class TestTerminalLotStateBeatsSafety:
    def test_adulterant_value_on_rejected_lot_returns_lot_terminal(self, api):
        """PRD §3.2: "Attempting to post a test against a `REJECTED` or
        `DEPLETED` lot is rejected with `ERR_LOT_TERMINAL` (HTTP 409)."
        PRD §2.8: "the first check that fails determines the response — later
        checks are not consulted."

        The posted 9.99 ppm would be an adulterant FAIL, but the state guard
        fires first: no SafetyTest row is created, no side effects.

        Design: Difficulty/priority_pair_validation_conflict/terminal_lot_test_state_beats_safety
        """
        lot_id, rejected = _setup_rejected_lot()
        assert rejected["status"] == "REJECTED"
        assert rejected["quantity_wasted_kg"] == pytest.approx(100.0)
        resp = api_client.post_test(
            lot_id, {"test_type": "ADULTERANT_SCREEN", "measured_value": 9.99,
                     "lab_code": "LAB-B"},
            TEST_USERS["quality_analyst_headers"])
        validate_error(resp, ApiErrorId.ERR_LOT_TERMINAL)
        tests = get_success_data(api_client.list_tests(
            lot_id, TEST_USERS["quality_manager_headers"]))
        assert len(tests) == 1
        after = get_lot(lot_id)
        assert after["status"] == "REJECTED"
        assert after["quantity_wasted_kg"] == pytest.approx(100.0)

    def test_disposition_on_rejected_lot_returns_lot_terminal(self, api):
        """PRD §3.2: "a `REJECTED` or `DEPLETED` lot draws `ERR_LOT_TERMINAL`
        instead." PRD §2.8 (lot terminal guard): "posting a test or a
        disposition against a `REJECTED` or `DEPLETED` lot is rejected with
        `ERR_LOT_TERMINAL` (HTTP 409)".

        Design: Difficulty/priority_pair_validation_conflict/terminal_lot_test_state_beats_safety
        """
        lot_id, rejected = _setup_rejected_lot()
        resp = api_client.disposition_lot(
            lot_id, {"action": "ACCEPT"},
            TEST_USERS["quality_manager_headers"])
        validate_error(resp, ApiErrorId.ERR_LOT_TERMINAL)
        after = get_lot(lot_id)
        assert after["status"] == "REJECTED"
        assert after["quantity_remaining_kg"] == pytest.approx(0.0)
        assert after["quantity_wasted_kg"] == pytest.approx(100.0)


def _setup_draft_vs_overlap():
    """COMMITTED blend br1 with a scheduled run at 08:00-12:00, and a second
    blend br2 left DRAFT — one payload that violates both the committed-blend
    gate and window exclusivity."""
    supplier, lots = setup_accepted_lots(costs=(100, 200, 300))
    formula = create_active_formula("REF-1")
    br1 = create_committed_blend_run(formula["id"], "COST_MIN", 100)
    br2 = create_blend_run(formula["id"], "COST_MIN", 100)
    line = create_line(name="Line-V")
    r1 = schedule_run(line["id"], formula["id"], br1["id"], 100,
                      "2026-09-07T08:00:00Z", "2026-09-07T12:00:00Z")
    return {"formula": formula, "br1": br1, "br2": br2, "line": line,
            "r1": r1}


class TestReferentialBeatsTemporal:
    def test_draft_blend_overlapping_window_reports_not_committed(self, api):
        """PRD §2.8: "Every request is evaluated against the following checks
        in the stated order, and the first check that fails determines the
        response — later checks are not consulted. This ordering is observable
        behavior: when two checks could both reject a request, the one listed
        earlier produces the error." PRD §3.5: "the `blend_run_id` (which must
        be `COMMITTED`, else `ERR_BLEND_RUN_NOT_COMMITTED`".

        The payload names a DRAFT blend run AND overlaps the existing run; the
        referential error (check 14) precedes the temporal one (check 15).

        Design: Difficulty/priority_pair_validation_conflict/blend_not_committed_referential_beats_window_conflict
        """
        s = _setup_draft_vs_overlap()
        version = get_line_version(s["line"]["id"])
        payload = production_run_payload(
            s["line"]["id"], s["formula"]["id"], s["br2"]["id"], 100,
            "2026-09-07T10:00:00Z", "2026-09-07T14:00:00Z", version)
        resp = api_client.create_production_run(
            payload, TEST_USERS["production_scheduler_headers"])
        validate_error(resp, ApiErrorId.ERR_BLEND_RUN_NOT_COMMITTED)

    def test_window_conflict_fires_once_blend_is_committed(self, api):
        """PRD §3.5: "Windows on a line are exclusive under half-open
        semantics: the new window must not intersect any non-`CANCELLED` run
        on the same line, though perfect adjacency — a neighbor whose
        `window_end` equals the new `window_start`, or whose `window_start`
        equals the new `window_end` — is allowed; a true overlap is rejected
        with `ERR_LINE_WINDOW_CONFLICT` (HTTP 409)."

        Same payload as its sibling after committing br2: the referential gate
        now passes and the straddling window [10:00,14:00) vs [08:00,12:00) is
        reported instead.

        Design: Difficulty/priority_pair_validation_conflict/blend_not_committed_referential_beats_window_conflict
        """
        s = _setup_draft_vs_overlap()
        commit_blend_run(s["br2"]["id"])
        version = get_line_version(s["line"]["id"])
        payload = production_run_payload(
            s["line"]["id"], s["formula"]["id"], s["br2"]["id"], 100,
            "2026-09-07T10:00:00Z", "2026-09-07T14:00:00Z", version)
        resp = api_client.create_production_run(
            payload, TEST_USERS["production_scheduler_headers"])
        validate_error(resp, ApiErrorId.ERR_LINE_WINDOW_CONFLICT)
