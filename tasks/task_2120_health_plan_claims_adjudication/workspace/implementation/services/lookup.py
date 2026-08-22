"""Deterministic selectors (PRD 2.5, 3.4, 3.5, 3.6).

Every rule that selects "the applicable row" declares an explicit sort key, and
no sort ever falls back to a surrogate identifier. Configuration rows tie-break
on created_at ascending; service lines tie-break on line_number.
"""

from store import db, sort_key_created

AUTH_STATUS_RANK = {"ACTIVE": 0, "PARTIALLY_CONSUMED": 1, "EXHAUSTED": 2, "REVOKED": 3}


# --------------------------------------------------------------------------
# basic row access
# --------------------------------------------------------------------------
def lines_of(claim):
    """The claim's service lines in line_number ascending order."""
    rows = [l for l in db.values("claim_lines") if l["claim_id"] == claim["id"]]
    rows.sort(key=lambda l: (l["line_number"], l["_seq"]))
    return rows


def member_of(claim):
    return db.members.get(claim["member_id"])


def plan_of_member(member):
    return db.benefit_plans.get(member["plan_id"])


def provider_of(claim):
    return db.providers.get(claim["provider_id"])


def coverages_of(member_id):
    rows = [c for c in db.values("member_coverages") if c["member_id"] == member_id]
    rows.sort(key=sort_key_created)
    return rows


def remittances_of(claim_id):
    rows = [r for r in db.values("remittance_advices") if r["claim_id"] == claim_id]
    rows.sort(key=sort_key_created)
    return rows


# --------------------------------------------------------------------------
# coverage (half-open interval [effective_date, term_date))
# --------------------------------------------------------------------------
def covers(segment, service_date):
    if segment["effective_date"] > service_date:
        return False
    if segment["term_date"] is None:
        return True
    return segment["term_date"] > service_date


def match_coverage_segment(member_id, earliest_service_date):
    """Rank candidates by effective_date DESC, then created_at ASC; first wins."""
    candidates = [
        c for c in coverages_of(member_id) if covers(c, earliest_service_date)
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda c: (_desc(c["effective_date"]), c["created_at"], c["_seq"]))
    return candidates[0]


def line_is_covered(member_id, service_date):
    return any(covers(c, service_date) for c in coverages_of(member_id))


def member_has_active_interval(member_id, on_date):
    return any(covers(c, on_date) for c in coverages_of(member_id))


# --------------------------------------------------------------------------
# fee schedule / contract selectors
# --------------------------------------------------------------------------
def select_fee_rate(plan_id, procedure_code, service_date):
    """Latest effective_date on or before the service date; created_at ASC tie-break."""
    candidates = [
        r
        for r in db.values("fee_schedule_rates")
        if r["plan_id"] == plan_id
        and r["procedure_code"] == procedure_code
        and r["effective_date"] <= service_date
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda r: (_desc(r["effective_date"]), r["created_at"], r["_seq"]))
    return candidates[0]


def select_contract(provider_id, plan_id, service_date):
    """ACTIVE contracts whose CLOSED interval contains the service date."""
    candidates = [
        c
        for c in db.values("provider_contracts")
        if c["provider_id"] == provider_id
        and c["plan_id"] == plan_id
        and c["status"] == "ACTIVE"
        and c["effective_date"] <= service_date
        and c["term_date"] >= service_date
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda c: (_desc(c["effective_date"]), c["created_at"], c["_seq"]))
    return candidates[0]


# --------------------------------------------------------------------------
# edit rules
# --------------------------------------------------------------------------
def edit_rules_sorted():
    rows = db.values("edit_rules")
    rows.sort(key=lambda r: (r["precedence_rank"], r["created_at"], r["_seq"]))
    return rows


def applicable_rules(line):
    """Rules whose keying code matches the line's procedure_code.

    BUNDLING and MUTUALLY_EXCLUSIVE are keyed by secondary_code (the code that
    is bundled away or knocked out); UNITS_LIMIT and AUTH_REQUIRED by
    primary_code. Applied in precedence_rank ASC, created_at ASC.
    """
    out = []
    for rule in edit_rules_sorted():
        if rule["edit_type"] in ("BUNDLING", "MUTUALLY_EXCLUSIVE"):
            if rule["secondary_code"] == line["procedure_code"]:
                out.append(rule)
        else:
            if rule["primary_code"] == line["procedure_code"]:
                out.append(rule)
    return out


# --------------------------------------------------------------------------
# authorization selector
# --------------------------------------------------------------------------
def authorization_candidates(claim, line):
    """member / provider / procedure match with a CLOSED validity interval.

    Ranked by status preference, then valid_to ASC (spend the grant expiring
    soonest first), then created_at ASC.
    """
    candidates = [
        a
        for a in db.values("authorizations")
        if a["member_id"] == claim["member_id"]
        and a["provider_id"] == claim["provider_id"]
        and a["procedure_code"] == line["procedure_code"]
        and a["valid_from"] <= line["service_date"]
        and a["valid_to"] >= line["service_date"]
    ]
    candidates.sort(
        key=lambda a: (
            AUTH_STATUS_RANK[a["status"]],
            a["valid_to"],
            a["created_at"],
            a["_seq"],
        )
    )
    return candidates


def select_authorization(claim, line):
    candidates = authorization_candidates(claim, line)
    return candidates[0] if candidates else None


class _Desc:
    """Descending sort adaptor for string keys (never for identifiers)."""

    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value

    def __lt__(self, other):
        return self.value > other.value

    def __eq__(self, other):
        return self.value == other.value


def _desc(value):
    return _Desc(value)
