"""Difficulty tests (queue A): cyclic state machines (rework loop,
verification rejection loop) and transitive cascades."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_shop, create_certified_shop, create_technician, create_order,
    create_published_requirement, attest, open_cycle, certify_shop,
    schedule_and_run_audit, order_in_qc, create_insurer_relation, sm,
    auditor_as,
    TEST_USERS,
    WINDOW2_START, WINDOW2_END,
)

ADMIN = TEST_USERS["admin_headers"]
AUD1 = TEST_USERS["auditor_headers"]
AUD2 = TEST_USERS["auditor2_headers"]
DEALER = TEST_USERS["dealer_headers"]


def test_repair_order_qc_rework_cycle_bounded(api):
    """PRD §3.5: "Failing QC moves QC → REWORK and increments rework_count —
    but only while rework_count is below the maximum of 3 loops; failing
    beyond that is rejected with ERR_MAX_REWORK (HTTP 422). A reworked order
    returns REWORK → QC by submitting to QC again."

    Design: Difficulty/non_linear_state_machine/repair_order_qc_rework_cycle_bounded
    """
    shop, _cycle = create_certified_shop(
        legal_name="Cycle Body", state_code="WA", zip_code="98101",
        latitude=47.61, longitude=-122.33)
    tech = create_technician(shop["id"], full_name="Lee Qa")
    order = order_in_qc(shop["id"], tech["id"], vin="1HGCV1F34LA000004",
                        estimate_total_cents=50000)
    oid = order["id"]
    for _ in range(3):
        r = validate_success(api.fail_qc(oid, sm(shop["id"])))
        assert r["status"] == "REWORK"
        r = validate_success(api.submit_qc(oid, sm(shop["id"])))
        assert r["status"] == "QC"
    fourth = api.fail_qc(oid, sm(shop["id"]))
    validate_error(fourth, ApiErrorId.ERR_MAX_REWORK)
    final = validate_success(api.get_repair_order(oid, sm(shop["id"])))
    assert final["status"] == "QC"
    assert final["rework_count"] == 3


def test_repair_order_rework_count_increments_per_loop(api):
    """PRD §3.5: "Failing QC moves QC → REWORK and increments rework_count".

    Design: Difficulty/non_linear_state_machine/repair_order_qc_rework_cycle_bounded
    """
    shop, _cycle = create_certified_shop(
        AUD2, legal_name="Cycle Body 2", state_code="WA", zip_code="98102",
        latitude=47.61, longitude=-122.33)
    tech = create_technician(shop["id"], full_name="Count Loops")
    order = order_in_qc(shop["id"], tech["id"], vin="1HGCV1F34LA000044",
                        estimate_total_cents=50000)
    oid = order["id"]
    for expected in (1, 2):
        r = validate_success(api.fail_qc(oid, sm(shop["id"])))
        assert r["rework_count"] == expected
        validate_success(api.submit_qc(oid, sm(shop["id"])))


def _setup_verification_loop(api):
    """Shop + TOOLING attestation, audit in FINDINGS_ISSUED with one MAJOR
    corrective action OPEN. Returns (shop, audit, att, cycle)."""
    shop = create_shop(legal_name="Loop Collision", state_code="NV", zip_code="89101",
                       latitude=36.17, longitude=-115.14)
    req = create_published_requirement(
        requirement_code="TL-LOOP-01", category="TOOLING",
        description="Rivet gun calibration cert", severity_if_failed="MAJOR",
        effective_from="2026-09-01T00:00:00Z")
    att = attest(shop["id"], req["id"])
    cycle = open_cycle(shop["id"])
    audit = schedule_and_run_audit(cycle["id"], AUD1)
    get_success_data(api.issue_findings(
        audit["id"],
        {"findings": [{"attestation_id": att["id"], "severity": "MAJOR"}]},
        AUD1))
    return shop, audit, att, cycle


def test_audit_verification_rejection_loop_increments_round(api):
    """PRD §3.3: "A verdict of REJECTED moves the action SUBMITTED → REJECTED,
    spawns a brand-new corrective action in OPEN status with a freshly
    calculated due_at (the revision loop), bumps the audit's round_number by
    one, and returns the audit VERIFICATION → FINDINGS_ISSUED." and "when that
    verification completes the last non-verified action of the audit, the
    audit moves VERIFICATION → PASSED". PRD §3.3: "A verdict of VERIFIED moves
    the action SUBMITTED → VERIFIED, returns the referenced attestation from
    UNDER_CORRECTION to ACTIVE as a compensation".

    Design: Difficulty/non_linear_state_machine/audit_verification_rejection_loop_increments_round
    """
    shop, audit, att, _cycle = _setup_verification_loop(api)
    cas = get_success_data(api.list_audit_corrective_actions(audit["id"], AUD1))
    ca1 = cas[0]
    get_success_data(api.submit_corrective_action(
        ca1["id"], {"evidence_uri": "s3://ev/attempt1.pdf"}, sm(shop["id"])))
    # Advance the clock so the replacement action's freshly calculated due_at
    # is measurably later than the rejected action's (both are due_at =
    # issuance-time logical clock + 30 days for MAJOR per §3.3).
    get_success_data(api.set_clock("2026-09-03T00:00:00Z", ADMIN))
    get_success_data(api.verify_corrective_action(ca1["id"], {"verdict": "REJECTED"}, AUD2))

    audit_mid = validate_success(api.get_audit(audit["id"], AUD1))
    assert audit_mid["status"] == "FINDINGS_ISSUED"
    assert audit_mid["round_number"] == 2

    cas2 = get_success_data(api.list_audit_corrective_actions(audit["id"], AUD1))
    fresh = [c for c in cas2 if c["id"] != ca1["id"]]
    assert len(fresh) == 1
    assert fresh[0]["status"] == "OPEN"
    assert fresh[0]["due_at"] != ca1["due_at"]

    ca2 = fresh[0]
    get_success_data(api.submit_corrective_action(
        ca2["id"], {"evidence_uri": "s3://ev/attempt2.pdf"}, sm(shop["id"])))
    get_success_data(api.verify_corrective_action(ca2["id"], {"verdict": "VERIFIED"}, AUD2))

    audit_final = validate_success(api.get_audit(audit["id"], AUD1))
    assert audit_final["status"] == "PASSED"
    att_now = validate_success(api.get_attestation(att["id"], ADMIN))
    assert att_now["status"] == "ACTIVE"


def test_audit_rejection_spawns_open_action_with_new_due(api):
    """PRD §3.3: "The audit's round_number is 1 at creation and increments on
    every such rejection round." and "spawns a brand-new corrective action in
    OPEN status with a freshly calculated due_at (the revision loop)".

    Design: Difficulty/non_linear_state_machine/audit_verification_rejection_loop_increments_round
    """
    shop, audit, _att, _cycle = _setup_verification_loop(api)
    cas = get_success_data(api.list_audit_corrective_actions(audit["id"], AUD1))
    assert len(cas) == 1
    ca1 = cas[0]
    get_success_data(api.submit_corrective_action(
        ca1["id"], {"evidence_uri": "s3://ev/a1.pdf"}, sm(shop["id"])))
    get_success_data(api.verify_corrective_action(ca1["id"], {"verdict": "REJECTED"}, AUD2))
    old = validate_success(api.get_corrective_action(ca1["id"], AUD1))
    assert old["status"] == "REJECTED"
    cas2 = get_success_data(api.list_audit_corrective_actions(audit["id"], AUD1))
    assert len(cas2) == 2
    audit_now = validate_success(api.get_audit(audit["id"], AUD1))
    assert audit_now["round_number"] == 2


def test_shop_suspension_cascades_to_relations_referrals_counters(api):
    """PRD §3.1: "The suspension cascade flips locator_hidden to true, sets
    steering_enabled false on every insurer relation of the shop, and
    force-transitions every ROUTED referral pointing at the shop to DECLINED,
    decrementing pending_referral_count for each." and "a clock sweep that
    finds any CRITICAL corrective action of the shop's audits past its due_at
    still OPEN, drives CERTIFIED → SUSPENDED."

    Design: Difficulty/transitive_cascade/shop_suspension_cascades_to_relations_referrals_counters
    """
    shop = create_shop(legal_name="Cascade Auto Body", state_code="AZ", zip_code="85001",
                       latitude=33.45, longitude=-112.07)
    rel = create_insurer_relation(shop["id"], insurer_code="INS-ACME", discount_pct_bps=500)
    certify_shop(shop["id"], scheduled_start="2026-09-01T01:00:00Z",
                 scheduled_end="2026-09-01T09:00:00Z", begin_at="2026-09-01T02:00:00Z")

    req = create_published_requirement(
        requirement_code="ST-CASC-01", category="STRUCTURAL",
        description="Frame bench cert", severity_if_failed="CRITICAL",
        effective_from="2026-09-01T02:00:00Z")
    att = attest(shop["id"], req["id"])
    cycle2 = open_cycle(shop["id"], WINDOW2_START, WINDOW2_END)
    audit2 = schedule_and_run_audit(
        cycle2["id"], AUD1,
        scheduled_start="2026-09-05T09:00:00Z",
        scheduled_end="2026-09-05T17:00:00Z",
        begin_at="2026-09-05T10:00:00Z")
    get_success_data(api.issue_findings(
        audit2["id"],
        {"findings": [{"attestation_id": att["id"], "severity": "CRITICAL"}]},
        AUD1))
    # The CRITICAL action is due 10 days after issuance (2026-09-15T10:00Z).
    # Route the referral only once the logical clock is close enough to the
    # suspension sweep that the 72-hour referral TTL cannot expire it first.
    get_success_data(api.set_clock("2026-09-14T00:00:00Z", ADMIN))
    ref = validate_success(api.create_referral(
        {"consumer_zip": "85001", "source_type": "DEALER", "source_reference": "DLR-7",
         "vin": "1HGCV1F34LA000005"}, DEALER), 201)
    assert ref["status"] == "ROUTED"
    assert ref["routed_shop_id"] == shop["id"]
    get_success_data(api.set_clock("2026-09-16T00:00:00Z", ADMIN))

    shop_now = validate_success(api.get_shop(shop["id"], ADMIN))
    assert shop_now["certification_status"] == "SUSPENDED"
    assert shop_now["locator_hidden"] is True
    assert shop_now["pending_referral_count"] == 0
    rel_now = validate_success(api.get_insurer_relation(rel["id"], ADMIN))
    assert rel_now["steering_enabled"] is False
    ref_now = validate_success(api.get_referral(ref["id"], ADMIN))
    assert ref_now["status"] == "DECLINED"


def test_suspension_cascade_disables_steering_only(api):
    """PRD §3.1: "The suspension cascade flips locator_hidden to true, sets
    steering_enabled false on every insurer relation of the shop, and
    force-transitions every ROUTED referral pointing at the shop to DECLINED,
    decrementing pending_referral_count for each."

    Design: Difficulty/transitive_cascade/shop_suspension_cascades_to_relations_referrals_counters
    """
    shop = create_shop(legal_name="Cascade Auto Body 2", state_code="AZ", zip_code="85002",
                       latitude=33.45, longitude=-112.07)
    rel = create_insurer_relation(shop["id"], insurer_code="INS-C2", discount_pct_bps=400)
    certify_shop(shop["id"], scheduled_start="2026-09-01T01:00:00Z",
                 scheduled_end="2026-09-01T09:00:00Z", begin_at="2026-09-01T02:00:00Z")
    rel_mid = validate_success(api.get_insurer_relation(rel["id"], ADMIN))
    assert rel_mid["steering_enabled"] is True

    req = create_published_requirement(
        requirement_code="ST-CASC-02", category="STRUCTURAL",
        severity_if_failed="CRITICAL", effective_from="2026-09-01T02:00:00Z")
    att = attest(shop["id"], req["id"])
    cycle2 = open_cycle(shop["id"], WINDOW2_START, WINDOW2_END)
    audit2 = schedule_and_run_audit(
        cycle2["id"], AUD1,
        scheduled_start="2026-09-05T09:00:00Z",
        scheduled_end="2026-09-05T17:00:00Z",
        begin_at="2026-09-05T10:00:00Z")
    get_success_data(api.issue_findings(
        audit2["id"],
        {"findings": [{"attestation_id": att["id"], "severity": "CRITICAL"}]},
        AUD1))
    get_success_data(api.set_clock("2026-09-16T00:00:00Z", ADMIN))
    rel_now = validate_success(api.get_insurer_relation(rel["id"], ADMIN))
    assert rel_now["steering_enabled"] is False
    assert validate_success(api.get_shop(shop["id"], ADMIN))["certification_status"] == "SUSPENDED"


def test_requirement_revision_cascades_to_attestation_and_score(api):
    """PRD §3.2: "Publishing a new revision of a PUBLISHED requirement creates
    an entirely new Requirement row with the same requirement_code,
    requirement_version incremented by one, and supersedes_requirement_id
    pointing at the row being replaced; the old row moves to SUPERSEDED. ...
    The revision has teeth: every ShopAttestation pinned to the superseded row
    flips from ACTIVE to LAPSED with lapse_reason REQUIREMENT_REVISED, each
    affected shop's live_compliance_score is recomputed". PRD §3.2: "The
    live_compliance_score itself is a weighted average over the four
    categories, with weights 30 for EQUIPMENT, 30 for STRUCTURAL, 15 for
    TOOLING, and 25 for TRAINING."

    Design: Difficulty/transitive_cascade/requirement_revision_cascades_to_attestation_and_score
    """
    shop = create_shop(legal_name="Revision Collision", state_code="CO", zip_code="80201",
                       latitude=39.74, longitude=-104.99)
    req = create_published_requirement(
        requirement_code="EQ-REV-01", category="EQUIPMENT",
        description="Spot welder", severity_if_failed="MAJOR",
        effective_from="2026-09-01T00:00:00Z")
    # A second, currently-effective EQUIPMENT row (also attested) keeps the
    # category denominator at 2 after the revision, so the lapsed attestation
    # drives the score to 30*(1/2) + 30 + 15 + 25 = 85 per §3.2.
    req2 = create_published_requirement(
        requirement_code="EQ-REV-02", category="EQUIPMENT",
        description="Dent puller", severity_if_failed="MINOR",
        effective_from="2026-09-01T00:00:00Z")
    att = attest(shop["id"], req["id"])
    attest(shop["id"], req2["id"])
    before = validate_success(api.get_shop(shop["id"], ADMIN))
    assert before["live_compliance_score"] == pytest.approx(100.0, abs=1e-9)

    rev = validate_success(api.publish_revision(
        req["id"],
        {"description": "Spot welder v2", "severity_if_failed": "MAJOR",
         "effective_from": "2026-09-01T00:00:00Z"},
        ADMIN), 201)
    old = validate_success(api.get_requirement(req["id"], ADMIN))
    assert old["status"] == "SUPERSEDED"
    assert rev["supersedes_requirement_id"] == req["id"]
    assert rev["requirement_version"] == 2
    att_now = validate_success(api.get_attestation(att["id"], ADMIN))
    assert att_now["status"] == "LAPSED"
    assert att_now["lapse_reason"] == "REQUIREMENT_REVISED"
    shop_now = validate_success(api.get_shop(shop["id"], ADMIN))
    assert shop_now["live_compliance_score"] == pytest.approx(85.0, abs=1e-9)


def test_requirement_retire_lapses_pinned_attestations(api):
    """PRD §3.2: "retiring a published row likewise lapses its pinned
    attestations with lapse_reason REQUIREMENT_RETIRED."

    Design: Difficulty/transitive_cascade/requirement_revision_cascades_to_attestation_and_score
    """
    shop = create_shop(legal_name="Retire Collision", state_code="CO", zip_code="80202",
                       latitude=39.74, longitude=-104.99)
    req = create_published_requirement(
        requirement_code="EQ-RET-01", category="EQUIPMENT",
        severity_if_failed="MINOR", effective_from="2026-09-01T00:00:00Z")
    att = attest(shop["id"], req["id"])
    validate_success(api.retire_requirement(req["id"], ADMIN))
    att_now = validate_success(api.get_attestation(att["id"], ADMIN))
    assert att_now["status"] == "LAPSED"
    assert att_now["lapse_reason"] == "REQUIREMENT_RETIRED"
    shop_now = validate_success(api.get_shop(shop["id"], ADMIN))
    # With the only EQUIPMENT row retired, the category has zero published
    # effective rows and scores the vacuous 100.0 per §3.2.
    assert shop_now["live_compliance_score"] == pytest.approx(100.0, abs=1e-9)
