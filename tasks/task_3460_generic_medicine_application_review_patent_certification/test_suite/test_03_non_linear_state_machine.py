"""Queue A: non_linear_state_machine — cyclic application loop, parallel axes."""
from test_helpers import (
    api_client, validate_success, TEST_USERS,
    set_clock, get_application, list_cycles, add_amendment,
    setup_tentative_p3, setup_approved, make_applicant_headers,
)

REVIEWER = TEST_USERS["regulatory_reviewer_headers"]


def test_application_tentative_approval_reopen_cycle():
    """PRD section 3.5: "Amending a `TENTATIVE_APPROVAL` application reopens
    review entirely: the application falls back to `RECEIVED`, its
    `tentative_approval_date` is cleared to null, the next cycle opens in
    `OPEN` with a fresh base snapshot, and `current_cycle_number` advances by
    one; if the reopening amendment is `MAJOR`, the new cycle begins with
    `major_amendment_extensions_count` already at one." After the blocking
    patent expires, a fresh APPROVE closes the loop at APPROVED — a genuine
    DRAFT -> RECEIVED -> TENTATIVE_APPROVAL -> RECEIVED -> APPROVED cycle.

    Design: Difficulty/non_linear_state_machine/application_tentative_approval_reopen_cycle
    """
    ctx = setup_tentative_p3(patent_expiry="2027-02-01")
    app_id, ac_id = ctx["app"]["id"], ctx["applicant"]["id"]
    assert ctx["app"]["status"] == "TENTATIVE_APPROVAL"
    assert ctx["app"]["tentative_approval_date"] == "2026-09-01", (
        "P3 deferral to 2027-02-01 blocks full approval at the default clock")

    set_clock("2026-12-01T00:00:00Z")
    add_amendment(app_id, ac_id, classification="MINOR", notes="labeling tweak after TA")
    reopened = get_application(app_id)
    assert reopened["status"] == "RECEIVED", "any amendment reopens a TA application"
    assert reopened["current_cycle_number"] == 2
    assert reopened["tentative_approval_date"] is None, "TA date cleared on reopen"
    cycle2 = [c for c in list_cycles(app_id) if c["cycle_number"] == 2][0]
    assert cycle2["status"] == "OPEN" and cycle2["base_review_months"] == 10

    set_clock("2027-02-02T00:00:00Z")
    decided = validate_success(api_client.approval_decision(
        app_id, {"decision": "APPROVE"}, REVIEWER), 200)
    assert decided["status"] == "APPROVED"
    assert decided["approval_date"] == "2027-02-02", (
        "patent expired 2027-02-01; the deferral block no longer contributes")


def test_supplement_parallel_review_and_effectivity_dimensions():
    """PRD section 3.9: "A `CBE_30` supplement takes effect on its own clock:
    when the logical clock reaches the date 30 calendar days after
    `submitted_date` — the thirtieth day itself counts — while the supplement
    still stands `SUBMITTED`, its effectivity flips to `EFFECTIVE` with
    `effective_date` set to that thirtieth day." A later REJECT revokes the
    already-effective change independently of the review axis.

    Design: Difficulty/non_linear_state_machine/supplement_parallel_review_and_effectivity_dimensions
    """
    ctx = setup_approved()
    app_id, ac_id = ctx["app"]["id"], ctx["applicant"]["id"]

    set_clock("2026-12-01T00:00:00Z")
    supp = validate_success(api_client.create_supplement(app_id, {
        "change_type": "LABELING", "pathway": "CBE_30",
        "description": "revise precautions section"},
        make_applicant_headers(ac_id)), 201)
    assert supp["review_status"] == "SUBMITTED"
    assert supp["effectivity"] == "NOT_EFFECTIVE"

    set_clock("2026-12-31T00:00:00Z")
    rows = validate_success(api_client.list_supplements(app_id, REVIEWER), 200)
    mid = rows[0]
    assert mid["review_status"] == "SUBMITTED", "review axis unmoved by the clock"
    assert mid["effectivity"] == "EFFECTIVE", "day 30 reached: effectivity flips alone"
    assert mid["effective_date"] == "2026-12-31"

    decided = validate_success(api_client.supplement_review_decision(
        supp["id"], {"decision": "REJECT"}, REVIEWER), 200)
    assert decided["review_status"] == "REJECTED"
    assert decided["effectivity"] == "REVOKED", (
        "rejection revokes a change that had already taken effect")
