"""Authentication, per-endpoint authorization, and segregation of duties
(PRD §2.1, §3.4, §3.8).
"""
import pytest

from test_helpers import (
    LEAD,
    LC_JANE,
    LC_JOHN,
    MEDIA,
    RETAIL,
    SCI_ANNA,
    SCI_BOB,
    ApiErrorId,
    api_client,
    complete_claim_study,
    create_claim_study,
    create_concept_payload,
    create_retail_agreement,
    create_season_payload,
    decide_media_payload,
    file_case,
    get_retail_agreement,
    order_line,
    record_judgment_payload,
    reset_clock,
    settle_case,
    settle_case_payload,
    setup_active_high_case,
    setup_airing_media,
    setup_season_with_category,
    setup_substantiated_study,
    setup_tooled_variant,
    validate_error,
    validate_ok,
)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request in which either header is missing or blank, or
    whose `X-User-Role` names no declared role, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    reset_clock()
    resp = api_client.create_season(create_season_payload("FW26"), headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_media_buyer_cannot_create_concept(api):
    """PRD §2.1: "A request whose authenticated role does not appear in the
    target endpoint's authorized-roles list is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."

    Design: Corner/validations/media_buyer_cannot_create_concept
    """
    base = setup_season_with_category()
    resp = api_client.create_concept(
        create_concept_payload(base["category"]["id"], "Sneaky media concept"), MEDIA
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_product_lead_cannot_sign_agreement(api):
    """PRD §2.1: "A request whose authenticated role does not appear in the
    target endpoint's authorized-roles list is rejected with `ERR_FORBIDDEN`
    (HTTP 403)." PRD §4 restricts sign to RetailExec.

    Design: Corner/rbac/product_lead_cannot_sign_agreement
    """
    base = setup_season_with_category()
    agreement = create_retail_agreement(base["category"]["id"], exclusive=False)
    resp = api_client.sign_retail_agreement(agreement["id"], LEAD)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert get_retail_agreement(agreement["id"])["status"] == "DRAFT"


def test_retail_exec_cannot_record_judgment(api):
    """PRD §2.1: "A request whose authenticated role does not appear in the
    target endpoint's authorized-roles list is rejected with `ERR_FORBIDDEN`
    (HTTP 403)." PRD §4 restricts record-judgment to LegalCounsel.

    Design: Corner/rbac/retail_exec_cannot_record_judgment
    """
    bundle = setup_active_high_case()
    resp = api_client.record_judgment(
        bundle["case"]["id"], record_judgment_payload("ADVERSE", 900000), RETAIL
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    cases = validate_ok(
        api_client.list_category_patent_cases(bundle["category"]["id"], LC_JANE)
    )
    assert cases[0]["status"] == "ACTIVE"


def test_claims_scientist_cannot_decide_media(api):
    """PRD §2.1: "A request whose authenticated role does not appear in the
    target endpoint's authorized-roles list is rejected with `ERR_FORBIDDEN`
    (HTTP 403)." PRD §4 restricts decide to MediaBuyer.

    Design: Corner/rbac/claims_scientist_cannot_decide_media
    """
    base = setup_season_with_category()
    bundle = setup_tooled_variant(base["category"]["id"])
    setup_substantiated_study(bundle["variant"]["id"])
    media = setup_airing_media(bundle["variant"]["id"])
    resp = api_client.decide_media_test(
        media["id"], decide_media_payload("KILL", [order_line(100)]), SCI_ANNA
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    tests = validate_ok(
        api_client.list_variant_media_tests(bundle["variant"]["id"], MEDIA)
    )
    assert tests[0]["status"] == "AIRING"


def test_sod_substantiate_by_conducting_scientist_rejected(api):
    """PRD §3.4: "A `ClaimsScientist` substantiates a `RESULTS_RECORDED` study,
    but the caller's `X-User-ID` must differ from the study's
    `conducted_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/sod_substantiate_by_conducting_scientist_rejected
    """
    base = setup_season_with_category()
    bundle = setup_tooled_variant(base["category"]["id"])
    study = create_claim_study(bundle["variant"]["id"], conductor_headers=SCI_ANNA)
    complete_claim_study(study["id"], 115, 100, 40, conductor_headers=SCI_ANNA)
    resp = api_client.substantiate_claim_study(study["id"], SCI_ANNA)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    data = validate_ok(api_client.substantiate_claim_study(study["id"], SCI_BOB))
    assert data["status"] == "SUBSTANTIATED"
    assert data["substantiated_by_user_id"] == "sci-bob"


def test_sod_settle_by_filing_counsel_rejected(api):
    """PRD §3.8: "A `LegalCounsel` settles a case in `FILED` or `ACTIVE` status
    ... but the caller's `X-User-ID` must differ from the case's
    `filed_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/sod_settle_by_filing_counsel_rejected
    """
    base = setup_season_with_category()
    case = file_case(base["category"]["id"], "PT-5001", 1_000_000, "MED",
                     filer_headers=LC_JANE)
    resp = api_client.settle_patent_case(
        case["id"], settle_case_payload(100000), LC_JANE
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    settled = settle_case(case["id"], 100000, settler_headers=LC_JOHN)
    assert settled["status"] == "SETTLED"
    assert settled["final_amount_cents"] == 100000
