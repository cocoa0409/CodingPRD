"""Cross-entity approval gates, temporal resource occupancy and conserved
quantities (penalty ledger money, audit-finding units).

Every test builds its own world from an empty database.
"""
import pytest

from test_helpers import *  # noqa: F401,F403


# --- module-private setup helpers ----------------------------------------

# Three findings whose derived severity is CRITICAL: two by code, and one MAJOR
# code carrying 5,000 affected units, which escalates exactly one level.
_CRITICAL_TRIO = [
    {"finding_code": "FIBER_CONTENT_MISSTATED", "units_affected": 100},
    {"finding_code": "ORIGIN_MISSTATED", "units_affected": 100},
    {"finding_code": "CARE_UNSUBSTANTIATED", "units_affected": 5000},
]

_BENCH_LAB_CODE = "LAB-ATL-1"
_FIBER_METHOD = "AATCC_20A"


def _pending_label_with_restriction_and_reverification():
    """A permanent label parked in PENDING_APPROVAL whose style and brand then
    move underneath it: a sibling audit carries three CRITICAL findings and a
    re-verification fiber-content bench reservation is left without results.

    Returns (bundle, label, audit, findings, reverification_test).
    """
    bundle, label = setup_pending_permanent_label()
    style_id = bundle["style"]["id"]
    _, _, audit, findings = setup_audit_with_findings(
        bundle["brand"]["id"], style_id, finding_specs=_CRITICAL_TRIO)
    reverification = reserve_fiber_test(
        style_id,
        specimen_received_at="2026-08-10T09:00:00Z",
        results_due_at="2026-08-12T09:00:00Z")
    return bundle, label, audit, findings, reverification


def _finding_with_corrective_label_awaiting_publication():
    """A style whose permanent label is APPROVED but not yet PUBLISHED, plus one
    OPEN audit finding of that style. Returns (bundle, label, audit, finding)."""
    bundle, label = setup_approved_permanent_label()
    _, _, audit, findings = setup_audit_with_findings(
        bundle["brand"]["id"], bundle["style"]["id"],
        finding_specs=[{"finding_code": "CARE_UNSUBSTANTIATED",
                        "units_affected": 100}])
    return bundle, label, audit, findings[0]


def _approved_labels_of_one_style(count):
    """`count` APPROVED permanent labels of one style, all printed for the same
    single market and differing only in placement. Returns (bundle, labels)."""
    placements = ["NECK_CENTER_INSIDE", "SIDE_SEAM_INSIDE", "WAISTBAND_INSIDE"]
    bundle = setup_label_ready_style()
    labels = []
    for placement in placements[:count]:
        draft = draft_permanent_label(bundle, placement_code=placement)
        submit_label(draft["id"])
        labels.append(approve_label(draft["id"]))
    return bundle, labels


def _bench_styles(count):
    """`count` distinct styles under one brand, each with a non-empty fiber
    declaration, so each can hold its own BENCH_RESERVED fiber-content run."""
    register_market("US")
    brand = register_brand()
    return brand, [create_style(brand["id"]) for _ in range(count)]


def _reserve_bench(api, style_id, received, due, **overrides):
    """Raw reservation on the shared (LAB-ATL-1, AATCC_20A) bench pair."""
    payload = fiber_test_payload(
        style_id, lab_code=_BENCH_LAB_CODE, method=_FIBER_METHOD,
        specimen_received_at=received, results_due_at=due, **overrides)
    return api.create_lab_test(payload, LAB)


def _lab_test_state(api, lab_test_id):
    return validate_success(api.get_lab_test(lab_test_id, ADMIN), 200)["state"]


def _brand_with_published_label_and_entries(entry_count=2):
    """A brand whose ledger starts empty, a PUBLISHED permanent label to correct
    against, and `entry_count` identical filed entries of 12,000 units at
    48,000.00 USD through the US port (marking_duty_rate 0.100)."""
    bundle, label = setup_published_permanent_label()
    entries = [
        file_shipment(bundle["brand"]["id"], bundle["style"]["id"],
                      quantity_units=12000, declared_value_usd=48000.00,
                      entry_market_code="US")
        for _ in range(entry_count)
    ]
    return bundle, label, entries


