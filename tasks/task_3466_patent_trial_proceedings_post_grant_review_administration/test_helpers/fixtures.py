"""Composite setup helpers (PRD §3 workflows).

Every helper builds preconditions from scratch using only PRD-declared
endpoints, because each test starts against an empty database. Setup calls
use the lenient get_success_data validator so a setup failure surfaces as a
clear "Setup step failed" error.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_success

from .api_client import api_client
from .constants import BASE_FEE_CENTS, DEFAULT_CLOCK_ISO
from .factories import (
    create_amendment_motion_payload,
    create_brief_payload,
    create_declaration_payload,
    create_discovery_payload,
    create_extension_payload,
    create_hearing_room_payload,
    create_litigation_matter_payload,
    create_party_payload,
    create_patent_payload,
    create_petition_payload,
    create_decision_payload,
    outcomes_payload,
    per_ground_scores,
    schedule_payload,
    substitute_claim,
)
from .test_users import TEST_USERS, make_patent_owner_headers, make_petitioner_headers

ADMIN = TEST_USERS["admin_headers"]
PANEL = TEST_USERS["panel_headers"]
APPEALS = TEST_USERS["appeals_headers"]


# --- Clock -------------------------------------------------------------------

def set_clock(to_iso8601: str = DEFAULT_CLOCK_ISO) -> dict:
    """Set the logical clock (PRD §2.4). Returns {current_utc}."""
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    return get_success_data(resp, 200)


# --- Docket registration -----------------------------------------------------

def create_party(name: str, party_type: str, counsel_firm: Optional[str] = None) -> dict:
    payload = create_party_payload(name=name, party_type=party_type)
    if counsel_firm is not None:
        payload["counsel_firm"] = counsel_firm
    resp = api_client.create_party(payload, ADMIN)
    return get_success_data(resp, 201)


def create_patent(owner_id: str, total_claims: int = 2, **overrides) -> dict:
    payload = create_patent_payload(
        owner_id=owner_id, total_claims=total_claims, **overrides
    )
    resp = api_client.create_patent(payload, ADMIN)
    return get_success_data(resp, 201)


def get_patent(patent_id: str) -> dict:
    return get_success_data(api_client.get_patent(patent_id, ADMIN), 200)


def create_litigation_matter(patent_id: str, defendant_party_id: str,
                             complaint_served_date: str,
                             trial_date: Optional[str] = None,
                             **overrides) -> dict:
    payload = create_litigation_matter_payload(
        defendant_party_id=defendant_party_id,
        complaint_served_date=complaint_served_date,
        **overrides,
    )
    if trial_date is not None:
        payload["trial_date"] = trial_date
    resp = api_client.create_litigation_matter(patent_id, payload, ADMIN)
    return get_success_data(resp, 201)


def get_litigation_matter(matter_id: str) -> dict:
    return get_success_data(api_client.get_litigation_matter(matter_id, ADMIN), 200)


def patch_litigation_matter(matter_id: str, payload: dict) -> dict:
    resp = api_client.patch_litigation_matter(matter_id, payload, ADMIN)
    return get_success_data(resp, 200)


def create_hearing_room(name: Optional[str] = None, capacity: int = 20) -> dict:
    payload = create_hearing_room_payload(capacity=capacity)
    if name is not None:
        payload["name"] = name
    resp = api_client.create_hearing_room(payload, ADMIN)
    return get_success_data(resp, 201)


# --- Petition lifecycle ------------------------------------------------------

def file_petition(petitioner_id: str, patent_id: str,
                  expected_patent_version: Optional[int] = None,
                  **overrides) -> dict:
    """File a petition as the given petitioner party (OCC version auto-read)."""
    if expected_patent_version is None:
        expected_patent_version = get_patent(patent_id)["version"]
    payload = create_petition_payload(
        patent_id=patent_id,
        petitioner_id=petitioner_id,
        expected_patent_version=expected_patent_version,
        **overrides,
    )
    resp = api_client.create_petition(payload, make_petitioner_headers(petitioner_id))
    return get_success_data(resp, 201)


def get_petition(petition_id: str) -> dict:
    return get_success_data(api_client.get_petition(petition_id, PANEL), 200)


def accord(petition_id: str) -> dict:
    resp = api_client.accord_filing_date(petition_id, PANEL)
    return get_success_data(resp, 200)


def decide_institution(petition_id: str, scores: list, lead_judge_user_id: str) -> dict:
    payload = create_decision_payload(scores, lead_judge_user_id)
    resp = api_client.decide_institution(petition_id, payload, PANEL)
    return get_success_data(resp, 201)


def get_proceeding(proceeding_id: str) -> dict:
    return get_success_data(api_client.get_proceeding(proceeding_id, PANEL), 200)


# --- World builders ----------------------------------------------------------

def new_world(petitioner_name: str = "Petitioner LLC",
              owner_name: str = "Owner LLC",
              total_claims: int = 2,
              patent_number: Optional[str] = None,
              issue_date: str = "2020-01-01T00:00:00Z",
              title: str = "Test Patent",
              clock: str = DEFAULT_CLOCK_ISO,
              matters: Optional[List[dict]] = None) -> Dict[str, Any]:
    """Clock + petitioner party + owner party + one patent owned by the owner.

    `matters` entries: {complaint_served_date, trial_date?, court_name?,
    docket_number?, defendant?} — defendant defaults to the petitioner party.
    """
    set_clock(clock)
    petitioner = create_party(petitioner_name, "PETITIONER")
    owner = create_party(owner_name, "PATENT_OWNER")
    patent_kw: Dict[str, Any] = {"issue_date": issue_date, "title": title}
    if patent_number is not None:
        patent_kw["patent_number"] = patent_number
    patent = create_patent(owner["id"], total_claims=total_claims, **patent_kw)
    world: Dict[str, Any] = {
        "petitioner": petitioner,
        "owner": owner,
        "patent": patent,
        "petitioner_headers": make_petitioner_headers(petitioner["id"]),
        "owner_headers": make_patent_owner_headers(owner["id"]),
        "matters": [],
    }
    for spec in matters or []:
        spec = dict(spec)
        defendant = spec.pop("defendant", None) or petitioner["id"]
        world["matters"].append(
            create_litigation_matter(patent["id"], defendant, **spec)
        )
    return world


def setup_instituted_proceeding(*, total_claims: int = 2,
                                challenged_claims=(1, 2),
                                scores: Optional[list] = None,
                                lead_judge: str = "judge-lead-1",
                                matters: Optional[List[dict]] = None,
                                review_type: str = "IPR",
                                grounds: Optional[list] = None,
                                prior_art: Optional[list] = None,
                                fee_paid_cents: int = BASE_FEE_CENTS,
                                clock: str = DEFAULT_CLOCK_ISO,
                                petitioner_name: str = "Petitioner LLC",
                                owner_name: str = "Owner LLC",
                                patent_number: Optional[str] = None,
                                issue_date: str = "2020-01-01T00:00:00Z"
                                ) -> Dict[str, Any]:
    """World + petition filed, accorded, and INSTITUTED. Returns the bundle."""
    world = new_world(
        petitioner_name=petitioner_name, owner_name=owner_name,
        total_claims=total_claims, patent_number=patent_number,
        issue_date=issue_date, clock=clock, matters=matters,
    )
    petition_overrides: Dict[str, Any] = {
        "review_type": review_type,
        "challenged_claims": list(challenged_claims),
        "fee_paid_cents": fee_paid_cents,
    }
    if grounds is not None:
        petition_overrides["grounds"] = grounds
    if prior_art is not None:
        petition_overrides["prior_art"] = prior_art
    petition = file_petition(
        world["petitioner"]["id"], world["patent"]["id"], **petition_overrides
    )
    accord(petition["id"])
    if scores is None:
        scores = per_ground_scores(*[(c, 80) for c in challenged_claims])
    decision = decide_institution(petition["id"], scores, lead_judge)
    proceeding = get_proceeding(decision["proceeding_id"])
    world.update({
        "petition": get_petition(petition["id"]),
        "decision": decision,
        "proceeding": proceeding,
        "lead_judge": lead_judge,
        "challenged_claims": list(challenged_claims),
    })
    return world


def add_petitioned_patent(world: Dict[str, Any], *, patent_number: str,
                          total_claims: int = 2,
                          challenged_claims=(1, 2),
                          review_type: str = "IPR",
                          grounds: Optional[list] = None,
                          prior_art: Optional[list] = None,
                          fee_paid_cents: int = BASE_FEE_CENTS,
                          matters: Optional[List[dict]] = None,
                          do_accord: bool = False,
                          scores: Optional[list] = None,
                          lead_judge: str = "judge-lead-2",
                          do_decide: bool = False) -> Dict[str, Any]:
    """Second patent + petition inside an existing world (same parties).

    Optionally accords the petition and/or decides institution. Returns a
    sub-bundle with patent, matters, petition and (when decided) decision
    and proceeding.
    """
    patent = create_patent(
        world["owner"]["id"], total_claims=total_claims,
        patent_number=patent_number,
    )
    created_matters = []
    for spec in matters or []:
        spec = dict(spec)
        defendant = spec.pop("defendant", None) or world["petitioner"]["id"]
        created_matters.append(
            create_litigation_matter(patent["id"], defendant, **spec)
        )
    petition_overrides: Dict[str, Any] = {
        "review_type": review_type,
        "challenged_claims": list(challenged_claims),
        "fee_paid_cents": fee_paid_cents,
    }
    if grounds is not None:
        petition_overrides["grounds"] = grounds
    if prior_art is not None:
        petition_overrides["prior_art"] = prior_art
    petition = file_petition(world["petitioner"]["id"], patent["id"],
                             **petition_overrides)
    bundle: Dict[str, Any] = {
        "patent": patent,
        "matters": created_matters,
        "petition": petition,
        "challenged_claims": list(challenged_claims),
    }
    if do_accord:
        accord(petition["id"])
        bundle["petition"] = get_petition(petition["id"])
    if do_decide:
        if scores is None:
            scores = per_ground_scores(*[(c, 80) for c in challenged_claims])
        bundle["decision"] = decide_institution(petition["id"], scores, lead_judge)
        bundle["proceeding"] = get_proceeding(bundle["decision"]["proceeding_id"])
        bundle["petition"] = get_petition(petition["id"])
    return bundle


# --- Briefing ----------------------------------------------------------------

def file_brief(proceeding_id: str, brief_type: str, page_count: int,
               headers: dict) -> dict:
    resp = api_client.create_brief(
        proceeding_id, create_brief_payload(brief_type, page_count), headers
    )
    return get_success_data(resp, 201)


def file_po_response(world: Dict[str, Any], page_count: int = 50) -> dict:
    return file_brief(world["proceeding"]["id"], "PO_RESPONSE", page_count,
                      world["owner_headers"])


def file_petitioner_reply(world: Dict[str, Any], page_count: int = 25) -> dict:
    return file_brief(world["proceeding"]["id"], "PETITIONER_REPLY", page_count,
                      world["petitioner_headers"])


def file_po_sur_reply(world: Dict[str, Any], page_count: int = 18) -> dict:
    return file_brief(world["proceeding"]["id"], "PO_SUR_REPLY", page_count,
                      world["owner_headers"])


def create_declaration(brief_id: str, headers: dict, **overrides) -> dict:
    resp = api_client.create_expert_declaration(
        brief_id, create_declaration_payload(**overrides), headers
    )
    return get_success_data(resp, 201)


# --- Discovery ---------------------------------------------------------------

def create_discovery_request(proceeding_id: str, headers: dict,
                             discovery_type: str = "ROUTINE",
                             factor_scores: Optional[list] = None) -> dict:
    payload = create_discovery_payload(discovery_type=discovery_type)
    if factor_scores is not None:
        payload["factor_scores"] = factor_scores
    resp = api_client.create_discovery_request(proceeding_id, payload, headers)
    return get_success_data(resp, 201)


def rule_discovery(request_id: str) -> dict:
    resp = api_client.rule_discovery_request(request_id, PANEL)
    return get_success_data(resp, 200)


# --- Amendment practice ------------------------------------------------------

def create_amendment_motion(proceeding_id: str, headers: dict,
                            original_claim_numbers=(1,)) -> dict:
    subs = [substitute_claim(c) for c in original_claim_numbers]
    resp = api_client.create_amendment_motion(
        proceeding_id, create_amendment_motion_payload(subs), headers
    )
    return get_success_data(resp, 201)


def resolve_amendment_motion(motion_id: str, outcome: str, headers: dict,
                             rationale: Optional[str] = None) -> dict:
    payload: Dict[str, Any] = {"outcome": outcome}
    if rationale is not None:
        payload["rationale"] = rationale
    resp = api_client.resolve_amendment_motion(motion_id, payload, headers)
    return get_success_data(resp, 200)


# --- Extension ---------------------------------------------------------------

def request_extension(proceeding_id: str, headers: dict,
                      justification: Optional[str] = None) -> dict:
    payload = create_extension_payload()
    if justification is not None:
        payload["justification"] = justification
    resp = api_client.create_extension_request(proceeding_id, payload, headers)
    return get_success_data(resp, 200)


# --- Oral hearing ------------------------------------------------------------

def request_hearing(proceeding_id: str, headers: dict,
                    argument_minutes: Optional[int] = None) -> dict:
    payload: Dict[str, Any] = {}
    if argument_minutes is not None:
        payload["argument_minutes"] = argument_minutes
    resp = api_client.create_oral_hearing(proceeding_id, payload, headers)
    return get_success_data(resp, 201)


def schedule_hearing(hearing_id: str, room_id: str,
                     start_at: str = "2027-02-01T09:00:00Z",
                     end_at: str = "2027-02-01T10:00:00Z") -> dict:
    resp = api_client.schedule_oral_hearing(
        hearing_id, schedule_payload(room_id, start_at, end_at), PANEL
    )
    return get_success_data(resp, 200)


def resolve_hearing(hearing_id: str, outcome: str, headers: dict) -> dict:
    resp = api_client.resolve_oral_hearing(hearing_id, {"outcome": outcome}, headers)
    return get_success_data(resp, 200)


# --- Composite lifecycle tiers ----------------------------------------------

def setup_hearing_scheduled(world: Dict[str, Any], *,
                            file_reply: bool = True,
                            po_pages: int = 50,
                            reply_pages: int = 25,
                            hearing_start: str = "2027-02-01T09:00:00Z",
                            hearing_end: str = "2027-02-01T10:00:00Z",
                            requester: str = "petitioner") -> Dict[str, Any]:
    """From an instituted world: briefs + room + hearing REQUESTED -> SCHEDULED.

    Phase lands in HEARING_PHASE.
    """
    proc_id = world["proceeding"]["id"]
    world["po_response"] = file_po_response(world, po_pages)
    if file_reply:
        world["reply"] = file_petitioner_reply(world, reply_pages)
    world["room"] = create_hearing_room()
    headers = (world["petitioner_headers"] if requester == "petitioner"
               else world["owner_headers"])
    world["hearing"] = request_hearing(proc_id, headers)
    world["hearing"] = schedule_hearing(
        world["hearing"]["id"], world["room"]["id"], hearing_start, hearing_end
    )
    world["proceeding"] = get_proceeding(proc_id)
    return world


def setup_decision_phase(world: Dict[str, Any], *,
                         hearing_outcome: str = "WAIVED",
                         **hearing_kw) -> Dict[str, Any]:
    """Full trial through hearing resolution. Phase lands in DECISION_PHASE."""
    waive_headers = hearing_kw.pop("waive_headers", None)
    world = setup_hearing_scheduled(world, **hearing_kw)
    if hearing_outcome == "HELD":
        resolve_hearing(world["hearing"]["id"], "HELD", PANEL)
    else:
        # WAIVED belongs to a party to the proceeding (PRD §3.7).
        party_headers = waive_headers or world["petitioner_headers"]
        resolve_hearing(world["hearing"]["id"], "WAIVED", party_headers)
    world["proceeding"] = get_proceeding(world["proceeding"]["id"])
    return world


def issue_final_decision(proceeding_id: str, outcomes: list) -> dict:
    resp = api_client.create_final_decision(proceeding_id, {"outcomes": outcomes},
                                            PANEL)
    return get_success_data(resp, 201)


def setup_decided_proceeding(world: Optional[Dict[str, Any]] = None, *,
                             outcomes: Optional[list] = None,
                             institute_kw: Optional[dict] = None,
                             hearing_outcome: str = "WAIVED",
                             **hearing_kw) -> Dict[str, Any]:
    """Instituted world carried through a final written decision (DECIDED)."""
    if world is None:
        world = setup_instituted_proceeding(**(institute_kw or {}))
    world = setup_decision_phase(world, hearing_outcome=hearing_outcome, **hearing_kw)
    if outcomes is None:
        outcomes = outcomes_payload(
            *[(c, "NOT_UNPATENTABLE") for c in world["challenged_claims"]]
        )
    world["fwd"] = issue_final_decision(world["proceeding"]["id"], outcomes)
    world["proceeding"] = get_proceeding(world["proceeding"]["id"])
    world["patent"] = get_patent(world["patent"]["id"])
    world["petition"] = get_petition(world["petition"]["id"])
    return world


def file_appeal(proceeding_id: str, headers: dict) -> dict:
    resp = api_client.create_appeal(proceeding_id, headers)
    return get_success_data(resp, 201)


def decide_appeal(appeal_id: str, outcome: str,
                  remand_instructions: Optional[str] = None) -> dict:
    payload: Dict[str, Any] = {"outcome": outcome}
    if remand_instructions is not None:
        payload["remand_instructions"] = remand_instructions
    resp = api_client.decide_appeal(appeal_id, payload, APPEALS)
    return get_success_data(resp, 200)


def setup_decided_with_appeal(world: Optional[Dict[str, Any]] = None, *,
                              appellant: str = "petitioner",
                              **kw) -> Dict[str, Any]:
    """DECIDED world plus one FILED appeal by the chosen party."""
    world = setup_decided_proceeding(world, **kw)
    headers = (world["petitioner_headers"] if appellant == "petitioner"
               else world["owner_headers"])
    world["appeal"] = file_appeal(world["proceeding"]["id"], headers)
    return world
