"""Evidence-only 20-SKU pilot: never writes product price fields."""
import json, os, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus
import requests
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'scratch_price_research'/'price_text_pilot_20.json'
PROMPT = """浣犳槸浠锋牸璇佹嵁瀹℃牳鍛樸€備粎浠庤緭鍏ユ悳绱㈢墖娈垫彁鍙栦腑鍥藉ぇ闄嗙殑瀹樻柟寤鸿闆跺敭浠锋垨棣栧彂瀹樻柟瀹氫环銆備弗鏍兼帓闄ゆ垚浜や环銆佷紭鎯犱环銆佽ˉ璐翠环銆佸埜鍚庝环銆侀鍞环銆佹捣澶栦环鏍煎拰鍨嬪彿涓嶅尮閰嶇殑浠锋牸銆傛病鏈夊彲闈犺瘉鎹垯 price_cny 蹇呴』涓?null銆傚彧杈撳嚭 JSON锛歿\"price_cny\": number|null, \"price_type\": \"瀹樻柟寤鸿闆跺敭浠穃"|\"棣栧彂瀹樻柟瀹氫环\"|\"鏃犲彲闈犵粨鏋淺", \"evidence_index\": number|null, \"evidence_quote\": string, \"confidence\": 0-1, \"reason\": string}銆?""
def products():
    out=[]
    for p in sorted((ROOT/'data/products').glob('*.json')):
        if p.name=='index.json': continue
        try: x=json.loads(p.read_text(encoding='utf-8'))
        except: continue
        s=x.get('cost_snapshot') or {}
        if s.get('price_cny') is None and x.get('brand') and x.get('model') and not x['canonical_id'].startswith('unknown--') and len(x['model'])<=48:
            out.append({'sku':x['canonical_id'],'brand':x['brand'],'model':x['model']})
    return out[:20]
def search(x):
    q=f"{x['brand']} {x['model']} 棣栧彂浠?鍞环"
    r=requests.get('https://www.bing.com/search?q='+quote_plus(q),headers={'User-Agent':'Mozilla/5.0'},timeout=20);r.raise_for_status()
    soup=BeautifulSoup(r.text,'html.parser');out=[]
    for e in soup.select('li.b_algo')[:6]:
        a=e.select_one('h2 a'); p=e.select_one('.b_caption p') or e.select_one('p')
        if a and p: out.append({'title':a.get_text(' ',strip=True),'url':a.get('href',''),'snippet':p.get_text(' ',strip=True)})
    return out
def extract(key,x,hits):
    r=requests.post('https://api.deepseek.com/chat/completions',headers={'Authorization':f'Bearer {key}','Content-Type':'application/json'},json={'model':'deepseek-v4-flash','thinking':{'type':'disabled'},'temperature':0,'max_tokens':300,'response_format':{'type':'json_object'},'messages':[{'role':'system','content':PROMPT},{'role':'user','content':json.dumps({'product':x,'search_evidence':hits},ensure_ascii=False)}]},timeout=45);r.raise_for_status()
    z=json.loads(r.json()['choices'][0]['message']['content']); i=z.get('evidence_index')
    if not isinstance(i,int) or not 0<=i<len(hits) or z.get('price_cny') is None: z.update({'price_cny':None,'price_type':'鏃犲彲闈犵粨鏋?,'confidence':0,'evidence_url':''})
    else:z['evidence_url']=hits[i]['url']
    return z
def main():
    key=os.environ['DEEPSEEK_API_KEY']; rows=[]
    for x in products():
        try:
            h=search(x); z=extract(key,x,h) if h else {'price_cny':None,'price_type':'鏃犲彲闈犵粨鏋?,'confidence':0,'reason':'no web evidence','evidence_url':''}
        except Exception as e:h=[];z={'price_cny':None,'price_type':'鏃犲彲闈犵粨鏋?,'confidence':0,'reason':str(e),'evidence_url':''}
        rows.append({**x,'query_time':datetime.now(timezone.utc).isoformat(),'search_evidence':h,'extraction':z});time.sleep(.4)
    OUT.parent.mkdir(exist_ok=True);OUT.write_text(json.dumps({'generated_at':datetime.now(timezone.utc).isoformat(),'model':'deepseek-v4-flash','scope':'evidence-only; no price_cny overwritten','records':rows},ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':main()
