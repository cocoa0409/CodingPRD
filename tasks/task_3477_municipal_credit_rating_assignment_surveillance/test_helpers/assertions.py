"""Entity assertions and PRD-formula recompute helpers.

Two families live here:

* ``assert_<entity>(data)`` — structural checks on one resource body: field
  presence, enum membership, common-field shape.  The append-only records
  (``CommitteeVote``, ``IssuerNotification``) must NOT carry ``version`` or
  ``updated_at`` — PRD section 2.5 states both are absent.
* ``expected_*`` recompute helpers — independent implementations of the
  PRD's pinned formulas (weighted score, anchor table, weak-link cap,
  yield and interest, withdrawal refund) so a test can state an expectation
  without hard-coding a magic number at every call site.

Monetary rounding is round-half-up to whole cents and weighted scores are
round-half-up to four decimals (PRD section 2.8); both are implemented with
``decimal`` so the expectation is exact, not float-approximated.
"""

from decimal import Decimal, ROUND_HALF_UP

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from . import constants as C


# ─── PRD-formula recompute helpers ──────────────────────────────────────────


def round_half_up_cents(value):
    """Round a Decimal-compatible value to whole cents, half-up (PRD 2.8)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def expected_refund_cents(fee_cents):
    """refund = round_half_up(fee * 0.5) (PRD section 3.1)."""
    return round_half_up_cents(Decimal(fee_cents) * C.WITHDRAWAL_REFUND_RATIO)


def compute_weighted_score(weights, scores):
    """Round-half-up to 4 decimals of sum(weight_i * score_i) (PRD 3.2).

    ``weights`` and ``scores`` are dicts keyed by the six factor names
    (``economy``, ``management``, ``budgetary_performance``, ``flexibility``,
    ``liquidity``, ``debt_profile``); ``weights`` keys carry the ``w_``
    prefix as on the criteria payload.
    """
    total = Decimal("0")
    for factor in (
        "economy",
        "management",
        "budgetary_performance",
        "flexibility",
        "liquidity",
        "debt_profile",
    ):
        total += Decimal(str(weights["w_" + factor])) * Decimal(scores[factor])
    return total.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def expected_anchor_notch(weighted_score):
    """Anchor table on the ROUNDED 4-decimal score, inclusive lower bounds
    (PRD section 3.2)."""
    score = Decimal(str(weighted_score))
    if score >= C.ANCHOR_THRESHOLD_AAA:
        return C.NOTCH_AAA
    if score >= C.ANCHOR_THRESHOLD_AA:
        return C.NOTCH_AA
    if score >= C.ANCHOR_THRESHOLD_A:
        return C.NOTCH_A
    if score >= C.ANCHOR_THRESHOLD_BBB:
        return C.NOTCH_BBB
    if score >= C.ANCHOR_THRESHOLD_BB:
        return C.NOTCH_BB
    if score >= C.ANCHOR_THRESHOLD_B:
        return C.NOTCH_B
    return C.NOTCH_CCC


def expected_indicative_notch(credit_type, scores, anchor_notch):
    """Weak-link cap variant (PRD section 3.2): ENTERPRISE with a minimum
    factor score of exactly 1 caps the indicative notch at the worse of the
    anchor and BB.  Returns ``(indicative_notch, capped)``."""
    if (
        credit_type == C.CREDIT_TYPE_ENTERPRISE
        and min(scores.values()) == C.WEAK_LINK_MIN_SCORE
    ):
        if C.NOTCH_SCALE.index(anchor_notch) > C.NOTCH_SCALE.index(
            C.WEAK_LINK_CAP_NOTCH
        ):
            return anchor_notch, True
        return C.WEAK_LINK_CAP_NOTCH, True
    return anchor_notch, False


def expected_median_notch(notch_votes):
    """Committee median (PRD section 3.3): sort by scale position and take
    index len//2 — for an even count that is the WORSE of the two middle
    notches (nearer CCC)."""
    indices = sorted(C.NOTCH_SCALE.index(n) for n in notch_votes)
    return C.NOTCH_SCALE[indices[len(indices) // 2]]


def expected_effective_yield_bps(notch):
    """300 bps benchmark plus the per-notch spread (PRD section 3.7)."""
    return C.BENCHMARK_YIELD_BPS + C.SPREAD_BPS[notch]


def expected_annual_interest_cents(par_amount_cents, effective_yield_bps):
    """round_half_up(par * yield_bps / 10000), applied per year FIRST
    (PRD section 3.7 pins this order)."""
    return round_half_up_cents(
        Decimal(par_amount_cents) * Decimal(effective_yield_bps)
        / Decimal(C.BPS_DENOMINATOR)
    )


def expected_total_interest_cents(par_amount_cents, effective_yield_bps, years):
    """maturity_years * annual_interest_cents — the per-year rounded figure
    multiplied afterwards (PRD section 3.7)."""
    return years * expected_annual_interest_cents(par_amount_cents, effective_yield_bps)


def one_notch_better(notch):
    """The notch one step stronger on the scale (PRD section 2.5)."""
    idx = C.NOTCH_SCALE.index(notch)
    assert idx > 0, "{0} has no stronger notch".format(notch)
    return C.NOTCH_SCALE[idx - 1]


def one_notch_worse(notch):
    """The notch one step weaker on the scale (PRD section 2.5)."""
    idx = C.NOTCH_SCALE.index(notch)
    assert idx < len(C.NOTCH_SCALE) - 1, "{0} has no weaker notch".format(notch)
    return C.NOTCH_SCALE[idx + 1]


# ─── Common-field shape ─────────────────────────────────────────────────────


def assert_common_fields(data, context="resource"):
    """id / created_at / updated_at / version present and well-formed
    (PRD section 2.5)."""
    assert is_valid_uuid(data.get("id", "")), "{0}: id must be a UUID".format(context)
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "{0}: created_at must be ISO 8601, got {1!r}".format(context, data.get("created_at"))
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "{0}: updated_at must be ISO 8601, got {1!r}".format(context, data.get("updated_at"))
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "{0}: version must be a positive integer, got {1!r}".format(
            context, data.get("version")
        )
    )


def assert_append_only_fields(data, context="resource"):
    """Append-only records carry id + created_at and NOT updated_at /
    version (PRD section 2.5)."""
    assert is_valid_uuid(data.get("id", "")), "{0}: id must be a UUID".format(context)
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "{0}: created_at must be ISO 8601".format(context)
    )
    assert "updated_at" not in data, "{0}: updated_at must be absent".format(context)
    assert "version" not in data, "{0}: version must be absent".format(context)


# ─── Per-entity structural assertions ───────────────────────────────────────


def assert_issuer(data):
    assert_common_fields(data, "Issuer")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["issuer_type"] in C.ISSUER_TYPES
    assert isinstance(data["fiscal_year_end"], str) and len(data["fiscal_year_end"]) == 5
    assert isinstance(data["population"], int)
    assert isinstance(data["credit_balance_cents"], int)
    assert isinstance(data["delinquent_flag"], bool)


def assert_underwriter(data):
    assert_common_fields(data, "Underwriter")
    assert isinstance(data["firm_name"], str) and data["firm_name"]
    assert isinstance(data["license_number"], str) and data["license_number"]


def assert_engagement(data):
    assert_common_fields(data, "RatingEngagement")
    assert is_valid_uuid(data.get("issuer_id", "")), "issuer_id must be a UUID"
    assert data["solicitation"] in C.SOLICITATIONS
    assert data["credit_type"] in C.CREDIT_TYPES
    assert isinstance(data["jurisdiction_code"], str) and data["jurisdiction_code"]
    assert isinstance(data["fee_cents"], int)
    assert isinstance(data["fee_paid"], bool)
    assert isinstance(data["refund_cents"], int)
    assert isinstance(data["required_document_codes"], list)
    assert isinstance(data["received_document_codes"], list)
    assert data["status"] in C.ENGAGEMENT_STATUSES


def assert_scorecard(data):
    assert_common_fields(data, "AnalyticalScorecard")
    assert is_valid_uuid(data.get("engagement_id", "")), "engagement_id must be a UUID"
    assert is_valid_uuid(data.get("criteria_version_id", "")), (
        "criteria_version_id must be a UUID"
    )
    for field in (
        "score_economy",
        "score_management",
        "score_budgetary_performance",
        "score_flexibility",
        "score_liquidity",
        "score_debt_profile",
    ):
        assert isinstance(data[field], int), "{0} must be an integer".format(field)
        assert C.SCORE_MIN <= data[field] <= C.SCORE_MAX, (
            "{0} must be within 1..5, got {1!r}".format(field, data[field])
        )
    assert isinstance(data["weighted_score"], (int, float))
    assert data["anchor_notch"] in C.NOTCH_SCALE
    assert isinstance(data["capped"], bool)
    assert data["indicative_notch"] in C.NOTCH_SCALE


def assert_criteria_version(data):
    assert_common_fields(data, "CriteriaVersion")
    assert isinstance(data["jurisdiction_code"], str) and data["jurisdiction_code"]
    assert data["credit_type"] in C.CREDIT_TYPES
    assert isinstance(data["version_label"], str) and data["version_label"]
    for field in (
        "w_economy",
        "w_management",
        "w_budgetary_performance",
        "w_flexibility",
        "w_liquidity",
        "w_debt_profile",
    ):
        assert isinstance(data[field], (int, float)), (
            "{0} must be numeric".format(field)
        )
    assert data["status"] in C.CRITERIA_STATUSES
    if data["status"] == C.CRITERIA_DRAFT:
        assert data.get("activated_at") is None, "DRAFT keeps activated_at null"
    else:
        assert is_iso8601_timestamp(data.get("activated_at", "")), (
            "activated version stamps activated_at"
        )


def assert_session(data):
    assert_common_fields(data, "CommitteeSession")
    assert is_valid_uuid(data.get("engagement_id", "")), "engagement_id must be a UUID"
    assert isinstance(data["chair_id"], str) and data["chair_id"]
    assert isinstance(data["voter_ids"], list)
    assert isinstance(data["appointed_alternate_ids"], list)
    assert isinstance(data["recused_voter_ids"], list)
    assert isinstance(data["eligible_voter_count"], int)
    assert is_iso8601_timestamp(data.get("start_at", "")), "start_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("end_at", "")), "end_at must be ISO 8601"
    assert data["status"] in C.SESSION_STATUSES
    if data["status"] == C.SESSION_COMPLETED:
        assert data["outcome_notch"] in C.NOTCH_SCALE, (
            "a completed session records its median outcome_notch"
        )
        assert data.get("adjourn_reason") is None
    elif data["status"] == C.SESSION_ADJOURNED:
        assert data["adjourn_reason"] in C.ADJOURN_REASONS
        assert data.get("outcome_notch") is None, (
            "an adjourned session leaves outcome_notch null"
        )


def assert_committee_vote(data):
    """A recorded ballot: append-only, exactly one of notch_vote /
    recusal_reason set according to kind (PRD sections 2.5 and 3.3)."""
    assert_append_only_fields(data, "CommitteeVote")
    assert is_valid_uuid(data.get("session_id", "")), "session_id must be a UUID"
    assert isinstance(data["voter_id"], str) and data["voter_id"]
    assert data["kind"] in C.VOTE_KINDS
    if data["kind"] == C.VOTE_KIND_VOTE:
        assert data["notch_vote"] in C.NOTCH_SCALE
    else:
        assert isinstance(data["recusal_reason"], str) and data["recusal_reason"]


def assert_rating(data):
    assert_common_fields(data, "Rating")
    assert is_valid_uuid(data.get("engagement_id", "")), "engagement_id must be a UUID"
    assert is_valid_uuid(data.get("issuer_id", "")), "issuer_id must be a UUID"
    assert data["credit_type"] in C.CREDIT_TYPES
    assert isinstance(data["jurisdiction_code"], str) and data["jurisdiction_code"]
    assert data["notch"] in C.NOTCH_SCALE
    assert data["status"] in C.RATING_STATUSES
    assert data["surveillance_posture"] in C.POSTURES
    assert is_iso8601_timestamp(data.get("assigned_at", "")), (
        "assigned_at must be ISO 8601"
    )
    assert isinstance(data["review_pending"], bool)
    assert isinstance(data["notch_history"], list)
    for entry in data["notch_history"]:
        assert entry["notch"] in C.NOTCH_SCALE
        assert entry["cause"] in C.NOTCH_HISTORY_CAUSES
        assert is_iso8601_timestamp(entry.get("changed_at", "")), (
            "notch_history.changed_at must be ISO 8601"
        )
    if data["status"] == C.RATING_PUBLISHED:
        assert is_iso8601_timestamp(data.get("published_at", "")), (
            "a PUBLISHED rating stamps published_at"
        )
    if data["status"] == C.RATING_WITHDRAWN:
        assert is_iso8601_timestamp(data.get("withdrawn_at", "")), (
            "a WITHDRAWN rating stamps withdrawn_at"
        )
        assert data["withdraw_reason"] in C.WITHDRAW_REASONS
        assert data["notch_at_withdrawal"] in C.NOTCH_SCALE


def assert_appeal(data):
    assert_common_fields(data, "Appeal")
    assert is_valid_uuid(data.get("rating_id", "")), "rating_id must be a UUID"
    assert isinstance(data["new_information_codes"], list)
    assert data["status"] in C.APPEAL_STATUSES
    if data["status"] == C.APPEAL_FILED:
        assert data.get("decided_at") is None
    else:
        assert is_iso8601_timestamp(data.get("decided_at", "")), (
            "a decided appeal stamps decided_at"
        )
        assert isinstance(data["decision_rationale"], str)


def assert_bond_sale(data):
    assert_common_fields(data, "BondSale")
    assert is_valid_uuid(data.get("issuer_id", "")), "issuer_id must be a UUID"
    assert is_valid_uuid(data.get("rating_id", "")), "rating_id must be a UUID"
    assert isinstance(data["par_amount_cents"], int) and data["par_amount_cents"] > 0
    assert C.MATURITY_MIN_YEARS <= data["maturity_years"] <= C.MATURITY_MAX_YEARS
    assert data["pricing_mode"] in C.PRICING_MODES
    assert isinstance(data["effective_yield_bps"], int)
    assert isinstance(data["annual_interest_cents"], int)
    assert isinstance(data["total_interest_cents"], int)


def assert_obligation(data):
    assert_common_fields(data, "DisclosureObligation")
    assert is_valid_uuid(data.get("rating_id", "")), "rating_id must be a UUID"
    assert isinstance(data["period_index"], int) and data["period_index"] >= 1
    assert is_iso8601_timestamp(data.get("fiscal_year_end", "")), (
        "fiscal_year_end must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("due_at", "")), "due_at must be ISO 8601"
    assert data["status"] in C.OBLIGATION_STATUSES
    if data["status"] in (C.OBLIGATION_SUBMITTED_ON_TIME, C.OBLIGATION_SUBMITTED_LATE):
        assert is_iso8601_timestamp(data.get("submitted_at", "")), (
            "a submitted obligation stamps submitted_at"
        )


def assert_review_item(data):
    assert_common_fields(data, "CriteriaReviewItem")
    assert is_valid_uuid(data.get("criteria_version_id", "")), (
        "criteria_version_id must be a UUID"
    )
    assert is_valid_uuid(data.get("rating_id", "")), "rating_id must be a UUID"
    assert is_iso8601_timestamp(data.get("due_at", "")), "due_at must be ISO 8601"
    assert data["status"] in C.REVIEW_ITEM_STATUSES
    if data["status"] == C.REVIEW_COMPLETED_RATING_ACTION:
        assert data["outcome_notch"] in C.NOTCH_SCALE
    if data["status"] in (C.REVIEW_COMPLETED_NO_ACTION, C.REVIEW_COMPLETED_RATING_ACTION):
        assert is_iso8601_timestamp(data.get("completed_at", "")), (
            "a completed review item stamps completed_at"
        )


def assert_issuer_notification(data):
    """An issuer communication entry: append-only (PRD sections 2.5/2.11)."""
    assert_append_only_fields(data, "IssuerNotification")
    assert is_valid_uuid(data.get("issuer_id", "")), "issuer_id must be a UUID"
    assert data["event_type"] in C.NOTIFICATION_EVENT_TYPES
    assert isinstance(data["reference_id"], str) and data["reference_id"]
    assert isinstance(data["message"], str) and data["message"]


# ─── Domain invariant checkers ──────────────────────────────────────────────


def notification_events(notifications):
    """Extract the ordered event_type list from a notification log page."""
    return [entry["event_type"] for entry in notifications]


def assert_notification_order(notifications, expected_events):
    """The issuer log is in emission order (created_at ascending, PRD
    section 2.11): assert that ``expected_events`` appear as an in-order
    subsequence of the log."""
    actual = notification_events(notifications)
    position = 0
    for expected in expected_events:
        found = False
        while position < len(actual):
            if actual[position] == expected:
                found = True
                position += 1
                break
            position += 1
        assert found, (
            "notification {0} not found in order; log reads {1}, expected "
            "subsequence {2}".format(expected, actual, expected_events)
        )


def assert_session_pool_invariant(session):
    """eligible_voter_count == 5 - recused + alternates (PRD section 3.3)."""
    expected = (
        C.COMMITTEE_SIZE
        - len(session["recused_voter_ids"])
        + len(session["appointed_alternate_ids"])
    )
    assert session["eligible_voter_count"] == expected, (
        "eligible_voter_count {0} != 5 - {1} recused + {2} alternates".format(
            session["eligible_voter_count"],
            len(session["recused_voter_ids"]),
            len(session["appointed_alternate_ids"]),
        )
    )


def assert_weighted_score(data, expected_score, places=4):
    """weighted_score equals the 4-decimal rounded expectation; compare via
    Decimal so 4.40 and 4.4 are the same value but 3.5000 and 3.4999 differ."""
    actual = Decimal(str(data["weighted_score"]))
    expected = Decimal(str(expected_score)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    assert actual == expected, (
        "weighted_score {0} != expected {1} (4dp round-half-up)".format(
            actual, expected
        )
    )


def assert_posture_for_obligations(rating, obligations):
    """Posture derivation for a PUBLISHED rating (PRD section 3.5):
    DELINQUENT if any open obligation is DELINQUENT, else GRACE if any is
    OVERDUE, else CURRENT.  DEFAULTED obligations belong to a withdrawn
    rating and are outside this derivation."""
    open_states = [o["status"] for o in obligations]
    if C.OBLIGATION_DELINQUENT in open_states:
        expected = C.POSTURE_DELINQUENT
    elif C.OBLIGATION_OVERDUE in open_states:
        expected = C.POSTURE_GRACE
    else:
        expected = C.POSTURE_CURRENT
    assert rating["surveillance_posture"] == expected, (
        "posture {0} != derived {1} from obligation states {2}".format(
            rating["surveillance_posture"], expected, open_states
        )
    )
