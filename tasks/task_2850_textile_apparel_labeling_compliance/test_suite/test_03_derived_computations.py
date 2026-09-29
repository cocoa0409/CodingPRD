"""Derived computations of the labeling-compliance service.

Care-performance verdicts, the canonical printable fiber string, the audit
rollup, the label content fingerprint and the two origin pools.
"""
from test_helpers import (
    ADMIN,
    AUDITOR,
    CLOCK_STARTUP,
    LAB,
    SPECIALIST,
    assert_audit_finding,
    assert_compliance_audit,
    assert_label_spec,
    assert_lab_test,
    assert_material_input,
    assert_origin_determination,
    assert_second_precision_instant,
    assert_style,
    build_supply_graph,
    care_results_payload,
    care_test_payload,
    compliance_audit_payload,
    create_style,
    disposition_payload,
    draft_determination,
    expected_content_hash,
    fiber_line,
    open_audit,
    pass_care_test,
    permanent_label_payload,
    raise_finding,
    read_audit,
    read_finding,
    read_style,
    register_brand,
    register_market,
    style_payload,
    style_version,
    validate_paginated,
    validate_success,
)

# The care-performance bench window shared by the two runs of the boundary test.
_CARE_WINDOW = {
    "lab_code": "LAB-ATL-1",
    "method": "AATCC_135",
    "specimen_received_at": "2026-08-03T09:00:00Z",
    "results_due_at": "2026-08-05T09:00:00Z",
    "wash_temp_c": 30,
}


def test_care_verdict_is_inclusive_on_all_three_declared_minimums(api):
    """PRD 3.4: "A care-performance run passes when `cycles_run` is at least 5, the absolute value of `dimensional_change_pct` is at most 3.0 percent, and `colorfastness_grade` is at least 3.5."

    PRD 3.4: "Note that `legibility_cycles` is deliberately **not** part of the
    care verdict; it is consumed later, by the durability gate at label approval."

    PRD 3.4: "a fiber-content row expires one year — 365 days — after its
    specimen was received, and a care-performance row expires two years — 730
    days — after its specimen was received."

    PRD 3.4: "A care-performance reservation leaves both style dimensions untouched."

    Design: Corner/calculations/care_performance_verdict_sits_exactly_on_the_three_declared_minimums
    """
    register_market("US")
    brand = register_brand()
    style_pass = create_style(brand["id"])
    style_fail = create_style(brand["id"])

    reserved_pass = validate_success(
        api.create_lab_test(care_test_payload(style_pass["id"], **_CARE_WINDOW), LAB), 201)
    reserved_fail = validate_success(
        api.create_lab_test(care_test_payload(style_fail["id"], **_CARE_WINDOW), LAB), 201)
    for reserved in (reserved_pass, reserved_fail):
        assert_lab_test(reserved)
        assert reserved["state"] == "BENCH_RESERVED", (
            f"A successful reservation creates the row in BENCH_RESERVED, got "
            f"{reserved['state']}")
        assert reserved["attempt_no"] == 1, (
            f"A fresh reservation carries attempt_no 1, got {reserved['attempt_no']}")
        assert reserved["valid_until"] is None, (
            "valid_until is stamped only when a run passes, so it is null on a "
            "BENCH_RESERVED row")

    passed = validate_success(api.post_lab_test_results(
        reserved_pass["id"],
        care_results_payload(cycles_run=5, dimensional_change_pct=3.0,
                             colorfastness_grade=3.5, legibility_cycles=12),
        LAB), 200)
    failed = validate_success(api.post_lab_test_results(
        reserved_fail["id"],
        care_results_payload(cycles_run=5, dimensional_change_pct=3.1,
                             colorfastness_grade=3.5, legibility_cycles=12),
        LAB), 200)

    assert passed["state"] == "PASSED", (
        "cycles_run 5, dimensional_change_pct 3.0 and colorfastness_grade 3.5 sit "
        f"exactly on all three inclusive minimums, so the run passes; got "
        f"{passed['state']}")
    assert failed["state"] == "FAILED", (
        "0.1 percentage point of extra shrinkage (3.1 against the 3.0 maximum) "
        f"flips the verdict to FAILED; got {failed['state']}")

    assert passed["legibility_cycles"] == 12, (
        "legibility_cycles is stored on the row even though it never enters the "
        f"care verdict, got {passed['legibility_cycles']}")

    assert_second_precision_instant(passed["valid_until"], "valid_until")
    assert passed["valid_until"] == "2028-08-02T09:00:00Z", (
        "A care-performance horizon is specimen_received_at 2026-08-03T09:00:00Z "
        f"plus 730 days, never the posting instant; got {passed['valid_until']}")
    assert failed["valid_until"] is None, (
        f"A FAILED run is never stamped with a horizon, got {failed['valid_until']}")

    for style_id in (style_pass["id"], style_fail["id"]):
        style = read_style(style_id)
        assert_style(style)
        assert style["substantiation_state"] == "FIBER_DECLARED", (
            "A care-performance reservation and its verdict leave the fiber "
            f"dimension untouched at FIBER_DECLARED, got "
            f"{style['substantiation_state']}")


