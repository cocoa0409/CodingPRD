"""Document authoring, peer review, fact-check cycles, publication and embargo."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    api_client,
    advance_document_to_cleared,
    create_analyst,
    create_document,
    create_inclusion,
    create_vendor,
    finalize_inclusion,
    get_document,
    get_success_data,
    make_analyst_headers,
    make_vendor_rep_headers,
    publish_document,
    record_peer_verdict,
    respond_fact_check,
    revise_document,
    set_clock,
    setup_document_with_inclusion,
    setup_published_document,
    submit_for_review,
    validate_error,
    validate_success,
)

def _vendor_read(document, vendor):
    return api_client.get_document(document["id"], make_vendor_rep_headers(vendor["id"]))


def test_editorial_and_embargo_dimensions_evolve_independently():
    """PRD §3.6: "The embargo is a second, independent axis of the document's state.
    `embargo_status` begins at `EMBARGOED` and moves to the terminal `RELEASED` once
    the logical clock reaches `embargo_until` — the boundary is inclusive — with the
    transition evaluated on every read or write of the document".
    PRD §3.6: "A vendor read of a document whose `embargo_status` is `EMBARGOED` is
    refused with `ERR_EMBARGO_ACTIVE` (HTTP 403); other roles read the document
    normally."

    Design: Difficulty/non_linear_state_machine/document_editorial_and_embargo_parallel_dimensions
    """
    scenario = setup_published_document()
    document = get_document(scenario["document"])
    assert document["editorial_status"] == "PUBLISHED"
    assert document["embargo_status"] == "EMBARGOED"
    assert document["embargo_until"] == "2026-09-15T00:00:00Z"

    refused = _vendor_read(document, scenario["vendor"])
    validate_error(refused, ApiErrorId.ERR_EMBARGO_ACTIVE)

    set_clock("2026-09-14T23:59:59Z")
    still_refused = _vendor_read(document, scenario["vendor"])
    validate_error(still_refused, ApiErrorId.ERR_EMBARGO_ACTIVE)

    set_clock("2026-09-15T00:00:00Z")
    released = _vendor_read(document, scenario["vendor"])
    body = validate_success(released, expected_status=200)
    assert body["embargo_status"] == "RELEASED"
    assert body["editorial_status"] == "PUBLISHED", (
        "Releasing the embargo leaves the editorial dimension untouched"
    )
    assert body["embargo_until"] == "2026-09-15T00:00:00Z"


def test_unpublished_document_keeps_the_embargo_dimension_dormant():
    """PRD §3.6: "A document that has never been published keeps `embargo_status`
    `EMBARGOED` with `embargo_until` null, and the release rule applies only once
    `published_at` is set."
    PRD §3.6: "A vendor read of a document whose `embargo_status` is `EMBARGOED` is
    refused with `ERR_EMBARGO_ACTIVE` (HTTP 403); other roles read the document
    normally."

    Design: Difficulty/non_linear_state_machine/document_editorial_and_embargo_parallel_dimensions
    """
    set_clock("2026-09-01T00:00:00Z")
    lead = create_analyst()
    draft = create_document(lead)
    set_clock("2026-10-15T00:00:00Z")

    unchanged = get_document(draft)
    assert unchanged["editorial_status"] == "DRAFT"
    assert unchanged["embargo_status"] == "EMBARGOED"
    assert unchanged["embargo_until"] is None

    scenario = setup_published_document(publish=False)
    scenario["document"] = publish_document(scenario["document"])
    published = get_document(scenario["document"])
    assert published["embargo_status"] == "EMBARGOED"

    director_read = api_client.get_document(
        published["id"], TEST_USERS["research_director_headers"]
    )
    validate_success(director_read, expected_status=200)
    validate_error(_vendor_read(published, scenario["vendor"]), ApiErrorId.ERR_EMBARGO_ACTIVE)


def test_embargo_releases_at_the_exact_instant_and_not_one_second_early():
    """PRD §2.4: "An embargo releases once the clock reading reaches `embargo_until`;
    the boundary is inclusive."
    PRD §3.6: "A vendor read of a document whose `embargo_status` is `EMBARGOED` is
    refused with `ERR_EMBARGO_ACTIVE` (HTTP 403); other roles read the document
    normally."

    Design: Difficulty/boundary_precision_check/embargo_release_at_the_exact_instant
    """
    scenario = setup_published_document()
    document = get_document(scenario["document"])
    assert document["embargo_until"] == "2026-09-15T00:00:00Z"

    set_clock("2026-09-14T23:59:59Z")
    validate_error(_vendor_read(document, scenario["vendor"]), ApiErrorId.ERR_EMBARGO_ACTIVE)

    set_clock("2026-09-15T00:00:00Z")
    body = validate_success(_vendor_read(document, scenario["vendor"]), expected_status=200)
    assert body["embargo_status"] == "RELEASED"


def test_default_embargo_length_for_a_market_guide_releases_on_day_thirty():
    """PRD §3.5: "when it is omitted the length defaults by document type to 30 days
    for a `MARKET_GUIDE`"
    PRD §3.6: "computes `embargo_until` as `published_at` plus `embargo_days`, rolled
    forward to the following Monday at 00:00:00Z when that landing date falls on a
    Saturday or a Sunday."

    Design: Difficulty/boundary_precision_check/embargo_release_at_the_exact_instant
    """
    set_clock("2026-09-01T00:00:00Z")
    lead = create_analyst()
    reviewer = create_analyst(
        full_name="Ravi Menon", seniority="SENIOR", topic_routes=["CLOUD_COST"]
    )
    vendor = create_vendor()
    document = create_document(
        lead, title="Market Guide: Observability", doc_type="MARKET_GUIDE",
        omit_fields=["embargo_days"],
    )
    assert document["embargo_days"] == 30

    scenario = {"lead": lead, "reviewer": reviewer, "vendor": vendor, "document": document}
    scenario["inclusion"] = create_inclusion(document, vendor)
    scenario["document"] = advance_document_to_cleared(scenario)
    scenario["document"] = publish_document(scenario["document"])

    published = get_document(scenario["document"])
    assert published["embargo_until"] == "2026-10-01T00:00:00Z"

    set_clock("2026-09-30T23:59:59Z")
    validate_error(_vendor_read(published, vendor), ApiErrorId.ERR_EMBARGO_ACTIVE)

    set_clock("2026-10-01T00:00:00Z")
    body = validate_success(_vendor_read(published, vendor), expected_status=200)
    assert body["embargo_status"] == "RELEASED"


def test_new_document_starts_in_draft_with_the_embargo_dimension_embargoed():
    """PRD §3.5: "The document is created in `editorial_status` `DRAFT` and
    `embargo_status` `EMBARGOED`, with `peer_verdict` `NOT_ASSIGNED`,
    `peer_review_round` 0, `fact_check_open_count` 0, `included_vendor_count` 0,
    `placement_locked` false, `revision_count` 0, and `published_at` and
    `embargo_until` null."

    Design: Corner/state_machines/document_create_starts_in_draft_with_embargo_dimension_embargoed
    """
    set_clock("2026-09-01T00:00:00Z")
    lead = create_analyst()
    resp = api_client.create_document(
        {
            "title": "Hype Profile: Edge AI",
            "doc_type": "HYPE_PROFILE",
            "practice_area": "CIO_TECH",
            "lead_analyst_id": lead["id"],
        },
        make_analyst_headers(lead["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["editorial_status"] == "DRAFT"
    assert data["embargo_status"] == "EMBARGOED"
    assert data["embargo_until"] is None
    assert data["published_at"] is None
    assert data["peer_verdict"] == "NOT_ASSIGNED"
    assert data["peer_review_round"] == 0
    assert data["included_vendor_count"] == 0
    assert data["fact_check_open_count"] == 0
    assert data["embargo_days"] == 14


def test_revising_a_published_document_reopens_the_fact_check_round():
    """PRD §3.6: "Every inclusion on the document whose `inclusion_status` is
    `INCLUDED` or `APPEAL_UPHELD` is unlocked and re-checked: `placement_locked`
    becomes false, `fact_check_status` becomes `REQUESTED`, `fact_check_round` is
    incremented, `fact_check_requested_at` is stamped with the clock reading, and
    `fact_check_due_utc` is recomputed."
    PRD §3.6: "the document then moves immediately from `REVISED` to `FACT_CHECK`
    with its `version` incremented."

    Design: Corner/state_machines/document_revise_reopens_fact_check_rounds
    """
    scenario = setup_published_document()
    before = get_success_data(
        api_client.get_inclusion(scenario["inclusion"]["id"])
    )
    assert before["fact_check_round"] == 1
    assert before["placement_locked"] is True

    revised = revise_document(scenario["document"], scenario["lead"])
    assert revised["editorial_status"] == "FACT_CHECK"
    assert revised["revision_count"] == 1
    assert revised["fact_check_open_count"] == 1

    after = get_success_data(api_client.get_inclusion(scenario["inclusion"]["id"]))
    assert after["fact_check_round"] == 2
    assert after["fact_check_status"] == "REQUESTED"
    assert after["placement_locked"] is False


def test_fact_check_deadline_rolls_a_saturday_landing_to_monday():
    """PRD §2.8: "When a round is opened at an instant T, the raw deadline is T plus
    14 calendar days. If that date falls on a Saturday the deadline rolls forward by
    2 days; if it falls on a Sunday it rolls forward by 1 day; otherwise it stays.
    The deadline `fact_check_due_utc` is that date at 23:59:59Z."
    PRD §2.8: "A response is late exactly when `fact_check_response_at` is strictly
    after `fact_check_due_utc`; a response at the deadline itself is on time."

    Design: Corner/calculations/fact_check_deadline_rolls_a_weekend_landing_to_monday
    """
    set_clock("2026-09-05T00:00:00Z")
    scenario = setup_document_with_inclusion()
    finalize_inclusion(scenario["inclusion"], "INCLUDE")
    submit_for_review(scenario["document"], scenario["lead"], scenario["reviewer"])
    record_peer_verdict(scenario["document"], scenario["reviewer"], "APPROVE")

    opened = get_success_data(api_client.get_inclusion(scenario["inclusion"]["id"]))
    assert opened["fact_check_requested_at"] == "2026-09-05T00:00:00Z"
    assert opened["fact_check_due_utc"] == "2026-09-21T23:59:59Z", (
        "2026-09-19 is a Saturday, so the deadline rolls forward two days"
    )

    set_clock("2026-09-21T23:59:59Z")
    responded = respond_fact_check(
        scenario["inclusion"], scenario["vendor"], summary="On the deadline.",
        correction_offered=False,
    )
    assert responded["fact_check_status"] == "VENDOR_RESPONDED"
    assert responded["fact_check_late"] is False


def test_fact_check_cycle_lapses_strictly_after_the_due_instant():
    """PRD §3.5: "Once the logical clock is strictly after `fact_check_due_utc`, an
    inclusion still in `REQUESTED` moves to `LAPSED` with `fact_check_late` set to
    true and its `version` incremented".
    PRD §3.5: "A response that arrives after the cycle has already lapsed is refused
    with `ERR_FACT_CHECK_RESPONSE_LATE` (HTTP 409)."

    Design: Corner/calculations/fact_check_lapse_is_strictly_after_the_due_instant
    """
    set_clock("2026-09-01T00:00:00Z")
    scenario = setup_document_with_inclusion()
    finalize_inclusion(scenario["inclusion"], "INCLUDE")
    submit_for_review(scenario["document"], scenario["lead"], scenario["reviewer"])
    record_peer_verdict(scenario["document"], scenario["reviewer"], "APPROVE")

    opened = get_success_data(api_client.get_inclusion(scenario["inclusion"]["id"]))
    assert opened["fact_check_due_utc"] == "2026-09-15T23:59:59Z"

    set_clock("2026-09-16T00:00:00Z")
    lapsed = get_success_data(api_client.get_inclusion(scenario["inclusion"]["id"]))
    assert lapsed["fact_check_status"] == "LAPSED"
    assert lapsed["fact_check_late"] is True

    refused = api_client.respond_fact_check(
        scenario["inclusion"]["id"],
        {"response_summary": "One second too late.", "correction_offered": False},
        make_vendor_rep_headers(scenario["vendor"]["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_FACT_CHECK_RESPONSE_LATE)

    still_lapsed = get_success_data(api_client.get_inclusion(scenario["inclusion"]["id"]))
    assert still_lapsed["fact_check_status"] == "LAPSED"


def test_publishing_a_draft_document_is_refused():
    """PRD §3.6: "Publication is a `ResearchDirector` decision available once a
    document is `CLEARED`."
    PRD §2.11: "Target state: the resource named by the request is in a state from
    which the requested transition exists, and a resource in a terminal state rejects
    every further transition. Failure is `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/endpoints/document_publish_requires_cleared_state
    """
    set_clock("2026-09-01T00:00:00Z")
    lead = create_analyst()
    document = create_document(lead)

    resp = api_client.publish_document(document["id"], TEST_USERS["research_director_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    unchanged = get_document(document)
    assert unchanged["editorial_status"] == "DRAFT"
    assert unchanged["published_at"] is None
    assert unchanged["embargo_until"] is None


def test_reading_an_unknown_document_id_reports_document_not_found():
    """PRD §2.11: "A path identifier that matches no resource of its kind produces
    that entity's own not-found error, and the request never proceeds to evaluate
    later identifiers or body rules."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the
    specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/entities/document_get_with_unknown_id_returns_document_not_found
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api_client.get_document(NON_EXISTENT_UUID, TEST_USERS["research_director_headers"])
    error = validate_error(resp, ApiErrorId.ERR_DOCUMENT_NOT_FOUND)
    assert error["error_id"] == "ERR_DOCUMENT_NOT_FOUND"
    assert error["message"].strip()
