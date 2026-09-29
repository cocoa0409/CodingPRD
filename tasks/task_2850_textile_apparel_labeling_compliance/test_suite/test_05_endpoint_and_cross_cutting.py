"""Endpoint-layer and cross-cutting-layer corner coverage.

Each test in this module translates exactly one design instance: the endpoint
round trips (audit create/read/filtered list, the computed compliance summary,
hangtag creation off a parent, retest conditionality, withdrawal cascade) and
the three optimistic-concurrency guards of PRD 2.5.
"""
from test_helpers import *  # noqa: F401,F403


def _hangtag_body(parent, expected_version, **overrides):
    """A hangtag payload whose printed strings, markets and languages are copied
    from the parent permanent label, carrying an explicit parent-version guard."""
    payload = hangtag_payload(
        expected_version,
        market_codes=list(parent["market_codes"]),
        languages=list(parent["languages"]),
        marketing_claims=[],
        fiber_content_text=parent["fiber_content_text"],
        origin_text=parent["origin_text"],
    )
    payload.update(overrides)
    return payload


def test_compliance_audit_create_read_and_filtered_list_round_trip(api):
    """PRD 3.9: "A new audit lands in state `OPEN` with `open_finding_count`, `critical_finding_count` and `units_in_scope` all at 0 and `closed_at` null; all three counters are derived from the child findings and are never supplied by the caller."

    PRD 3.9: "Audits are readable individually with their rolled-up counts, and
    the audit list is ordered by `created_at` ascending with optional `brand_id`,
    `state` and `scope` filters."

    Design: Corner/endpoints/compliance_audit_create_read_and_filtered_list_round_trip
    """
    brand = register_brand(legal_name="Northline Apparel Co", rn_number="RN12345")

    payload = compliance_audit_payload(
        brand["id"], scope="STYLE_DOSSIER",
        audit_window_from="2026-01-01T00:00:00Z",
        audit_window_to="2026-12-31T00:00:00Z")
    created = validate_success(api.create_compliance_audit(payload, AUDITOR), 201)

    assert_compliance_audit(created)
    assert created["brand_id"] == brand["id"], "the audit must name the audited brand"
    assert created["state"] == "OPEN", f"a new audit lands in OPEN, got {created['state']}"
    assert created["open_finding_count"] == 0, "open_finding_count starts at 0"
    assert created["critical_finding_count"] == 0, "critical_finding_count starts at 0"
    assert created["units_in_scope"] == 0, "units_in_scope starts at 0"
    assert created["closed_at"] is None, "closed_at is null on a new audit"
    assert_second_precision_instant(created["audit_window_from"], "audit_window_from")
    assert_second_precision_instant(created["audit_window_to"], "audit_window_to")
    assert_millisecond_instant(created["created_at"], "created_at")

    read = validate_success(api.get_compliance_audit(created["id"], ADMIN), 200)
    assert read["id"] == created["id"], "the audit must read back by its own id"
    assert read["state"] == "OPEN", "the individual read agrees with the create"
    assert read["scope"] == "STYLE_DOSSIER", "the individual read echoes the scope"
    assert read["audit_window_from"] == "2026-01-01T00:00:00Z", (
        "audit_window_from round-trips at second precision"
    )
    assert read["open_finding_count"] == 0, "the rolled-up count reads back as 0"

    open_rows, open_meta = validate_paginated(api.list_compliance_audits(
        ADMIN, params={"brand_id": brand["id"], "state": "OPEN"}))
    assert [row["id"] for row in open_rows] == [created["id"]], (
        "the OPEN listing must return exactly the created audit"
    )
    assert open_meta["total_count"] == 1, "total_count counts the matching rows"
    assert open_meta["has_more"] is False, "a single row leaves nothing beyond the page"

    closed_rows, closed_meta = validate_paginated(api.list_compliance_audits(
        ADMIN, params={"brand_id": brand["id"], "state": "CLOSED"}))
    assert closed_rows == [], "a CLOSED filter must not return the OPEN audit"
    assert closed_meta["total_count"] == 0, "total_count is 0 when nothing matches"


