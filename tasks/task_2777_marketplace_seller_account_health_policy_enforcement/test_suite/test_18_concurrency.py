"""The two version expectations a client must carry, and the atomicity of the one
cascade that touches five entities at once: a stale writer is refused without
leaving a trace, and the retry prices itself against the world as it now stands.
"""

from test_helpers import (
    INVESTIGATOR,
    OFFICER,
    ApiErrorId,
    acknowledge,
    assert_cents,
    assert_funds,
    assert_instant_equals,
    assert_points,
    assert_posture,
    create_listing,
    credit,
    file_violation,
    hold_payload,
    issue_action,
    open_hold,
    open_investigation,
    poa_payload,
    publish_rule,
    read_action,
    read_holds,
    read_notices,
    read_seller,
    register_seller,
    set_clock,
    substantiated_violation,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00.000Z"
COVERAGE_START = "2026-08-02T00:00:00.000Z"
COVERAGE_END = "2026-08-05T00:00:00.000Z"

PLAN_ROOT_CAUSE = (
    "Our supplier feed mapped compatibility attributes onto the wrong parent listing."
)
PLAN_CORRECTIVE = ["Corrected the attribute mapping for every affected listing"]
PLAN_PREVENTIVE = ["Nightly automated diff of the feed against the published catalogue"]


def _harbor_tools(api, **overrides):
    payload = {"legal_name": "Harbor Tools LLC", "email": "ops@harbor-tools.example",
               "tax_id_hash": "TAX-HT-0001", "payout_bank_token": "BANK-HT-0001",
               "address_fingerprint": "ADDR-HT-0001"}
    payload.update(overrides)
    return register_seller(api, **payload)


def _reserve_request(api, seller_id, expected_version):
    return api.create_hold(
        hold_payload(seller_id, COVERAGE_START, COVERAGE_END, expected_version,
                     hold_type="RESERVE", reserve_basis="ROLLING"),
        INVESTIGATOR,
    )


# --------------------------------------------------------------------------
# The seller version a reserve is priced against
# --------------------------------------------------------------------------
def test_a_credit_between_the_read_and_the_write_invalidates_the_reserve(api):
    """PRD §2.10: "If the seller's `version` has advanced since — because another hold
    was created or released, because proceeds were credited, or because a posture
    cascade ran — the amount the client believes it is reserving is no longer the
    amount the server would compute, so the stale writer is refused with
    `ERR_STALE_SELLER_VERSION` (HTTP 412) instead of silently reserving a different
    figure."

    Design: Corner/cross_cutting_complexity_layers/occ_hold_creation_is_refused_on_a_stale_seller_version
    """
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="LA-OCC1-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = _harbor_tools(api)
    credit(api, seller["id"], 100000, "PAYOUT-CYCLE-2026-07-O")
    violation = file_violation(
        api, seller["id"], rule["id"], reporter_type="BUYER",
        evidence_reference="EV-OCC1-0001",
    )
    open_investigation(api, violation["id"])

    # The investigator's snapshot of the seller, taken before the interleaving write.
    stale = read_seller(api, seller["id"], INVESTIGATOR)
    assert_cents(stale["available_balance_cents"], 100000, "available_balance_cents")
    topped_up = credit(api, seller["id"], 50000, "PAYOUT-CYCLE-2026-07-P")
    assert_cents(topped_up["available_balance_cents"], 150000, "available_balance_cents")
    assert topped_up["version"] == stale["version"] + 1

    refused = _reserve_request(api, seller["id"], stale["version"])

    validate_error(refused, ApiErrorId.STALE_SELLER_VERSION.value, 412)
    assert read_holds(api, params={"seller_id": seller["id"]}) == []
    fresh = read_seller(api, seller["id"], INVESTIGATOR)
    assert_cents(fresh["held_balance_cents"], 0, "held_balance_cents")
    # A refusal is not a mutation: the version the retry will carry is unchanged.
    assert fresh["version"] == topped_up["version"]

    retried = validate_success(_reserve_request(api, seller["id"], fresh["version"]), 201)

    # Ten percent of the balance as it now stands, never of the balance the caller
    # first read.
    assert_cents(retried["held_amount_cents"], 15000, "held_amount_cents")
    assert retried["risk_tier"] == "TIER_1"
    assert retried["state"] == "ACTIVE"
    after = read_seller(api, seller["id"])
    assert_funds(after, available=135000, held=15000, credited=150000, debited=0)
    assert after["version"] == fresh["version"] + 1


# --------------------------------------------------------------------------
# The action version a plan is answered against
# --------------------------------------------------------------------------
def test_the_sellers_own_acknowledgement_invalidates_its_own_plan_token(api):
    """PRD §2.10: "A fresh submission legitimately supersedes the seller's prior
    returned plan, so the operation cannot be refused on state alone; but if the
    action's `version` has advanced — because it was acknowledged, because a plan
    against it was reviewed, or because an appeal outcome resolved it — the seller is
    answering a version of the action that no longer exists, and the submission is
    refused with `ERR_STALE_ACTION_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_plan_submission_is_refused_on_a_stale_action_version
    """
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="LA-OCC2-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=True,
    )
    seller = _harbor_tools(api)
    violation = substantiated_violation(
        api, seller["id"], rule["id"], reporter_type="BUYER",
        evidence_reference="EV-OCC2-0001",
        decision_note="The compatibility list on the listing named a part it does not fit.",
    )
    action = issue_action(api, violation["id"])
    assert_instant_equals(action["issued_at"], CLOCK, "issued_at")

    acknowledged = acknowledge(api, action["id"], seller["id"])
    assert acknowledged["state"] == "ACKNOWLEDGED"
    assert acknowledged["version"] == action["version"] + 1

    def submission(expected_version):
        return api.create_plan_of_action(
            poa_payload(action["id"], expected_version, root_cause=PLAN_ROOT_CAUSE,
                        corrective_measures=PLAN_CORRECTIVE,
                        preventive_measures=PLAN_PREVENTIVE),
            {"X-User-Role": "Seller", "X-User-ID": seller["id"],
             "Content-Type": "application/json"},
        )

    refused = submission(action["version"])

    # The concurrency stage answers before the one-open-plan slot check and before
    # any state check, so no slot is consumed.
    validate_error(refused, ApiErrorId.STALE_ACTION_VERSION.value, 412)
    plans, plan_meta = validate_paginated(api.list_plans_of_action(OFFICER))
    assert plans == [] and plan_meta["total_count"] == 0
    fresh = read_action(api, action["id"])
    assert fresh["version"] == acknowledged["version"]

    submitted = validate_success(submission(fresh["version"]), 201)

    assert submitted["state"] == "SUBMITTED"
    assert submitted["revision_count"] == 0
    # Seventeen days from the action's own issuance, not from the submission.
    assert_instant_equals(submitted["deadline_at"], "2026-08-18T00:00:00.000Z",
                          "deadline_at")
    assert read_action(api, action["id"])["version"] == fresh["version"] + 1


