"""Breadth tests: endpoint behaviours — the conditional auto-record on
coverage verification, the WITHHOLD_MARKS hold/restore cascade, the recall
classification precondition, and the platform clock's fixed start."""

from test_helpers import (
    ApiErrorId,
    CLOCK_START_ISO,
    RECALL_COORDINATOR_HEADERS,
    assert_instant,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
)


def test_verify_coverage_on_processing_shift_gap_creates_no_nr(api):
    """PRD §3.2: "The final gap drives the transition: a final gap of exactly 0
    moves the window to `VERIFIED_COVERED`, and a final gap greater than 0
    moves it to `COVERAGE_GAP_FLAGGED`. When a `SLAUGHTER` window is flagged,
    the system additionally issues a noncompliance record in the same request:
    `regulation_family` `OTHER`, `description` "inspection presence gap",
    `observed_at` at the logical clock, issued by the verifying inspector, in
    `OPEN` status."

    Design: Corner/endpoints/verify_coverage_on_processing_shift_gap_creates_no_nr
    """
    base = fx.setup_granted_with_window(
        api, species_classes=["CATTLE"], name="EP1 Plant", slaughter_capable=False,
        shift_type="PROCESSING",
    )
    inspector = fx.create_inspector(api, species_qualifications=["CATTLE"])

    verified = fx.verify_coverage(api, base["window"]["id"], inspector["id"])

    # No assignments at all: the whole 480-minute window is uncovered.
    assert verified["status"] == "COVERAGE_GAP_FLAGGED"
    assert verified["final_gap_minutes"] == 480
    assert verified["provisional_gap_minutes"] == 480
    assert fx.list_nrs(api) == [], "the auto-NR consequence is SLAUGHTER-specific"


def test_withhold_marks_activation_holds_label_applications(api):
    """PRD §3.4: "Activating a `WITHHOLD_MARKS` moves every label application
    of the establishment in `SUBMITTED` or `UNDER_REVIEW` to `HELD`."
    PRD §3.4: "Lifting a `WITHHOLD_MARKS` returns every label application it
    holds in `HELD` to the status it occupied before the hold, `SUBMITTED` or
    `UNDER_REVIEW`."

    Design: Corner/endpoints/withhold_marks_activation_holds_label_applications
    """
    base = fx.create_granted_establishment(api, species_classes=["CATTLE"], name="EP2 Plant")
    est_id = base["establishment"]["id"]
    inspector = fx.create_inspector(api, species_qualifications=["CATTLE"])
    fx.issue_nr(api, est_id, inspector["id"], regulation_family="SANITATION",
                description="qualifying nr")
    label_x = fx.submit_label_application(api, est_id, product_name="Label X",
                                          documentation_refs=["doc-x1"])
    label_y = fx.create_label_in_review(api, est_id, product_name="Label Y",
                                        documentation_refs=["doc-y1"])
    label_z = fx.create_approved_label(api, est_id, product_name="Label Z",
                                       documentation_refs=["doc-z1"])
    action = fx.create_enforcement_action(
        api, est_id, action_type="WITHHOLD_MARKS", basis="NR_LINKAGE", regulation_family="SANITATION"
    )

    fx.activate_enforcement(api, action["id"])

    held = {row["id"]: row["status"] for row in fx.list_label_applications(api, est_id)}
    assert held[label_x["id"]] == "HELD", "SUBMITTED -> HELD"
    assert held[label_y["id"]] == "HELD", "UNDER_REVIEW -> HELD"
    assert held[label_z["id"]] == "APPROVED", "APPROVED applications are left alone"

    lifted = fx.lift_enforcement(api, action["id"], "marks released after corrective plan")
    assert lifted["status"] == "LIFTED"
    assert lifted["abatement_evidence"] == "marks released after corrective plan"

    restored = {row["id"]: row["status"] for row in fx.list_label_applications(api, est_id)}
    assert restored[label_x["id"]] == "SUBMITTED", "restored to its pre-hold status"
    assert restored[label_y["id"]] == "UNDER_REVIEW", "restored to its pre-hold status"
    assert restored[label_z["id"]] == "APPROVED"


def test_effectiveness_check_before_class_determined_rejected(api):
    """PRD §3.8: "Recording a check before classification — or after the recall
    has left `CLASS_DETERMINED` — is rejected with `ERR_RECALL_CLASS_REQUIRED`
    (HTTP 409)."

    Design: Corner/endpoints/effectiveness_check_before_class_determined_rejected
    """
    est = fx.create_establishment(api, name="EP3 Plant", species_classes=["CATTLE"])
    recall = fx.create_recall(api, est["id"], product_description="ham lot 2",
                              quantity_lbs=400, reason_code="FOREIGN_MATTER")
    assert recall["status"] == "INITIATED"

    resp = api.record_effectiveness_check(
        recall["id"],
        f.effectiveness_check_payload(consignee_name="Depot A", outcome="EFFECTIVE"),
        RECALL_COORDINATOR_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_RECALL_CLASS_REQUIRED)

    rows, meta = validate_paginated(
        api.list_effectiveness_checks(recall["id"], RECALL_COORDINATOR_HEADERS)
    )
    assert rows == [] and meta["total_count"] == 0, "no check may be recorded"


def test_platform_clock_default_is_fixed_start(api):
    """PRD §2.4: "All temporal rules in this system — trailing windows,
    observation-time ceilings, abatement periods — evaluate against a single
    logical clock maintained by the platform, never against wall-clock time.
    Before any call to the clock endpoint, the logical clock reads exactly
    `2026-09-01T00:00:00Z`; there is no wall-clock fallback at startup or at
    any later point."
    PRD §3.3: "The record is born `OPEN`, with `issued_at` stamped from the
    logical clock."

    Design: Corner/endpoints/platform_clock_default_is_fixed_start
    """
    # The clock is NEVER set in this test.
    est = fx.create_establishment(api, name="EP5 Plant", species_classes=["CATTLE"])
    inspector = fx.create_inspector(api, species_qualifications=["CATTLE"])

    record = fx.issue_nr(api, est["id"], inspector["id"], regulation_family="OTHER",
                         description="default clock probe")

    assert_instant(
        record["issued_at"], CLOCK_START_ISO,
        "issued_at reflects the fixed default clock, never wall-clock time",
    )
    assert record["status"] == "OPEN"
