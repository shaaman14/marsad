from datetime import datetime, timezone
import re

TIER_1 = {
    "default", "bankruptcy", "restructuring", "downgrade", "upgrade",
    "earnings", "guidance", "merger", "acquisition", "takeover",
    "capital raise", "bond issuance", "refinancing", "regulatory",
    "investigation", "lawsuit", "war", "missile", "sanction",
    "tariff", "rate hike", "rate cut", "inflation", "gdp", "earthquake"
}
TIER_2 = {
    "partnership", "contract", "launch", "product", "strategy",
    "ceo", "cfo", "management", "investment", "stake"
}
TIER_3 = {
    "analyst", "price target", "undervalued", "overvalued", "fair value",
    "beat estimates", "stock rating", "fund holdings", "trims stake",
    "raises target", "lowers target"
}

CATEGORY_RULES = [
    ("Rates & Central Banks", ["fed", "federal reserve", "ecb", "boj", "bank of japan", "pboc", "rate cut", "rate hike", "yield", "bond-buying"]),
    ("Credit", ["default", "bankruptcy", "restructuring", "bond issuance", "refinancing", "downgrade", "upgrade", "rating"]),
    ("Macro", ["gdp", "inflation", "jobs", "employment", "pmi", "retail sales", "consumer confidence"]),
    ("FX", ["dollar", "yen", "yuan", "euro", "currency", "forex", "fx"]),
    ("Commodities", ["oil", "gold", "copper", "uranium", "commodity"]),
    ("Equities", ["earnings", "guidance", "shares", "stocks", "nasdaq", "s&p"]),
    ("Geopolitics", ["war", "missile", "strike", "sanction", "tariff", "ceasefire", "election"]),
]

def text(item):
    return " ".join(str(item.get(k) or "") for k in ("title", "summary", "source")).lower()

def age_hours(item, now=None):
    raw=item.get("published_at")
    if not raw: return 999.0
    try:
        dt=datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
        now=now or datetime.now(timezone.utc)
        return max(0.0, (now-dt.astimezone(timezone.utc)).total_seconds()/3600)
    except Exception:
        return 999.0

def classify_tier(item):
    t=text(item)
    if any(x in t for x in TIER_1): return 1
    if any(x in t for x in TIER_2): return 2
    if any(x in t for x in TIER_3): return 3
    return 2

def classify_category(item):
    t=text(item)
    for label, terms in CATEGORY_RULES:
        if any(term in t for term in terms): return label
    return None

def freshness_adjustment(item):
    h=age_hours(item)
    if h <= 3: return 10
    if h <= 8: return 7
    if h <= 16: return 4
    if h <= 24: return 1
    if h <= 36: return -5
    if h <= 48: return -12
    return -25

def editorial_score(item, source_quality=None, section="general"):
    source_quality=source_quality or {}
    score=int(item.get("importance", 0))
    score += int(source_quality.get(item.get("source") or "", 0))
    score += freshness_adjustment(item)
    tier=classify_tier(item)
    score += {1:18, 2:6, 3:-8}[tier]
    t=text(item)
    if section == "world":
        for term, weight in {"war":14,"missile":12,"earthquake":12,"sanction":10,"tariff":9,"election":7}.items():
            if term in t: score += weight
        for term in ("interview", "approval rating", "celebrity", "viral"):
            if term in t: score -= 18
    return score

def institutional_why(item):
    category=classify_category(item)
    tier=classify_tier(item)
    if tier == 3:
        return "Market sentiment or positioning signal; no direct change to fundamentals."
    mapping={
        "Credit":"May affect refinancing capacity, leverage, spreads or recovery value.",
        "Rates & Central Banks":"Can shift yields, currencies and asset valuations.",
        "Macro":"Can change growth expectations and the likely policy path.",
        "FX":"Affects imported inflation, earnings translation and cross-border returns.",
        "Commodities":"Feeds into inflation, trade balances and producer earnings.",
        "Equities":"May alter earnings expectations, valuation or sector leadership.",
        "Geopolitics":"Can affect energy, shipping, inflation and broad risk sentiment.",
    }
    return mapping.get(category, "May affect company fundamentals or investor positioning.")
