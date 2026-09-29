"""Pre-built role headers for every role named by the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Opaque agency and auditor identities. The PRD records the caller's X-User-ID on
# issuance, approval and adjudication, and requires the issuer, the approver and
# the adjudicator to be distinct people, so each duty gets its own identity.
AGENCY_REGISTRAR_ID = "fws-user-registrar"
AGENCY_REVIEWER_ID = "fws-user-reviewer"
AGENCY_ISSUER_ID = "fws-user-issuer"
AGENCY_APPROVER_ID = "fws-user-approver"
AGENCY_ADJUDICATOR_ID = "fws-user-adjudicator"
AUDITOR_ID = "fws-user-auditor"

TEST_USERS = {
    # Proponent identity is entity backed: the shared constant is only safe for
    # calls that are refused before ownership is resolved.
    "proponent_headers": build_user_headers("prd-proponent-placeholder", "Proponent"),
    "agency_registrar_headers": build_user_headers(AGENCY_REGISTRAR_ID, "WildlifeAgency"),
    "agency_reviewer_headers": build_user_headers(AGENCY_REVIEWER_ID, "WildlifeAgency"),
    "agency_issuer_headers": build_user_headers(AGENCY_ISSUER_ID, "WildlifeAgency"),
    "agency_approver_headers": build_user_headers(AGENCY_APPROVER_ID, "WildlifeAgency"),
    "agency_adjudicator_headers": build_user_headers(AGENCY_ADJUDICATOR_ID, "WildlifeAgency"),
    "auditor_headers": build_user_headers(AUDITOR_ID, "Auditor"),
}


def make_proponent_headers(user_id: str) -> dict:
    """Headers for the Proponent role, whose X-User-ID is a Proponent row id.

    Every ownership-gated Proponent call must pass the real proponent's id here.
    """
    return build_user_headers(user_id, "Proponent")


def make_agency_headers(user_id: str) -> dict:
    """Headers for a WildlifeAgency caller with an explicit opaque identity."""
    return build_user_headers(user_id, "WildlifeAgency")


def make_auditor_headers(user_id: str = AUDITOR_ID) -> dict:
    """Headers for an Auditor caller.

    The PRD does not require an X-User-ID for the Auditor role, so the canonical
    Auditor headers omit it entirely; pass a user id only when a test needs one.
    """
    return auditor_headers_without_user_id()


def auditor_headers_without_user_id() -> dict:
    """Auditor headers carrying only the role, as the PRD permits."""
    return {"X-User-Role": "Auditor", "Content-Type": "application/json"}


def anonymous_headers() -> dict:
    """Headers for the Anonymous role, which carries no user identity."""
    return {"X-User-Role": "Anonymous", "Content-Type": "application/json"}


def headers_without_role() -> dict:
    """Headers that omit X-User-Role entirely."""
    return {"Content-Type": "application/json"}


def headers_with_blank_role(user_id: str = "prd-proponent-placeholder") -> dict:
    """Headers whose X-User-Role is present but empty."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


def headers_with_whitespace_role(user_id: str = "prd-proponent-placeholder") -> dict:
    """Headers whose X-User-Role contains only whitespace."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "   ",
        "Content-Type": "application/json",
    }


def headers_with_blank_user_id(role: str = "Proponent") -> dict:
    """Headers whose X-User-ID is present but empty."""
    return {
        "X-User-ID": "",
        "X-User-Role": role,
        "Content-Type": "application/json",
    }


def headers_without_user_id(role: str = "Proponent") -> dict:
    """Headers that omit X-User-ID entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_unknown_role(role: str = "Regulator", user_id: str = "some-user") -> dict:
    """Headers naming a role string outside the four the PRD recognises."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": role,
        "Content-Type": "application/json",
    }


def no_headers() -> dict:
    """A request carrying no identity headers at all."""
    return {"Content-Type": "application/json"}
