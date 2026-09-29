"""Lifecycle and state-transition behaviour of the labeling compliance service.

Every test in this module drives one declared state edge - or one edge the
service must refuse - and checks both the moved row and the rows the move is
declared to carry with it.
"""
import pytest

from test_helpers import (
    ADMIN, AUDITOR, CUSTOMS, SPECIALIST, APPROVER,
    ApiErrorId, CLOCK_STARTUP, TEST_USERS,
    assert_audit_finding, assert_compliance_audit, assert_import_shipment,
    assert_label_spec, assert_origin_determination, assert_second_precision_instant,
    assert_style, assert_style_readiness_invariant,
    build_supply_graph, create_style, draft_determination, draft_permanent_label,
    file_shipment, fiber_line, issue_determination, marking_review_payload,
    make_brand_admin_headers, open_audit, raise_finding, read_audit, read_brand,
    read_finding, read_label, read_style, register_brand, register_market,
    setup_label_ready_style, style_payload,
    validate_error, validate_paginated, validate_success,
)

# A two-node graph whose two legal methods disagree: the only transformation-pool
# node sits in VN, while the yarn-forward pool falls back to the FIBER node in IN.
_DIVERGENT_GRAPH = [
    {"stage": "FIBER", "country_code": "IN", "value_added_usd": 2.00,
     "weight_grams": 500.0},
    {"stage": "CUT_AND_SEW", "country_code": "VN", "value_added_usd": 9.00,
     "weight_grams": 900.0, "_parent": 0},
]


def _drafted_determination_on_divergent_graph(api):
    """Registry + brand + style + the divergent graph + one DRAFT determination.

    Returns (brand, style, determination). Nothing else is substantiated, so the
    style's fiber dimension deliberately stays at FIBER_DECLARED.
    """
    register_market("US")
    brand = register_brand()
    style = create_style(brand["id"], target_market_codes=["US"])
    build_supply_graph(style["id"], _DIVERGENT_GRAPH)
    determination = draft_determination(style["id"])
    return brand, style, determination


def test_new_style_starts_at_both_dimension_initial_states(api):
    """PRD 3.2: "`substantiation_state` is the fiber-content dimension and starts
    at `FIBER_DECLARED`, moving among `FIBER_DECLARED`, `FIBER_TEST_PENDING`,
    `FIBER_SUBSTANTIATED` and `FIBER_MISSTATED`. `origin_state` is the
    country-of-origin dimension and starts at `ORIGIN_UNDETERMINED`, moving among
    `ORIGIN_UNDETERMINED`, `ORIGIN_DRAFTED` and `ORIGIN_ISSUED`."
    PRD 2.4: "Most resources additionally carry an `updated_at` timestamp that is
    refreshed on every mutation and an integer `version` that starts at 1 on
    creation and increments by exactly 1 on every mutation of that row — including
    mutations the row suffers as a side effect of an operation aimed at some other
    resource."

    Design: Corner/state_machines/style_is_created_in_fiber_declared_and_origin_undetermined
    """
    register_market("US")
    brand = register_brand(legal_name="Northline Apparel Co", rn_number="RN12345")

    payload = style_payload(
        brand["id"], style_code="NL-4410", product_class="WOVEN_OUTERWEAR",
        target_market_codes=["US"], net_weight_grams=320.0,
        declared_fibers=[fiber_line("COTTON", 100.0)])
    style = validate_success(
        api.create_style(payload, make_brand_admin_headers(brand["id"])), 201)

    assert_style(style)
    assert style["substantiation_state"] == "FIBER_DECLARED", (
        "a newly created style must sit at the initial fiber state FIBER_DECLARED, "
        f"got {style['substantiation_state']}")
    assert style["origin_state"] == "ORIGIN_UNDETERMINED", (
        "a newly created style must sit at the initial origin state "
        f"ORIGIN_UNDETERMINED, got {style['origin_state']}")
    assert style["label_readiness"] == "BLOCKED", (
        "neither dimension is satisfied on a new style, so label_readiness must "
        f"read BLOCKED, got {style['label_readiness']}")
    assert style["version"] == 1, (
        f"version starts at 1 on creation, got {style['version']}")

    # Both dimensions still read their initial values on a fresh read of the row.
    reread = read_style(style["id"])
    assert reread["substantiation_state"] == "FIBER_DECLARED"
    assert reread["origin_state"] == "ORIGIN_UNDETERMINED"
    assert reread["version"] == 1, "reading a style must not mutate it"
    assert_style_readiness_invariant(reread)

    # No laboratory evidence exists yet for a brand-new style.
    rows, meta = validate_paginated(api.list_style_lab_tests(style["id"], ADMIN))
    assert meta["total_count"] == 0, (
        f"a newly created style owns no laboratory rows, got {meta['total_count']}")
    assert rows == [], f"expected an empty lab-test listing, got {rows}"


