"""Composite setup helpers.

The server starts each test with an empty store and the logical clock at its
pinned 2026-09-01T00:00:00Z start, so every precondition here is built through
the public endpoints. Setup calls go through ``get_success_data`` (any 2xx) so a
fixture failure reports "Setup failed" instead of a confusing assertion.

Identity threading: calls gated on an entity-backed role always build headers
from the live entity's ``id`` (``make_state_regulator_headers(state["id"])`` and
friends) — never a shared constant. OCC-carrying creates (filings, adoptions)
re-read the parent's current ``version`` unless the caller pins one explicitly.

All default datetimes sit at or after the clock start; helpers that need the
clock at a window's end advance it themselves.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .constants import (
    ACTIVATOR_ACTUARY_USER_ID,
    AUTHOR_ACTUARY_USER_ID,
    DEFAULT_EXPOSURE_END,
    DEFAULT_EXPOSURE_START,
    DEFAULT_REVIEW_PERIOD_END,
    DEFAULT_REVIEW_PERIOD_START,
    MIN_REVIEW_GAP_DAYS,
    REVIEW_LEAD_USER_ID,
    SECOND_EXPOSURE_END,
    SECOND_EXPOSURE_START,
    SECOND_REVIEW_LEAD_USER_ID,
    days_after,
)
from .test_users import (
    TEST_USERS,
    make_actuary_headers,
    make_association_staff_headers,
    make_insurer_user_headers,
    make_producer_user_headers,
    make_review_team_lead_headers,
    make_state_regulator_headers,
)
from .types import JsonObject

STAFF = TEST_USERS["association_staff_headers"]


class Bundle(object):
    """A small attribute bag so a test can read ``bundle.act["id"]`` fluently."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def __repr__(self):
        return "Bundle(%s)" % ", ".join(sorted(self.__dict__))


# ------------------------------------------------------------------ logical clock
def advance_clock(client, to_iso8601: str) -> JsonObject:
    """Move the logical clock forward (also runs the license expiry sweep)."""
    return get_success_data(client.set_clock(factories.clock_payload(to_iso8601), STAFF))


# ------------------------------------------------------------------------ states
def create_state(client, code: str = "CA", **overrides) -> JsonObject:
    """Register a jurisdiction; a new state starts ACCREDITED, fail count 0."""
    return get_success_data(
        client.create_state(factories.state_payload(code=code, **overrides), STAFF)
    )


def create_states(client, codes=("CA",)) -> dict:
    """Register several jurisdictions at once; returns {code: state}."""
    return {code: create_state(client, code=code) for code in codes}


def read_state(client, state_id) -> JsonObject:
    return get_success_data(client.get_state(state_id, STAFF))


def state_version(client, state_id) -> int:
    """Re-read the state to obtain the version an adoption create must echo."""
    return read_state(client, state_id)["version"]


# --------------------------------------------------------------------- model acts
def create_model_act(client, **overrides) -> JsonObject:
    """Register a model instrument; it starts DRAFTING with zeroed counters."""
    return get_success_data(
        client.create_model_act(factories.model_act_payload(**overrides), STAFF)
    )


def read_model_act(client, act_id) -> JsonObject:
    return get_success_data(client.get_model_act(act_id, STAFF))


def open_exposure_draft(client, act_id, start: str = DEFAULT_EXPOSURE_START,
                        end: str = DEFAULT_EXPOSURE_END, **overrides) -> JsonObject:
    """Open an exposure draft; the first draft moves the act to EXPOSURE_OPEN."""
    return get_success_data(
        client.create_exposure_draft(
            factories.exposure_draft_payload(
                act_id, comment_window_start=start, comment_window_end=end, **overrides
            ),
            STAFF,
        )
    )


def close_exposure_draft(client, draft_id, window_end: str = None,
                         advance: bool = True) -> JsonObject:
    """Close an OPEN draft, first advancing the clock to the window end when
    asked (the close gate requires the clock to have reached it). Closing the
    act's last OPEN draft moves the act to BALLOTING."""
    if advance and window_end is not None:
        advance_clock(client, window_end)
    return get_success_data(client.close_exposure_draft(draft_id, STAFF))


def move_act_to_balloting(client, act_id, start: str = DEFAULT_EXPOSURE_START,
                          end: str = DEFAULT_EXPOSURE_END) -> Bundle:
    """Draft open + clock advanced to the window end + close -> act BALLOTING."""
    draft = open_exposure_draft(client, act_id, start=start, end=end)
    closed = close_exposure_draft(client, draft["id"], window_end=end)
    return Bundle(act=read_model_act(client, act_id), draft=closed)


