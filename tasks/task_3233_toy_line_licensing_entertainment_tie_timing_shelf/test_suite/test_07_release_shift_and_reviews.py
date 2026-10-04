"""Release-shift cascades, review windows, confidentiality and temporal gates."""
from test_helpers import (
    ApiErrorId,
    BRAND,
    STUDIO,
    activate_agreement,
    canonical_instant,
    create_agreement,
    create_commitment,
    create_evergreen_line,
    create_licensed_line,
    create_property,
    create_retailer,
    create_shipment,
    create_sku,
    create_studio,
    fixtures,
    make_retailer_ops_headers,
    set_clock,
    setup_active_agreement,
    setup_evergreen_line_with_sku,
    setup_licensed_chain,
    setup_licensed_chain_with_shipment,
    setup_retail_open_review,
    setup_review_with_commitment,
    validate_error,
    validate_success,
)

REVIEW_WINDOW = dict(
    window_start="2026-09-15T00:00:00Z",
    window_end="2026-11-15T00:00:00Z",
    commitment_deadline="2026-11-01T00:00:00Z",
)


# ── Release shift cascade (difficulty: transitive_cascade) ───────────────────


def test_release_shift_cascades_to_lines_shipments_commitments(api):
    """PRD §3.1: "The shift then cascades. Every `LICENSED` toy line anchored to the
    property has its `target_street_date` rewritten to the new release date and its
    line `version` incremented. Every `PLANNED` shipment of such a line has its
    `street_date` rewritten to the new release date and its shipment `version`
    incremented. And every `COMMITTED` assortment commitment that references a SKU
    of such a line, and whose host line review's `window_start` is strictly before
    the new release date — meaning the assortment was committed before the demand
    signal the new date implies — transitions to `AT_RISK`."

    Design: Difficulty/transitive_cascade/release_shift_cascades_to_lines_shipments_commitments
    """
    studio, prop, agreement, line, sku, retailer, review, commitment, shipment = (
        setup_licensed_chain_with_shipment(
            commitment_overrides={"committed_units": 1000, "unit_price_cents": 100, "shelf_slots": 4},
            shipment_overrides={"planned_ship_date": "2027-02-01T00:00:00Z", "units": 1000},
            moq_units=100,
            unit_cost_cents=200,
            tooling_cost_cents=50000,
            age_grade_months=48,
        )
    )
    data = validate_success(
        api.shift_release(prop["id"], {"new_release_date": "2027-06-01T00:00:00Z"}, STUDIO)
    )
    assert data["shift_count"] == 1
    assert canonical_instant(data["release_date"]) == canonical_instant("2027-06-01T00:00:00Z")

    line_data = validate_success(api.get_toy_line(line["id"], BRAND))
    assert canonical_instant(line_data["target_street_date"]) == canonical_instant("2027-06-01T00:00:00Z")

    shipment_data = validate_success(api.get_shipment(shipment["id"], BRAND))
    assert canonical_instant(shipment_data["street_date"]) == canonical_instant("2027-06-01T00:00:00Z")

    # window_start 2026-09-15 is strictly before the new release 2027-06-01.
    commitment_data = validate_success(api.get_commitment(commitment["id"], BRAND))
    assert commitment_data["status"] == "AT_RISK"


def test_release_shift_leaves_commitment_untouched_when_window_not_before(api):
    """PRD §3.1: "And every `COMMITTED` assortment commitment that references a SKU
    of such a line, and whose host line review's `window_start` is strictly before
    the new release date — meaning the assortment was committed before the demand
    signal the new date implies — transitions to `AT_RISK`. Commitments already
    `AT_RISK` or `CANCELLED` are untouched by the cascade."

    Design: Difficulty/transitive_cascade/release_shift_cascades_to_lines_shipments_commitments
    """
    # Review window starts AFTER the new release date: not "committed before the
    # demand signal", so the commitment must stay COMMITTED.
    studio, prop, agreement, line, sku = setup_licensed_chain(age_grade_months=48, moq_units=100)
    retailer = create_retailer(name="LateWindow Retail")
    review = fixtures.create_confirmed_review(
        retailer,
        window_start="2027-07-01T00:00:00Z",
        window_end="2027-09-01T00:00:00Z",
        commitment_deadline="2027-08-01T00:00:00Z",
    )
    # Move the clock into the window so the review is OPEN for the commitment.
    set_clock("2027-07-15T00:00:00Z")
    commitment = create_commitment(
        review["id"], sku["id"], committed_units=100, unit_price_cents=100, shelf_slots=4
    )

    validate_success(api.shift_release(prop["id"], {"new_release_date": "2027-06-01T00:00:00Z"}, STUDIO))

    commitment_data = validate_success(api.get_commitment(commitment["id"], BRAND))
    assert commitment_data["status"] == "COMMITTED"
    line_data = validate_success(api.get_toy_line(line["id"], BRAND))
    assert canonical_instant(line_data["target_street_date"]) == canonical_instant("2027-06-01T00:00:00Z")


