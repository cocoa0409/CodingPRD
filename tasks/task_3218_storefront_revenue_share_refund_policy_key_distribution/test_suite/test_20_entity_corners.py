"""Breadth coverage for entity creation defaults, uniqueness, and lookup."""
from test_helpers import (
    api_client,
    create_active_developer,
    create_developer,
    create_title,
    make_developer_headers,
    validate_error,
    validate_success,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
)

OPS = TEST_USERS["platform_ops_headers"]


def test_developer_account_creation_and_defaults():
    """PRD §3.1: "The new account starts in `PENDING` status with
    `onboarding_fee_paid` and `bank_details_submitted` both false."

    Design: Corner/entities/developer_account_creation_and_defaults
    """
    dev = create_developer(company_name="Fresh Studio", contact_email="fresh@studio.example")

    read = validate_success(api_client.get_developer_account(dev["id"], OPS))
    assert read["status"] == "PENDING"
    assert read["onboarding_fee_paid"] is False
    assert read["bank_details_submitted"] is False
    assert isinstance(read["version"], int)


def test_developer_account_duplicate_email_rejected():
    """PRD §3.1: "The contact email must be unique across all developer
    accounts; a duplicate is rejected with `ERR_DUPLICATE` (HTTP 409)."

    Design: Corner/entities/developer_account_duplicate_email_rejected
    """
    create_developer(company_name="First", contact_email="dup@studio.example")

    res = api_client.create_developer_account(
        {"company_name": "Second", "contact_email": "dup@studio.example"}, OPS
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE)


def test_entity_not_found_returns_404():
    """PRD §2.7: "Next, every identifier referenced in the path and body is
    resolved left-to-right in path order, and the first missing resource yields
    `ERR_NOT_FOUND`."

    Design: Corner/entities/entity_not_found_returns_404
    """
    res = api_client.get_title(NON_EXISTENT_UUID, OPS)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_title_patch_only_in_draft():
    """PRD §3.2: "A patch attempted against a title that has left `DRAFT` is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/entities/title_patch_only_in_draft
    """
    developer = create_active_developer()
    title = create_title(developer, title_name="Patch Game", base_price_usd_cents=500)
    dev_headers = make_developer_headers(developer["id"])

    # Leaving DRAFT: submit for store-page review.
    from test_helpers import submit_and_get_review, read_title
    submit_and_get_review(title, developer)

    res = api_client.patch_title(title["id"], {"title_name": "Renamed"}, dev_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    unchanged = read_title(title["id"], developer)
    assert unchanged["title_name"] == "Patch Game"
