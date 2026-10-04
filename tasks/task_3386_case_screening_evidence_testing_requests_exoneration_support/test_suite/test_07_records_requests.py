"""Records pipeline: reveal legality against the item's current location, the
three-link destruction cascade into policy pattern counts, and the denial /
appeal loop feeding RECORDS_TRANSPARENCY."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_records_request,
    create_jurisdiction,
    create_records_request,
    get_case,
    get_evidence_item,
    list_rows,
    records_advance_payload,
    respond_records_request,
    revealed_item,
    setup_accepted_case,
    setup_case_with_destroyed_evidence,
    setup_case_with_item,
    setup_policy_initiative,
    setup_submitted_records_request,
    validate_error,
)

POLICY = TEST_USERS["policy_director_headers"]
ANALYST = TEST_USERS["evidence_analyst_headers"]


def _initiative_count(api, jurisdiction_id):
    data, _ = list_rows(api.list_jurisdiction_policy_initiatives(jurisdiction_id, POLICY))
    assert len(data) == 1
    return data[0]["pattern_case_count"]


def test_records_response_destroyed_rejected_for_confirmed_item(api):
    """PRD section 3.3: "Each reveal is legal only against the item's current
    location: `LOCATED` requires the item to be in `SEARCHING` or
    `REPORTED_MISSING`; `DESTROYED` requires `IDENTIFIED`, `SEARCHING`, or
    `REPORTED_MISSING`; `MISSING` requires `IDENTIFIED` or `SEARCHING` — an
    illegal reveal rejects the whole response with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/records_response_destroyed_rejected_for_confirmed_item
    """
    ctx = setup_case_with_item(
        jurisdiction_overrides={"state_code": "KS", "name": "Kansas"},
        begin_investigation=False,
    )
    item = ctx["item"]
    assert item["location_status"] == "CUSTODY_CONFIRMED"
    request = setup_submitted_records_request(
        ctx["case"]["id"], agency_type="LABORATORY", agency_name="State Crime Lab"
    )

    resp = api.advance_records_request(
        request["id"],
        records_advance_payload(
            "RECORD_RESPONSE",
            disposition="FULFILLED",
            items_revealed=[revealed_item(item["id"], "DESTROYED")],
        ),
        ANALYST,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    # Atomic rejection: neither entity mutates.
    assert get_evidence_item(item["id"])["location_status"] == "CUSTODY_CONFIRMED"
    rows, meta = list_rows(api.list_case_records_requests(ctx["case"]["id"], ANALYST))
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "SUBMITTED"
    assert rows[0]["response_disposition"] is None


def test_destroyed_reveal_cascade_item_and_case(api):
    """PRD section 3.3: "Every entry into `REPORTED_DESTROYED` increments the
    owning case's `destroyed_evidence_count` by one (the count never
    decrements), re-derives `evidence_posture`, refreshes the case's
    `updated_at` and `version`, and re-derives the `pattern_case_count` of
    every `EVIDENCE_PRESERVATION` policy initiative in the case's jurisdiction
    (§2.6, chain A)."
    PRD section 3.3: "with none confirmed and at least one destroyed,
    `FULLY_COMPROMISED`".

    Design: Difficulty/transitive_cascade/records_response_destroyed_cascade_reaches_policy_count
    """
    jurisdiction = create_jurisdiction(state_code="IL", name="Illinois")
    ctx = setup_case_with_destroyed_evidence(jurisdiction_id=jurisdiction["id"])

    # Link 1: the reveal mutates the item's location.
    assert ctx["item"]["location_status"] == "REPORTED_DESTROYED"
    # Link 2: the case's count and posture re-derive from the item mutation.
    assert ctx["case"]["destroyed_evidence_count"] == 1
    assert ctx["case"]["evidence_posture"] == "FULLY_COMPROMISED"
    assert ctx["records_request"]["status"] == "FULFILLED"
    assert ctx["records_request"]["response_disposition"] == "FULFILLED"


def test_destroyed_reveal_cascade_reaches_policy_count(api):
    """PRD section 2.6: "the response mutates the evidence item's location,
    the destruction increments the owning case's `destroyed_evidence_count`
    and re-derives its `evidence_posture`, and every evidence-preservation
    policy initiative in the case's jurisdiction has its `pattern_case_count`
    re-derived — three links past the triggering write."
    PRD section 3.9: "for `EVIDENCE_PRESERVATION`, a case whose
    `destroyed_evidence_count` is at least 1".

    Design: Difficulty/transitive_cascade/records_response_destroyed_cascade_reaches_policy_count
    """
    jurisdiction = create_jurisdiction(state_code="IL", name="Illinois")
    initiative = setup_policy_initiative(
        jurisdiction["id"],
        topic="EVIDENCE_PRESERVATION",
        title="Mandate evidence retention inventories",
    )
    assert initiative["pattern_case_count"] == 0, (
        "initial derivation finds no qualifying cases"
    )

    setup_case_with_destroyed_evidence(jurisdiction_id=jurisdiction["id"])

    # Link 3, observed via the initiative's own read path.
    assert _initiative_count(api, jurisdiction["id"]) == 1


def test_records_denial_feeds_records_transparency_pattern(api):
    """PRD section 3.3: "a denial additionally re-derives the
    `pattern_case_count` of every `RECORDS_TRANSPARENCY` initiative in the
    case's jurisdiction."
    PRD section 3.3: "A `DENIED` request may be appealed, moving to `APPEALED`,
    and an appealed request accepts a fresh response with the same rules —
    including another `DENIED`, which may itself be appealed again".
    PRD section 3.9: "The pattern count aggregates distinct cases in the
    initiative's jurisdiction".

    Design: Corner/calculations/records_denial_feeds_records_transparency_pattern
    """
    jurisdiction = create_jurisdiction(
        state_code="MS",
        name="Mississippi",
        has_post_conviction_dna_statute=False,
        clemency_available=False,
        compensation_statute_exists=False,
    )
    setup_policy_initiative(
        jurisdiction["id"],
        topic="RECORDS_TRANSPARENCY",
        title="Public-records compliance",
    )
    ctx = setup_accepted_case(jurisdiction_id=jurisdiction["id"])
    request = setup_submitted_records_request(ctx["case"]["id"])

    denied = respond_records_request(request["id"], "DENIED")
    assert denied["status"] == "DENIED"
    assert denied["response_disposition"] == "DENIED"
    appealed = advance_records_request(request["id"], "APPEAL")
    assert appealed["status"] == "APPEALED"
    denied_again = respond_records_request(request["id"], "DENIED")
    assert denied_again["status"] == "DENIED"

    # Distinct-case semantics: two denials of the SAME case count once.
    assert _initiative_count(api, jurisdiction["id"]) == 1
