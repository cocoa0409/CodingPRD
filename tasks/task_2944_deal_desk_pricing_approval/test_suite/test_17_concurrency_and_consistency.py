"""Stale-version protection on the two guarded writes, and immediate repricing."""
import pytest

from test_helpers import (
    ApiErrorId,
    VOID_REASON_SUPERSEDED,
    add_line,
    assert_instant_equals,
    assert_paginated_list,
    assert_unset,
    create_quote,
    generate_order_form,
    order_form_payload,
    patch_line,
    read_order_form,
    read_pricing_preview,
    read_quote,
    renegotiate,
    renegotiate_payload,
    submit_quote,
    validate_error,
)


def test_renegotiating_on_a_stale_source_version_creates_no_clone(
    api, base, rep_headers, analyst_headers
):
    """PRD §2.9: "A `POST /quotes/{id}/renegotiate` request must carry `expected_quote_version` as
    a required, non-optional body field holding the client's last observed `version` of the source
    quote. If that value does not equal the source quote's current `version`, the clone is refused
    with `ERR_STALE_QUOTE_VERSION` (HTTP 412) and no clone is created."
    PRD §3.8: "A successful clone is created as a brand-new quote in `DRAFT` with
    `renegotiated_from_quote_id` naming the source quote, with a copy of every one of the source's
    lines, and with its own `expires_at` computed from the clone's own `created_at` and the pinned
    validity period."

    Design: Corner/cross_cutting_complexity_layers/renegotiate_with_a_stale_expected_quote_version_is_rejected
    """
    source = create_quote(
        api, base["account"]["id"], 12, rep_headers,
        title="Northwind Round One", payment_terms_days=30,
    )
    stale_version = source["version"]
    add_line(api, source["id"], base["core"]["id"], 10, 0.10, rep_headers)

    refreshed = read_quote(api, source["id"], analyst_headers)
    assert refreshed["version"] != stale_version
    assert refreshed["renegotiation_count"] == 0

    validate_error(
        api.renegotiate_quote(
            source["id"], renegotiate_payload(stale_version, term_months=24), rep_headers
        ),
        ApiErrorId.ERR_STALE_QUOTE_VERSION,
        412,
    )
    assert_paginated_list(
        api.list_quotes(analyst_headers, {"renegotiated_from_quote_id": source["id"]}),
        expected_total=0,
    )

    clone = renegotiate(api, source["id"], refreshed["version"], rep_headers, term_months=24)
    assert clone["status"] == "DRAFT"
    assert clone["renegotiated_from_quote_id"] == source["id"]
    assert clone["term_months"] == 24
    assert_instant_equals(clone["expires_at"], "2026-08-31T00:00:00.000Z", "expires_at")

    after = read_quote(api, source["id"], analyst_headers)
    assert after["renegotiation_count"] == 1
    assert after["status"] == "DRAFT"

    assert_paginated_list(
        api.list_quote_lines(clone["id"], analyst_headers), expected_total=1
    )


def test_replaying_the_expected_version_on_generation_is_refused_as_stale(
    api, base, rep_headers, analyst_headers
):
    """PRD §2.9: "The value is compared against the quote's `version` as observed before this
    request's own version bump; a mismatch is refused with `ERR_STALE_QUOTE_VERSION` (HTTP 412) and
    no form is generated."
    PRD §3.9: "Generation also voids the previous paperwork: every existing order form of the same
    quote whose `status` is `GENERATED` or `OUT_FOR_SIGNATURE` moves to `VOID`, with `voided_at`
    stamped and `void_reason` set to the fixed string `SUPERSEDED_BY_NEW_ORDER_FORM`."

    Design: Corner/cross_cutting_complexity_layers/order_form_generation_with_a_stale_expected_quote_version_is_rejected
    """
    quote = create_quote(
        api, base["account"]["id"], 12, rep_headers,
        title="Northwind Papering", payment_terms_days=30,
    )
    add_line(api, quote["id"], base["support"]["id"], 10, 0.00, rep_headers)
    approved = submit_quote(api, quote["id"], rep_headers)
    assert approved["status"] == "APPROVED"

    first = generate_order_form(
        api, quote["id"], approved["version"], rep_headers,
        signer_name="Dana Reeves", signer_email="dana.reeves@northwind.example",
    )
    assert first["status"] == "GENERATED"

    validate_error(
        api.create_order_form(
            order_form_payload(
                quote["id"], approved["version"],
                signer_name="Dana Reeves", signer_email="dana.reeves@northwind.example",
            ),
            rep_headers,
        ),
        ApiErrorId.ERR_STALE_QUOTE_VERSION,
        412,
    )
    survivor = read_order_form(api, first["id"], analyst_headers)
    assert survivor["status"] == "GENERATED"
    assert_unset(survivor, "void_reason")

    refreshed = read_quote(api, quote["id"], analyst_headers)
    second = generate_order_form(
        api, quote["id"], refreshed["version"], rep_headers,
        signer_name="Dana Reeves", signer_email="dana.reeves@northwind.example",
    )
    assert second["status"] == "GENERATED"
    assert second["generated_from_quote_version"] == read_quote(
        api, quote["id"], analyst_headers
    )["version"]

    superseded = read_order_form(api, first["id"], analyst_headers)
    assert superseded["status"] == "VOID"
    assert superseded["void_reason"] == VOID_REASON_SUPERSEDED


def test_a_line_edit_reprices_the_quote_for_the_very_next_read(
    api, base, rep_headers, analyst_headers
):
    """PRD §3.2: "Every line write — create, edit or delete — reprices **every** line on the quote
    rather than just the touched one, because a sibling line's presence and quantity can change
    another line's bundle eligibility; it then rolls the quote-level totals, increments
    `Quote.version` by one, and marks every revenue recognition assessment on the quote as stale."
    PRD §3.3: "All of the above is recomputed on every line create, line edit, line delete and
    header patch, and again at submit."

    Design: Corner/consistency_model/line_write_recomputes_quote_totals_visible_to_the_next_read
    """
    quote = create_quote(
        api, base["account"]["id"], 12, rep_headers,
        title="Northwind Immediate Totals", payment_terms_days=30,
    )
    line = add_line(api, quote["id"], base["core"]["id"], 10, 0.10, rep_headers)

    before = read_quote(api, quote["id"], analyst_headers)
    assert before["list_total_cents"] == 1200000
    assert before["final_net_total_cents"] == 1080000

    edited = patch_line(api, line["id"], rep_headers, quantity=20)
    assert edited["volume_tier_level_applied"] == 1
    assert edited["extended_list_cents"] == 2400000
    assert edited["extended_cost_cents"] == 600000
    assert edited["final_net_cents"] == 2160000

    after = read_quote(api, quote["id"], analyst_headers)
    assert after["list_total_cents"] == 2400000
    assert after["cost_total_cents"] == 600000
    assert after["final_net_total_cents"] == 2160000
    assert after["final_blended_discount_pct"] == pytest.approx(0.100000, abs=1e-9)
    assert after["final_margin_pct"] == pytest.approx(0.722222, abs=1e-9)

    preview = read_pricing_preview(api, quote["id"], analyst_headers)
    assert preview["final_net_total_cents"] == 2160000
    assert preview["final_margin_pct"] == pytest.approx(0.722222, abs=1e-9)
    assert preview["required_approval_level"] == 1