def test_submit_moves_a_draft_permanent_label_to_pending_approval(api):
    """PRD 3.5: "On success it moves from `DRAFT` to `PENDING_APPROVAL` and its
    `version` is incremented by 1."
    PRD 3.5: "A newly drafted permanent label lands in state `DRAFT` with
    `parent_label_spec_id` null, `consistency_state` at `NOT_APPLICABLE`,
    `approved_by_user_id`, `revision_note`, `withdrawn_reason`, `effective_from`
    and `effective_to` all null, and `authored_by_user_id` set to the acting
    operator's `X-User-ID`."

    Design: Corner/state_machines/label_spec_submit_moves_draft_to_pending_approval
    """
    author_id = TEST_USERS["labeling_specialist_headers"]["X-User-ID"]
    bundle = setup_label_ready_style()
    label = draft_permanent_label(bundle, headers=SPECIALIST)

    assert_label_spec(label)
    assert label["state"] == "DRAFT", (
        f"a freshly drafted artifact lands in DRAFT, got {label['state']}")
    assert label["artifact_type"] == "PERMANENT_LABEL", (
        "drafting a label directly yields a PERMANENT_LABEL, got "
        f"{label['artifact_type']}")
    assert label["authored_by_user_id"] == author_id, (
        "authored_by_user_id must be the acting operator's X-User-ID, got "
        f"{label['authored_by_user_id']}")
    assert label["approved_by_user_id"] is None, (
        "approved_by_user_id is null on a draft, got "
        f"{label['approved_by_user_id']}")
    assert label["version"] == 1, (
        f"a created artifact starts at version 1, got {label['version']}")

    submitted = validate_success(api.submit_label_spec(label["id"], SPECIALIST), 200)

    assert submitted["state"] == "PENDING_APPROVAL", (
        "submit is the DRAFT -> PENDING_APPROVAL edge, got "
        f"{submitted['state']}")
    assert submitted["approved_by_user_id"] is None, (
        "submission records no approver, got "
        f"{submitted['approved_by_user_id']}")
    assert submitted["authored_by_user_id"] == author_id, (
        "the author frozen at creation must survive the submit, got "
        f"{submitted['authored_by_user_id']}")
    assert submitted["version"] == 2, (
        "the submit is exactly one mutation of the artifact, so version must be 2, "
        f"got {submitted['version']}")
    assert submitted["consistency_state"] == "NOT_APPLICABLE", (
        "consistency_state reads NOT_APPLICABLE on a permanent label, got "
        f"{submitted['consistency_state']}")
    assert submitted["revision_note"] is None
    assert submitted["withdrawn_reason"] is None
    assert submitted["effective_from"] is None
    assert submitted["effective_to"] is None
    assert_label_spec(submitted)


def test_approving_a_draft_label_reports_the_state_error_not_the_evidence_gate(api):
    """PRD 3.6: "The artifact must be in `PENDING_APPROVAL`; any other state is
    rejected with `ERR_LABEL_STATE_INVALID`."
    PRD 2.7: "State legality: the target row must sit in a state from which the
    requested transition is declared — `ERR_LABEL_STATE_INVALID`,
    `ERR_LAB_TEST_STATE_INVALID`, `ERR_ORIGIN_STATE_INVALID`,
    `ERR_SHIPMENT_STATE_INVALID`, `ERR_AUDIT_STATE_INVALID` or
    `ERR_FINDING_STATE_INVALID` (all HTTP 409), on every action endpoint that
    drives a state transition."

    Design: Corner/state_machines/label_spec_approve_directly_from_draft_is_rejected
    """
    # No fiber test at all, so the style's fiber dimension is unsubstantiated and
    # the evidence gate at ladder step 11 is genuinely live on this row too.
    bundle = setup_label_ready_style(skip_fiber=True)
    label = draft_permanent_label(bundle, headers=SPECIALIST)
    assert label["state"] == "DRAFT", "setup must leave the artifact in DRAFT"

    style_before = read_style(bundle["style"]["id"])
    assert style_before["substantiation_state"] != "FIBER_SUBSTANTIATED", (
        "the fiber-substantiation gate must also be violated for this test to be "
        "about ordering at all, got "
        f"{style_before['substantiation_state']}")

    validate_error(api.approve_label_spec(label["id"], APPROVER),
                   ApiErrorId.ERR_LABEL_STATE_INVALID)

    after = read_label(label["id"])
    assert after["state"] == "DRAFT", (
        f"the refused approval must be a no-op, got state {after['state']}")
    assert after["approved_by_user_id"] is None, (
        "a refused approval records no approver, got "
        f"{after['approved_by_user_id']}")
    assert after["version"] == label["version"], (
        "a refused approval must not increment the artifact version, got "
        f"{after['version']} against {label['version']}")