class TestApprovalReadsForeignEntityState:
    """The label row never changes; the answer changes because the approval gate
    reads the style's laboratory dimension and the brand's posture."""

    def test_open_reverification_bench_blocks_approval_with_the_fiber_gate(self, api):
        """PRD 3.4: "A fiber-content reservation also drives the style's substantiation dimension: from `FIBER_DECLARED` it advances to `FIBER_TEST_PENDING`, and from `FIBER_SUBSTANTIATED` it *also* advances to `FIBER_TEST_PENDING`, which is the re-verification of an already substantiated style."
        PRD 3.6: "The style's `substantiation_state` must be `FIBER_SUBSTANTIATED`, or the approval is rejected with `ERR_FIBER_NOT_SUBSTANTIATED`."

        Design: Difficulty/cross_entity_state_dependency/approval_is_gated_by_lab_test_style_and_brand_states_it_does_not_own
        """
        bundle, label, audit, findings, reverification = (
            _pending_label_with_restriction_and_reverification())

        assert reverification["state"] == "BENCH_RESERVED", (
            "the re-verification run must sit in BENCH_RESERVED, got "
            f"{reverification['state']}")
        style = read_style(bundle["style"]["id"])
        assert style["substantiation_state"] == "FIBER_TEST_PENDING", (
            "re-verifying an already substantiated style must return the fiber "
            f"dimension to FIBER_TEST_PENDING, got {style['substantiation_state']}")

        resp = api.approve_label_spec(label["id"], APPROVER)
        validate_error(resp, ApiErrorId.ERR_FIBER_NOT_SUBSTANTIATED, 422)

        row = read_label(label["id"])
        assert row["state"] == "PENDING_APPROVAL", (
            "a rejected approval must leave the artifact in PENDING_APPROVAL, got "
            f"{row['state']}")
        assert row["approved_by_user_id"] is None, (
            "a rejected approval must not stamp approved_by_user_id")

    def test_sibling_audit_posture_blocks_the_same_approval_once_fiber_passes(self, api):
        """PRD 3.1: "otherwise, if there exists at least one compliance audit of this brand of record whose state is `IN_REVIEW` and whose critical-finding count is **at least** 3 — three critical findings is enough — the posture is `RESTRICTED`; otherwise it is `OPEN`."
        PRD 3.6: "And the posture of the brand of record must be neither `SUSPENDED`, which is rejected with `ERR_BRAND_POSTURE_SUSPENDED`, nor `RESTRICTED`, which is rejected with `ERR_BRAND_POSTURE_RESTRICTED`; both sit near the very bottom of the ladder, with the suspension check evaluated before the restriction check."

        Design: Difficulty/cross_entity_state_dependency/approval_is_gated_by_lab_test_style_and_brand_states_it_does_not_own
        """
        bundle, label, audit, findings, reverification = (
            _pending_label_with_restriction_and_reverification())

        assert findings[2]["severity"] == "CRITICAL", (
            "a MAJOR finding code carrying 5,000 affected units escalates one "
            f"level to CRITICAL, got {findings[2]['severity']}")

        passed = post_results(
            reverification["id"],
            fiber_results_payload(measured_fibers=[
                {"fiber_generic_name": "COTTON", "measured_pct": 60.0},
                {"fiber_generic_name": "POLYESTER", "measured_pct": 40.0},
            ]))
        assert passed["state"] == "PASSED", (
            f"the re-verification run must pass, got {passed['state']}")
        style = read_style(bundle["style"]["id"])
        assert style["substantiation_state"] == "FIBER_SUBSTANTIATED", (
            "a fiber-content pass must return the style to FIBER_SUBSTANTIATED, "
            f"got {style['substantiation_state']}")

        brand = read_brand(bundle["brand"]["id"])
        assert brand["critical_audit_finding_count"] == 3, (
            "three CRITICAL findings inside one IN_REVIEW audit must roll up to "
            f"the brand, got {brand['critical_audit_finding_count']}")
        assert brand["posture"] == "RESTRICTED", (
            f"expected posture RESTRICTED, got {brand['posture']}")

        resp = api.approve_label_spec(label["id"], APPROVER)
        validate_error(resp, ApiErrorId.ERR_BRAND_POSTURE_RESTRICTED, 422)
        assert read_label(label["id"])["state"] == "PENDING_APPROVAL", (
            "the artifact must still be awaiting approval after the posture gate")

    def test_verifying_one_critical_finding_away_lets_the_identical_call_succeed(self, api):
        """PRD 3.9: "The third hop, caused by the second, recomputes the brand-of-record's `posture`: because no audit of that party is any longer in `IN_REVIEW` with at least 3 critical findings, a posture that was `RESTRICTED` for that reason drops back to `OPEN`."

        Design: Difficulty/cross_entity_state_dependency/approval_is_gated_by_lab_test_style_and_brand_states_it_does_not_own
        """
        bundle, label, audit, findings, reverification = (
            _pending_label_with_restriction_and_reverification())
        rating_before = read_label(label["id"])["durability_cycles_rating"]

        post_results(reverification["id"], fiber_results_payload(measured_fibers=[
            {"fiber_generic_name": "COTTON", "measured_pct": 60.0},
            {"fiber_generic_name": "POLYESTER", "measured_pct": 40.0},
        ]))
        escalated = findings[2]
        record_disposition(escalated["id"], units_destroyed=escalated["units_affected"])
        verified = verify_finding(escalated["id"])
        assert verified["state"] == "CLOSED", (
            f"a verified finding must move to CLOSED, got {verified['state']}")

        brand = read_brand(bundle["brand"]["id"])
        assert brand["critical_audit_finding_count"] == 2, (
            "closing one CRITICAL finding must drop the brand's critical count to "
            f"2, got {brand['critical_audit_finding_count']}")
        assert brand["posture"] == "OPEN", (
            f"posture must fall back to OPEN below 3 critical findings, got "
            f"{brand['posture']}")

        data = validate_success(api.approve_label_spec(label["id"], APPROVER), 200)
        assert data["state"] == "APPROVED", (
            f"the identical approval must now succeed, got {data['state']}")
        assert data["durability_cycles_rating"] == rating_before, (
            "the label row itself was never edited between the three attempts")
        assert _lab_test_state(api, bundle["fiber_test"]["id"]) == "SUPERSEDED", (
            "the older passed fiber-content row must be superseded by the newer one")
        assert _lab_test_state(api, reverification["id"]) == "PASSED", (
            "the re-verification row must stand at PASSED")