def test_compliance_summary_reports_every_blocking_reason_of_a_bare_style(api):
    """PRD 3.9: "And it returns `blocking_reasons`, the list of error identifiers for the four style-level gates that are not yet satisfied, listed in ladder order: `ERR_FIBER_NOT_SUBSTANTIATED` while `substantiation_state` is anything other than `FIBER_SUBSTANTIATED`, `ERR_ORIGIN_NOT_ISSUED` while `origin_state` is anything other than `ORIGIN_ISSUED`, `ERR_CARE_NOT_SUBSTANTIATED` while the style has no passed care-performance run, and `ERR_DURABILITY_INSUFFICIENT` while the substantiated cycles figure is strictly less than the required one."

    PRD 3.9: "It returns `substantiated_durability_cycles`, which is the
    `legibility_cycles` of the newest passed care-performance run of the style and
    reads 0 when the style has none." ... "The read stores nothing."

    Design: Corner/endpoints/compliance_summary_reports_every_blocking_reason_of_a_bare_style
    """
    register_market("US", min_durability_cycles=20)
    brand = register_brand(legal_name="Northline Apparel Co", rn_number="RN12345")
    style = create_style(
        brand["id"], style_code="NL-4410", product_class="WOVEN_OUTERWEAR",
        target_market_codes=["US"], net_weight_grams=320.0,
        declared_fibers=[fiber_line("COTTON", 100.0)])
    version_before = style["version"]

    data = validate_success(api.get_compliance_summary(style["id"], SPECIALIST), 200)

    assert data["style_id"] == style["id"], "the summary names the style it read"
    assert data["substantiation_state"] == "FIBER_DECLARED", (
        "a style with no laboratory evidence stands at FIBER_DECLARED"
    )
    assert data["origin_state"] == "ORIGIN_UNDETERMINED", (
        "a style with no determination stands at ORIGIN_UNDETERMINED"
    )
    assert data["label_readiness"] == "BLOCKED", (
        "label_readiness is BLOCKED unless both dimensions are satisfied"
    )
    assert data["effective_fiber_content_text"] == "100.0% COTTON", (
        "the single listed line renders at one decimal place"
    )
    assert data["determined_country"] is None, (
        "determined_country is null unless the style has an issued determination"
    )
    assert data["published_permanent_label_count"] == 0, (
        "the style has published no permanent label"
    )

    expected_floor = expected_durability_floor({"US": 20}, ["US"], "WOVEN_OUTERWEAR")
    assert expected_floor == 20, "the US floor of 20 scales by 1.00 for WOVEN_OUTERWEAR"
    assert data["required_durability_cycles"] == expected_floor, (
        f"required_durability_cycles must be {expected_floor}, "
        f"got {data['required_durability_cycles']}"
    )
    assert data["substantiated_durability_cycles"] == 0, (
        "the substantiated figure reads 0 when the style has no passed care run"
    )
    assert data["blocking_reasons"] == [
        ApiErrorId.ERR_FIBER_NOT_SUBSTANTIATED.value,
        ApiErrorId.ERR_ORIGIN_NOT_ISSUED.value,
        ApiErrorId.ERR_CARE_NOT_SUBSTANTIATED.value,
        ApiErrorId.ERR_DURABILITY_INSUFFICIENT.value,
    ], f"all four style-level gates must be listed in ladder order, got {data['blocking_reasons']}"

    after = validate_success(api.get_style(style["id"], ADMIN), 200)
    assert after["version"] == version_before, (
        "the computed read stores nothing, so the style version must not move"
    )