def test_a_compliant_entry_cannot_be_reviewed_a_second_time(api):
    """PRD 3.8: "Only a `CustomsOfficer` decides a marking review, and only from
    `ENTRY_FILED`; a review of any other state is rejected with
    `ERR_SHIPMENT_STATE_INVALID`."
    PRD 3.8: "A compliant outcome moves the entry to the terminal state
    `MARKING_COMPLIANT` and leaves every penalty figure at 0.00."

    Design: Corner/state_machines/compliant_shipment_cannot_be_reviewed_a_second_time
    """
    register_market("US")
    brand = register_brand(legal_name="Northline Apparel Co", rn_number="RN12345")
    style = create_style(brand["id"], style_code="NL-4410",
                        target_market_codes=["US"])

    shipment = file_shipment(brand["id"], style["id"], entry_number="ENT-7001",
                             quantity_units=100, declared_value_usd=400.00,
                             entry_market_code="US")
    assert shipment["marking_state"] == "ENTRY_FILED", (
        f"a filed entry lands in ENTRY_FILED, got {shipment['marking_state']}")

    first = validate_success(
        api.marking_review(shipment["id"], {"outcome": "COMPLIANT"}, CUSTOMS), 200)
    assert_import_shipment(first)
    assert first["marking_state"] == "MARKING_COMPLIANT", (
        "a compliant outcome moves the entry to MARKING_COMPLIANT, got "
        f"{first['marking_state']}")
    assert first["penalty_assessed_usd"] == pytest.approx(0.00, abs=0.01), (
        "a compliant outcome leaves every penalty figure at 0.00, got "
        f"{first['penalty_assessed_usd']}")
    assert first["deficiency_code"] is None, (
        "a compliant outcome stores no deficiency code, got "
        f"{first['deficiency_code']}")
    assert_second_precision_instant(first["review_decided_at"], "review_decided_at")

    # MARKING_COMPLIANT is terminal: the second review is refused on state.
    validate_error(api.marking_review(shipment["id"], marking_review_payload(),
                                      CUSTOMS),
                   ApiErrorId.ERR_SHIPMENT_STATE_INVALID)

    after = validate_success(api.get_import_shipment(shipment["id"], CUSTOMS), 200)
    assert after["marking_state"] == "MARKING_COMPLIANT", (
        "the refused re-review must not move the entry, got "
        f"{after['marking_state']}")
    assert after["penalty_assessed_usd"] == pytest.approx(0.00, abs=0.01), (
        "a cleared entry must keep its zero assessment, got "
        f"{after['penalty_assessed_usd']}")
    assert after["penalty_mitigated_usd"] == pytest.approx(0.00, abs=0.01)
    assert after["deficiency_code"] is None, (
        "the refused re-review must not write a deficiency code, got "
        f"{after['deficiency_code']}")
    assert after["review_decided_at"] == first["review_decided_at"], (
        "the first review instant must survive the refused replay, got "
        f"{after['review_decided_at']} against {first['review_decided_at']}")
    assert after["version"] == first["version"], (
        "a refused review must not increment the entry version, got "
        f"{after['version']} against {first['version']}")

    # A MARKING_COMPLIANT entry contributes nothing to the ledger of record.
    party = read_brand(brand["id"])
    assert party["outstanding_penalty_usd"] == pytest.approx(0.00, abs=0.01), (
        "an entry found MARKING_COMPLIANT contributes nothing to the ledger, got "
        f"{party['outstanding_penalty_usd']}")
    assert party["posture"] == "OPEN", (
        f"an empty ledger leaves the posture OPEN, got {party['posture']}")


