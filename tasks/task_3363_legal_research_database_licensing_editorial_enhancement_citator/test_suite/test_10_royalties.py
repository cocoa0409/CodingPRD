"""Secondary-source licensing and royalty settlement: the PER_VIEW and
REVENUE_SHARE bases, immutable statements, termination gates, and half-open
exclusivity windows (PRD §3.7)."""
from test_helpers import (
    CLOCK_SEP_05,
    CLOCK_SEP_10,
    ApiErrorId,
    assert_royalty_statement,
    create_license_agreement,
    generate_invoice,
    generate_royalty_statement,
    issue_invoice,
    license_agreement_payload,
    make_researcher_headers,
    record_usage,
    royalty_statement_payload,
    set_clock,
    setup_subscribed_user,
    terminate_agreement,
    usage_event_payload,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

_LICENSING = TEST_USERS["licensing_manager_headers"]
_BILLING = TEST_USERS["billing_admin_headers"]


def test_royalty_per_view_literal(api):
    """PRD §3.7: "Under `PER_VIEW`, `revenue_base_cents` is 0 and
    `royalty_amount_cents` is simply the `view_count` times the agreement's
    `per_view_fee_cents`."
    PRD §3.7: "The contrast is stark on identical traffic: three licensed views at
    45 cents each settle at 135 cents under `PER_VIEW`, while a 250-basis-point
    share of a 5906-cent revenue base settles at 148 cents."

    Design: Corner/calculations/royalty_per_view_literal
    """
    set_clock(CLOCK_SEP_10)
    agreement = create_license_agreement(
        work_title="PV Treatise", author_name="Auth PV", per_view_fee_cents=45,
    )
    ctx = setup_subscribed_user(
        plan_overrides={"name": "PV Plan", "practice_area": "ALL",
                        "included_searches": 10, "included_doc_views": 10},
        user_email="pv@pv.com",
    )
    record_usage(ctx["user"]["id"], "DOC_VIEW", 3, license_agreement_id=agreement["id"])

    statement = generate_royalty_statement(agreement["id"])
    assert_royalty_statement(statement)
    assert statement["view_count"] == 3
    assert statement["revenue_base_cents"] == 0
    assert statement["royalty_amount_cents"] == 135


def test_royalty_revenue_share_literal(api):
    """PRD §3.7: "Under `REVENUE_SHARE`, `revenue_base_cents` sums the `total_cents`
    of every invoice in `ISSUED` or `PAID` status whose own billing window overlaps
    the settlement window and whose subscription's plan `practice_area` equals the
    agreement's `practice_area` — voided, overdue, and draft invoices contribute
    nothing — and `royalty_amount_cents` is that base multiplied by
    `revenue_share_bps` and divided by ten thousand, rounded half-up to whole
    cents."
    PRD §3.7: "The contrast is stark on identical traffic: three licensed views at
    45 cents each settle at 135 cents under `PER_VIEW`, while a 250-basis-point
    share of a 5906-cent revenue base settles at 148 cents."

    Design: Corner/calculations/royalty_revenue_share_literal
    """
    set_clock(CLOCK_SEP_10)
    agreement = create_license_agreement(
        work_title="RS Treatise", author_name="Auth RS",
        royalty_basis="REVENUE_SHARE", revenue_share_bps=250,
    )
    ctx = setup_subscribed_user(plan_overrides={"name": "RS Plan"},
                                searches=5, doc_views=4, user_email="rs@rs.com")
    invoice = issue_invoice(generate_invoice(ctx["subscription"]["id"])["id"])
    assert invoice["total_cents"] == 5906

    statement = generate_royalty_statement(agreement["id"])
    assert statement["view_count"] == 0
    assert statement["revenue_base_cents"] == 5906
    assert statement["royalty_amount_cents"] == 148, (
        "round_half_up(5906 * 250 / 10000) = round_half_up(147.65) = 148"
    )


def test_royalty_statement_immutable_record(api):
    """PRD §2.5: "Two resources are deliberate exceptions, behaving as immutable
    ledger entries rather than mutable records: a UsageEvent and a RoyaltyStatement
    each carry only `id` and `created_at`."
    PRD §3.7: "Once written, `royalty_amount_cents` never changes."

    Design: Corner/entities/royalty_statement_immutable_record
    """
    set_clock(CLOCK_SEP_10)
    agreement = create_license_agreement(
        work_title="Imm Treatise", author_name="Auth Imm", per_view_fee_cents=45,
    )
    ctx = setup_subscribed_user(
        plan_overrides={"name": "Imm Plan R", "practice_area": "ALL",
                        "included_searches": 10, "included_doc_views": 10},
        user_email="r@imm.com",
    )
    record_usage(ctx["user"]["id"], "DOC_VIEW", 2, license_agreement_id=agreement["id"])

    statement = generate_royalty_statement(agreement["id"])
    assert_royalty_statement(statement)
    assert statement["view_count"] == 2
    assert statement["revenue_base_cents"] == 0
    assert statement["royalty_amount_cents"] == 90, "2 views at 45 cents"


def test_agreement_terminated_blocks_statement_and_events(api):
    """PRD §3.7: "Termination ends an agreement's commercial life. A
    `LicensingManager` terminates an `ACTIVE` agreement into `TERMINATED` — the
    only transition, and terminal; repeating it or acting on a terminated agreement
    fails with `ERR_INVALID_STATE`. From termination onward, usage events carrying
    that `license_agreement_id` are refused with `ERR_AGREEMENT_NOT_ACTIVE`
    (HTTP 409), and royalty generation against the agreement is refused the same
    way."

    Design: Corner/validations/agreement_terminated_blocks_statement_and_events
    """
    set_clock(CLOCK_SEP_10)
    agreement = create_license_agreement(
        work_title="Term Treatise", author_name="Auth T", per_view_fee_cents=45,
    )
    terminate_agreement(agreement["id"])
    ctx = setup_subscribed_user(
        plan_overrides={"name": "TA Plan", "practice_area": "ALL",
                        "included_searches": 10, "included_doc_views": 10},
        user_email="t@ta.com",
    )
    gen = api.generate_royalty_statement(
        royalty_statement_payload(agreement["id"]), _BILLING,
    )
    validate_error(gen, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE, 409)

    event = api.create_usage_event(
        usage_event_payload(event_type="DOC_VIEW", practice_area_tag="LITIGATION",
                            license_agreement_id=agreement["id"]),
        make_researcher_headers(ctx["user"]["id"]),
    )
    validate_error(event, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE, 409)


def test_license_exclusivity_adjacent_window_allowed(api):
    """PRD §3.7: "Two agreements in the same `practice_area` that both carry the
    `exclusive` flag must not have overlapping windows: interior overlap is
    rejected with `ERR_LICENSE_WINDOW_OVERLAP` (HTTP 409), while pure adjacency —
    one window's `window_end` equaling the other's `window_start` — is permitted
    under the half-open semantics of §2.11."

    Design: Difficulty/resource_temporal_overlap/license_exclusivity_half_open_adjacency_allowed
    """
    set_clock(CLOCK_SEP_05)
    create_license_agreement(
        work_title="Treatise One", author_name="Author A", exclusive=True,
        per_view_fee_cents=45, window_start="2026-01-01", window_end="2027-01-01",
    )
    adjacent = api.create_license_agreement(
        license_agreement_payload(
            work_title="Treatise Two", author_name="Author B", exclusive=True,
            per_view_fee_cents=50, window_start="2027-01-01", window_end="2028-01-01",
        ),
        _LICENSING,
    )
    data = validate_success(adjacent, 201)
    assert data["exclusive"] is True

    overlapping = api.create_license_agreement(
        license_agreement_payload(
            work_title="Treatise Three", author_name="Author C", exclusive=True,
            royalty_basis="REVENUE_SHARE", revenue_share_bps=200,
            window_start="2026-12-31", window_end="2027-06-01",
        ),
        _LICENSING,
    )
    validate_error(overlapping, ApiErrorId.ERR_LICENSE_WINDOW_OVERLAP, 409)


def test_license_exclusivity_scoped_per_practice_area(api):
    """PRD §3.7: "Two agreements in the same `practice_area` that both carry the
    `exclusive` flag must not have overlapping windows: interior overlap is
    rejected with `ERR_LICENSE_WINDOW_OVERLAP` (HTTP 409), while pure adjacency —
    one window's `window_end` equaling the other's `window_start` — is permitted
    under the half-open semantics of §2.11."
    PRD §3.7: "Only `ACTIVE` exclusive agreements are consulted, and agreements
    without the exclusive flag never conflict with anything."

    Design: Difficulty/resource_temporal_overlap/license_exclusivity_half_open_adjacency_allowed
    """
    set_clock(CLOCK_SEP_05)
    create_license_agreement(
        work_title="Treatise One", author_name="Author A", exclusive=True,
        per_view_fee_cents=45, window_start="2026-01-01", window_end="2027-01-01",
    )
    other_area = api.create_license_agreement(
        license_agreement_payload(
            work_title="Treatise Four", author_name="Author D", practice_area="TAX",
            exclusive=True, per_view_fee_cents=60,
            window_start="2026-06-01", window_end="2026-12-01",
        ),
        _LICENSING,
    )
    data = validate_success(other_area, 201)
    assert data["practice_area"] == "TAX", (
        "exclusivity is scoped per practice_area: a TAX window overlapping the "
        "LITIGATION window is accepted"
    )
