"""Suspension, appeals, trust demotion cascade, and listing cycles."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    appeal_case,
    claim_listing,
    create_map_edit_payload,
    create_suspension_payload,
    decide_case,
    get_contributor,
    get_listing,
    make_business_owner_headers,
    make_contributor,
    make_contributor_headers,
    make_listing,
    make_map_edit,
    make_policy_analyst_headers,
    make_region,
    make_rejected_edit,
    make_verified_listing,
    open_edit_review_ticket,
    set_clock,
    start_appeal_review,
    suspend_listing,
    validate_error,
    validate_success,
    verify_listing,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PA1 = TEST_USERS["policy_analyst_headers"]
PA2 = TEST_USERS["policy_analyst2_headers"]

LONG_APPEAL = (
    "This appeal statement is deliberately long enough to pass the "
    "fifty character minimum length requirement."
)


def test_listing_reverify_cycle_then_suspension_overturn_reinstates(api):
    """PRD §3.3: "A second administrative sweep examines verified listings:
    any listing in `VERIFIED` whose `reverify_due_at` has been reached
    transitions to `REVERIFY_REQUIRED`, and any `ISSUED` verification attempt
    outstanding on such a listing is cancelled as the transition lands; the
    sweep reports a `transitioned_count`."
    PRD §3.3: "Completing a fresh verification from `REVERIFY_REQUIRED`
    refreshes `verified_at` and `reverify_due_at`, closing the cycle."
    PRD §3.6: "An `OVERTURNED` decision reinstates: the listing returns to
    `VERIFIED`, or to `REVERIFY_REQUIRED` instead when its `reverify_due_at`
    passed during the suspension — the system picks the stricter outcome — its
    `visibility` recomputes from health, the owner's trust penalty unwinds,
    and when the violation was keyword stuffing the listing's
    `keyword_stuffing_strikes` reset to 0."

    Design: Difficulty/non_linear_state_machine/listing_reverify_cycle_suspension_reinstatement
    """
    region = make_region(name="R6")
    owner = make_contributor(region["id"], display_name="C7", email="c7@x.com")
    listing, _ = make_verified_listing(region["id"], owner["id"],
                                       name="Lodge Six", method="POSTCARD")
    assert listing["status"] == "VERIFIED"

    # First cycle: VERIFIED -> REVERIFY_REQUIRED -> VERIFIED.
    set_clock("2027-09-02T00:00:00Z")
    sweep = validate_success(api.sweep_listings_reverify(ADMIN))
    assert sweep["transitioned_count"] >= 1
    listing = get_listing(listing["id"])
    assert listing["status"] == "REVERIFY_REQUIRED"
    listing, _attempt = verify_listing(listing["id"], owner["id"], method="PHONE")
    assert listing["status"] == "VERIFIED", "first cycle closes back to VERIFIED"

    # Second cycle: VERIFIED -> SUSPENDED -> (appeal OVERTURNED) -> VERIFIED.
    case = suspend_listing(listing["id"], analyst_id="pa-1",
                           violation_type="FAKE_ADDRESS",
                           evidence_notes="geocoded centroid lands in open water")
    appeal_case(case["id"], owner["id"],
                appeal_text="The address is correct; the geocoder pinned the "
                            "wrong parcel. Attached deed and utility bill prove "
                            "occupancy at the listed address.")
    start_appeal_review(case["id"], analyst_id="pa-2")
    decided = decide_case(case["id"], analyst_id="pa-2", decision="OVERTURNED")
    assert decided["status"] == "OVERTURNED"

    listing = get_listing(listing["id"])
    assert listing["status"] == "VERIFIED", (
        f"reinstated (fresh reverify_due_at is still in the future), "
        f"got {listing['status']}"
    )


def test_listing_reverify_sweep_cycle_closes(api):
    """PRD §3.3: "A second administrative sweep examines verified listings:
    any listing in `VERIFIED` whose `reverify_due_at` has been reached
    transitions to `REVERIFY_REQUIRED`, and any `ISSUED` verification attempt
    outstanding on such a listing is cancelled as the transition lands; the
    sweep reports a `transitioned_count`."
    PRD §3.3: "Completing a fresh verification from `REVERIFY_REQUIRED`
    refreshes `verified_at` and `reverify_due_at`, closing the cycle."

    Design: Difficulty/non_linear_state_machine/listing_reverify_cycle_suspension_reinstatement
    """
    region = make_region(name="R6b")
    owner = make_contributor(region["id"], display_name="C7b", email="c7b@x.com")
    listing, _ = make_verified_listing(region["id"], owner["id"],
                                       name="Lodge Six B", method="POSTCARD")

    set_clock("2027-09-02T00:00:00Z")
    sweep = validate_success(api.sweep_listings_reverify(ADMIN))
    assert sweep["transitioned_count"] >= 1
    listing = get_listing(listing["id"])
    assert listing["status"] == "REVERIFY_REQUIRED"
    listing, _attempt = verify_listing(listing["id"], owner["id"], method="PHONE")
    assert listing["status"] == "VERIFIED"
    assert listing["verification_method"] == "PHONE"


def test_suspension_edit_rejection_trust_demotion_cascade(api):
    """PRD §3.6: "Second, every map edit on the listing sitting in
    `SUBMITTED`, `QUEUED`, `IN_REVIEW`, or `NEEDS_MORE_INFO` is rejected with
    `rejection_reason` `POLICY` — a rejection storm."
    PRD §3.6: "Third, each of those rejections recomputes its author's trust,
    and any contributor whose `finalized_trust_score` falls below 20 is moved
    to `RESTRICTED`."
    PRD §3.6: "Contributor trust itself is a weighted ledger. Its base is 50,
    plus 3 points per published edit, minus 6 per rejected edit, minus 9 per
    reverted edit; reverted edits count in the reverted tally and are never
    double-counted as published."
    PRD §3.6: "First, a suspension case opens with the violation type and
    evidence, an `appeal_deadline` exactly 30 days out, and null `appeal_text`
    and `decided_by`."

    Design: Difficulty/transitive_cascade/suspension_edit_rejection_trust_demotion_cascade
    """
    region = make_region(name="R7")
    author = make_contributor(region["id"], display_name="C8", email="c8@x.com")
    owner = make_contributor(region["id"], display_name="C9", email="c9@x.com")
    listing, _ = make_verified_listing(region["id"], owner["id"],
                                       name="Hotel Seven", method="PHONE")

    for i in range(1, 7):
        make_rejected_edit(listing, author["id"], attribute=f"a{i}")

    pre = get_contributor(author["id"])
    assert pre["provisional_trust_score"] == 14, (
        f"50 - 6*6 = 14 before the cascade, got {pre['provisional_trust_score']}"
    )
    assert pre["status"] == "ACTIVE"

    # Queue the seventh edit while the author's finalized trust is still 50
    # (all edits younger than seven days), so its auto-score is 55 -> QUEUED.
    queued_edit = make_map_edit(listing, author["id"],
                                payload={"attribute": "a7", "value": True})
    assert queued_edit["status"] == "QUEUED"

    # PRD §2.4: only edits created at least seven days before the current
    # logical clock time count toward the finalized variant that gates
    # automatic restriction — age the six rejections past that window.
    set_clock("2026-09-10T00:00:00Z")

    case = suspend_listing(listing["id"], analyst_id="pa-1",
                           violation_type="IMPERSONATION",
                           evidence_notes="owner identity mismatch with "
                                          "registration records")
    assert case["status"] == "OPEN"

    edit_read = validate_success(api.get_map_edit(queued_edit["id"], ADMIN))
    assert edit_read["status"] == "REJECTED"
    assert edit_read["rejection_reason"] == "POLICY"

    post = get_contributor(author["id"])
    assert post["provisional_trust_score"] == 8, (
        f"cascade rejection drops provisional trust 14 - 6 = 8, "
        f"got {post['provisional_trust_score']}"
    )
    assert post["status"] == "RESTRICTED"


def test_suspension_cascade_rejects_open_edits_and_hides_listing(api):
    """PRD §3.6: "Second, every map edit on the listing sitting in
    `SUBMITTED`, `QUEUED`, `IN_REVIEW`, or `NEEDS_MORE_INFO` is rejected with
    `rejection_reason` `POLICY` — a rejection storm."
    PRD §3.6: "The listing itself becomes `SUSPENDED`, its `visibility`
    collapses to `HIDDEN`, its `version` increments, and any `ISSUED` or
    `CODE_SUBMITTED` verification attempt outstanding on it is cancelled."
    PRD §3.2: "A listing's `visibility` derives from status and health:
    `SUSPENDED` and `PERMANENTLY_CLOSED` listings are always `HIDDEN`;
    otherwise, a listing whose public health score falls below 30 becomes
    `RESTRICTED`; everything else is `PUBLIC`."

    Design: Difficulty/transitive_cascade/suspension_edit_rejection_trust_demotion_cascade
    """
    region = make_region(name="R7b")
    author = make_contributor(region["id"], display_name="C8b", email="c8b@x.com")
    owner = make_contributor(region["id"], display_name="C9b", email="c9b@x.com")
    listing, _ = make_verified_listing(region["id"], owner["id"],
                                       name="Hotel Seven B", method="PHONE")
    queued_edit = make_map_edit(listing, author["id"],
                                payload={"attribute": "a7", "value": True})

    suspend_listing(listing["id"], analyst_id="pa-1", violation_type="IMPERSONATION",
                    evidence_notes="owner identity mismatch")

    edit_read = validate_success(api.get_map_edit(queued_edit["id"], ADMIN))
    assert edit_read["status"] == "REJECTED"
    assert edit_read["rejection_reason"] == "POLICY"

    listing = get_listing(listing["id"])
    assert listing["status"] == "SUSPENDED"
    assert listing["visibility"] == "HIDDEN"


def test_terminal_permanently_closed_lockdown(api):
    """PRD §2.6: "State admissibility comes next — for example, resolving a
    ticket is only admissible on a `CLAIMED` ticket, submitting a code only on
    an `ISSUED` or `CODE_SUBMITTED` attempt, an appeal only on an `OPEN` case,
    scheduling only on a `PLANNED` task, and validating only on a `PROPOSED`
    routing update — with violations returning `ERR_INVALID_STATE`."
    PRD §3.6: "Suspension is admissible from `CLAIM_PENDING`, `VERIFIED`, or
    `REVERIFY_REQUIRED`."
    PRD §3.6: "An `UPHELD` decision permanently closes the listing: it becomes
    `PERMANENTLY_CLOSED`, stays `HIDDEN` and out of public lists while its
    reviews remain on record, and the owner's trust absorbs a permanent
    25-point penalty folded into the `finalized_trust_score`."

    Design: Corner/state_machines/terminal_permanently_closed_lockdown
    """
    region = make_region(name="RPC")
    owner = make_contributor(region["id"], display_name="OwnPC", email="own@x.com")
    listing, _ = make_verified_listing(region["id"], owner["id"],
                                       name="Closed Biz", method="RECORDS")
    case = suspend_listing(listing["id"], analyst_id="pa-1",
                           violation_type="IMPERSONATION",
                           evidence_notes="identity mismatch")
    appeal_case(case["id"], owner["id"], appeal_text=LONG_APPEAL)
    start_appeal_review(case["id"], analyst_id="pa-2")
    decide_case(case["id"], analyst_id="pa-2", decision="UPHELD")

    listing = get_listing(listing["id"])
    assert listing["status"] == "PERMANENTLY_CLOSED"

    resp = api.suspend_listing(
        listing["id"],
        create_suspension_payload(violation_type="FAKE_REVIEWS",
                                  evidence_notes="post-closure probe"),
        TEST_USERS["policy_analyst3_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    listing = get_listing(listing["id"])
    assert listing["status"] == "PERMANENTLY_CLOSED"


def test_keyword_stuffing_suspend_requires_two_strikes(api):
    """PRD §3.6: "One violation type carries a precondition: a
    keyword-stuffing suspension demands that the listing's
    `keyword_stuffing_strikes` have already reached 2; attempting it earlier
    is refused with `ERR_STRIKES_BELOW_THRESHOLD` (HTTP 409)."
    PRD §3.2: "Critically, the rejection still records a strike: the listing's
    `keyword_stuffing_strikes` increments by one on every such violation,
    persisting even though the write itself fails."

    Design: Corner/state_machines/keyword_stuffing_suspend_requires_two_strikes
    """
    region = make_region(name="RKS")
    owner = make_contributor(region["id"], display_name="OwnKS", email="own4@x.com")
    listing = make_listing(region["id"], name="Stuffing Biz")
    listing = claim_listing(listing, owner["id"])
    owner_headers = make_business_owner_headers(owner["id"])

    resp = api.suspend_listing(
        listing["id"],
        create_suspension_payload(violation_type="KEYWORD_STUFFING",
                                  evidence_notes="premature suspend attempt"),
        PA1,
    )
    validate_error(resp, ApiErrorId.ERR_STRIKES_BELOW_THRESHOLD)

    resp = api.update_listing(listing["id"], {"name": "BEST CHEAP Stuffing Biz"},
                              owner_headers)
    validate_error(resp, ApiErrorId.ERR_KEYWORD_STUFFING)
    resp = api.update_listing(
        listing["id"], {"name": "BEST CHEAP Stuffing Biz AGAIN TOP"}, owner_headers
    )
    validate_error(resp, ApiErrorId.ERR_KEYWORD_STUFFING)

    listing = get_listing(listing["id"])
    assert listing["keyword_stuffing_strikes"] == 2, (
        f"each rejected write persists a strike, got "
        f"{listing['keyword_stuffing_strikes']}"
    )

    resp = api.suspend_listing(
        listing["id"],
        create_suspension_payload(violation_type="KEYWORD_STUFFING",
                                  evidence_notes="two strikes recorded"),
        PA1,
    )
    case = validate_success(resp)
    assert case["status"] == "OPEN"
    assert case["violation_type"] == "KEYWORD_STUFFING"
    listing = get_listing(listing["id"])
    assert listing["status"] == "SUSPENDED"


def test_appeal_after_deadline_rejected(api):
    """PRD §3.6: "Submitting one requires the actor to be the listing's owner
    (`ERR_NOT_LISTING_OWNER` otherwise), the logical clock to be at or before
    the `appeal_deadline` — afterward the window is shut and the appeal is
    refused with `ERR_APPEAL_WINDOW_CLOSED` (HTTP 409) — and an `appeal_text`
    of at least 50 characters, shorter statements drawing
    `ERR_INVALID_REQUEST`."
    PRD §3.6: "First, a suspension case opens with the violation type and
    evidence, an `appeal_deadline` exactly 30 days out, and null `appeal_text`
    and `decided_by`."

    Design: Corner/state_machines/appeal_after_deadline_rejected
    """
    region = make_region(name="RApp")
    owner = make_contributor(region["id"], display_name="OwnApp", email="own5@x.com")
    listing = make_listing(region["id"], name="Appeal Biz")
    claim_listing(listing, owner["id"])
    case = suspend_listing(listing["id"], analyst_id="pa-1",
                           violation_type="FAKE_REVIEWS",
                           evidence_notes="coordinated review ring detected")

    set_clock("2026-10-02T00:00:00Z")
    resp = api.appeal_suspension_case(
        case["id"],
        {"appeal_text": "This late appeal statement is deliberately long "
                        "enough to pass the fifty character minimum length "
                        "requirement."},
        make_business_owner_headers(owner["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED)
    case_read = validate_success(api.get_suspension_case(case["id"], ADMIN))
    assert case_read["status"] == "OPEN"


def test_segregation_of_duties_same_analyst_cannot_review_own_suspension(api):
    """PRD §3.6: "Taking the appeal under review must be done by a policy
    analyst different from the one who suspended the listing; the suspending
    analyst attempting it is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP
    403). The reviewing analyst's id is recorded as `decided_by`, and the case
    moves to `UNDER_APPEAL_REVIEW`."

    Design: Corner/state_machines/segregation_of_duties_same_analyst_cannot_review_own_suspension
    """
    region = make_region(name="RSoD")
    owner = make_contributor(region["id"], display_name="OwnSoD", email="own6@x.com")
    listing = make_listing(region["id"], name="SoD Biz")
    claim_listing(listing, owner["id"])
    case = suspend_listing(listing["id"], analyst_id="pa-1",
                           violation_type="IMPERSONATION",
                           evidence_notes="identity mismatch")
    appeal_case(case["id"], owner["id"], appeal_text=LONG_APPEAL)

    resp = api.start_appeal_review(case["id"], PA1)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    resp = api.start_appeal_review(case["id"], PA2)
    reviewed = validate_success(resp)
    assert reviewed["status"] == "UNDER_APPEAL_REVIEW"
