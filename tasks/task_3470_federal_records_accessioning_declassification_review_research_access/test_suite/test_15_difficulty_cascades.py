"""Difficulty coverage (queue A): depth-3 transitive cascades — a release or
a declassification completion flips the collection posture to PUBLIC, and the
posture flip itself closes the collection's pending FOIA requests."""

import test_helpers as th


def _presidential_collection_with_pending_foia(api):
    """PRESIDENTIAL collection under a live P5 restriction (posture
    PRESIDENTIAL_HOLD), with the restriction's representative designated and
    the notification stamped at the startup clock."""
    th.set_clock()
    bundle = th.setup_presidential_collection()
    collection = bundle["collection"]
    restriction = th.impose_restriction(collection, "P5_CONFIDENTIAL_ADVICE")
    restriction = th.designate_representative(restriction, "rep-44")
    restriction = th.notify_restriction(restriction)
    return bundle, restriction


def test_presidential_release_posture_foia_cascade(api):
    """PRD §3.6: "Release moves the restriction to its terminal `RELEASED`
    status and stamps `released_at`. It then recomputes the collection's
    `restriction_posture` and advances the collection's `version`: when the
    released restriction was the last live one and no classification remains,
    the posture flips to `PUBLIC`, and the §2.8 posture-flip cascade closes
    the collection's pending FOIA requests with `close_reason` of
    `RECORDS_MADE_PUBLIC`."
    PRD §2.8: "On any recompute that changes a collection's posture into
    `PUBLIC`, every FOIA request against that collection still sitting in
    `RECEIVED` or `IN_REVIEW` is transitioned to `CLOSED` with `close_reason`
    set to `RECORDS_MADE_PUBLIC`, and each such request's `version`
    increments."

    Design: Difficulty/transitive_cascade/presidential_release_posture_foia_cascade
    """
    bundle, restriction = _presidential_collection_with_pending_foia(api)
    collection = bundle["collection"]
    assert th.read_collection(collection["id"])["restriction_posture"] == (
        "PRESIDENTIAL_HOLD"
    )

    ada = th.create_active_researcher()
    foia = th.create_foia(ada, collection, "advice memoranda 2001-2004")
    assert foia["status"] == "RECEIVED"

    version_before_release = th.current_collection_version(collection["id"])

    # Hop 1: the release itself (cooling period elapsed at +30 days).
    th.set_clock("2026-10-01T00:00:00Z")
    released = th.release_restriction(restriction)
    assert released["status"] == "RELEASED"
    assert th.same_instant(released["released_at"], "2026-10-01T00:00:00Z")

    # Hop 2: the collection posture recomputes into PUBLIC.
    collection_after = th.read_collection(collection["id"])
    assert collection_after["restriction_posture"] == "PUBLIC"
    assert collection_after["version"] > version_before_release

    # Hop 3: the posture flip auto-closes the pending FOIA request.
    foia_after = th.get_success_data(
        api.get_foia_request(foia["id"], headers=th.TEST_USERS["foia_officer_headers"])
    )
    assert foia_after["status"] == "CLOSED"
    assert foia_after["close_reason"] == "RECORDS_MADE_PUBLIC"


def test_presidential_release_cascade_closes_only_pending_requests(api):
    """PRD §2.8: "On any recompute that changes a collection's posture into
    `PUBLIC`, every FOIA request against that collection still sitting in
    `RECEIVED` or `IN_REVIEW` is transitioned to `CLOSED` with `close_reason`
    set to `RECORDS_MADE_PUBLIC`, and each such request's `version`
    increments."
    PRD §3.9: "`GRANTED`, `APPEAL_GRANTED`, `APPEAL_UPHELD`, and `CLOSED` are
    the terminal states."

    Design: Difficulty/transitive_cascade/presidential_release_posture_foia_cascade
    """
    bundle, restriction = _presidential_collection_with_pending_foia(api)
    collection = bundle["collection"]
    ada = th.create_active_researcher()
    bob = th.create_active_researcher(
        "Bob Press", "bob@example.org", "JOURNALIST", "PP-2002"
    )
    pending_a = th.create_foia(ada, collection, "pending request A")
    pending_b = th.create_foia(bob, collection, "pending request B")
    granted = th.create_foia(ada, collection, "already granted request")
    granted = th.adjudicate_foia(granted, "GRANT")
    assert granted["status"] == "GRANTED"

    th.set_clock("2026-10-01T00:00:00Z")
    th.release_restriction(restriction)

    reader = th.TEST_USERS["foia_officer_headers"]
    for pending in (pending_a, pending_b):
        after = th.get_success_data(api.get_foia_request(pending["id"], headers=reader))
        assert after["status"] == "CLOSED"
        assert after["close_reason"] == "RECORDS_MADE_PUBLIC"

    # A terminal request is untouched by the cascade.
    granted_after = th.get_success_data(api.get_foia_request(granted["id"], headers=reader))
    assert granted_after["status"] == "GRANTED"
    assert granted_after.get("close_reason") is None

    collection_after = th.read_collection(collection["id"])
    assert collection_after["restriction_posture"] == "PUBLIC"
    assert collection_after["foia_release_count"] == 1


