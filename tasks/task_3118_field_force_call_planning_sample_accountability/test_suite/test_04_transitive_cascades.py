"""Transitive cascades: signature capture reaching the prescriber's annual
cap, and CRITICAL excursion assessment quarantining stock in flight.

Queue A — difficulty design rule ``transitive_cascade``.
"""

from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_field_rep_headers,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers import factories as f
from test_helpers.test_users import COMPLIANCE_HEADERS, QA_HEADERS


class TestSignatureAnnualCapCascade:
    """SIGNED -> YTD hits annual max -> prescriber INELIGIBLE -> future
    SCHEDULED visits for that prescriber auto-CANCELLED."""

    def _setup(self, api):
        ctx = fx.setup_published_plan_with_rep(
            api,
            tier="A",
            planned_sample_units=60,
            budget=300,
            rep_issue_qty=30,
            lot_quantity=100,
            per_visit_max_units=10,
            annual_max_units_per_prescriber=20,
        )
        # PRD §3.5 caps each disbursement at per_visit_max_units (10), so
        # reaching the annual cap of 20 requires two 10-unit visits. Each
        # visit is completed at the logical-clock instant inside its
        # scheduled window.
        disbursements = []
        for day in ("2026-09-02", "2026-09-03"):
            visit = fx.schedule_visit(
                api,
                ctx["plan"]["id"],
                ctx["entry"]["id"],
                ctx["rep"],
                scheduled_start=f"{day}T08:00:00Z",
                scheduled_end=f"{day}T09:00:00Z",
            )
            fx.set_clock(api, f"{day}T08:30:00Z")
            fx.complete_visit(api, visit["id"], ctx["rep"])
            disbursements.append(
                get_success_data(
                    api.create_sample_disbursement(
                        f.create_sample_disbursement_payload(
                            visit["id"], ctx["lot"]["id"], 10
                        ),
                        headers=make_field_rep_headers(ctx["rep"]["id"]),
                    )
                )
            )
        disbursement = disbursements[0]
        future_visit = fx.schedule_visit(
            api,
            ctx["plan"]["id"],
            ctx["entry"]["id"],
            ctx["rep"],
            scheduled_start="2026-09-10T08:00:00Z",
            scheduled_end="2026-09-10T09:00:00Z",
        )
        ctx["visit"] = visit
        ctx["disbursement"] = disbursement
        ctx["second_disbursement"] = disbursements[1]
        ctx["future_visit"] = future_visit
        return ctx

    def test_signature_flips_prescriber_ineligible_at_annual_cap(self, api):
        """PRD section 3.5: "Third, the prescriber's year-to-date usage is increased;
        if it reaches or exceeds the product's annual_max_units_per_prescriber, the
        prescriber's eligibility_status flips to INELIGIBLE."

        Design: Difficulty/transitive_cascade/signature_capture_annual_cap_cascade_cancels_future_visits
        """
        ctx = self._setup(api)
        data = fx.sign_disbursement(api, ctx["disbursement"]["id"], ctx["rep"])
        assert data["reconciliation_status"] == "SIGNED"
        prescriber = get_success_data(
            api.get_prescriber(ctx["prescriber"]["id"], headers=COMPLIANCE_HEADERS)
        )
        assert prescriber["eligibility_status"] == "ELIGIBLE"
        data = fx.sign_disbursement(
            api, ctx["second_disbursement"]["id"], ctx["rep"]
        )
        assert data["reconciliation_status"] == "SIGNED"
        prescriber = get_success_data(
            api.get_prescriber(ctx["prescriber"]["id"], headers=COMPLIANCE_HEADERS)
        )
        assert prescriber["eligibility_status"] == "INELIGIBLE"

    def test_signature_cascade_cancels_future_visits(self, api):
        """PRD section 3.5: "and when that happens, every still-SCHEDULED future visit
        for that prescriber is automatically CANCELLED."

        Design: Difficulty/transitive_cascade/signature_capture_annual_cap_cascade_cancels_future_visits
        """
        ctx = self._setup(api)
        fx.sign_disbursement(api, ctx["disbursement"]["id"], ctx["rep"])
        fx.sign_disbursement(api, ctx["second_disbursement"]["id"], ctx["rep"])
        future = get_success_data(
            api.get_call_visit(
                ctx["future_visit"]["id"],
                headers=make_field_rep_headers(ctx["rep"]["id"]),
            )
        )
        assert future["call_status"] == "CANCELLED"


