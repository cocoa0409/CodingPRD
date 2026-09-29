"""Composite setup helpers.

Every helper builds its preconditions from scratch through published endpoints,
because each test runs against an empty database.  Setup calls go through the
lenient validator so a broken precondition reports as a setup failure rather
than as a confusing assertion.

Money is always an integer number of cents.  Calls made in the two roles that
name an entity — ``MemberLibrarian`` and ``VendorRep`` — always thread the real
member id / vendor id through the header builders.
"""

from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import factories as F
from .api_client import api_client
from .constants import ACTIVATION_CLOCK_UTC, TEST_DEFAULTS
from .test_users import (
    make_admin_headers,
    make_engineer_headers,
    make_librarian_headers,
    make_negotiator_headers,
    make_vendor_rep_headers,
)

ADMIN = make_admin_headers("admin-1")
NEGOTIATOR = make_negotiator_headers("neg-1")
ENGINEER = make_engineer_headers("eng-1")

# The canonical evaluation criteria of the reference trial.
CANONICAL_CRITERIA = [{"code": "CONTENT_FIT", "weight_pct": 100}]

# Three rows from three distinct stakeholder groups, all scoring 90 on the one
# criterion: enough rows to evaluate, enough groups to escape the quorum penalty.
CANONICAL_FEEDBACK = [
    ("FACULTY", "CONTENT_FIT", 90),
    ("GRADUATE", "CONTENT_FIT", 90),
    ("LIBRARIAN", "CONTENT_FIT", 90),
]


# ─── Primitives ───────────────────────────────────────────────────────────────

def set_clock(to_iso8601: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Move the logical clock, running the activation and expiry sweeps."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601},
                                                 headers or ADMIN))


def create_vendor(**overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_vendor(F.vendor_payload(**overrides), ADMIN))


def create_member(**overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_member(F.member_payload(**overrides), ADMIN))


def create_product(vendor_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_product(F.product_payload(vendor_id, **overrides), ADMIN)
    )


def read_member(member_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_member(member_id, ADMIN))


def read_subscription(subscription_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_subscription(subscription_id, ADMIN))


def read_commitment(commitment_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_commitment(commitment_id, ADMIN))


def read_trial(trial_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_trial(trial_id, ADMIN))


def read_negotiation(negotiation_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_negotiation(negotiation_id, ADMIN))


def read_incident(incident_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_access_incident(incident_id, ADMIN))


def subscription_version(subscription_id: str) -> int:
    """The subscription version a client would have last observed."""
    return read_subscription(subscription_id)["version"]


# ─── Tier 1: catalogue ────────────────────────────────────────────────────────

