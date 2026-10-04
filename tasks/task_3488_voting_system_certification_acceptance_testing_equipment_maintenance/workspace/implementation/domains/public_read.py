"""Public transparency read (PRD 3.10): system summary, certificate counts,
campaign count, and published-audit count. Open to every role with no
ownership checks. The certificate count applies the same lazy expiry sweep as
the certificate read path.
"""
from flask import Blueprint

from auth import auth_context
from domains.certificates import sweep_certificate
from domains.systems import get_system_or_404
from envelope import ok_object
from store import db

bp = Blueprint("public_read", __name__)


@bp.get("/evote/public/voting-systems/<system_id>/documentation")
def public_documentation(system_id):
    auth_context()
    system = get_system_or_404(system_id)
    for cert in db.certificates.values():
        if cert["voting_system_id"] == system_id:
            sweep_certificate(cert)
    active_certs = sum(
        1 for cert in db.certificates.values()
        if cert["voting_system_id"] == system_id and cert["status"] == "ACTIVE"
    )
    campaign_count = sum(
        1 for c in db.certification_campaigns.values() if c["voting_system_id"] == system_id
    )
    public_audits = 0
    for audit in db.post_election_audits.values():
        if not audit["report_public"]:
            continue
        definition = db.election_definitions.get(audit["election_definition_id"])
        if definition is None:
            continue
        proc = db.procurements.get(definition["procurement_id"])
        if proc is not None and proc["voting_system_id"] == system_id:
            public_audits += 1
    return ok_object({
        "system_id": system["id"],
        "model_name": system["model_name"],
        "software_baseline_version": system["software_baseline_version"],
        "hardware_class": system["hardware_class"],
        "system_status": system["status"],
        "active_certificate_count": active_certs,
        "campaign_count": campaign_count,
        "public_audit_count": public_audits,
    }, 200)
