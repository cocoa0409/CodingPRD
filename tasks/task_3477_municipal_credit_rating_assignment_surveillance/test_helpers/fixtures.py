"""Composite setup builders for the Municipal Credit Ratings API.

Every builder drives the public API only and uses the lenient
``get_success_data`` validator so that a setup failure surfaces as a clear
"Setup failed" assertion rather than a confusing status-pinning error deep
inside a fixture.

Time discipline (PRD section 2.4): the harness restarts the server before
every test, so each test starts against an empty database with the logical
clock already at exactly 2026-09-01T00:00:00Z.  Builders therefore NEVER
backdate anything and never assume wall-clock time; every later instant is
reached by advancing the clock through ``advance_clock``.  The default
session window (the morning of 2026-09-02) and the default publication
instant (2026-09-08T00:00:00Z, strictly past the 120-hour appeal window of
a rating assigned in that window) keep the standard chain monotonic.

Identity threading (PRD section 2.1): after creating an issuer or an
underwriter, every ownership-gated call in the same chain uses
``make_issuer_headers(issuer["id"])`` / ``make_underwriter_headers(...)`` —
never a shared placeholder header set.

Document requirements: the PRD pins the unsolicited requirement to exactly
[PUBLIC_FILING_FY] but leaves the solicited per-credit-type sets to the
server; ``submit_required_documents`` therefore reads
``required_document_codes`` back from the engagement and submits exactly
those codes, which drives any engagement to ANALYSIS regardless of how the
requirement set is derived.
"""

from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from . import factories as f
from .assertions import (
    assert_engagement,
    assert_issuer,
    assert_rating,
    assert_scorecard,
    assert_session,
)
from .test_users import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    CHAIR_HEADERS,
    OFFICER_HEADERS,
    make_committee_chair_headers,
    make_committee_member_headers,
    make_issuer_headers,
    make_underwriter_headers,
)

# ─── Instant arithmetic (logical-clock values are ISO 8601 UTC) ─────────────


