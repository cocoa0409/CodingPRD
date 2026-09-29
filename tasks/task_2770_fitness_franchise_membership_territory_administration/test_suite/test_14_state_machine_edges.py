"""Declared edges, refused edges and the bubble-up writes that ride along with them.

Initial states, terminal-state lockdowns and non-idempotent transitions across the relocation
review, the plan library, the membership contract, the transfer handshake and the inspection
file — each paired with the counters that must or must not move alongside.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_approved_promotion,
    create_member,
    create_plan_template,
    create_promotion,
    create_published_plan_template,
    create_relocation_request_payload,
    create_usage_settlement,
    create_usage_settlement_payload,
    file_relocation_request,
    file_transfer_request,
    inspect_club,
    make_club_manager_headers,
    make_franchise_owner_headers,
    open_club,
    post_dues,
    post_payment,
    post_usage_settlement,
    publish_plan_template,
    read_agreement,
    read_club,
    read_franchisee,
    read_guest_usage_event,
    read_inspection,
    read_member,
    read_plan_template,
    read_promotion,
    read_relocation_request,
    read_territory,
    read_transfer_request,
    relocation_decision_payload,
    request_cancellation,
    reverse_usage_settlement,
    score_inspection_payload,
    set_clock_date,
    setup_guest_usage_scenario,
    setup_home_and_host_clubs,
    setup_single_club_franchise,
    sign_active_agreement,
    sign_agreement,
    submit_relocation_request,
    withdraw_relocation_payload,
    withdraw_relocation_request,
)

BRAND = TEST_USERS["brand_administrator_headers"]

FILED_LAT = 34.02
FILED_LNG = -118.02


def _open_club_franchise(club_name: str = "Harborline Downtown") -> dict:
    return setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name=club_name,
        with_plan=False,
    )


def _filed_draft(scenario: dict) -> dict:
    return file_relocation_request(
        scenario["club"]["id"],
        scenario["franchisee"]["id"],
        requested_lat=FILED_LAT,
        requested_lng=FILED_LNG,
        requested_radius_km=5.0,
        justification="Anchor tenant lease not renewed; moving two miles north.",
    )


def test_a_freshly_filed_relocation_request_is_a_draft_with_nothing_stamped_on_it():
    """The draft records only what the owner asked for: no revisions, no submitter, no decision.

    PRD 3.1: "The draft is created in `DRAFT` with `revision_count` at 0, and only one request
    per club may be open at a time: a second draft is refused with `ERR_RELOCATION_PENDING` while
    an existing request is in `DRAFT`, `SUBMITTED` or `CHANGES_REQUESTED`."

    Design: Corner/state_machines/corner_relocation_request_is_created_in_draft_with_no_revisions_or_slack
    """
    scenario = _open_club_franchise()

    request = _filed_draft(scenario)
    assert request["status"] == "DRAFT"
    assert request["revision_count"] == 0
    assert request["submitted_by_user_id"] is None
    assert request["decided_by_user_id"] is None
    assert request["version"] == 1


def test_a_draft_holds_no_clearance_because_the_geometry_is_measured_only_on_submit():
    """Clearance is computed when the request goes to the brand, so a draft may legally hold
    coordinates nobody has measured yet, and the trade area has not moved.

    PRD 3.1: "Submitting the request for brand review moves it `DRAFT → SUBMITTED`, records
    `submitted_by_user_id` as the acting owner's identifier, and computes and stores the proposed
    circle's clearance into `encroachment_km` using the measurement above, run against other
    franchisees' territories."

    Design: Corner/state_machines/corner_relocation_request_is_created_in_draft_with_no_revisions_or_slack
    """
    scenario = _open_club_franchise()

    request = _filed_draft(scenario)
    assert request["encroachment_km"] is None
    territory = read_territory(scenario["territory"]["id"])
    assert territory["center_lat"] == 34.0
    assert territory["center_lng"] == -118.0
    assert territory["relocation_count"] == 0


def test_a_territory_holding_only_a_shell_stays_reserved():
    """Before the location trades, the trade area is merely reserved and both records are still on
    their first version.

    PRD 3.1: "A territory holding only a `PRE_OPENING` club stays `RESERVED`."

    Design: Corner/state_machines/corner_territory_bubbles_up_to_active_when_its_first_club_opens
    """
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
        open_the_club=False,
        with_plan=False,
    )

    territory = read_territory(scenario["territory"]["id"])
    assert territory["status"] == "RESERVED"
    assert territory["version"] == 1
    assert read_club(scenario["club"]["id"])["status"] == "PRE_OPENING"


def test_bringing_the_club_into_service_promotes_the_parent_territory():
    """Nothing addressed the territory endpoint, yet opening the club flips the trade area to
    active and advances both versions.

    PRD 3.1: "Opening bubbles up: if the parent territory is still `RESERVED`, it flips
    `RESERVED → ACTIVE` and its `version` increments, alongside the club's own `version`
    increment."

    Design: Corner/state_machines/corner_territory_bubbles_up_to_active_when_its_first_club_opens
    """
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
        open_the_club=False,
        with_plan=False,
    )

    opened = open_club(scenario["club"]["id"], scenario["franchisee"]["id"])
    assert opened["status"] == "OPEN"
    assert opened["version"] == 2
    territory = read_territory(scenario["territory"]["id"])
    assert territory["status"] == "ACTIVE"
    assert territory["version"] == 2


def test_publishing_a_published_template_a_second_time_is_refused():
    """Publication is not idempotent: the retry finds no `DRAFT` to advance and the template's
    version does not climb with the attempt.

    PRD 3.2: "Publishing an already-`PUBLISHED` template is refused with `ERR_INVALID_PLAN_STATE`,
    since the transition no longer exists from that state; `PUBLISHED` is terminal and a template
    is never unpublished or edited afterwards."

    Design: Corner/state_machines/corner_publishing_an_already_published_plan_template_is_rejected
    """
    template = create_plan_template(code="CORE12")
    publish_plan_template(template["id"])

    response = api_client.publish_plan_template(template["id"], {}, BRAND)
    validate_error(response, ApiErrorId.ERR_INVALID_PLAN_STATE.value)
    reread = read_plan_template(template["id"])
    assert reread["status"] == "PUBLISHED"
    assert reread["version"] == 2


def test_a_submitted_relocation_request_cannot_be_withdrawn_by_its_owner():
    """Once the brand owns the decision the franchisee cannot pull the request back, and the
    submitter stamp survives the refusal.

    PRD 3.1: "A `SUBMITTED` request is under active brand review and may not be withdrawn; the
    attempt is refused with `ERR_INVALID_RELOCATION_STATE`."

    Design: Corner/state_machines/corner_withdrawing_a_submitted_relocation_request_is_rejected
    """
    scenario = _open_club_franchise()
    franchisee_id = scenario["franchisee"]["id"]
    request = _filed_draft(scenario)
    submit_relocation_request(request["id"], franchisee_id)

    response = api_client.withdraw_relocation_request(
        request["id"],
        withdraw_relocation_payload(reason="Landlord reopened negotiations."),
        make_franchise_owner_headers(franchisee_id),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_RELOCATION_STATE.value)
    reread = read_relocation_request(request["id"])
    assert reread["status"] == "SUBMITTED"
    assert reread["submitted_by_user_id"] == franchisee_id
    assert reread["revision_count"] == 0


def test_a_withdrawn_relocation_request_can_never_be_submitted_again():
    """Withdrawal is terminal, so the abandoned row is not a route back into brand review.

    PRD 3.1: "Submitting from any state other than `DRAFT` or `CHANGES_REQUESTED` is refused with
    `ERR_INVALID_RELOCATION_STATE`."

    Design: Corner/state_machines/corner_withdrawn_relocation_request_cannot_be_resubmitted
    """
    scenario = _open_club_franchise()
    franchisee_id = scenario["franchisee"]["id"]
    request = _filed_draft(scenario)
    withdraw_relocation_request(
        request["id"], franchisee_id, reason="Landlord reopened negotiations."
    )

    response = api_client.submit_relocation_request(
        request["id"], {}, make_franchise_owner_headers(franchisee_id)
    )
    validate_error(response, ApiErrorId.ERR_INVALID_RELOCATION_STATE.value)
    reread = read_relocation_request(request["id"])
    assert reread["status"] == "WITHDRAWN"
    assert reread["submitted_by_user_id"] is None


def test_withdrawing_frees_the_club_to_file_a_fresh_relocation_request():
    """The withdrawn row no longer counts as an open request, so a second draft on the same club
    is accepted rather than blocked as pending.

    PRD 3.1: "The franchisee may also abandon its own request, moving it `DRAFT → WITHDRAWN` or
    `CHANGES_REQUESTED → WITHDRAWN` with an optional `reason`, which frees the club to draft a
    fresh one."

    Design: Corner/state_machines/corner_withdrawn_relocation_request_cannot_be_resubmitted
    """
    scenario = _open_club_franchise()
    franchisee_id = scenario["franchisee"]["id"]
    request = _filed_draft(scenario)
    withdraw_relocation_request(request["id"], franchisee_id)

    second = validate_success(
        api_client.create_relocation_request(
            create_relocation_request_payload(
                scenario["club"]["id"],
                requested_lat=34.03,
                requested_lng=-118.03,
                requested_radius_km=5.0,
                justification="Second attempt at a northern site.",
            ),
            make_franchise_owner_headers(franchisee_id),
        ),
        expected_status=201,
    )
    assert second["status"] == "DRAFT"
    assert second["revision_count"] == 0


def test_rejecting_a_relocation_leaves_the_territory_and_the_club_exactly_where_they_were():
    """The refusing branch writes only the request row; not one coordinate of the trade area or
    the club moves.

    PRD 3.1: "On `REJECT`, the request moves `SUBMITTED → REJECTED`, `decided_by_user_id` and
    `reviewer_note` are stored, and nothing else in the system changes at all: territory and club
    geometry are left exactly as they were, and only the request's own `version` increments."

    Design: Corner/state_machines/corner_rejected_relocation_leaves_territory_and_club_geometry_untouched
    """
    scenario = _open_club_franchise()
    franchisee_id = scenario["franchisee"]["id"]
    request = _filed_draft(scenario)
    submit_relocation_request(request["id"], franchisee_id)

    decided = validate_success(
        api_client.decide_relocation_request(
            request["id"],
            relocation_decision_payload(
                "REJECT", reviewer_note="Site fails brand frontage standard."
            ),
            BRAND,
        )
    )
    assert decided["status"] == "REJECTED"
    assert decided["decided_by_user_id"] == "brand-reviewer-1"
    assert decided["reviewer_note"] == "Site fails brand frontage standard."


def test_a_rejected_relocation_never_counts_against_the_relocation_tally():
    """The trade area keeps its original centre and radius and its relocation count stays at zero,
    while the club keeps the coordinates it inherited.

    PRD 3.1: "On `REJECT`, the request moves `SUBMITTED → REJECTED`, `decided_by_user_id` and
    `reviewer_note` are stored, and nothing else in the system changes at all: territory and club
    geometry are left exactly as they were, and only the request's own `version` increments."

    Design: Corner/state_machines/corner_rejected_relocation_leaves_territory_and_club_geometry_untouched
    """
    scenario = _open_club_franchise()
    franchisee_id = scenario["franchisee"]["id"]
    request = _filed_draft(scenario)
    submit_relocation_request(request["id"], franchisee_id)
    validate_success(
        api_client.decide_relocation_request(
            request["id"],
            relocation_decision_payload("REJECT", reviewer_note="Frontage standard unmet."),
            BRAND,
        )
    )

    territory = read_territory(scenario["territory"]["id"])
    assert territory["center_lat"] == 34.0
    assert territory["center_lng"] == -118.0
    assert territory["protected_radius_km"] == 5.0
    assert territory["relocation_count"] == 0
    club = read_club(scenario["club"]["id"])
    assert club["lat"] == 34.0
    assert club["lng"] == -118.0


def test_a_signed_but_unpaid_membership_cannot_be_put_on_hold():
    """The freeze edge leaves only `ACTIVE`, so a membership that has never taken a payment is
    refused and keeps its first version.

    PRD 3.5: "Three conditions must hold: the agreement must currently be `ACTIVE`, or the
    request is refused with `ERR_INVALID_AGREEMENT_STATE`; the acting manager must be the home
    club, or the request is refused with `ERR_NOT_RESOURCE_OWNER`; and the collections dimension
    must be `CURRENT` or `PAST_DUE`, so a membership that has already reached `DELINQUENT` or
    worse cannot be frozen out of trouble and is refused with `ERR_INVALID_DUES_STATE`."

    Design: Corner/state_machines/corner_freezing_a_pending_agreement_is_rejected
    """
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
    )
    member = create_member(
        scenario["club"]["id"], full_name="Noor Haddad", email="noor.haddad@example.com"
    )
    agreement = sign_agreement(
        member["id"], scenario["club"]["id"], scenario["plan_template"]["id"]
    )
    assert agreement["agreement_status"] == "PENDING"

    response = api_client.freeze_agreement(
        agreement["id"], {}, make_club_manager_headers(scenario["club"]["id"])
    )
    validate_error(response, ApiErrorId.ERR_INVALID_AGREEMENT_STATE.value)
    reread = read_agreement(agreement["id"])
    assert reread["agreement_status"] == "PENDING"
    assert reread["version"] == 1


def test_a_signed_but_unpaid_membership_contributes_to_no_club_counter():
    """The refused freeze cannot have moved a counter, because the membership was never in the
    denominator to begin with.

    PRD 3.4: "Until that payment arrives the membership is signed but not live, and it
    contributes to no club counter."

    Design: Corner/state_machines/corner_freezing_a_pending_agreement_is_rejected
    """
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
    )
    member = create_member(
        scenario["club"]["id"], full_name="Noor Haddad", email="noor.haddad@example.com"
    )
    agreement = sign_agreement(
        member["id"], scenario["club"]["id"], scenario["plan_template"]["id"]
    )
    validate_error(
        api_client.freeze_agreement(
            agreement["id"], {}, make_club_manager_headers(scenario["club"]["id"])
        ),
        ApiErrorId.ERR_INVALID_AGREEMENT_STATE.value,
    )

    club = read_club(scenario["club"]["id"])
    assert club["active_agreement_count"] == 0
    assert club["delinquent_member_count"] == 0


def _pending_membership() -> dict:
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
    )
    member = create_member(
        scenario["club"]["id"], full_name="Noor Haddad", email="noor.haddad@example.com"
    )
    scenario["member"] = member
    scenario["agreement"] = sign_agreement(
        member["id"], scenario["club"]["id"], scenario["plan_template"]["id"]
    )
    return scenario


def test_both_ledger_entries_are_stamped_to_the_billing_partner():
    """The charge and the settling payment are both client-appended entries, so each records the
    billing channel rather than the system as its origin.

    PRD 3.4: "`DUES_POSTED`, `PAYMENT_RECEIVED`, `PAYMENT_FAILED` and `WRITE_OFF` may be appended
    through the ledger endpoint by the `BillingPartner` or a `BrandAdministrator`, and those
    entries are stamped with `source` `BILLING_PARTNER`."

    Design: Corner/state_machines/corner_first_payment_received_activates_the_agreement_and_its_club_counter
    """
    scenario = _pending_membership()
    agreement_id = scenario["agreement"]["id"]

    charge = post_dues(agreement_id, 4500, "2026-08-01", "2026-09-05")
    payment = post_payment(agreement_id, 4500, "2026-08-01")
    assert charge["event_type"] == "DUES_POSTED"
    assert charge["source"] == "BILLING_PARTNER"
    assert payment["event_type"] == "PAYMENT_RECEIVED"
    assert payment["source"] == "BILLING_PARTNER"


def test_each_ledger_entry_snapshots_the_balance_that_it_left_behind():
    """The charge leaves 4500 outstanding and the payment that clears it leaves nothing, and each
    entry carries that figure as of its own append.

    PRD 3.4: "Every appended entry also stores `resulting_outstanding_balance_cents`, a snapshot
    of the agreement's outstanding balance immediately after that entry was folded into the
    projection, so the ledger can be replayed for audit."

    Design: Corner/state_machines/corner_first_payment_received_activates_the_agreement_and_its_club_counter
    """
    scenario = _pending_membership()
    agreement_id = scenario["agreement"]["id"]

    charge = post_dues(agreement_id, 4500, "2026-08-01", "2026-09-05")
    assert charge["resulting_outstanding_balance_cents"] == 4500
    payment = post_payment(agreement_id, 4500, "2026-08-01")
    assert payment["resulting_outstanding_balance_cents"] == 0


def test_the_first_paid_cent_makes_the_membership_live_and_moves_the_club_counter():
    """One payment does double duty: the contract dimension advances and the club's live-membership
    denominator gains a row, with the operator's score recomputed on the way out.

    PRD 3.4: "When a `PAYMENT_RECEIVED` entry with an `amount_cents` greater than 0 is the first
    such entry on the agreement, the contract dimension advances `PENDING → ACTIVE` in the same
    request: the home club's `active_agreement_count` increases by 1, `collections_watch` is
    recomputed from the new share, the owning franchisee's `compliance_score` is recomputed, and
    the agreement's and the club's `version` each increment."

    Design: Corner/state_machines/corner_first_payment_received_activates_the_agreement_and_its_club_counter
    """
    scenario = _pending_membership()
    post_dues(scenario["agreement"]["id"], 4500, "2026-08-01", "2026-09-05")
    post_payment(scenario["agreement"]["id"], 4500, "2026-08-01")

    assert read_agreement(scenario["agreement"]["id"])["agreement_status"] == "ACTIVE"
    club = read_club(scenario["club"]["id"])
    assert club["active_agreement_count"] == 1
    assert club["delinquent_member_count"] == 0
    assert club["collections_watch"] is False
    franchisee = read_franchisee(scenario["franchisee"]["id"])
    assert franchisee["compliance_score"] == 100
    assert franchisee["status"] == "ACTIVE"


def test_the_settled_charge_leaves_the_projection_paid_up_and_flat():
    """The single charge and the matching payment cancel out, so the money the club has collected
    is recorded while nothing remains outstanding.

    PRD 3.4: "`dues_paid_cents` is the sum of `amount_cents` over every `PAYMENT_RECEIVED` entry.
    The write-off total is the sum of `amount_cents` over every `WRITE_OFF` entry.
    `outstanding_balance_cents` is the sum of the charge amounts minus the payment total minus the
    write-off total, and it may legitimately go to zero or below."

    Design: Corner/state_machines/corner_first_payment_received_activates_the_agreement_and_its_club_counter
    """
    scenario = _pending_membership()
    post_dues(scenario["agreement"]["id"], 4500, "2026-08-01", "2026-09-05")
    post_payment(scenario["agreement"]["id"], 4500, "2026-08-01")

    agreement = read_agreement(scenario["agreement"]["id"])
    assert agreement["dues_paid_cents"] == 4500
    assert agreement["outstanding_balance_cents"] == 0
    assert agreement["dues_status"] == "CURRENT"


def test_scoring_an_inspection_that_has_already_been_scored_is_refused():
    """The scoring edge exists only out of `SCHEDULED`, and the closed file has long since left
    that state, so the second visit's numbers are refused.

    PRD 3.9: "Scoring is the auditor's act and is available only from `SCHEDULED`; scoring
    anything else is refused with `ERR_INVALID_INSPECTION_STATE`."

    Design: Corner/state_machines/corner_scoring_an_already_scored_inspection_is_rejected
    """
    scenario = _open_club_franchise()
    inspection = inspect_club(scenario["club"]["id"], "2026-07-15", 95, 92, 90, 12)
    assert inspection["score"] == 91

    response = api_client.score_inspection(
        inspection["id"],
        score_inspection_payload(80, 80, 80, 24),
        TEST_USERS["compliance_auditor_headers"],
    )
    validate_error(response, ApiErrorId.ERR_INVALID_INSPECTION_STATE.value)
    reread = read_inspection(inspection["id"])
    assert reread["score"] == 91
    assert reread["status"] == "CLOSED"


def test_the_refused_rescore_leaves_the_original_cascade_standing():
    """Nothing about the club or its operator is re-derived from the rejected numbers: the passing
    score of 91 still governs.

    PRD 3.9: "The club's `last_inspection_score` is set to the new `score`, and its
    `equipment_compliance_state` is re-derived from that score alone: `COMPLIANT` at 85 or above,
    `WATCH` at 70 through 84, and `NON_COMPLIANT` below 70. A club that has just become
    `NON_COMPLIANT` and was `OPEN` moves to `SUSPENDED`; a club that was `SUSPENDED` and has just
    scored 70 or better moves back to `OPEN`. The franchisee's `inspection_fail_streak` and
    `compliance_score` are then recomputed, which may demote the franchisee and withdraw its
    approved promotions. Finally the inspection auto-resolves: `SCORED → CLOSED` when the `score`
    is 70 or higher, and `SCORED → REMEDIATION_REQUIRED` when it is below 70."

    Design: Corner/state_machines/corner_scoring_an_already_scored_inspection_is_rejected
    """
    scenario = _open_club_franchise()
    inspection = inspect_club(scenario["club"]["id"], "2026-07-15", 95, 92, 90, 12)
    validate_error(
        api_client.score_inspection(
            inspection["id"],
            score_inspection_payload(40, 40, 40, 200),
            TEST_USERS["compliance_auditor_headers"],
        ),
        ApiErrorId.ERR_INVALID_INSPECTION_STATE.value,
    )

    club = read_club(scenario["club"]["id"])
    assert club["last_inspection_score"] == 91
    assert club["equipment_compliance_state"] == "COMPLIANT"
    assert club["status"] == "OPEN"
    franchisee = read_franchisee(scenario["franchisee"]["id"])
    assert franchisee["inspection_fail_streak"] == 0
    assert franchisee["compliance_score"] == 100


def _requested_transfer_between_sibling_clubs() -> dict:
    scenario = setup_home_and_host_clubs()
    member = create_member(
        scenario["home_club"]["id"], full_name="Dario Fuentes", email="dario.fuentes@example.com"
    )
    agreement = sign_active_agreement(
        member["id"],
        scenario["home_club"]["id"],
        scenario["plan_template"]["id"],
        multi_club_access=False,
    )
    scenario["member"] = member
    scenario["agreement"] = agreement
    scenario["request"] = file_transfer_request(
        agreement["id"],
        scenario["home_club"]["id"],
        scenario["host_club"]["id"],
        reason="Member changed jobs to the other side of the valley",
    )
    return scenario


def test_completing_a_transfer_that_was_never_approved_is_refused():
    """Completion is reachable only from `APPROVED`, so the receiving club cannot skip the
    decision step and execute the move straight out of `REQUESTED`.

    PRD 2.6: "The target record is in a state from which the requested transition exists. Only a
    `SCHEDULED` inspection may be scored; only a `DRAFT` or `CHANGES_REQUESTED` relocation request
    may be submitted; only an `OPEN` settlement may be posted; only a `PUBLISHED` plan template
    may back a new agreement; only an `OPEN` club may host a new agreement or receive a transfer;
    and only a `RESERVED` territory may take a new club shell, so a territory that has already
    reached `ACTIVE` because its club opened is refused with `ERR_INVALID_TERRITORY_STATE`. The
    codes in this band are `ERR_INVALID_TERRITORY_STATE`, `ERR_CLUB_NOT_OPERATIONAL`,
    `ERR_INVALID_RELOCATION_STATE`, `ERR_PLAN_NOT_PUBLISHED`, `ERR_INVALID_PLAN_STATE`,
    `ERR_INVALID_PROMOTION_STATE`, `ERR_INVALID_AGREEMENT_STATE`, `ERR_INVALID_DUES_STATE`,
    `ERR_INVALID_TRANSFER_STATE`, `ERR_INVALID_SETTLEMENT_STATE`, `ERR_INVALID_INSPECTION_STATE`,
    `ERR_INVALID_ROYALTY_STATE`, `ERR_INVALID_ALLOCATION_STATE` and
    `ERR_CORPORATE_ACCOUNT_SUSPENDED`, all HTTP 409."

    Design: Corner/state_machines/corner_completing_a_requested_transfer_before_approval_is_rejected
    """
    scenario = _requested_transfer_between_sibling_clubs()

    response = api_client.complete_transfer_request(
        scenario["request"]["id"], {}, make_club_manager_headers(scenario["host_club"]["id"])
    )
    validate_error(response, ApiErrorId.ERR_INVALID_TRANSFER_STATE.value)
    request = read_transfer_request(scenario["request"]["id"])
    assert request["status"] == "REQUESTED"
    assert request["transfer_fee_cents"] is None
    assert request["effective_on"] is None


def test_the_refused_completion_moves_no_membership_and_no_counter():
    """Because the execution never ran, the membership is still billed by the releasing club and
    neither club's live-membership counter has changed hands.

    PRD 3.6: "First, the agreement's `home_club_id` is rewritten to the `to_club_id` and its
    `transfer_count` increments by 1. Second, because the agreement's home club moved, both clubs'
    counters are recomputed from the share definition of §3.4 — the releasing club loses this
    agreement from its `active_agreement_count` and, where applicable, from its
    `delinquent_member_count`, the receiving club gains it, and `collections_watch` is recomputed
    on both."

    Design: Corner/state_machines/corner_completing_a_requested_transfer_before_approval_is_rejected
    """
    scenario = _requested_transfer_between_sibling_clubs()
    validate_error(
        api_client.complete_transfer_request(
            scenario["request"]["id"], {}, make_club_manager_headers(scenario["host_club"]["id"])
        ),
        ApiErrorId.ERR_INVALID_TRANSFER_STATE.value,
    )

    agreement = read_agreement(scenario["agreement"]["id"])
    assert agreement["home_club_id"] == scenario["home_club"]["id"]
    assert agreement["transfer_count"] == 0
    assert read_club(scenario["home_club"]["id"])["active_agreement_count"] == 1
    assert read_club(scenario["host_club"]["id"])["active_agreement_count"] == 0


def _cancelled_inside_the_california_cooling_off_window() -> dict:
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
    )
    member = create_member(
        scenario["club"]["id"], full_name="Priya Raghavan", email="priya.raghavan@example.com"
    )
    agreement = sign_active_agreement(
        member["id"],
        scenario["club"]["id"],
        scenario["plan_template"]["id"],
        multi_club_access=False,
    )
    set_clock_date("2026-08-05")
    scenario["member"] = member
    scenario["cancellation"] = request_cancellation(
        agreement["id"], member["id"], reason="Changed my mind about the twelve-month term"
    )
    scenario["agreement"] = agreement
    return scenario


def test_a_rescission_four_days_after_signature_refunds_every_cent_collected():
    """Four whole days is inside California's five-day window, so the initiation fee and the one
    month of dues both come back with no termination fee against them.

    PRD 3.5: "When the number of whole days from `signed_on` to the logical clock date is at most
    the statute's cooling-off days — 5 for `CA`, 3 for `TX`, 3 for `NY` — the consumer is inside
    their statutory right of rescission and the contract unwinds immediately.
    `cancellation_effective_on` is set to the logical clock date itself, with no notice period at
    all. `refund_cents` is the sum of `initiation_fee_cents` and `dues_paid_cents`, which is every
    cent the club has collected. `early_termination_fee_cents` is 0, and `net_settlement_cents`
    therefore equals `refund_cents`."

    Design: Corner/state_machines/corner_last_agreement_cancellation_flips_the_member_to_inactive
    """
    scenario = _cancelled_inside_the_california_cooling_off_window()

    cancelled = scenario["cancellation"]
    assert cancelled["cancellation_requested_on"] == "2026-08-05"
    assert cancelled["cancellation_effective_on"] == "2026-08-05"
    assert cancelled["refund_cents"] == 9400
    assert cancelled["early_termination_fee_cents"] == 0
    assert cancelled["net_settlement_cents"] == 9400


def test_losing_its_only_membership_makes_the_member_inactive():
    """The immediate unwind fires the whole cascade at once: the club's live count drops to zero,
    and the member — now holding nothing — is deactivated.

    PRD 3.5: "The contract dimension goes straight to `CANCELLED`, and because a live membership
    just disappeared, the cascade fires in full: the home club's `active_agreement_count`
    decreases by 1 and its `delinquent_member_count` and `collections_watch` are recomputed;
    because those club counters moved, the owning franchisee's `compliance_score` is recomputed;
    the member's `agreement_count` decreases by 1 and, if it has reached 0, the member flips to
    `INACTIVE`; the corporate account's enrolled agreement count is recomputed where a
    `corporate_account_id` applies; and the agreement's, the club's and the member's `version`
    each increment by 1."

    Design: Corner/state_machines/corner_last_agreement_cancellation_flips_the_member_to_inactive
    """
    scenario = _cancelled_inside_the_california_cooling_off_window()

    assert scenario["cancellation"]["agreement_status"] == "CANCELLED"
    member = read_member(scenario["member"]["id"])
    assert member["agreement_count"] == 0
    assert member["status"] == "INACTIVE"
    club = read_club(scenario["club"]["id"])
    assert club["active_agreement_count"] == 0
    assert club["collections_watch"] is False
    assert read_franchisee(scenario["franchisee"]["id"])["compliance_score"] == 100


def _probation_after_two_failures_with_two_promotions() -> dict:
    """One operator holding an APPROVED summer promotion and a PENDING_REVIEW autumn promotion,
    driven onto probation by two consecutive failing inspections."""
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
    )
    franchisee_id = scenario["franchisee"]["id"]
    elite = create_published_plan_template(
        code="ELITE24",
        monthly_dues_cents=7900,
        initiation_fee_cents=9900,
        term_months=24,
        floor_price_cents=6300,
    )
    scenario["approved_promotion"] = create_approved_promotion(
        franchisee_id,
        scenario["plan_template"]["id"],
        code="CORESUMMER",
        discount_pct=0.10,
        starts_on="2026-07-01",
        ends_on="2026-09-30",
    )
    scenario["pending_promotion"] = create_promotion(
        franchisee_id,
        elite["id"],
        code="ELITEFALL",
        discount_pct=0.10,
        starts_on="2026-10-01",
        ends_on="2026-12-31",
    )
    inspect_club(scenario["club"]["id"], "2026-07-10", 60, 60, 60, 60)
    scenario["second_inspection"] = inspect_club(
        scenario["club"]["id"], "2026-07-20", 60, 60, 60, 60
    )
    return scenario


def test_a_second_failing_inspection_puts_the_operator_on_probation():
    """Two consecutive failures cost 40 points off a clean 100, and 60 is strictly below the
    threshold, so the operator is demoted.

    PRD 3.9: "`compliance_score` then starts at 100 and subtracts 20 for each step of
    `inspection_fail_streak`, a flat 20 if `collections_watch_club_count` is greater than zero —
    one flat penalty no matter how many clubs are on watch, not 20 per club — and 10 for each
    disputed royalty report, with the result clamped into 0 through 100. If the franchisee is
    `ACTIVE` and the freshly recomputed score is strictly below 70, the franchisee is demoted
    `ACTIVE → PROBATION`, which withdraws every `APPROVED` promotion it owns; a score of exactly
    70 keeps it `ACTIVE`."

    Design: Corner/state_machines/corner_probation_withdraws_only_approved_promotions_and_spares_pending_review
    """
    scenario = _probation_after_two_failures_with_two_promotions()

    assert scenario["second_inspection"]["score"] == 51
    assert scenario["second_inspection"]["status"] == "REMEDIATION_REQUIRED"
    club = read_club(scenario["club"]["id"])
    assert club["equipment_compliance_state"] == "NON_COMPLIANT"
    assert club["status"] == "SUSPENDED"
    franchisee = read_franchisee(scenario["franchisee"]["id"])
    assert franchisee["inspection_fail_streak"] == 2
    assert franchisee["compliance_score"] == 60
    assert franchisee["status"] == "PROBATION"


def test_probation_withdraws_the_approved_promotion_and_spares_the_one_under_review():
    """The sweep is keyed on `APPROVED` alone: the live summer discount is pulled with a reason
    recorded, while the autumn filing still awaiting a decision is left exactly as it was.

    PRD 3.2: "When the owning franchisee is demoted from `ACTIVE` to `PROBATION` by the compliance
    cascade of §3.9, every promotion of that franchisee whose `status` is `APPROVED` moves
    `APPROVED → WITHDRAWN_BY_BRAND`, has its `withdrawn_reason` set to the string
    `FRANCHISEE_PROBATION`, and has its `version` incremented — one increment per withdrawn
    promotion."

    Design: Corner/state_machines/corner_probation_withdraws_only_approved_promotions_and_spares_pending_review
    """
    scenario = _probation_after_two_failures_with_two_promotions()

    withdrawn = read_promotion(scenario["approved_promotion"]["id"])
    assert withdrawn["status"] == "WITHDRAWN_BY_BRAND"
    assert withdrawn["withdrawn_reason"] == "FRANCHISEE_PROBATION"
    spared = read_promotion(scenario["pending_promotion"]["id"])
    assert spared["status"] == "PENDING_REVIEW"
    assert spared["withdrawn_reason"] is None


def _posted_then_reversed_settlement() -> dict:
    """Two August visit batches worth 105000 cents gross, settled, posted and then reversed."""
    scenario = setup_guest_usage_scenario(period_visits=[("2026-08", 50), ("2026-08", 34)])
    settlement = create_usage_settlement(
        "2026-08", scenario["home_club"]["id"], scenario["host_club"]["id"]
    )
    assert settlement["gross_fee_cents"] == 105000
    post_usage_settlement(settlement["id"])
    scenario["settlement"] = reverse_usage_settlement(
        settlement["id"], reason="Host club disputed the August visit log"
    )
    return scenario


def test_reversing_a_posted_settlement_unwinds_both_ledgers_and_releases_the_batches():
    """The compensating action returns both club ledgers to zero and clears the sweep flag from
    every batch it had collected.

    PRD 3.7: "It advances `POSTED → REVERSED`, adds `net_payable_cents` back to the home club's
    `settlement_ledger_cents` and subtracts the same amount from the host club's, clears
    `settlement_id` back to null on every batch the settlement had swept — making those batches
    eligible for a later settlement of the same triple — records `reversed_on` as the logical clock
    date, and increments the settlement's `version` and both clubs' `version` values by 1 each."

    Design: Corner/state_machines/corner_settlement_reversal_restores_unsettled_usage_and_permits_a_fresh_settlement
    """
    scenario = _posted_then_reversed_settlement()

    assert scenario["settlement"]["status"] == "REVERSED"
    assert scenario["settlement"]["reversed_on"] == "2026-08-01"
    for event in scenario["guest_usage_events"]:
        assert read_guest_usage_event(event["id"])["settlement_id"] is None
    assert read_club(scenario["home_club"]["id"])["settlement_ledger_cents"] == 0
    assert read_club(scenario["host_club"]["id"])["settlement_ledger_cents"] == 0


def test_the_released_batches_may_be_swept_into_a_fresh_settlement():
    """A reversed settlement no longer occupies the month-and-pair triple, so the same two batches
    are settleable again and are re-stamped with the new settlement's identifier.

    PRD 3.7: "Reversing anything that is not `POSTED` is refused with
    `ERR_INVALID_SETTLEMENT_STATE`, and `REVERSED` is terminal — a reversed settlement is never
    re-posted, though the released batches may be swept into a fresh one."

    Design: Corner/state_machines/corner_settlement_reversal_restores_unsettled_usage_and_permits_a_fresh_settlement
    """
    scenario = _posted_then_reversed_settlement()

    replacement = validate_success(
        api_client.create_usage_settlement(
            create_usage_settlement_payload(
                "2026-08", scenario["home_club"]["id"], scenario["host_club"]["id"]
            ),
            BRAND,
        ),
        expected_status=201,
    )
    assert replacement["status"] == "OPEN"
    assert replacement["id"] != scenario["settlement"]["id"]
    for event in scenario["guest_usage_events"]:
        assert read_guest_usage_event(event["id"])["settlement_id"] == replacement["id"]


def test_the_second_sweep_reproduces_the_whole_waterfall_from_the_released_batches():
    """Both batches come back into scope, so the replacement settlement recomputes the identical
    84 visits, 105000 gross, 8400 hold, three-percent tier and 93702 payable.

    PRD 3.7: "`event_count` is the number of swept rows and `visit_count` is the sum of their visit
    counts. `gross_fee_cents` is the sum of their `usage_fee_cents`. Step one, the brand's
    administration hold: `admin_hold_cents` is `gross_fee_cents` multiplied by 0.08 — eight percent
    — rounded half up to whole cents. Step two: `net_before_rebate_cents` is `gross_fee_cents`
    minus `admin_hold_cents`. Step three, tier selection, which is keyed on
    `net_before_rebate_cents` and on nothing else — never on `gross_fee_cents` and never on the
    final payable: `rebate_pct` is 0.00 when `net_before_rebate_cents` is below 50000 cents, 0.03
    when it is at least 50000 but below 100000 cents, and 0.06 when it is at or above 100000 cents.
    Step four, and only now: `volume_rebate_cents` is `net_before_rebate_cents` multiplied by
    `rebate_pct`, rounded half up to whole cents. Finally `net_payable_cents` is
    `net_before_rebate_cents` minus `volume_rebate_cents`."

    Design: Corner/state_machines/corner_settlement_reversal_restores_unsettled_usage_and_permits_a_fresh_settlement
    """
    scenario = _posted_then_reversed_settlement()

    replacement = validate_success(
        api_client.create_usage_settlement(
            create_usage_settlement_payload(
                "2026-08", scenario["home_club"]["id"], scenario["host_club"]["id"]
            ),
            BRAND,
        ),
        expected_status=201,
    )
    assert replacement["event_count"] == 2
    assert replacement["visit_count"] == 84
    assert replacement["gross_fee_cents"] == 105000
    assert replacement["admin_hold_cents"] == 8400
    assert replacement["net_before_rebate_cents"] == 96600
    assert replacement["rebate_pct"] == 0.03
    assert replacement["volume_rebate_cents"] == 2898
    assert replacement["net_payable_cents"] == 93702
