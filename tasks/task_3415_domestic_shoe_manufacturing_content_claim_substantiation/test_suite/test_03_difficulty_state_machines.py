"""Depth probes: cyclic state machines (LabelClaim challenge/re-substantiation
loop; ProductionRun release and hold/resume loops)."""
import pytest

from test_helpers import (
    CLOCK_START_PREFIX, ApiErrorId, certify_pair, complete_run, get_claim,
    get_lot, get_run, lock_allocation, make_allocation, make_component,
    make_factory, make_lot, make_model, make_run, make_verified_document,
    publish, release_run, reserve_run, set_clock, start_run, standard_kit,
    substantiated_claim_95, published_claim_95, substantiate, upload_document,
    validate_error, validate_success, verify_document,
)
from test_helpers import TEST_USERS

COMPLIANCE = TEST_USERS["compliance"]


def test_published_claim_challenged_by_linked_cert_rejection(api):
    """PRD §3.8: "Also in hop two, a rejected document linked directly to a
    claim sends that claim — when `SUBSTANTIATED` or `PUBLISHED` — to
    `CHALLENGED` outright."
    PRD §3.8: "Challenging a `PUBLISHED` claim clears its `published_at` to
    null"

    Design: Difficulty/non_linear_state_machine/label_claim_challenge_resubstantiation_cycle
    """
    kit = published_claim_95()
    claim = kit["claim"]
    assert claim["status"] == "PUBLISHED" and claim["version"] == 3
    assert claim["published_at"].startswith(CLOCK_START_PREFIX)

    # Reject the claim-linked origin cert (uploaded by sm-1, rejected by co-1).
    resp = api.reject_document(kit["d_oc"]["id"],
                               {"X-User-ID": "co-1", "X-User-Role": "ComplianceOfficer"})
    validate_success(resp)

    challenged = get_claim(claim["id"])
    assert challenged["status"] == "CHALLENGED" and challenged["version"] == 4
    assert challenged["published_at"] is None
    # The claim-linked rejection does not touch the content report.
    reports = validate_success(api.list_content_reports(
        kit["run"]["id"], TEST_USERS["planner"],
        params={"variant": "CERTIFIED", "status": "ACTIVE"}))
    assert len(reports) == 1
    assert reports[0]["id"] == kit["report"]["id"]
    assert reports[0]["us_content_pct"] == pytest.approx(95.00)


def test_challenged_claim_resubstantiates_and_republishes(api):
    """PRD §3.8: "A `ComplianceOfficer` substantiates a `DRAFT` claim — or
    re-substantiates a `CHALLENGED` one, which is the loop that closes the
    `PUBLISHED` → `CHALLENGED` → `SUBSTANTIATED` cycle — by supplying a
    `report_id`."
    PRD §3.8: "On success the claim pins `report_id` to the substantiating
    report, stamps `substantiated_at` from the logical clock — and, on the
    re-substantiation path, clears `published_at` to null — increments its
    `version`, and sits in `SUBSTANTIATED`."

    Design: Difficulty/non_linear_state_machine/label_claim_challenge_resubstantiation_cycle
    """
    kit = published_claim_95()
    claim_id = kit["claim"]["id"]
    api.reject_document(kit["d_oc"]["id"],
                        {"X-User-ID": "co-1", "X-User-Role": "ComplianceOfficer"})
    assert get_claim(claim_id)["status"] == "CHALLENGED"

    # Replacement origin cert attached to the claim, verified by a peer.
    replacement = upload_document("SUPPLIER_ORIGIN_CERT", "claim_id", claim_id,
                                  uploader_id="sm-1", valid_from="2026-09-01",
                                  valid_until="2027-08-31")
    verify_document(replacement["id"], reviewer_id="co-1")

    resub = substantiate(claim_id, kit["report"]["id"])
    assert resub["status"] == "SUBSTANTIATED" and resub["version"] == 5
    assert resub["published_at"] is None
    assert resub["report_id"] == kit["report"]["id"]

    republished = publish(claim_id)
    assert republished["status"] == "PUBLISHED" and republished["version"] == 6


def _loop_run_kit():
    """MLOOP (one IMPORT_ALLOWED thread line planned 100c); lot 1000 @100;
    STOCK run of 10 in 2026-W36 (allocation total 500), locked, workforce
    certified. Run still PLANNED."""
    kit = standard_kit(alloc_total=500, run_units=10,
                       model_overrides={"style_code": "MLOOP"})
    lock_allocation(kit["allocation"]["id"])
    certify_pair(kit["factory"]["id"])
    return kit


def test_run_release_recredits_and_allows_re_reserve(api):
    """PRD §3.5: "Releasing materials is the compensating reverse, moving a run
    from `MATERIAL_RESERVED` back to `PLANNED` (any other starting state,
    `ERR_INVALID_STATE`). Every lot in the run's `consumed_lots` is re-credited
    — each lot's `quantity_remaining` grows by the units that were consumed and
    its `version` increments — and the run's `consumed_lots` is cleared, with
    the run's `version` incrementing by 1."
    PRD §3.5: "Reservation and release form a compensating pair that conserves
    each lot's `quantity_received`: what reservation draws down, release
    restores exactly."

    Design: Difficulty/non_linear_state_machine/production_run_release_and_hold_cycles
    """
    kit = _loop_run_kit()
    run_id, lot_id = kit["run"]["id"], kit["lot"]["id"]

    reserved = reserve_run(run_id)
    assert reserved["status"] == "MATERIAL_RESERVED" and reserved["version"] == 2
    assert get_lot(lot_id)["quantity_remaining"] == 990

    released = release_run(run_id)
    assert released["status"] == "PLANNED" and released["version"] == 3
    assert released["consumed_lots"] == []
    assert get_lot(lot_id)["quantity_remaining"] == 1000

    re_reserved = reserve_run(run_id)
    assert re_reserved["status"] == "MATERIAL_RESERVED" and re_reserved["version"] == 4
    assert get_lot(lot_id)["quantity_remaining"] == 990


def test_run_hold_resume_cycle_then_completion(api):
    """PRD §3.5: "A run in production can be placed on quality hold, moving
    from `IN_PRODUCTION` to `QUALITY_HOLD`, by a `ProductionPlanner` or by a
    `FactoryManager`"
    PRD §3.5: "Resuming a held run returns it from `QUALITY_HOLD` to
    `IN_PRODUCTION` under the same actor rules and ownership check, and resume
    is a full re-qualification"
    PRD §3.5: "a `CUSTOM_BATCH` run pays an additional 5 percent on top of its
    tier. The certified unit cost is the base multiplied by one plus the
    surcharge, rounded half up to integer cents"

    Design: Difficulty/non_linear_state_machine/production_run_release_and_hold_cycles
    """
    kit = _loop_run_kit()
    run_id = kit["run"]["id"]
    reserve_run(run_id)
    started = start_run(run_id)
    assert started["status"] == "IN_PRODUCTION" and started["version"] == 3

    held = validate_success(api.hold_run(run_id, TEST_USERS["planner"]))
    assert held["status"] == "QUALITY_HOLD" and held["version"] == 4
    resumed = validate_success(api.resume_run(run_id, TEST_USERS["planner"]))
    assert resumed["status"] == "IN_PRODUCTION" and resumed["version"] == 5

    completed = complete_run(run_id, (0, 0, 0))
    assert completed["status"] == "COMPLETED" and completed["version"] == 6
    # base = 100 material + 0 labor + 600 overhead = 700; STOCK of 10 -> 15% tier.
    assert completed["certified_unit_cost_cents"] == 805
