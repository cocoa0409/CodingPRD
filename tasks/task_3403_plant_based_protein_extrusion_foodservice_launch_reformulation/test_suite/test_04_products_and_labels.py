"""Product generations, label workflow (submit/return/approve), claim gates,
and the product-version OCC rule on label approval (PRD sections 2.7, 3.4)."""
import pytest

from test_helpers import (
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    validate_error, validate_success,
    create_product_payload, product_lifecycle_payload,
    label_transition_payload,
    create_bare_product, create_draft_label, submit_label,
    return_label_to_draft, approve_label, transition_product,
    create_product_with_approved_label,
    fetch_product, fetch_label,
)

_PROD = TEST_USERS["product_manager_headers"]


def test_get_product_missing_id_returns_not_found(api):
    """PRD section 2.8: "Every identifier the request references must resolve:
    path parameters first, left to right, then foreign keys carried in the
    body in the endpoint's declared input order — otherwise `ERR_NOT_FOUND`
    (404)."

    Design: Corner/entities/cn_ent_product_get_not_found_returns_404
    """
    resp = api.get_product(NON_EXISTENT_UUID, _PROD)
    err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert err.get("message")


def test_unknown_isolate_enum_rejected(api):
    """PRD section 2.8: "Unknown or invalid enum values, missing required
    inputs, and violated type-conditional field requirements — all
    `ERR_INVALID_REQUEST` (400)." `SEAWEED` is not one of the declared isolate
    types of PRD section 3.1 ("one of `PEA`, `FABA_BEAN`, `SOY`, or
    `MUNG_BEAN`").

    Design: Corner/entities/cn_ent_invalid_enum_returns_invalid_request
    """
    resp = api.create_product(
        create_product_payload(product_code="PROD-BAD-E",
                               isolate_type="SEAWEED"),
        _PROD)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_product_cannot_skip_pilot(api):
    """PRD section 3.4: "Products walk the lifecycle `DEVELOPMENT` → `PILOT` →
    `ACTIVE` → `SUNSET` → `DISCONTINUED`, each step taken deliberately by the
    `ProductManager` naming a `target_state`, and each requiring the product
    to sit in the immediately preceding state (`ERR_INVALID_STATE`)." Even
    with an APPROVED label, DEVELOPMENT -> ACTIVE is not a declared step.

    Design: Corner/state_machines/cn_sm_product_skip_pilot_returns_409
    """
    product, _label = create_product_with_approved_label(
        {"product_code": "PROD-K-5"})
    resp = api.product_lifecycle_transition(
        product["id"], product_lifecycle_payload("ACTIVE"), _PROD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_approved_label_cannot_return_to_submitted(api):
    """PRD section 3.4 declares only three client-driven label moves —
    "Submitting a label (`DRAFT` → `SUBMITTED`)", "returned for revision
    (`SUBMITTED` → `DRAFT`)", and "Approval (`SUBMITTED` → `APPROVED`)" — and
    APPROVED labels leave only because a sibling "is cascaded to
    `SUPERSEDED`, which is terminal". Per PRD section 2.8 an undeclared move
    from APPROVED is `ERR_INVALID_STATE` (409).

    Design: Corner/state_machines/cn_sm_label_approved_to_submitted_returns_409
    """
    product, label = create_product_with_approved_label(
        {"product_code": "PROD-K-6"})
    resp = api.label_version_transition(
        label["id"], label_transition_payload("SUBMITTED"), _PROD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_label_revision_loop_is_legal(api):
    """PRD section 3.4: "A submitted label can be returned for revision
    (`SUBMITTED` → `DRAFT`) without ceremony." The DRAFT -> SUBMITTED -> DRAFT
    -> SUBMITTED loop is legal and moves no product version.

    Design: Difficulty/non_linear_state_machine/nsm_label_revision_cycle
    """
    product = create_bare_product(product_code="PROD-CYC-1")
    label = create_draft_label(product["id"])
    submit_label(label["id"])
    label = return_label_to_draft(label["id"])
    assert label["status"] == "DRAFT"
    label = submit_label(label["id"])
    assert label["status"] == "SUBMITTED"
    assert fetch_product(product["id"])["version"] == product["version"]


def test_label_loop_then_approve_bumps_product_version_once(api):
    """PRD section 3.4: "on success the product's `version` advances by one"
    — only the final APPROVED of the DRAFT -> SUBMITTED -> DRAFT -> SUBMITTED
    -> APPROVED loop advances the product's version; submits and returns do
    not.

    Design: Difficulty/non_linear_state_machine/nsm_label_revision_cycle
    """
    product = create_bare_product(product_code="PROD-CYC-1")
    label = create_draft_label(product["id"])
    submit_label(label["id"])
    return_label_to_draft(label["id"])
    submit_label(label["id"])
    label = approve_label(label["id"], product["id"])
    assert label["status"] == "APPROVED"
    assert fetch_product(product["id"])["version"] == product["version"] + 1


def test_second_approval_supersedes_first_label(api):
    """PRD section 3.4: "on success the product's `version` advances by one
    while any previously `APPROVED` label of the same product is cascaded to
    `SUPERSEDED`, which is terminal. At most one label version per product is
    therefore `APPROVED` at any moment."

    Design: Corner/state_machines/cn_sm_label_second_approve_supersedes_first
    """
    product, label1 = create_product_with_approved_label(
        {"product_code": "PROD-K-9"})
    version_after_first = product["version"]
    label2 = create_draft_label(
        product["id"], version_number=2, protein_g=19, fat_g=4,
        sodium_mg=300, claims=[],
        ingredient_statement="Water, pea protein isolate, cocoa butter")
    submit_label(label2["id"])
    label2 = approve_label(label2["id"], product["id"])
    assert label2["status"] == "APPROVED"
    assert fetch_label(label1["id"])["status"] == "SUPERSEDED"
    assert fetch_product(product["id"])["version"] == version_after_first + 1


def test_high_protein_claim_needs_20g_protein(api):
    """PRD section 3.4: "a `HIGH_PROTEIN` claim is supported only when
    `protein_g` is at least 20, and a `LOW_SATURATED_FAT` claim only when
    `fat_g` is at most 3; an unsupported claim is rejected with
    `ERR_LABEL_CLAIM_UNSUPPORTED`". The gate runs at SUBMITTED, not at draft
    creation.

    Design: Corner/validations/cn_val_label_claim_unsupported
    """
    product = create_bare_product(product_code="PROD-K-22")
    label = create_draft_label(product["id"], protein_g=18,
                               claims=["HIGH_PROTEIN"])
    resp = api.label_version_transition(
        label["id"], label_transition_payload("SUBMITTED"), _PROD)
    validate_error(resp, ApiErrorId.ERR_LABEL_CLAIM_UNSUPPORTED)
    assert fetch_label(label["id"])["status"] == "DRAFT"


def test_label_approval_with_stale_product_version_rejected(api):
    """PRD section 2.7: "The value must equal the product's current
    `version`; if the product's `version` has advanced since the client last
    read it — for example because another label of the same product has since
    been approved, superseding the previous one — the approval is rejected as
    stale with `ERR_STALE_PRODUCT_VERSION` (HTTP 412)." Re-reading the product
    and retrying with the current version succeeds and supersedes the prior
    APPROVED label (PRD section 3.4).

    Design: Corner/cross_cutting_layers/cn_occ_label_approve_stale_product_version
    """
    product = create_bare_product(product_code="PROD-K-61")
    stale_version = product["version"]
    label1 = create_draft_label(product["id"], version_number=1)
    submit_label(label1["id"])
    approve_label(label1["id"], product["id"])
    label2 = create_draft_label(
        product["id"], version_number=2, protein_g=24, fat_g=4,
        sodium_mg=300, claims=["HIGH_PROTEIN"],
        ingredient_statement="Water, pea protein isolate, cocoa butter")
    submit_label(label2["id"])
    resp_stale = api.label_version_transition(
        label2["id"],
        label_transition_payload("APPROVED",
                                 expected_product_version=stale_version),
        _PROD)
    validate_error(resp_stale, ApiErrorId.ERR_STALE_PRODUCT_VERSION)
    fresh_version = fetch_product(product["id"])["version"]
    resp_retry = api.label_version_transition(
        label2["id"],
        label_transition_payload("APPROVED",
                                 expected_product_version=fresh_version),
        _PROD)
    label2_after = validate_success(resp_retry)
    assert label2_after["status"] == "APPROVED"
    assert fetch_label(label1["id"])["status"] == "SUPERSEDED"
    assert fetch_product(product["id"])["version"] == fresh_version + 1
