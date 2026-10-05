"""INSTAT's 12 themes and 62 sub-topic pages (from its public A-Z index), with English + Albanian search terms.

Bundled so that topic search needs no network access at all; only *opening* a topic fetches one HTML page.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..i18n import N_, language, tr

BASE = "https://www.instat.gov.al"

THEMES: dict[str, tuple[str, str]] = {
    "economy-and-finance": ("Economy and Finance", "Ekonomia dhe Financat"),
    "demography-and-social-indicators": ("Demography and Social Indicators", "Demografia dhe Treguesit Social"),
    "agriculture-and-fishery": ("Agriculture and Fishery", "Bujqësia dhe Peshkimi"),
    "social-condition": ("Social Condition", "Kushtet Sociale"),
    "industry-trade-and-services": ("Industry, Trade and Services", "Industria, Tregtia dhe Shërbimet"),
    "labour-market-and-education": ("Labour Market and Education", "Tregu i Punës dhe Arsimi"),
    "international-trade": ("International Trade", "Tregtia e Jashtme"),
    "general-and-regional-statistics": ("General and Regional Statistics", "Statistika të Përgjithshme dhe Rajonale"),
    "science-technology-and-innovation": ("Science, Technology and Innovation", "Shkenca, Teknologjia dhe Inovacioni"),
    "environment-and-energy": ("Environment and Energy", "Mjedisi dhe Energjia"),
    "prices": ("Prices", "Çmimet"),
    "censuses": ("Censuses", "Regjistrimet"),
}


@dataclass(frozen=True)
class Topic:
    theme: str
    slug: str
    name: str
    keywords: tuple[str, ...] = field(default_factory=tuple)  # English and Albanian search terms

    @property
    def url(self) -> str:
        return f"{BASE}/en/themes/{self.theme}/{self.slug}/"

    @property
    def title(self) -> str:
        """The topic's name in the language that is switched on."""
        return tr(self.name)

    @property
    def theme_name(self) -> str:
        return THEMES[self.theme][1 if language() == "sq" else 0]

    @property
    def key(self) -> str:
        return f"{self.theme}/{self.slug}"


def _t(theme: str, slug: str, name: str, *kw: str) -> Topic:
    return Topic(theme, slug, name, tuple(kw))


