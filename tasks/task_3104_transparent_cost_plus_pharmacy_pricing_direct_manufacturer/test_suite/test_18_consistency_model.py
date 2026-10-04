"""Queue B — consistency_model section (1 non-stub instance)."""
from test_helpers import (
    create_drug,
    create_manufacturer,
    create_patient,
    create_prescriber,
    create_prescription,
    create_sourced_price,
    get_success_data,
    validate_success,
    reset_clock,
    OPS,
    PHARMACIST,
)


class TestImmediateConsistency:

    def test_expansion_response_already_carries_every_recomputed_field(self, api):
        """PRD §2.8: "Any server-side reconciliation that changes a derived field
        on a resource is a mutation like any other: it refreshes that resource's
        updated_at and increments its version."
        PRD §3.3: "On success the drug's packaging is set from the selected
        primary price row, and effective_unit_cost_cents, ship_interval_days and
        expansion_score are recomputed."

        Design: Corner/consistency_model/immediate_consistency_reads_reflect_the_write_before_the_response_returns
        """
        reset_clock()
        ctx = gate_passing_drug(api)
        admitted = validate_success(api.expand_formulary(ctx["drug"]["id"], OPS))
        assert admitted["state"] == "FORMULARY"
        assert admitted["packaging"] == "500-count bottle"
        assert admitted["effective_unit_cost_cents"] == 12

    def test_a_follow_up_read_returns_the_identical_values(self, api):
        """PRD §2.4: "updated_at is an ISO 8601 UTC timestamp with three
        fractional digits, refreshed on every mutation of the resource"

        Design: Corner/consistency_model/immediate_consistency_reads_reflect_the_write_before_the_response_returns
        """
        reset_clock()
        ctx = gate_passing_drug(api)
        admitted = validate_success(api.expand_formulary(ctx["drug"]["id"], OPS))
        fetched = get_success_data(api.get_drug(ctx["drug"]["id"], OPS))

        for field in ("state", "packaging", "effective_unit_cost_cents",
                      "ship_interval_days", "expansion_score"):
            assert fetched[field] == admitted[field], (
                f"{field} must be settled inside the mutating request, with no "
                "follow-up reconciliation read required"
            )
        assert fetched["ship_interval_days"] == 14, (
            "the C-tier base of 21 with the at-least-200-units adjustment of -7 "
            "is 14 days"
        )


# ─── local helpers ────────────────────────────────────

def gate_passing_drug(api):
    """A NON_FORMULARY drug with a 500-unit C-tier pool and 250 units of demand,
    so the admission gate passes at score 2."""
    manufacturer = create_manufacturer()
    drug = create_drug()
    create_sourced_price(drug["id"], manufacturer["id"], unit_cost_cents=12,
                         available_units=500, reliability_tier="C",
                         packaging="500-count bottle")
    patient = create_patient()
    prescriber = create_prescriber()
    rx = create_prescription(patient["id"], prescriber["id"], drug["id"],
                             total_refills_authorized=1, ship_state_code="CA")
    rq = get_success_data(api.create_intake_request(rx["id"], 250, OPS))
    get_success_data(api.review_intake_request(rq["id"], PHARMACIST))
    get_success_data(api.accept_intake_request(rq["id"], PHARMACIST))
    return {"drug": drug, "prescription": rx}