# ── Review windows (difficulty: resource_temporal_overlap) ───────────────────


def test_line_review_half_open_window_adjacency(api):
    """PRD §3.6: "Windows for the same retailer must not overlap, but they use
    half-open semantics: one review's `window_end` may coincide exactly with
    another's `window_start`. An overlapping window is rejected with
    `ERR_REVIEW_WINDOW_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/line_review_half_open_window_adjacency
    """
    set_clock("2026-08-01T00:00:00Z")
    retailer = create_retailer(name="ToyBox")
    headers = make_retailer_ops_headers(retailer["id"])

    resp = api.create_line_review(
        {
            "retailer_id": retailer["id"],
            "window_start": "2026-09-01T00:00:00Z",
            "window_end": "2026-10-01T00:00:00Z",
            "commitment_deadline": "2026-09-25T00:00:00Z",
            "shelf_slots_total": 20,
        },
        headers,
    )
    validate_success(resp, expected_status=201)

    # Adjacent: window_start == prior window_end -> allowed.
    resp = api.create_line_review(
        {
            "retailer_id": retailer["id"],
            "window_start": "2026-10-01T00:00:00Z",
            "window_end": "2026-11-01T00:00:00Z",
            "commitment_deadline": "2026-10-25T00:00:00Z",
            "shelf_slots_total": 20,
        },
        headers,
    )
    validate_success(resp, expected_status=201)

    # Overlapping: starts 2026-09-30 inside [09-01, 10-01) -> rejected.
    resp = api.create_line_review(
        {
            "retailer_id": retailer["id"],
            "window_start": "2026-09-30T00:00:00Z",
            "window_end": "2026-10-15T00:00:00Z",
            "commitment_deadline": "2026-10-10T00:00:00Z",
            "shelf_slots_total": 20,
        },
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_REVIEW_WINDOW_OVERLAP, expected_status=409)


def test_line_review_windows_for_different_retailers_may_overlap(api):
    """PRD §3.6: "Windows for the same retailer must not overlap, but they use
    half-open semantics: one review's `window_end` may coincide exactly with
    another's `window_start`."

    Design: Difficulty/resource_temporal_overlap/line_review_half_open_window_adjacency
    """
    set_clock("2026-08-01T00:00:00Z")
    retailer_a = create_retailer(name="ToyBox")
    retailer_b = create_retailer(name="MegaMart")
    window = {
        "window_start": "2026-09-01T00:00:00Z",
        "window_end": "2026-10-01T00:00:00Z",
        "commitment_deadline": "2026-09-25T00:00:00Z",
        "shelf_slots_total": 20,
    }
    resp = api.create_line_review(
        {"retailer_id": retailer_a["id"], **window}, make_retailer_ops_headers(retailer_a["id"])
    )
    validate_success(resp, expected_status=201)
    # Identical window for a different retailer is not an overlap violation.
    resp = api.create_line_review(
        {"retailer_id": retailer_b["id"], **window}, make_retailer_ops_headers(retailer_b["id"])
    )
    validate_success(resp, expected_status=201)


# ── Review lock gating (difficulty: cross_entity_state_dependency) ───────────


def test_commitment_cancel_gated_by_review_lock(api):
    """PRD §3.6: "A `BrandManager` may cancel a `COMMITTED` or `AT_RISK` commitment,
    but only while the host review's lifecycle is `OPEN`; a `LOCKED` review is
    frozen and the attempt yields `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/commitment_cancel_gated_by_review_lock
    """
    set_clock("2026-10-01T00:00:00Z")
    line, sku = setup_evergreen_line_with_sku()
    retailer, review, commitment = setup_review_with_commitment(
        sku, commitment_deadline="2026-10-15T00:00:00Z"
    )
    # Move past the commitment deadline: the review is now LOCKED.
    set_clock("2026-10-20T00:00:00Z")

    resp = api.cancel_commitment(commitment["id"], {}, BRAND)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    commitment_data = validate_success(api.get_commitment(commitment["id"], BRAND))
    assert commitment_data["status"] == "COMMITTED"
    review_data = validate_success(api.get_line_review(review["id"], BRAND))
    assert review_data["shelf_slots_used"] == 4