def cast_ballot(client, act_id, state, vote: str = "YEA") -> JsonObject:
    """Cast one state's ballot; the regulator identity is the State's own id."""
    return get_success_data(
        client.cast_ballot(
            act_id,
            factories.ballot_payload(state_code=state["code"], vote=vote),
            make_state_regulator_headers(state["id"]),
        )
    )


def cast_ballots(client, act_id, ballots) -> list:
    """Cast several ballots: an iterable of (state, vote) pairs."""
    return [cast_ballot(client, act_id, state, vote) for state, vote in ballots]


def create_act_in_balloting(client, states=("CA",), state_map=None,
                            exposure_start: str = DEFAULT_EXPOSURE_START,
                            exposure_end: str = DEFAULT_EXPOSURE_END,
                            **act_overrides) -> Bundle:
    """A BALLOTING act plus the voting states ({code: state}). Pass
    ``state_map`` to reuse already-registered states (state codes are unique —
    re-registering one would be rejected). The default exposure window assumes
    the clock has not yet passed its end; pass a later window otherwise."""
    if state_map is None:
        state_map = create_states(client, states)
    act = create_model_act(client, **act_overrides)
    progressed = move_act_to_balloting(
        client, act["id"], start=exposure_start, end=exposure_end
    )
    return Bundle(act=progressed.act, draft=progressed.draft, states=state_map)


def create_adopted_act(client, voting=("CA",), state_map=None,
                       exposure_start: str = DEFAULT_EXPOSURE_START,
                       exposure_end: str = DEFAULT_EXPOSURE_END,
                       **act_overrides) -> Bundle:
    """A BALLOTING act carried to ADOPTED by the given (state_code, vote) plan.
    The default single YEA from one registered state meets quorum and the
    two-thirds bar."""
    if voting and isinstance(voting[0], str):
        voting = [(code, "YEA") for code in voting]
    codes = [code for code, _ in voting]
    bundle = create_act_in_balloting(
        client, states=codes, state_map=state_map,
        exposure_start=exposure_start, exposure_end=exposure_end, **act_overrides,
    )
    cast_ballots(
        client, bundle.act["id"],
        [(bundle.states[code], vote) for code, vote in voting],
    )
    adopted = get_success_data(client.close_ballot(bundle.act["id"], STAFF))
    return Bundle(act=adopted, states=bundle.states, draft=bundle.draft)


def create_published_act(client, voting=("CA",), state_map=None,
                         exposure_start: str = DEFAULT_EXPOSURE_START,
                         exposure_end: str = DEFAULT_EXPOSURE_END,
                         **act_overrides) -> Bundle:
    """The full forward path: DRAFTING -> EXPOSURE_OPEN -> BALLOTING -> ADOPTED
    -> PUBLISHED. Returns the published act and its voting states."""
    bundle = create_adopted_act(
        client, voting=voting, state_map=state_map,
        exposure_start=exposure_start, exposure_end=exposure_end, **act_overrides,
    )
    published = get_success_data(client.publish_model_act(bundle.act["id"], STAFF))
    return Bundle(act=published, states=bundle.states, draft=bundle.draft)


# ---------------------------------------------------------------------- adoptions
def create_adoption(client, act, state, expected_state_version=None,
                    **overrides) -> JsonObject:
    """Record the state's adoption of a PUBLISHED act (PENDING_CERTIFICATION).
    The state version is re-read for the OCC field unless one is pinned."""
    if expected_state_version is None:
        expected_state_version = state_version(client, state["id"])
    return get_success_data(
        client.create_adoption(
            factories.adoption_payload(
                act["id"], state["code"], expected_state_version, **overrides
            ),
            make_state_regulator_headers(state["id"]),
        )
    )


def certify_adoption(client, adoption_id,
                     variation_class: str = "SUBSTANTIALLY_SIMILAR") -> JsonObject:
    return get_success_data(
        client.certify_adoption(
            adoption_id, factories.certify_payload(variation_class), STAFF
        )
    )


def setup_certified_adoption(client, variation_class: str = "SUBSTANTIALLY_SIMILAR",
                             state_code: str = "CA", is_core: bool = True,
                             **act_overrides) -> Bundle:
    """A PUBLISHED act, the state's PENDING adoption, certified one branch in."""
    act_overrides.setdefault("is_core", is_core)
    published = create_published_act(client, voting=(state_code,), **act_overrides)
    state = published.states[state_code]
    adoption = create_adoption(client, published.act, state)
    certified = certify_adoption(client, adoption["id"], variation_class)
    return Bundle(act=published.act, state=state, adoption=certified,
                  states=published.states)


