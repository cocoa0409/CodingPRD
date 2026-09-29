"""Conditional submit gates, the stack cap and the cumulative exception allowance."""
import pytest

from test_helpers import (
    ApiErrorId,
    AUTO_APPROVED_REVIEWER_NOTE,
    add_line,
    add_term,
    assert_paginated_list,
    assert_unset,
    assess_revrec,
    create_desk_policy_with_matrix,
    create_quote,
    decide_exception,
    exception_decision_payload,
    file_exception,
    open_revrec,
    quote_line_payload,
    read_account,
    read_exception,
    read_quote,
    read_term,
    submit_quote,
    validate_error,
)


def test_a_sixty_day_quote_cannot_submit_until_a_matching_payment_terms_term_exists(
    api, base, rep_headers, analyst_headers
):
    """PRD §3.7: "If its `payment_terms_days` exceeds the pinned revision's
    `standard_payment_terms_days`, there must exist a non-standard term on this quote whose
    `term_category` is `PAYMENT_TERMS`, whose `requested_numeric_value` equals that same
    `payment_terms_days`, and whose `review_state` is either `PENDING` or `APPROVED`, otherwise
    `ERR_NONSTANDARD_TERM_REQUIRED`."
    PRD §3.7: "That last branch is the auto-approval path: when there are pending terms but the
    aggregate score falls short of the review threshold, every non-standard term on the quote
    whose `review_state` is `PENDING` is moved from `PENDING` to `APPROVED` in the same request,
    with `reviewed_at` stamped at the logical clock, `reviewed_by_user_id` left unset because no
    human decided it, and `reviewer_note` set to the fixed string
    `AUTO_APPROVED_BELOW_RISK_THRESHOLD`."

    Design: Corner/validations/submit_with_extended_payment_terms_and_no_matching_term_is_rejected
    """
    quote = create_quote(
        api, base["account"]["id"], 12, rep_headers,
        title="Northwind Net 60", payment_terms_days=60,
    )
    add_line(api, quote["id"], base["support"]["id"], 10, 0.00, rep_headers)

    validate_error(
        api.submit_quote(quote["id"], rep_headers),
        ApiErrorId.ERR_NONSTANDARD_TERM_REQUIRED,
        422,
    )
    assert read_quote(api, quote["id"], analyst_headers)["status"] == "DRAFT"

    term = add_term(api, quote["id"], "PAYMENT_TERMS", 60, rep_headers)
    assert term["severity_factor"] == pytest.approx(0.250000, abs=1e-9)
    assert term["risk_contribution"] == pytest.approx(5.00, abs=1e-9)
    assert term["review_state"] == "PENDING"
    assert term["requires_cfo_cosign"] is False

    submitted = submit_quote(api, quote["id"], rep_headers)
    assert submitted["status"] == "APPROVED"
    assert submitted["terms_risk_score_aggregate"] == pytest.approx(5.00, abs=1e-9)
    assert submitted["terms_risk_score_dominant"] == pytest.approx(6.25, abs=1e-9)

    settled = read_term(api, quote["id"], term["id"], rep_headers)
    assert settled["review_state"] == "APPROVED"
    assert settled["reviewer_note"] == AUTO_APPROVED_REVIEWER_NOTE
    assert_unset(settled, "reviewed_by_user_id")


def test_a_line_discount_above_the_stack_cap_is_refused_while_the_cap_itself_passes(
    api, base, rep_headers, analyst_headers
):
    """PRD §3.2: "A rep-requested discount above the pinned revision's `max_stack_discount_pct`
    is refused outright with `ERR_DISCOUNT_STACK_EXCEEDED`, and the same check applies when a
    line's discount is edited."

    Design: Corner/validations/line_discount_above_the_max_stack_cap_is_rejected
    """
    quote = create_quote(
        api, base["account"]["id"], 12, rep_headers,
        title="Northwind Stack Cap", payment_terms_days=30,
    )

    validate_error(
        api.create_quote_line(
            quote_line_payload(quote["id"], base["support"]["id"], 10, 0.50), rep_headers
        ),
        ApiErrorId.ERR_DISCOUNT_STACK_EXCEEDED,
        422,
    )
    assert_paginated_list(
        api.list_quote_lines(quote["id"], analyst_headers), expected_total=0
    )

    accepted = add_line(api, quote["id"], base["support"]["id"], 10, 0.45, rep_headers)
    assert accepted["extended_list_cents"] == 300000
    assert accepted["final_net_cents"] == 165000
    assert accepted["effective_stack_discount_pct"] == pytest.approx(0.450000, abs=1e-9)

    assert read_quote(api, quote["id"], analyst_headers)["final_net_total_cents"] == 165000