TOPICS: list[Topic] = [
    _t("labour-market-and-education", "administrative-data-on-labour-market", N_("Administrative data on labour market"),
       "registered unemployed", "employment offices", "punësimi administrativ", "punëkërkues"),
    _t("agriculture-and-fishery", "agriculture", N_("Agriculture"), "crops", "farms", "harvest", "bujqësia", "kultura", "prodhimi bujqësor"),
    _t("censuses", "agriculture-census", N_("Agriculture Census"), "farm census", "regjistrimi i bujqësisë"),
    _t("economy-and-finance", "annual-accounts-by-institutional-sector", N_("Annual Accounts by Institutional Sector"),
       "sector accounts", "households sector", "llogaritë sektoriale"),
    _t("economy-and-finance", "banking-statistics", N_("Banking Statistics"), "banks", "credit", "deposits", "loans", "bankat", "kredia"),
    _t("demography-and-social-indicators", "births-deaths-and-marriages", N_("Births, deaths and marriages"),
       "births", "deaths", "marriages", "divorces", "fertility", "mortality", "lindjet", "vdekjet", "martesat", "shkurorëzimet"),
    _t("industry-trade-and-services", "business-registers", N_("Business Registers"), "enterprises", "companies", "ndërmarrjet", "regjistri i bizneseve"),
    _t("censuses", "census-of-population-and-housing", N_("Census of Population and Housing"),
       "census 2011", "census 2023", "population census", "housing census", "regjistrimi i popullsisë", "regjistrimi", "banesat"),
    _t("general-and-regional-statistics", "cities-and-degree-of-urbanization", N_("Cities and degree of urbanization"),
       "urban", "rural", "cities", "qytetet", "urbanizimi"),
    _t("industry-trade-and-services", "construction", N_("Construction"), "building permits", "dwellings", "ndërtimi", "leje ndërtimi"),
    _t("prices", "construction-cost-index", N_("Construction Cost Index"), "construction costs", "kostoja e ndërtimit"),
    _t("prices", "consumer-price-index", N_("Consumer Price Index"), "cpi", "inflation", "prices", "cost of living", "inflacioni", "çmimet", "indeksi i çmimeve të konsumit", "ick"),
    _t("demography-and-social-indicators", "crimes-and-criminal-justice", N_("Crimes and criminal justice"), "crime", "police", "courts", "prisons", "krimi", "drejtësia", "gjykatat"),
    _t("demography-and-social-indicators", "culture-and-sport", N_("Culture and Sport"), "museums", "libraries", "cinema", "sports", "kultura", "sporti"),
    _t("censuses", "economic-enterprises-census", N_("Economic Enterprises Census"), "enterprise census", "regjistrimi i ndërmarrjeve"),
    _t("labour-market-and-education", "education", N_("Education"), "students", "schools", "universities", "enrolment", "teachers", "arsimi", "nxënësit", "shkollat", "universitetet"),
    _t("labour-market-and-education", "employment-and-unemployment-from-lfs", N_("Employment and unemployment from LFS"),
       "labour force survey", "lfs", "unemployment", "employment", "jobs", "labour market", "participation", "papunësia", "punësimi", "forca e punës", "tregu i punës"),
    _t("environment-and-energy", "energy", N_("Energy"), "electricity", "gas", "oil", "fuel", "renewable", "energjia", "elektriciteti", "karburantet"),
    _t("environment-and-energy", "environment", N_("Environment"), "waste", "water", "air quality", "emissions", "mjedisi", "mbetjet", "uji"),
    _t("environment-and-energy", "environmental-accounts", N_("Environmental Accounts"), "environmental taxes", "material flows", "llogaritë mjedisore"),
    _t("economy-and-finance", "fiscal-statistics", N_("Fiscal Statistics"), "government finance", "budget", "debt", "taxes", "revenue", "buxheti", "borxhi", "taksat"),
    _t("agriculture-and-fishery", "fishery", N_("Fishery"), "fish", "aquaculture", "fishing", "peshkimi", "peshku"),
    _t("agriculture-and-fishery", "forests", N_("Forests"), "forestry", "timber", "wood", "pyjet", "pylltaria"),
    _t("demography-and-social-indicators", "gender-equality", N_("Gender equality"), "women and men", "gender gap", "gjinia", "barazia gjinore", "gratë dhe burrat"),
    _t("prices", "harmonized-index-of-consumer-price", N_("Harmonized Index Of Consumer Price"), "hicp", "harmonised", "inflation", "inflacioni", "ecoicop"),
    _t("social-condition", "health", N_("Health"), "hospitals", "doctors", "patients", "health care", "shëndetësia", "spitalet", "mjekët"),
    _t("social-condition", "household-budget-survey", N_("Household Budget Survey"), "household consumption", "expenditure", "hbs", "buxheti i familjes", "shpenzimet"),
    _t("prices", "import-price-index", N_("Import Price Index"), "import prices", "çmimet e importit"),
    _t("social-condition", "income-and-living-conditions-in-albania", N_("Income and Living Conditions in Albania"),
       "silc", "income", "living conditions", "deprivation", "të ardhurat", "kushtet e jetesës"),
    _t("prices", "index-of-producer-prices-for-agricultural-products", N_("Index of Producer Prices for Agricultural Products"),
       "farm prices", "agricultural prices", "çmimet e prodhuesit bujqësor"),
    _t("general-and-regional-statistics", "indicators-by-municipalities", N_("Indicators by Municipalities"), "municipalities", "local government", "bashkitë", "bashkia"),
    _t("industry-trade-and-services", "industrial-production-survey-prodcom", N_("Industrial Production Survey (PRODCOM)"), "manufacturing", "industrial output", "prodcom", "prodhimi industrial"),
    _t("science-technology-and-innovation", "information-and-communication-technologies", N_("Information and communication technologies"),
       "ict", "telecom", "internet", "broadband", "teknologjia e informacionit"),
    _t("social-condition", "information-and-communication-technologies-ict-usage-in-households-and-by-individuals",
       N_("ICT usage in households and by individuals"), "internet use", "computers", "mobile phones", "përdorimi i internetit"),
    _t("science-technology-and-innovation", "innovation-statistics", N_("Innovation Statistics"), "innovation", "inovacioni"),
    _t("international-trade", "international-trade-in-goods", N_("International Trade in Goods"),
       "exports", "imports", "foreign trade", "trade balance", "partner countries", "eksportet", "importet", "tregtia e jashtme", "bilanci tregtar"),
    _t("labour-market-and-education", "labour-costs", N_("Labour Costs"), "cost of labour", "hourly labour costs", "kostot e punës"),
    _t("labour-market-and-education", "lifelong-learning", N_("Lifelong Learning"), "adult education", "training", "mësimi gjatë gjithë jetës"),
    _t("agriculture-and-fishery", "livestock", N_("Livestock"), "cattle", "sheep", "milk", "meat", "blegtoria", "qumështi", "mishi"),
    _t("social-condition", "living-standard-measurement-survey-lsms", N_("Living Standard Measurement Survey (LSMS)"), "lsms", "living standards", "standardi i jetesës"),
    _t("demography-and-social-indicators", "migration-and-migrant-integration", N_("Migration and migrant integration"),
       "emigration", "immigration", "migrants", "citizenship", "migrimi", "emigrimi", "imigrimi"),
    _t("economy-and-finance", "national-accounts", N_("National Accounts"), "gdp", "gross domestic product", "value added", "growth", "economy", "pbb", "prodhimi i brendshëm bruto", "llogaritë kombëtare", "rritja ekonomike"),
    _t("demography-and-social-indicators", "population", N_("Population"), "inhabitants", "age structure", "life expectancy", "population by age", "popullsia", "jetëgjatësia", "banorët", "grupmosha"),
    _t("social-condition", "poverty", N_("Poverty"), "poor", "inequality", "gini", "varfëria", "pabarazia"),
    _t("prices", "producer-price-index", N_("Producer Price Index"), "ppi", "producer prices", "industrial prices", "çmimet e prodhuesit"),
    _t("demography-and-social-indicators", "projection", N_("Projection"), "population projections", "forecast", "parashikimi", "projeksionet"),
    _t("prices", "purchasing-power-parity", N_("Purchasing Power Parity"), "ppp", "price levels", "fuqia blerëse"),
    _t("economy-and-finance", "regional-accounts-in-albania", N_("Regional Accounts in Albania"), "regional gdp", "gdp by region", "llogaritë rajonale"),
    _t("general-and-regional-statistics", "regions", N_("Regions"), "prefectures", "counties", "regional statistics", "qarqet", "rajonet"),
    _t("science-technology-and-innovation", "research-and-development", N_("Research and development"), "r&d", "research", "kërkimi dhe zhvillimi"),
    _t("industry-trade-and-services", "retail-trade", N_("Retail Trade"), "retail", "shops", "turnover", "tregtia me pakicë", "tregtia"),
    _t("industry-trade-and-services", "short-term-statistics", N_("Short Term Statistics"), "monthly indicators", "industrial production index", "turnover index", "statistikat afatshkurtra"),
    _t("social-condition", "social-protection", N_("Social protection"), "pensions", "benefits", "social assistance", "pensionet", "ndihma ekonomike", "mbrojtja sociale"),
    _t("industry-trade-and-services", "statistics-on-the-demographic-events-of-enterprises", N_("Demographic events of enterprises"),
       "enterprise births", "enterprise deaths", "business demography", "demografia e ndërmarrjeve"),
    _t("industry-trade-and-services", "structural-business-statistics", N_("Structural Business Statistics"), "sbs", "business economy", "enterprise statistics", "statistikat strukturore"),
    _t("labour-market-and-education", "structure-of-earnings-survey", N_("Structure of Earnings Survey"), "earnings", "pay structure", "struktura e pagave"),
    _t("economy-and-finance", "supply-use-and-input-output-tables", N_("Supply, Use and Input-Output Tables"), "input output", "supply and use", "tabelat input-output"),
    _t("social-condition", "survey-on-tourism-holiday-and-trips", N_("Survey on Tourism Holiday and Trips"), "trips", "holidays", "domestic tourism", "udhëtimet", "pushimet"),
    _t("social-condition", "time-use-survey", N_("Time Use Survey"), "time use", "unpaid work", "koha e përdorur"),
    _t("industry-trade-and-services", "tourism-statistics", N_("Tourism Statistics"), "tourism", "tourists", "visitors", "arrivals", "hotels", "accommodation", "nights", "turizmi", "turistët", "ardhjet", "hotelet", "akomodimi"),
    _t("industry-trade-and-services", "transport-accidents-and-characteristics-of-road-vehicles", N_("Transport, Accidents and Road Vehicles"),
       "transport", "vehicles", "road accidents", "cars", "passengers", "transporti", "aksidentet", "automjetet"),
    _t("labour-market-and-education", "wages", N_("Wages"), "salary", "pay", "earnings", "minimum wage", "gender pay gap", "paga", "pagat", "paga minimale", "hendeku gjinor", "rroga", "rrogat", "rroga minimale"),
]

# The pages most people are after; they win ties against narrower look-alikes (for example the LFS over
# administrative labour-market data when someone types just "employment").
POPULAR = frozenset({
    "labour-market-and-education/employment-and-unemployment-from-lfs", "prices/consumer-price-index",
    "economy-and-finance/national-accounts", "demography-and-social-indicators/population",
    "international-trade/international-trade-in-goods", "industry-trade-and-services/tourism-statistics",
    "labour-market-and-education/wages", "censuses/census-of-population-and-housing",
})

BY_KEY = {t.key: t for t in TOPICS}
BY_URL = {t.url: t for t in TOPICS}


def topics_in_theme(theme: str) -> list[Topic]:
    return [t for t in TOPICS if t.theme == theme]


def topic_for_url(url: str) -> Topic | None:
    """Match an INSTAT page URL (English or trailing-slash variants) to a known sub-topic."""
    u = url.split("#")[0].split("?")[0]
    if not u.endswith("/"):
        u += "/"
    return BY_URL.get(u.replace("http://", "https://").replace("://instat.gov.al", "://www.instat.gov.al"))