def test_hangtag_creation_links_and_inherits_from_its_parent_permanent_label(api):
    """PRD 3.7: "A created hangtag lands in `DRAFT` with `artifact_type` set to `HANGTAG`, `parent_label_spec_id` set to the parent's identifier, `style_id` copied from the parent, `placement_code` fixed to `NOT_PERMANENT`, and both `origin_determination_id` and `care_test_id` null."

    PRD 3.5: "Only fields of the artifact itself plus the registered
    identification number and legal name of the party that owns its style
    participate; for a hangtag the care code fields and `identity_display_mode`
    are inherited verbatim from the parent permanent label at creation time,
    which is why two artifacts printing the same text produce the same hash."

    PRD 3.7: "The parent permanent label's own `version` is incremented by 1 by
    the creation, which is precisely why the next hangtag create must carry the
    parent's new version."

    Design: Corner/endpoints/hangtag_creation_links_and_inherits_from_its_parent_permanent_label
    """
    bundle = setup_label_ready_style()
    parent = draft_permanent_label(bundle)
    assert parent["artifact_type"] == "PERMANENT_LABEL", "the drafted artifact is the sewn-in label"
    parent_version = parent["version"]

    hangtag = validate_success(
        api.create_hangtag(parent["id"], _hangtag_body(parent, parent_version),
                           SPECIALIST), 201)

    assert_label_spec(hangtag)
    assert hangtag["artifact_type"] == "HANGTAG", "the sub-resource yields a HANGTAG"
    assert hangtag["parent_label_spec_id"] == parent["id"], (
        "parent_label_spec_id is set to the parent named in the path"
    )
    assert hangtag["style_id"] == parent["style_id"], "style_id is copied from the parent"
    assert hangtag["style_id"] == bundle["style"]["id"], "and resolves to the parent's style"
    assert hangtag["placement_code"] == "NOT_PERMANENT", (
        "placement_code is fixed to NOT_PERMANENT on a hangtag"
    )
    assert hangtag["origin_determination_id"] is None, "a hangtag pins no determination"
    assert hangtag["care_test_id"] is None, "a hangtag pins no care run"
    assert hangtag["state"] == "DRAFT", "a created hangtag lands in DRAFT"
    assert hangtag["consistency_state"] == "CONSISTENT", (
        "both printed strings equal the parent's, so the verdict is CONSISTENT"
    )
    assert hangtag["content_hash"] == parent["content_hash"], (
        "the inherited care codes and identity mode reproduce the parent's fingerprint"
    )
    assert hangtag["content_hash"] == expected_content_hash(
        parent["fiber_content_text"], parent["origin_text"], parent["wash_temp_c"],
        parent["bleach_code"], parent["dry_code"], parent["iron_code"],
        parent["dryclean_code"], parent["identity_display_mode"],
        parent["languages"], rn_number=bundle["brand"]["rn_number"],
        legal_name=bundle["brand"]["legal_name"],
    ), "the hangtag fingerprint follows the canonical five-segment construction"

    parent_after = validate_success(api.get_label_spec(parent["id"], SPECIALIST), 200)
    assert parent_after["consistency_state"] == "NOT_APPLICABLE", (
        "consistency_state reads NOT_APPLICABLE on a permanent label"
    )
    assert parent_after["version"] == parent_version + 1, (
        f"the hangtag create bumps the parent from {parent_version} to "
        f"{parent_version + 1}, got {parent_after['version']}"
    )

    rows, meta = validate_paginated(api.list_label_specs(
        SPECIALIST, params={"parent_label_spec_id": parent["id"]}))
    assert meta["total_count"] == 1, "the parent filter finds exactly its one hangtag"
    assert [row["id"] for row in rows] == [hangtag["id"]], (
        "the parent filter returns the hangtag that hangs off it"
    )


