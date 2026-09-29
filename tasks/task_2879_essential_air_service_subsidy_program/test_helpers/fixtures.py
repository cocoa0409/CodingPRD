"""Composite state builders.

The harness restarts the API against an empty database before every single
test, so every precondition has to be built from declared endpoints. These
builders assemble the recurring chains — reference data, an open solicitation,
a submitted proposal, an awarded agreement, a reported month, a certified
month, a disbursed payment, a hold-in agreement and its replacement
solicitation — so individual tests only express the step under test.

Every builder uses get_success_data(), which accepts any 2xx and raises a
readable AssertionError naming the error_id when a setup step fails.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import (
    AGREEMENT_TERMINATE,
    DECISION_GRANT_WITH_HOLD_IN,
    DECISION_OPEN_REVIEW,
    PAYMENT_APPROVE,
    PAYMENT_DISBURSE,
    PROPOSAL_SUBMIT,
    SOLICITATION_CLOSE,
)
from .test_users import (
    ADMIN,
    ADMIN_APPROVER,
    ADMIN_DISBURSER,
    ANALYST,
    OFFICER,
    make_carrier_headers,
    make_community_rep_headers,
)


# ─── containers ──────────────────────────────────────────────────────

@dataclass
class Reference:
    """Reference data every workflow needs before a solicitation can open."""
    api: ApiClient
    community: Dict[str, Any]
    determination: Dict[str, Any]
    aircraft_type: Dict[str, Any]
    carrier: Dict[str, Any]
    second_carrier: Optional[Dict[str, Any]] = None
    fuel_index: Optional[Dict[str, Any]] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def community_id(self) -> str:
        return self.community["id"]

    @property
    def aircraft_type_id(self) -> str:
        return self.aircraft_type["id"]

    @property
    def carrier_id(self) -> str:
        return self.carrier["id"]

    @property
    def second_carrier_id(self) -> str:
        assert self.second_carrier is not None, "No second carrier was registered"
        return self.second_carrier["id"]

    @property
    def community_headers(self) -> Dict[str, str]:
        return make_community_rep_headers(self.community_id)

    @property
    def carrier_headers(self) -> Dict[str, str]:
        return make_carrier_headers(self.carrier_id)

    @property
    def second_carrier_headers(self) -> Dict[str, str]:
        return make_carrier_headers(self.second_carrier_id)


@dataclass
class Award:
    """An awarded solicitation and the service agreement it booked."""
    ref: Reference
    solicitation: Dict[str, Any]
    proposal: Dict[str, Any]
    agreement: Dict[str, Any]

    @property
    def api(self) -> ApiClient:
        return self.ref.api

    @property
    def solicitation_id(self) -> str:
        return self.solicitation["id"]

    @property
    def proposal_id(self) -> str:
        return self.proposal["id"]

    @property
    def agreement_id(self) -> str:
        return self.agreement["id"]

    @property
    def community_id(self) -> str:
        return self.ref.community_id

    @property
    def carrier_id(self) -> str:
        return self.ref.carrier_id

    @property
    def carrier_headers(self) -> Dict[str, str]:
        return make_carrier_headers(self.agreement["carrier_id"])

    @property
    def community_headers(self) -> Dict[str, str]:
        return make_community_rep_headers(self.agreement["community_id"])

    def reload(self) -> Dict[str, Any]:
        """Re-read the agreement and cache it back onto this container."""
        self.agreement = get_success_data(
            self.api.get_service_agreement(self.agreement_id, ADMIN)
        )
        return self.agreement


# ─── clock ───────────────────────────────────────────────────────────

def set_clock(api: ApiClient, instant: str, headers: Dict[str, str] = ADMIN) -> Dict[str, Any]:
    """Move the logical clock and return the new reading."""
    return get_success_data(api.set_clock(f.clock_payload(instant), headers))


# ─── reference data ──────────────────────────────────────────────────

def make_reference_data(
    api: ApiClient,
    *,
    clock: Optional[str] = None,
    community_overrides: Optional[Dict[str, Any]] = None,
    aircraft_overrides: Optional[Dict[str, Any]] = None,
    determination_overrides: Optional[Dict[str, Any]] = None,
    with_second_carrier: bool = True,
    fuel_month: Optional[str] = "2026-08",
    fuel_price: float = 2.4000,
) -> Reference:
    """Community + determination + aircraft type + carrier(s) + fuel index."""
    if clock is not None:
        set_clock(api, clock)

    community = get_success_data(
        api.create_community(f.community_payload(**(community_overrides or {})), ADMIN)
    )
    determination = get_success_data(
        api.create_eligibility_determination(
            community["id"],
            f.determination_payload(**(determination_overrides or {})),
            ANALYST,
        )
    )
    aircraft_type = get_success_data(
        api.create_aircraft_type(
            f.aircraft_type_payload(**(aircraft_overrides or {})), ADMIN
        )
    )
    carrier = get_success_data(api.create_carrier(f.carrier_payload(), ADMIN))
    second_carrier = None
    if with_second_carrier:
        second_carrier = get_success_data(
            api.create_carrier(f.second_carrier_payload(), ADMIN)
        )
    fuel_index = None
    if fuel_month is not None:
        fuel_index = get_success_data(
            api.create_fuel_index(f.fuel_index_payload(fuel_month, fuel_price), ADMIN)
        )
    # Re-read the community so its post-determination status is on the row.
    community = get_success_data(api.get_community(community["id"], ADMIN))
    return Reference(
        api=api,
        community=community,
        determination=determination,
        aircraft_type=aircraft_type,
        carrier=carrier,
        second_carrier=second_carrier,
        fuel_index=fuel_index,
    )


def publish_fuel_index(api: ApiClient, index_month: str,
                       price_per_gallon_usd: float) -> Dict[str, Any]:
    return get_success_data(
        api.create_fuel_index(
            f.fuel_index_payload(index_month, price_per_gallon_usd), ADMIN
        )
    )


def register_second_community(api: ApiClient, **overrides) -> Dict[str, Any]:
    """A second eligible community, used as an isolation control."""
    community = get_success_data(
        api.create_community(f.second_community_payload(**overrides), ADMIN)
    )
    get_success_data(
        api.create_eligibility_determination(
            community["id"], f.determination_payload(), ANALYST
        )
    )
    return get_success_data(api.get_community(community["id"], ADMIN))


# ─── solicitation and proposal steps ─────────────────────────────────

def open_solicitation(api: ApiClient, community_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_solicitation(f.solicitation_payload(community_id, **overrides), ADMIN)
    )


def draft_proposal(api: ApiClient, solicitation_id: str, carrier_id: str,
                   aircraft_type_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_proposal(
            f.proposal_payload(solicitation_id, carrier_id, aircraft_type_id, **overrides),
            make_carrier_headers(carrier_id),
        )
    )


def submit_proposal(api: ApiClient, proposal_id: str, carrier_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.proposal_action(
            proposal_id,
            f.proposal_action_payload(PROPOSAL_SUBMIT),
            make_carrier_headers(carrier_id),
        )
    )


def submitted_proposal(api: ApiClient, solicitation_id: str, carrier_id: str,
                       aircraft_type_id: str, **overrides) -> Dict[str, Any]:
    """Draft then submit one proposal, returning the SUBMITTED row."""
    proposal = draft_proposal(
        api, solicitation_id, carrier_id, aircraft_type_id, **overrides
    )
    return submit_proposal(api, proposal["id"], carrier_id)


def close_solicitation(api: ApiClient, solicitation_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.solicitation_action(
            solicitation_id, f.solicitation_action_payload(SOLICITATION_CLOSE), ADMIN
        )
    )


def file_preferences(api: ApiClient, solicitation: Dict[str, Any],
                     proposal_ids: List[str]) -> Dict[str, Any]:
    """File a complete ranking 1..N in the order given, by the owning community."""
    return get_success_data(
        api.file_preferences(
            solicitation["id"],
            f.preference_filing_payload(
                solicitation["version"], f.ranking_entries(*proposal_ids)
            ),
            make_community_rep_headers(solicitation["community_id"]),
        )
    )


def issue_selection_order(api: ApiClient, solicitation_id: str,
                          headers: Dict[str, str] = OFFICER) -> Dict[str, Any]:
    """Issue the order and return the newly booked service agreement."""
    return get_success_data(
        api.create_selection_order(solicitation_id, f.selection_order_payload(), headers),
        expected_status=201,
    )


# ─── end-to-end award ────────────────────────────────────────────────

def build_award(
    api: ApiClient,
    *,
    ref: Optional[Reference] = None,
    clock: Optional[str] = None,
    proposal_overrides: Optional[Dict[str, Any]] = None,
    solicitation_overrides: Optional[Dict[str, Any]] = None,
    officer_headers: Dict[str, str] = OFFICER,
    with_second_carrier: bool = True,
) -> Award:
    """Reference data -> solicitation -> submitted proposal -> close -> award.

    A single candidate, so the winner is unambiguous. The booked agreement is
    returned inside the Award container together with the rows it came from.
    """
    if ref is None:
        ref = make_reference_data(
            api, clock=clock, with_second_carrier=with_second_carrier
        )
    solicitation = open_solicitation(
        api, ref.community_id, **(solicitation_overrides or {})
    )
    proposal = submitted_proposal(
        api,
        solicitation["id"],
        ref.carrier_id,
        ref.aircraft_type_id,
        **(proposal_overrides or {}),
    )
    solicitation = close_solicitation(api, solicitation["id"])
    agreement = issue_selection_order(api, solicitation["id"], officer_headers)
    solicitation = get_success_data(api.get_solicitation(solicitation["id"], ADMIN))
    proposal = get_success_data(api.get_proposal(proposal["id"], ADMIN))
    return Award(
        ref=ref, solicitation=solicitation, proposal=proposal, agreement=agreement
    )


def build_two_candidate_solicitation(
    api: ApiClient,
    *,
    ref: Optional[Reference] = None,
    clock: Optional[str] = None,
    first_overrides: Optional[Dict[str, Any]] = None,
    second_overrides: Optional[Dict[str, Any]] = None,
    close: bool = True,
) -> Dict[str, Any]:
    """Two submitted proposals from two carriers on one solicitation.

    Returns {"ref", "solicitation", "proposal_a", "proposal_b"} where
    proposal_a belongs to the first carrier and proposal_b to the second.
    """
    if ref is None:
        ref = make_reference_data(api, clock=clock, with_second_carrier=True)
    solicitation = open_solicitation(api, ref.community_id)
    proposal_a = submitted_proposal(
        api,
        solicitation["id"],
        ref.carrier_id,
        ref.aircraft_type_id,
        **(first_overrides or {}),
    )
    proposal_b = submitted_proposal(
        api,
        solicitation["id"],
        ref.second_carrier_id,
        ref.aircraft_type_id,
        **(second_overrides or {}),
    )
    if close:
        solicitation = close_solicitation(api, solicitation["id"])
    return {
        "ref": ref,
        "solicitation": solicitation,
        "proposal_a": proposal_a,
        "proposal_b": proposal_b,
    }


# ─── monthly reporting steps ─────────────────────────────────────────

def open_period(api: ApiClient, agreement_id: str, period_month: str) -> Dict[str, Any]:
    return get_success_data(
        api.create_service_period(
            f.service_period_payload(agreement_id, period_month), ADMIN
        ),
        expected_status=201,
    )


def file_report(api: ApiClient, period_id: str, carrier_id: str,
                **counts) -> Dict[str, Any]:
    return get_success_data(
        api.report_service_period(
            period_id, f.report_payload(**counts), make_carrier_headers(carrier_id)
        )
    )


def reported_period(api: ApiClient, agreement_id: str, carrier_id: str,
                    period_month: str, **counts) -> Dict[str, Any]:
    """Open a month and file its report, returning the REPORTED period."""
    period = open_period(api, agreement_id, period_month)
    return file_report(api, period["id"], carrier_id, **counts)


def certify_period(api: ApiClient, period_id: str,
                   headers: Dict[str, str] = ADMIN) -> Dict[str, Any]:
    return get_success_data(
        api.certify_service_period(period_id, f.certify_payload(), headers)
    )


def payment_for_period(api: ApiClient, period_id: str,
                       headers: Dict[str, str] = ADMIN) -> Dict[str, Any]:
    """The subsidy payment created by certifying this period."""
    response = api.list_subsidy_payments(headers, {"service_period_id": period_id})
    rows = get_success_data(response)
    assert rows, f"No subsidy payment found for period {period_id}"
    return rows[-1]


def approve_payment(api: ApiClient, payment_id: str,
                    headers: Dict[str, str] = ADMIN_APPROVER) -> Dict[str, Any]:
    return get_success_data(
        api.payment_action(payment_id, f.payment_action_payload(PAYMENT_APPROVE), headers)
    )


def disburse_payment(api: ApiClient, payment_id: str,
                     headers: Dict[str, str] = ADMIN_DISBURSER) -> Dict[str, Any]:
    return get_success_data(
        api.payment_action(
            payment_id, f.payment_action_payload(PAYMENT_DISBURSE), headers
        )
    )


def certified_month(api: ApiClient, agreement_id: str, carrier_id: str,
                    period_month: str, **counts) -> Dict[str, Any]:
    """Open, report and certify one month.

    Returns {"period", "payment"} with the period CERTIFIED and its payment
    freshly COMPUTED.
    """
    period = reported_period(api, agreement_id, carrier_id, period_month, **counts)
    period = certify_period(api, period["id"])
    return {"period": period, "payment": payment_for_period(api, period["id"])}


def settled_month(api: ApiClient, agreement_id: str, carrier_id: str,
                  period_month: str, **counts) -> Dict[str, Any]:
    """Open, report, certify, approve and disburse one month.

    Returns {"period", "payment"} with the period PAID and the payment
    DISBURSED, so the agreement ledger has moved.
    """
    result = certified_month(api, agreement_id, carrier_id, period_month, **counts)
    approve_payment(api, result["payment"]["id"])
    payment = disburse_payment(api, result["payment"]["id"])
    period = get_success_data(api.get_service_period(result["period"]["id"], ADMIN))
    return {"period": period, "payment": payment}


# ─── petitions, hold-in and replacement ──────────────────────────────

def file_petition(api: ApiClient, agreement: Dict[str, Any], **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_termination_petition(
            f.petition_payload(agreement["community_id"], agreement["id"], **overrides),
            make_community_rep_headers(agreement["community_id"]),
        ),
        expected_status=201,
    )


def petition_under_review(api: ApiClient, agreement: Dict[str, Any],
                          **overrides) -> Dict[str, Any]:
    """File a petition and open review on it."""
    petition = file_petition(api, agreement, **overrides)
    return get_success_data(
        api.petition_decision(
            petition["id"], f.petition_decision_payload(DECISION_OPEN_REVIEW), OFFICER
        )
    )


def build_hold_in(api: ApiClient, award: Award, **overrides) -> Dict[str, Any]:
    """Drive an ACTIVE agreement into HOLD_IN through a granted petition.

    Returns {"petition", "agreement", "community", "replacement_solicitation"}.
    """
    petition = petition_under_review(api, award.agreement, **overrides)
    petition = get_success_data(
        api.petition_decision(
            petition["id"],
            f.petition_decision_payload(DECISION_GRANT_WITH_HOLD_IN),
            OFFICER,
        )
    )
    agreement = award.reload()
    community = get_success_data(api.get_community(award.community_id, ADMIN))
    replacements = get_success_data(
        api.list_community_solicitations(
            award.community_id, ADMIN, {"created_reason": "REPLACEMENT"}
        )
    )
    return {
        "petition": petition,
        "agreement": agreement,
        "community": community,
        "replacement_solicitation": replacements[0] if replacements else None,
    }


def replacement_solicitations(api: ApiClient, community_id: str) -> List[Dict[str, Any]]:
    return get_success_data(
        api.list_community_solicitations(
            community_id, ADMIN, {"created_reason": "REPLACEMENT"}
        )
    )


def terminate_agreement(api: ApiClient, agreement_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.agreement_status_action(
            agreement_id, f.agreement_status_payload(AGREEMENT_TERMINATE), ADMIN
        )
    )


# ─── renegotiations ──────────────────────────────────────────────────

def file_fuel_renegotiation(api: ApiClient, award: Award, fuel_index_month: str,
                            requested_annual_subsidy_usd: float,
                            **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_rate_renegotiation(
            f.fuel_renegotiation_payload(
                award.agreement_id,
                fuel_index_month,
                requested_annual_subsidy_usd,
                **overrides,
            ),
            award.carrier_headers,
        ),
        expected_status=201,
    )


def file_cost_renegotiation(api: ApiClient, award: Award,
                            documented_cost_increase_pct: float,
                            requested_annual_subsidy_usd: float,
                            **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_rate_renegotiation(
            f.cost_renegotiation_payload(
                award.agreement_id,
                documented_cost_increase_pct,
                requested_annual_subsidy_usd,
                **overrides,
            ),
            award.carrier_headers,
        ),
        expected_status=201,
    )