class TestDispositionCorrectiveLabelMustBePublished:
    """The disposition payload never changes; only the referenced label's state
    does, which is what proves the reference check reads that row's state."""

    def test_an_approved_but_unpublished_corrective_label_is_not_eligible(self, api):
        """PRD 2.6: "a `corrective_label_spec_id` must name a permanent label of the same style whose state is `PUBLISHED`, and on an audit-finding disposition it is required exactly when `units_relabeled` is greater than zero and must be omitted when `units_relabeled` is zero"

        Design: Difficulty/cross_entity_state_dependency/disposition_requires_its_corrective_label_to_be_published_not_merely_approved
        """
        bundle, label, audit, finding = _finding_with_corrective_label_awaiting_publication()

        assert label["state"] == "APPROVED", (
            f"the corrective label must sit in APPROVED, got {label['state']}")
        assert finding["severity"] == "MAJOR", (
            f"CARE_UNSUBSTANTIATED under 5,000 units stays MAJOR, got "
            f"{finding['severity']}")

        payload = disposition_payload(finding["units_affected"], 0, 0, label["id"])
        validate_error(api.record_finding_disposition(finding["id"], payload, SPECIALIST),
                       ApiErrorId.ERR_REFERENCE_NOT_ELIGIBLE, 422)

        row = read_finding(finding["id"])
        assert row["state"] == "OPEN", (
            f"the rejected disposition must leave the finding OPEN, got {row['state']}")
        assert row["corrective_label_spec_id"] is None, (
            "a rejected disposition must not store the corrective reference")
        assert row["units_relabeled"] == 0 and row["units_unresolved"] == row["units_affected"], (
            "a rejected disposition must leave every unit bucket untouched")
        assert_finding_unit_conservation(row)

    def test_publishing_the_same_label_makes_the_identical_disposition_succeed(self, api):
        """PRD 3.9: "plus a `corrective_label_spec_id` when — and only when — `units_relabeled` is greater than zero, naming a published permanent label of the same style as the finding."

        Design: Difficulty/cross_entity_state_dependency/disposition_requires_its_corrective_label_to_be_published_not_merely_approved
        """
        bundle, label, audit, finding = _finding_with_corrective_label_awaiting_publication()
        payload = disposition_payload(finding["units_affected"], 0, 0, label["id"])
        validate_error(api.record_finding_disposition(finding["id"], payload, SPECIALIST),
                       ApiErrorId.ERR_REFERENCE_NOT_ELIGIBLE, 422)

        published = publish_label(label["id"], "2026-09-01T00:00:00Z",
                                  "2026-10-01T00:00:00Z")
        assert published["state"] == "PUBLISHED", (
            f"the corrective label must reach PUBLISHED, got {published['state']}")

        data = validate_success(
            api.record_finding_disposition(finding["id"], payload, SPECIALIST), 200)
        assert data["state"] == "REMEDIATED", (
            f"the identical disposition must now succeed, got {data['state']}")
        assert data["corrective_label_spec_id"] == label["id"], (
            "the disposition must store the published corrective label")
        assert data["units_relabeled"] == finding["units_affected"], (
            "every affected unit was relabeled")
        assert data["units_unresolved"] == 0, (
            f"a complete disposition drives units_unresolved to 0, got "
            f"{data['units_unresolved']}")
        assert_finding_unit_conservation(data)

        rolled = read_audit(audit["id"])
        assert rolled["state"] == "IN_REVIEW" and rolled["open_finding_count"] == 1, (
            "a REMEDIATED finding is still open for closure purposes, so the audit "
            f"stays IN_REVIEW with one open finding, got {rolled['state']} / "
            f"{rolled['open_finding_count']}")

    def test_a_withdrawn_corrective_label_is_not_eligible_either(self, api):
        """PRD 2.6: "a `corrective_label_spec_id` must name a permanent label of the same style whose state is `PUBLISHED`, and on an audit-finding disposition it is required exactly when `units_relabeled` is greater than zero and must be omitted when `units_relabeled` is zero"

        Design: Difficulty/cross_entity_state_dependency/disposition_requires_its_corrective_label_to_be_published_not_merely_approved
        """
        bundle, label, audit, finding = _finding_with_corrective_label_awaiting_publication()
        publish_label(label["id"], "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z")

        withdrawn = validate_success(
            api.withdraw_label_spec(label["id"], "the print run was pulled", ADMIN), 200)
        assert withdrawn["state"] == "WITHDRAWN", (
            f"the corrective label must reach WITHDRAWN, got {withdrawn['state']}")

        payload = disposition_payload(finding["units_affected"], 0, 0, label["id"])
        validate_error(api.record_finding_disposition(finding["id"], payload, SPECIALIST),
                       ApiErrorId.ERR_REFERENCE_NOT_ELIGIBLE, 422)
        assert read_finding(finding["id"])["state"] == "OPEN", (
            "the finding must still be OPEN after the rejected disposition")


