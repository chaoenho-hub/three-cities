"""Fetch candidate site photos from Wikipedia/Wikimedia Commons with license metadata.
Runs on GitHub Actions; results are committed to the `photo-candidates` branch."""
import json, os, re, urllib.parse, urllib.request
UA = {'User-Agent': 'three-cities-field-notes/1.0 (https://github.com/chaoenho-hub/three-cities)'}
def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
        return r.read()
def js(url): return json.loads(get(url))
SITES = {
 'van': {'wp': [], 'q': [], 'cat': ['Category:Le Voyage à Nantes', 'Category:Ligne verte (Nantes)', 'Category:Le Voyage à Nantes 2019']},
 'lieux': {'wp': [], 'q': ['Cité des arts de la rue', 'Lieux publics Cité des arts'], 'cat': ['Category:Cité des arts de la rue', 'Category:Lieux publics']},
 'brtf': {'wp': [], 'q': ['Bureau de représentation de Taipei en France', 'Taipei Representative Office France'], 'cat': []},
}
def pageimage(lang, title):
    u = f'https://{lang}.wikipedia.org/w/api.php?' + urllib.parse.urlencode({'action':'query','prop':'pageimages','piprop':'name','titles':title,'redirects':1,'format':'json'})
    for p in js(u).get('query',{}).get('pages',{}).values():
        if p.get('pageimage'): return p['pageimage']
def search(q, n=4):
    u = 'https://commons.wikimedia.org/w/api.php?' + urllib.parse.urlencode({'action':'query','list':'search','srnamespace':6,'srsearch':q+' filetype:bitmap','srlimit':n,'format':'json'})
    return [h['title'][5:] for h in js(u).get('query',{}).get('search',[])]
def catmembers(c, n=6):
    u = 'https://commons.wikimedia.org/w/api.php?' + urllib.parse.urlencode({'action':'query','list':'categorymembers','cmtitle':c,'cmtype':'file','cmlimit':n,'format':'json'})
    return [h['title'][5:] for h in js(u).get('query',{}).get('categorymembers',[])]
def info(name):
    u = 'https://commons.wikimedia.org/w/api.php?' + urllib.parse.urlencode({'action':'query','titles':'File:'+name,'prop':'imageinfo','iiprop':'url|extmetadata|mime|size','iiurlwidth':1000,'format':'json'})
    for p in js(u).get('query',{}).get('pages',{}).values():
        ii = (p.get('imageinfo') or [None])[0]
        if ii: return ii
def strip(h): return re.sub(r'\s+',' ',re.sub(r'<[^>]+>','',h or '')).strip()
os.makedirs('cand', exist_ok=True)
meta = {}
for sid, cfg in SITES.items():
    names = []
    for lang, t in cfg['wp']:
        try:
            n = pageimage(lang, t)
            if n and n not in names: names.append(n)
        except Exception as e: print('wp fail', sid, t, e)
    for q in cfg['q']:
        try:
            for n in search(q):
                if n not in names: names.append(n)
        except Exception as e: print('search fail', sid, q, e)
    for c in cfg.get('cat', []):
        try:
            for n in catmembers(c):
                if n not in names: names.append(n)
        except Exception as e: print('cat fail', sid, c, e)
    meta[sid] = []
    for i, n in enumerate(names[:10]):
        try:
            ii = info(n)
            if not ii or ii.get('mime') not in ('image/jpeg','image/png','image/webp'): continue
            em = ii.get('extmetadata', {})
            ext = {'image/jpeg':'jpg','image/png':'png','image/webp':'webp'}[ii['mime']]
            fn = f'{sid}_{i}.{ext}'
            open('cand/'+fn,'wb').write(get(ii['thumburl']))
            meta[sid].append({'file': fn, 'name': n, 'page': ii.get('descriptionurl'),
                'artist': strip(em.get('Artist',{}).get('value')), 'license': strip(em.get('LicenseShortName',{}).get('value')),
                'licenseUrl': strip(em.get('LicenseUrl',{}).get('value')), 'desc': strip(em.get('ImageDescription',{}).get('value'))[:300]})
            print('ok', sid, n)
        except Exception as e: print('img fail', sid, n, e)
json.dump(meta, open('cand/meta.json','w'), ensure_ascii=False, indent=1)