def test_commitment_cancel_allowed_while_review_open(api):
    """PRD §3.6: "Cancellation moves the commitment to `CANCELLED`, decrements the
    review's `shelf_slots_used` by the commitment's `shelf_slots`, and increments
    the commitment's `version`."

    Design: Difficulty/cross_entity_state_dependency/commitment_cancel_gated_by_review_lock
    """
    set_clock("2026-10-01T00:00:00Z")
    line, sku = setup_evergreen_line_with_sku()
    retailer, review, commitment = setup_review_with_commitment(
        sku, committed_units=100, unit_price_cents=500, shelf_slots=4
    )
    review_data = validate_success(api.get_line_review(review["id"], BRAND))
    assert review_data["lifecycle"] == "OPEN"
    assert review_data["shelf_slots_used"] == 4

    cancelled = validate_success(api.cancel_commitment(commitment["id"], {}, BRAND))
    assert cancelled["status"] == "CANCELLED"
    review_data = validate_success(api.get_line_review(review["id"], BRAND))
    assert review_data["shelf_slots_used"] == 0


# ── Line advance gates (difficulty: cross_entity_state_dependency) ───────────


def test_toy_line_advance_gated_by_agreement_and_property(api):
    """PRD §3.4: "`CONCEPT → IN_DEVELOPMENT`: a `LICENSED` line requires its license
    agreement to be `ACTIVE` and its property's `lifecycle` to be anything other
    than `CONFIDENTIAL`; an `EVERGREEN` line faces no additional gate."
    PRD §3.4: "any advance attempt whose preconditions fail is rejected with
    `ERR_INVALID_STATE` (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/toy_line_advance_gated_by_agreement_and_property
    """
    set_clock("2026-10-01T00:00:00Z")
    studio = create_studio(name="Stealth Studio", confidentiality_tier="STANDARD")
    prop = create_property(
        studio["id"],
        title="Secret Sequel",
        reveal_date="2026-10-05T00:00:00Z",
        release_date="2027-06-01T00:00:00Z",
    )
    agreement = create_agreement(prop["id"])  # stays NEGOTIATION
    # Move past the reveal so licensed line creation is permitted.
    set_clock("2026-10-06T00:00:00Z")
    line = create_licensed_line(prop["id"], agreement["id"], name="Secret Line")

    resp = api.advance_toy_line(
        line["id"], {"expected_toy_line_version": line["version"]}, BRAND
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    line_data = validate_success(api.get_toy_line(line["id"], BRAND))
    assert line_data["status"] == "CONCEPT"


def test_toy_line_advance_succeeds_once_agreement_active(api):
    """PRD §3.4: "`CONCEPT → IN_DEVELOPMENT`: a `LICENSED` line requires its license
    agreement to be `ACTIVE` and its property's `lifecycle` to be anything other
    than `CONFIDENTIAL`".

    Design: Difficulty/cross_entity_state_dependency/toy_line_advance_gated_by_agreement_and_property
    """
    set_clock("2026-10-01T00:00:00Z")
    studio, prop, agreement = setup_active_agreement()
    line = create_licensed_line(prop["id"], agreement["id"], name="Racers")

    advanced = validate_success(
        api.advance_toy_line(line["id"], {"expected_toy_line_version": line["version"]}, BRAND)
    )
    assert advanced["status"] == "IN_DEVELOPMENT"


# ── Confidentiality gate ─────────────────────────────────────────────────────


def test_confidentiality_gate_blocks_licensed_line_before_reveal(api):
    """PRD §3.1: "Creating a `LICENSED` toy line, creating a SKU under a licensed
    line, or creating a tooling order for a licensed line is rejected with
    `ERR_CONFIDENTIALITY_BREACH` (HTTP 422) while the property's `lifecycle` is
    `CONFIDENTIAL`."

    Design: Corner/validations/confidentiality_gate_blocks_licensed_line_before_reveal
    """
    set_clock("2026-10-01T00:00:00Z")
    studio, prop, agreement = setup_active_agreement(
        reveal_date="2027-01-01T00:00:00Z", release_date="2027-06-01T00:00:00Z"
    )
    resp = api.create_toy_line(
        {
            "name": "Secret Line",
            "brand_kind": "LICENSED",
            "property_id": prop["id"],
            "license_agreement_id": agreement["id"],
        },
        BRAND,
    )
    validate_error(resp, ApiErrorId.ERR_CONFIDENTIALITY_BREACH, expected_status=422)


# ── Locked-review commitment create vs shelf overflow (priority pair) ────────


def test_state_beats_fiscal_on_locked_review_commitment(api):
    """PRD §2.9: "When several validation rules could reject the same request, they
    are evaluated in a fixed priority order, and the highest-priority failing rule
    determines the error returned: first authentication (`ERR_UNAUTHENTICATED`),
    then authorization and ownership (`ERR_UNAUTHORIZED`), then path existence
    (`ERR_NOT_FOUND`), then lifecycle-state gates (`ERR_INVALID_STATE`), then
    safety and packaging compliance (`ERR_SAFETY_GATE`), then confidentiality gates
    (`ERR_CONFIDENTIALITY_BREACH`), then structural and referential integrity
    (`ERR_CONSTRAINT_VIOLATION`), then review-window overlap
    (`ERR_REVIEW_WINDOW_OVERLAP`), then factory month capacity
    (`ERR_FACTORY_CAPACITY_EXCEEDED`), then shelf-capacity and shipment-oversell
    checks (`ERR_SHELF_OVERFLOW` / `ERR_SHIPMENT_OVERSOLD`)".
    PRD §3.6: "Committing into a review whose lifecycle is not `OPEN` is rejected
    with `ERR_CONSTRAINT_VIOLATION`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_locked_review_commitment
    """
    set_clock("2026-10-01T00:00:00Z")
    line, sku = setup_evergreen_line_with_sku()
    retailer, review = setup_retail_open_review(
        shelf_slots_total=2, commitment_deadline="2026-10-15T00:00:00Z"
    )
    set_clock("2026-10-20T00:00:00Z")  # review LOCKED

    resp = api.create_commitment(
        {
            "line_review_id": review["id"],
            "sku_id": sku["id"],
            "committed_units": 100,
            "unit_price_cents": 500,
            "shelf_slots": 5,
        },
        BRAND,
    )
    # The non-OPEN-review rejection outranks the shelf-overflow check; the
    # reported error is not ERR_SHELF_OVERFLOW.
    assert resp.status_code in (409, 422)
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] in ("ERR_CONSTRAINT_VIOLATION", "ERR_INVALID_STATE")


