"""Validation-cascade ordering: when two checks would fail at once, the
higher-priority check's error surfaces (PRD section 2.6).

Queue A — difficulty design rule ``priority_pair_validation_conflict``.
"""

from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_field_rep_headers,
    validate_error,
)
from test_helpers import fixtures as fx
from test_helpers import factories as f
from test_helpers.test_users import QA_HEADERS


class TestStaleVersionBeatsLotNotReleasable:
    """A transfer request that is both stale-versioned and against a
    QUARANTINED lot must surface the OCC error (priority 5) before the
    releasability rule (checked later)."""

    def _setup_quarantined_lot(self, api):
        ctx = fx.setup_two_reps_with_lot(api, sender_issued=20, lot_quantity=100)
        excursion = fx.report_excursion(
            api,
            ctx["sender"],
            ctx["product"]["id"],
            location_type="HOME_OFFICE",
            observed_temp_c=15.0,
            excursion_minutes=45,
        )
        fx.assess_excursion(api, excursion["id"])
        lot = get_success_data(
            api.get_sample_lot(ctx["lot"]["id"], headers=QA_HEADERS)
        )
        assert lot["status"] == "QUARANTINED"
        return ctx

    def test_stale_version_returned_for_quarantined_lot(self, api):
        """PRD section 2.6: "The cascade evaluates, in order: ... (5)
        optimistic-concurrency version match, producing ERR_STALE_VERSION; (6)
        state-machine legality ... and only then (7 onward) the business-safety,
        temporal, referential, and fiscal rules described in §3." and "a stale
        version is reported before any state-machine complaint."

        Design: Difficulty/priority_pair_validation_conflict/stale_version_state_beats_safety_lot_not_releasable
        """
        ctx = self._setup_quarantined_lot(api)
        response = api.create_sample_transfer(
            f.create_sample_transfer_payload(
                ctx["receiver"]["id"],
                ctx["lot"]["id"],
                5,
                1,  # version 1 is long behind after issuance + quarantine
            ),
            headers=make_field_rep_headers(ctx["sender"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_STALE_VERSION)

    def test_current_version_against_quarantined_lot_reports_releasability(self, api):
        """PRD section 3.2: "This releasability check is enforced at four points —
        recording a disbursement, capturing a signature, requesting a transfer, and
        accepting a transfer — and failure at any of them is rejected with
        ERR_LOT_NOT_RELEASABLE."

        Design: Difficulty/priority_pair_validation_conflict/stale_version_state_beats_safety_lot_not_releasable
        """
        ctx = self._setup_quarantined_lot(api)
        current_version = fx.fresh_lot_version(api, ctx["lot"]["id"])
        response = api.create_sample_transfer(
            f.create_sample_transfer_payload(
                ctx["receiver"]["id"],
                ctx["lot"]["id"],
                5,
                current_version,
            ),
            headers=make_field_rep_headers(ctx["sender"]["id"]),
        )
        # With a fresh version the OCC check passes and the releasability rule
        # is reached — proving the two failures are genuinely different checks.
        validate_error(response, ApiErrorId.ERR_LOT_NOT_RELEASABLE)


class TestEligibilityBeatsQuantityCap:
    """A disbursement for a PENDING_REVIEW prescriber whose quantity also
    exceeds the per-visit cap reports the eligibility failure."""

    def _setup(self, api):
        # Prescriber never verified: stays PENDING_REVIEW.
        region, territory, manager = fx.setup_manager_territory(api, budget=500)
        rep = fx.create_representative(api, territory["id"])
        prescriber = fx.create_prescriber(api)
        product = fx.create_product(api, per_visit_max_units=10)
        lot = fx.create_sample_lot(api, product["id"], quantity_received=100)
        fx.issue_lot_to_rep(api, rep["id"], lot["id"], 50)
        entry = fx.add_target_entry(
            api,
            territory["id"],
            prescriber["id"],
            product["id"],
            manager,
            tier="A",
            planned_sample_units=100,
        )
        plan = fx.create_plan(api, territory["id"], territory["version"], manager)
        fx.publish_plan(api, plan["id"], manager)
        visit = fx.schedule_visit(api, plan["id"], entry["id"], rep)
        return {
            "rep": rep,
            "prescriber": prescriber,
            "lot": lot,
            "visit": visit,
            "entry": entry,
        }

    def test_pending_prescriber_and_over_cap_reports_eligibility(self, api):
        """PRD section 3.2: "Only an ELIGIBLE prescriber may receive samples, and the
        check is performed both when a disbursement is recorded and again when the
        visit is completed — either point of enforcement rejects with
        ERR_PRESCRIBER_NOT_ELIGIBLE."

        Design: Difficulty/priority_pair_validation_conflict/safety_eligibility_beats_fiscal_quantity_cap
        """
        ctx = self._setup(api)
        response = api.create_sample_disbursement(
            f.create_sample_disbursement_payload(
                ctx["visit"]["id"], ctx["lot"]["id"], 25
            ),
            headers=make_field_rep_headers(ctx["rep"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_PRESCRIBER_NOT_ELIGIBLE)

    def test_completion_gate_also_enforces_live_eligibility(self, api):
        """PRD section 3.4: "The prescriber must be ELIGIBLE at completion time
        (otherwise ERR_PRESCRIBER_NOT_ELIGIBLE)."

        Design: Difficulty/priority_pair_validation_conflict/safety_eligibility_beats_fiscal_quantity_cap
        """
        ctx = self._setup(api)
        response = api.complete_call_visit(
            ctx["visit"]["id"],
            headers=make_field_rep_headers(ctx["rep"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_PRESCRIBER_NOT_ELIGIBLE)
        visit = get_success_data(
            api.get_call_visit(
                ctx["visit"]["id"],
                headers=make_field_rep_headers(ctx["rep"]["id"]),
            )
        )
        assert visit["call_status"] == "SCHEDULED"
