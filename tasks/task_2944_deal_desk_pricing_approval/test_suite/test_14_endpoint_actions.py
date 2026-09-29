"""Supersede-on-generate, the expiry sweep report and the read-only pricing preview."""
import pytest

from test_helpers import (
    VOID_REASON_SUPERSEDED,
    add_line,
    assert_instant_equals,
    assert_paginated_list,
    assert_unset,
    create_grant,
    create_quote,
    generate_order_form,
    ids_of,
    read_order_form,
    read_pricing_preview,
    read_quote,
    run_expiry_sweep,
    set_clock,
    submit_quote,
    USER_IDS,
)


def test_generating_a_second_order_form_voids_the_first_as_superseded(
    api, base, rep_headers, analyst_headers
):
    """PRD §3.9: "Generation increments `Quote.version` by one and then records
    `generated_from_quote_version` as the **incremented** value, so a freshly generated form
    always matches its quote exactly while any later write to the quote leaves the form behind."
    PRD §3.9: "Generation also voids the previous paperwork: every existing order form of the same
    quote whose `status` is `GENERATED` or `OUT_FOR_SIGNATURE` moves to `VOID`, with `voided_at`
    stamped and `void_reason` set to the fixed string `SUPERSEDED_BY_NEW_ORDER_FORM`."

    Design: Corner/endpoints/regenerating_an_order_form_supersedes_the_previous_generated_form
    """
    quote = create_quote(
        api, base["account"]["id"], 12, rep_headers,
        title="Northwind Reissue", payment_terms_days=30,
    )
    add_line(api, quote["id"], base["support"]["id"], 10, 0.00, rep_headers)
    approved = submit_quote(api, quote["id"], rep_headers)
    assert approved["status"] == "APPROVED"

    first = generate_order_form(
        api, quote["id"], approved["version"], rep_headers,
        signer_name="Dana Reeves", signer_email="dana.reeves@northwind.example",
    )
    assert first["status"] == "GENERATED"
    after_first = read_quote(api, quote["id"], analyst_headers)
    assert first["generated_from_quote_version"] == after_first["version"]

    second = generate_order_form(
        api, quote["id"], after_first["version"], rep_headers,
        signer_name="Dana Reeves", signer_email="dana.reeves@northwind.example",
    )
    assert second["status"] == "GENERATED"
    after_second = read_quote(api, quote["id"], analyst_headers)
    assert second["generated_from_quote_version"] == after_second["version"]

    superseded = read_order_form(api, first["id"], analyst_headers)
    assert superseded["status"] == "VOID"
    assert superseded["void_reason"] == VOID_REASON_SUPERSEDED
    assert_instant_equals(superseded["voided_at"], "2026-08-01T00:00:00.000Z", "voided_at")

    assert_paginated_list(
        api.list_quote_order_forms(quote["id"], analyst_headers), expected_total=2
    )


def test_the_expiry_sweep_reports_only_the_delegation_grant_it_expired(
    api, base, director_headers, admin_headers
):
    """PRD §3.8: "Separately, every delegation grant still in `ACTIVE` whose `ends_at` the logical
    clock has reached — at or past, since the window's upper bound is exclusive — moves `ACTIVE`
    to `EXPIRED`; nothing else about that grant or its already-decided steps changes, and any
    later attempt to decide a step under it is refused with `ERR_DELEGATION_NOT_ACTIVE`."
    PRD §3.8: "The sweep answers with `swept_at`, `expired_quote_ids`,
    `expired_delegation_grant_ids`, `voided_order_form_ids` and `released_exception_ids`."

    Design: Corner/endpoints/expiry_sweep_reports_every_delegation_grant_it_expired
    """
    grant = create_grant(
        api, USER_IDS["grantee_a"], 2, 0.20,
        "2026-08-01T00:00:00Z", "2026-08-05T00:00:00Z", director_headers,
    )
    assert grant["status"] == "ACTIVE"

    set_clock(api, "2026-08-05T00:00:00Z")
    swept = run_expiry_sweep(api, admin_headers)
    assert_instant_equals(swept["swept_at"], "2026-08-05T00:00:00.000Z", "swept_at")
    assert swept["expired_delegation_grant_ids"] == [grant["id"]]
    assert swept["expired_quote_ids"] == []
    assert swept["voided_order_form_ids"] == []
    assert swept["released_exception_ids"] == []

    listed, _ = assert_paginated_list(
        api.list_delegation_grants(director_headers, {"status": "EXPIRED"}),
        expected_total=1,
    )
    assert ids_of(listed) == [grant["id"]]
    assert listed[0]["status"] == "EXPIRED"
    assert_unset(listed[0], "revoked_at")


def test_the_pricing_preview_computes_both_passes_without_touching_the_quote(
    api, base, rep_headers, analyst_headers
):
    """PRD §3.3: "Any reader may also ask for a **pricing preview** on a quote, a purely computed
    read that mutates nothing and returns both passes side by side: `list_total_cents`,
    `cost_total_cents`, `provisional_net_total_cents`, `final_net_total_cents`,
    `provisional_blended_discount_pct`, `final_blended_discount_pct`, `provisional_margin_pct`,
    `final_margin_pct`, `volume_rebate_cents`, `payment_terms_uplift_cents`,
    `required_approval_level`, both risk scores in `terms_risk_score_aggregate` and
    `terms_risk_score_dominant`, the `arrangement_type`, the revenue-allocation figures
    `usage_excluded_cents`, `allocable_amount_cents` and `allocation_residual_cents`, the
    `margin_give_up_cents` the deal would cost in allowance, and a `lines` array carrying the
    per-line figures."
    PRD §3.3: "the **matrix level** is the `tier_level` of the single band of the pinned revision
    whose `min_discount_pct` is at or below that figure and whose `max_discount_pct` is strictly
    above it."

    Design: Corner/endpoints/pricing_preview_is_a_read_only_computed_view_of_both_variants
    """
    quote = create_quote(
        api, base["account"]["id"], 12, rep_headers,
        title="Northwind Preview Only", payment_terms_days=30,
    )
    add_line(api, quote["id"], base["core"]["id"], 10, 0.10, rep_headers)

    before = read_quote(api, quote["id"], analyst_headers)
    assert before["status"] == "DRAFT"
    assert before["final_net_total_cents"] == 1080000

    preview = read_pricing_preview(api, quote["id"], analyst_headers)
    assert preview["list_total_cents"] == 1200000
    assert preview["cost_total_cents"] == 300000
    assert preview["provisional_net_total_cents"] == 1080000
    assert preview["final_net_total_cents"] == 1080000
    assert preview["provisional_blended_discount_pct"] == pytest.approx(0.100000, abs=1e-9)
    assert preview["final_blended_discount_pct"] == pytest.approx(0.100000, abs=1e-9)
    assert preview["final_margin_pct"] == pytest.approx(0.722222, abs=1e-9)
    assert preview["required_approval_level"] == 1
    assert preview["arrangement_type"] == "SINGLE_ELEMENT"

    after = read_quote(api, quote["id"], analyst_headers)
    assert after["version"] == before["version"]
    assert after["status"] == before["status"]
    assert after["status"] == "DRAFT"