class TestCriticalExcursionCascade:
    """CRITICAL assess -> held lots QUARANTINED -> PENDING_SIGNATURE
    disbursements VOIDED -> REQUESTED transfers auto-CANCELLED."""

    def _setup(self, api):
        ctx = fx.setup_published_plan_with_rep(
            api,
            tier="B",
            planned_sample_units=30,
            budget=300,
            rep_issue_qty=25,
            lot_quantity=200,
            per_visit_max_units=8,
            annual_max_units_per_prescriber=80,
        )
        # A second rep in a second territory receives the transfer.
        region = ctx["region"]
        t_receiver = fx.create_territory(api, region["id"])
        receiver = fx.create_representative(api, t_receiver["id"])
        ctx["receiver"] = receiver

        visit = fx.schedule_visit(
            api, ctx["plan"]["id"], ctx["entry"]["id"], ctx["rep"]
        )
        fx.complete_visit(api, visit["id"], ctx["rep"])
        disbursement = get_success_data(
            api.create_sample_disbursement(
                f.create_sample_disbursement_payload(
                    visit["id"], ctx["lot"]["id"], 3
                ),
                headers=make_field_rep_headers(ctx["rep"]["id"]),
            )
        )
        transfer = fx.request_transfer(
            api, ctx["rep"], receiver, ctx["lot"], 5
        )
        # CRITICAL: 14.0C is 6.0 degrees above the 8.0 band ceiling (> 5.0).
        excursion = fx.report_excursion(
            api,
            ctx["rep"],
            ctx["product"]["id"],
            location_type="VEHICLE",
            observed_temp_c=14.0,
            excursion_minutes=60,
        )
        ctx["disbursement"] = disbursement
        ctx["transfer"] = transfer
        ctx["excursion"] = excursion
        return ctx

    def test_assess_quarantines_held_lots(self, api):
        """PRD section 3.7: "When a CRITICAL excursion is assessed, a three-hop
        cascade fires: first, every lot of the excursion's product_id in the
        reporting rep's custody with a qty_available_forward greater than zero is
        moved to QUARANTINED with quarantine_reason TEMPERATURE_EXCURSION."

        Design: Difficulty/transitive_cascade/critical_excursion_quarantine_voids_disbursements_and_cancels_transfers
        """
        ctx = self._setup(api)
        assessed = fx.assess_excursion(api, ctx["excursion"]["id"])
        assert assessed["severity"] == "CRITICAL"
        assert assessed["status"] == "ASSESSED"
        lot = get_success_data(
            api.get_sample_lot(ctx["lot"]["id"], headers=QA_HEADERS)
        )
        assert lot["status"] == "QUARANTINED"
        assert lot["quarantine_reason"] == "TEMPERATURE_EXCURSION"

    def test_assess_voids_pending_disbursements_and_cancels_transfers(self, api):
        """PRD section 3.7: "second, every PENDING_SIGNATURE disbursement referencing
        a quarantined lot is VOIDED; and third, every REQUESTED transfer referencing
        a quarantined lot is automatically CANCELLED."

        Design: Difficulty/transitive_cascade/critical_excursion_quarantine_voids_disbursements_and_cancels_transfers
        """
        ctx = self._setup(api)
        fx.assess_excursion(api, ctx["excursion"]["id"])
        disbursement = get_success_data(
            api.get_sample_disbursement(
                ctx["disbursement"]["id"], headers=COMPLIANCE_HEADERS
            )
        )
        assert disbursement["reconciliation_status"] == "VOIDED"
        transfer = get_success_data(
            api.get_sample_transfer(ctx["transfer"]["id"], headers=COMPLIANCE_HEADERS)
        )
        assert transfer["status"] == "CANCELLED"