def test_retest_is_allowed_only_from_a_failed_bench(api):
    """PRD 3.4: "Retesting requires the row to be in `FAILED`; anything else is rejected with `ERR_LAB_TEST_STATE_INVALID`."

    PRD 3.4: "On success the row returns to `BENCH_RESERVED`, `attempt_no` is
    incremented by 1, the occupancy interval is replaced, and `measured_fibers`,
    `dimensional_change_pct`, `colorfastness_grade`, `legibility_cycles`,
    `cycles_run`, `result_delta_pp_max` and `valid_until` are all cleared;
    `valid_until` is then recomputed from the new `specimen_received_at` when
    results next pass."

    Design: Corner/endpoints/retest_is_allowed_only_from_a_failed_bench
    """
    register_market("US")
    brand = register_brand(legal_name="Northline Apparel Co", rn_number="RN12345")
    style_kwargs = dict(product_class="WOVEN_OUTERWEAR", target_market_codes=["US"],
                        net_weight_grams=320.0,
                        declared_fibers=[fiber_line("COTTON", 100.0)])
    s1 = create_style(brand["id"], style_code="NL-R1", **style_kwargs)
    s2 = create_style(brand["id"], style_code="NL-R2", **style_kwargs)

    reservation = dict(lab_code="LAB-ATL-1", method="AATCC_135",
                       specimen_received_at="2026-08-03T09:00:00Z",
                       results_due_at="2026-08-05T09:00:00Z", wash_temp_c=30)
    t1 = reserve_care_test(s1["id"], **reservation)
    passed = post_results(t1["id"], care_results_payload(
        cycles_run=5, dimensional_change_pct=2.0, colorfastness_grade=4.0,
        legibility_cycles=40))
    assert passed["state"] == "PASSED", "the compliant care run must pass all three gates"

    t2 = reserve_care_test(s2["id"], **reservation)
    failed = post_results(t2["id"], care_results_payload(
        cycles_run=5, dimensional_change_pct=4.0, colorfastness_grade=4.0,
        legibility_cycles=40))
    assert failed["state"] == "FAILED", "4.0 percent shrinkage exceeds the 3.0 limit"

    retest_body = retest_payload(specimen_received_at="2026-08-10T09:00:00Z",
                                 results_due_at="2026-08-12T09:00:00Z",
                                 wash_temp_c=30)

    refused = api.retest_lab_test(t1["id"], dict(retest_body), LAB)
    validate_error(refused, ApiErrorId.ERR_LAB_TEST_STATE_INVALID, 409)

    t1_after = validate_success(api.get_lab_test(t1["id"], LAB), 200)
    assert t1_after["state"] == "PASSED", "the refused retest leaves the passed row alone"
    assert t1_after["attempt_no"] == 1, "the refused retest does not advance attempt_no"
    assert t1_after["valid_until"] == passed["valid_until"], (
        "the refused retest clears nothing, so the validity horizon still stands"
    )

    reopened = validate_success(api.retest_lab_test(t2["id"], dict(retest_body), LAB), 200)
    assert_lab_test(reopened)
    assert reopened["state"] == "BENCH_RESERVED", "a failed row returns to the bench"
    assert reopened["attempt_no"] == 2, (
        f"attempt_no is incremented by 1, got {reopened['attempt_no']}"
    )
    for field in ("dimensional_change_pct", "colorfastness_grade", "legibility_cycles",
                  "cycles_run", "result_delta_pp_max", "valid_until"):
        assert reopened[field] is None, f"{field} must be cleared by the retest"
    assert reopened["specimen_received_at"] == "2026-08-10T09:00:00Z", (
        "the fresh specimen window replaces the old one"
    )
    assert reopened["results_due_at"] == "2026-08-12T09:00:00Z", (
        "the fresh results_due_at replaces the old one"
    )
    assert_second_precision_instant(reopened["specimen_received_at"],
                                    "specimen_received_at")
    assert_second_precision_instant(reopened["results_due_at"], "results_due_at")


