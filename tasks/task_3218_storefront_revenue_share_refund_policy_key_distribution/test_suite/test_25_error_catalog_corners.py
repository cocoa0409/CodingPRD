"""Breadth coverage for the error catalogue."""
from test_helpers import (
    api_client,
    create_active_developer,
    make_developer_headers,
    validate_error,
    ApiErrorId,
)


def test_error_catalog_triggerability():
    """PRD §2.7: "Field-level request validity comes seventh — missing required
    fields, bad types, out-of-range enums, empty strings, and numeric bounds
    all yield `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/errors/error_catalog_triggerability
    """
    developer = create_active_developer()
    dev_headers = make_developer_headers(developer["id"])

    res = api_client.create_title(
        {"developer_account_id": developer["id"], "title_name": "No Price"},
        dev_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)
