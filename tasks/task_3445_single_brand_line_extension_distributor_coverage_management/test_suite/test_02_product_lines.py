"""Product-line lifecycle: brand-review loop, per-brand uniqueness, terminal
DISCONTINUED lockdown, write-read consistency and listing filters."""
from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS, api_client,
    assert_product_line, validate_error, validate_paginated, validate_success,
)
from test_helpers import fixtures as fx

BM = TEST_USERS["brand_manager_headers"]


def test_product_line_brand_review_revision_loop():
    """PRD §3.2: "A `REJECT` decision while `brand_review_attempts` is below 2 keeps the line in `FORMULATION` for rework and increments `brand_review_attempts` by one."
    PRD §3.2: "An `APPROVE` decision moves the line `FORMULATION` → `PILOT`, but only after three gates pass in order. First, at least one formulation of the line must be `SEALED` or `COMPARTMENTALIZED`, failing `ERR_FORMULATION_NOT_SEALED` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/product_line_brand_review_revision_loop
    """
    sc = fx.setup_line_with_sealed_formulation(
        line_overrides={"line_code": "EXT-R", "name": "Revision Loop Line",
                        "is_core": False})
    line_id = sc["line"]["id"]

    r1 = validate_success(api_client.brand_review(line_id, "REJECT", BM))
    assert r1["status"] == "FORMULATION"
    assert r1["brand_review_attempts"] == 1

    r2 = validate_success(api_client.brand_review(line_id, "REJECT", BM))
    assert r2["status"] == "FORMULATION"
    assert r2["brand_review_attempts"] == 2

    r3 = validate_success(api_client.brand_review(line_id, "APPROVE", BM))
    assert r3["status"] == "PILOT"
    assert r3["brand_review_attempts"] == 2, \
        "APPROVE does not reset the review counter after two rejections"


def test_second_core_line_and_duplicate_line_code_rejected():
    """PRD §3.2: "The `line_code` must be unique within the brand among lines that are not `DISCONTINUED` — a clash is rejected with `ERR_DUPLICATE_LINE_CODE` (HTTP 409) — and at most one non-`DISCONTINUED` line per brand may be marked `is_core`; a second core line is rejected with `ERR_CORE_LINE_EXISTS` (HTTP 409)."

    Design: Corner/entities/second_core_line_and_duplicate_line_code_rejected
    """
    brand_a = fx.create_brand()
    fx.create_product_line(brand_a["id"], line_code="CORE", name="Core Multi-Use",
                           is_core=True)
    brand_b = fx.create_brand(name="Second Brand",
                              legal_entity_name="Second Products Co")

    second_core = api_client.create_product_line(
        brand_a["id"],
        {"line_code": "CORE-2", "name": "Another Core", "is_core": True,
         "target_channels": ["MASS"]}, BM)
    validate_error(second_core, ApiErrorId.ERR_CORE_LINE_EXISTS)

    dup_code = api_client.create_product_line(
        brand_a["id"],
        {"line_code": "CORE", "name": "Duplicate Code", "is_core": False,
         "target_channels": ["MASS"]}, BM)
    validate_error(dup_code, ApiErrorId.ERR_DUPLICATE_LINE_CODE)

    other_brand = api_client.create_product_line(
        brand_b["id"],
        {"line_code": "CORE", "name": "Same Code Other Brand", "is_core": True,
         "target_channels": ["MASS"]}, BM)
    data = validate_success(other_brand, 201)
    assert_product_line(data)


