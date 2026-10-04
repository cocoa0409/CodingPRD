"""Corner queue B — errors section instances."""

from test_helpers import (
    ApiErrorId,
    create_consent_payload,
    create_institution_payload,
    headers_without_role,
    make_admin_headers,
    make_consumer_headers,
    get_success_data,
    validate_error,
    validate_paginated,
)


def test_err_unauthenticated_missing_role_header(api):
    """PRD §2.1: "A request missing either header, or presenting an
    `X-User-Role` value that is not one of these four, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/err_unauthenticated_missing_role_header
    """
    resp = api.list_institutions(headers_without_role("some_user"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_err_unauthorized_wrong_role(api):
    """PRD §2.1: "When the role is legitimate but is not permitted to invoke
    the requested endpoint, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."
    PRD §4: "`POST /institutions` — Create an institution — PlatformAdmin."

    Design: Corner/errors/err_unauthorized_wrong_role
    """
    resp = api.create_institution(
        create_institution_payload(name="Forbidden Bank"),
        make_consumer_headers("cons_zz"),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    institutions, meta = validate_paginated(api.list_institutions(make_admin_headers()))
    assert meta["total_count"] == 0, "a forbidden create must persist nothing"


def test_err_invalid_request_bad_enum(api):
    """PRD §2.10: "The platform's enumerations are closed sets... Minimization
    policies are `STRICT`, `STANDARD`, and `BROAD`."
    PRD §2.9: "Field-level input validity — enums within declared sets,
    parseable datetimes, in-range integers, required fields present
    (`ERR_INVALID_REQUEST`)."

    Design: Corner/errors/err_invalid_request_bad_enum
    """
    resp = api.create_recipient(
        {
            "name": "BadEnumApp",
            "declared_use_case": "enum test",
            "minimization_policy": "EXTREME",
        },
        make_admin_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_err_parent_not_operable_consent_on_pending_recipient(api):
    """PRD §3.4: "The recipient must be `APPROVED`; otherwise
    `ERR_PARENT_NOT_OPERABLE`."

    Design: Corner/errors/err_parent_not_operable_consent_on_pending_recipient
    """
    admin = make_admin_headers()
    recipient = get_success_data(
        api.create_recipient(
            {"name": "PendingApp", "declared_use_case": "pending gate", "minimization_policy": "BROAD"},
            admin,
        )
    )
    assert recipient["status"] == "PENDING_REVIEW"

    resp = api.create_consent(
        recipient["id"],
        create_consent_payload(
            consumer_ref="cons_ah",
            data_scopes=["BALANCE"],
            expected_recipient_version=recipient["version"],
        ),
        make_consumer_headers("cons_ah"),
    )
    validate_error(resp, ApiErrorId.ERR_PARENT_NOT_OPERABLE)

    consents, meta = validate_paginated(api.list_recipient_consents(recipient["id"], admin))
    assert meta["total_count"] == 0