class TestPublishedWindowIsHalfOpen:
    """One style-and-market pair is a capacity-1 resource over the half-open
    window [effective_from, effective_to)."""

    def test_a_window_starting_inside_a_published_window_is_rejected(self, api):
        """PRD 3.6: "The window is exclusive of its upper bound, and exactly one published artifact may occupy a given style-and-market pair at any instant: for every market this artifact shares with another published artifact of the same style, the half-open window from `effective_from` inclusive to `effective_to` exclusive must not intersect that row's window."

        Design: Difficulty/resource_temporal_overlap/published_label_windows_are_half_open_so_touching_windows_are_allowed
        """
        bundle, labels = _approved_labels_of_one_style(2)
        first = validate_success(api.publish_label_spec(
            labels[0]["id"], "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z",
            APPROVER), 200)
        assert first["state"] == "PUBLISHED", (
            f"the first label must publish cleanly, got {first['state']}")
        assert first["effective_from"] == "2026-09-01T00:00:00Z"
        assert first["effective_to"] == "2026-10-01T00:00:00Z"

        validate_error(api.publish_label_spec(
            labels[1]["id"], "2026-09-15T00:00:00Z", "2026-11-01T00:00:00Z",
            APPROVER), ApiErrorId.ERR_LABEL_WINDOW_OVERLAP, 409)

        blocked = read_label(labels[1]["id"])
        assert blocked["state"] == "APPROVED", (
            "a rejected publication must leave the artifact in APPROVED, got "
            f"{blocked['state']}")
        assert blocked["effective_from"] is None and blocked["effective_to"] is None, (
            "a rejected publication must store neither instant")

    def test_a_window_starting_at_another_windows_exclusive_end_is_allowed(self, api):
        """PRD 3.6: "Windows that merely touch — where a new `effective_from` equals an existing `effective_to` — are allowed; a true intersection is rejected with `ERR_LABEL_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/published_label_windows_are_half_open_so_touching_windows_are_allowed
        """
        bundle, labels = _approved_labels_of_one_style(2)
        validate_success(api.publish_label_spec(
            labels[0]["id"], "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z",
            APPROVER), 200)

        touching = validate_success(api.publish_label_spec(
            labels[1]["id"], "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z",
            APPROVER), 200)
        assert touching["state"] == "PUBLISHED", (
            "a window starting exactly at the previous window's exclusive end must "
            f"be accepted, got {touching['state']}")
        assert touching["effective_from"] == "2026-10-01T00:00:00Z"

        summary = validate_success(
            api.get_compliance_summary(bundle["style"]["id"], ADMIN), 200)
        assert summary["published_permanent_label_count"] == 2, (
            "both touching artifacts stand published, so the style must report 2, "
            f"got {summary['published_permanent_label_count']}")

    def test_an_empty_window_is_rejected_before_any_occupancy_reasoning(self, api):
        """PRD 3.6: "It requires state `APPROVED`, and it takes `effective_from` and `effective_to`, with `effective_to` strictly after `effective_from` — otherwise `ERR_INVALID_EFFECTIVE_WINDOW`."

        Design: Difficulty/resource_temporal_overlap/published_label_windows_are_half_open_so_touching_windows_are_allowed
        """
        bundle, labels = _approved_labels_of_one_style(1)
        validate_error(api.publish_label_spec(
            labels[0]["id"], "2026-11-01T00:00:00Z", "2026-11-01T00:00:00Z",
            APPROVER), ApiErrorId.ERR_INVALID_EFFECTIVE_WINDOW, 422)
        assert read_label(labels[0]["id"])["state"] == "APPROVED", (
            "the artifact must remain APPROVED after an empty window is refused")


