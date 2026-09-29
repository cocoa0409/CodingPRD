"""Warning content selection: the seven pinned steps of PRD 3.7."""
from util import D
import db
from services import calc

BASE_URL = "https://www.P65Warnings.ca.gov"
PLACES_URL = "https://www.P65Warnings.ca.gov/places"
FOOD_URL = "https://www.P65Warnings.ca.gov/food"

HARM_CLASS_ORDER = ("CANCER", "REPRODUCTIVE")
CHANNEL_ORDER = ("LABEL", "CATALOG", "INTERNET_POS", "POSTED_SIGN")
SHORT_LABEL_THRESHOLD = D("5")

LONG_TEMPLATE = ("WARNING: This product can expose you to chemicals including "
                 "{chem_list}, which {verb} known to the State of California to "
                 "cause {harm_clause}. For more information go to {website_url}.")
OCCUPANCY_TEMPLATE = ("WARNING: Entering this area can expose you to chemicals "
                      "including {chem_list}, which {verb} known to the State of "
                      "California to cause {harm_clause}. For more information go "
                      "to {website_url}.")
SHORT_TEMPLATE = "WARNING: {harm_label} risk from exposure to {chemical} - {website_url}"

HARM_CLAUSE = {
    ("CANCER",): "cancer",
    ("REPRODUCTIVE",): "birth defects or other reproductive harm",
    ("CANCER", "REPRODUCTIVE"): "cancer and birth defects or other reproductive harm",
}
HARM_LABEL = {
    ("CANCER",): "Cancer",
    ("REPRODUCTIVE",): "Reproductive Harm",
    ("CANCER", "REPRODUCTIVE"): "Cancer and Reproductive Harm",
}


def qualifying_set(product):
    """Step one: FINAL assessments whose result is adverse."""
    return [a for a in calc.assessments_of(product["id"])
            if a["status"] == "FINAL" and a["result"] in calc.QUALIFYING_RESULTS]


def _rank_key(assessment):
    chemical = db.get("listed_chemicals", assessment["chemical_id"])
    no_harbor = assessment["result"] == "NO_SAFE_HARBOR"
    margin = assessment.get("margin_ratio")
    level = None if chemical is None else chemical.get("safe_harbor_level_ug_per_day")
    name = "" if chemical is None else chemical.get("chemical_name") or ""
    return (
        0 if no_harbor else 1,
        D(0) if margin is None else -D(margin),
        (0, D(0)) if level is None else (1, D(level)),
        name,
    )


def required_channels(product):
    """Step seven, in the pinned channel order."""
    channels = product.get("distribution_channels") or []
    out = []
    if "RETAIL" in channels:
        out.append("LABEL")
    if "CATALOG" in channels:
        out.append("CATALOG")
    if "INTERNET" in channels:
        out.append("INTERNET_POS")
    if product.get("occupancy_type") not in (None, "NONE"):
        out.append("POSTED_SIGN")
    return out


def compute_content(determination, product):
    """Runs at determination create time and again on approval."""
    if determination["decision"] == "NO_WARNING_REQUIRED":
        determination["warning_type"] = "NONE"
        determination["symbol_required"] = False
        determination["named_chemicals"] = []
        determination["website_url"] = None
        determination["warning_text"] = None
        determination["required_channels"] = []
        return determination

    qualifying = qualifying_set(product)

    # step two: warning_type
    if product.get("occupancy_type") not in (None, "NONE"):
        warning_type = "OCCUPANCY"
    elif D(product["label_area_sq_in"]) < SHORT_LABEL_THRESHOLD:
        warning_type = "PRODUCT_SPECIFIC_SHORT"
    else:
        warning_type = "PRODUCT_SPECIFIC_LONG"

    # step three: named_chemicals, at most one name per harm class
    named = []
    for harm_class in HARM_CLASS_ORDER:
        subset = []
        for assessment in qualifying:
            chemical = db.get("listed_chemicals", assessment["chemical_id"])
            if chemical is not None and chemical.get("harm_class") == harm_class:
                subset.append(assessment)
        if not subset:
            continue
        subset.sort(key=_rank_key)
        chemical = db.get("listed_chemicals", subset[0]["chemical_id"])
        named.append(chemical["chemical_name"])

    # step four: symbol_required
    symbol_required = not (product.get("product_category") == "FOOD"
                           and warning_type != "OCCUPANCY")

    # step five: website_url
    if warning_type == "OCCUPANCY":
        website_url = PLACES_URL
    elif product.get("product_category") == "FOOD":
        website_url = FOOD_URL
    else:
        website_url = BASE_URL

    # step six: warning_text
    classes = set()
    for assessment in qualifying:
        chemical = db.get("listed_chemicals", assessment["chemical_id"])
        if chemical is not None and chemical.get("harm_class"):
            classes.add(chemical["harm_class"])
    key = tuple(c for c in HARM_CLASS_ORDER if c in classes)
    harm_clause = HARM_CLAUSE.get(key)
    harm_label = HARM_LABEL.get(key)
    verb = "is" if len(named) == 1 else "are"
    chem_list = ", ".join(named)
    if warning_type == "PRODUCT_SPECIFIC_SHORT":
        warning_text = SHORT_TEMPLATE.format(
            harm_label=harm_label, chemical=named[0] if named else "",
            website_url=website_url)
    elif warning_type == "OCCUPANCY":
        warning_text = OCCUPANCY_TEMPLATE.format(
            chem_list=chem_list, verb=verb, harm_clause=harm_clause,
            website_url=website_url)
    else:
        warning_text = LONG_TEMPLATE.format(
            chem_list=chem_list, verb=verb, harm_clause=harm_clause,
            website_url=website_url)

    determination["warning_type"] = warning_type
    determination["symbol_required"] = symbol_required
    determination["named_chemicals"] = named
    determination["website_url"] = website_url
    determination["warning_text"] = warning_text
    determination["required_channels"] = required_channels(product)
    return determination
