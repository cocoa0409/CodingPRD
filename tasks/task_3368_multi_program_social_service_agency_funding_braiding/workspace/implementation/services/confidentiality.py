"""confidentiality_scope_resolution.

Two independent instruments control cross-program access: the agency-set
confidentiality_tier and the client's consent_scope paired with
consent_expires_on. The base (tier_first) variant governs every write path;
the consent_first variant is used only for the read-only shareable_domains
projection.
"""

import clock
from errors import ApiError


def _at(at):
    return at if at is not None else clock.now()


def _consent_valid(client, domain, at):
    scope = client.get("consent_scope") or []
    if domain not in scope:
        return False
    expires = client.get("consent_expires_on")
    if expires is None:
        # No expiry instant was recorded, so the consent never stops authorizing.
        return True
    return _at(at) <= expires


def allowed_tier_first(client, domain, at=None):
    """Base variant: the tier is consulted first and the first branch that
    matches wins. SEALED is absolute; consent never overrides it."""
    tier = client.get("confidentiality_tier") or "STANDARD"
    if tier == "SEALED":
        return False
    if tier == "PROTECTED":
        return _consent_valid(client, domain, at)
    return True


def allowed_consent_first(client, domain, at=None):
    """Read-only projection variant: valid consent short-circuits the tier,
    otherwise the tier_first rules apply unchanged."""
    if _consent_valid(client, domain, at):
        return True
    return allowed_tier_first(client, domain, at)


def assert_allowed(client, domain, at=None):
    if not allowed_tier_first(client, domain, at):
        raise ApiError(
            "ERR_CONFIDENTIALITY_SCOPE_DENIED",
            "The confidentiality tier of this client record refuses sharing "
            "for domain %s." % domain,
        )


def assert_client_readable(client, at=None):
    """The client read is one of the four operations guarded by the rule.

    A SEALED record is refused outright. A PROTECTED record is readable only
    while at least one consented domain is still authorized."""
    tier = client.get("confidentiality_tier") or "STANDARD"
    if tier == "SEALED":
        raise ApiError(
            "ERR_CONFIDENTIALITY_SCOPE_DENIED",
            "This client record is SEALED and may not be read.",
        )
    if tier == "PROTECTED":
        scope = client.get("consent_scope") or []
        if not any(_consent_valid(client, d, at) for d in scope):
            raise ApiError(
                "ERR_CONFIDENTIALITY_SCOPE_DENIED",
                "This client record is PROTECTED and no consented domain is "
                "currently authorized.",
            )


def shareable_domains(client, at=None):
    """The service_domain values this client consents to share, evaluated
    under the consent_first variant. Diagnostic only: it never authorizes a
    write."""
    out = []
    for domain in client.get("consent_scope") or []:
        if domain in out:
            continue
        if allowed_consent_first(client, domain, at):
            out.append(domain)
    return out
