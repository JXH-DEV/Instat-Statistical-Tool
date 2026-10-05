"""Names for the kinds of column a table can have and for the subjects it can be about, in either language."""

from __future__ import annotations

from ..i18n import N_, tr

# role -> (the thing, "by" + the thing); Albanian needs the second form because "sipas" takes another case
_ROLES = {
    "age_group": (N_("age group"), N_("by age group")),
    "sex": (N_("sex"), N_("by sex")),
    "region": (N_("region"), N_("by region")),
    "activity": (N_("economic activity"), N_("by economic activity")),
    "product": (N_("product group"), N_("by product group")),
    "country": (N_("country"), N_("by country")),
    "category": (N_("category"), N_("by category")),
    "education": (N_("education level"), N_("by education level")),
    "labour_status": (N_("labour status"), N_("by labour status")),
    "urban_rural": (N_("urban/rural area"), N_("by urban/rural area")),
    "ownership": (N_("ownership"), N_("by ownership")),
    "month": (N_("month"), N_("by month")),
    "year": (N_("year"), N_("by year")),
    "period_label": (N_("period"), N_("by period")),
    "marital_status": (N_("marital status"), N_("by marital status")),
    "household_status": (N_("household status"), N_("by household status")),
    "code": (N_("classification code"), N_("by classification code")),
    "measure_name": (N_("indicator"), N_("by indicator")),
}

_TOPICS = {
    "prices": N_("prices"), "labour": N_("labour market"), "national_accounts": N_("national accounts"),
    "trade": N_("foreign trade"), "population": N_("population"), "tourism": N_("tourism"), "wages": N_("wages"),
    "education": N_("education"), "health": N_("health"), "agriculture": N_("agriculture"), "energy": N_("energy"),
    "construction": N_("construction"), "transport": N_("transport"), "business": N_("business"),
    "poverty_living": N_("poverty and living standards"), "environment": N_("environment"),
    "ict": N_("information and communication technology"), "crime": N_("crime and justice"), "gender": N_("gender"),
}


def role_name(role: str) -> str:
    """``age_group`` -> "age group"."""
    return tr(_ROLES[role][0]) if role in _ROLES else role.replace("_", " ")


def by_role(role: str) -> str:
    """``age_group`` -> "by age group"."""
    return tr(_ROLES[role][1]) if role in _ROLES else tr("by {name}", name=role.replace("_", " "))


def topic_name(topic: str) -> str:
    return tr(_TOPICS[topic]) if topic in _TOPICS else topic.replace("_", " ")