def test_printable_fiber_string_breaks_percentage_ties_by_name_at_one_decimal(api):
    """PRD 3.2: "The listed lines are sorted by `declared_pct` descending, and lines with equal percentages are then ordered by `fiber_generic_name` ascending; insertion order and row identifiers never participate."

    PRD 3.2: "Each listed line renders as its percentage at exactly one decimal
    place, then a percent sign, then a single space, then the fiber name."

    Design: Corner/calculations/effective_fiber_content_text_renders_one_decimal_and_breaks_percentage_ties_alphabetically
    """
    register_market("US")
    brand = register_brand()

    # Submission order is LINEN, VISCOSE, COTTON on purpose: it must not survive
    # into the rendered string.
    payload = style_payload(
        brand["id"],
        style_code="NL-TIE-1",
        net_weight_grams=300.0,
        declared_fibers=[
            fiber_line("LINEN", 33.3),
            fiber_line("VISCOSE", 33.4),
            fiber_line("COTTON", 33.3),
        ])
    style = validate_success(api.create_style(payload, ADMIN), 201)
    assert_style(style)

    text = style["effective_fiber_content_text"]
    assert text == "33.4% VISCOSE, 33.3% COTTON, 33.3% LINEN", (
        "33.4 leads on percentage; the two lines tied at 33.3 order COTTON before "
        f"LINEN by fiber name, not by submission order; got {text!r}")
    assert "OTHER FIBER" not in text, (
        "Every line is at or above the 5.0 listing threshold and none is "
        f"ornamentation-exempt, so no bucketed segment is appended; got {text!r}")


def test_audit_rollup_keeps_a_remediated_finding_inside_the_open_set(api):
    """PRD 3.9: "`open_finding_count` counts the findings whose state is `OPEN` **or** `REMEDIATED` — a remediated finding is still open for closure purposes, because nobody has verified it yet."

    PRD 3.9: "an audit in `IN_REVIEW` whose open-finding count has reached 0
    moves to `PENDING_CLOSURE`, and an audit in `PENDING_CLOSURE` whose
    open-finding count has risen above 0 falls back to `IN_REVIEW`."

    Design: Corner/calculations/audit_rollup_still_counts_a_remediated_finding_as_open
    """
    register_market("US")
    brand = register_brand()
    style_a = create_style(brand["id"], style_code="NL-A1")
    style_b = create_style(brand["id"], style_code="NL-A2")

    audit = validate_success(
        api.create_compliance_audit(compliance_audit_payload(brand["id"]), AUDITOR), 201)
    assert_compliance_audit(audit)
    assert audit["state"] == "OPEN", (
        f"A new audit lands in OPEN, got {audit['state']}")

    finding_a = raise_finding(audit["id"], style_a["id"],
                              finding_code="PLACEMENT_NON_PERMANENT", units_affected=100)
    finding_b = raise_finding(audit["id"], style_b["id"],
                              finding_code="IDENTITY_MISSING", units_affected=40)
    for finding in (finding_a, finding_b):
        assert finding["severity"] == "MAJOR", (
            "PLACEMENT_NON_PERMANENT and IDENTITY_MISSING are MAJOR, and neither "
            f"reaches the 5,000-unit escalation breakpoint; got {finding['severity']}")

    before = read_audit(audit["id"])
    assert before["state"] == "IN_REVIEW", (
        f"The first finding drives the audit out of OPEN, got {before['state']}")
    assert before["open_finding_count"] == 2, (
        f"Two OPEN findings, got {before['open_finding_count']}")
    assert before["critical_finding_count"] == 0, (
        f"Neither MAJOR finding is CRITICAL, got {before['critical_finding_count']}")
    assert before["units_in_scope"] == 140, (
        f"units_in_scope sums 100 + 40, got {before['units_in_scope']}")

    remediated = validate_success(api.record_finding_disposition(
        finding_a["id"], disposition_payload(0, 100, 0), SPECIALIST), 200)
    assert remediated["state"] == "REMEDIATED", (
        f"A complete disposition moves the finding to REMEDIATED, got "
        f"{remediated['state']}")

    mid = read_audit(audit["id"])
    assert mid["open_finding_count"] == 2, (
        "REMEDIATED is still inside the open set, so the count must stay at 2, got "
        f"{mid['open_finding_count']}")
    assert mid["critical_finding_count"] == 0, (
        f"Still no CRITICAL finding, got {mid['critical_finding_count']}")
    assert mid["units_in_scope"] == 140, (
        f"units_in_scope is invariant under disposition, got {mid['units_in_scope']}")
    assert mid["state"] == "IN_REVIEW", (
        "The open-finding count has not reached 0, so the audit must not move to "
        f"PENDING_CLOSURE; got {mid['state']}")

    closed = validate_success(api.verify_finding(finding_a["id"], AUDITOR), 200)
    assert closed["state"] == "CLOSED", (
        f"Verification closes the finding, got {closed['state']}")

    after = read_audit(audit["id"])
    assert after["open_finding_count"] == 1, (
        "Only the CLOSED finding leaves the open set, got "
        f"{after['open_finding_count']}")
    assert after["units_in_scope"] == 140, (
        f"units_in_scope is invariant under verification, got {after['units_in_scope']}")
    assert after["state"] == "IN_REVIEW", (
        f"The second finding is still open, got {after['state']}")
    assert read_finding(finding_b["id"])["state"] == "OPEN", (
        "The untouched sibling finding is the one still holding the count at 1")


