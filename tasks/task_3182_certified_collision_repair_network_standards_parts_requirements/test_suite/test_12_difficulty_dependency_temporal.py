"""Difficulty tests (queue A): cross-entity state dependencies and resource
temporal overlap (audit half-open windows, cycle zero-gap adjacency)."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, get_success_data,
    ApiErrorId,
    create_shop, create_certified_shop, create_technician, create_order,
    create_published_requirement, attest, open_cycle, certify_shop,
    create_course, record_completion, record_step, create_referral,
    schedule_and_run_audit, sm,
    TEST_USERS,
    WINDOW_START, WINDOW_END, WINDOW2_START, WINDOW2_END,
)

ADMIN = TEST_USERS["admin_headers"]
AUD1 = TEST_USERS["auditor_headers"]
DEALER = TEST_USERS["dealer_headers"]


def _gated_shop_with_expiring_tech(api):
    """CERTIFIED shop; technician CURRENT via one 1-month course completed
    2026-08-15 (expires when clock passes 2026-09-15)."""
    shop, _cycle = create_certified_shop(
        legal_name="Gated Body", state_code="MI", zip_code="48201",
        latitude=42.33, longitude=-83.05)
    course = create_course(course_code="TR-NS-101", title="Non-structural basics",
                           required_for_roles=["NON_STRUCTURAL"], validity_months=1,
                           credit_hours=4)
    tech = create_technician(shop["id"], full_name="Cur Rent", tech_role="NON_STRUCTURAL")
    record_completion(tech["id"], course["id"], completed_at="2026-08-15T00:00:00Z")
    return shop, tech


def test_approve_gated_by_technician_currency(api):
    """PRD §3.4: "when a required completion flips to EXPIRED under the clock
    sweep and drops progress below 100.0, a previously CURRENT technician
    falls to LAPSED ... and any repair order in ESTIMATE that names this
    technician as lead can no longer be approved until reassigned — the lapse
    does not auto-void anything."

    Design: Difficulty/cross_entity_state_dependency/approve_gated_by_technician_currency
    """
    shop, tech = _gated_shop_with_expiring_tech(api)
    order1 = create_order(shop["id"], tech["id"], vin="1HGCV1F34LA000009",
                          estimate_total_cents=20000)
    record_step(order1["id"], "PRE_SCAN", tech["id"], "2026-09-01T03:00:00Z", "PASS", shop["id"])
    approved = validate_success(api.approve_order(order1["id"], sm(shop["id"])))
    assert approved["status"] == "APPROVED"

    order2 = create_order(shop["id"], tech["id"], vin="1HGCV1F34LA000010",
                          estimate_total_cents=20000)
    record_step(order2["id"], "PRE_SCAN", tech["id"], "2026-09-01T04:00:00Z", "PASS", shop["id"])

    get_success_data(api.set_clock("2026-09-16T00:00:01Z", ADMIN))
    tech_now = validate_success(api.get_technician(tech["id"], sm(shop["id"])))
    assert tech_now["status"] == "LAPSED"

    resp = api.approve_order(order2["id"], sm(shop["id"]))
    validate_error_is_one_of(resp, [ApiErrorId.ERR_INVALID_STATE,
                                    ApiErrorId.ERR_STRUCTURAL_CAPABILITY])
    after = validate_success(api.get_repair_order(order2["id"], sm(shop["id"])))
    assert after["status"] == "ESTIMATE"


def test_approve_unblocked_after_technician_recertified(api):
    """PRD §3.4: "Recording a new completion that restores progress to 100.0
    flips the technician back from LAPSED (or PROVISIONAL) to CURRENT and
    recomputes the shop score as a compensation."

    Design: Difficulty/cross_entity_state_dependency/approve_gated_by_technician_currency
    """
    shop, tech = _gated_shop_with_expiring_tech(api)
    get_success_data(api.set_clock("2026-09-16T00:00:01Z", ADMIN))
    tech_now = validate_success(api.get_technician(tech["id"], sm(shop["id"])))
    assert tech_now["status"] == "LAPSED"

    # New completion restores currency.
    courses = get_success_data(api.list_courses(ADMIN, params={"active": True}))
    course = [c for c in courses if c["course_code"] == "TR-NS-101"][0]
    record_completion(tech["id"], course["id"], completed_at="2026-09-16T00:00:00Z")
    tech_after = validate_success(api.get_technician(tech["id"], sm(shop["id"])))
    assert tech_after["status"] == "CURRENT"

    order = create_order(shop["id"], tech["id"], vin="1HGCV1F34LA000049",
                         estimate_total_cents=20000)
    record_step(order["id"], "PRE_SCAN", tech["id"], "2026-09-16T01:00:00Z", "PASS", shop["id"])
    approved = validate_success(api.approve_order(order["id"], sm(shop["id"])))
    assert approved["status"] == "APPROVED"


def _shop_graded_f_with_routed_referral(api):
    """Shop CERTIFIED -> routed referral -> second cycle's audit closed FAIL
    with a CRITICAL finding (grade F, 25 points) so the shop lands SUSPENDED
    and the referral is force-declined."""
    shop = create_shop(legal_name="Gated Referral Body", state_code="MN", zip_code="55401",
                       latitude=44.98, longitude=-93.27)
    req = create_published_requirement(
        requirement_code="ST-GATE-01", category="STRUCTURAL",
        description="Frame cert", severity_if_failed="CRITICAL",
        effective_from="2026-09-01T00:00:00Z")
    att = attest(shop["id"], req["id"])
    certify_shop(shop["id"])
    ref = create_referral(DEALER, consumer_zip="55401", source_type="DEALER",
                          source_reference="DLR-9", vin="1HGCV1F34LA000011")
    cycle = open_cycle(shop["id"], WINDOW2_START, WINDOW2_END)
    audit = schedule_and_run_audit(cycle["id"], AUD1,
                                   scheduled_start="2026-09-02T09:00:00Z",
                                   scheduled_end="2026-09-02T17:00:00Z",
                                   begin_at="2026-09-02T10:00:00Z")
    get_success_data(api.issue_findings(
        audit["id"],
        {"findings": [{"attestation_id": att["id"], "severity": "CRITICAL"}]},
        AUD1))
    cyc = validate_success(api.get_cycle(cycle["id"], AUD1))
    validate_success(api.close_cycle(
        cycle["id"], {"expected_cycle_version": cyc["version"], "result": "FAIL"}, AUD1))
    return shop, ref


def test_referral_accept_gated_by_shop_posture(api):
    """PRD §3.8: "Accepting requires the acting shop to be the referral's
    routed_shop_id, the logical clock to be earlier than routed_at plus 72
    hours, and the shop's posture to still be CERTIFIED or PROBATION".
    PRD §3.8: "A late or posture-ineligible acceptance is rejected with
    ERR_REFERRAL_EXPIRED (HTTP 422)." PRD §3.1: "force-transitions every
    ROUTED referral pointing at the shop to DECLINED, decrementing
    pending_referral_count for each."

    Design: Difficulty/cross_entity_state_dependency/referral_accept_gated_by_shop_posture
    """
    shop, ref = _shop_graded_f_with_routed_referral(api)
    assert ref["status"] == "ROUTED"
    ref_now = validate_success(api.get_referral(ref["id"], DEALER))
    assert ref_now["status"] == "DECLINED"
    resp = api.accept_referral(ref["id"], sm(shop["id"]))
    validate_error_is_one_of(resp, [ApiErrorId.ERR_REFERRAL_EXPIRED,
                                    ApiErrorId.ERR_INVALID_STATE])
    shop_now = validate_success(api.get_shop(shop["id"], ADMIN))
    assert shop_now["pending_referral_count"] == 0


def test_referral_accept_succeeds_within_ttl_when_certified(api):
    """PRD §3.8: "Accepting requires the acting shop to be the referral's
    routed_shop_id, the logical clock to be earlier than routed_at plus 72
    hours, and the shop's posture to still be CERTIFIED or PROBATION;
    acceptance moves the referral ROUTED → ACCEPTED and decrements the shop's
    pending_referral_count."

    Design: Difficulty/cross_entity_state_dependency/referral_accept_gated_by_shop_posture
    """
    shop, _cycle = create_certified_shop(
        AUD1, legal_name="Accept Body", state_code="MN", zip_code="55402",
        latitude=44.98, longitude=-93.27)
    ref = create_referral(DEALER, consumer_zip="55402", source_type="DEALER",
                          source_reference="DLR-10", vin="1HGCV1F34LA000050")
    assert ref["status"] == "ROUTED"
    assert ref["routed_shop_id"] == shop["id"]
    accepted = validate_success(api.accept_referral(ref["id"], sm(shop["id"])))
    assert accepted["status"] == "ACCEPTED"
    shop_now = validate_success(api.get_shop(shop["id"], ADMIN))
    assert shop_now["pending_referral_count"] == 0


def test_audit_window_half_open_adjacency(api):
    """PRD §3.3: "the new window must not intersect any other audit of the
    same shop that is in SCHEDULED or IN_PROGRESS: an intersection exists
    whenever the new start falls before the existing window's end and the
    existing window's start falls before the new end. Touching windows, where
    the new start equals an existing window's end, do not conflict, and audits
    in CANCELLED, PASSED, or FAILED never conflict. An overlap is rejected
    with ERR_AUDIT_OVERLAP (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/audit_window_half_open_adjacency
    """
    shop = create_shop(legal_name="Overlap Body", state_code="WI", zip_code="53201",
                       latitude=43.04, longitude=-87.91)
    cycle = open_cycle(shop["id"])
    a1 = get_success_data(api.schedule_audit(
        cycle["id"], {"scheduled_start": "2026-09-03T10:00:00Z",
                      "scheduled_end": "2026-09-03T14:00:00Z"}, AUD1))
    get_success_data(api.cancel_audit(a1["id"], AUD1))
    # CANCELLED audits never conflict: the exact same window succeeds.
    a2 = validate_success(api.schedule_audit(
        cycle["id"], {"scheduled_start": "2026-09-03T10:00:00Z",
                      "scheduled_end": "2026-09-03T14:00:00Z"}, AUD1), 201)
    get_success_data(api.cancel_audit(a2["id"], AUD1))
    a3 = validate_success(api.schedule_audit(
        cycle["id"], {"scheduled_start": "2026-09-03T10:00:00Z",
                      "scheduled_end": "2026-09-03T14:00:00Z"}, AUD1), 201)
    # §3.3's first refusal clause bars a second active audit on the same
    # cycle, so the half-open touching/overlap checks are exercised from the
    # shop's later cycles against a3 (still SCHEDULED).
    cycle2 = open_cycle(shop["id"], WINDOW2_START, WINDOW2_END)
    # Touching at the end is allowed.
    validate_success(api.schedule_audit(
        cycle2["id"], {"scheduled_start": "2026-09-03T14:00:00Z",
                       "scheduled_end": "2026-09-03T18:00:00Z"}, AUD1), 201)
    cycle3 = open_cycle(shop["id"], "2028-08-31T00:00:00Z",
                        "2029-08-30T23:59:59Z")
    # Overlap by one second with a3 is rejected.
    overlap = api.schedule_audit(
        cycle3["id"], {"scheduled_start": "2026-09-03T13:59:59Z",
                       "scheduled_end": "2026-09-03T15:00:00Z"}, AUD1)
    validate_error(overlap, ApiErrorId.ERR_AUDIT_OVERLAP)


def test_audit_window_overlap_same_instant_start_rejected(api):
    """PRD §3.3: "an intersection exists whenever the new start falls before
    the existing window's end and the existing window's start falls before
    the new end ... An overlap is rejected with ERR_AUDIT_OVERLAP
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/audit_window_half_open_adjacency
    """
    shop = create_shop(legal_name="Overlap Body 2", state_code="WI", zip_code="53202",
                       latitude=43.04, longitude=-87.91)
    cycle = open_cycle(shop["id"])
    validate_success(api.schedule_audit(
        cycle["id"], {"scheduled_start": "2026-09-03T10:00:00Z",
                      "scheduled_end": "2026-09-03T14:00:00Z"}, AUD1), 201)
    # A second cycle of the same shop: the first audit stays SCHEDULED, so the
    # strictly-interior window intersects an active audit of the shop.
    cycle2 = open_cycle(shop["id"], WINDOW2_START, WINDOW2_END)
    dup = api.schedule_audit(
        cycle2["id"], {"scheduled_start": "2026-09-03T11:00:00Z",
                       "scheduled_end": "2026-09-03T12:00:00Z"}, AUD1)
    # The second audit for the same shop while the first is SCHEDULED is
    # rejected; the recipe pins the overlap error.
    validate_error(dup, ApiErrorId.ERR_AUDIT_OVERLAP)


def test_cycle_window_zero_gap_closed_adjacency(api):
    """PRD §3.1: "The window is a closed interval that must span exactly one
    year: window_end must equal window_start plus 365 days minus 1 second, and
    a new cycle's window_start must equal the previous cycle's window_end plus
    1 second — zero-gap adjacency with no overlap and no gap. A window that
    violates either rule is rejected with ERR_CYCLE_WINDOW (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/cycle_window_zero_gap_closed_adjacency
    """
    shop = create_shop(legal_name="Gapless Body", state_code="UT", zip_code="84101",
                       latitude=40.76, longitude=-111.89)
    get_success_data(api.create_cycle(
        shop["id"], {"window_start": WINDOW_START, "window_end": WINDOW_END}, ADMIN))

    # Overlap by one second (start == prev.window_end) is rejected.
    overlap = api.create_cycle(
        shop["id"], {"window_start": "2027-08-31T23:59:59Z",
                     "window_end": "2028-08-30T23:59:59Z"}, ADMIN)
    validate_error(overlap, ApiErrorId.ERR_CYCLE_WINDOW)

    # Gap of one second (start == prev.window_end + 2s) is rejected.
    gap = api.create_cycle(
        shop["id"], {"window_start": "2027-09-01T00:00:01Z",
                     "window_end": "2028-08-31T00:00:00Z"}, ADMIN)
    validate_error(gap, ApiErrorId.ERR_CYCLE_WINDOW)

    # Exact adjacency succeeds.
    ok = validate_success(api.create_cycle(
        shop["id"], {"window_start": WINDOW2_START, "window_end": WINDOW2_END}, ADMIN), 201)
    assert ok["cycle_index"] == 2
    assert ok["status"] == "OPEN"


def test_cycle_window_wrong_length_rejected(api):
    """PRD §3.1: "window_end must equal window_start plus 365 days minus 1
    second ... A window that violates either rule is rejected with
    ERR_CYCLE_WINDOW (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/cycle_window_zero_gap_closed_adjacency
    """
    shop = create_shop(legal_name="Gapless Body 2", state_code="UT", zip_code="84102",
                       latitude=40.76, longitude=-111.89)
    # 364-day window: one day short.
    bad = api.create_cycle(
        shop["id"], {"window_start": WINDOW_START,
                     "window_end": "2027-08-30T23:59:59Z"}, ADMIN)
    validate_error(bad, ApiErrorId.ERR_CYCLE_WINDOW)