def test_locked_review_commitment_rejected_before_shelf_capacity_check(api):
    """PRD §3.6: "Shelf capacity is enforced at creation: the review's
    `shelf_slots_used` plus the new commitment's `shelf_slots` must not exceed
    `shelf_slots_total`, or the create is rejected with `ERR_SHELF_OVERFLOW`
    (HTTP 422)."
    PRD §3.6: "Committing into a review whose lifecycle is not `OPEN` is rejected
    with `ERR_CONSTRAINT_VIOLATION`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_locked_review_commitment
    """
    set_clock("2026-10-01T00:00:00Z")
    line, sku = setup_evergreen_line_with_sku()
    retailer, review = setup_retail_open_review(
        shelf_slots_total=2, commitment_deadline="2026-10-15T00:00:00Z"
    )
    set_clock("2026-10-20T00:00:00Z")

    resp = api.create_commitment(
        {
            "line_review_id": review["id"],
            "sku_id": sku["id"],
            "committed_units": 100,
            "unit_price_cents": 500,
            "shelf_slots": 5,
        },
        BRAND,
    )
    assert resp.status_code in (409, 422)
    body = resp.json()
    assert body["data"]["error_id"] != "ERR_SHELF_OVERFLOW"


# ── Safety vs state priority pair ────────────────────────────────────────────


def test_safety_beats_temporal_on_record_result(api):
    """PRD §2.9: "then lifecycle-state gates (`ERR_INVALID_STATE`), then safety and
    packaging compliance (`ERR_SAFETY_GATE`)".
    PRD §3.4: "The test must be `SUBMITTED` — recording twice yields
    `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_record_result
    """
    set_clock("2026-10-01T00:00:00Z")
    line, sku = setup_evergreen_line_with_sku()
    sku = fixtures.create_sku(line["id"], age_grade_months=48, moq_units=1)
    test = fixtures.submit_safety_test(sku)
    fixtures.pass_safety_test(test, sku)  # test now PASSED (terminal)

    resp = api.record_safety_result(
        test["id"],
        {"outcome": "PASS", "result_age_grade_months": 20, "validated_claims": ["BPA_FREE"]},
        fixtures.SAFETY,
    )
    # Terminal-state violation (priority 4) outranks the out-of-range safety value.
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_record_result_on_failed_test_also_yields_invalid_state(api):
    """PRD §3.4: "The test must be `SUBMITTED` — recording twice yields
    `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_record_result
    """
    set_clock("2026-10-01T00:00:00Z")
    line = create_evergreen_line()
    sku = create_sku(line["id"], age_grade_months=36)
    test = fixtures.submit_safety_test(sku)
    # Fail the test via an explicit FAIL outcome (recorded, unlike a gated
    # conformance failure).
    validate_success(
        api.record_safety_result(
            test["id"],
            {"outcome": "FAIL", "result_age_grade_months": 36, "validated_claims": ["BPA_FREE"]},
            fixtures.SAFETY,
        )
    )
    resp = api.record_safety_result(
        test["id"],
        {"outcome": "PASS", "result_age_grade_months": 36, "validated_claims": ["BPA_FREE"]},
        fixtures.SAFETY,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