def test_withdrawing_a_published_label_cascades_to_its_hangtag_and_frees_the_market_window(api):
    """PRD 3.6: "Withdrawing from `PUBLISHED` also releases the style-and-market window occupancy for every listed market."

    PRD 3.6: "Either way, every hangtag whose `parent_label_spec_id` names this
    artifact and whose state is `DRAFT`, `PENDING_APPROVAL`, `APPROVED` or
    `PUBLISHED` is withdrawn with `withdrawn_reason` set to
    `AUTO_PARENT_WITHDRAWN`; the style's `label_readiness` is recomputed; and the
    `version` of this row, of the style, and of every cascaded child is
    incremented by 1."

    PRD 3.6: "Withdrawal from any other state — and any action at all on an
    artifact already in `WITHDRAWN` — is rejected with `ERR_LABEL_STATE_INVALID`."

    Design: Corner/endpoints/withdrawing_a_published_label_cascades_to_its_hangtag_and_frees_the_market_window
    """
    window = ("2026-09-01T00:00:00Z", "2026-12-01T00:00:00Z")
    bundle, l1 = setup_published_permanent_label(effective_from=window[0],
                                                 effective_to=window[1])
    assert l1["state"] == "PUBLISHED", "the incumbent label occupies the US window"

    h1 = create_hangtag(l1)
    assert h1["state"] == "DRAFT", "the child hangtag is still a draft"

    l2 = draft_permanent_label(bundle, placement_code="SIDE_SEAM_INSIDE")
    submit_label(l2["id"])
    l2 = approve_label(l2["id"])
    assert l2["state"] == "APPROVED", "the sibling label is approved but unpublished"

    overlap = api.publish_label_spec(l2["id"], window[0], window[1], APPROVER)
    validate_error(overlap, ApiErrorId.ERR_LABEL_WINDOW_OVERLAP, 409)

    l1_before = read_label(l1["id"])
    withdrawn = validate_success(api.withdraw_label_spec(
        l1["id"], "artwork recalled by the brand", APPROVER), 200)
    assert withdrawn["state"] == "WITHDRAWN", "withdrawal from PUBLISHED is legal"
    assert withdrawn["withdrawn_reason"] == "artwork recalled by the brand", (
        "the operator-supplied note is recorded on the withdrawn parent"
    )
    assert withdrawn["version"] == l1_before["version"] + 1, (
        f"the withdrawal bumps the parent from {l1_before['version']} to "
        f"{l1_before['version'] + 1}, got {withdrawn['version']}"
    )

    h1_after = read_label(h1["id"])
    assert h1_after["state"] == "WITHDRAWN", "the DRAFT hangtag is caught by the cascade"
    assert h1_after["withdrawn_reason"] == "AUTO_PARENT_WITHDRAWN", (
        "the child records the cascade literal, never the operator note"
    )
    assert h1_after["version"] == h1["version"] + 1, (
        "every cascaded child has its version incremented by 1"
    )

    again = api.withdraw_label_spec(l1["id"], "second attempt", APPROVER)
    validate_error(again, ApiErrorId.ERR_LABEL_STATE_INVALID, 409)

    republished = validate_success(api.publish_label_spec(
        l2["id"], window[0], window[1], APPROVER), 200)
    assert republished["state"] == "PUBLISHED", (
        "the identical window is free once the incumbent is withdrawn"
    )
    assert republished["effective_from"] == window[0], "the window instants are stored"
    assert republished["effective_to"] == window[1], "the window instants are stored"
    assert_second_precision_instant(republished["effective_from"], "effective_from")
    assert_second_precision_instant(republished["effective_to"], "effective_to")

    rows, meta = validate_paginated(api.list_label_specs(SPECIALIST, params={
        "style_id": bundle["style"]["id"], "state": "WITHDRAWN",
        "limit": 10, "offset": 0}))
    assert meta["total_count"] == 2, (
        f"the WITHDRAWN listing covers the parent and its cascaded hangtag, "
        f"got total_count {meta['total_count']}"
    )
    assert {row["id"] for row in rows} == {l1["id"], h1["id"]}, (
        "exactly the parent and the cascaded hangtag are withdrawn"
    )