# ------------------------------------------------------------------------ reviews
def create_review(client, state_id, period_start=None, period_end=None,
                  team_lead_id: str = REVIEW_LEAD_USER_ID,
                  self_assessment_compliant: int = 0, self_assessment_total: int = 1,
                  **overrides) -> JsonObject:
    """Schedule a MANUAL review; desk_score is computed at creation."""
    return get_success_data(
        client.create_review(
            factories.review_payload(
                state_id,
                team_lead_id=team_lead_id,
                self_assessment_compliant=self_assessment_compliant,
                self_assessment_total=self_assessment_total,
                **({"period_start": period_start} if period_start else {}),
                **({"period_end": period_end} if period_end else {}),
                **overrides,
            ),
            STAFF,
        )
    )


def issue_findings(client, review_id, findings_compliant: int = 18,
                   findings_total: int = 20,
                   team_lead_id: str = REVIEW_LEAD_USER_ID) -> JsonObject:
    """Team lead issues findings; onsite_score and proposed_outcome are derived.
    The header id must equal the review's stored team_lead_id."""
    return get_success_data(
        client.issue_findings(
            review_id,
            factories.findings_payload(findings_compliant, findings_total),
            make_review_team_lead_headers(team_lead_id),
        )
    )


def finalize_review(client, review_id) -> JsonObject:
    """AssociationStaff finalizes; the state's standing follows proposed_outcome."""
    return get_success_data(client.finalize_review(review_id, STAFF))


def run_review(client, state_id, period_start, period_end,
               team_lead_id: str = REVIEW_LEAD_USER_ID,
               findings_compliant: int = 18, findings_total: int = 20) -> JsonObject:
    """Schedule + issue + finalize one review; returns the FINAL_* review."""
    review = create_review(
        client, state_id, period_start=period_start, period_end=period_end,
        team_lead_id=team_lead_id,
    )
    issue_findings(
        client, review["id"], findings_compliant, findings_total,
        team_lead_id=team_lead_id,
    )
    return finalize_review(client, review["id"])


def next_review_period(prior_period_end: str, length_days: int = 120):
    """The earliest legal follow-on period: start exactly the 180-day gap after
    the prior period's end; end ``length_days`` later. Returns (start, end)."""
    start = days_after(prior_period_end, MIN_REVIEW_GAP_DAYS)
    return start, days_after(start, length_days)


def drive_state_to(client, state_id, target_status: str,
                   period_start: str = None, period_end: str = None) -> JsonObject:
    """Drive a state's standing via consecutive failed reviews:
    PROBATION after one FINAL_FAIL, SUSPENDED after two. Periods are spaced by
    the 180-day gap rule and leads rotate to satisfy reviewer rotation."""
    targets = {"PROBATION": 1, "SUSPENDED": 2}
    assert target_status in targets, "drive_state_to targets PROBATION or SUSPENDED"
    start = period_start or DEFAULT_REVIEW_PERIOD_START
    end = period_end or DEFAULT_REVIEW_PERIOD_END
    leads = [REVIEW_LEAD_USER_ID, SECOND_REVIEW_LEAD_USER_ID]
    for round_no in range(targets[target_status]):
        run_review(
            client, state_id, start, end,
            team_lead_id=leads[round_no % 2],
            findings_compliant=10, findings_total=20,  # onsite 50.0 -> FAIL
        )
        start, end = next_review_period(end)
    return read_state(client, state_id)


# -------------------------------------------------------------- standards/insurers
def create_active_standard(client, code: str = "VM-20", version_label: str = "v2026.1",
                           author: str = AUTHOR_ACTUARY_USER_ID,
                           activator: str = ACTIVATOR_ACTUARY_USER_ID,
                           **overrides) -> JsonObject:
    """Draft a standard as one actuary and activate it as another (the author
    may not activate their own draft). Returns the ACTIVE standard."""
    drafted = get_success_data(
        client.create_valuation_standard(
            factories.valuation_standard_payload(code, version_label, **overrides),
            make_actuary_headers(author),
        )
    )
    return get_success_data(
        client.activate_valuation_standard(drafted["id"], make_actuary_headers(activator))
    )


def create_insurer(client, naic_code: str = "90001", domicile_state_code: str = "CA",
                   **overrides) -> JsonObject:
    """Register an insurer; starts ACTIVE with null RBC posture."""
    return get_success_data(
        client.create_insurer(
            factories.insurer_payload(naic_code, domicile_state_code, **overrides),
            STAFF,
        )
    )


