"""Cross-cutting layers: the one optimistic-concurrency token in the service, the many writes that
can invalidate it, and the deepest cascade a permit decision can set off.

The three probes here share a shape: a token or a state is captured, unrelated writes move the world
underneath it, and the assertions pin both what changed and what deliberately did not.
"""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_paginated

from test_helpers import (
    ApiErrorId,
    OFFICER_1,
    api_client,
    assert_aums,
    assert_pct,
    make_officer_headers,
    make_specialist_headers,
)
from test_helpers import factories as f
from test_helpers.fixtures import (
    create_allotment,
    create_base_property,
    create_closure_order,
    create_permit,
    create_permittee,
    drafted_aoi_setup,
    get_allotment,
    get_aoi,
    get_bill,
    get_closure_order,
    get_decision,
    get_pasture,
    get_permit,
    get_permittee,
    issue_aoi,
    issued_aoi_setup,
    lift_closure_order,
    signed_decision,
)


def _decisions_on(allotment_id):
    """The filtered total_count of the decisions authored against one allotment."""
    _items, meta = validate_paginated(api_client.list_decisions(
        make_specialist_headers(), {"allotment_id": allotment_id, "limit": 100}))
    return meta["total_count"]


def test_the_decision_version_token_is_compared_for_equality_and_never_for_recency():
    """One observation of the allotment's version is deliberately reused after it has gone stale. The
    first authorship consumes it and bumps the version by exactly one, so the second authorship quoting
    the very same figure is refused; and a figure three ahead of the server is refused with the identical
    code, which is what distinguishes an equality comparison from an at-least test. Both refusals are
    inert: they write no decision, they vacate no predecessor, and they contribute no bump of their own,
    so the allotment ends exactly two versions on from where it started and the collection holds exactly
    the two documents that were accepted. The second accepted document supersedes the first, taking it
    straight to VACATED with no capacity consequence whatsoever.

    PRD 2.7: "A decision-authoring request must therefore carry `expected_allotment_version`, a
    non-optional integer field holding the `version` of the target allotment as the client last observed
    it. If that value does not equal the allotment's current `version`, the request is rejected with
    `ERR_STALE_ALLOTMENT_VERSION` and HTTP 412, and nothing is written."
    PRD 2.7: "A newly authored draft decision legitimately vacates any earlier decision of the same
    `decision_type` on the same allotment that is still in `DRAFT` or `PROPOSED`."
    PRD 2.6: "**Optimistic concurrency** — `ERR_STALE_ALLOTMENT_VERSION`, HTTP 412, on authoring a
    permit decision, exactly as specified in §2.7."
    PRD 2.4: "`version` is an integer that starts at 1 when the resource is created and increases by
    exactly 1 on every mutation of that resource, whether the mutation was requested directly by a
    client or applied as a side effect of an operation on some other resource."
    PRD 3.8: "The new decision lands in `decision_status` `DRAFT` with `nepa_status` `PENDING`,
    `nepa_findings_summary` null, `pre_decision_adjustment_pct` null, `deciding_officer_id` null and
    `effective_date` null unless supplied, and its `authoring_officer_id` is stamped with the authoring
    specialist's `X-User-ID`."
    PRD 3.8: "And it **supersedes** any earlier decision of the same `decision_type` on the same
    allotment that is still in `decision_status` `DRAFT` or `PROPOSED`: each such predecessor moves
    straight to `VACATED`."
    PRD 3.8: "That supersession is deliberately effect-free — a decision that has not yet become
    effective never applied a cascade, so nothing is unwound, no bill is superseded, and the
    predecessor's `pre_decision_adjustment_pct`, still null, is simply discarded."
    PRD 3.8: "Authorship itself bumps the allotment's `version`, which means two decisions authored
    back to back against the same allotment cannot both quote the same `expected_allotment_version`; the
    second author must re-read the allotment first."

    Design: Corner/cross_cutting_complexity_layers/corner_stale_allotment_version_refused_then_correct_version_accepted
    """
    allotment = create_allotment(name="Version Probe Allotment", admin_unit_code="QB-183",
                                 acres=9500, total_permitted_aums=800,
                                 required_pasture_rotation_count=1)
    holder = create_permittee(name="Version Probe Cattle",
                             contact_email="versionprobe.qb183@example.com")
    prop = create_base_property(holder["id"], carrying_capacity_aums=400,
                               legal_description="T18N R44E Sec 09 NE")
    permit = create_permit(allotment["id"], holder["id"], prop["id"], requested_aums=200)

    # A single observation, taken after every setup write, and then deliberately reused.
    version_0 = get_allotment(allotment["id"])["version"]

    first = get_success_data(api_client.create_decision(
        f.decision_payload(allotment["id"], version_0, permit_id=permit["id"],
                           rationale="First issuance document authored against a fresh reading."),
        make_specialist_headers()), 201)
    assert first["decision_status"] == "DRAFT"
    assert first["pre_decision_adjustment_pct"] is None

    validate_error(api_client.create_decision(
        f.decision_payload(allotment["id"], version_0, permit_id=permit["id"],
                           rationale="Second document authored from the same, now stale, reading."),
        make_specialist_headers()), ApiErrorId.ERR_STALE_ALLOTMENT_VERSION, 412)

    version_1 = get_allotment(allotment["id"])["version"]
    assert version_1 == version_0 + 1, "exactly one bump, from the one authorship that succeeded"

    validate_error(api_client.create_decision(
        f.decision_payload(allotment["id"], version_1 + 3, permit_id=permit["id"],
                           rationale="Document authored with a version ahead of the server's."),
        make_specialist_headers()), ApiErrorId.ERR_STALE_ALLOTMENT_VERSION, 412)

    second = get_success_data(api_client.create_decision(
        f.decision_payload(allotment["id"], version_1, permit_id=permit["id"],
                           rationale="Second document authored after re-reading the allotment."),
        make_specialist_headers()), 201)
    assert second["decision_status"] == "DRAFT"
    assert second["id"] != first["id"]

    after = get_allotment(allotment["id"])
    assert after["version"] == version_0 + 2, "the two refusals contributed no bump of their own"
    assert _decisions_on(allotment["id"]) == 2, "the two refusals created nothing"

    superseded = get_decision(first["id"])
    assert superseded["decision_status"] == "VACATED"
    assert superseded["pre_decision_adjustment_pct"] is None
    assert_pct(after["stocking_adjustment_pct"], 0.0)
    assert after["allotment_status"] == "OPEN"
    assert after["effective_capacity_aums"] == 800