def test_a_stale_style_version_blocks_the_declaration_replace_and_the_correct_one_succeeds(api):
    """PRD 2.5: "A writer whose `expected_style_version` is behind the style's current `version` has therefore based its replacement on a declaration, a test outcome or an origin state that has since moved, and the replacement is rejected with `ERR_STALE_STYLE_VERSION` (HTTP 412) rather than silently discarding the newer facts."

    PRD 2.5: "Replacing a whole fiber declaration is a legitimate supersede — a
    writer that submits the same replacement against an up-to-date style version
    always succeeds — so nothing else blocks it."

    Design: Corner/cross_cutting_layers/a_stale_style_version_blocks_the_declaration_replace_and_the_correct_one_succeeds
    """
    register_market("US")
    brand = register_brand(legal_name="Northline Apparel Co", rn_number="RN12345")
    brand_headers = make_brand_admin_headers(brand["id"])
    style = create_style(
        brand["id"], style_code="NL-OCC-1", product_class="WOVEN_OUTERWEAR",
        target_market_codes=["US"], net_weight_grams=320.0,
        declared_fibers=[fiber_line("COTTON", 100.0)])
    v1 = style["version"]
    assert v1 == 1, "a freshly created style stands at version 1"

    two_lines = [fiber_line("COTTON", 60.0), fiber_line("POLYESTER", 40.0)]
    first = validate_success(api.replace_fiber_declaration(
        style["id"], {"declared_fibers": two_lines, "expected_style_version": v1},
        brand_headers), 200)
    assert first["version"] == v1 + 1, (
        f"the accepted replace increments version to {v1 + 1}, got {first['version']}"
    )
    assert first["effective_fiber_content_text"] == "60.0% COTTON, 40.0% POLYESTER", (
        "the printable string is recomputed, listed lines descending by percentage"
    )

    replay = api.replace_fiber_declaration(
        style["id"], {"declared_fibers": two_lines, "expected_style_version": v1},
        brand_headers)
    validate_error(replay, ApiErrorId.ERR_STALE_STYLE_VERSION, 412)

    mid = validate_success(api.get_style(style["id"], ADMIN), 200)
    assert mid["version"] == first["version"], (
        "the refused replay wrote nothing, so the version did not move again"
    )
    assert mid["effective_fiber_content_text"] == first["effective_fiber_content_text"], (
        "the refused replay left the winner's printable string in place"
    )
    assert [line["fiber_generic_name"] for line in mid["declared_fibers"]] == [
        "COTTON", "POLYESTER"], "the refused replay left the winner's declaration"

    third = validate_success(api.replace_fiber_declaration(
        style["id"], {"declared_fibers": [fiber_line("LINEN", 100.0)],
                      "expected_style_version": mid["version"]}, brand_headers), 200)
    assert third["version"] == mid["version"] + 1, (
        "a replace against the up-to-date version succeeds and increments by 1"
    )
    assert third["effective_fiber_content_text"] == "100.0% LINEN", (
        "the replacement declaration renders as the new printable string"
    )