def read_insurer(client, insurer_id) -> JsonObject:
    return get_success_data(client.get_insurer(insurer_id, STAFF))


def insurer_version(client, insurer_id) -> int:
    """Re-read the insurer to obtain the version a filing create must echo."""
    return read_insurer(client, insurer_id)["version"]


# ------------------------------------------------------------------------ filings
def create_filing(client, insurer, valuation_standard_code: str = "VM-20",
                  expected_insurer_version=None, **overrides) -> JsonObject:
    """Create a DRAFT filing as the insurer itself. The insurer version is
    re-read for the OCC field unless the caller pins one (stale-version tests
    pin an old one deliberately)."""
    if expected_insurer_version is None:
        expected_insurer_version = insurer_version(client, insurer["id"])
    return get_success_data(
        client.create_filing(
            factories.filing_payload(
                insurer["id"], expected_insurer_version,
                valuation_standard_code=valuation_standard_code, **overrides,
            ),
            make_insurer_user_headers(insurer["id"]),
        )
    )


def submit_filing(client, filing) -> JsonObject:
    """Submit a DRAFT filing as its owning insurer."""
    insurer_id = filing["insurer_id"] if isinstance(filing, dict) else filing
    filing_id = filing["id"] if isinstance(filing, dict) else filing
    return get_success_data(
        client.submit_filing(filing_id, make_insurer_user_headers(insurer_id))
    )


def validate_filing(client, filing_id) -> JsonObject:
    """Run the validation edits (HTTP 200 whether they pass or fail)."""
    return get_success_data(client.validate_filing(filing_id, STAFF))


def list_rbc_reports(client, filing_id) -> list:
    """Zero or one RBC report for the filing."""
    body = client.list_rbc_reports(filing_id, STAFF).json()
    assert body.get("response_type") == "array", "rbc-reports must be a list envelope"
    return body["data"]


def create_validated_filing(client, insurer, valuation_standard_code: str = "VM-20",
                            **overrides) -> Bundle:
    """Create + submit + validate a passing filing. Returns the VALIDATED
    filing and its single RBC report."""
    filing = create_filing(
        client, insurer, valuation_standard_code=valuation_standard_code, **overrides
    )
    submit_filing(client, filing)
    validated = validate_filing(client, filing["id"])
    reports = list_rbc_reports(client, filing["id"])
    assert len(reports) == 1, "a passing validation computes exactly one RBC report"
    return Bundle(filing=validated, report=reports[0])


def setup_filing_ready(client, naic_code: str = "90001", state_code: str = "CA",
                       standard_code: str = "VM-20", **filing_overrides) -> Bundle:
    """State + insurer + ACTIVE standard + one SUBMITTED filing awaiting
    validation. The workhorse preamble of the filing/RBC tests."""
    state = create_state(client, code=state_code)
    insurer = create_insurer(client, naic_code, state["code"])
    standard = create_active_standard(client, code=standard_code)
    filing = create_filing(client, insurer, valuation_standard_code=standard["code"],
                           **filing_overrides)
    submitted = submit_filing(client, filing)
    return Bundle(state=state, insurer=insurer, standard=standard, filing=submitted)


def setup_validated_filing(client, naic_code: str = "90001", state_code: str = "CA",
                           standard_code: str = "VM-20", **filing_overrides) -> Bundle:
    """setup_filing_ready carried through a passing validation (RBC cascade
    included). Returns state, insurer (post-cascade), standard, filing, report."""
    bundle = setup_filing_ready(
        client, naic_code=naic_code, state_code=state_code,
        standard_code=standard_code, **filing_overrides,
    )
    validated = validate_filing(client, bundle.filing["id"])
    reports = list_rbc_reports(client, bundle.filing["id"])
    insurer = read_insurer(client, bundle.insurer["id"])
    return Bundle(state=bundle.state, insurer=insurer, standard=bundle.standard,
                  filing=validated, report=reports[0] if reports else None)


# -------------------------------------------------------------- producers/licenses
def create_producer(client, npn: str = "P-1", **overrides) -> JsonObject:
    """Register a producer; active_license_count starts at 0."""
    return get_success_data(
        client.create_producer(factories.producer_payload(npn, **overrides), STAFF)
    )


def read_producer(client, producer_id) -> JsonObject:
    return get_success_data(client.get_producer(producer_id, STAFF))


def create_license(client, producer, state_code: str = "CA", **overrides) -> JsonObject:
    """Apply for a license as the producer itself; starts APPLIED."""
    return get_success_data(
        client.create_license(
            factories.license_payload(producer["id"], state_code, **overrides),
            make_producer_user_headers(producer["id"]),
        )
    )