def test_content_hash_folds_case_and_whitespace_but_not_the_care_codes(api):
    """PRD 3.5: "It is built by concatenating five segments separated by a single vertical-bar character, in this order: the normalized `fiber_content_text`; the normalized `origin_text`; the care code string; the identity string; and the artifact's `languages` sorted ascending and joined with a single comma between entries."

    PRD 3.5: "The care code string is the `wash_temp_c` value rendered as a
    string, then a forward slash, then `bleach_code`, a forward slash,
    `dry_code`, a forward slash, `iron_code`, a forward slash, and
    `dryclean_code`."

    Design: Corner/calculations/label_content_hash_normalizes_case_and_whitespace_but_not_care_codes
    """
    register_market("US")
    brand = register_brand(legal_name="Northline Apparel Co", rn_number="RN12345")
    style = create_style(brand["id"], style_code="NL-4410", net_weight_grams=320.0,
                         declared_fibers=[fiber_line("COTTON", 100.0)])
    build_supply_graph(style["id"], [
        {"stage": "FIBER", "country_code": "IN", "value_added_usd": 2.00,
         "weight_grams": 500.0},
        {"stage": "CUT_AND_SEW", "country_code": "VN", "value_added_usd": 9.00,
         "weight_grams": 900.0, "_parent": 0},
    ])
    determination = draft_determination(style["id"], SPECIALIST)
    care = pass_care_test(
        style["id"],
        reserve_overrides={"lab_code": "LAB-ATL-1", "wash_temp_c": 30},
        results_overrides={"cycles_run": 5, "dimensional_change_pct": 2.0,
                           "colorfastness_grade": 4.0, "legibility_cycles": 40})

    base = permanent_label_payload(
        style["id"], determination["id"], care["id"],
        market_codes=["US"], languages=["en"], durability_cycles_rating=40,
        wash_temp_c=30, fiber_content_text="100.0% COTTON", origin_text="Made in VN")

    label_a = validate_success(api.create_label_spec(dict(base), SPECIALIST), 201)
    label_b = validate_success(api.create_label_spec(
        dict(base, fiber_content_text="  100.0%   cotton ",
             origin_text="made in vn"), SPECIALIST), 201)
    label_c = validate_success(api.create_label_spec(
        dict(base, iron_code="IRON_MEDIUM"), SPECIALIST), 201)

    for label in (label_a, label_b, label_c):
        assert_label_spec(label)
    assert len({label_a["id"], label_b["id"], label_c["id"]}) == 3, (
        "The three drafts are distinct rows")

    expected = expected_content_hash(
        "100.0% COTTON", "Made in VN", 30, "NO_BLEACH", "TUMBLE_LOW", "IRON_LOW",
        "DO_NOT_DRYCLEAN", "RN", ["en"], rn_number="RN12345")
    assert label_a["content_hash"] == expected, (
        "content_hash is the SHA-256 of the five bar-separated canonical segments, "
        f"expected {expected}, got {label_a['content_hash']}")
    assert label_b["content_hash"] == label_a["content_hash"], (
        "Trim, internal-whitespace collapse and uppercasing fold the two differently "
        f"typed drafts onto one canonical string: {label_b['content_hash']} vs "
        f"{label_a['content_hash']}")
    assert label_c["content_hash"] != label_a["content_hash"], (
        "iron_code enters the care code segment verbatim, so IRON_MEDIUM must change "
        f"the fingerprint; both read {label_a['content_hash']}")