def _parse_instant(value):
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def _format_instant(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_add_seconds(value, seconds):
    """The instant ``seconds`` after the given ISO 8601 UTC value."""
    return _format_instant(_parse_instant(value) + timedelta(seconds=seconds))


def iso_add_hours(value, hours):
    return _format_instant(_parse_instant(value) + timedelta(hours=hours))


def iso_add_days(value, days):
    return _format_instant(_parse_instant(value) + timedelta(days=days))


#: Default instant at which the standard chain publishes: strictly later
#: than assigned_at + 120h for a rating assigned in the default session
#: window (PRD section 3.4), and before the issuer's next 06-30 fiscal
#: year-end, so obligation period 1 lands on 2027-06-30.
DEFAULT_PUBLISH_AT = "2026-09-08T00:00:00Z"


# ─── Logical clock ──────────────────────────────────────────────────────────


def advance_clock(api, to_iso8601, headers=ADMIN_HEADERS):
    """Advance the logical clock (PlatformAdmin only); every advance runs
    the full time-driven sweep (PRD section 2.4)."""
    response = api.set_clock(to_iso8601, headers=headers)
    assert response.status_code == 200, (
        "Setup failed: advancing the clock to {0} answered {1}: {2}".format(
            to_iso8601, response.status_code, response.text
        )
    )
    return to_iso8601


# ─── Registrations ──────────────────────────────────────────────────────────


def create_issuer(api, headers=ADMIN_HEADERS, **overrides):
    """Register a municipal issuer (201); returns the issuer body."""
    response = api.create_issuer(f.issuer_payload(**overrides), headers=headers)
    data = get_success_data(response)
    assert response.status_code == 201, (
        "Setup failed: issuer registration answered {0}: {1}".format(
            response.status_code, response.text
        )
    )
    assert_issuer(data)
    return data


def create_underwriter(api, headers=ADMIN_HEADERS, **overrides):
    """Register an underwriter (201); returns the underwriter body."""
    response = api.create_underwriter(
        f.underwriter_payload(**overrides), headers=headers
    )
    data = get_success_data(response)
    assert response.status_code == 201, (
        "Setup failed: underwriter registration answered {0}: {1}".format(
            response.status_code, response.text
        )
    )
    return data


def issuer_headers(issuer):
    """Ownership headers for calls made as this issuer (entity-backed id)."""
    return make_issuer_headers(issuer["id"])


def underwriter_headers(underwriter):
    return make_underwriter_headers(underwriter["id"])


def get_issuer(api, issuer_id, headers=ADMIN_HEADERS):
    return get_success_data(api.get_issuer(issuer_id, headers=headers))


def get_notifications(api, issuer_id, headers=ADMIN_HEADERS):
    """The issuer's append-only communication log, in emission order."""
    return get_success_data(api.list_issuer_notifications(issuer_id, headers=headers))


# ─── Criteria versions ──────────────────────────────────────────────────────


def create_criteria_version(api, headers=OFFICER_HEADERS, **overrides):
    """Draft a criteria version (201, SurveillanceOfficer); DRAFT body."""
    response = api.create_criteria_version(
        f.criteria_version_payload(**overrides), headers=headers
    )
    data = get_success_data(response)
    assert response.status_code == 201, (
        "Setup failed: criteria creation answered {0}: {1}".format(
            response.status_code, response.text
        )
    )
    return data


def activate_criteria(api, criteria_version_id, headers=OFFICER_HEADERS):
    """Activate a DRAFT criteria version (200); returns the ACTIVE body."""
    data = get_success_data(
        api.activate_criteria_version(criteria_version_id, headers=headers)
    )
    assert data["status"] == C.CRITERIA_ACTIVE, (
        "Setup failed: activation left the version in {0}".format(data["status"])
    )
    return data


def setup_active_criteria(api, headers=OFFICER_HEADERS, **overrides):
    """Create + activate a criteria version; returns the ACTIVE body.

    The first activation of a (jurisdiction, credit_type) segment creates no
    review items (PRD section 3.6), so this is safe to call during any
    pre-publication setup.
    """
    draft = create_criteria_version(api, headers=headers, **overrides)
    return activate_criteria(api, draft["id"], headers=headers)


# ─── Engagements: origination, terms, documents, scorecard ─────────────────


def create_engagement_solicited(api, issuer, headers=None, **overrides):
    """Open a SOLICITED engagement as the issuer itself (201, REQUESTED)."""
    if headers is None:
        headers = issuer_headers(issuer)
    response = api.create_engagement(
        f.engagement_payload(issuer["id"], **overrides), headers=headers
    )
    data = get_success_data(response)
    assert response.status_code == 201, (
        "Setup failed: engagement creation answered {0}: {1}".format(
            response.status_code, response.text
        )
    )
    assert_engagement(data)
    return data


def create_engagement_by_underwriter(api, issuer, underwriter, **overrides):
    """Open a SOLICITED engagement as an underwriter on the issuer's
    behalf; the payload's underwriter_id equals the caller's id (PRD 2.1)."""
    response = api.create_engagement(
        f.engagement_payload(
            issuer["id"], underwriter_id=underwriter["id"], **overrides
        ),
        headers=underwriter_headers(underwriter),
    )
    data = get_success_data(response)
    assert response.status_code == 201, (
        "Setup failed: underwriter-originated engagement answered {0}: {1}".format(
            response.status_code, response.text
        )
    )
    assert_engagement(data)
    return data


def create_engagement_unsolicited(api, issuer, analyst_headers=ANALYST_HEADERS,
                                  **overrides):
    """Open an UNSOLICITED engagement as a LeadAnalyst (201); starts in
    INFORMATION_GATHERING with the fee waived (PRD section 3.1)."""
    response = api.create_engagement(
        f.engagement_payload(
            issuer["id"], solicitation=C.SOLICITATION_UNSOLICITED, **overrides
        ),
        headers=analyst_headers,
    )
    data = get_success_data(response)
    assert response.status_code == 201, (
        "Setup failed: unsolicited engagement answered {0}: {1}".format(
            response.status_code, response.text
        )
    )
    assert_engagement(data)
    return data


def get_engagement(api, engagement_id, headers=ADMIN_HEADERS):
    return get_success_data(api.get_engagement(engagement_id, headers=headers))


def accept_terms(api, engagement, issuer=None, fee_payment_cents=None,
                 apply_credit_cents=0, headers=None):
    """Issuer accepts terms (REQUESTED -> ENGAGED).  By default the cash
    payment covers exactly fee_cents minus the applied credit."""
    if issuer is None and headers is None:
        raise AssertionError("accept_terms needs the owning issuer or headers")
    if headers is None:
        headers = issuer_headers(issuer)
    if fee_payment_cents is None:
        fee_payment_cents = engagement["fee_cents"] - apply_credit_cents
    payload = f.accept_terms_payload(
        fee_cents=engagement["fee_cents"],
        fee_payment_cents=fee_payment_cents,
        apply_credit_cents=apply_credit_cents,
    )
    data = get_success_data(
        api.accept_terms(engagement["id"], payload, headers=headers)
    )
    assert data["status"] == C.ENGAGEMENT_ENGAGED, (
        "Setup failed: accept-terms left the engagement in {0}".format(data["status"])
    )
    return data


def submit_document(api, engagement_id, document_code, headers):
    """Submit one document by code; returns the engagement body."""
    return get_success_data(
        api.submit_document(
            engagement_id, f.document_payload(document_code), headers=headers
        )
    )


def submit_required_documents(api, engagement, actor_headers=None):
    """Submit exactly the engagement's outstanding required documents,
    driving it to ANALYSIS (PRD section 3.2).  The submitting actor is the
    owning issuer for a solicited engagement and a LeadAnalyst for an
    unsolicited one.  Returns the freshest engagement body."""
    current = get_engagement(api, engagement["id"])
    if actor_headers is None:
        if current["solicitation"] == C.SOLICITATION_UNSOLICITED:
            actor_headers = ANALYST_HEADERS
        else:
            actor_headers = make_issuer_headers(current["issuer_id"])
    received = set(current.get("received_document_codes", []))
    for code in current["required_document_codes"]:
        if code in received:
            continue
        current = submit_document(api, current["id"], code, actor_headers)
        received.add(code)
    assert current["status"] in (
        C.ENGAGEMENT_ANALYSIS,
        C.ENGAGEMENT_COMMITTEE_READY,
    ), "Setup failed: documents left the engagement in {0}".format(current["status"])
    return current


def submit_scorecard(api, engagement, scores=None, analyst_headers=ANALYST_HEADERS,
                     expected_engagement_version=None):
    """Submit (or supersede) the analytical scorecard (200).  The OCC
    anchor defaults to the engagement's CURRENT version, re-read so a stale
    caller-side body cannot silently fail setup; tests probing staleness
    build their payload via factories instead."""
    if expected_engagement_version is None:
        engagement = get_engagement(api, engagement["id"])
        expected_engagement_version = engagement["version"]
    payload = f.scorecard_payload(
        expected_engagement_version, **(scores or {})
    )
    data = get_success_data(
        api.submit_scorecard(engagement["id"], payload, headers=analyst_headers)
    )
    assert_scorecard(data)
    return data


# ─── Composite engagement drivers ───────────────────────────────────────────


def setup_engagement_in_analysis(api, issuer=None, credit_type=C.CREDIT_TYPE_GENERAL_OBLIGATION,
                                 jurisdiction_code="US-CA", issuer_overrides=None,
                                 analyst_headers=ANALYST_HEADERS, **engagement_overrides):
    """Issuer + engagement driven through terms and documents to ANALYSIS.
    No criteria version is needed until scorecard submission (PRD 3.2).
    Returns {"issuer", "engagement"}."""
    if issuer is None:
        issuer = create_issuer(api, **(issuer_overrides or {}))
    engagement = create_engagement_solicited(
        api, issuer, credit_type=credit_type, jurisdiction_code=jurisdiction_code,
        **engagement_overrides
    )
    engagement = accept_terms(api, engagement, issuer)
    engagement = submit_required_documents(api, engagement)
    return {"issuer": issuer, "engagement": engagement}


def setup_committee_ready_engagement(api, issuer=None,
                                     credit_type=C.CREDIT_TYPE_GENERAL_OBLIGATION,
                                     jurisdiction_code="US-CA", scores=None,
                                     analyst_headers=ANALYST_HEADERS,
                                     criteria_version=None,
                                     criteria_overrides=None,
                                     issuer_overrides=None,
                                     **engagement_overrides):
    """Full analytical setup: issuer, an ACTIVE criteria version for the
    segment (created unless one is handed in), and an engagement scored
    into COMMITTEE_READY.  Returns {"issuer", "criteria_version",
    "engagement", "scorecard"} with the engagement body refreshed after
    the scorecard submission."""
    base = setup_engagement_in_analysis(
        api,
        issuer=issuer,
        credit_type=credit_type,
        jurisdiction_code=jurisdiction_code,
        issuer_overrides=issuer_overrides,
        **engagement_overrides
    )
    issuer = base["issuer"]
    engagement = base["engagement"]
    if criteria_version is None:
        criteria_version = setup_active_criteria(
            api,
            jurisdiction_code=jurisdiction_code,
            credit_type=credit_type,
            **(criteria_overrides or {})
        )
    scorecard = submit_scorecard(
        api, engagement, scores=scores, analyst_headers=analyst_headers
    )
    engagement = get_engagement(api, engagement["id"])
    assert engagement["status"] == C.ENGAGEMENT_COMMITTEE_READY, (
        "Setup failed: scorecard left the engagement in {0}".format(
            engagement["status"]
        )
    )
    return {
        "issuer": issuer,
        "criteria_version": criteria_version,
        "engagement": engagement,
        "scorecard": scorecard,
    }


# ─── Committee sessions ─────────────────────────────────────────────────────


def schedule_session(api, engagement, chair_headers=CHAIR_HEADERS,
                     start_at=f.DEFAULT_SESSION_START,
                     end_at=f.DEFAULT_SESSION_END, voter_ids=None):
    """Schedule a committee session on a COMMITTEE_READY engagement (201);
    the calling chair is recorded as chair_id (PRD section 3.3)."""
    payload = f.session_payload(start_at=start_at, end_at=end_at)
    if voter_ids is not None:
        payload["voter_ids"] = list(voter_ids)
    response = api.schedule_session(engagement["id"], payload, headers=chair_headers)
    data = get_success_data(response)
    assert response.status_code == 201, (
        "Setup failed: session scheduling answered {0}: {1}".format(
            response.status_code, response.text
        )
    )
    assert_session(data)
    return data


def next_session_window(prior_session, hours=2):
    """The earliest lawful window for a follow-up session on the SAME
    engagement: start exactly 24h after the prior session's end (the
    cooling-off boundary is inclusive-permitting, PRD section 3.3)."""
    start = iso_add_hours(prior_session["end_at"], C.SESSION_COOLING_OFF_HOURS)
    return start, iso_add_hours(start, hours)


def get_session(api, session_id, headers=ADMIN_HEADERS):
    return get_success_data(api.get_session(session_id, headers=headers))


def open_session(api, session, chair_headers=None, open_at=None):
    """Advance the clock inside the window and open (SCHEDULED ->
    IN_SESSION).  The chair defaults to the session's recorded chair_id."""
    if chair_headers is None:
        chair_headers = make_committee_chair_headers(session["chair_id"])
    if open_at is None:
        open_at = session["start_at"]
    advance_clock(api, open_at)
    data = get_success_data(api.open_session(session["id"], headers=chair_headers))
    assert data["status"] == C.SESSION_IN_SESSION, (
        "Setup failed: open left the session in {0}".format(data["status"])
    )
    return data


def cast_vote(api, session_id, voter_id, notch=None, recusal_reason=None):
    """Cast one ballot as the pool member ``voter_id`` (201); exactly one
    of notch / recusal_reason (PRD section 3.3)."""
    response = api.cast_vote(
        session_id,
        f.vote_payload(voter_id, notch_vote=notch, recusal_reason=recusal_reason),
        headers=make_committee_member_headers(voter_id),
    )
    data = get_success_data(response)
    assert response.status_code == 201, (
        "Setup failed: vote by {0} answered {1}: {2}".format(
            voter_id, response.status_code, response.text
        )
    )
    return data


def cast_votes(api, session_id, votes):
    """Cast several ballots; each entry is (voter_id, notch) or
    (voter_id, None, recusal_reason)."""
    for entry in votes:
        voter_id, notch = entry[0], entry[1]
        reason = entry[2] if len(entry) > 2 else None
        cast_vote(api, session_id, voter_id, notch=notch, recusal_reason=reason)


def appoint_alternate(api, session, recused_voter_id, alternate_voter_id,
                      chair_headers=None):
    """Appoint an alternate for a recused seat (200, chair only)."""
    if chair_headers is None:
        chair_headers = make_committee_chair_headers(session["chair_id"])
    return get_success_data(
        api.appoint_alternate(
            session["id"],
            f.alternate_payload(recused_voter_id, alternate_voter_id),
            headers=chair_headers,
        )
    )


def close_session(api, session, chair_headers=None):
    """Close and tally (200).  COMPLETED assigns the rating; ADJOURNED
    leaves the engagement COMMITTEE_READY (PRD section 3.3)."""
    if chair_headers is None:
        chair_headers = make_committee_chair_headers(session["chair_id"])
    return get_success_data(api.close_session(session["id"], headers=chair_headers))


def get_ratings_for_engagement(api, engagement_id, headers=ADMIN_HEADERS):
    """All ratings of an engagement, in insertion order (PRD section 2.3)."""
    return get_success_data(
        api.list_ratings(headers=headers, params={"engagement_id": engagement_id})
    )


def get_rating(api, rating_id, headers=ADMIN_HEADERS):
    return get_success_data(api.get_rating(rating_id, headers=headers))


#: The standard closing slate: A, A, BBB — median A, inside the one-notch
#: band around an indicative A (PRD section 3.3).
STANDARD_VOTES_A = [("voter-1", "A"), ("voter-2", "A"), ("voter-3", "BBB")]


def run_committee(api, engagement, chair_headers=CHAIR_HEADERS, votes=None,
                  start_at=f.DEFAULT_SESSION_START, end_at=f.DEFAULT_SESSION_END,
                  open_at=f.DEFAULT_SESSION_OPEN_AT, voter_ids=None):
    """Schedule, open, vote and close one committee session.  On
    COMPLETED the created rating is fetched and returned as well.
    Returns {"session", "rating"} (rating None when the session adjourned)."""
    session = schedule_session(
        api, engagement, chair_headers=chair_headers,
        start_at=start_at, end_at=end_at, voter_ids=voter_ids,
    )
    session = open_session(api, session, open_at=open_at)
    cast_votes(api, session["id"], votes if votes is not None else STANDARD_VOTES_A)
    session = close_session(api, session)
    rating = None
    if session["status"] == C.SESSION_COMPLETED:
        ratings = get_ratings_for_engagement(api, engagement["id"])
        assert ratings, "Setup failed: a completed session created no rating"
        rating = ratings[-1]
        assert_rating(rating)
    return {"session": session, "rating": rating}


def setup_assigned_rating(api, issuer=None,
                          credit_type=C.CREDIT_TYPE_GENERAL_OBLIGATION,
                          jurisdiction_code="US-CA", scores=None, votes=None,
                          analyst_headers=ANALYST_HEADERS,
                          chair_headers=CHAIR_HEADERS, **kwargs):
    """The full pre-publication chain: issuer, ACTIVE criteria, engagement
    to COMMITTEE_READY, one committee session completed.  Returns
    {"issuer", "criteria_version", "engagement", "scorecard", "session",
    "rating"} with the rating in ASSIGNED."""
    ctx = setup_committee_ready_engagement(
        api,
        issuer=issuer,
        credit_type=credit_type,
        jurisdiction_code=jurisdiction_code,
        scores=scores,
        analyst_headers=analyst_headers,
        **kwargs
    )
    outcome = run_committee(
        api, ctx["engagement"], chair_headers=chair_headers, votes=votes
    )
    assert outcome["rating"] is not None, (
        "Setup failed: the standard committee session adjourned ({0})".format(
            outcome["session"].get("adjourn_reason")
        )
    )
    ctx.update(outcome)
    ctx["engagement"] = get_engagement(api, ctx["engagement"]["id"])
    return ctx


# ─── Publication and disclosure ─────────────────────────────────────────────


def publish_rating(api, rating, analyst_headers=ANALYST_HEADERS, publish_at=None,
                   **publish_overrides):
    """Publish an ASSIGNED rating after the 120-hour appeal window: the
    clock must stand strictly later than assigned_at + 120h (PRD 3.4).
    Defaults to one hour past the window when no instant is given."""
    if publish_at is None:
        publish_at = iso_add_hours(rating["assigned_at"], C.APPEAL_WINDOW_HOURS + 1)
    advance_clock(api, publish_at)
    data = get_success_data(
        api.publish_rating(
            rating["id"], f.publish_payload(**publish_overrides),
            headers=analyst_headers,
        )
    )
    assert data["status"] == C.RATING_PUBLISHED, (
        "Setup failed: publish left the rating in {0}".format(data["status"])
    )
    return data


def get_obligations(api, rating_id, headers=OFFICER_HEADERS):
    """A rating's disclosure obligations in period order (PRD section 2.3)."""
    return get_success_data(api.list_obligations(rating_id, headers=headers))


def setup_published_rating(api, publish_at=DEFAULT_PUBLISH_AT, **kwargs):
    """setup_assigned_rating + publication.  Returns the same context plus
    "obligations" (period 1 created at publication, PRD section 3.5)."""
    ctx = setup_assigned_rating(api, **kwargs)
    rating = publish_rating(api, ctx["rating"], publish_at=publish_at)
    ctx["rating"] = rating
    ctx["engagement"] = get_engagement(api, ctx["engagement"]["id"])
    ctx["obligations"] = get_obligations(api, rating["id"])
    return ctx


def submit_obligation(api, obligation, issuer):
    """The issuer submits a periodic disclosure (200); classification into
    SUBMITTED_ON_TIME / SUBMITTED_LATE is the clock's business (PRD 3.5)."""
    return get_success_data(
        api.submit_obligation(obligation["id"], headers=issuer_headers(issuer))
    )


def advance_past_obligation_due(api, obligation, extra_days=1):
    """Advance the clock strictly past an obligation's due_at (default one
    day past), flipping it OVERDUE in the sweep (PRD section 3.5)."""
    return advance_clock(api, iso_add_days(obligation["due_at"], extra_days))


def advance_past_delinquency(api, obligation, extra_days=0):
    """Advance strictly past due_at + 30 days, flipping an OVERDUE
    obligation to DELINQUENT (PRD section 3.5)."""
    target = iso_add_days(
        obligation["due_at"], C.DELINQUENCY_GRACE_DAYS + 1 + extra_days
    )
    return advance_clock(api, target)


def advance_past_default(api, obligation, extra_days=0):
    """Advance strictly past due_at + 60 days: the obligation flips
    DEFAULTED and its rating is withdrawn for NON_DISCLOSURE (PRD 3.5)."""
    target = iso_add_days(
        obligation["due_at"], C.NONDISCLOSURE_WITHDRAW_DAYS + 1 + extra_days
    )
    return advance_clock(api, target)


def setup_withdrawn_non_disclosure(api, publish_at=DEFAULT_PUBLISH_AT, **kwargs):
    """A published rating whose period-1 obligation is left unanswered past
    due_at + 60 days: obligation DEFAULTED, rating WITHDRAWN with reason
    NON_DISCLOSURE, issuer delinquent_flag set (PRD section 3.5).
    Returns the published-rating context with refreshed "rating",
    "obligations" and "issuer"."""
    ctx = setup_published_rating(api, publish_at=publish_at, **kwargs)
    advance_past_default(api, ctx["obligations"][0])
    ctx["rating"] = get_rating(api, ctx["rating"]["id"])
    ctx["obligations"] = get_obligations(api, ctx["rating"]["id"])
    ctx["issuer"] = get_issuer(api, ctx["issuer"]["id"])
    return ctx


def cure_defaulted_obligation(api, ctx):
    """Submit the DEFAULTED period-1 obligation from a withdrawn context;
    lands SUBMITTED_LATE and clears the issuer's delinquent flag without
    reinstating the rating (PRD section 3.5)."""
    obligation = ctx["obligations"][0]
    cured = submit_obligation(api, obligation, ctx["issuer"])
    ctx["obligations"] = get_obligations(api, ctx["rating"]["id"])
    ctx["issuer"] = get_issuer(api, ctx["issuer"]["id"])
    ctx["rating"] = get_rating(api, ctx["rating"]["id"])
    return cured


# ─── Rating actions, withdrawal, reinstatement ─────────────────────────────


def post_rating_action(api, rating, action, headers=OFFICER_HEADERS,
                       expected_rating_version=None, **overrides):
    """Post a surveillance action (200); the OCC anchor defaults to the
    rating's CURRENT version, re-read so setup never fails on staleness."""
    if expected_rating_version is None:
        rating = get_rating(api, rating["id"])
        expected_rating_version = rating["version"]
    payload = f.rating_action_payload(
        action, expected_rating_version, **overrides
    )
    return get_success_data(
        api.post_rating_action(rating["id"], payload, headers=headers)
    )


def withdraw_rating(api, rating, withdraw_reason=C.WITHDRAW_REASON_ISSUER_REQUEST,
                    headers=OFFICER_HEADERS):
    """Manual withdrawal via the actions endpoint (PUBLISHED -> WITHDRAWN,
    reason ISSUER_REQUEST or CRITERIA only — PRD section 3.5)."""
    data = post_rating_action(
        api, rating, C.ACTION_WITHDRAW, headers=headers,
        withdraw_reason=withdraw_reason,
    )
    assert data["status"] == C.RATING_WITHDRAWN, (
        "Setup failed: withdraw left the rating in {0}".format(data["status"])
    )
    return data


def reinstate_rating(api, rating, headers=OFFICER_HEADERS):
    """Reinstate a NON_DISCLOSURE-withdrawn rating (200, WITHDRAWN ->
    PUBLISHED, SurveillanceOfficer only — PRD section 3.5)."""
    return get_success_data(api.reinstate_rating(rating["id"], headers=headers))


# ─── Appeals ────────────────────────────────────────────────────────────────


def file_appeal(api, rating, issuer, new_information_codes=None):
    """The issuer files a pre-publication appeal (201, FILED)."""
    response = api.file_appeal(
        rating["id"],
        f.appeal_payload(new_information_codes),
        headers=issuer_headers(issuer),
    )
    data = get_success_data(response)
    assert response.status_code == 201, (
        "Setup failed: appeal filing answered {0}: {1}".format(
            response.status_code, response.text
        )
    )
    return data


def decide_appeal(api, appeal, decision=C.DECISION_UPHELD,
                  chair_headers=CHAIR_HEADERS, rationale=None):
    """The committee chair decides a FILED appeal (200)."""
    overrides = {}
    if rationale is not None:
        overrides["rationale"] = rationale
    return get_success_data(
        api.decide_appeal(
            appeal["id"],
            f.appeal_decision_payload(decision, **overrides),
            headers=chair_headers,
        )
    )


# ─── Criteria governance: review fan-out ────────────────────────────────────


def get_review_items(api, headers=OFFICER_HEADERS, **filters):
    """Portfolio review items in fan-out order (PRD section 2.3)."""
    return get_success_data(api.list_review_items(headers=headers, params=filters))


def begin_review(api, review_item, headers=OFFICER_HEADERS):
    """PENDING or ESCALATED -> IN_REVIEW (200, SurveillanceOfficer)."""
    return get_success_data(api.begin_review_item(review_item["id"], headers=headers))


def complete_review(api, review_item, outcome=C.REVIEW_OUTCOME_NO_ACTION,
                    headers=OFFICER_HEADERS, **overrides):
    """IN_REVIEW -> COMPLETED_* (200); RATING_ACTION requires new_notch."""
    return get_success_data(
        api.complete_review_item(
            review_item["id"],
            f.review_complete_payload(outcome, **overrides),
            headers=headers,
        )
    )


def setup_with_pending_review(api, new_criteria_overrides=None, **kwargs):
    """A published rating plus a successor criteria version activated for
    the same segment: the prior version is superseded and exactly one
    review item per affected PUBLISHED rating fans out in PENDING with
    due_at = activated_at + 90 days (PRD section 3.6).
    Returns the published-rating context plus "successor_criteria" and
    "review_item"."""
    ctx = setup_published_rating(api, **kwargs)
    successor_overrides = {
        "jurisdiction_code": ctx["engagement"]["jurisdiction_code"],
        "credit_type": ctx["engagement"]["credit_type"],
        "version_label": "GO-2026.2",
    }
    successor_overrides.update(new_criteria_overrides or {})
    successor = setup_active_criteria(api, **successor_overrides)
    items = get_review_items(api, criteria_version_id=successor["id"])
    assert items, "Setup failed: activation fanned out no review items"
    ctx["successor_criteria"] = successor
    ctx["review_item"] = items[0]
    ctx["rating"] = get_rating(api, ctx["rating"]["id"])
    return ctx


def setup_with_escalated_review(api, **kwargs):
    """A pending review item whose 90-day deadline has passed: the clock
    sweep escalates it PENDING -> ESCALATED (PRD section 3.6), which also
    blocks committee scheduling for the issuer's engagements."""
    ctx = setup_with_pending_review(api, **kwargs)
    advance_clock(api, iso_add_days(ctx["review_item"]["due_at"], 1))
    ctx["review_item"] = get_success_data(
        api.get_review_item(ctx["review_item"]["id"], headers=OFFICER_HEADERS)
    )
    return ctx


# ─── Bond sales ─────────────────────────────────────────────────────────────


def create_bond_sale(api, issuer, rating, headers=None, **overrides):
    """Price a bond sale against a rating of the same issuer (201); the
    caller defaults to the issuer itself (PRD section 3.7)."""
    if headers is None:
        headers = issuer_headers(issuer)
    response = api.create_bond_sale(
        f.bond_sale_payload(issuer["id"], rating["id"], **overrides),
        headers=headers,
    )
    data = get_success_data(response)
    assert response.status_code == 201, (
        "Setup failed: bond sale answered {0}: {1}".format(
            response.status_code, response.text
        )
    )
    return data