class TestLabBenchOccupancy:
    """The (lab_code, method) pair is a capacity-2 resource whose occupancy
    interval is closed at both ends."""

    def test_a_third_overlapping_reservation_exceeds_the_capacity_of_two(self, api):
        """PRD 3.4: "At most two reservations may overlap any instant on a given laboratory-and-method pair: if two other rows already in `BENCH_RESERVED` on that pair occupy an interval overlapping the requested one, the request is rejected with `ERR_LAB_BENCH_CAPACITY`."
        PRD 3.4: "The bench itself is a scarce resource, and the resource is the pair of laboratory and method rather than the laboratory alone."

        Design: Difficulty/resource_temporal_overlap/lab_bench_occupancy_is_closed_at_both_ends_with_capacity_two
        """
        brand, styles = _bench_styles(3)
        first = validate_success(_reserve_bench(
            api, styles[0]["id"], "2026-08-03T09:00:00Z", "2026-08-05T09:00:00Z"), 201)
        second = validate_success(_reserve_bench(
            api, styles[1]["id"], "2026-08-04T09:00:00Z", "2026-08-06T09:00:00Z"), 201)
        for row in (first, second):
            assert row["state"] == "BENCH_RESERVED", (
                f"one overlap is under the capacity of 2, got {row['state']}")
            assert row["attempt_no"] == 1, (
                f"a fresh reservation starts at attempt_no 1, got {row['attempt_no']}")

        validate_error(_reserve_bench(
            api, styles[2]["id"], "2026-08-05T00:00:00Z", "2026-08-07T00:00:00Z"),
            ApiErrorId.ERR_LAB_BENCH_CAPACITY, 409)

        other_pair = validate_success(api.create_lab_test(care_test_payload(
            styles[2]["id"], lab_code=_BENCH_LAB_CODE, method="AATCC_135",
            specimen_received_at="2026-08-05T00:00:00Z",
            results_due_at="2026-08-07T00:00:00Z", wash_temp_c=40), LAB), 201)
        assert other_pair["state"] == "BENCH_RESERVED", (
            "a different method is a different bench pair, so the same interval on "
            f"the same laboratory must be free, got {other_pair['state']}")

    def test_a_passing_result_releases_the_bench_for_the_identical_request(self, api):
        """PRD 3.4: "A passing run sets the row to `PASSED`, releases the bench occupancy interval, supersedes the previously `PASSED` row of the same style and test type if one existed, and stamps `valid_until`, the evidence validity horizon."

        Design: Difficulty/resource_temporal_overlap/lab_bench_occupancy_is_closed_at_both_ends_with_capacity_two
        """
        brand, styles = _bench_styles(3)
        first = validate_success(_reserve_bench(
            api, styles[0]["id"], "2026-08-03T09:00:00Z", "2026-08-05T09:00:00Z"), 201)
        validate_success(_reserve_bench(
            api, styles[1]["id"], "2026-08-04T09:00:00Z", "2026-08-06T09:00:00Z"), 201)
        validate_error(_reserve_bench(
            api, styles[2]["id"], "2026-08-05T00:00:00Z", "2026-08-07T00:00:00Z"),
            ApiErrorId.ERR_LAB_BENCH_CAPACITY, 409)

        resolved = post_results(first["id"], fiber_results_payload())
        assert resolved["state"] == "PASSED", (
            f"the first run must pass and free its slot, got {resolved['state']}")

        refit = validate_success(_reserve_bench(
            api, styles[2]["id"], "2026-08-05T00:00:00Z", "2026-08-07T00:00:00Z"), 201)
        assert refit["state"] == "BENCH_RESERVED", (
            "the identical request must fit once only one row still occupies the "
            f"bench, got {refit['state']}")

    def test_a_start_instant_equal_to_another_occupancy_end_still_collides(self, api):
        """PRD 3.4: "A reservation occupies the interval running from `specimen_received_at` through `results_due_at` plus a 24-hour conditioning buffer, and that interval is **closed at both ends**, so an interval whose start instant equals another interval's end instant does collide."

        Design: Difficulty/resource_temporal_overlap/lab_bench_occupancy_is_closed_at_both_ends_with_capacity_two
        """
        brand, styles = _bench_styles(4)
        first = validate_success(_reserve_bench(
            api, styles[0]["id"], "2026-08-03T09:00:00Z", "2026-08-05T09:00:00Z"), 201)
        second_due = "2026-08-06T09:00:00Z"
        validate_success(_reserve_bench(
            api, styles[1]["id"], "2026-08-04T09:00:00Z", second_due), 201)
        post_results(first["id"], fiber_results_payload())
        validate_success(_reserve_bench(
            api, styles[2]["id"], "2026-08-05T00:00:00Z", "2026-08-07T00:00:00Z"), 201)

        # The second row's occupancy ends 24 hours after its results_due_at.
        touching_start = shift_instant(second_due, hours=24)
        assert touching_start == "2026-08-07T09:00:00Z"
        validate_error(_reserve_bench(
            api, styles[3]["id"], touching_start, "2026-08-08T09:00:00Z"),
            ApiErrorId.ERR_LAB_BENCH_CAPACITY, 409)

        rows = validate_paginated(api.list_style_lab_tests(styles[3]["id"], ADMIN))[0]
        assert rows == [], (
            "the rejected reservation must not have created a laboratory row, got "
            f"{len(rows)}")