def test_discontinued_line_rejects_all_further_transitions():
    """PRD §3.2: "`DISCONTINUED` is terminal."
    PRD §2.6: "The target resource's own state machine must admit the requested transition (`ERR_INVALID_STATE_TRANSITION`, 409; with the dedicated wrong-from-state errors `ERR_RENEWAL_WINDOW_NOT_OPEN`, `ERR_REGISTRATION_EXPIRED`, `ERR_DISTRIBUTOR_NOT_APPROVED` and `ERR_PROMO_WINDOW_CLOSED` where §3 assigns them)."

    Design: Corner/state_machines/discontinued_line_rejects_all_further_transitions
    """
    sc = fx.setup_line_with_sealed_formulation(
        line_overrides={"line_code": "EXT-1", "name": "Doomed Extension",
                        "is_core": False})
    fx.approve_line_to_pilot(sc["line"]["id"])
    gone = api_client.discontinue_product_line(sc["line"]["id"], BM)
    assert validate_success(gone)["status"] == "DISCONTINUED"

    review = api_client.brand_review(sc["line"]["id"], "APPROVE", BM)
    validate_error(review, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    launch = api_client.launch_product_line(sc["line"]["id"], BM)
    validate_error(launch, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    again = api_client.discontinue_product_line(sc["line"]["id"], BM)
    validate_error(again, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    after = validate_success(api_client.get_product_line(sc["line"]["id"], BM))
    assert after["status"] == "DISCONTINUED"


def test_third_brand_review_rejection_auto_discontinues():
    """PRD §3.2: "The third rejection is fatal: when the count already stands at 2, the rejection moves the line to `DISCONTINUED`, sets `brand_review_attempts` to 3, and recomputes the brand's `dilution_consumed_bps` and `core_identity_share_bps`."
    PRD §3.1: "a line discontinued while still in `FORMULATION` never froze a cost and contributes nothing."

    Design: Corner/state_machines/third_brand_review_rejection_auto_discontinues
    """
    sc = fx.setup_line_with_sealed_formulation(
        line_overrides={"line_code": "EXT-R", "name": "Thrice Rejected",
                        "is_core": False,
                        "target_channels": ["HARDWARE", "MASS"]})
    line_id = sc["line"]["id"]
    api_client.brand_review(line_id, "REJECT", BM)
    api_client.brand_review(line_id, "REJECT", BM)
    third = validate_success(api_client.brand_review(line_id, "REJECT", BM))
    assert third["status"] == "DISCONTINUED"
    assert third["brand_review_attempts"] == 3

    brand = validate_success(api_client.get_brand(sc["brand"]["id"], BM))
    assert brand["dilution_consumed_bps"] == 0, \
        "a line discontinued from FORMULATION never froze a cost"


def test_core_line_cannot_be_discontinued():
    """PRD §3.2: "A line in `PILOT` or `LAUNCHED` may be discontinued by a `BrandManager`, unless it is the core line — the core line can never be discontinued and the attempt is rejected with `ERR_CORE_LINE_IMMUTABLE` (HTTP 409)."

    Design: Corner/errors/core_line_cannot_be_discontinued
    """
    sc = fx.setup_launched_line(
        line_overrides={"line_code": "CORE", "name": "Core Multi-Use",
                        "is_core": True})
    resp = api_client.discontinue_product_line(sc["line"]["id"], BM)
    validate_error(resp, ApiErrorId.ERR_CORE_LINE_IMMUTABLE)
    line = validate_success(api_client.get_product_line(sc["line"]["id"], BM))
    assert line["status"] == "LAUNCHED"


def test_mutation_visible_in_same_response():
    """PRD §4: "Creation and modification responses return the created or updated resource in the envelope's `data` field."
    PRD §2.5: "`version` (integer): starts at its initial value at creation and increments by exactly one on every mutation, including system-driven cascades and sweeps."
    PRD §3.2: "On approval the line's `dilution_cost_bps` is **frozen** at its current value and the brand's consumption and identity share are recomputed with the line now counting at full frozen cost."
    PRD §3.2: "Any other line costs 400 basis points, plus 150 basis points for every target channel beyond the first, plus a 200-basis-point **novelty** surcharge when at least one of the line's pack formats (in any status except `RETIRED`) uses a `delivery_system` that no pack format (again excluding `RETIRED`) of any *other* `LAUNCHED` line of the same brand uses — capped in total at 1000 basis points."

    Design: Corner/consistency_model/mutation_visible_in_same_response
    """
    sc = fx.setup_line_with_sealed_formulation(
        line_overrides={"line_code": "EXT-1", "name": "Simple Extension",
                        "is_core": False})
    line_id = sc["line"]["id"]
    created = validate_success(api_client.get_product_line(line_id, BM))
    assert created["status"] == "FORMULATION"

    approved = validate_success(api_client.brand_review(line_id, "APPROVE", BM))
    assert approved["status"] == "PILOT", "the APPROVE response itself shows PILOT"
    assert approved["dilution_cost_bps"] == 400, \
        "1-channel line with no pack formats freezes at the 400 base cost"
    assert approved["version"] == created["version"] + 1, \
        "version increments by exactly one on the mutation"

    reread = validate_success(api_client.get_product_line(line_id, BM))
    assert reread["status"] == approved["status"]
    assert reread["dilution_cost_bps"] == approved["dilution_cost_bps"]
    assert reread["version"] == approved["version"], \
        "no drift between the write response and a subsequent read"


def test_product_lines_filter_by_brand_and_status_with_stable_sort():
    """PRD §3.2: "Lines can be listed with optional `brand_id` and `status` filters, and retrieved individually."
    PRD §2.3: "Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order."
    PRD §2.3: "List responses carry the pagination fields `limit`, `offset`, `total_count` and `has_more` in the `meta` object of the response envelope."
    PRD §2.10: "the server validates path identifiers strictly left to right and rejects with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve" — the brand_id query filter is not a path identifier, so an unknown filter value yields an empty page, not a 404.

    Design: Corner/endpoints/product_lines_filter_by_brand_and_status_with_stable_sort
    """
    brand_a = fx.create_brand()
    la = fx.create_product_line(brand_a["id"], line_code="EXT-A", name="A First",
                                is_core=False)
    lb = fx.create_product_line(brand_a["id"], line_code="EXT-B", name="A Second",
                                is_core=False, target_channels=["MASS"])
    brand_b = fx.create_brand(name="Second Brand",
                              legal_entity_name="Second Products Co")
    lc = fx.create_product_line(brand_b["id"], line_code="EXT-C", name="B Only",
                                is_core=False, target_channels=["INDUSTRIAL"])

    rows, meta = validate_paginated(api_client.list_product_lines(
        BM, params={"brand_id": brand_a["id"], "status": "FORMULATION"}))
    assert meta["total_count"] == 2 and len(rows) == 2
    assert {r["id"] for r in rows} == {la["id"], lb["id"]}
    created = [r["created_at"] for r in rows]
    assert created == sorted(created), "rows are created_at ascending"

    rows_b, meta_b = validate_paginated(api_client.list_product_lines(
        BM, params={"brand_id": brand_b["id"]}))
    assert meta_b["total_count"] == 1 and [r["id"] for r in rows_b] == [lc["id"]]

    rows_none, meta_none = validate_paginated(api_client.list_product_lines(
        BM, params={"brand_id": NON_EXISTENT_UUID}))
    assert rows_none == [] and meta_none["total_count"] == 0
    assert meta_none["has_more"] is False

    rows_pilot, meta_pilot = validate_paginated(api_client.list_product_lines(
        BM, params={"status": "PILOT"}))
    assert rows_pilot == [] and meta_pilot["total_count"] == 0
