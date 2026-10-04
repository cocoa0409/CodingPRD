"""ProtectionPin routes: manual reissue (OCC-guarded) and the annual
regeneration ops batch (idempotent per tax_year)."""
from flask import Blueprint

from auth import require_roles
from domain import active_pin, create_pin, get_taxpayer, new_record, pub, touch
from envelope import created, ok
from errors import err
from store import DB
from validate import body, opt_enum, req_int, req_str
from validate import sorted_created

bp = Blueprint("pins", __name__)

DELIVERY_CHANNELS = ("POSTAL_MAIL", "ONLINE_ACCOUNT")


@bp.post("/identity-protection/protection-pins")
def reissue_pin():
    require_roles(["SystemAdmin", "TaxpayerAdvocate"])
    b = body()
    # Priority 4: body-carried taxpayer_id must resolve.
    tid = b.get("taxpayer_id")
    taxpayer = None
    if tid is not None:
        taxpayer = get_taxpayer(tid)
    # Priority 5: OCC.
    expected = b.get("expected_taxpayer_version")
    if taxpayer is not None and expected is not None and expected != taxpayer["version"]:
        err("ERR_STALE_VERSION")
    # Priority 11: reissue requires ENROLLED.
    if taxpayer is not None and taxpayer["ip_pin_enrollment"] != "ENROLLED":
        err("ERR_NOT_ENROLLED")
    # Priority 14: payload shape.
    tid = req_str(b, "taxpayer_id")
    if taxpayer is None:
        err("ERR_TAXPAYER_NOT_FOUND")
    tax_year = req_int(b, "tax_year")
    expected = req_int(b, "expected_taxpayer_version")
    if expected != taxpayer["version"]:
        err("ERR_STALE_VERSION")
    channel = opt_enum(b, "delivery_channel", DELIVERY_CHANNELS)
    pin = create_pin(taxpayer, tax_year, channel or taxpayer["pin_delivery_channel"])
    touch(taxpayer)  # reissue increments Taxpayer.version by 1
    return created(pub(pin))


@bp.post("/identity-protection/ops/annual-pin-regeneration")
def annual_regeneration():
    require_roles(["SystemAdmin"])
    tax_year = req_int(body(), "tax_year")
    created_count = 0
    superseded_count = 0
    skipped_count = 0
    enrolled = [t for t in DB.taxpayers.values() if t["ip_pin_enrollment"] == "ENROLLED"]
    for t in sorted_created(enrolled):
        if active_pin(t["id"], tax_year) is not None:
            skipped_count += 1
            continue
        create_pin(t, tax_year, t["pin_delivery_channel"])
        for p in DB.pins.values():
            if (p["taxpayer_id"] == t["id"] and p["tax_year"] != tax_year
                    and p["status"] == "ACTIVE"):
                p["status"] = "SUPERSEDED"
                touch(p)
                superseded_count += 1
        created_count += 1
    return ok({
        "created_count": created_count,
        "superseded_count": superseded_count,
        "skipped_count": skipped_count,
    })
