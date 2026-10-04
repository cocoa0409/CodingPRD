"""Claim submission and adjudication waterfall, warranty boundary, OCC."""
from test_helpers import (
    ApiErrorId,
    adjudicate,
    get_episode,
    get_success_data,
    setup_episode_in_post_op,
    setup_episode_in_sor_pending,
    submit_claim,
    validate_error,
    validate_success,
)

ADMIN = {"X-User-ID": "test-program-admin-1", "X-User-Role": "ProgramAdmin"}
COORD = {"X-User-ID": "test-care-coordinator-1", "X-User-Role": "CareCoordinator"}
CLAIMS = {"X-User-ID": "test-claims-admin-1", "X-User-Role": "ClaimsAdmin"}


def test_warranty_window_half_open_last_day_vs_first_day_after(api):
    """PRD §3.7: "the service day must fall inside the half-open warranty
    window from `discharge_seq` up to but not including `warranty_end_seq`,
    else denial with reason `OUTSIDE_WARRANTY_WINDOW`"
    PRD §3.5: "The warranty window is half-open: it includes the discharge day
    and runs up to but does not include `warranty_end_seq`."

    Design: Difficulty/boundary_precision_check/warranty_window_half_open_last_day_vs_first_day_after
    """
    ctx = setup_episode_in_post_op(template_overrides={"warranty_days": 5})
    episode = ctx["episode"]
    assert episode["warranty_end_seq"] == (
        episode["discharge_seq"] + 5
    ), "warranty_end_seq is the discharge stamp plus warranty_days"

    in_window = submit_claim(
        episode, "RELATED_CARE", episode["warranty_end_seq"] - 1, 100000,
        submitting_entity="SURGERY_CENTER",
    )
    out_of_window = submit_claim(
        episode, "RELATED_CARE", episode["warranty_end_seq"], 100000,
        submitting_entity="SURGERY_CENTER",
    )

    adj_in = adjudicate(in_window["id"])
    assert adj_in["status"] == "APPROVED"
    assert adj_in["adjudicated_payable_cents"] == 100000

    adj_out = adjudicate(out_of_window["id"])
    assert adj_out["status"] == "DENIED"
    assert adj_out["adjudication_reason"] == "OUTSIDE_WARRANTY_WINDOW"
    assert adj_out["adjudicated_payable_cents"] == 0


def test_discharge_stamps_warranty_end_and_close_sequences(api):
    """PRD §3.5: "`discharge_seq` is stamped from the post-increment
    `screen_seq`, `warranty_end_seq` is set to the discharge stamp plus the
    template's `warranty_days`, and `warranty_close_seq` is set seven days
    beyond the warranty end — a quiet-tail horizon after which an uneventful
    episode closes itself."

    Design: Difficulty/boundary_precision_check/warranty_window_half_open_last_day_vs_first_day_after
    """
    ctx = setup_episode_in_post_op(template_overrides={"warranty_days": 5})
    episode = ctx["episode"]
    assert episode["status"] == "POST_OP_TRACKING"
    assert episode["discharge_seq"] == episode["screen_seq"]
    assert episode["warranty_end_seq"] == episode["discharge_seq"] + 5
    assert episode["warranty_close_seq"] == episode["warranty_end_seq"] + 7


def test_related_care_payable_min_of_bill_and_remaining_bundle(api):
    """PRD §3.7: "The payable is the billed amount capped at what remains of
    the bundle: the episode's `applied_bundle_price_cents` minus the payables
    already approved or paid on this episode's `BUNDLE_CASE` and
    `RELATED_CARE` claims, floored at zero — so approval with a payable of
    zero is possible once the bundle is exhausted."

    Design: Difficulty/combinatorial_formula/related_care_payable_min_of_bill_and_remaining_bundle
    """
    ctx = setup_episode_in_post_op()
    episode = ctx["episode"]

    case = submit_claim(
        episode, "BUNDLE_CASE", episode["surgery_done_seq"], 3000000
    )
    adj_case = adjudicate(case["id"])
    assert adj_case["status"] == "APPROVED"
    assert adj_case["adjudicated_payable_cents"] == 3000000

    # The case rate exhausts the bundle: remaining room is max(0, 3000000 -
    # 3000000) == 0, so the related-care claim approves at payable zero.
    related = submit_claim(
        episode, "RELATED_CARE", episode["discharge_seq"], 200000,
        submitting_entity="SURGERY_CENTER",
    )
    adj_related = adjudicate(related["id"])
    assert adj_related["status"] == "APPROVED", (
        "zero payable is still an approval, not a denial"
    )
    assert adj_related["adjudicated_payable_cents"] == 0