def setup_catalog(vendor_overrides: Optional[Dict[str, Any]] = None,
                  product_overrides: Optional[Dict[str, Any]] = None,
                  member_overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One vendor, one package of that vendor, one member library.

    Returns ``{"vendor", "product", "member"}``.
    """
    vendor = create_vendor(**(vendor_overrides or {}))
    product = create_product(vendor["id"], **(product_overrides or {}))
    member = create_member(**(member_overrides or {}))
    return {"vendor": vendor, "product": product, "member": member}


def setup_members(specs: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Create the member libraries described by ``specs``, in order.

    Creation order matters: several orderings in the platform are keyed on the
    member's ``created_at``.
    """
    return [create_member(**spec) for spec in specs]


# ─── Tier 2: trials ───────────────────────────────────────────────────────────

def create_draft_trial(product_id: str, member_id: str,
                       start_date: str = "2026-08-01",
                       end_date: str = "2026-08-31",
                       trial_criteria: Optional[List[Dict[str, Any]]] = None,
                       **overrides) -> Dict[str, Any]:
    payload = F.trial_payload(member_id, start_date, end_date,
                              trial_criteria or CANONICAL_CRITERIA, **overrides)
    return get_success_data(
        api_client.create_trial(product_id, payload, make_librarian_headers(member_id))
    )


def open_trial(trial_id: str, member_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.open_trial(trial_id, make_librarian_headers(member_id))
    )


def submit_feedback_rows(trial_id: str, member_id: str,
                         rows: Sequence[Sequence[Any]]) -> List[Dict[str, Any]]:
    """Submit ``(stakeholder_group, criterion_code, score)`` triples in order."""
    headers = make_librarian_headers(member_id)
    created = []
    for group, criterion, score in rows:
        created.append(get_success_data(
            api_client.submit_feedback(
                trial_id, F.feedback_payload(group, criterion, score), headers)
        ))
    return created


def close_trial(trial_id: str, member_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.close_trial(trial_id, make_librarian_headers(member_id))
    )


def evaluate_trial(trial_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.evaluate_trial(trial_id, ADMIN))


def endorse_trial(trial_id: str, member_id: str,
                  rows: Optional[Sequence[Sequence[Any]]] = None) -> Dict[str, Any]:
    """Walk a DRAFT trial all the way to ENDORSED.

    open -> three feedback rows from three distinct stakeholder groups -> close
    -> evaluate.  Returns the evaluated trial.
    """
    open_trial(trial_id, member_id)
    submit_feedback_rows(trial_id, member_id, rows or CANONICAL_FEEDBACK)
    close_trial(trial_id, member_id)
    return evaluate_trial(trial_id)


def setup_endorsed_trial(**catalog_kwargs) -> Dict[str, Any]:
    """Catalogue plus one ENDORSED trial of the package by the member.

    Returns ``{"vendor", "product", "member", "trial"}``.
    """
    scenario = setup_catalog(**catalog_kwargs)
    trial = create_draft_trial(scenario["product"]["id"], scenario["member"]["id"])
    scenario["trial"] = endorse_trial(trial["id"], scenario["member"]["id"])
    return scenario


# ─── Tier 3: negotiations ─────────────────────────────────────────────────────

def create_negotiation(product_id: str, trial_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_negotiation(
            F.negotiation_payload(product_id, trial_id, **overrides), ADMIN)
    )


def submit_round(negotiation_id: str, negotiator_user_id: str = "neg-1") -> Dict[str, Any]:
    """Send the current draft to the publisher; stamps the submitting negotiator."""
    return get_success_data(
        api_client.submit_negotiation(negotiation_id,
                                      make_negotiator_headers(negotiator_user_id))
    )


def vendor_accepts(negotiation_id: str, vendor_id: str,
                   accepted_price_cents: int = TEST_DEFAULTS["AGREED_PRICE_CENTS"],
                   **overrides) -> Dict[str, Any]:
    payload = F.accept_response_payload(accepted_price_cents, **overrides)
    return get_success_data(
        api_client.vendor_response(negotiation_id, payload,
                                  make_vendor_rep_headers(vendor_id))
    )


def vendor_counters(negotiation_id: str, vendor_id: str,
                    counter_price_cents: int = 9900000, **overrides) -> Dict[str, Any]:
    payload = F.counter_response_payload(counter_price_cents, **overrides)
    return get_success_data(
        api_client.vendor_response(negotiation_id, payload,
                                  make_vendor_rep_headers(vendor_id))
    )


def revise_round(negotiation_id: str, negotiator_user_id: str = "neg-1",
                 **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.revise_negotiation(negotiation_id, F.revise_payload(**overrides),
                                     make_negotiator_headers(negotiator_user_id))
    )


def setup_agreed_negotiation(negotiation_overrides: Optional[Dict[str, Any]] = None,
                             accepted_price_cents: int = TEST_DEFAULTS["AGREED_PRICE_CENTS"],
                             granted: Optional[Dict[str, Any]] = None,
                             negotiator_user_id: str = "neg-1",
                             **catalog_kwargs) -> Dict[str, Any]:
    """Catalogue + ENDORSED trial + a negotiation carried through to AGREED.

    Returns ``{"vendor", "product", "member", "trial", "negotiation"}``.
    """
    scenario = setup_endorsed_trial(**catalog_kwargs)
    negotiation = create_negotiation(scenario["product"]["id"], scenario["trial"]["id"],
                                     **(negotiation_overrides or {}))
    submit_round(negotiation["id"], negotiator_user_id)
    scenario["negotiation"] = vendor_accepts(negotiation["id"], scenario["vendor"]["id"],
                                             accepted_price_cents, **(granted or {}))
    scenario["negotiator_user_id"] = negotiator_user_id
    return scenario


# ─── Tier 3: commitments ──────────────────────────────────────────────────────

def pledge(product_id: str, member_id: str, **overrides) -> Dict[str, Any]:
    """Pledge one member library's participation in a package."""
    return get_success_data(
        api_client.create_commitment(product_id, F.commitment_payload(member_id, **overrides),
                                     make_librarian_headers(member_id))
    )


def pledge_all(product_id: str, members: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pledge every member in order; pledge order fixes the projected prices."""
    return [pledge(product_id, member["id"]) for member in members]


def withdraw(commitment_id: str, member_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.withdraw_commitment(commitment_id, make_librarian_headers(member_id))
    )


# ─── Tier 4: signing, activation ──────────────────────────────────────────────

def sign(negotiation_id: str,
         activation_start_date: str = TEST_DEFAULTS["ACTIVATION_START_DATE"],
         signer_user_id: str = "admin-1") -> Dict[str, Any]:
    """Sign the AGREED negotiation. Answers the created subscription."""
    return get_success_data(
        api_client.sign_negotiation(negotiation_id,
                                    F.sign_payload(activation_start_date),
                                    make_admin_headers(signer_user_id)),
        expected_status=201,
    )


def setup_signed_subscription(activation_start_date: str = TEST_DEFAULTS["ACTIVATION_START_DATE"],
                              signer_user_id: str = "admin-1",
                              **agreed_kwargs) -> Dict[str, Any]:
    """Everything through the signature: the subscription is PENDING_ACTIVATION.

    Returns the AGREED-negotiation scenario plus ``{"commitment", "subscription"}``.
    """
    scenario = setup_agreed_negotiation(**agreed_kwargs)
    scenario["commitment"] = pledge(scenario["product"]["id"], scenario["member"]["id"])
    scenario["subscription"] = sign(scenario["negotiation"]["id"], activation_start_date,
                                   signer_user_id)
    return scenario


def setup_active_subscription(clock: str = ACTIVATION_CLOCK_UTC,
                              **signed_kwargs) -> Dict[str, Any]:
    """A signed subscription whose contract axis has been activated by the clock.

    Returns the signed scenario with ``subscription`` refreshed after the sweep.
    """
    scenario = setup_signed_subscription(**signed_kwargs)
    set_clock(clock)
    scenario["subscription"] = read_subscription(scenario["subscription"]["id"])
    scenario["commitment"] = read_commitment(scenario["commitment"]["id"])
    return scenario


def setup_multi_member_subscription(member_specs: Sequence[Dict[str, Any]],
                                    activate: bool = False,
                                    clock: str = ACTIVATION_CLOCK_UTC,
                                    accepted_price_cents: int = TEST_DEFAULTS["AGREED_PRICE_CENTS"],
                                    product_overrides: Optional[Dict[str, Any]] = None,
                                    vendor_overrides: Optional[Dict[str, Any]] = None,
                                    trial_member_index: int = 0) -> Dict[str, Any]:
    """A package pledged by several member libraries, then signed.

    ``member_specs`` are created in the given order, the trial is run by the
    member at ``trial_member_index``, and every member pledges in list order.

    Returns ``{"vendor", "product", "members", "trial", "negotiation",
    "commitments", "subscription"}``.
    """
    vendor = create_vendor(**(vendor_overrides or {}))
    product = create_product(vendor["id"], **(product_overrides or {}))
    members = setup_members(member_specs)
    trial_member = members[trial_member_index]
    trial = create_draft_trial(product["id"], trial_member["id"])
    trial = endorse_trial(trial["id"], trial_member["id"])
    negotiation = create_negotiation(product["id"], trial["id"])
    submit_round(negotiation["id"])
    negotiation = vendor_accepts(negotiation["id"], vendor["id"], accepted_price_cents)
    commitments = pledge_all(product["id"], members)
    subscription = sign(negotiation["id"])
    if activate:
        set_clock(clock)
        subscription = read_subscription(subscription["id"])
    return {
        "vendor": vendor,
        "product": product,
        "members": members,
        "trial": trial,
        "negotiation": negotiation,
        "commitments": commitments,
        "subscription": subscription,
    }


# ─── Tier 4: authentication configuration and access ──────────────────────────

def configure_auth(subscription_id: str, **overrides) -> Dict[str, Any]:
    """Bind a subscription to a federation realm. Requires an ACTIVE contract."""
    return get_success_data(
        api_client.create_auth_config(subscription_id, F.auth_config_payload(**overrides),
                                      ENGINEER),
        expected_status=201,
    )


def probe_auth(auth_config_id: str, probe_result: str = "PASS") -> Dict[str, Any]:
    return get_success_data(
        api_client.verify_auth_config(auth_config_id, F.probe_payload(probe_result),
                                      ENGINEER)
    )


def setup_configured_access(**active_kwargs) -> Dict[str, Any]:
    """An ACTIVE subscription whose access axis is CONFIGURED by a passing probe.

    Returns the active scenario plus ``{"auth_config"}``.
    """
    scenario = setup_active_subscription(**active_kwargs)
    auth_config = configure_auth(scenario["subscription"]["id"])
    scenario["auth_config"] = probe_auth(auth_config["id"], "PASS")
    scenario["subscription"] = read_subscription(scenario["subscription"]["id"])
    return scenario


def report_incident(subscription_id: str, member_id: str,
                    symptom_code: str = "OFF_CAMPUS_DENIED",
                    off_campus: bool = True, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_access_incident(
            subscription_id,
            F.incident_payload(member_id, symptom_code, off_campus, **overrides),
            make_librarian_headers(member_id)),
        expected_status=201,
    )


def report_incidents(subscription_id: str, member_id: str,
                     specs: Sequence[Sequence[Any]]) -> List[Dict[str, Any]]:
    """Report ``(symptom_code, off_campus)`` pairs in order."""
    return [report_incident(subscription_id, member_id, symptom, off_campus)
            for symptom, off_campus in specs]


def report_off_campus_incidents(subscription_id: str, member_id: str,
                                count: int) -> List[Dict[str, Any]]:
    """Report ``count`` off-campus denials, each costing eight health points."""
    return [report_incident(subscription_id, member_id, "OFF_CAMPUS_DENIED", True)
            for _ in range(count)]


def diagnose(incident_id: str, root_cause_code: str = "PROXY_MISCONFIGURED") -> Dict[str, Any]:
    return get_success_data(
        api_client.diagnose_incident(incident_id, F.diagnose_payload(root_cause_code),
                                     ENGINEER)
    )


def resolve(incident_id: str, remedy_code: str = "PROXY_FIXED") -> Dict[str, Any]:
    return get_success_data(
        api_client.resolve_incident(incident_id, F.resolve_payload(remedy_code), ENGINEER)
    )


def reopen(incident_id: str, member_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.reopen_incident(incident_id, make_librarian_headers(member_id))
    )


def diagnose_and_resolve(incident_id: str,
                         root_cause_code: str = "PROXY_MISCONFIGURED",
                         remedy_code: str = "PROXY_FIXED") -> Dict[str, Any]:
    diagnose(incident_id, root_cause_code)
    return resolve(incident_id, remedy_code)


# ─── Tier 4: usage reporting ──────────────────────────────────────────────────

def file_usage(subscription_id: str, vendor_id: str, member_id: str,
               period_month: str, full_text_requests: int = 1200,
               searches: int = 4000, denials: int = 10, **overrides) -> Dict[str, Any]:
    """The publisher files one COUNTER month for one member library."""
    payload = F.usage_report_payload(member_id, period_month, full_text_requests,
                                     searches, denials, **overrides)
    return get_success_data(
        api_client.create_usage_report(subscription_id, payload,
                                       make_vendor_rep_headers(vendor_id)),
        expected_status=201,
    )


def file_usage_months(subscription_id: str, vendor_id: str, member_id: str,
                      months: Sequence[Sequence[Any]]) -> List[Dict[str, Any]]:
    """File ``(period_month, full_text_requests)`` pairs in order."""
    return [file_usage(subscription_id, vendor_id, member_id, month, requests)
            for month, requests in months]


# ─── Tier 5: renewal decisions ────────────────────────────────────────────────

def open_renewal_decision(subscription_id: str, recommended_action: str = "RENEW",
                          vendor_requested_increase_pct: float = 0.00,
                          expected_version: Optional[int] = None,
                          **overrides) -> Dict[str, Any]:
    """Open a DRAFT renewal decision against the observed subscription version."""
    version = (expected_version if expected_version is not None
               else subscription_version(subscription_id))
    payload = F.renewal_decision_payload(version, recommended_action,
                                         vendor_requested_increase_pct, **overrides)
    return get_success_data(
        api_client.create_renewal_decision(subscription_id, payload, ADMIN),
        expected_status=201,
    )


def open_vote(decision_id: str) -> Dict[str, Any]:
    """Put the decision to the participating members and stamp the offer."""
    return get_success_data(api_client.open_vote(decision_id, ADMIN))


def cast_vote(decision_id: str, member_id: str, ballot: str = "YES") -> Dict[str, Any]:
    return get_success_data(
        api_client.cast_vote(decision_id, F.ballot_payload(member_id, ballot),
                             make_librarian_headers(member_id))
    )


def cast_votes(decision_id: str, members: Sequence[Dict[str, Any]],
               ballot: str = "YES") -> List[Dict[str, Any]]:
    return [cast_vote(decision_id, member["id"], ballot) for member in members]


def decide(decision_id: str, resolved_action: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.decide_renewal(decision_id, F.decide_payload(resolved_action, **overrides),
                                  ADMIN)
    )


def execute_decision(decision_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.execute_renewal(decision_id, ADMIN))


def revert_restructure(decision_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.revert_restructure(decision_id, ADMIN))


def setup_voting_decision(recommended_action: str = "RENEW",
                          vendor_requested_increase_pct: float = 0.00,
                          decision_overrides: Optional[Dict[str, Any]] = None,
                          **active_kwargs) -> Dict[str, Any]:
    """An ACTIVE subscription with one CONFIRMED participant and a VOTING decision.

    Returns the active scenario plus ``{"decision"}``.
    """
    scenario = setup_active_subscription(**active_kwargs)
    decision = open_renewal_decision(scenario["subscription"]["id"], recommended_action,
                                     vendor_requested_increase_pct,
                                     **(decision_overrides or {}))
    scenario["decision"] = open_vote(decision["id"])
    scenario["subscription"] = read_subscription(scenario["subscription"]["id"])
    return scenario


def setup_decided_decision(resolved_action: str,
                           recommended_action: Optional[str] = None,
                           vendor_requested_increase_pct: float = 0.00,
                           decision_overrides: Optional[Dict[str, Any]] = None,
                           decide_overrides: Optional[Dict[str, Any]] = None,
                           **active_kwargs) -> Dict[str, Any]:
    """A VOTING decision carried through a unanimous ballot to its decided state.

    Returns the voting scenario with ``decision`` refreshed after the fork.
    """
    scenario = setup_voting_decision(recommended_action or resolved_action,
                                     vendor_requested_increase_pct,
                                     decision_overrides, **active_kwargs)
    cast_vote(scenario["decision"]["id"], scenario["member"]["id"], "YES")
    scenario["decision"] = decide(scenario["decision"]["id"], resolved_action,
                                  **(decide_overrides or {}))
    scenario["subscription"] = read_subscription(scenario["subscription"]["id"])
    return scenario


# ─── Tier 5: archival deposit checks ──────────────────────────────────────────

def open_archival_check(subscription_id: str, agency_code: str = "PORTICO",
                        deposited_title_count: int = 380,
                        expected_version: Optional[int] = None,
                        **overrides) -> Dict[str, Any]:
    version = (expected_version if expected_version is not None
               else subscription_version(subscription_id))
    payload = F.archival_check_payload(version, agency_code, deposited_title_count,
                                       **overrides)
    return get_success_data(
        api_client.create_archival_check(subscription_id, payload, ADMIN),
        expected_status=201,
    )


def attest_archival_check(check_id: str, attested_title_count: int,
                          vendor_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.attest_archival_check(check_id, F.attest_payload(attested_title_count),
                                         make_vendor_rep_headers(vendor_id))
    )


def verify_archival_check(check_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.verify_archival_check(check_id, ADMIN))


def setup_archival_check(subscription_id: str, vendor_id: str,
                         deposited_title_count: int = 380,
                         attested_title_count: Optional[int] = None,
                         verify: bool = True,
                         agency_code: str = "PORTICO") -> Dict[str, Any]:
    """Open, attest and (optionally) verify one archival deposit check.

    With the default counts against a 400-title package the coverage lands on
    95.00 and the check reaches VERIFIED.
    """
    check = open_archival_check(subscription_id, agency_code, deposited_title_count)
    if attested_title_count is None:
        attested_title_count = deposited_title_count
    check = attest_archival_check(check["id"], attested_title_count, vendor_id)
    if verify:
        check = verify_archival_check(check["id"])
    return check


# ─── Tier 5: branch-specific end-to-end scenarios ─────────────────────────────

DEFAULT_TITLES_OUT = ["T-0001", "T-0002", "T-0003"]
DEFAULT_TITLES_IN = ["T-9001"]
DEFAULT_DELTA_PRICE_CENTS = 250000


def setup_restructure_ready(titles_out: Optional[List[str]] = None,
                            titles_in: Optional[List[str]] = None,
                            delta_price_cents: int = DEFAULT_DELTA_PRICE_CENTS,
                            configure_access: bool = True,
                            decide_now: bool = True,
                            **active_kwargs) -> Dict[str, Any]:
    """An ACTIVE, access-CONFIGURED subscription with a DECIDED_RESTRUCTURE decision.

    Returns ``{... , "auth_config"?, "decision"}``.  With ``decide_now`` false the
    decision is left in VOTING with one YES ballot already cast.
    """
    scenario = (setup_configured_access(**active_kwargs) if configure_access
                else setup_active_subscription(**active_kwargs))
    decision = open_renewal_decision(
        scenario["subscription"]["id"], "RESTRUCTURE", 0.00,
        titles_out=list(titles_out if titles_out is not None else DEFAULT_TITLES_OUT),
        titles_in=list(titles_in if titles_in is not None else DEFAULT_TITLES_IN),
    )
    decision = open_vote(decision["id"])
    cast_vote(decision["id"], scenario["member"]["id"], "YES")
    if decide_now:
        decision = decide(decision["id"], "RESTRUCTURE",
                          delta_price_cents=delta_price_cents)
    scenario["decision"] = decision
    scenario["subscription"] = read_subscription(scenario["subscription"]["id"])
    return scenario


def setup_executed_restructure(**kwargs) -> Dict[str, Any]:
    """A restructuring that has already been executed against the subscription."""
    scenario = setup_restructure_ready(**kwargs)
    scenario["decision"] = execute_decision(scenario["decision"]["id"])
    scenario["subscription"] = read_subscription(scenario["subscription"]["id"])
    scenario["commitment"] = read_commitment(scenario["commitment"]["id"])
    return scenario


def setup_cancel_ready(with_verified_archive: bool = True,
                       deposited_title_count: int = 380,
                       attested_title_count: Optional[int] = None,
                       verify_archive: bool = True,
                       **active_kwargs) -> Dict[str, Any]:
    """A DECIDED_CANCEL decision on a subscription whose contract is NOTICE_GIVEN.

    Returns the active scenario plus ``{"decision", "archival_check"?}``.
    """
    scenario = setup_active_subscription(**active_kwargs)
    decision = open_renewal_decision(scenario["subscription"]["id"], "CANCEL", 0.00)
    decision = open_vote(decision["id"])
    cast_vote(decision["id"], scenario["member"]["id"], "YES")
    scenario["decision"] = decide(decision["id"], "CANCEL")
    if with_verified_archive:
        scenario["archival_check"] = setup_archival_check(
            scenario["subscription"]["id"], scenario["vendor"]["id"],
            deposited_title_count, attested_title_count, verify_archive)
    scenario["subscription"] = read_subscription(scenario["subscription"]["id"])
    return scenario


def setup_over_committed_member(ceiling_cents: int,
                                first_price_cents: int = TEST_DEFAULTS["AGREED_PRICE_CENTS"],
                                member_overrides: Optional[Dict[str, Any]] = None,
                                second_product_overrides: Optional[Dict[str, Any]] = None,
                                draft_trial_on_second: bool = False,
                                second_trial_window=("2026-10-01", "2026-10-31"),
                                ) -> Dict[str, Any]:
    """Drive one member library past its budget ceiling through a signature.

    The member pledges on a first package and the signature confirms that pledge
    at the settled price, pushing the ledger past ``ceiling_cents``.  A second
    package of the same vendor is left available, optionally with the member's
    own DRAFT trial on it.

    Returns ``{"vendor", "member", "product", "second_product", "trial",
    "negotiation", "commitment", "subscription", "second_trial"?}``.
    """
    vendor = create_vendor()
    product = create_product(vendor["id"])
    second_product = create_product(vendor["id"], name="Atlas Sciences Collection",
                                    **(second_product_overrides or {}))
    member = create_member(**{"budget_ceiling_cents": ceiling_cents,
                              **(member_overrides or {})})
    trial = create_draft_trial(product["id"], member["id"])
    trial = endorse_trial(trial["id"], member["id"])
    second_trial = None
    if draft_trial_on_second:
        second_trial = create_draft_trial(second_product["id"], member["id"],
                                          second_trial_window[0], second_trial_window[1])
    negotiation = create_negotiation(product["id"], trial["id"])
    submit_round(negotiation["id"])
    negotiation = vendor_accepts(negotiation["id"], vendor["id"], first_price_cents)
    commitment = pledge(product["id"], member["id"])
    subscription = sign(negotiation["id"])
    scenario = {
        "vendor": vendor,
        "member": read_member(member["id"]),
        "product": product,
        "second_product": second_product,
        "trial": read_trial(trial["id"]),
        "negotiation": negotiation,
        "commitment": read_commitment(commitment["id"]),
        "subscription": subscription,
    }
    if second_trial is not None:
        scenario["second_trial"] = read_trial(second_trial["id"])
    return scenario


def setup_realm_bindings(binding_count: int = 3,
                         subscription_count: int = 4,
                         auth_realm_code: str = "SHIB-EDU-1",
                         auth_method: str = "SHIBBOLETH",
                         member_overrides: Optional[Dict[str, Any]] = None,
                         clock: str = ACTIVATION_CLOCK_UTC) -> Dict[str, Any]:
    """Several ACTIVE subscriptions of one member whose terms all overlap.

    ``binding_count`` of them are already bound to ``auth_realm_code`` and left
    awaiting their probe, so the next binding on that realm is the one under test.

    Returns ``{"vendor", "member", "products", "subscriptions", "auth_configs"}``.
    """
    vendor = create_vendor()
    member = create_member(**{"budget_ceiling_cents": 40000000,
                              **(member_overrides or {})})
    products: List[Dict[str, Any]] = []
    subscriptions: List[Dict[str, Any]] = []
    for index in range(subscription_count):
        product = create_product(vendor["id"], name=f"Atlas Collection {index + 1}")
        products.append(product)
        trial = create_draft_trial(product["id"], member["id"])
        trial = endorse_trial(trial["id"], member["id"])
        negotiation = create_negotiation(product["id"], trial["id"])
        submit_round(negotiation["id"])
        vendor_accepts(negotiation["id"], vendor["id"])
        pledge(product["id"], member["id"])
        subscriptions.append(sign(negotiation["id"]))
    set_clock(clock)
    subscriptions = [read_subscription(s["id"]) for s in subscriptions]
    auth_configs = [
        configure_auth(subscriptions[index]["id"], auth_method=auth_method,
                       auth_realm_code=auth_realm_code)
        for index in range(binding_count)
    ]
    return {
        "vendor": vendor,
        "member": member,
        "products": products,
        "subscriptions": subscriptions,
        "auth_configs": auth_configs,
    }