class TestPenaltyLedgerCompensation:
    """Money is the conserved quantity: what a marking review adds to the ledger a
    full prompt correction takes back out exactly."""

    def test_a_full_prompt_correction_restores_the_pre_review_ledger(self, api):
        """PRD 3.1: "It is the sum, over every customs entry whose importing party resolves through the brand-of-record rule to this party and whose marking state is either `REDELIVERY_ORDERED` or `MARKING_CORRECTED`, of that entry's assessed penalty minus its mitigated amount, with the total rounded half-up to 2 decimal places."
        PRD 3.8: "The mitigation rate is the full rate of 1.00 when the correction is both complete — `corrected_units` equal to `quantity_units` — and prompt; in every other case it is the partial rate of 0.50."

        Design: Difficulty/compensating_invariant/full_prompt_correction_returns_the_penalty_ledger_to_its_pre_review_value
        """
        bundle, label, entries = _brand_with_published_label_and_entries(1)
        brand_id = bundle["brand"]["id"]
        ledger_initial = read_brand(brand_id)["outstanding_penalty_usd"]
        assert ledger_initial == pytest.approx(0.00, abs=0.01), (
            f"a freshly registered party owns no shipments, got {ledger_initial}")

        reviewed = review_shipment(entries[0]["id"])
        assert reviewed["marking_state"] == "REDELIVERY_ORDERED"
        assert reviewed["posture_at_review"] == "OPEN", (
            f"the ledger excluding this entry is empty, got "
            f"{reviewed['posture_at_review']}")
        assert reviewed["assessment_basis"] == "AD_VALOREM", (
            f"a non-suspended posture selects AD_VALOREM, got "
            f"{reviewed['assessment_basis']}")
        assert reviewed["penalty_assessed_usd"] == pytest.approx(4800.00, abs=0.01), (
            "48000.00 at a marking-duty rate of 0.100 escalated by 1.00 is 4800.00, "
            f"got {reviewed['penalty_assessed_usd']}")
        assert reviewed["redelivery_deadline_at"] == "2026-08-31T00:00:00Z", (
            "the deadline is the review instant plus 30 days, got "
            f"{reviewed['redelivery_deadline_at']}")

        ledger_after_review = read_brand(brand_id)["outstanding_penalty_usd"]
        assert ledger_after_review == pytest.approx(4800.00, abs=0.01), (
            f"the assessed entry must enter the ledger, got {ledger_after_review}")

        corrected = correct_shipment(entries[0]["id"], label["id"], 12000)
        assert corrected["marking_state"] == "MARKING_CORRECTED"
        assert corrected["penalty_mitigated_usd"] == pytest.approx(4800.00, abs=0.01), (
            "a complete and prompt correction mitigates the whole assessment, got "
            f"{corrected['penalty_mitigated_usd']}")

        brand = read_brand(brand_id)
        assert brand["outstanding_penalty_usd"] == pytest.approx(0.00, abs=0.01), (
            "assessed minus mitigated is zero, so the ledger must return to its "
            f"pre-review value, got {brand['outstanding_penalty_usd']}")
        assert brand["posture"] == "OPEN", (
            f"an empty ledger keeps the posture OPEN, got {brand['posture']}")
        assert_cost_precision(brand["outstanding_penalty_usd"])

    def test_a_half_correction_leaves_exactly_the_uncompensated_remainder(self, api):
        """PRD 3.8: "Then `penalty_mitigated_usd` is the assessed penalty multiplied by that rate, multiplied by the correction ratio, with a **single** rounding half-up to 2 decimal places applied at the very end."

        Design: Difficulty/compensating_invariant/full_prompt_correction_returns_the_penalty_ledger_to_its_pre_review_value
        """
        bundle, label, entries = _brand_with_published_label_and_entries(2)
        brand_id = bundle["brand"]["id"]

        review_shipment(entries[0]["id"])
        correct_shipment(entries[0]["id"], label["id"], 12000)
        assert read_brand(brand_id)["outstanding_penalty_usd"] == pytest.approx(
            0.00, abs=0.01), "the first entry must be fully compensated"

        second = review_shipment(entries[1]["id"], outcome="DEFICIENT",
                                 deficiency_code="WRONG_ORIGIN")
        assert second["posture_at_review"] == "OPEN", (
            "the fully corrected first entry leaves nothing in the ledger, got "
            f"{second['posture_at_review']}")
        assert second["penalty_assessed_usd"] == pytest.approx(4800.00, abs=0.01)

        partial = correct_shipment(entries[1]["id"], label["id"], 6000)
        assert partial["penalty_mitigated_usd"] == pytest.approx(1200.00, abs=0.01), (
            "4800.00 at the partial rate of 0.50 times a correction ratio of one "
            f"half is 1200.00, got {partial['penalty_mitigated_usd']}")

        ledger = read_brand(brand_id)["outstanding_penalty_usd"]
        assert ledger == pytest.approx(3600.00, abs=0.01), (
            "the compensation follows the rate and ratio rather than deleting the "
            f"row from the ledger, got {ledger}")

    def test_the_correction_never_rewrites_the_frozen_assessment(self, api):
        """PRD 3.8: "**The mitigation computation** reads only this entry, and it treats `penalty_assessed_usd` as frozen by the marking review — it is never recomputed here."

        Design: Difficulty/compensating_invariant/full_prompt_correction_returns_the_penalty_ledger_to_its_pre_review_value
        """
        bundle, label, entries = _brand_with_published_label_and_entries(1)
        reviewed = review_shipment(entries[0]["id"])
        assessed_at_review = reviewed["penalty_assessed_usd"]

        correct_shipment(entries[0]["id"], label["id"], 12000)

        row = validate_success(api.get_import_shipment(entries[0]["id"], ADMIN), 200)
        assert row["penalty_assessed_usd"] == pytest.approx(assessed_at_review, abs=0.01), (
            "the assessment itself is never rewritten by the correction, got "
            f"{row['penalty_assessed_usd']} against {assessed_at_review}")
        assert row["penalty_mitigated_usd"] == pytest.approx(4800.00, abs=0.01)
        assert row["corrected_units"] == 12000, (
            f"the corrected unit count must be stored, got {row['corrected_units']}")
        assert row["corrective_label_spec_id"] == label["id"], (
            "the published corrective label must be pinned on the entry")
        assert row["marking_state"] == "MARKING_CORRECTED", (
            f"the entry must reach its terminal corrected state, got "
            f"{row['marking_state']}")


