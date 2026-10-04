"""Difficulty queue — exact-boundary checks and buffered/half-open interval
overlap semantics."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_consented_participants,
    add_participant,
    approve_irb_protocol,
    consent_payload,
    create_irb_protocol_payload,
    create_wave_payload,
    get_study,
    irb_decision_payload,
    make_participant_headers,
    ruf_review_decision_payload,
    setup_contract_with_study,
    setup_ruf_in_review,
    setup_study_with_locked_plan,
    setup_active_site_study,
    validate_error,
    validate_paginated,
    validate_success,
)

AO = TEST_USERS["agency_officer_headers"]
PI = TEST_USERS["principal_investigator_headers"]
SD = TEST_USERS["study_director_headers"]
DM = TEST_USERS["data_manager_headers"]
IRB = TEST_USERS["irb_reviewer_headers"]


def test_site_capacity_exact_boundary(api):
    """PRD §3.5: "the site's `enrolled_count` must be below its
    `max_participants`, with a consent arriving when the site is exactly at
    capacity rejected with `ERR_SITE_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/site_capacity_exact_boundary
    """
    ctx = setup_active_site_study(
        site_specs=((2, "RECRUITED"), (300, "CONTACTED"), (300, "CONTACTED"),
                    (300, "CONTACTED"))
    )
    study_id = ctx["study"]["id"]
    site_a = ctx["site"]
    p1, p2 = add_consented_participants(site_a["id"], 2)
    p3 = add_participant(site_a["id"], external_ref="P003")

    sites, _ = validate_paginated(api.list_sites(study_id, SD))
    site_now = next(s for s in sites if s["id"] == site_a["id"])
    assert site_now["enrolled_count"] == 2 == site_now["max_participants"]

    resp = api.consent_participant(
        p3["id"], consent_payload(1), make_participant_headers(p3["id"])
    )
    validate_error(resp, ApiErrorId.ERR_SITE_CAPACITY_EXCEEDED)

    p3 = api.get_participant(p3["id"], PI).json()["data"]
    assert p3["status"] == "IDENTIFIED"
    assert get_study(study_id)["enrolled_total"] == 2


def test_k_anonymity_exact_boundary_release(api):
    """PRD §3.9: "For illustration, with `cell_counts` of 5, 4, 12, and 30
    against weights of 1.0, 1.0, 0.5, and 0.5, the cell of count 4 is
    suppressed; the survivors' worst cell yields a `max_risk` of 0.20 —
    exactly at the release gate, so it passes — while `mean_risk` computes to
    0.0426."
    PRD §3.9: "`max_risk` must be at most `MAX_DISCLOSURE_RISK` of 0.20, with a
    value of exactly 0.20 passing and anything above rejected with
    `ERR_DISCLOSURE_RISK_TOO_HIGH` (HTTP 422); a passing approval moves the
    file to the terminal `RELEASED` state."

    Design: Difficulty/boundary_precision_check/k_anonymity_exact_boundary_release
    """
    ctx = setup_ruf_in_review()  # cell_counts [5, 4, 12, 30], weights [1.0, 1.0, 0.5, 0.5]
    ruf = ctx["ruf"]
    assert ruf["status"] == "DISCLOSURE_REVIEW"
    assert ruf["suppressed_cell_count"] == 1, "only the 4-cell falls below K_ANONYMITY_MIN 5"
    assert ruf["max_risk"] == pytest.approx(0.20, abs=1e-9)   # 1.0 / 5
    assert ruf["mean_risk"] == pytest.approx(0.0426, abs=1e-9)  # 2.0 / 47

    ruf = validate_success(
        api.ruf_review_decision(ruf["id"], ruf_review_decision_payload("APPROVE"), AO), 200
    )
    assert ruf["status"] == "RELEASED", "exactly 0.20 passes the release gate"


def test_site_visit_gap_buffer_semantics(api):
    """PRD §3.6: "Site visits additionally observe a spacing rule: at the same
    site, a new `SITE_VISIT` window must neither overlap nor sit closer than
    `SITE_VISIT_MIN_GAP_DAYS` of 7 days to the window of any other
    non-`CANCELLED` `SITE_VISIT` wave of that site — a gap of exactly 7 days
    passes, anything tighter or overlapping is rejected with
    `ERR_VISIT_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/site_visit_gap_buffer_semantics
    """
    ctx = setup_study_with_locked_plan()  # RECRUITMENT, site A RECRUITED
    study_id = ctx["study"]["id"]
    site_a = ctx["site"]

    visit1 = validate_success(
        api.create_wave(
            study_id,
            create_wave_payload(
                wave_type="SITE_VISIT", site_id=site_a["id"],
                open_at="2026-10-01T00:00:00Z", close_at="2026-10-03T00:00:00Z",
            ),
            DM,
        ),
        201,
    )
    assert visit1["status"] == "PLANNED"

    # Gap of 5 days (close 2026-10-03 -> open 2026-10-08): rejected.
    resp = api.create_wave(
        study_id,
        create_wave_payload(
            wave_type="SITE_VISIT", site_id=site_a["id"],
            open_at="2026-10-08T00:00:00Z", close_at="2026-10-09T00:00:00Z",
        ),
        DM,
    )
    validate_error(resp, ApiErrorId.ERR_VISIT_WINDOW_CONFLICT)

    # Gap of exactly 7 days (close 2026-10-03 -> open 2026-10-10): passes.
    visit3 = validate_success(
        api.create_wave(
            study_id,
            create_wave_payload(
                wave_type="SITE_VISIT", site_id=site_a["id"],
                open_at="2026-10-10T00:00:00Z", close_at="2026-10-11T00:00:00Z",
            ),
            DM,
        ),
        201,
    )
    assert visit3["status"] == "PLANNED"

    # Overlapping the first visit's window [2026-10-01, 2026-10-03): rejected.
    resp = api.create_wave(
        study_id,
        create_wave_payload(
            wave_type="SITE_VISIT", site_id=site_a["id"],
            open_at="2026-10-02T00:00:00Z", close_at="2026-10-04T00:00:00Z",
        ),
        DM,
    )
    validate_error(resp, ApiErrorId.ERR_VISIT_WINDOW_CONFLICT)


def test_irb_window_overlap_half_open_adjacency(api):
    """PRD §3.3: "The half-open window from `approval_start` (inclusive) to
    `approval_end` (exclusive) must also not overlap the approval window of any
    other `APPROVED` protocol of the same study; two windows that merely touch,
    one's start equalling the other's end, do not count as overlapping. An
    overlap is rejected with `ERR_IRB_WINDOW_OVERLAP`."
    PRD §3.3: "if the protocol's history within this submission cycle passed
    through `MODIFICATIONS_REQUIRED` at least once, `consent_form_version`
    increments by one" (no modifications cycle here, so it stays 1).

    Design: Difficulty/resource_temporal_overlap/irb_window_overlap_half_open_adjacency
    """
    ctx = setup_contract_with_study()
    study_id = ctx["study"]["id"]
    approve_irb_protocol(study_id)  # P1 APPROVED [2026-09-01, 2027-09-01)

    irb2 = validate_success(
        api.create_irb_protocol(
            study_id,
            create_irb_protocol_payload(title="Protocol P2", estimated_burden_minutes=320),
            PI,
        ),
        201,
    )
    validate_success(api.submit_irb_protocol(irb2["id"], PI), 200)

    # Overlapping [2027-06-01, 2028-05-31) vs P1's [2026-09-01, 2027-09-01).
    resp = api.irb_decision(
        irb2["id"],
        irb_decision_payload(
            "APPROVED",
            approval_start="2027-06-01T00:00:00Z",
            approval_end="2028-05-31T00:00:00Z",
        ),
        IRB,
    )
    validate_error(resp, ApiErrorId.ERR_IRB_WINDOW_OVERLAP)
    protocols, _ = validate_paginated(api.list_irb_protocols(study_id, PI))
    assert next(p for p in protocols if p["id"] == irb2["id"])["status"] == "SUBMITTED"

    # Adjacent: start == prior end is legal for half-open windows.
    irb2 = validate_success(
        api.irb_decision(
            irb2["id"],
            irb_decision_payload(
                "APPROVED",
                approval_start="2027-09-01T00:00:00Z",
                approval_end="2028-08-31T00:00:00Z",
            ),
            IRB,
        ),
        200,
    )
    assert irb2["status"] == "APPROVED"
    assert irb2["consent_form_version"] == 1
