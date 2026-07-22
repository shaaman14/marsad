import asyncio
import os
import tempfile
from pathlib import Path

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="marsad-test-")

from database import get_company_snapshot, initialise
from sources import fetch_company_snapshot
from brew import company_price_line


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "chart": {
                "result": [{
                    "meta": {
                        "currency": "USD",
                        "fullExchangeName": "NasdaqGS",
                        "regularMarketPrice": 214.36,
                        "chartPreviousClose": 190.00,
                        "previousClose": 209.52,
                        "regularMarketChangePercent": 2.31,
                        "regularMarketTime": 1784260800,
                    },
                    "timestamp": [1784174400, 1784260800],
                    "indicators": {"quote": [{"close": [209.52, 214.36]}]},
                }]
            }
        }


class FakeClient:
    async def get(self, *args, **kwargs):
        return FakeResponse()


async def main():
    initialise()
    config = {"company_market_data": {"NVIDIA": {"symbol": "NVDA", "currency": "USD", "exchange": "Nasdaq"}}}
    rows = await fetch_company_snapshot(config, FakeClient())
    assert len(rows) == 1
    stored = get_company_snapshot("NVIDIA")
    assert stored["symbol"] == "NVDA"
    assert round(stored["value"], 2) == 214.36
    rendered = company_price_line("NVIDIA")
    assert "NVDA" in rendered
    assert "$214.36" in rendered
    assert "🟢" in rendered
    assert "▲ 2.31%" in rendered
    print("company price tests passed")


if __name__ == "__main__":
    asyncio.run(main())