class TestFindingUnitConservation:
    """units_affected is conserved: a disposition may only split it, and a reopen
    must put every unit back into the unresolved bucket."""

    def test_a_short_split_is_refused_and_leaves_every_counter_untouched(self, api):
        """PRD 3.9: "A disposition requires that the three supplied counters sum to exactly `units_affected`, which drives `units_unresolved` to exactly 0; any other sum is rejected with `ERR_DISPOSITION_INCOMPLETE`."

        Design: Difficulty/compensating_invariant/finding_units_are_conserved_across_disposition_and_reopen
        """
        brand_id, style_id, audit, findings = setup_audit_with_findings(
            finding_specs=[{"finding_code": "PLACEMENT_NON_PERMANENT",
                            "units_affected": 100}])
        finding = findings[0]
        assert finding["units_unresolved"] == 100, (
            f"a new finding leaves every unit unresolved, got "
            f"{finding['units_unresolved']}")

        validate_error(
            api.record_finding_disposition(
                finding["id"], disposition_payload(0, 60, 30), SPECIALIST),
            ApiErrorId.ERR_DISPOSITION_INCOMPLETE, 422)

        row = read_finding(finding["id"])
        assert row["state"] == "OPEN", (
            f"a refused disposition leaves the finding OPEN, got {row['state']}")
        assert row["units_destroyed"] == 0 and row["units_released"] == 0, (
            "a refused disposition must write none of the three buckets")
        assert row["units_unresolved"] == 100, (
            f"the unresolved remainder must still be the full 100, got "
            f"{row['units_unresolved']}")
        assert_finding_unit_conservation(row)

        rolled = read_audit(audit["id"])
        assert rolled["units_in_scope"] == 100, (
            f"units_in_scope is summed with no state filter, got "
            f"{rolled['units_in_scope']}")

    def test_a_complete_split_drives_the_unresolved_remainder_to_zero(self, api):
        """PRD 3.9: "`units_unresolved` is always `units_affected` less the sum of the relabeled, destroyed and released counts, and it may never be negative; after every request that touches a finding, the four buckets must still add back up to the affected total."

        Design: Difficulty/compensating_invariant/finding_units_are_conserved_across_disposition_and_reopen
        """
        brand_id, style_id, audit, findings = setup_audit_with_findings(
            finding_specs=[{"finding_code": "PLACEMENT_NON_PERMANENT",
                            "units_affected": 100}])
        finding = findings[0]

        data = validate_success(api.record_finding_disposition(
            finding["id"], disposition_payload(0, 60, 40), SPECIALIST), 200)
        assert data["state"] == "REMEDIATED", (
            f"a complete disposition moves the finding to REMEDIATED, got "
            f"{data['state']}")
        assert data["units_destroyed"] == 60 and data["units_released"] == 40
        assert data["units_unresolved"] == 0, (
            f"a complete split drives the remainder to 0, got "
            f"{data['units_unresolved']}")
        assert data["units_affected"] == 100, (
            "units_affected is immutable after creation")
        assert_finding_unit_conservation(data)
        assert_second_precision_instant(data["disposition_recorded_at"],
                                        "disposition_recorded_at")

        rolled = read_audit(audit["id"])
        assert rolled["units_in_scope"] == 100, (
            f"units_in_scope is invariant under disposition, got "
            f"{rolled['units_in_scope']}")
        assert rolled["open_finding_count"] == 1, (
            "a REMEDIATED finding is still counted as open for closure purposes, "
            f"got {rolled['open_finding_count']}")

    def test_a_reopen_restores_the_full_unresolved_quantity(self, api):
        """PRD 3.9: "resets `units_relabeled`, `units_destroyed` and `units_released` to 0 — which restores `units_unresolved` to the full `units_affected` and leaves the audit's `units_in_scope` byte-identical to its pre-disposition value."

        Design: Difficulty/compensating_invariant/finding_units_are_conserved_across_disposition_and_reopen
        """
        brand_id, style_id, audit, findings = setup_audit_with_findings(
            finding_specs=[{"finding_code": "PLACEMENT_NON_PERMANENT",
                            "units_affected": 100}])
        finding = findings[0]
        record_disposition(finding["id"], units_destroyed=60, units_released=40)
        closed = verify_finding(finding["id"])
        assert closed["state"] == "CLOSED", (
            f"a verified finding moves to CLOSED, got {closed['state']}")

        reopened = reopen_finding(
            finding["id"], "The destroyed lot was found back in the distribution centre.")
        assert reopened["state"] == "OPEN", (
            f"a reopened finding returns to OPEN, got {reopened['state']}")
        assert reopened["units_relabeled"] == 0, "the relabeled bucket must be reset"
        assert reopened["units_destroyed"] == 0, "the destroyed bucket must be reset"
        assert reopened["units_released"] == 0, "the released bucket must be reset"
        assert reopened["units_unresolved"] == 100, (
            f"every affected unit must return to the unresolved bucket, got "
            f"{reopened['units_unresolved']}")
        assert reopened["verified_at"] is None and reopened["disposition_recorded_at"] is None, (
            "a reopen clears both stamps")
        assert reopened["corrective_label_spec_id"] is None, (
            "a reopen clears the corrective reference")
        assert_finding_unit_conservation(reopened)

        rolled = read_audit(audit["id"])
        assert rolled["units_in_scope"] == 100, (
            f"units_in_scope is invariant under reopening, got "
            f"{rolled['units_in_scope']}")
        assert rolled["state"] == "IN_REVIEW", (
            f"the audit is pulled back from PENDING_CLOSURE to IN_REVIEW, got "
            f"{rolled['state']}")
        assert rolled["open_finding_count"] == 1, (
            f"the reopened finding counts as open again, got "
            f"{rolled['open_finding_count']}")
