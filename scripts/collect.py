#!/usr/bin/env python3
"""Collect public prudential publication metadata; no automated legal conclusions."""
import json, re, html, hashlib, urllib.request, urllib.parse, datetime, pathlib, email.utils, xml.etree.ElementTree as ET
ROOT=pathlib.Path(__file__).resolve().parents[1]
SOURCES=[
("EBA consultations","EBA","Regulatory pipeline","https://www.eba.europa.eu/publications-and-media/consultations","html"),
("EBA publications","EBA","Risk outlook","https://www.eba.europa.eu/publications-and-media/publications","html"),
("ECB supervision","ECB / SSM","Supervisory signals","https://www.bankingsupervision.europa.eu/home/html/index.en.html","html"),
("ECB newsletter","ECB / SSM","Supervisory signals","https://www.bankingsupervision.europa.eu/press/supervisory-newsletters/newsletter/html/index.en.html","html"),
("ECB sanctions","ECB / SSM","Enforcement","https://www.bankingsupervision.europa.eu/activities/sanctions/supervisory-sanctions/html/index.en.html","html"),
("FMA news","FMA","Regulatory pipeline","https://www.fma.gv.at/en/category/news-en/feed/","rss"),
("OeNB press","OeNB","Risk outlook","https://www.oenb.at/news-und-events/presse.html","html")]
FILTER=re.compile(r"\b(bank|banking|prudential|supervisory|srep|crr|crd|credit|capital|liquidity|risk|governance|regulatory|reporting|financial stability|finanzstabilität|banken|kredit|eigenmittel|aufsicht|risiko|meldewesen|liquidität)\b",re.I)
EXCLUDE=re.compile(r"\b(dora|insurance|pension|crypto|fraudulent|scam|payment services|investment firms|dgs payouts|credit servicers|micar|esma)\b",re.I)
LINK=re.compile(r'<a\b[^>]*\bhref=["\x27]([^"\x27]+)["\x27][^>]*>(.*?)</a>',re.I|re.S)
TAGS=re.compile(r'<[^>]+>')
def clean(s):return re.sub(r'\s+',' ',html.unescape(TAGS.sub(' ',s))).strip()
def topic(s):
 s=s.lower()
 for keys,name in [(('capital','own funds','crr','eigenmittel'),'Capital & CRR3'),(('liquidity','lcr','nsfr','liquidität'),'Liquidity'),(('credit','npl','kredit'),'Credit risk'),(('reporting','corep','meldewesen'),'Regulatory reporting'),(('operational risk',),'Operational risk')]:
  if any(k in s for k in keys):return name
 return 'Governance & SREP'
def relevant(name,title,url):
 """Require a publication-style document link, not institutional navigation."""
 if not FILTER.search(title) or EXCLUDE.search(title):return False
 path=urllib.parse.urlsplit(url).path.lower()
 if name=="EBA consultations":
  return path.startswith("/publications-and-media/events/consultation")
 if name=="EBA publications":
  return path.startswith("/publications-and-media/publications/") or path.startswith("/risk-and-data-analysis/risk-analysis/risk-monitoring/")
 if name=="ECB supervision":
  return bool(re.search(r"/press/(?:pr|speeches)/date/20\d{2}/|/press/blog/20\d{2}/|/activities/srep/20\d{2}/|/framework/priorities/html/ssm[.]supervisory_priorities",path))
 if name=="ECB newsletter":
  return "/press/supervisory-newsletters/newsletter/" in path and path.endswith(".en.html")
 if name=="ECB sanctions":
  return "/activities/sanctions/supervisory-sanctions/" in path and path.endswith(".en.html")
 if name=="FMA news":
  return bool(re.search(r"\b(banking|banks|credit institutions|capital requirements|crr|crd|bwg|srep|prudential)\b",title,re.I))
 if name=="OeNB press":
  return path.startswith("/news-und-events/presse/") and bool(FILTER.search(title))
 return False