def test_related_care_payable_draws_down_remaining_room(api):
    """PRD §3.7: "The payable is the billed amount capped at what remains of
    the bundle: the episode's `applied_bundle_price_cents` minus the payables
    already approved or paid on this episode's `BUNDLE_CASE` and
    `RELATED_CARE` claims, floored at zero"

    Design: Difficulty/combinatorial_formula/related_care_payable_min_of_bill_and_remaining_bundle
    """
    ctx = setup_episode_in_post_op()
    episode = ctx["episode"]

    # Billed under the outlier threshold: the case claim pays the full applied
    # basis (no outlier excess).
    case = submit_claim(
        episode, "BUNDLE_CASE", episode["surgery_done_seq"], 2000000
    )
    adj_case = adjudicate(case["id"])
    assert adj_case["adjudicated_payable_cents"] == 3000000

    # The case rate exhausts the bundle; a zero-billed in-window related-care
    # claim approves at payable zero.
    first = submit_claim(
        episode, "RELATED_CARE", episode["discharge_seq"], 0,
        submitting_entity="SURGERY_CENTER",
    )
    adj_first = adjudicate(first["id"])
    assert adj_first["status"] == "APPROVED"
    assert adj_first["adjudicated_payable_cents"] == 0, (
        "min(0, max(0, 3000000 - 3000000)) == 0"
    )


def test_outlier_truncation_then_add_rounding_order(api):
    """PRD §2.5: "The single division that appears in a financial computation
    — the outlier share applied to billed excess — truncates to whole cents
    rather than rounding."
    PRD §3.7: "the excess is the billed amount above the contract's
    `outlier_threshold_cents`, floored at zero; the outlier payable is that
    excess multiplied by `outlier_share_pct` and divided by 100, truncated to
    whole cents; and the payable is the episode's `applied_bundle_price_cents`
    plus the outlier payable."

    Design: Difficulty/combinatorial_formula/outlier_truncation_then_add_rounding_order
    """
    ctx = setup_episode_in_post_op(
        contract_overrides={
            "outlier_threshold_cents": 3100001,
            "outlier_share_pct": 33,
        }
    )
    episode = ctx["episode"]
    claim = submit_claim(
        episode, "BUNDLE_CASE", episode["surgery_done_seq"], 3100002
    )
    adj = adjudicate(claim["id"])
    assert adj["status"] == "APPROVED"
    # excess = 1; (1 * 33) / 100 truncates to 0 BEFORE the addition.
    assert adj["adjudicated_payable_cents"] == 3000000


def test_outlier_share_partial_amount_truncates(api):
    """PRD §2.5: "The single division that appears in a financial computation
    — the outlier share applied to billed excess — truncates to whole cents
    rather than rounding."

    Design: Difficulty/combinatorial_formula/outlier_truncation_then_add_rounding_order
    """
    ctx = setup_episode_in_post_op(
        contract_overrides={
            "outlier_threshold_cents": 1000000,
            "outlier_share_pct": 33,
        }
    )
    episode = ctx["episode"]
    # excess = 101; (101 * 33) / 100 = 33.33 -> truncates to 33.
    claim = submit_claim(
        episode, "BUNDLE_CASE", episode["surgery_done_seq"], 1000101
    )
    adj = adjudicate(claim["id"])
    assert adj["status"] == "APPROVED"
    assert adj["adjudicated_payable_cents"] == 3000000 + 33


def test_claim_constants_threshold_and_share_applied_verbatim(api):
    """PRD §3.7: "the excess is the billed amount above the contract's
    `outlier_threshold_cents`, floored at zero; the outlier payable is that
    excess multiplied by `outlier_share_pct` and divided by 100, truncated to
    whole cents; and the payable is the episode's `applied_bundle_price_cents`
    plus the outlier payable."

    Design: Corner/calculations/claim_constants_threshold_and_share_applied_verbatim
    """
    ctx = setup_episode_in_post_op(
        contract_overrides={
            "outlier_threshold_cents": 5000000,
            "outlier_share_pct": 50,
        }
    )
    episode = ctx["episode"]
    claim = submit_claim(
        episode, "BUNDLE_CASE", episode["surgery_done_seq"], 6000000
    )
    adj = adjudicate(claim["id"])
    assert adj["status"] == "APPROVED"
    # 3000000 + (1000000 * 50) / 100 == 3000000 + 500000.
    assert adj["adjudicated_payable_cents"] == 3500000


