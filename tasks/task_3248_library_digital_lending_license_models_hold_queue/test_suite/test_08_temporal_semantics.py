"""Half-open temporal semantics: copy occupancy until due; fund period overlap."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    checkout,
    create_fund,
    create_patron,
    make_library_admin_headers,
    make_patron_headers,
    set_clock,
    setup_base,
    setup_ocou_library,
    validate_error,
    validate_success,
)


def test_checkout_one_second_before_due_finds_no_license(api):
    """PRD §3.6: "For an `OCOU` license, `copies_on_loan` is the count of
    `ACTIVE` loans against it, and the lendable count is `copies_total` minus
    `copies_on_loan` minus the number of `READY` holds whose reserved copy
    belongs to that license."
    PRD §3.5: "If no eligible license exists, the checkout fails with
    `ERR_NO_LICENSE_AVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/ocou_copy_occupancy_until_due_boundary
    """
    ctx = setup_ocou_library(copies=1)
    lib = ctx["library"]
    p0 = create_patron(lib["id"], external_card_number="P-0", full_name="Patron Zero")
    p1 = create_patron(lib["id"], external_card_number="P-1", full_name="Patron One")
    checkout(p0["id"], ctx["title"]["id"])
    set_clock("2026-09-21T23:59:59Z")
    resp = api.checkout({"patron_id": p1["id"], "title_id": ctx["title"]["id"]},
                        make_patron_headers(p1["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_LICENSE_AVAILABLE)


def test_epoch_at_exact_due_instant_frees_copy_for_recheckout(api):
    """PRD §3.7: "When an epoch finds an `ACTIVE` loan whose `due_at` has been
    reached, the loan moves `ACTIVE` → `EXPIRED`, the meter unwinds exactly as
    for a return (`copies_on_loan` decrements for `OCOU`; the grace-window
    restore does not apply here), the patron's `active_loan_count` decrements,
    a `LOAN_EXPIRED` event is written, and the freed copy triggers the same
    promotion cascade."

    Design: Difficulty/resource_temporal_overlap/ocou_copy_occupancy_until_due_boundary
    """
    ctx = setup_ocou_library(copies=1)
    lib = ctx["library"]
    p0 = create_patron(lib["id"], external_card_number="P-0", full_name="Patron Zero")
    p1 = create_patron(lib["id"], external_card_number="P-1", full_name="Patron One")
    loan0 = checkout(p0["id"], ctx["title"]["id"])
    assert loan0["due_at"] == "2026-09-22T00:00:00Z"
    set_clock("2026-09-22T00:00:00Z")
    api.run_epoch(ADMIN)
    expired = validate_success(
        api.get_loan(loan0["id"], make_patron_headers(p0["id"]))
    )
    assert expired["status"] == "EXPIRED"
    resp = api.checkout({"patron_id": p1["id"], "title_id": ctx["title"]["id"]},
                        make_patron_headers(p1["id"]))
    loan1 = validate_success(resp, expected_status=201)
    assert loan1["status"] == "ACTIVE"
    assert loan1["checkout_at"] == "2026-09-22T00:00:00Z"


def test_overlapping_sibling_fund_rejected(api):
    """PRD §3.10: "A new fund starts `OPEN`, and the period must not intersect
    any sibling fund of the same library: an overlapping window is rejected
    with `ERR_FUND_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/fund_period_half_open_overlap_vs_adjacency
    """
    ctx = setup_base()
    lib = ctx["library"]
    resp = api.create_fund(
        lib["id"],
        {"fiscal_year": 2027, "period_start": "2026-12-31T23:59:59Z",
         "period_end": "2028-01-01T00:00:00Z", "budget_cents": 500000},
        make_library_admin_headers(lib["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FUND_PERIOD_OVERLAP)


def test_adjacent_sibling_fund_accepted(api):
    """PRD §3.10: "adjacent periods, where one fund's end equals the next's
    start, are allowed because the intervals are half-open."

    Design: Difficulty/resource_temporal_overlap/fund_period_half_open_overlap_vs_adjacency
    """
    ctx = setup_base()
    lib = ctx["library"]
    resp = api.create_fund(
        lib["id"],
        {"fiscal_year": 2027, "period_start": "2027-01-01T00:00:00Z",
         "period_end": "2028-01-01T00:00:00Z", "budget_cents": 500000},
        make_library_admin_headers(lib["id"]),
    )
    fund = validate_success(resp, expected_status=201)
    assert fund["status"] == "OPEN"
    assert fund["version"] == 1
