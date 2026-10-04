"""Conversion programs: evaluation bubble-up, review gates, redesign loop."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_conversion_program,
    create_conversion_program,
    create_facility,
    create_product,
    evaluate_line_item,
    find_line_item,
    get_conversion_program,
    make_clinician_headers,
    review_program,
    setup_program_in_review,
    setup_suspended_agreement_scenario,
    validate_error,
    validate_success,
)

CM = TEST_USERS["conversion_mgr_headers"]


def test_program_auto_advances_to_in_review(api):
    """PRD §3.3: "A bubble-up rule rides on every evaluation: the moment an
    evaluation leaves zero line items `PENDING`, the program auto-transitions
    from `IN_EVALUATION` to `IN_REVIEW`, and the program's `version` increments
    by 1 for the call."

    Design: Corner/state_machines/program_auto_advances_to_in_review
    """
    facility = create_facility()
    incumbent = create_product(sku="AA-I")
    replacement = create_product(sku="AA-R", brand_type="PRIVATE_LABEL")
    program = create_conversion_program(
        facility["id"],
        [
            {
                "incumbent_product_id": incumbent["id"],
                "replacement_product_id": replacement["id"],
            },
            {
                "incumbent_product_id": replacement["id"],
                "replacement_product_id": incumbent["id"],
            },
        ],
        name="Switch",
    )
    ln1 = program["line_items"][0]["line_id"]
    ln2 = program["line_items"][1]["line_id"]
    mid = evaluate_line_item(program["id"], ln1, "PASSED", True)
    assert mid["status"] == "IN_EVALUATION"
    fin = evaluate_line_item(
        program["id"], ln2, "FAILED", False, clinician_id="clin-2",
        notes="clinician preferred incumbent",
    )
    assert fin["status"] == "IN_REVIEW"
    assert find_line_item(fin, ln2)["evaluation_status"] == "FAILED"


def test_review_decision_from_in_evaluation_409(api):
    """PRD §3.3: "Review is a gated decision by a `ConversionManager`, valid only
    while the program is `IN_REVIEW` (otherwise `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/program_review_decision_from_in_evaluation_rejected
    """
    facility = create_facility()
    incumbent = create_product(sku="AB-I")
    replacement = create_product(sku="AB-R", brand_type="PRIVATE_LABEL")
    program = create_conversion_program(
        facility["id"],
        [
            {
                "incumbent_product_id": incumbent["id"],
                "replacement_product_id": replacement["id"],
            }
        ],
        name="Switch",
    )
    resp = api.record_review_decision(program["id"], {"decision": "APPROVE"}, CM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert get_conversion_program(program["id"])["status"] == "IN_EVALUATION"


def test_line_item_failed_reevaluation_loop(api):
    """PRD §3.3: "A `REDESIGN` decision instead loops the program back to
    `IN_EVALUATION` — the cyclic redesign path — where line items keep their
    existing `evaluation_status` values and `FAILED` items become eligible for
    re-evaluation."

    Design: Corner/state_machines/line_item_failed_reevaluation_loop
    """
    ctx = setup_program_in_review(outcome="FAILED", training_completed=False)
    program = ctx["program"]
    assert program["status"] == "IN_REVIEW"
    looped = review_program(program["id"], "REDESIGN")
    assert looped["status"] == "IN_EVALUATION"
    reeval = evaluate_line_item(
        program["id"], ctx["line_id"], "PASSED", True,
        notes="second look after inservice",
    )
    assert reeval["status"] == "IN_REVIEW"
    item = find_line_item(reeval, ctx["line_id"])
    assert item["evaluation_status"] == "PASSED"
    assert item["training_completed"] is True


def test_conversion_same_product_line_422(api):
    """PRD §3.3: "the two must differ, and the replacement's `availability` must
    be `ACTIVE` — a line item that names the same product twice, or whose
    replacement is discontinued, rejects the whole creation with
    `ERR_SAME_PRODUCT_CONVERSION` (HTTP 422)."

    Design: Corner/validations/conversion_same_product_line_rejected
    """
    facility = create_facility()
    product = create_product(sku="CS-1")
    resp = api.create_conversion_program(
        {
            "facility_id": facility["id"],
            "name": "Bad switch",
            "target_categories": ["WOUND_CARE"],
            "line_items": [
                {
                    "incumbent_product_id": product["id"],
                    "replacement_product_id": product["id"],
                }
            ],
        },
        headers=CM,
    )
    validate_error(resp, ApiErrorId.ERR_SAME_PRODUCT_CONVERSION.value, 422)


def test_program_items_failed_blocks_approve(api):
    """PRD §3.3: "An `APPROVE` decision runs three gates in this order: every
    line item's `evaluation_status` must be `PASSED` (otherwise
    `ERR_PROGRAM_ITEMS_FAILED`, HTTP 409); then every line item's
    `training_completed` must be true (otherwise `ERR_ITEMS_NOT_TRAINED`,
    HTTP 409); then the facility's `PrimeVendorAgreement` must exist, be
    `ACTIVE`, and have an `end_date` at or after the current logical clock
    (otherwise `ERR_AGREEMENT_NOT_ACTIVE`, HTTP 409)."

    Design: Corner/validations/program_items_failed_blocks_approve
    """
    ctx = setup_program_in_review(
        outcome="FAILED", training_completed=False, with_agreement=True
    )
    resp = api.record_review_decision(ctx["program"]["id"], {"decision": "APPROVE"}, CM)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_ITEMS_FAILED.value, 409)
    assert get_conversion_program(ctx["program"]["id"])["status"] == "IN_REVIEW"


def test_items_not_trained_blocks_approve(api):
    """PRD §3.3: "then every line item's `training_completed` must be true
    (otherwise `ERR_ITEMS_NOT_TRAINED`, HTTP 409)". PRD §2.6: "within the
    conversion review gate, the line-item evaluation check is evaluated before
    the training check, which is evaluated before the cross-entity agreement
    check".

    Design: Corner/validations/items_not_trained_blocks_approve
    """
    ctx = setup_program_in_review(
        outcome="PASSED", training_completed=False, with_agreement=True
    )
    resp = api.record_review_decision(ctx["program"]["id"], {"decision": "APPROVE"}, CM)
    validate_error(resp, ApiErrorId.ERR_ITEMS_NOT_TRAINED.value, 409)
    assert get_conversion_program(ctx["program"]["id"])["status"] == "IN_REVIEW"


def test_clinician_cannot_review_decision_403(api):
    """PRD §2.1: "A request whose role is not among the roles authorized for the
    target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)".
    PRD §4: review-decision is authorized for `ConversionManager` only.

    Design: Corner/rbac/clinician_cannot_review_decision
    """
    facility = create_facility()
    incumbent = create_product(sku="RB1-I")
    replacement = create_product(sku="RB1-R", brand_type="PRIVATE_LABEL")
    program = create_conversion_program(
        facility["id"],
        [
            {
                "incumbent_product_id": incumbent["id"],
                "replacement_product_id": replacement["id"],
            }
        ],
        name="Switch",
    )
    resp = api.record_review_decision(
        program["id"], {"decision": "REDESIGN"}, make_clinician_headers("clin-7")
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value, 403)


def test_conversion_approve_blocked_by_suspended_agreement(api):
    """PRD §3.3: "then the facility's `PrimeVendorAgreement` must exist, be
    `ACTIVE`, and have an `end_date` at or after the current logical clock
    (otherwise `ERR_AGREEMENT_NOT_ACTIVE`, HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/conversion_approve_requires_active_agreement
    """
    ctx = setup_suspended_agreement_scenario()
    assert ctx["order"]["final_fill_rate_pct"] == 85.00
    facility = ctx["facility"]
    incumbent = create_product(sku="PG-INC", each_price_cents=50)
    replacement = create_product(
        sku="PG-REP", brand_type="PRIVATE_LABEL", each_price_cents=40
    )
    program = create_conversion_program(
        facility["id"],
        [
            {
                "incumbent_product_id": incumbent["id"],
                "replacement_product_id": replacement["id"],
            }
        ],
        name="Wound care switch",
    )
    line_id = program["line_items"][0]["line_id"]
    evaluated = evaluate_line_item(
        program["id"], line_id, "PASSED", True, clinician_id="clin-9",
        notes="staff in-serviced",
    )
    assert evaluated["status"] == "IN_REVIEW"
    resp = api.record_review_decision(program["id"], {"decision": "APPROVE"}, CM)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value, 409)


def test_conversion_approve_rejection_preserves_in_review(api):
    """PRD §3.3: "Review is a gated decision by a `ConversionManager`, valid only
    while the program is `IN_REVIEW` (otherwise `ERR_INVALID_STATE`)."
    PRD §3.3: "then the facility's `PrimeVendorAgreement` must exist, be
    `ACTIVE`, and have an `end_date` at or after the current logical clock
    (otherwise `ERR_AGREEMENT_NOT_ACTIVE`, HTTP 409)." A rejected gate leaves
    the program in `IN_REVIEW`.

    Design: Difficulty/cross_entity_state_dependency/conversion_approve_requires_active_agreement
    """
    ctx = setup_suspended_agreement_scenario()
    facility = ctx["facility"]
    incumbent = create_product(sku="PG-IN2")
    replacement = create_product(sku="PG-RE2", brand_type="PRIVATE_LABEL")
    program = create_conversion_program(
        facility["id"],
        [
            {
                "incumbent_product_id": incumbent["id"],
                "replacement_product_id": replacement["id"],
            }
        ],
        name="Wound care switch",
    )
    line_id = program["line_items"][0]["line_id"]
    evaluate_line_item(program["id"], line_id, "PASSED", True)
    resp = api.record_review_decision(program["id"], {"decision": "APPROVE"}, CM)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value, 409)
    reread = get_conversion_program(program["id"])
    assert_conversion_program(reread)
    assert reread["status"] == "IN_REVIEW"
