"""Endpoint surfaces: the registry read/list envelope, cross-reference bodies,
the computed recoupment projection and the revenue-eligibility gate.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_common_fields,
    assert_fields_equal,
    assert_ids,
    assert_instant_format,
    assert_integer_cents,
    assert_payment_components,
)
from test_helpers.constants import (
    FUNCTION_DUAL,
    UNKNOWN_ENGAGEMENT_ID,
)
from test_helpers.fixtures import (
    accept_milestone,
    activate,
    authorize_payment,
    create_engagement,
    payment_of_milestone,
    setup_registry,
    setup_single_alpha,
)
from test_helpers.test_users import make_developer_headers


def test_corner_publisher_user_registry_is_create_read_list_only_with_a_paginated_envelope(api):
    """The publisher-user registry offers creation, individual reads and a
    paginated list, and the list read is closed to the Developer role.

    PRD §4 publishes `POST /publisher-users` for `PlatformAdmin` only, and of
    `GET /publisher-users/{id}` it says "Developers have no visibility into
    publisher staffing", listing only "PlatformAdmin, PublisherReviewer,
    PublisherFinance" — so a Developer actor is outside the authorized-role list
    and PRD §2.2 answers `ERR_ROLE_NOT_PERMITTED` (403). PRD §2.3 fixes the
    envelope: "Every list response repeats `limit` and `offset` in the `meta`
    object alongside `total_count`, the number of records matching the filter
    before pagination is applied, and `has_more`, a boolean that is true when
    records remain beyond the current window."

    Design: Corner/endpoints/corner_publisher_user_registry_create_read_and_paginated_list
    """
    reg = setup_registry(api)

    created = validate_success(
        api.create_publisher_user(
            f.publisher_user_payload(reg.publisher_id, "Dov Dual", FUNCTION_DUAL),
            reg.admin,
        ),
        expected_status=201,
    )
    assert_fields_equal(
        created,
        {
            "publisher_id": reg.publisher_id,
            "display_name": "Dov Dual",
            "function": FUNCTION_DUAL,
            "version": 1,
        },
        "publisher user",
    )
    assert_common_fields(created, "publisher user")
    assert is_valid_uuid(created["id"]), created["id"]
    assert_instant_format(created["created_at"], "publisher_user.created_at")
    assert_instant_format(created["updated_at"], "publisher_user.updated_at")
    dual_id = created["id"]

    # No mutation surface exists, so the individual read is the creation payload.
    fetched = validate_success(api.get_publisher_user(dual_id, reg.finance))
    assert fetched == created, f"read differs from creation: {fetched} vs {created}"

    first_rows, first_meta = validate_paginated(
        api.list_publisher_users(reg.admin, {"limit": 2, "offset": 0})
    )
    assert len(first_rows) == 2, f"expected 2 rows in the first window, got {len(first_rows)}"
    assert first_meta["total_count"] == 3, first_meta
    assert first_meta["has_more"] is True, first_meta

    second_rows, second_meta = validate_paginated(
        api.list_publisher_users(reg.admin, {"limit": 2, "offset": 2})
    )
    assert len(second_rows) == 1, f"expected 1 row in the second window, got {len(second_rows)}"
    assert second_meta["total_count"] == 3, second_meta
    assert second_meta["has_more"] is False, second_meta

    paged_ids = [row["id"] for row in first_rows] + [row["id"] for row in second_rows]
    assert len(set(paged_ids)) == 3, f"pagination repeated a row: {paged_ids}"
    assert_ids(
        first_rows + second_rows,
        [reg.reviewer_id, reg.finance_id, dual_id],
        "publisher users",
    )

    validate_error(
        api.get_publisher_user(dual_id, make_developer_headers(reg.studio_id)),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )


def test_corner_invoice_body_foreign_key_must_resolve_before_the_invoice_is_written(api):
    """An invoice naming an unknown engagement is refused with 404 and nothing is
    written; the resolvable invoice appears on the engagement's sub-collection.

    PRD §2.10 rule 19 requires that "Every foreign key in the request body
    resolves, left to right, on every creation endpoint that carries one", and
    PRD §2.9 pins the answer: "invoice creation resolves `engagement_id` to
    `ERR_ENGAGEMENT_NOT_FOUND` ... Every one of these is HTTP 404." PRD §3.8
    fixes the birth status of a resolvable invoice — "New invoices land in
    `SUBMITTED`" — and PRD §4 exposes
    `GET /contractor-engagements/{id}/invoices`, the only route that reads the
    association from the engagement's side.

    Design: Corner/endpoints/corner_invoice_links_to_engagement_only_when_the_engagement_exists
    """
    scenario = setup_single_alpha(api)
    reg = scenario.reg
    engagement = create_engagement(
        reg, scenario.m1["id"], "ART-QUILL", 400000, "2026-08-01", "2026-08-31"
    )
    assert engagement["status"] == "ACTIVE", engagement

    before = get_success_data(api.list_engagement_invoices(engagement["id"], reg.dev))
    assert before == [], f"engagement started with invoices: {before}"

    validate_error(
        api.create_invoice(
            f.invoice_payload(UNKNOWN_ENGAGEMENT_ID, "QUILL-001", 150000, "2026-08-31"),
            reg.dev,
        ),
        "ERR_ENGAGEMENT_NOT_FOUND",
        404,
    )
    still_empty = get_success_data(api.list_engagement_invoices(engagement["id"], reg.dev))
    assert still_empty == [], f"the refused invoice was written: {still_empty}"

    created = validate_success(
        api.create_invoice(
            f.invoice_payload(engagement["id"], "QUILL-001", 150000, "2026-08-31"),
            reg.dev,
        ),
        expected_status=201,
    )
    assert_fields_equal(
        created,
        {
            "engagement_id": engagement["id"],
            "invoice_number": "QUILL-001",
            "amount_cents": 150000,
            "period_end_date": "2026-08-31",
            "status": "SUBMITTED",
            "decided_at": None,
            "rejection_reason": None,
        },
        "invoice",
    )
    assert_integer_cents(created["amount_cents"], "invoice.amount_cents")

    rows = get_success_data(api.list_engagement_invoices(engagement["id"], reg.dev))
    assert len(rows) == 1, f"expected exactly one invoice on the engagement, got {rows}"
    assert rows[0]["id"] == created["id"], rows

    read_back = validate_success(api.get_invoice(created["id"], reg.dev))
    assert_fields_equal(
        read_back,
        {"invoice_number": "QUILL-001", "amount_cents": 150000, "status": "SUBMITTED"},
        "invoice read",
    )

    # Nothing was approved, so the engagement's incurred basis is untouched.
    after = validate_success(api.get_engagement(engagement["id"], reg.dev))
    assert after["approved_invoice_total_cents"] == 0, after


def test_corner_recoupment_summary_projects_the_authorized_payment_ledger(api):
    """The computed recoupment read shows `PRE_RECOUP` with nothing disbursed, and
    the same read after authorization shows the net advance and `RECOUPING`.

    PRD §3.9 lists the payload verbatim: "A separate computed read exposes the
    whole recoupment and rights position of an agreement in one payload:
    `agreement_id`, `funding_pool_cents`, `advance_disbursed_cents`,
    `advance_recouped_cents`, `unrecouped_advance_cents`,
    `royalties_paid_to_date_cents`, `recoupment_state`,
    `accepted_milestone_ratio`, `ip_reversion_state`, `sequel_rights_holder`,
    `post_launch_support_state` and `live_ops_drawn_cents`." PRD §3.6 fixes the
    posting: "Step one adds `net_amount_cents` to `advance_disbursed_cents` and
    `holdback_cents` to `holdback_reserve_cents`. Step two ... recomputes
    `unrecouped_advance_cents` as `advance_disbursed_cents` less
    `advance_recouped_cents`, and moves `recoupment_state` from `PRE_RECOUP` to
    `RECOUPING` as soon as `advance_disbursed_cents` is greater than zero".

    Design: Corner/endpoints/corner_recoupment_summary_reflects_the_authorized_payment_ledger
    """
    scenario = setup_single_alpha(api)
    reg = scenario.reg
    accept_milestone(reg, scenario.m1["id"])

    before = validate_success(api.get_recoupment_summary(scenario.agreement_id, reg.finance))
    assert_fields_equal(
        before,
        {
            "agreement_id": scenario.agreement_id,
            "funding_pool_cents": 3600000,
            "advance_disbursed_cents": 0,
            "advance_recouped_cents": 0,
            "unrecouped_advance_cents": 0,
            "royalties_paid_to_date_cents": 0,
            "recoupment_state": "PRE_RECOUP",
            "ip_reversion_state": "NONE",
            "sequel_rights_holder": "PUBLISHER",
            "post_launch_support_state": "PENDING",
            "live_ops_drawn_cents": 0,
        },
        "recoupment summary",
    )
    # PRD §3.9 lists `accepted_milestone_ratio` among the payload's fields, so the key
    # must be present and numeric. Its value is not asserted here: PRD §3.9 writes the
    # ratio only as part of the rights settlement "evaluated both at termination and at
    # completion", and this agreement's single ALPHA milestone triggers neither — which
    # is also why `ip_reversion_state` is still `NONE` above.
    assert "accepted_milestone_ratio" in before, before
    assert isinstance(before["accepted_milestone_ratio"], (int, float)), before

    payment = payment_of_milestone(reg, scenario.m1["id"])
    assert payment["status"] == "PENDING_AUTHORIZATION", payment
    authorized = authorize_payment(reg, payment["id"], "advance on acceptance")
    assert authorized["status"] == "AUTHORIZED", authorized
    assert authorized["authorized_by_user_id"] == reg.finance_id, authorized
    assert_instant_format(authorized["authorized_at"], "payment.authorized_at")
    assert_payment_components(authorized, 3600000, 0, 3600000, 500, 180000, 3420000)

    after = validate_success(api.get_recoupment_summary(scenario.agreement_id, reg.finance))
    assert_fields_equal(
        after,
        {
            "agreement_id": scenario.agreement_id,
            "funding_pool_cents": 3600000,
            "advance_disbursed_cents": 3420000,
            "advance_recouped_cents": 0,
            "unrecouped_advance_cents": 3420000,
            "royalties_paid_to_date_cents": 0,
            "recoupment_state": "RECOUPING",
            "ip_reversion_state": "NONE",
            "sequel_rights_holder": "PUBLISHER",
            "post_launch_support_state": "PENDING",
            "live_ops_drawn_cents": 0,
        },
        "recoupment summary",
    )
    for field in ("advance_disbursed_cents", "unrecouped_advance_cents"):
        assert_integer_cents(after[field], f"summary.{field}")

    agreement = scenario.read_agreement()
    assert agreement["holdback_reserve_cents"] == 180000, agreement
    assert agreement["withheld_payment_cents"] == 0, agreement


def test_corner_royalty_statement_is_refused_until_the_agreement_is_revenue_eligible(api):
    """A `DRAFT` agreement has no reporting surface; once activated the same body
    creates a `DRAFT` statement carrying the provisional waterfall.

    PRD §3.9 says "the agreement must be revenue-eligible, meaning its `status`
    is `ACTIVE` or `COMPLETED`, since a `DRAFT`, `SUSPENDED` or `TERMINATED`
    agreement has no reporting surface and answers
    `ERR_AGREEMENT_NOT_REVENUE_ELIGIBLE`", and PRD §5 prices that error at 409.
    The figures follow PRD §3.9: the line's net is 1000000, its platform fee is
    3000 bps of that net, so `distributable_total_cents` is 700000; the cost cap
    is applied to a claim of 0 so `cost_deduction_cents` is 0;
    `recoupment_base_cents` is 700000; `recoup_applied_cents` is "the smaller of
    the agreement's `unrecouped_advance_cents` as observed at creation time and
    `recoupment_base_cents`", which is 0 with nothing disbursed;
    `royalty_base_cents` is 700000 and the per-line provisional royalty is 2500
    bps of it, 175000.

    Design: Corner/endpoints/corner_royalty_statement_is_allowed_only_on_a_revenue_eligible_agreement
    """
    scenario = setup_single_alpha(api, title="Ledgerline", activate_agreement=False)
    reg = scenario.reg
    lines = [f.revenue_line("PC-GLOBAL", 1000000, 0)]

    draft_agreement_row = scenario.read_agreement()
    assert draft_agreement_row["status"] == "DRAFT", draft_agreement_row
    validate_error(
        api.create_royalty_statement(
            f.royalty_statement_payload(
                scenario.agreement_id, "2027-Q1", draft_agreement_row["version"],
                lines, 0,
            ),
            reg.finance,
        ),
        "ERR_AGREEMENT_NOT_REVENUE_ELIGIBLE",
        409,
    )
    refused = get_success_data(
        api.list_agreement_royalty_statements(scenario.agreement_id, reg.finance)
    )
    assert refused == [], f"a statement was written on a DRAFT agreement: {refused}"

    activated = activate(reg, scenario.agreement_id)
    assert activated["status"] == "ACTIVE", activated
    assert activated["version"] > draft_agreement_row["version"], activated

    statement = validate_success(
        api.create_royalty_statement(
            f.royalty_statement_payload(
                scenario.agreement_id, "2027-Q1", activated["version"], lines, 0,
            ),
            reg.finance,
        ),
        expected_status=201,
    )
    assert_fields_equal(
        statement,
        {
            "agreement_id": scenario.agreement_id,
            "period_label": "2027-Q1",
            "state": "DRAFT",
            "recoupable_cost_cents": 0,
            "distributable_total_cents": 700000,
            "cost_deduction_cents": 0,
            "recoupment_base_cents": 700000,
            "recoup_applied_cents": 0,
            "royalty_base_cents": 700000,
            "provisional_royalty_payable_cents": 175000,
            "final_royalty_payable_cents": None,
            "finalized_at": None,
        },
        "royalty statement",
    )
    for field in (
        "distributable_total_cents",
        "recoupment_base_cents",
        "royalty_base_cents",
        "provisional_royalty_payable_cents",
    ):
        assert_integer_cents(statement[field], f"statement.{field}")

    rows = get_success_data(
        api.list_agreement_royalty_statements(scenario.agreement_id, reg.finance)
    )
    assert len(rows) == 1 and rows[0]["id"] == statement["id"], rows

    summary = validate_success(
        api.get_recoupment_summary(scenario.agreement_id, reg.finance)
    )
    assert summary["royalties_paid_to_date_cents"] == 0, summary
    assert summary["recoupment_state"] == "PRE_RECOUP", summary
