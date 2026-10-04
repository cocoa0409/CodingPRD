"""Corner coverage: role-based access control denials."""
from test_helpers import (
    ApiErrorId,
    create_consortium,
    create_library,
    create_order,
    create_patron,
    make_library_admin_headers,
    make_patron_headers,
    setup_base,
    setup_base_with_title,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_patron_cannot_propose_acquisition_order(api):
    """PRD §2.1: "A request whose role is recognized but not permitted on the
    target endpoint, or which fails an ownership check, is rejected with
    `ERR_FORBIDDEN`."
    PRD §3.10: "A `LibraryAdmin` of the purchasing library then moves the order
    along. Proposing sends `DRAFT` → `PROPOSED`."

    Design: Corner/rbac/patron_cannot_propose_acquisition_order
    """
    ctx = setup_base_with_title()
    lib = ctx["library"]
    p0 = create_patron(lib["id"], external_card_number="P-0", full_name="Patron Zero")
    order = create_order(lib["id"], ctx["fund"]["id"], ctx["title"]["id"])
    resp = api.propose_order(order["id"], make_patron_headers(p0["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    fresh = validate_success(
        api.get_order(order["id"], make_library_admin_headers(lib["id"]))
    )
    assert fresh["status"] == "DRAFT"


def test_library_admin_cannot_touch_other_library_patrons(api):
    """PRD §2.1: "When `X-User-Role` is `LibraryAdmin`, `X-User-ID` is the `id`
    of the acting `Library`; ownership checks on any resource that references a
    `Library` compare the resource's `library_id` foreign-key field to
    `X-User-ID`."

    Design: Corner/rbac/library_admin_cannot_touch_other_library_patrons
    """
    ctx = setup_base()
    lib_a = ctx["library"]
    lib_b = create_library(ctx["consortium"]["id"], name="Library B")
    resp = api.create_patron(
        lib_a["id"],
        {"external_card_number": "X-1", "full_name": "Cross Library",
         "postal_code": "94301"},
        make_library_admin_headers(lib_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    patrons, _ = validate_paginated(
        api.list_patrons(lib_a["id"], make_library_admin_headers(lib_a["id"]))
    )
    assert len(patrons) == 0


def test_patron_cannot_read_other_patron_record(api):
    """PRD §2.1: "When `X-User-Role` is `Patron`, `X-User-ID` is the `id` of
    the acting `Patron`; ownership checks compare the resource's `patron_id`
    foreign-key field to `X-User-ID`."

    Design: Corner/rbac/patron_cannot_read_other_patron_record
    """
    ctx = setup_base()
    lib = ctx["library"]
    p0 = create_patron(lib["id"], external_card_number="P-0", full_name="Patron Zero")
    p1 = create_patron(lib["id"], external_card_number="P-1", full_name="Patron One")
    resp = api.get_patron(p1["id"], make_patron_headers(p0["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting a role string
    outside this set, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    ctx = setup_base()
    resp = api.get_consortium(ctx["consortium"]["id"], headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
