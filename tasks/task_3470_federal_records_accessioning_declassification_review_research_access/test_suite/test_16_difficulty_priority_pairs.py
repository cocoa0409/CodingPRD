"""Difficulty coverage (queue A): validation-priority pairs — when two
rungs of the §2.6 ladder are both violated, the earlier rung's error is the
one returned; and each later rung still fires when the earlier one passes."""

import test_helpers as th

E = th.ApiErrorId


def test_appeal_state_beats_window_temporal(api):
    """PRD §2.6: "Every request is adjudicated against a fixed ladder of
    checks. A request that fails a rung is rejected with that rung's error, and
    no later rung is evaluated."
    PRD §2.6: "8. **From-state validity.** The target resource must be in a
    valid from-state for the requested transition."
    PRD §2.6: "13. **Temporal gates.** Time-gate checks against the logical
    clock: `ERR_TRANSFER_LAG_NOT_ELAPSED`, `ERR_SYSTEMATIC_REVIEW_PREMATURE`,
    `ERR_COOLING_PERIOD_ACTIVE`, `ERR_APPEAL_WINDOW_CLOSED`, and
    `ERR_VISIT_DATE_OUT_OF_WINDOW` (all 409)."
    PRD §3.9: "The owning `Researcher` appeals a request in `PARTIAL_GRANT` or
    `DENIED` (`ERR_OWNERSHIP_MISMATCH` for anyone else;
    `ERR_APPEAL_NOT_ALLOWED_STATE`, 409, from any other status), supplying an
    `appeal_reason`."

    Design: Difficulty/priority_pair_validation_conflict/appeal_state_beats_window_temporal
    """
    th.set_clock()
    bundle = th.setup_classified_collection(classification_default="SECRET")
    ada = th.create_active_researcher()
    foia = th.create_foia(ada, bundle["collection"], "full case file")
    foia = th.adjudicate_foia(foia, "GRANT")  # decided_at = startup clock

    # GRANTED is not an appealable state AND the 30-day window has closed;
    # the from-state rung (8) fires before the temporal rung (13).
    th.set_clock("2026-10-15T00:00:00Z")
    resp = api.appeal_foia_request(
        foia["id"], th.appeal_payload("too late and wrong state"),
        headers=th.make_researcher_headers(ada["id"]),
    )
    assert resp.status_code == 409
    th.validate_error(resp, E.ERR_APPEAL_NOT_ALLOWED_STATE)


def test_appeal_window_temporal_fires_when_state_valid(api):
    """PRD §3.9: "The appeal window is thirty days: the appeal must arrive
    while the clock stands at or before `decided_at` plus 30 days, with the
    boundary inclusive — an appeal at exactly the thirtieth day is timely, and
    one a day later is rejected with `ERR_APPEAL_WINDOW_CLOSED` (409)."
    PRD §2.6: "Every request is adjudicated against a fixed ladder of checks.
    A request that fails a rung is rejected with that rung's error, and no
    later rung is evaluated."

    Design: Difficulty/priority_pair_validation_conflict/appeal_state_beats_window_temporal
    """
    th.set_clock()
    bundle = th.setup_classified_collection(classification_default="SECRET")
    ada = th.create_active_researcher()
    foia = th.create_denied_foia(ada, bundle["collection"], ["B1"])  # appealable

    # DENIED passes the from-state rung, so the temporal rung decides.
    th.set_clock("2026-10-02T00:00:00Z")  # decided_at + 31 days
    resp = api.appeal_foia_request(
        foia["id"], th.appeal_payload("one day late"),
        headers=th.make_researcher_headers(ada["id"]),
    )
    assert resp.status_code == 409
    th.validate_error(resp, E.ERR_APPEAL_WINDOW_CLOSED)


