from datetime import datetime, timedelta, timezone
from editorial import classify_tier, editorial_score, classify_category, institutional_why

def item(title, hours=1, source="Reuters", importance=5):
    return {"title":title,"summary":"","source":source,"importance":importance,
            "published_at":(datetime.now(timezone.utc)-timedelta(hours=hours)).isoformat()}

assert classify_tier(item("Company reports earnings and raises guidance")) == 1
assert classify_tier(item("Bank trims stake in Visa")) == 2 or classify_tier(item("Bank trims stake in Visa")) == 3
assert classify_tier(item("Visa price target raised")) == 3
assert classify_category(item("BOJ may ramp up bond-buying as yields rise")) == "Rates & Central Banks"
assert editorial_score(item("Iran war intensifies", 1), {"Reuters":10}, "world") > editorial_score(item("Local politician gives interview", 1), {"Reuters":10}, "world")
assert editorial_score(item("Fresh earnings", 2), {"Reuters":10}, "companies") > editorial_score(item("Old earnings", 60), {"Reuters":10}, "companies")
assert "sentiment" in institutional_why(item("Visa price target raised")).lower()
print("editorial tests: PASS")
