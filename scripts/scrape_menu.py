#!/usr/bin/env python3
"""Optional convenience fetcher for a business's PUBLIC official product/menu page.

Usage: python3 scripts/scrape_menu.py 'https://business.example/menu'
Outputs a dated readable HTML-text snapshot plus *draft* CSV suggestions only
when a page contains explicit schema.org Product/Offer JSON-LD. Nothing scraped
is marked verified and no bulk crawling/robots bypass is implemented.
"""
import argparse,csv,json,re,sys
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

parser=argparse.ArgumentParser(description='Read a public official business webpage, then manually verify extracted data.')
parser.add_argument('url',help='Official HTTPS product/menu page you are permitted to retrieve')
parser.add_argument('--business-id',default='new_business')
parser.add_argument('--business-name',default='Business Name')
args=parser.parse_args()
url=urlparse(args.url)
if url.scheme!='https' or not url.hostname:sys.exit('Provide a public HTTPS URL of the business official website.')
response=requests.get(args.url,timeout=20,headers={'User-Agent':'ProofFlowerHackathonResearch/0.2'})
response.raise_for_status()
if len(response.content)>3_000_000:sys.exit('Page too large for this lightweight extractor.')
soup=BeautifulSoup(response.text,'html.parser')
# Save raw structured data BEFORE removing <script> nodes.
items=[]
def dig(d):
    if isinstance(d,list):
        for x in d:dig(x)
    elif isinstance(d,dict):
        if '@graph' in d:dig(d['@graph'])
        typ=d.get('@type',[])
        if isinstance(typ,str):typ=[typ]
        if 'Product' in typ:items.append(d)
        if 'itemListElement' in d:dig(d['itemListElement'])
        if 'item' in d:dig(d['item'])
for tag in soup.select('script[type="application/ld+json"]'):
    try:dig(json.loads(tag.string or tag.get_text() or '{}'))
    except json.JSONDecodeError:pass
for element in soup(['script','style','nav','footer']):element.decompose()
text='\n'.join(soup.stripped_strings)
day=datetime.now(timezone.utc).date().isoformat()
out=Path('data/snapshots');out.mkdir(parents=True,exist_ok=True)
slug=re.sub(r'[^a-z0-9]+','_',args.business_id.lower()).strip('_')
(out/f'{slug}_{day}_page.txt').write_text(f'SOURCE: {args.url}\nFETCHED: {day}\n\n{text[:100000]}',encoding='utf-8')
# The candidate CSV uses the SAME HEADERS expected by the application.
cols=['fact_id','business_id','business_name','product_id','product_name','field','value','context','source_url','checked_at','approved','is_demo']
proposals=[]
for i,item in enumerate(items,1):
    name=item.get('name')
    if not isinstance(name,str) or not name.strip():continue
    pid=re.sub(r'[^a-z0-9]+','_',name.lower()).strip('_')
    offers=item.get('offers',[])
    offers=offers if isinstance(offers,list) else [offers]
    for offer in offers:
        if not isinstance(offer,dict):continue
        price=offer.get('price')
        if price is not None and str(offer.get('priceCurrency','USD')).upper()=='USD':
            proposals.append([f'DRAFT_{i}_PRICE',args.business_id,args.business_name,pid,name,'price_usd',
                str(price),'',args.url,day,'no','no'])
        availability=offer.get('availability','')
        if isinstance(availability,str) and availability:
            v='available' if availability.rsplit('/',1)[-1]=='InStock' else \
                'unavailable' if availability.rsplit('/',1)[-1]=='OutOfStock' else ''
            if v:proposals.append([f'DRAFT_{i}_AVAIL',args.business_id,args.business_name,pid,name,
                                  'availability',v,'',args.url,day,'no','no'])
if proposals:
    file=out/f'{slug}_{day}_DRAFT.csv'
    with file.open('w',newline='',encoding='utf-8') as f:
        writer=csv.writer(f);writer.writerow(cols);writer.writerows(proposals)
    print(f'Candidate CSV (UNVERIFIED): {file}')
else:print('No Product JSON-LD found. Copy only verified facts from the saved page text into the CSV template.')
print(f'Saved webpage text: {out / (slug+"_"+day+"_page.txt")}')