def test_a_second_issue_on_an_issued_determination_is_rejected(api):
    """PRD 3.3: "The determination must be in `DRAFT`; an issue against any other
    state is rejected with `ERR_ORIGIN_STATE_INVALID`."
    PRD 3.3: "On success the row records `method_pinned`, derives
    `determined_country` from the frozen pair — `st_country` under substantial
    transformation, `yf_country` under yarn-forward — stamps `issued_at` from the
    logical clock, and moves from `DRAFT` to `ISSUED`."

    Design: Corner/state_machines/second_issue_on_an_already_issued_determination_is_rejected
    """
    brand, style, draft = _drafted_determination_on_divergent_graph(api)
    first = issue_determination(draft["id"], "SUBSTANTIAL_TRANSFORMATION")

    assert_origin_determination(first)
    assert first["state"] == "ISSUED", (
        f"the first issue moves DRAFT -> ISSUED, got {first['state']}")
    assert first["method_pinned"] == "SUBSTANTIAL_TRANSFORMATION", (
        "the pinned method must be the one supplied, got "
        f"{first['method_pinned']}")
    assert first["st_country"] == "VN", (
        "the only transformation-pool node sits in VN, got "
        f"{first['st_country']}")
    assert first["yf_country"] == "IN", (
        "with no YARN node the yarn-forward pool falls back to the FIBER node in "
        f"IN, got {first['yf_country']}")
    assert first["determined_country"] == "VN", (
        "substantial transformation resolves determined_country to st_country, got "
        f"{first['determined_country']}")

    # Issue is not idempotent: replaying it with the other method is refused.
    validate_error(
        api.issue_origin_determination(draft["id"], {"method": "YARN_FORWARD"},
                                       ADMIN),
        ApiErrorId.ERR_ORIGIN_STATE_INVALID)

    after = validate_success(api.get_origin_determination(draft["id"], ADMIN), 200)
    assert after["state"] == "ISSUED", (
        f"the refused replay must leave the row in ISSUED, got {after['state']}")
    assert after["method_pinned"] == "SUBSTANTIAL_TRANSFORMATION", (
        "a refused second issue must not repin the method, got "
        f"{after['method_pinned']}")
    assert after["determined_country"] == "VN", (
        "a refused second issue must not repoint determined_country, got "
        f"{after['determined_country']}")
    assert after["issued_at"] == first["issued_at"], (
        "the first issuance instant must survive the refused replay, got "
        f"{after['issued_at']} against {first['issued_at']}")
    assert after["version"] == first["version"], (
        "a refused issue must not increment the determination version, got "
        f"{after['version']} against {first['version']}")

    style_after = read_style(style["id"])
    assert style_after["origin_state"] == "ORIGIN_ISSUED", (
        "the refused replay must leave the style's origin dimension at "
        f"ORIGIN_ISSUED, got {style_after['origin_state']}")


def test_reopening_a_finding_that_is_still_open_is_rejected(api):
    """PRD 3.9: "It requires the finding to be in `CLOSED` and the parent audit to
    be in any state other than `CLOSED`."
    PRD 3.9: "A new finding lands in state `OPEN` with `units_relabeled`,
    `units_destroyed` and `units_released` all 0, `units_unresolved` equal to
    `units_affected`, `corrective_label_spec_id` null, and
    `disposition_recorded_at`, `verified_at` and `reopen_reason` all null."

    Design: Corner/state_machines/reopen_on_an_open_finding_is_rejected
    """
    register_market("US")
    brand = register_brand(legal_name="Northline Apparel Co", rn_number="RN12345")
    style = create_style(brand["id"], style_code="NL-4410",
                        target_market_codes=["US"])
    audit = open_audit(brand["id"])
    finding = raise_finding(audit["id"], style["id"],
                           finding_code="PLACEMENT_NON_PERMANENT",
                           units_affected=100)

    assert_audit_finding(finding)
    assert finding["state"] == "OPEN", (
        f"a new finding lands in OPEN, got {finding['state']}")
    assert finding["severity"] == "MAJOR", (
        "PLACEMENT_NON_PERMANENT is MAJOR and 100 units is below the 5,000-unit "
        f"escalation breakpoint, got {finding['severity']}")
    assert finding["units_unresolved"] == 100, (
        "units_unresolved starts equal to units_affected, got "
        f"{finding['units_unresolved']}")
    assert finding["reopen_reason"] is None, (
        f"reopen_reason starts null, got {finding['reopen_reason']}")

    # The only edge into OPEN from elsewhere is CLOSED -> OPEN.
    validate_error(
        api.reopen_finding(finding["id"],
                           "Reopening a finding that was never closed.", AUDITOR),
        ApiErrorId.ERR_FINDING_STATE_INVALID)

    after = read_finding(finding["id"])
    assert after["state"] == "OPEN", (
        f"the refused reopen must leave the finding in OPEN, got {after['state']}")
    assert after["reopen_reason"] is None, (
        "a refused reopen must not store a reason, got "
        f"{after['reopen_reason']}")
    assert after["units_unresolved"] == 100, (
        "a refused reopen must not disturb the unit buckets, got "
        f"{after['units_unresolved']}")
    assert after["version"] == finding["version"], (
        "a refused reopen must not increment the finding version, got "
        f"{after['version']} against {finding['version']}")

    audit_after = read_audit(audit["id"])
    assert_compliance_audit(audit_after)
    assert audit_after["state"] == "IN_REVIEW", (
        "the audit took its first finding and moved to IN_REVIEW, got "
        f"{audit_after['state']}")
    assert audit_after["open_finding_count"] == 1, (
        "the one OPEN finding is still counted, got "
        f"{audit_after['open_finding_count']}")
    assert audit_after["units_in_scope"] == 100, (
        "units_in_scope sums units_affected over every finding, got "
        f"{audit_after['units_in_scope']}")