def test_declass_completion_posture_foia_cascade(api):
    """PRD §3.5: "A `DECLASSIFIED` outcome clears the collection's
    `classification_level` to `NONE` and stamps `declass_outcome` as
    `DECLASSIFIED`."
    PRD §3.5: "In every case the collection's `restriction_posture` is
    recomputed under §2.8 and its `version` advances — and if the recompute
    flips the posture to `PUBLIC`, the posture-flip cascade fires, closing the
    collection's still-pending FOIA requests as §2.8 describes."
    PRD §2.8: "On any recompute that changes a collection's posture into
    `PUBLIC`, every FOIA request against that collection still sitting in
    `RECEIVED` or `IN_REVIEW` is transitioned to `CLOSED` with `close_reason`
    set to `RECORDS_MADE_PUBLIC`, and each such request's `version`
    increments."

    Design: Difficulty/transitive_cascade/declass_completion_posture_foia_cascade
    """
    th.set_clock()
    bundle = th.setup_classified_collection(classification_default="SECRET")
    collection = bundle["collection"]
    ada = th.create_active_researcher()
    foia = th.create_foia(ada, collection, "classified memos")

    review = th.create_in_progress_mdr(collection, ada,
                                       "scholarly research on 2001 decisions")
    completed = th.complete_review(review, "DECLASSIFY")
    assert completed["status"] == "COMPLETED"
    assert completed["outcome"] == "DECLASSIFIED"

    # Hop 1: the outcome clears the classification; hop 2: posture flips.
    collection_after = th.read_collection(collection["id"])
    assert collection_after["classification_level"] == "NONE"
    assert collection_after["declass_outcome"] == "DECLASSIFIED"
    assert collection_after["restriction_posture"] == "PUBLIC"

    # Hop 3: the flip closes the pending FOIA request.
    foia_after = th.get_success_data(
        api.get_foia_request(foia["id"], headers=th.TEST_USERS["foia_officer_headers"])
    )
    assert foia_after["status"] == "CLOSED"
    assert foia_after["close_reason"] == "RECORDS_MADE_PUBLIC"


def test_declass_completion_partial_outcome_flips_nothing(api):
    """PRD §3.5: "A `PARTIAL` or `EXEMPT_RETAINED` outcome stamps
    `declass_outcome` with that value and leaves `classification_level`
    unchanged."
    PRD §3.5: "If the reviewer's own assessment is `EXEMPT`, the outcome is
    `EXEMPT_RETAINED`. Otherwise, if at least one `RESPONDED` referral decided
    `EXEMPT`, the outcome is `PARTIAL`. Otherwise the outcome is
    `DECLASSIFIED`."
    PRD §2.8: "A recompute that leaves the posture non-public, or that changes
    it between the two restricted postures, closes nothing."

    Design: Difficulty/transitive_cascade/declass_completion_posture_foia_cascade
    """
    th.set_clock()
    ctx = th.setup_in_progress_mdr_with_referral()
    collection = ctx["collection"]
    review = ctx["review"]
    ada = ctx["researcher"]
    foia = th.create_foia(ada, collection, "pending during partial outcome")

    th.respond_referral(ctx["referral"], "EXEMPT", "B1")
    completed = th.complete_review(review, "DECLASSIFY")
    assert completed["status"] == "COMPLETED"
    assert completed["outcome"] == "PARTIAL"
    assert completed["exemption_codes"] == ["B1"]

    # Classification survives a PARTIAL outcome, so the posture stays
    # restricted and the pending FOIA request is not closed.
    collection_after = th.read_collection(collection["id"])
    assert collection_after["classification_level"] == "SECRET"
    assert collection_after["declass_outcome"] == "PARTIAL"
    assert collection_after["restriction_posture"] == "CLASSIFIED_REVIEW_REQUIRED"

    foia_after = th.get_success_data(
        api.get_foia_request(foia["id"], headers=th.TEST_USERS["foia_officer_headers"])
    )
    assert foia_after["status"] == "RECEIVED"
