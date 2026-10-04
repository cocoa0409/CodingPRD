"""Validation-rule corner tests (corner design: validations)."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_app,
    create_app_version,
    create_developer,
    create_merchant,
    create_review_window_payload,
    get_success_data,
    make_admin_headers,
    make_developer_headers,
    make_merchant_headers,
    make_reviewer_headers,
    register_permission_scope,
    set_clock,
    setup_active_installation,
    setup_uninstalling_installation,
    submit_app,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


def test_discount_on_recurring_charge_rejected(api):
    """PRD §3.6: "a `discount_code` is honored only on `ONE_TIME` charges.
    Supplying a `discount_code` on a `RECURRING` or `USAGE` charge is rejected
    with `ERR_DISCOUNT_NOT_APPLICABLE`."

    Design: Corner/validations/discount_on_recurring_charge_rejected
    """
    developer, app, version, merchant, installation = setup_active_installation(
        company="DV1", category="MARKETING"
    )
    resp = api.create_billing_charge(
        installation["id"],
        {"charge_type": "RECURRING", "base_amount_cents": 1000,
         "description": "bad coupon", "discount_code": "LAUNCH10"},
        make_developer_headers(developer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DISCOUNT_NOT_APPLICABLE)


def test_overdue_data_deletion_confirm_rejected(api):
    """PRD §3.9: "The developer confirms deletion via the
    confirm-data-deletion action, which requires the installation to be
    `UNINSTALLING`, requires the current logical time to be at or before
    `data_deletion_deadline`, and requires the acting developer to own the
    app. Confirmation attempted after the deadline is rejected with
    `ERR_DELETION_OVERDUE`."

    Design: Corner/validations/overdue_data_deletion_confirm_rejected
    """
    developer, app, merchant, installation, _ = setup_uninstalling_installation(
        company="DV2", category="FINANCE"
    )
    # Deadline is uninstalled_at + 30 days; jump past it. Per PRD §3.9 the
    # system cascade moves the installation UNINSTALLING → UNINSTALLED as the
    # deadline passes, so the confirm action sees a non-UNINSTALLING state;
    # PRD §2.7 places the state category (priority 4) above the
    # data-deletion-deadline category (priority 11), so either
    # ERR_INVALID_STATE (state masks deadline) or ERR_DELETION_OVERDUE is a
    # PRD-faithful outcome here.
    set_clock("2026-10-03T00:00:00Z")
    resp = api.confirm_data_deletion(
        installation["id"], {}, make_developer_headers(developer["id"])
    )
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_DELETION_OVERDUE, ApiErrorId.ERR_INVALID_STATE]
    )


def test_high_scope_request_without_justification_rejected(api):
    """PRD §3.3: "A developer creates a scope request against a version by
    providing the `scope_code` of a scope already registered in the platform's
    permission catalog and, when the scope's `risk_level` is `HIGH`, a
    free-text `justification` of at least 20 characters. The justification
    requirement is enforced at request creation: a `HIGH`-risk scope request
    without a sufficient justification is rejected with
    `ERR_SCOPE_JUSTIFICATION_REQUIRED`. For scopes of `LOW` or `MEDIUM` risk
    the justification is optional."

    Design: Corner/validations/high_scope_request_without_justification_rejected
    """
    developer = create_developer(company_name="DV3")
    app = create_app(developer["id"], name="AppV3", category="PRODUCTIVITY")
    version = create_app_version(app["id"], developer["id"])
    register_permission_scope("write_orders", risk_level="HIGH")
    register_permission_scope("read_products", risk_level="LOW")
    dev_headers = make_developer_headers(developer["id"])
    resp = api.create_scope_request(
        version["id"], {"scope_code": "write_orders"}, dev_headers
    )
    validate_error(resp, ApiErrorId.ERR_SCOPE_JUSTIFICATION_REQUIRED)
    ok = api.create_scope_request(
        version["id"], {"scope_code": "read_products"}, dev_headers
    )
    validate_success(ok, expected_status=201)


def test_charge_amount_zero_rejected(api):
    """PRD §3.6: "Billing begins when a developer creates a charge against an
    installation, providing the `charge_type` (one of `RECURRING`, `USAGE`, or
    `ONE_TIME`), the `base_amount_cents` (which must be strictly positive — a
    zero or negative amount is rejected with `ERR_INVALID_AMOUNT`), a
    human-readable `description` that will appear as the line-item text on the
    merchant's invoice, and an optional `discount_code`."

    Design: Corner/validations/charge_amount_zero_rejected
    """
    developer, app, version, merchant, installation = setup_active_installation(
        company="DV4", category="ANALYTICS"
    )
    resp = api.create_billing_charge(
        installation["id"],
        {"charge_type": "ONE_TIME", "base_amount_cents": 0, "description": "free?"},
        make_developer_headers(developer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_AMOUNT)


def test_app_name_duplicate_per_developer_rejected(api):
    """PRD §3.1: "App names must be unique within the owning developer's
    portfolio; the same name may be used by a different developer without
    conflict, but a second app with the same name under the same developer is
    rejected with `ERR_DUPLICATE`."

    Design: Corner/validations/app_name_duplicate_per_developer_rejected
    """
    developer_a = create_developer(company_name="DV5A")
    developer_b = create_developer(company_name="DV5B")
    validate_success(
        api.create_app(
            {"developer_id": developer_a["id"], "name": "Dup", "category": "PRODUCTIVITY"},
            make_developer_headers(developer_a["id"]),
        ),
        expected_status=201,
    )
    resp = api.create_app(
        {"developer_id": developer_a["id"], "name": "Dup", "category": "MARKETING"},
        make_developer_headers(developer_a["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE)
    other = api.create_app(
        {"developer_id": developer_b["id"], "name": "Dup", "category": "MARKETING"},
        make_developer_headers(developer_b["id"]),
    )
    validate_success(other, expected_status=201)


def test_review_window_inverted_interval_rejected(api):
    """PRD §3.2: "The window is a half-open interval `[starts_at, ends_at)`:
    `starts_at` is the inclusive lower bound and `ends_at` is the exclusive
    upper bound, and `ends_at` must be strictly after `starts_at`."

    Design: Corner/validations/review_window_inverted_interval_rejected
    """
    developer = create_developer(company_name="DV6")
    app = create_app(developer["id"], name="AppV6", category="FULFILLMENT")
    version = create_app_version(app["id"], developer["id"])
    submit_app(app["id"], developer["id"])
    resp = api.create_review_window(
        version["id"],
        create_review_window_payload(
            starts_at="2026-09-15T00:00:00Z", ends_at="2026-09-15T00:00:00Z"
        ),
        make_reviewer_headers("rev-1"),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
