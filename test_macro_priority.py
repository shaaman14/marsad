import os, tempfile
os.environ['DATA_DIR'] = tempfile.mkdtemp(prefix='marsad-macro-')
from brew import market_story_score, dynamic_market_topic
from pathlib import Path
import json
cfg=json.loads((Path(__file__).parent/'config.json').read_text())

def item(title, source='Reuters', importance=10):
    return {'title':title,'summary':'','source':source,'importance':importance,'published_at':None,'section':'markets'}

fomc=item('FOMC keeps rates unchanged as Powell signals data-dependent path')
au=item('Australia CPI inflation slows more than expected, reshaping RBA bets')
minor=item('Company shares rise after routine broker commentary')
assert market_story_score(fomc,cfg) > market_story_score(minor,cfg)+80
assert market_story_score(au,cfg) > market_story_score(minor,cfg)+60
assert dynamic_market_topic(au) == 'Rates & Central Banks' or dynamic_market_topic(au) == 'Economy'
print('macro priority tests passed')