def test_origin_pools_ignore_ornamentation_and_trim_nodes(api):
    """PRD 3.3: "The population for both is every material-input node of the style whose `is_ornamentation` flag is false, with no state filter of any kind because a supply node has no lifecycle; the count of that population is stored as `graph_node_count`."

    PRD 3.3: "The **substantial-transformation** variant takes the
    non-ornamentation nodes whose stage is `YARN`, `FABRIC` or `CUT_AND_SEW`,
    groups them by `country_code`, and for each country sums the
    `value_added_usd` of its nodes at 2 decimal places."

    PRD 3.3: "The **yarn-forward** variant takes only the non-ornamentation nodes
    whose stage is `YARN`; if the style has no yarn node at all, and only then, it
    falls back to the nodes whose stage is `FIBER`."

    Design: Corner/calculations/origin_pools_exclude_ornamentation_and_trim_nodes
    """
    register_market("US")
    brand = register_brand()
    style = create_style(brand["id"], style_code="NL-ORN-1", net_weight_grams=320.0,
                         declared_fibers=[fiber_line("COTTON", 100.0)])
    nodes = build_supply_graph(style["id"], [
        {"stage": "FIBER", "country_code": "IN", "value_added_usd": 2.00,
         "weight_grams": 500.0},
        {"stage": "YARN", "country_code": "PK", "value_added_usd": 3.00,
         "weight_grams": 520.0, "_parent": 0},
        {"stage": "FABRIC", "country_code": "CN", "value_added_usd": 6.00,
         "weight_grams": 950.0, "_parent": 1},
        {"stage": "TRIM", "country_code": "FR", "value_added_usd": 4.00,
         "weight_grams": 30.0, "is_ornamentation": True},
    ])
    for node in nodes:
        assert_material_input(node)

    draft = validate_success(api.create_origin_determination(
        {"style_id": style["id"], "expected_style_version": style_version(style["id"])},
        SPECIALIST), 201)
    assert_origin_determination(draft)

    assert draft["graph_node_count"] == 3, (
        "The ornamentation TRIM node is excluded from the scored population, so the "
        f"count is 3 of the 4 stored nodes; got {draft['graph_node_count']}")
    assert draft["st_country"] == "CN", (
        "CN's FABRIC node contributes 6.00 against PK's 3.00 of YARN, and the FR "
        f"trim's 4.00 never enters the transformation pool; got {draft['st_country']}")
    assert draft["yf_country"] == "PK", (
        "PK is the only non-ornamentation YARN country at 520.0 g, so no FIBER "
        f"fallback happens; got {draft['yf_country']}")
    assert draft["divergent"] is True, (
        "st_country CN and yf_country PK differ, so divergent is true; got "
        f"{draft['divergent']}")
    assert draft["determined_country"] is None, (
        f"No method is pinned on a DRAFT row, got {draft['determined_country']}")
    assert draft["method_pinned"] is None, (
        f"No method is pinned on a DRAFT row, got {draft['method_pinned']}")

    issued = validate_success(api.issue_origin_determination(
        draft["id"], {"method": "YARN_FORWARD"}, ADMIN), 200)
    assert issued["state"] == "ISSUED", (
        f"Issuance moves the row from DRAFT to ISSUED, got {issued['state']}")
    assert issued["method_pinned"] == "YARN_FORWARD", (
        f"The pinned method is recorded, got {issued['method_pinned']}")
    assert issued["determined_country"] == "PK", (
        "Under yarn-forward the determined country is the frozen yf_country, got "
        f"{issued['determined_country']}")

    style_after = read_style(style["id"])
    assert_style(style_after)
    assert style_after["origin_state"] == "ORIGIN_ISSUED", (
        f"Issuance advances the origin dimension, got {style_after['origin_state']}")

    listed, meta = validate_paginated(
        api.list_material_inputs(ADMIN, params={"style_id": style["id"]}))
    assert meta["total_count"] == 4, (
        "All four nodes are stored, including the ornamentation trim row that is "
        f"merely not scored; got total_count {meta['total_count']}")
    assert len(listed) == 4, f"Expected 4 nodes on the page, got {len(listed)}"


