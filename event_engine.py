import re
from collections import defaultdict

HIGH={'reuters':100,'bloomberg':95,'financial times':92,'wall street journal':92,'wsj':92,'cnbc':88,'nikkei':88,'ap':86,'bbc':82}
LOW=['bitcoin world','cointelegraph','decrypt']
EVENTS=[('FOMC',['fomc','federal reserve','fed decision','powell']),('US CPI',['cpi','inflation']),('Payrolls',['nonfarm','payroll']),('RBA',['reserve bank of australia','rba']),('Australia CPI',['australia cpi','australian inflation']),('ECB',['ecb','european central bank']),('BOJ',['bank of japan','boj']),('M&A',['acquire','acquisition','merger','buyout'])]

def detect_event(item):
 t=(item.get('title','')+' '+item.get('summary','')).lower()
 for n,keys in EVENTS:
  if any(k in t for k in keys): return n
 w=re.findall(r'[a-z]{4,}',t)
 return ' '.join(w[:3]) or 'Other'

def source_weight(src):
 s=(src or '').lower()
 for k,v in HIGH.items():
  if k in s:return v
 if any(x in s for x in LOW): return -50
 return 20

def cluster(items):
 d=defaultdict(list)
 for i in items:d[detect_event(i)].append(i)
 out=[]
 for ev,arts in d.items():
  arts=sorted(arts,key=lambda x:x.get('importance',0)+source_weight(x.get('source','')),reverse=True)
  lead=arts[0].copy();lead['cluster']=arts;lead['event']=ev;lead['sources']=sorted({a.get('source','') for a in arts});lead['importance']=max(a.get('importance',0) for a in arts)+len(arts)*5
  out.append(lead)
 return sorted(out,key=lambda x:x['importance'],reverse=True)