def issue_license(client, license_id, state) -> JsonObject:
    """Issue an APPLIED license as the regulator of the licensing state."""
    return get_success_data(
        client.issue_license(license_id, make_state_regulator_headers(state["id"]))
    )


def revoke_license(client, license_id, state) -> JsonObject:
    return get_success_data(
        client.revoke_license(license_id, make_state_regulator_headers(state["id"]))
    )


def setup_issued_license(client, npn: str = "P-1", state_code: str = "CA",
                         **license_overrides) -> Bundle:
    """State + producer + one ISSUED license (active_license_count == 1)."""
    state = create_state(client, code=state_code)
    producer = create_producer(client, npn=npn, home_state_code=state["code"])
    license_row = create_license(client, producer, state["code"], **license_overrides)
    issued = issue_license(client, license_row["id"], state)
    return Bundle(state=state, producer=read_producer(client, producer["id"]),
                  license=issued)


# ---------------------------------------------------------- market conduct calls
def create_call(client, state, call_code: str = "MC-100", **overrides) -> JsonObject:
    """Open a data call; the lead state is the acting regulator's own state."""
    return get_success_data(
        client.create_market_conduct_call(
            factories.call_payload(call_code=call_code, **overrides),
            make_state_regulator_headers(state["id"]),
        )
    )


def add_response(client, call_id, insurer, direct_premium_cents: int = 100000000,
                 complaint_count: int = 0, **overrides) -> JsonObject:
    """File the insurer's response; score and escalation_flag are computed."""
    return get_success_data(
        client.create_response(
            call_id,
            factories.response_payload(direct_premium_cents, complaint_count, **overrides),
            make_insurer_user_headers(insurer["id"]),
        )
    )


def close_call(client, call_id, state) -> JsonObject:
    """Close an OPEN call as the regulator of its lead state; runs the
    cost-share assessment over its responses."""
    return get_success_data(
        client.close_call(call_id, make_state_regulator_headers(state["id"]))
    )


def list_responses(client, call_id) -> list:
    body = client.list_responses(call_id, STAFF).json()
    assert body.get("response_type") == "array", "responses must be a list envelope"
    return body["data"]


def setup_call_with_responses(client, premiums, call_code: str = "MC-100",
                              total_cost_cents: int = None,
                              state_code: str = "CA",
                              naic_start: int = 90001) -> Bundle:
    """An OPEN call led by one state with one response per premium in
    ``premiums`` (insurers are registered on the fly). Returns the state, the
    insurers, the call, and the responses in creation order."""
    state = create_state(client, code=state_code)
    insurers = [
        create_insurer(client, str(naic_start + index), state["code"])
        for index in range(len(premiums))
    ]
    kwargs = {"total_cost_cents": total_cost_cents} if total_cost_cents else {}
    call = create_call(client, state, call_code=call_code, **kwargs)
    responses = [
        add_response(client, call["id"], insurer, premium)
        for insurer, premium in zip(insurers, premiums)
    ]
    return Bundle(state=state, insurers=insurers, call=call, responses=responses)


# ------------------------------------------------------- coverage cascade setups
def setup_publish_cascade_ready(client, model_code: str = "MDL-101",
                                state_code: str = "CA",
                                variation_class: str = "SUBSTANTIALLY_SIMILAR",
                                ) -> Bundle:
    """v1 of a core act line PUBLISHED with the state's adoption CERTIFIED;
    v2 of the same line ADOPTED and awaiting publish. Publishing v2 supersedes
    v1, supersedes the adoption, and recomputes coverage. The state is
    registered once and shared by both acts' ballots."""
    state = create_state(client, code=state_code)
    state_map = {state_code: state}
    v1 = create_published_act(
        client, voting=(state_code,), state_map=state_map,
        model_code=model_code, version_label="v1", is_core=True,
        title="Model Act v1",
    )
    adoption = create_adoption(client, v1.act, state)
    certified = certify_adoption(client, adoption["id"], variation_class)
    # v2 exposes over the second default window so the clock keeps moving
    # strictly forward (v1's close already advanced it to the first window end).
    v2 = create_adopted_act(
        client, voting=(state_code,), state_map=state_map,
        exposure_start=SECOND_EXPOSURE_START, exposure_end=SECOND_EXPOSURE_END,
        model_code=model_code, version_label="v2", is_core=True,
        title="Model Act v2",
    )
    return Bundle(state=state, act_v1=v1.act, act_v2=v2.act, adoption=certified,
                  states=state_map)