def test_a_stale_style_version_blocks_a_determination_create(api):
    """PRD 2.5: "A create carrying an `expected_style_version` behind the style's current `version` was computed against a supply graph that has since gained or lost a node, and it is rejected with `ERR_STALE_STYLE_VERSION` (HTTP 412) so that the frozen candidate-country pair can never disagree with the graph it claims to describe."

    PRD 2.4: "Most resources additionally carry an `updated_at` timestamp that is
    refreshed on every mutation and an integer `version` that starts at 1 on
    creation and increments by exactly 1 on every mutation of that row —
    including mutations the row suffers as a side effect of an operation aimed at
    some other resource."

    Design: Corner/cross_cutting_layers/a_stale_style_version_blocks_a_determination_create
    """
    register_market("US")
    brand = register_brand(legal_name="Northline Apparel Co", rn_number="RN12345")
    brand_headers = make_brand_admin_headers(brand["id"])
    style = create_style(
        brand["id"], style_code="NL-OCC-2", product_class="WOVEN_OUTERWEAR",
        target_market_codes=["US"], net_weight_grams=320.0,
        declared_fibers=[fiber_line("COTTON", 100.0)])
    root = add_material_input(style["id"], stage="FIBER", country_code="IN",
                              value_added_usd=2.00, weight_grams=500.0)
    version_before = style_version(style["id"])

    appended = validate_success(api.create_material_input(
        style["id"], material_input_payload(
            stage="CUT_AND_SEW", country_code="VN", value_added_usd=9.00,
            weight_grams=900.0, parent_input_id=root["id"]), brand_headers), 201)
    assert_material_input(appended)
    version_after = style_version(style["id"])
    assert version_after == version_before + 1, (
        f"appending a graph node moves the style from {version_before} to "
        f"{version_before + 1}, got {version_after}"
    )

    stale = api.create_origin_determination(
        {"style_id": style["id"], "expected_style_version": version_before}, SPECIALIST)
    validate_error(stale, ApiErrorId.ERR_STALE_STYLE_VERSION, 412)

    drafted = validate_success(api.create_origin_determination(
        {"style_id": style["id"], "expected_style_version": version_after},
        SPECIALIST), 201)
    assert_origin_determination(drafted)
    assert drafted["state"] == "DRAFT", "a new determination is created in DRAFT"
    assert drafted["graph_node_count"] == 2, (
        "both non-ornamentation nodes enter the frozen population"
    )
    assert drafted["st_country"] == "VN", (
        "substantial transformation ranks by value added, and only VN is in that pool"
    )
    assert drafted["yf_country"] == "IN", (
        "yarn-forward finds no YARN node and falls back to the FIBER node in IN"
    )
    assert drafted["divergent"] is True, "the two candidate countries disagree"

    rows, meta = validate_paginated(
        api.list_style_origin_determinations(style["id"], ADMIN))
    assert meta["total_count"] == 1, (
        f"the refused create left no row behind, got total_count {meta['total_count']}"
    )
    assert [row["id"] for row in rows] == [drafted["id"]], (
        "the only determination of the style is the accepted one"
    )


def test_a_stale_parent_label_version_blocks_a_hangtag_create(api):
    """PRD 2.5: "A create carrying an `expected_parent_label_spec_version` behind the parent's current `version` was authored against parent content that has since been edited, re-approved or withdrawn, and it is rejected with `ERR_STALE_LABEL_VERSION` (HTTP 412)."

    PRD 3.7: "The parent permanent label's own `version` is incremented by 1 by
    the creation, which is precisely why the next hangtag create must carry the
    parent's new version."

    Design: Corner/cross_cutting_layers/a_stale_parent_label_version_blocks_a_hangtag_create
    """
    bundle = setup_label_ready_style()
    parent = draft_permanent_label(bundle)
    lv1 = parent["version"]

    h1 = validate_success(api.create_hangtag(
        parent["id"], _hangtag_body(parent, lv1), SPECIALIST), 201)
    assert is_valid_uuid(h1["id"]), "the first hangtag is created with a minted id"
    assert h1["artifact_type"] == "HANGTAG", "the sub-resource yields a HANGTAG"

    stale = api.create_hangtag(parent["id"], _hangtag_body(parent, lv1), SPECIALIST)
    validate_error(stale, ApiErrorId.ERR_STALE_LABEL_VERSION, 412)

    lv2 = read_label(parent["id"])["version"]
    assert lv2 == lv1 + 1, (
        f"the accepted hangtag create bumped the parent to {lv1 + 1}, got {lv2}"
    )

    h2 = validate_success(api.create_hangtag(
        parent["id"], _hangtag_body(parent, lv2), SPECIALIST), 201)
    assert h2["id"] != h1["id"], "the replay body succeeds as a new row once retargeted"
    assert h2["consistency_state"] == "CONSISTENT", (
        "the printed strings still equal the parent's, so the verdict is CONSISTENT"
    )

    lv3 = read_label(parent["id"])["version"]
    assert lv3 == lv2 + 1, (
        f"the second accepted create bumped the parent to {lv2 + 1}, got {lv3}"
    )

    rows, meta = validate_paginated(api.list_label_specs(
        SPECIALIST, params={"parent_label_spec_id": parent["id"]}))
    assert meta["total_count"] == 2, (
        f"the refused create left no row behind, got total_count {meta['total_count']}"
    )
    assert {row["id"] for row in rows} == {h1["id"], h2["id"]}, (
        "exactly the two accepted hangtags hang off the parent"
    )