def test_disposition_and_verification_are_already_rolled_up_on_the_next_read(api):
    """PRD 3.9: "`units_in_scope` sums `units_affected` over **every** finding of the audit with no state filter at all, which is what makes it invariant under disposition, verification and reopening."

    PRD 3.9: "On success the finding stores the three counters, the corrective
    reference and a `disposition_recorded_at` stamped from the logical clock, and
    moves from `OPEN` to `REMEDIATED`."

    PRD 3.9: "The first hop stamps `verified_at` from the logical clock and moves
    the finding to `CLOSED`. The second hop, caused by the first, re-derives the
    parent audit's counters"

    Design: Corner/consistency_model/a_disposition_response_already_shows_the_recomputed_audit_rollup
    """
    register_market("US")
    brand = register_brand()
    style_a = create_style(brand["id"], style_code="NL-4410", net_weight_grams=320.0)
    style_b = create_style(brand["id"], style_code="NL-4411",
                           product_class="KNIT_TOP", net_weight_grams=200.0)

    audit = open_audit(brand["id"])
    finding_a = raise_finding(audit["id"], style_a["id"],
                             finding_code="ORIGIN_MISSTATED", units_affected=400)
    finding_b = raise_finding(audit["id"], style_b["id"],
                             finding_code="FIBER_CONTENT_MISSTATED", units_affected=300)
    for finding in (finding_a, finding_b):
        assert_audit_finding(finding)
        assert finding["severity"] == "CRITICAL", (
            "ORIGIN_MISSTATED and FIBER_CONTENT_MISSTATED are CRITICAL from their "
            f"code alone, got {finding['severity']}")

    before = read_audit(audit["id"])
    assert_compliance_audit(before)
    assert before["state"] == "IN_REVIEW", (
        f"The first finding drove the audit out of OPEN, got {before['state']}")
    assert before["open_finding_count"] == 2, (
        f"Two OPEN findings, got {before['open_finding_count']}")
    assert before["critical_finding_count"] == 2, (
        f"Both open findings are CRITICAL, got {before['critical_finding_count']}")
    assert before["units_in_scope"] == 700, (
        f"units_in_scope sums 400 + 300, got {before['units_in_scope']}")

    remediated = validate_success(api.record_finding_disposition(
        finding_a["id"], disposition_payload(0, 150, 250), SPECIALIST), 200)
    assert_audit_finding(remediated)
    assert remediated["state"] == "REMEDIATED", (
        "The disposition response itself already reports REMEDIATED, got "
        f"{remediated['state']}")
    assert remediated["units_unresolved"] == 0, (
        "150 destroyed plus 250 released exhausts the 400 affected units in the "
        f"very same response, got {remediated['units_unresolved']}")
    assert remediated["units_destroyed"] == 150
    assert remediated["units_released"] == 250
    assert_second_precision_instant(remediated["disposition_recorded_at"],
                                    "disposition_recorded_at")
    assert remediated["disposition_recorded_at"] == CLOCK_STARTUP, (
        "disposition_recorded_at is stamped from the logical clock, which still "
        f"reads {CLOCK_STARTUP}; got {remediated['disposition_recorded_at']}")

    closed = validate_success(api.verify_finding(finding_a["id"], AUDITOR), 200)
    assert closed["state"] == "CLOSED", (
        f"The verify response itself already reports CLOSED, got {closed['state']}")
    assert_second_precision_instant(closed["verified_at"], "verified_at")
    assert closed["verified_at"] == CLOCK_STARTUP, (
        "verified_at is stamped from the logical clock, which has not moved; got "
        f"{closed['verified_at']}")

    after = read_audit(audit["id"])
    assert after["open_finding_count"] == 1, (
        "The very next read, with no intervening write and no clock advance, already "
        f"shows the closed finding gone from the open set; got "
        f"{after['open_finding_count']}")
    assert after["critical_finding_count"] == 1, (
        "Only the still-open CRITICAL finding remains counted, got "
        f"{after['critical_finding_count']}")
    assert after["units_in_scope"] == 700, (
        "units_in_scope has no state filter, so it is invariant under disposition "
        f"and verification; got {after['units_in_scope']}")
    assert after["state"] == "IN_REVIEW", (
        "One finding is still open, so the audit cannot reach PENDING_CLOSURE; got "
        f"{after['state']}")