def test_restriction_safety_beats_quota_fiscal(api):
    """PRD §2.6: "Every request is adjudicated against a fixed ladder of
    checks. A request that fails a rung is rejected with that rung's error, and
    no later rung is evaluated."
    PRD §2.6: "10. **Restriction-posture gates.** Operations that require the
    records to be open check `restriction_posture` here
    (`ERR_COLLECTION_RESTRICTED`, 403)."
    PRD §2.6: "17. **Fiscal and quota rules.** The daily reproduction-page
    quota and the paid-before-fulfilled requirement
    (`ERR_DAILY_PAGE_LIMIT_EXCEEDED`, `ERR_REPRO_NOT_PAID`)."
    PRD §3.8: "The same described-and-open gates as pulls apply in ladder
    order: the researcher must be `ACTIVE` (`ERR_RESEARCHER_NOT_ACTIVE`), the
    collection's posture must be `PUBLIC` (`ERR_COLLECTION_RESTRICTED`), and
    its `processing_status` must be `DESCRIBED` or `PUBLISHED`
    (`ERR_COLLECTION_NOT_DESCRIBED`)."

    Design: Difficulty/priority_pair_validation_conflict/restriction_safety_beats_quota_fiscal
    """
    th.set_clock()
    agency = th.create_agency()
    public_bundle = th.setup_public_described_collection(
        agency=agency, schedule_kwargs={"schedule_number": "SCH-DOJ-002"}
    )
    classified_bundle = th.setup_classified_collection(
        agency=agency, classification_default="SECRET", described=True,
        schedule_kwargs={"schedule_number": "SCH-DOJ-001"},
    )
    bob = th.create_active_researcher(
        "Bob Press", "bob@example.org", "JOURNALIST", "PP-2002"
    )
    researcher = th.make_researcher_headers(bob["id"])

    # Exactly fill Bob's 200-page daily quota on the PUBLIC collection.
    big = th.validate_success(
        api.create_reproduction_request(
            th.reproduction_payload(bob["id"], public_bundle["collection"]["id"],
                                    200, "DIGITAL_SCAN"),
            headers=researcher,
        ),
        201,
    )
    assert big["status"] == "QUOTED"

    # The target is posture-restricted AND the quota is exhausted; the
    # restriction-posture rung (10) fires before the fiscal rung (17).
    resp = api.create_reproduction_request(
        th.reproduction_payload(bob["id"], classified_bundle["collection"]["id"],
                                10, "DIGITAL_SCAN"),
        headers=researcher,
    )
    assert resp.status_code == 403
    th.validate_error(resp, E.ERR_COLLECTION_RESTRICTED)


def test_quota_fiscal_fires_when_safety_passes(api):
    """PRD §3.8: "A daily quota protects the reproduction lab. Summed across
    the researcher's requests created on the same UTC calendar day as the
    logical clock and still counted — those in `QUOTED`, `PAID`, or `FULFILLED`
    status — the committed pages plus the new request's `page_count` must not
    exceed 200 pages, with the boundary inclusive: a request that brings the
    day to exactly 200 pages succeeds, and one page beyond is rejected with
    `ERR_DAILY_PAGE_LIMIT_EXCEEDED` (409)."
    PRD §2.6: "17. **Fiscal and quota rules.** The daily reproduction-page
    quota and the paid-before-fulfilled requirement
    (`ERR_DAILY_PAGE_LIMIT_EXCEEDED`, `ERR_REPRO_NOT_PAID`)."

    Design: Difficulty/priority_pair_validation_conflict/restriction_safety_beats_quota_fiscal
    """
    th.set_clock()
    bundle = th.setup_public_described_collection()
    bob = th.create_active_researcher(
        "Bob Press", "bob@example.org", "JOURNALIST", "PP-2002"
    )
    researcher = th.make_researcher_headers(bob["id"])
    collection_id = bundle["collection"]["id"]

    th.validate_success(
        api.create_reproduction_request(
            th.reproduction_payload(bob["id"], collection_id, 200, "DIGITAL_SCAN"),
            headers=researcher,
        ),
        201,
    )
    # The posture rung passes (PUBLIC), so the quota rung decides.
    resp = api.create_reproduction_request(
        th.reproduction_payload(bob["id"], collection_id, 1, "DIGITAL_SCAN"),
        headers=researcher,
    )
    assert resp.status_code == 409
    th.validate_error(resp, E.ERR_DAILY_PAGE_LIMIT_EXCEEDED)
