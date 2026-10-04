"""Difficulty depth index: compensating invariants — a warranty's two shares
always summing to its exposure across adjudication re-splits, and the
project's committed exposure ledger returning to net zero over the claim
lifecycle.
"""
from test_helpers import (
    ApiClient,
    adjudicate,
    assert_cents,
    begin_evidence,
    claim_warranty,
    create_world,
    drive_to_completed_work_order,
    issue_warranty,
    read_investigation,
    read_project,
    read_warranty,
    void_warranty,
)


def test_warranty_share_sum_invariant_across_adjudication(api: ApiClient):
    """PRD §3.7: "The split into shares follows one invariant at all times:
    `material_share_cents` plus `application_share_cents` must equal
    `exposure_cents` exactly."
    PRD §3.7: "When an adjudication later sets the fault percentage to some
    value f, the manufacturer's share is recomputed as the exposure multiplied
    by f and divided by 100, rounded half-up, with the applicator's share
    again taking the remainder."

    Design: Difficulty/compensating_invariant/warranty_share_sum_invariant_across_adjudication
    """
    world = create_world(
        api,
        warranty_budget_cents=500_000,
        system_overrides={"system_code": "SW-INV-100"},
        applicator_overrides={"company_name": "Invariant Applicators"},
    )
    completion = drive_to_completed_work_order(api, world, asset_zone="DECK-CENTER")
    warranty = issue_warranty(
        api, world["project"]["id"], completion["work_order"]["id"],
        term_years=15, exposure_cents=200_003,
    )

    # Issuance at the default 50: round_half_up(200003 * 0.50) == 100002.
    assert_cents(warranty["material_share_cents"], 100_002, "material_share_cents at issuance")
    assert_cents(warranty["application_share_cents"], 100_001, "application_share_cents at issuance")
    assert warranty["material_share_cents"] + warranty["application_share_cents"] == 200_003

    claim_warranty(
        api, world["project"]["id"], warranty["id"],
        defect_mode="CORROSION_UNDERFILM", evidence_notes="underfilm creep at scribe",
    )
    investigation = begin_evidence(
        api, warranty["id"], read_investigation(api, warranty["id"])["id"]
    )
    adjudicate(api, warranty["id"], investigation["id"], "SHARED", adjudicated_fault_pct=30)

    resolved = read_warranty(api, warranty["id"])
    assert resolved["status"] == "RESOLVED"
    assert resolved["manufacturer_fault_pct"] == 30
    # round_half_up(200003 * 30 / 100) == round_half_up(60000.9) == 60001.
    assert_cents(resolved["material_share_cents"], 60_001, "material_share_cents after re-split")
    assert_cents(resolved["application_share_cents"], 140_002, "application_share_cents after re-split")
    assert (
        resolved["material_share_cents"] + resolved["application_share_cents"]
        == resolved["exposure_cents"] == 200_003
    ), "the compensating re-split changes the shares but never the total"


def test_project_committed_exposure_net_zero_lifecycle(api: ApiClient):
    """PRD §3.4: "that committed figure is recomputed as the sum of
    `exposure_cents` across all of the project's warranties in `ACTIVE` or
    `CLAIMED` status."
    PRD §3.7: "Either way — resolved or denied — the warranty's
    `exposure_cents` is released from the project's
    `committed_warranty_exposure_cents`, because only warranties still in
    `ACTIVE` or `CLAIMED` count against the budget."

    Design: Difficulty/compensating_invariant/project_committed_exposure_net_zero_lifecycle
    """
    world = create_world(
        api,
        warranty_budget_cents=100_000,
        system_overrides={"system_code": "SW-LIFE-100"},
        applicator_overrides={"company_name": "Lifecycle Coaters"},
    )
    project_id = world["project"]["id"]
    completion_1 = drive_to_completed_work_order(api, world, asset_zone="BAY-ALPHA")
    completion_2 = drive_to_completed_work_order(api, world, asset_zone="BAY-BETA")
    warranty_1 = issue_warranty(
        api, project_id, completion_1["work_order"]["id"], term_years=5, exposure_cents=70_000
    )
    warranty_2 = issue_warranty(
        api, project_id, completion_2["work_order"]["id"], term_years=3, exposure_cents=30_000
    )
    assert read_project(api, project_id)["committed_warranty_exposure_cents"] == 100_000

    # The claim alone releases nothing: CLAIMED still counts.
    claim_warranty(
        api, project_id, warranty_1["id"],
        defect_mode="CRACKING", evidence_notes="hairline cracking panel 4",
    )
    assert read_project(api, project_id)["committed_warranty_exposure_cents"] == 100_000

    # NO_DEFECT adjudication denies the claim and releases the 70000.
    investigation = begin_evidence(
        api, warranty_1["id"], read_investigation(api, warranty_1["id"])["id"]
    )
    adjudicate(api, warranty_1["id"], investigation["id"], "NO_DEFECT")
    assert read_warranty(api, warranty_1["id"])["status"] == "DENIED"
    assert read_project(api, project_id)["committed_warranty_exposure_cents"] == 30_000

    # Voiding the second warranty releases the remaining 30000: net zero.
    void_warranty(api, project_id, warranty_2["id"], "applicator fraud documented in audit")
    assert read_warranty(api, warranty_2["id"])["status"] == "VOIDED"
    assert read_project(api, project_id)["committed_warranty_exposure_cents"] == 0
