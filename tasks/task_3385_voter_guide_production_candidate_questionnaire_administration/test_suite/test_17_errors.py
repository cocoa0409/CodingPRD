"""Corner queue, errors section: catalog spot-check, isolated filing
deadline rejection, and the single-failure language gate."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_candidate_contest,
    build_locked_candidate_contest,
    create_edition,
    fresh_league,
    get_edition,
    get_success_data,
    make_filing_payload,
    set_clock,
    validate_error,
    validate_success,
)


def test_every_error_id_is_triggered_by_a_declared_surface(api, admin_headers):
    """PRD §2.7: "Only then are path identifiers resolved, strictly left to
    right, with the first unresolvable id producing `ERR_NOT_FOUND`" — the
    catalog spot check: an unknown cycle id resolves to ERR_NOT_FOUND.

    Design: Corner/errors/every_error_id_is_triggered_by_a_declared_surface
    """
    resp = api.get_cycle(NON_EXISTENT_UUID, admin_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert resp.status_code == 404


def test_filing_after_deadline_rejected(api):
    """PRD §3.2: "a filing at exactly the deadline is accepted, anything
    later is rejected with `ERR_FILING_DEADLINE_PASSED`".

    Design: Corner/errors/filing_after_deadline_rejected
    """
    ctx = fresh_league(api)
    contest = add_candidate_contest(api, ctx)
    set_clock(api, "2026-09-15T17:00:01Z")  # one second past the deadline
    resp = api.create_filing(
        contest["id"],
        make_filing_payload(candidate_name="Too Late", filing_reference="F-TL"),
        ctx["coordinator_h"],
    )
    validate_error(resp, ApiErrorId.ERR_FILING_DEADLINE_PASSED)
    assert resp.status_code == 422

    listed = get_success_data(
        api.list_filings(contest["id"], ctx["coordinator_h"])
    )
    assert listed == []


def test_language_unsupported_alone_rejected(api):
    """PRD §3.6: "The edition's `language_code` must appear in the
    `supported_language_codes` of every jurisdiction of the cycle
    (`ERR_LANGUAGE_UNSUPPORTED`)."

    Design: Corner/errors/language_unsupported_alone_rejected
    """
    # One LOCKED candidate contest, no measures anywhere, jurisdiction EN
    # only — the language gate is the single failing rule.
    sc = build_locked_candidate_contest(api, filings=())
    ctx = sc["ctx"]
    edition = create_edition(api, ctx, language_code="ES", channel="WEB")
    resp = api.transition_edition(edition["id"], {"to": "READY"},
                                  ctx["editor_h"])
    validate_error(resp, ApiErrorId.ERR_LANGUAGE_UNSUPPORTED)
    assert resp.status_code == 422
    assert get_edition(api, ctx, edition["id"])["status"] == "ASSEMBLING"