def test_the_second_exception_acceptance_that_would_overdraw_the_pool_is_refused(
    api, base, rep_headers, analyst_headers
):
    """PRD §3.5: "And the account must still have budget: the account's
    `exception_allowance_used_cents` plus this deal's margin give-up must not exceed the pinned
    revision's `exception_allowance_cents`, otherwise `ERR_EXCEPTION_ALLOWANCE_EXHAUSTED`."
    PRD §3.3: "The **margin give-up** is the pinned revision's `margin_floor_pct` less the
    quote's `final_margin_pct`, multiplied by `final_net_total_cents`, rounded half up to a whole
    cent."
    PRD §3.5: "It records the margin give-up figure into `allowance_consumed_cents`, and it moves
    the account's conserved pool upwards by exactly that amount. It then reaches back into the
    quote: `required_approval_level` is recomputed as the greater of the matrix level and 3, and
    `Quote.version` is incremented by one."

    Design: Corner/validations/exception_acceptance_exhausting_the_account_allowance_is_rejected
    """
    pilot = create_desk_policy_with_matrix(
        api, activate=True, name="FY26 Allowance Pilot", exception_allowance_cents=200000
    )
    assert pilot["policy"]["status"] == "ACTIVE"

    first, second = _two_services_quotes_pinning(api, base, pilot, rep_headers)
    assert first["desk_policy_id"] == pilot["policy"]["id"]

    exception_a = file_exception(
        api, first["id"], rep_headers,
        competitor_name="Helios Cloud",
        competitor_quoted_total_cents=1850000,
        evidence_reference="EV-2026-0801-A",
        justification="Displacing Helios on a services-led migration",
    )
    exception_b = file_exception(
        api, second["id"], rep_headers,
        competitor_name="Helios Cloud",
        competitor_quoted_total_cents=1850000,
        evidence_reference="EV-2026-0801-B",
        justification="Second phase of the same displacement",
    )

    accepted = decide_exception(
        api, exception_a["id"], "ACCEPT", analyst_headers, "First tranche approved"
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["allowance_consumed_cents"] == 200000
    assert read_account(api, base["account"]["id"], analyst_headers)[
        "exception_allowance_used_cents"
    ] == 200000

    validate_error(
        api.decide_competitive_exception(
            exception_b["id"], exception_decision_payload("ACCEPT", "Second tranche"),
            analyst_headers,
        ),
        ApiErrorId.ERR_EXCEPTION_ALLOWANCE_EXHAUSTED,
        422,
    )
    assert read_account(api, base["account"]["id"], analyst_headers)[
        "exception_allowance_used_cents"
    ] == 200000

    refused = read_exception(api, second["id"], exception_b["id"], analyst_headers)
    assert refused["status"] == "SUBMITTED"
    assert refused["allowance_consumed_cents"] == 0

    assert read_quote(api, first["id"], analyst_headers)["required_approval_level"] == 3
    assert read_quote(api, second["id"], analyst_headers)["required_approval_level"] == 0


def _two_services_quotes_pinning(api, base, pilot, rep_headers):
    quotes = []
    for title in ("Northwind Services Alpha", "Northwind Services Beta"):
        quote = create_quote(
            api, base["account"]["id"], 12, rep_headers,
            title=title, payment_terms_days=30,
        )
        add_line(api, quote["id"], base["service"]["id"], 10, 0.00, rep_headers)
        quotes.append(read_quote(api, quote["id"], rep_headers))
    return quotes[0], quotes[1]


def test_a_multi_element_quote_cannot_submit_until_its_assessment_is_cleared(
    api, base, rep_headers, accountant_headers
):
    """PRD §3.6: "Submission requires either that the quote's `arrangement_type` be
    `SINGLE_ELEMENT` or that some assessment on the quote be in `CLEARED` status, refusing
    otherwise with `ERR_REVREC_NOT_CLEARED`."
    PRD §3.6: "In every other case — two or more distinct categories with no usage-metered line
    — it is `MULTI_ELEMENT`."

    Design: Corner/validations/submit_of_a_multi_element_quote_without_cleared_revrec_is_rejected
    """
    quote = create_quote(
        api, base["account"]["id"], 12, rep_headers,
        title="Northwind Platform Plus Services", payment_terms_days=30,
    )
    add_line(api, quote["id"], base["core"]["id"], 10, 0.00, rep_headers)
    add_line(api, quote["id"], base["service"]["id"], 1, 0.00, rep_headers)

    assessment = open_revrec(api, quote["id"], accountant_headers)
    assert assessment["status"] == "ASSESSED"
    assert assessment["arrangement_type"] == "MULTI_ELEMENT"
    assert assessment["allocable_amount_cents"] == 1400000

    validate_error(
        api.submit_quote(quote["id"], rep_headers),
        ApiErrorId.ERR_REVREC_NOT_CLEARED,
        422,
    )

    cleared = assess_revrec(api, assessment["id"], "CLEAR", accountant_headers, "Allocation reviewed")
    assert cleared["status"] == "CLEARED"

    submitted = submit_quote(api, quote["id"], rep_headers)
    assert submitted["required_approval_level"] == 0
    assert submitted["status"] == "APPROVED"
    assert read_quote(api, quote["id"], rep_headers)["status"] == "APPROVED"
