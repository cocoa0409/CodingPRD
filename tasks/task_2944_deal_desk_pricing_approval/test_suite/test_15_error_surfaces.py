"""Exception-acceptance floors and the two ownership rejections."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_line,
    assert_instant_equals,
    assert_paginated_list,
    assert_unset,
    create_grant,
    create_quote,
    exception_decision_payload,
    file_exception,
    generate_order_form,
    ids_of,
    read_account,
    read_exception,
    read_order_form,
    read_quote,
    revoke_grant,
    send_order_form,
    submit_quote,
    validate_error,
    USER_IDS,
)


def test_no_exception_can_buy_through_the_absolute_margin_floor(
    api, base, rep_headers, analyst_headers
):
    """PRD §3.5: "The quote's `final_margin_pct` must sit at or above the pinned revision's
    `absolute_margin_floor_pct`, because no exception can rescue a deal below the hard floor,
    otherwise `ERR_ABSOLUTE_MARGIN_FLOOR_BREACH`."
    PRD §3.5: "Filing an exception consumes no allowance whatsoever; only a decision does."

    Design: Corner/errors/exception_acceptance_below_the_absolute_margin_floor_is_rejected
    """
    quote = create_quote(
        api, base["account"]["id"], 12, rep_headers,
        title="Northwind Services Deep Cut", payment_terms_days=30,
    )
    line = add_line(api, quote["id"], base["service"]["id"], 10, 0.05, rep_headers)
    assert line["final_net_cents"] == 1900000

    rolled = read_quote(api, quote["id"], analyst_headers)
    assert rolled["final_net_total_cents"] == 1900000
    assert rolled["final_margin_pct"] == pytest.approx(0.210526, abs=1e-9)

    exception = file_exception(
        api, quote["id"], rep_headers,
        competitor_name="Helios Cloud",
        competitor_quoted_total_cents=1800000,
        evidence_reference="EV-2026-0801-C",
        justification="Aggressive services bid from Helios",
    )
    assert exception["status"] == "SUBMITTED"

    validate_error(
        api.decide_competitive_exception(
            exception["id"],
            exception_decision_payload("ACCEPT", "Attempting to bless the deep cut"),
            analyst_headers,
        ),
        ApiErrorId.ERR_ABSOLUTE_MARGIN_FLOOR_BREACH,
        422,
    )

    assert read_account(api, base["account"]["id"], analyst_headers)[
        "exception_allowance_used_cents"
    ] == 0
    refused = read_exception(api, quote["id"], exception["id"], analyst_headers)
    assert refused["status"] == "SUBMITTED"
    assert refused["allowance_consumed_cents"] == 0


def test_accepting_an_exception_on_a_healthy_quote_is_refused_as_not_needed(
    api, base, rep_headers, analyst_headers
):
    """PRD §3.5: "The quote's `final_margin_pct` must actually sit strictly below the pinned
    revision's `margin_floor_pct` — an exception on a healthy deal is refused with
    `ERR_EXCEPTION_NOT_NEEDED`."
    PRD §3.3: "it is the greater of the matrix level and 3 whenever some competitive exception on
    the quote is in `ACCEPTED` status, because an accepted exception always drags the deal up to at
    least the third level of authority"

    Design: Corner/errors/exception_acceptance_on_a_quote_above_the_floor_returns_exception_not_needed
    """
    quote = create_quote(
        api, base["account"]["id"], 12, rep_headers,
        title="Northwind Support At List", payment_terms_days=30,
    )
    add_line(api, quote["id"], base["support"]["id"], 10, 0.00, rep_headers)

    healthy = read_quote(api, quote["id"], analyst_headers)
    assert healthy["final_margin_pct"] == pytest.approx(0.800000, abs=1e-9)
    assert healthy["required_approval_level"] == 0

    exception = file_exception(
        api, quote["id"], rep_headers,
        competitor_name="Helios Cloud",
        competitor_quoted_total_cents=290000,
        evidence_reference="EV-2026-0801-D",
        justification="Filed defensively with no margin pressure",
    )

    validate_error(
        api.decide_competitive_exception(
            exception["id"], exception_decision_payload("ACCEPT", "Nothing to except"),
            analyst_headers,
        ),
        ApiErrorId.ERR_EXCEPTION_NOT_NEEDED,
        422,
    )

    assert read_exception(api, quote["id"], exception["id"], analyst_headers)["status"] == "SUBMITTED"
    assert read_quote(api, quote["id"], analyst_headers)["required_approval_level"] == 0


def test_only_the_owning_rep_may_send_the_order_form(
    api, base, rep_headers, other_rep_headers, analyst_headers
):
    """PRD §2.11: "The quote-owner operations are exactly `PATCH /quotes/{id}`,
    `POST /quote-lines`, `PATCH /quote-lines/{id}`, `DELETE /quote-lines/{id}`,
    `POST /quotes/{id}/submit`, `POST /quotes/{id}/reopen`, `POST /quotes/{id}/renegotiate`,
    `POST /nonstandard-terms`, `POST /competitive-exceptions`, `POST /order-forms` and
    `POST /order-forms/{id}/send`; the grantor check applies to
    `POST /delegation-grants/{id}/revoke`."
    PRD §3.9: "The owning `SalesRep` sends the form, moving it `GENERATED` to
    `OUT_FOR_SIGNATURE` and stamping `sent_at`"

    Design: Corner/errors/sending_an_order_form_as_a_non_owner_rep_is_rejected
    """
    quote = create_quote(
        api, base["account"]["id"], 12, rep_headers,
        title="Northwind Owner Only", payment_terms_days=30,
    )
    assert quote["owner_rep_user_id"] == USER_IDS["rep"]
    add_line(api, quote["id"], base["support"]["id"], 10, 0.00, rep_headers)
    approved = submit_quote(api, quote["id"], rep_headers)
    assert approved["status"] == "APPROVED"

    form = generate_order_form(
        api, quote["id"], approved["version"], rep_headers,
        signer_name="Dana Reeves", signer_email="dana.reeves@northwind.example",
    )
    assert form["status"] == "GENERATED"
    assert_unset(form, "sent_at")

    validate_error(
        api.send_order_form(form["id"], other_rep_headers),
        ApiErrorId.ERR_NOT_QUOTE_OWNER,
        403,
    )
    untouched = read_order_form(api, form["id"], analyst_headers)
    assert untouched["status"] == "GENERATED"
    assert_unset(untouched, "sent_at")

    sent = send_order_form(api, form["id"], rep_headers)
    assert sent["status"] == "OUT_FOR_SIGNATURE"
    assert_instant_equals(sent["sent_at"], "2026-08-01T00:00:00.000Z", "sent_at")


def test_only_the_granting_director_may_revoke_the_delegation(
    api, base, director_headers, other_director_headers
):
    """PRD §2.11: "`X-User-ID` equals `Quote.owner_rep_user_id` for quote-owner operations,
    otherwise `ERR_NOT_QUOTE_OWNER` (403); and `X-User-ID` equals `DelegationGrant.grantor_user_id`
    for grant revocation, otherwise `ERR_NOT_GRANT_GRANTOR` (403)."
    PRD §2.10: "A grant is created in `ACTIVE` status and leaves that status in exactly two ways:
    the grantor revokes it, moving it to `REVOKED` and stamping `revoked_at`; or the expiry sweep
    observes that the logical clock has reached `ends_at` and moves it to `EXPIRED`."

    Design: Corner/errors/revoking_another_directors_delegation_grant_is_rejected
    """
    grant = create_grant(
        api, USER_IDS["grantee_a"], 2, 0.20,
        "2026-08-10T00:00:00Z", "2026-08-20T00:00:00Z", director_headers,
    )
    assert grant["grantor_user_id"] == USER_IDS["director"]
    assert grant["status"] == "ACTIVE"

    validate_error(
        api.revoke_delegation_grant(grant["id"], other_director_headers),
        ApiErrorId.ERR_NOT_GRANT_GRANTOR,
        403,
    )

    still_active, _ = assert_paginated_list(
        api.list_delegation_grants(other_director_headers, {"status": "ACTIVE"}),
        expected_total=1,
    )
    assert ids_of(still_active) == [grant["id"]]

    revoked = revoke_grant(api, grant["id"], director_headers)
    assert revoked["status"] == "REVOKED"
    assert_instant_equals(revoked["revoked_at"], "2026-08-01T00:00:00.000Z", "revoked_at")