def test_writes_the_client_never_made_invalidate_the_token_it_is_holding():
    """Six endpoints can move an allotment's version and only one of them accepts a version field, so a
    token a specialist holds can be invalidated by hands it cannot see. Issuing an instruction rewrites
    the capacity ledger, concurring with an assessment rewrites the health determination, and opening a
    closure order rewrites the posture: three separate writes, three bumps of exactly one each, and the
    token captured before them is refused at the end. Then the restoring direction is shown to be no
    gentler — lifting the order puts every figure back where it was and still bumps the version, so even
    a write that undoes another write invalidates a token; only a freshly re-read figure is accepted.

    PRD 2.4: "Because `version` moves on side-effect mutations as well as direct ones, an allotment's
    `version` advances whenever its capacity ledger, posture or health determination is rewritten — when
    a closure order is issued or lifted, when a health assessment is finalized with a concurrence, when a
    decision document is authored against it, and when a decision is made effective or vacated."
    PRD 2.7: "No other operation in this service accepts a version field."
    PRD 2.7: "If that value does not equal the allotment's current `version`, the request is rejected
    with `ERR_STALE_ALLOTMENT_VERSION` and HTTP 412, and nothing is written."
    PRD 3.4: "The `aoi_status` becomes `ISSUED`, `authorized_aums_at_issue` is re-stamped from
    `authorized_aums`, the allotment's `allocated_aums` and `open_aums` are recomputed by the ledger of
    §2.9 — `allocated_aums` rising by exactly this instruction's `billable_aums` — the allotment's
    `version` is bumped, and `scheduled_aums` is refreshed on every pasture the instruction's use records
    name."
    PRD 3.7: "A `CONCUR` outcome moves `FIELD_REVIEW → FINALIZED`, computes `composite_score` and
    `determination`, computes `recommended_reduction_pct`, writes the resulting `determination` onto the
    allotment's `health_determination`, and bumps the allotment's `version`."
    PRD 3.10: "The order lands in `order_status` `ACTIVE` with `issuing_officer_id` stamped from the
    issuing officer's `X-User-ID`."
    PRD 3.10: "The `effective_capacity_aums` becomes the `carrying_capacity_aums` multiplied by one
    minus `stocking_adjustment_pct`, floored to a whole AUM — so a 0.40 reduction on a carrying capacity
    of 1,000 AUMs yields 600, and a total closure yields 0."
    PRD 3.10: "For every operating instruction of the allotment whose `grazing_year` equals the
    allotment's `current_grazing_year` and whose `aoi_status` is `ISSUED` or `USE_REPORTED`, the
    `authorized_aums` becomes the instruction's own `authorized_aums_at_issue` snapshot multiplied by one
    minus `stocking_adjustment_pct`, floored to a whole AUM, and `billable_aums` becomes the new
    `authorized_aums` less `nonuse_aums`."
    PRD 3.10: "The allotment's `version` is bumped once for the whole cascade."
    PRD 3.10: "The order moves `ACTIVE → LIFTED` and the identical five-hop cascade re-runs over the
    **remaining** sources, so a lift recomputes rather than subtracts: lifting a 0.40 drought order while
    a 0.30 effective stocking adjustment survives leaves the allotment at 0.30 and `RESTRICTED`, not at
    0.0 and `OPEN`."
    PRD 3.8: "Authorship itself bumps the allotment's `version`, which means two decisions authored
    back to back against the same allotment cannot both quote the same `expected_allotment_version`; the
    second author must re-read the allotment first."

    Design: Corner/cross_cutting_complexity_layers/corner_every_allotment_write_path_bumps_the_version
    """
    setup = drafted_aoi_setup(
        authorized_aums=100, planned_head_count=100, planned_entry_date="2026-06-01",
        planned_exit_date="2026-07-01", total_permitted_aums=1000, pasture_aum_capacity=1000,
        carrying_capacity_aums=500, requested_aums=200,
        allotment_overrides={"name": "Bump Ladder Allotment", "admin_unit_code": "QB-184",
                             "acres": 14000})
    allotment_id = setup["allotment"]["id"]

    assessment = get_success_data(api_client.create_assessment(
        f.assessment_payload(allotment_id, standards_not_met=[],
                             causal_factor_is_livestock=False), make_specialist_headers()), 201)
    submitted = get_success_data(api_client.submit_assessment(
        assessment["id"], make_specialist_headers()))
    assert submitted["assessment_status"] == "FIELD_REVIEW"

    # Captured last, so it is the client's freshest possible reading before the sequence begins.
    version_0 = get_allotment(allotment_id)["version"]

    issued = issue_aoi(setup["aoi"]["id"])
    assert issued["aoi_status"] == "ISSUED"
    assert issued["authorized_aums_at_issue"] == 100

    concurred = get_success_data(api_client.review_assessment(
        assessment["id"], f.review_payload(
            review_notes="Indicator scores support a meeting determination."),
        make_officer_headers(OFFICER_1)))
    assert concurred["determination"] == "MEETING"
    assert get_allotment(allotment_id)["health_determination"] == "MEETING"

    order = create_closure_order(
        allotment_id, order_type="DROUGHT_REDUCTION", reduction_pct=0.30,
        effective_start_date="2026-08-10", effective_end_date="2026-09-10",
        justification="Persistent drought requires a temporary thirty percent reduction.")
    assert order["order_status"] == "ACTIVE"
    reduced = get_allotment(allotment_id)
    assert_pct(reduced["stocking_adjustment_pct"], 0.30)
    assert reduced["effective_capacity_aums"] == 700  # floor(1000 x 0.70)
    assert reduced["allotment_status"] == "RESTRICTED"
    assert get_aoi(setup["aoi"]["id"])["authorized_aums"] == 70  # floor(100 x 0.70)

    validate_error(api_client.create_decision(
        f.decision_payload(allotment_id, version_0, permit_id=setup["permit"]["id"],
                           rationale="Authored from a token captured before three other writes."),
        make_specialist_headers()), ApiErrorId.ERR_STALE_ALLOTMENT_VERSION, 412)

    version_3 = get_allotment(allotment_id)["version"]
    assert version_3 == version_0 + 3, "three separate endpoints each bumped exactly one"

    lifted = lift_closure_order(order["id"])
    assert lifted["order_status"] == "LIFTED"
    assert get_closure_order(order["id"])["order_status"] == "LIFTED"
    restored = get_allotment(allotment_id)
    assert_pct(restored["stocking_adjustment_pct"], 0.0)
    assert restored["effective_capacity_aums"] == 1000
    assert restored["allotment_status"] == "OPEN"
    assert get_aoi(setup["aoi"]["id"])["authorized_aums"] == 100, "restored from the snapshot"

    version_4 = restored["version"]
    assert version_4 == version_3 + 1, "even a restoring write invalidates a token"

    accepted = get_success_data(api_client.create_decision(
        f.decision_payload(allotment_id, version_4, permit_id=setup["permit"]["id"],
                           rationale="Authored from a freshly re-read token."),
        make_specialist_headers()), 201)
    assert accepted["decision_status"] == "DRAFT"
    assert _decisions_on(allotment_id) == 1, "only the authorship that quoted the live figure survived"