def test_issue_pins_the_method_and_advances_the_owning_style_origin_dimension(api):
    """PRD 3.3: "On success the row records `method_pinned`, derives
    `determined_country` from the frozen pair — `st_country` under substantial
    transformation, `yf_country` under yarn-forward — stamps `issued_at` from the
    logical clock, and moves from `DRAFT` to `ISSUED`."
    PRD 3.3: "The style's `origin_state` advances from `ORIGIN_DRAFTED` to
    `ORIGIN_ISSUED`, `label_readiness` is recomputed, and both the determination's
    `version` and the style's `version` are incremented by 1."
    PRD 2.4: "At server startup the logical clock reads exactly
    `2026-08-01T00:00:00Z`, and until it is explicitly moved it must not fall back
    to real time."

    Design: Corner/state_machines/origin_issue_pins_the_method_and_advances_the_style_origin_dimension
    """
    brand, style, draft = _drafted_determination_on_divergent_graph(api)

    assert draft["state"] == "DRAFT", (
        f"a new determination is created in DRAFT, got {draft['state']}")
    assert draft["graph_node_count"] == 2, (
        "both non-ornamentation nodes enter the population, got "
        f"{draft['graph_node_count']}")
    assert draft["method_pinned"] is None, (
        f"method_pinned is null while the row is a DRAFT, got {draft['method_pinned']}")
    assert draft["determined_country"] is None, (
        "determined_country is null while the row is a DRAFT, got "
        f"{draft['determined_country']}")
    assert draft["issued_at"] is None, (
        f"issued_at is unstamped on a DRAFT, got {draft['issued_at']}")

    style_drafted = read_style(style["id"])
    assert style_drafted["origin_state"] == "ORIGIN_DRAFTED", (
        "drafting moves the style from ORIGIN_UNDETERMINED to ORIGIN_DRAFTED, got "
        f"{style_drafted['origin_state']}")
    style_version_before = style_drafted["version"]

    issued = validate_success(
        api.issue_origin_determination(
            draft["id"], {"method": "SUBSTANTIAL_TRANSFORMATION"}, ADMIN), 200)

    assert_origin_determination(issued)
    assert issued["state"] == "ISSUED", (
        f"issue drives DRAFT -> ISSUED, got {issued['state']}")
    assert issued["method_pinned"] == "SUBSTANTIAL_TRANSFORMATION", (
        f"the supplied method must be pinned, got {issued['method_pinned']}")
    assert issued["st_country"] == "VN", (
        f"the frozen transformation country is VN, got {issued['st_country']}")
    assert issued["yf_country"] == "IN", (
        f"the frozen yarn-forward country is IN, got {issued['yf_country']}")
    assert issued["divergent"] is True, (
        "the two candidate countries disagree, so divergent must be true, got "
        f"{issued['divergent']}")
    assert issued["determined_country"] == "VN", (
        "under SUBSTANTIAL_TRANSFORMATION determined_country derives from "
        f"st_country, got {issued['determined_country']}")
    assert_second_precision_instant(issued["issued_at"], "issued_at")
    assert issued["issued_at"] == CLOCK_STARTUP, (
        "issued_at is stamped from the unmoved logical clock, got "
        f"{issued['issued_at']}")
    assert issued["version"] == draft["version"] + 1, (
        "the issuance is exactly one mutation of the determination, got "
        f"{issued['version']} against {draft['version']}")

    style_after = read_style(style["id"])
    assert style_after["origin_state"] == "ORIGIN_ISSUED", (
        "the cross-entity effect: the owning style's origin dimension must advance "
        f"to ORIGIN_ISSUED, got {style_after['origin_state']}")
    assert style_after["version"] == style_version_before + 1, (
        "the style's version is incremented by 1 by the issuance, got "
        f"{style_after['version']} against {style_version_before}")
    assert_style_readiness_invariant(style_after)
