"""Supply disruptions: partition invariant, allocations, substitutions, OCC."""
from test_helpers import (
    AUTO_RESOLVED_RATIONALE,
    TEST_USERS,
    ApiErrorId,
    assert_disruption_partition_invariant,
    assert_supply_disruption,
    create_disruption,
    create_facility,
    create_product,
    create_registered_product,
    decide_substitution,
    find_substitution_request,
    get_disruption,
    make_clinician_headers,
    make_facility_director_headers,
    post_allocation,
    request_substitution,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def _disruption_pair(disrupted_qty=100):
    """Facility + EXAM_GLOVES disrupted product + REGISTERED same-category
    substitute + disruption. Returns (facility, disrupted, substitute, disruption)."""
    facility = create_facility()
    disrupted = create_product(category="EXAM_GLOVES", each_price_cents=20)
    substitute = create_registered_product(
        brand_type="PRIVATE_LABEL", category="EXAM_GLOVES", each_price_cents=22
    )
    disruption = create_disruption(
        disrupted["id"], disrupted_quantity=disrupted_qty
    )
    return facility, disrupted, substitute, disruption


def test_disruption_create_initializes_partition(api):
    """PRD §3.8: "The disruption starts `DECLARED` with `allocated_total` 0,
    `approved_sub_total` 0, `covered_quantity` 0, and `remaining_pool` equal to
    the full `disrupted_quantity`; its embedded `allocations` and
    `substitution_requests` arrays start empty."

    Design: Corner/entities/disruption_create_initializes_partition
    """
    product = create_product(sku="DP-9", category="EXAM_GLOVES", each_price_cents=20)
    disruption = create_disruption(
        product["id"],
        disrupted_quantity=75,
        reason="DEMAND_SURGE",
        severity="MEDIUM",
        expected_resolution_date="2026-12-15",
    )
    assert_supply_disruption(disruption)
    assert disruption["status"] == "DECLARED"
    assert disruption["allocated_total"] == 0
    assert disruption["approved_sub_total"] == 0
    assert disruption["remaining_pool"] == 75
    assert disruption["covered_quantity"] == 0
    assert disruption["allocations"] == []
    assert disruption["substitution_requests"] == []
    assert disruption["version"] == 1


def test_allocation_after_resolve_409(api):
    """PRD §3.8: "if coverage is now complete, meaning `covered_quantity` is
    greater than or equal to `disrupted_quantity` with equality resolving, the
    disruption moves from `MITIGATING` to `RESOLVED`" and "nothing may be posted
    against a `RESOLVED` disruption, otherwise `ERR_DISRUPTION_RESOLVED`
    (HTTP 409)".

    Design: Corner/state_machines/disruption_allocation_after_resolve_rejected
    """
    facility = create_facility()
    product = create_product(sku="AI-1", category="EXAM_GLOVES", each_price_cents=20)
    disruption = create_disruption(
        product["id"], disrupted_quantity=10, reason="RECALL", severity="LOW",
        expected_resolution_date="2026-11-01",
    )
    resolved = post_allocation(
        disruption["id"], facility["id"], 10, disruption["version"]
    )
    assert resolved["status"] == "RESOLVED"  # first mitigation + full coverage
    resp = api.post_allocation(
        disruption["id"],
        {
            "facility_id": facility["id"],
            "quantity": 1,
            "expected_disruption_version": resolved["version"],
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DISRUPTION_RESOLVED.value, 409)


def test_duplicate_pending_substitution_409(api):
    """PRD §3.8: "One pending request per facility per disruption is the limit:
    a second `PENDING` request for the same disruption and facility is rejected
    with `ERR_DUPLICATE_SUBSTITUTION` (HTTP 409)."

    Design: Corner/validations/duplicate_pending_substitution_rejected
    """
    facility, _, substitute, disruption = _disruption_pair()
    request_substitution(disruption["id"], facility["id"], substitute["id"], 40)
    resp = api.post_substitution_request(
        disruption["id"],
        {
            "action": "REQUEST",
            "facility_id": facility["id"],
            "proposed_product_id": substitute["id"],
            "covered_quantity": 30,
        },
        headers=make_facility_director_headers(facility["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SUBSTITUTION.value, 409)


def test_substitution_wrong_category_422(api):
    """PRD §3.8: "The proposed product must exist (`ERR_NOT_FOUND`), be
    `REGISTERED`, be `ACTIVE`, share the disrupted product's `category`, and
    differ from the disrupted product itself; any failure is rejected with
    `ERR_PRODUCT_NOT_SUBSTITUTABLE` (HTTP 422)."

    Design: Corner/validations/substitution_wrong_category_rejected
    """
    facility = create_facility()
    disrupted = create_product(sku="SW-D", category="EXAM_GLOVES", each_price_cents=20)
    wrong_category = create_registered_product(
        sku="SW-W", category="RESPIRATORY", each_price_cents=30
    )
    disruption = create_disruption(
        disrupted["id"], reason="FDA_HOLD", severity="HIGH"
    )
    resp = api.post_substitution_request(
        disruption["id"],
        {
            "action": "REQUEST",
            "facility_id": facility["id"],
            "proposed_product_id": wrong_category["id"],
            "covered_quantity": 40,
        },
        headers=make_facility_director_headers(facility["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_SUBSTITUTABLE.value, 422)


def test_decide_unknown_request_404(api):
    """PRD §2.9: "an evaluation's `line_id`, and a substitution decision's
    `request_id` must each resolve to an existing resource before deeper checks
    proceed" — an unknown `request_id` is `ERR_NOT_FOUND` (HTTP 404).

    Design: Corner/errors/substitution_decide_unknown_request_not_found
    """
    facility = create_facility()
    product = create_product(sku="NF-1", category="EXAM_GLOVES", each_price_cents=20)
    disruption = create_disruption(
        product["id"], reason="RECALL", severity="LOW"
    )
    resp = api.post_substitution_request(
        disruption["id"],
        {"action": "DECIDE", "request_id": "req-nonexistent", "decision": "APPROVE"},
        headers=make_clinician_headers("clin-1"),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_allocation_exceeds_pool_422(api):
    """PRD §3.8: "The allocation's `quantity` must be greater than 0 and no more
    than the disruption's current `remaining_pool`, otherwise
    `ERR_INSUFFICIENT_ALLOCATION_POOL` (HTTP 422)". 70 against 60 remaining
    fails.

    Design: Corner/validations/allocation_exceeds_pool_rejected
    """
    facility = create_facility()
    product = create_product(sku="AP-1", category="EXAM_GLOVES", each_price_cents=20)
    disruption = create_disruption(product["id"], disrupted_quantity=100)
    after_first = post_allocation(
        disruption["id"], facility["id"], 40, disruption["version"]
    )
    assert after_first["remaining_pool"] == 60
    resp = api.post_allocation(
        disruption["id"],
        {
            "facility_id": facility["id"],
            "quantity": 70,
            "expected_disruption_version": after_first["version"],
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_ALLOCATION_POOL.value, 422)
    reread = get_disruption(disruption["id"])
    assert reread["remaining_pool"] == 60
    assert reread["version"] == after_first["version"]


def test_occ_disruption_allocation_stale_412(api):
    """PRD §2.7: "Posting a disruption allocation requires the request body to
    carry `expected_disruption_version`, holding the client's last observed
    `version` of the target `SupplyDisruption`. If the disruption's current
    `version` has advanced — because another allocation was posted, or a
    substitution decision consumed pool quantity, since the client last read
    the disruption — the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412)".

    Design: Corner/complexity_layers/occ_disruption_allocation_stale_version_rejected
    """
    facility = create_facility()
    product = create_product(sku="OC-D", category="EXAM_GLOVES", each_price_cents=20)
    disruption = create_disruption(
        product["id"], disrupted_quantity=100, reason="DEMAND_SURGE",
        severity="LOW",
    )
    after_first = post_allocation(
        disruption["id"], facility["id"], 10, disruption["version"]
    )
    assert after_first["version"] == 2
    resp = api.post_allocation(
        disruption["id"],
        {
            "facility_id": facility["id"],
            "quantity": 5,
            "expected_disruption_version": disruption["version"],  # stale: now 2
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)
    reread = get_disruption(disruption["id"])
    assert reread["remaining_pool"] == 90
    assert reread["allocated_total"] == 10


def test_substitution_approve_resolves_disruption(api):
    """PRD §3.8: "An `APPROVE` decision sets the request's status to `APPROVED`,
    stamps `decided_by` with the acting clinician's `X-User-ID`, adds the
    request's `covered_quantity` to `approved_sub_total`, and subtracts it from
    `remaining_pool`" — 40 allocated + 60 approved >= 100, so "the disruption
    auto-resolves".

    Design: Difficulty/transitive_cascade/substitution_approval_resolves_and_rejects_pending
    """
    facility1 = create_facility(name="Fac S1")
    facility2 = create_facility(name="Fac S2")
    disrupted = create_product(sku="DP-1", category="EXAM_GLOVES", each_price_cents=20)
    substitute = create_registered_product(
        sku="SP-1", brand_type="PRIVATE_LABEL", category="EXAM_GLOVES",
        each_price_cents=22,
    )
    disruption = create_disruption(disrupted["id"], disrupted_quantity=100)
    after_alloc = post_allocation(
        disruption["id"], facility1["id"], 40, disruption["version"]
    )
    assert after_alloc["status"] == "MITIGATING"
    r1_resp = request_substitution(
        disruption["id"], facility1["id"], substitute["id"], 60
    )
    req1 = find_substitution_request(r1_resp, facility_id=facility1["id"])
    request_substitution(disruption["id"], facility2["id"], substitute["id"], 50)
    decided = decide_substitution(
        disruption["id"], req1["request_id"], "APPROVE",
        clinician_id="clin-1", rationale="clinically equivalent",
    )
    assert decided["status"] == "RESOLVED"
    assert decided["allocated_total"] == 40
    assert decided["approved_sub_total"] == 60
    assert decided["remaining_pool"] == 0
    assert decided["covered_quantity"] == 100
    req1_after = find_substitution_request(decided, request_id=req1["request_id"])
    assert req1_after["status"] == "APPROVED"
    assert req1_after["decided_by"] == "clin-1"


def test_resolve_auto_rejects_pending_requests(api):
    """PRD §3.8: "Entering `RESOLVED` fires a cleanup cascade: every
    substitution request still `PENDING` is set to `REJECTED` with its
    `rationale` overwritten to `AUTO_RESOLVED`."

    Design: Difficulty/transitive_cascade/substitution_approval_resolves_and_rejects_pending
    """
    facility1 = create_facility(name="Fac T1")
    facility2 = create_facility(name="Fac T2")
    disrupted = create_product(sku="DP-2", category="EXAM_GLOVES", each_price_cents=20)
    substitute = create_registered_product(
        sku="SP-2", brand_type="PRIVATE_LABEL", category="EXAM_GLOVES",
        each_price_cents=22,
    )
    disruption = create_disruption(disrupted["id"], disrupted_quantity=100)
    post_allocation(disruption["id"], facility1["id"], 40, disruption["version"])
    request_substitution(disruption["id"], facility1["id"], substitute["id"], 60)
    r2_resp = request_substitution(
        disruption["id"], facility2["id"], substitute["id"], 50
    )
    req1 = find_substitution_request(
        get_disruption(disruption["id"]), facility_id=facility1["id"]
    )
    req2 = find_substitution_request(r2_resp, facility_id=facility2["id"])
    decided = decide_substitution(
        disruption["id"], req1["request_id"], "APPROVE",
        clinician_id="clin-1", rationale="clinically equivalent",
    )
    assert decided["status"] == "RESOLVED"
    req2_after = find_substitution_request(decided, request_id=req2["request_id"])
    assert req2_after["status"] == "REJECTED"
    assert req2_after["rationale"] == AUTO_RESOLVED_RATIONALE


def test_partition_invariant_allocations_and_reject(api):
    """PRD §3.8: "Three quantities always reconcile: `allocated_total` is the
    sum of allocation quantities, `approved_sub_total` is the sum of
    `covered_quantity` over approved substitution requests, `covered_quantity`
    is their sum, and `remaining_pool` is what is left of the disrupted
    quantity after both." A REJECTED request consumes nothing.

    Design: Difficulty/compensating_invariant/disruption_partition_invariant_across_decisions
    """
    facility, _, substitute, disruption = _disruption_pair()
    after_alloc = post_allocation(
        disruption["id"], facility["id"], 40, disruption["version"]
    )
    assert after_alloc["allocated_total"] == 40
    assert after_alloc["remaining_pool"] == 60
    assert after_alloc["approved_sub_total"] == 0
    assert_disruption_partition_invariant(after_alloc)
    req_resp = request_substitution(
        disruption["id"], facility["id"], substitute["id"], 60
    )
    req1 = find_substitution_request(req_resp, facility_id=facility["id"])
    decided = decide_substitution(
        disruption["id"], req1["request_id"], "REJECT",
        clinician_id="clin-2", rationale="not latex-free equivalent",
    )
    # REJECT conserves the partition: nothing was consumed.
    assert decided["approved_sub_total"] == 0
    assert decided["remaining_pool"] == 60
    assert decided["status"] == "MITIGATING"
    assert_disruption_partition_invariant(decided)


def test_partition_invariant_through_resolve(api):
    """PRD §3.8: "Three quantities always reconcile: `allocated_total` is the
    sum of allocation quantities, `approved_sub_total` is the sum of
    `covered_quantity` over approved substitution requests, `covered_quantity`
    is their sum, and `remaining_pool` is what is left of the disrupted
    quantity after both." The invariant holds at every step including the
    terminal auto-resolve (65 + 35 + 0 == 100).

    Design: Difficulty/compensating_invariant/disruption_partition_invariant_across_decisions
    """
    facility, _, substitute, disruption = _disruption_pair()
    post_allocation(disruption["id"], facility["id"], 40, disruption["version"])
    req1_resp = request_substitution(
        disruption["id"], facility["id"], substitute["id"], 60
    )
    req1 = find_substitution_request(req1_resp, facility_id=facility["id"])
    decided = decide_substitution(
        disruption["id"], req1["request_id"], "REJECT",
        clinician_id="clin-2", rationale="not latex-free equivalent",
    )
    after_alloc2 = post_allocation(
        disruption["id"], facility["id"], 25, decided["version"]
    )
    assert after_alloc2["allocated_total"] == 65
    assert after_alloc2["remaining_pool"] == 35
    assert_disruption_partition_invariant(after_alloc2)
    req2_resp = request_substitution(
        disruption["id"], facility["id"], substitute["id"], 35
    )
    # req1 (REJECTED) shares this facility_id; the DECIDE target is the
    # facility's PENDING request.
    req2 = find_substitution_request(
        req2_resp, facility_id=facility["id"], status="PENDING"
    )
    final = decide_substitution(
        disruption["id"], req2["request_id"], "APPROVE",
        clinician_id="clin-2", rationale="acceptable after spec review",
    )
    assert final["status"] == "RESOLVED"
    assert final["allocated_total"] == 65
    assert final["approved_sub_total"] == 35
    assert final["remaining_pool"] == 0
    assert final["covered_quantity"] == 100
    assert_disruption_partition_invariant(final)