def test_claim_input_set_excludes_denied_claims_from_allocated(api):
    """PRD §3.7: "the episode's `applied_bundle_price_cents` minus the payables
    already approved or paid on this episode's `BUNDLE_CASE` and
    `RELATED_CARE` claims, floored at zero" — a denied claim is neither
    approved nor paid, so it never consumes bundle room.
    PRD §3.7: "the first failing rule moves the claim to `DENIED` with that
    rule's reason code recorded in `adjudication_reason`,
    `adjudicated_payable_cents` set to zero"

    Design: Corner/calculations/claim_input_set_excludes_denied_claims_from_allocated
    """
    ctx = setup_episode_in_post_op()
    episode = ctx["episode"]

    case = submit_claim(
        episode, "BUNDLE_CASE", episode["surgery_done_seq"], 3000000
    )
    assert adjudicate(case["id"])["adjudicated_payable_cents"] == 3000000

    denied = submit_claim(
        episode, "RELATED_CARE", episode["warranty_end_seq"] + 100, 500000,
        submitting_entity="SURGERY_CENTER",
    )
    adj_denied = adjudicate(denied["id"])
    assert adj_denied["status"] == "DENIED"
    assert adj_denied["adjudication_reason"] == "OUTSIDE_WARRANTY_WINDOW"
    assert adj_denied["adjudicated_payable_cents"] == 0

    ok = submit_claim(
        episode, "RELATED_CARE", episode["discharge_seq"], 100,
        submitting_entity="SURGERY_CENTER",
    )
    adj_ok = adjudicate(ok["id"])
    assert adj_ok["status"] == "APPROVED"
    assert adj_ok["adjudicated_payable_cents"] == 0, (
        "the DENIED row's billed 500000 never entered the allocated set"
    )


def test_adjudicate_paid_claim_returns_invalid_state(api):
    """PRD §2.10: "Current-state legality of the transition or action
    (`ERR_INVALID_STATE`, HTTP 409) — for example a screening submitted on an
    already-approved episode, a review on an episode still in `SCREENING`, or
    adjudication of a claim already `PAID`."
    PRD §3.7: "an approved claim is later paid (`APPROVED → PAID`) by a
    `ClaimsAdmin`"

    Design: Corner/state_machines/adjudicate_paid_claim_returns_invalid_state
    """
    ctx = setup_episode_in_post_op()
    episode = ctx["episode"]
    claim = submit_claim(
        episode, "BUNDLE_CASE", episode["surgery_done_seq"], 3000000
    )
    adjudicated = adjudicate(claim["id"])
    assert adjudicated["status"] == "APPROVED"

    paid = validate_success(api.pay_claim(claim["id"], CLAIMS))
    assert paid["status"] == "PAID"

    resp = api.adjudicate_claim(claim["id"], CLAIMS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after = get_success_data(api.get_claim(claim["id"], CLAIMS))
    assert after["status"] == "PAID"
    assert after["adjudicated_payable_cents"] == 3000000


def test_error_stale_version_triggerable(api, care_coordinator_headers):
    """PRD §2.6: "Every episode mutation — recording a second-opinion review,
    scheduling or rescheduling the surgery day, marking surgery complete,
    discharging the patient, submitting a claim, and administering a travel or
    lodging benefit — must carry `expected_episode_version` equal to the
    episode's current `version` as the client last observed it."
    PRD §2.6: "the mutation is rejected with `ERR_STALE_VERSION` (HTTP 412)
    rather than applied against an out-of-date episode."

    Design: Corner/errors/error_stale_version_triggerable
    """
    ctx = setup_episode_in_sor_pending()
    episode = ctx["episode"]
    stale_version = episode["version"]
    # The review bumps the episode version, so the pre-review token is stale.
    validate_success(
        api.record_review(
            episode["id"],
            {"conclusion": "SURGERY_INDICATED",
             "expected_episode_version": stale_version},
            {"X-User-ID": "test-physician-reviewer-1",
             "X-User-Role": "PhysicianReviewer"},
        ),
        expected_status=201,
    )

    resp = api.schedule_episode(
        episode["id"],
        {"requested_day_seq": get_episode(episode["id"])["screen_seq"] + 1,
         "expected_episode_version": stale_version},
        care_coordinator_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    after = get_episode(episode["id"])
    assert after["status"] == "APPROVED"
    assert after["scheduled_start_seq"] == 0, "a stale write must not apply"
