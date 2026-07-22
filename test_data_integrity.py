import asyncio
import os
import tempfile

os.environ['DATA_DIR'] = tempfile.mkdtemp(prefix='marsad-integrity-')

from database import get_company_snapshot, initialise
from sources import fetch_company_snapshot
from brew import company_price_line, dynamic_market_topic


class FakeResponse:
    def __init__(self, payload): self.payload = payload
    def raise_for_status(self): return None
    def json(self): return self.payload


class FakeClient:
    def __init__(self, payload): self.payload = payload
    async def get(self, *args, **kwargs): return FakeResponse(self.payload)


def payload(*, reported=None, stale=False):
    # chartPreviousClose is deliberately wrong (multi-day baseline). The code
    # must use the immediately preceding valid session close of 100 instead.
    import time
    now = int(time.time()) - (120 * 3600 if stale else 0)
    meta = {
        'currency': 'USD',
        'fullExchangeName': 'NasdaqGS',
        'regularMarketPrice': 102.0,
        'chartPreviousClose': 90.0,
        'previousClose': 100.0,
        'regularMarketTime': now,
    }
    if reported is not None:
        meta['regularMarketChangePercent'] = reported
    return {'chart': {'result': [{
        'meta': meta,
        'timestamp': [now - 86400, now],
        'indicators': {'quote': [{'close': [100.0, 102.0]}]},
    }], 'error': None}}


async def main():
    initialise()
    cfg = {
        'company_market_data': {
            'NVIDIA': {'symbol': 'NVDA', 'currency': 'USD', 'exchange': 'Nasdaq'}
        },
        'data_integrity': {
            'company_quote_max_age_hours': 96,
            'abnormal_move_pct': 15,
            'move_validation_tolerance_pct': 0.35,
        },
    }

    rows = await fetch_company_snapshot(cfg, FakeClient(payload(reported=2.0)))
    assert len(rows) == 1
    row = get_company_snapshot('NVIDIA')
    assert row['validation_status'] == 'verified'
    assert row['previous_close'] == 100.0
    assert round(row['change_pct'], 2) == 2.00, row
    rendered = company_price_line('NVIDIA')
    assert 'Verified' in rendered and '▲ 2.00%' in rendered

    # Inconsistent vendor-reported percentage must be suppressed.
    bad_cfg = {**cfg, 'company_market_data': {'Reddit': {'symbol':'RDDT','currency':'USD','exchange':'Nasdaq'}}}
    bad = await fetch_company_snapshot(bad_cfg, FakeClient(payload(reported=7.0)))
    assert bad == []

    # Stale quote must be suppressed.
    stale = await fetch_company_snapshot(bad_cfg, FakeClient(payload(reported=2.0, stale=True)))
    assert stale == []

    assert dynamic_market_topic({'title':'EQT raises Kakaku.com offer price, topping rival bid','summary':'','source':'','section':'markets'}) == 'M&A'
    assert dynamic_market_topic({'title':'Seven & i shares jump on Zabka stake talks','summary':'','source':'','section':'markets'}) == 'M&A'
    print('data integrity tests passed')


if __name__ == '__main__':
    asyncio.run(main())
