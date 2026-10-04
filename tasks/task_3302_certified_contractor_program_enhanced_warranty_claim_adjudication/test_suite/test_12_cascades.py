"""Difficulty queue A: transitive cascades — complaint cascade and adjudication decertification."""
from test_helpers import (
    adjudicate,
    assign_lead,
    create_complaint_payload,
    create_distributor_payload,
    file_claim_with_photos,
    get_remedy,
    get_success_data,
    make_certified_contractor,
    set_clock,
    setup_active_registration,
)


def test_complaint_cascade_suspends_contractor_and_certification(api, program_admin_headers, claimant_headers):
    """PRD §3.7: "Otherwise, if the recomputed weighted score has reached 5 and the
    contractor is currently `ACTIVE`, the contractor is `SUSPENDED` and the suspension
    cascade fires. The suspension cascade moves every `ACTIVE` certification of the
    contractor to `SUSPENDED` — each with its `version` incremented — and returns
    every `ASSIGNED` lead assignment of the contractor to `RETURNED`, recomputing
    each owning distributor's `lead_pool_available`."

    Design: Difficulty/transitive_cascade/complaint_substantiation_cascade_suspends_contractor_cert_and_recalls_lead
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = make_certified_contractor(tier="GOLD")
    contractor, cert = ctx["contractor"], ctx["certification"]
    cmp_old = get_success_data(api.create_complaint(
        create_complaint_payload(contractor_id=contractor["id"], category="WORKMANSHIP"), claimant_headers))
    set_clock("2027-06-01T00:00:00Z")
    cmp_new = get_success_data(api.create_complaint(
        create_complaint_payload(contractor_id=contractor["id"], category="PROPERTY_DAMAGE"), claimant_headers))
    set_clock("2027-08-01T00:00:00Z")
    get_success_data(api.substantiate_complaint(cmp_old["id"], program_admin_headers))
    get_success_data(api.substantiate_complaint(cmp_new["id"], program_admin_headers))

    cnow = get_success_data(api.get_contractor(contractor["id"], program_admin_headers))
    assert cnow["complaint_score_24mo"] == 5
    assert cnow["status"] == "SUSPENDED"
    cert_now = get_success_data(api.get_certification(cert["id"], program_admin_headers))
    assert cert_now["status"] == "SUSPENDED"


def test_complaint_cascade_recalls_lead_and_restores_pool(api, program_admin_headers, claimant_headers):
    """PRD §3.7: "The suspension cascade moves every `ACTIVE` certification of the
    contractor to `SUSPENDED` — each with its `version` incremented — and returns
    every `ASSIGNED` lead assignment of the contractor to `RETURNED`, recomputing
    each owning distributor's `lead_pool_available`." PRD §3.8: "Returns also arrive
    by cascade from §3.7 when a contractor is suspended or revoked; the pool math is
    identical regardless of who initiated the return."

    Design: Difficulty/transitive_cascade/complaint_substantiation_cascade_suspends_contractor_cert_and_recalls_lead
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = make_certified_contractor(tier="GOLD")
    contractor = ctx["contractor"]
    dist = get_success_data(api.create_distributor(
        create_distributor_payload(name="Dist 1", territory_codes=["T1"], lead_pool_total=1),
        program_admin_headers))
    lead = assign_lead(dist["id"], contractor["id"], territory_code="T1", required_tier="SILVER")
    mid = get_success_data(api.get_distributor(dist["id"], program_admin_headers))
    assert mid["lead_pool_available"] == 0

    cmp_old = get_success_data(api.create_complaint(
        create_complaint_payload(contractor_id=contractor["id"], category="WORKMANSHIP"), claimant_headers))
    set_clock("2027-06-01T00:00:00Z")
    cmp_new = get_success_data(api.create_complaint(
        create_complaint_payload(contractor_id=contractor["id"], category="PROPERTY_DAMAGE"), claimant_headers))
    set_clock("2027-08-01T00:00:00Z")
    get_success_data(api.substantiate_complaint(cmp_old["id"], program_admin_headers))
    get_success_data(api.substantiate_complaint(cmp_new["id"], program_admin_headers))

    lead_now = get_success_data(api.get_lead_assignment(lead["id"], program_admin_headers))
    assert lead_now["status"] == "RETURNED"
    dist_now = get_success_data(api.get_distributor(dist["id"], program_admin_headers))
    assert dist_now["lead_pool_available"] == 1


def test_installation_error_adjudication_decertifies_at_score_60(api, program_admin_headers, claimant_headers):
    """PRD §3.6 step 8: "Only after the allocation is persisted does the system apply
    the workmanship delta to the contractor: minus 10 for `INSTALLATION_ERROR`, minus
    4 for `MIXED`, and zero for `MANUFACTURER_DEFECT`, with the score never falling
    below its floor of 0. ... Finally, if the determination was `INSTALLATION_ERROR`
    or `MIXED` and the contractor's resulting `workmanship_score` is 60 or below,
    every `ACTIVE` certification of the contractor transitions to `SUSPENDED` — each
    with its `version` incremented."

    Design: Difficulty/transitive_cascade/installation_error_adjudication_cascade_decertifies_at_score_60
    """
    ctx = setup_active_registration(tier="BRONZE")
    reg = ctx["registration"]
    cert = ctx["certification"]
    set_clock("2027-09-10T00:00:00Z")
    for i in range(4):
        info = file_claim_with_photos(reg["id"], claim_labor_cost_cents=10000,
                                      file_at=None, description=f"c{i+1}")
        claim, cv = info["claim"], info["version"]
        adjudicate(claim["id"], "INSTALLATION_ERROR", cv)
    cnow = get_success_data(api.get_contractor(ctx["contractor"]["id"], program_admin_headers))
    assert cnow["workmanship_score"] == 60
    cert_now = get_success_data(api.get_certification(cert["id"], program_admin_headers))
    assert cert_now["status"] == "SUSPENDED"


def test_installation_error_liability_uses_filing_score_snapshot_bands(api, program_admin_headers, claimant_headers):
    """PRD §3.6 step 7: "The liability factor is read from a band of the claim's
    `filing_workmanship_score` — the intake snapshot, never the live score: 1.00 when
    the snapshot is 80 or higher, 1.10 when the snapshot is between 61 and 79
    inclusive, and 1.25 when the snapshot is 60 or below. `contractor_liability_cents`
    is the complement of the determination share (one minus the share) applied to the
    sum of the total installed material cost and the `claim_labor_cost_cents`, then
    multiplied by that factor, rounded half up to a whole cent."

    Design: Difficulty/transitive_cascade/installation_error_adjudication_cascade_decertifies_at_score_60
    """
    ctx = setup_active_registration(tier="BRONZE")
    reg = ctx["registration"]
    set_clock("2027-09-10T00:00:00Z")
    for i in range(4):
        info = file_claim_with_photos(reg["id"], claim_labor_cost_cents=10000,
                                      file_at=None, description=f"c{i+1}")
        claim, cv = info["claim"], info["version"]
        adjudicate(claim["id"], "INSTALLATION_ERROR", cv)
    cnow = get_success_data(api.get_contractor(ctx["contractor"]["id"], program_admin_headers))
    # liabilities: 110000 (snapshots 100/90/80 at factor 1.00) x3 + 121000 (snapshot 70 at 1.10)
    assert cnow["outstanding_liability_cents"] == 451000