def scan(source):
 name,authority,track,base,kind=source
 req=urllib.request.Request(base,headers={"User-Agent":"PrudentialRadarResearch/0.3 (weekly metadata-only)","Accept":"text/html, application/rss+xml, application/xml"})
 with urllib.request.urlopen(req,timeout=22) as r:
  blob=r.read(3000000)
 items=[]
 if kind=="rss":
  root=ET.fromstring(blob)
  for x in root.findall('.//item'):
   items.append((x.findtext('title') or '', x.findtext('link') or '',x.findtext('pubDate') or ''))
 else:
  page=blob.decode('utf-8','replace')
  for href,title in LINK.findall(page):
   items.append((clean(title),urllib.parse.urljoin(base,html.unescape(href)),''))
 found={}
 for title,url,published in items:
  if len(title)<23 or len(title)>320 or not relevant(name,title,url):continue
  parsed=urllib.parse.urlsplit(url)
  if parsed.scheme!='https' or not any((parsed.hostname or '')==h or (parsed.hostname or '').endswith('.'+h) for h in ('eba.europa.eu','bankingsupervision.europa.eu','fma.gv.at','oenb.at')):continue
  url=urllib.parse.urlunsplit((parsed.scheme,parsed.netloc,parsed.path.rstrip('/'),'', ''))
  if not url or url==base.rstrip('/') or url.endswith(('.pdf','.zip','.xlsx')):continue
  id='AUTO-'+hashlib.sha256(url.encode()).hexdigest()[:12].upper()
  pubdate=""
  if published:
   try:pubdate=email.utils.parsedate_to_datetime(published).date().isoformat()
   except (ValueError,TypeError,IndexError):pass
  found[url]={"id":id,"title":title,"source":authority,"track":track,"area":topic(title),"url":url,"published":pubdate,"discovered_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),"review_state":"Unverified candidate · check consultation lifecycle (not confirmed open)","legal_status":"Not assessed — requires analyst review","impact":None,"readiness":None,"urgency":None,"assessment_status":"Unassessed — may be closed or superseded","source_feed":name,"summary":""}
  if len(found)>=45:break
 return list(found.values())
def main():
 base=ROOT/'data';base.mkdir(exist_ok=True)
 queuefile=base/'discovered.json';statusfile=base/'status.json'
 previous=json.loads(queuefile.read_text()) if queuefile.exists() else []
 by_url={d['url']:d for d in previous if relevant(d.get('source_feed',''),d.get('title',''),d.get('url','')) and not ('srep guidelines' in d.get('title','').lower() and 'consultation' in d.get('title','').lower())}
 now=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
 statuses={};successful=0;added=0
 for s in SOURCES:
  try:
   docs=scan(s);successful+=1;fresh=0
   for d in docs:
    if d['url'] not in by_url:by_url[d['url']]=d;fresh+=1;added+=1
   statuses[s[0]]={"state":"ok" if docs else "no_matches","checked_utc":now,"matching_items":len(docs),"new_items":fresh,"url":s[3]}
   print("OK",s[0],len(docs),fresh)
  except Exception as e:
   statuses[s[0]]={"state":"error","checked_utc":now,"error":str(e)[:200],"url":s[3]}
   print("ERROR",s[0],str(e)[:200])
 old=json.loads(statusfile.read_text()) if statusfile.exists() else {}
 status={"last_run_utc":now,"last_success_utc":now if successful else old.get("last_success_utc"),"sources":statuses,"new_items_last_run":added,"total_discovered":len(by_url),"note":f"{successful}/{len(SOURCES)} sources checked; discovered items remain unassessed."}
 statusfile.write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n')
 if not successful:raise RuntimeError('All source checks failed; no successful refresh')
 queuefile.write_text(json.dumps(list(by_url.values()),ensure_ascii=False,indent=2)+'\n')
 page=ROOT/'docs'/'index.html'
 content=page.read_text()
 pattern=r'const PAYLOAD=(.*?);</script>'
 m=re.search(pattern,content,re.S)
 if not m:raise RuntimeError('Dashboard payload marker missing')
 payload=json.loads(m.group(1))
 payload['discovered']=list(by_url.values());payload['status']=status
 # The verified editorial register is maintained separately: discovery never promotes a proposal to active law.
 intelligence_file=base/'intelligence.json'
 if intelligence_file.exists():
  payload['intelligence_last_editorial_review']=json.loads(intelligence_file.read_text()).get('editorial_as_of')
 new=json.dumps(payload,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c').replace('>','\\u003e')
 content=re.sub(pattern,lambda _: 'const PAYLOAD='+new+';</script>',content,count=1,flags=re.S)
 page.write_text(content)
 print('Updated',added,'documents; total',len(by_url))
if __name__=='__main__':main()