def test_making_a_cancellation_effective_runs_a_four_hop_chain_from_one_named_permit():
    """The request names nothing but the decision, and each hop is caused only by the one before it. The
    permit is cancelled; because it is cancelled its issued instruction is voided; because that
    instruction is voided its outstanding bill is voided and its forage returns to the allotment's ledger
    and to its pasture's roll-up; because the bill is voided the permittee's balance falls to zero and the
    permit's billing axis reads CURRENT. What the chain does not touch is just as pinned: the snapshot
    authorized_aums_at_issue is history and is never rewritten, the allotment's posture and capacity are
    untouched because a cancellation is not a reduction, the whole cascade rides inside a single version
    bump, and replaying the call is refused so the AUMs cannot be released twice.

    PRD 3.8: "Putting a decision into effect is the moment its consequences reach the rangeland, and it
    is reserved to the same `AuthorizedOfficer` who signed it: the acting `X-User-ID` must equal
    `deciding_officer_id`, and any other officer is refused with `ERR_UNAUTHORIZED`."
    PRD 3.8: "The decision must be in `decision_status` `FINAL`, else `ERR_DECISION_STATE_INVALID`, and
    it must not be frozen by an appeal — a decision in `decision_status` `STAYED` yields
    `ERR_DECISION_STAYED`."
    PRD 3.8: "Two fields are stamped **before** any cascade runs: `effective_date` takes the
    logical-clock date in `YYYY-MM-DD` form, and `pre_decision_adjustment_pct` takes a snapshot of the
    allotment's `stocking_adjustment_pct` **as it stands before the adjustment is applied**."
    PRD 3.8: "Then `decision_status` becomes `EFFECTIVE`, the type-specific cascade runs, and the
    allotment's `version` is bumped once."
    PRD 3.8: "A `CANCELLATION` decision moves the named permit to `permit_status` `CANCELLED`, voids
    that permit's instructions in `aoi_status` `DRAFT` or `ISSUED`, and returns the permit's
    `permitted_aums` to the allotment ledger so that `allocated_aums` falls and `open_aums` rises."
    PRD 2.9: "The AUM invariant: an allotment's `open_aums` plus its `allocated_aums` always equals its
    `effective_capacity_aums`."
    PRD 2.9: "The compensation invariant: if an allotment's `allocated_aums` is A before an operating
    instruction is issued, then after issuance it is A plus that instruction's `billable_aums`, and after
    that same instruction is voided it is A again — exactly A, with no drift — while `open_aums` returns
    to `effective_capacity_aums` less A."
    PRD 2.9: "A permittee's `outstanding_balance_cents` always equals the sum, over that permittee's
    bills whose `bill_status` is `ISSUED` or `DELINQUENT`, of each bill's `total_amount_cents` less its
    `amount_paid_cents`; bills in `PAID` or `VOIDED` contribute nothing, and an `ADJUSTMENT_CREDIT` bill
    contributes its negative total and so reduces the balance."
    PRD 2.9: "A permittee's `permittee_status` is derived from the same aggregate: it is `DEBT_FLAGGED`
    exactly when `outstanding_balance_cents` is greater than zero **and** at least one of the contributing
    bills is in `bill_status` `DELINQUENT`, and `IN_GOOD_STANDING` in every other case — so an unpaid bill
    that is not yet overdue leaves the permittee `IN_GOOD_STANDING`."
    PRD 2.9: "`allocated_aums` is the sum, over every annual operating instruction whose permit belongs
    to this allotment, whose `grazing_year` equals the allotment's `current_grazing_year`, and whose
    `aoi_status` is one of `ISSUED`, `USE_REPORTED`, `BILLED` or `CLOSED`, of that instruction's
    `authorized_aums` less its `nonuse_aums`."
    PRD 3.1: "Its `scheduled_aums` is the sum of `planned_aums` over every use record naming that
    pasture whose owning operating instruction has a `grazing_year` equal to the allotment's
    `current_grazing_year` and an `aoi_status` of `ISSUED`, `USE_REPORTED`, `BILLED` or `CLOSED`; the
    figure is carried to 2 decimal places and starts at 0."
    PRD 3.6: "`FINAL_USE`, raised when an accepted use report replaces an unpaid preliminary bill;
    `REVISED_USE`, raised when a capacity movement supersedes an unpaid use bill"

    Design: Corner/cross_cutting_complexity_layers/corner_cancellation_decision_cascades_permit_aoi_bill_and_ledger
    """
    setup = issued_aoi_setup(
        authorized_aums=100, planned_head_count=100, planned_entry_date="2026-06-01",
        planned_exit_date="2026-07-01", total_permitted_aums=1000, pasture_aum_capacity=1000,
        carrying_capacity_aums=500, requested_aums=200,
        allotment_overrides={"name": "Cancellation Cascade Allotment",
                             "admin_unit_code": "QB-185", "acres": 13000})
    allotment_id = setup["allotment"]["id"]
    permittee_id = setup["permittee"]["id"]
    bill = setup["preliminary_bill"]
    assert bill is not None
    assert bill["total_amount_cents"] == 17200  # 100 AUMs x 172, no admin fee under 50,000
    assert bill["bill_status"] == "ISSUED"

    before = get_allotment(allotment_id)
    assert before["allocated_aums"] == 100
    assert before["open_aums"] == 900
    assert_aums(get_pasture(setup["pasture"]["id"])["scheduled_aums"], 100.00)
    assert get_permittee(permittee_id)["outstanding_balance_cents"] == 17200
    version_before = before["version"]

    decision = signed_decision(
        allotment_id, decision_type="CANCELLATION", permit_id=setup["permit"]["id"],
        nepa_level="EA",
        rationale="Repeated willful unauthorized use warrants cancellation of the permit.")
    assert decision["decision_status"] == "FINAL"
    assert decision["deciding_officer_id"] == OFFICER_1

    effective = get_success_data(api_client.make_decision_effective(
        decision["id"], make_officer_headers(OFFICER_1)))
    assert effective["decision_status"] == "EFFECTIVE"
    assert effective["effective_date"] == "2026-08-01", "the logical-clock date, not an authored date"
    assert_pct(effective["pre_decision_adjustment_pct"], 0.0)

    # Hop one: the permit named by the decision.
    cancelled = get_permit(setup["permit"]["id"])
    assert cancelled["permit_status"] == "CANCELLED"
    assert cancelled["suspension_reason"] is None

    # Hop two: the instruction beneath that permit.
    voided_aoi = get_aoi(setup["aoi"]["id"])
    assert voided_aoi["aoi_status"] == "VOIDED"
    assert voided_aoi["authorized_aums_at_issue"] == 100, "the snapshot is history, never rewritten"

    # Hop three: the money and the forage that instruction held.
    voided_bill = get_bill(bill["id"])
    assert voided_bill["bill_status"] == "VOIDED"
    assert voided_bill["amount_paid_cents"] == 0
    after = get_allotment(allotment_id)
    assert after["allocated_aums"] == 0
    assert after["open_aums"] == 1000
    assert after["open_aums"] + after["allocated_aums"] == after["effective_capacity_aums"]
    assert_aums(get_pasture(setup["pasture"]["id"])["scheduled_aums"], 0.00)

    # Hop four: the permittee's standing.
    settled = get_permittee(permittee_id)
    assert settled["outstanding_balance_cents"] == 0
    assert settled["permittee_status"] == "IN_GOOD_STANDING"
    assert get_permit(setup["permit"]["id"])["account_status"] == "CURRENT"

    assert after["version"] == version_before + 2, "one bump for authorship, one for the cascade"
    assert_pct(after["stocking_adjustment_pct"], 0.0)
    assert after["allotment_status"] == "OPEN"
    assert after["effective_capacity_aums"] == 1000, "a cancellation is not a reduction"

    validate_error(api_client.make_decision_effective(
        decision["id"], make_officer_headers(OFFICER_1)),
        ApiErrorId.ERR_DECISION_STATE_INVALID, 409)

    items, meta = validate_paginated(api_client.list_bills(
        make_officer_headers(), {"permittee_id": permittee_id, "limit": 100}))
    assert meta["total_count"] == 1, "no replacement bill is raised by a cancellation"
    assert items[0]["id"] == bill["id"]
    assert items[0]["bill_status"] == "VOIDED"