# --------------------------------------------------------------------------
# One issuance, five entities, one version increment
# --------------------------------------------------------------------------
def test_the_whole_suspension_cascade_is_readable_on_the_next_call(api):
    """PRD §3.6: "Whichever rung applies, the seller's `version` increments by one and
    an `ACTION_ISSUED` notice goes out disclosing `policy_rule_code`,
    `severity_points_disclosed`, `appeal_deadline_at`, and the cited violation's
    `evidence_reference`; where the adjudication recorded a `decision_note`, that text
    is disclosed as the notice's `decision_rationale`."

    Design: Corner/consistency_model/consistency_every_cascade_effect_is_readable_in_the_same_breath
    """
    set_clock(api, CLOCK)
    # PRD §3.2 caps base_severity_weight at 8.00, so the twelve points that select
    # ACCOUNT_SUSPENSION on a first offence come from PRD §3.6's rights-owner
    # escalation: 8.00 x 1.00 (first offence) x 1.50 (IP + RIGHTS_OWNER) = 12.00.
    rule = publish_rule(
        api, code="IP-CONS-1", category="INTELLECTUAL_PROPERTY", base_severity_weight=8.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = _harbor_tools(api)
    credit(api, seller["id"], 100000, "PAYOUT-CYCLE-2026-07-C")
    listing = create_listing(
        api, seller["id"], sku="SKU-CONS-0001", title="18V Cordless Drill",
        category_code="TOOLS",
    )
    assert listing["state"] == "ACTIVE"
    open_investigation(
        api,
        file_violation(api, seller["id"], rule["id"], reporter_type="RIGHTS_OWNER",
                       evidence_reference="EV-CONS-0002")["id"],
    )
    prior = open_hold(api, seller["id"], COVERAGE_START, COVERAGE_END)
    assert_cents(prior["held_amount_cents"], 10000, "held_amount_cents")
    substantiated = substantiated_violation(
        api, seller["id"], rule["id"], reporter_type="RIGHTS_OWNER",
        evidence_reference="EV-CONS-0001",
        decision_note="Three listings misdescribed the material of the tool handles.",
    )
    before = read_seller(api, seller["id"], INVESTIGATOR)
    assert_posture(before, disbursement_state="RESERVE_HELD")
    assert_cents(before["held_balance_cents"], 10000, "held_balance_cents")

    action = validate_success(
        api.create_enforcement_action({"violation_id": substantiated["id"]}, INVESTIGATOR),
        201,
    )

    # The issuance response already carries every computed field.
    assert_points(action["severity_points_applied"], "12.00", "severity_points_applied")
    assert action["ladder_rung_computed"] == "ACCOUNT_SUSPENSION"
    assert action["action_type"] == "ACCOUNT_SUSPENSION"
    assert action["removed_listing_count"] == 0

    # And the very next reads, with no clock movement, show the finished cascade.
    after = read_seller(api, seller["id"])
    assert_posture(after, enforcement_state="SUSPENDED", disbursement_state="FULL_HOLD",
                   severity_points_balance="12.00")
    assert_funds(after, available=0, held=100000, credited=100000, debited=0)
    # Five entities moved, and the seller's version moved exactly once.
    assert after["version"] == before["version"] + 1

    suppressed = validate_success(
        api.list_seller_listings(seller["id"], OFFICER, {"state": "SUPPRESSED"})
    )
    assert [row["id"] for row in suppressed] == [listing["id"]]
    assert suppressed[0]["suppressed_by_suspension"] is True

    superseded = validate_success(api.get_hold(prior["id"], OFFICER))
    assert superseded["state"] == "RELEASED"
    assert superseded["release_reason"] == "SUPERSEDED_BY_FULL_HOLD"

    active = read_holds(api, params={"seller_id": seller["id"], "state": "ACTIVE"})
    assert len(active) == 1, f"expected one sweeping hold, got {active}"
    assert active[0]["id"] != prior["id"]
    assert active[0]["hold_type"] == "FULL_HOLD"
    assert active[0]["auto_created"] is True
    # Release-then-mint: the swept figure includes the 10000 the prior hold returned.
    assert_cents(active[0]["held_amount_cents"], 100000, "held_amount_cents")

    held_notices = read_notices(api, seller["id"], params={"template_code": "FUNDS_HELD"})
    disclosed = {int(notice["amount_cents"]): notice for notice in held_notices}
    assert sorted(disclosed) == [10000, 100000], f"disclosures were {sorted(disclosed)}"
    assert disclosed[100000]["state"] == "SENT"
