"""Fetch candidate site photos from Wikipedia/Wikimedia Commons with license metadata.
Runs on GitHub Actions; results are committed to the `photo-candidates` branch."""
import json, os, re, urllib.parse, urllib.request
UA = {'User-Agent': 'three-cities-field-notes/1.0 (https://github.com/chaoenho-hub/three-cities)'}
def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
        return r.read()
def js(url): return json.loads(get(url))
SITES = {
 'brtf': {'wp': [], 'q': ['Esplanade des Invalides', 'Rue de Constantine Paris']},
 '104': {'wp': [('fr','Le Centquatre-Paris'), ('en','Le Centquatre-Paris')], 'q': ['Centquatre Paris']},
 'tokyo': {'wp': [('fr','Palais de Tokyo'), ('en','Palais de Tokyo')], 'q': ['Palais de Tokyo Paris facade']},
 'gpe': {'wp': [('fr','Gare de Saint-Denis Pleyel'), ('en','Saint-Denis Pleyel station')], 'q': ['Gare Saint-Denis Pleyel', 'Grand Paris Express gare']},
 'cartoucherie': {'wp': [('fr','Cartoucherie (Paris)'), ('fr','Cartoucherie de Vincennes')], 'q': ['Cartoucherie de Vincennes']},
 'nourry': {'wp': [], 'q': ['Prune Nourry Terracotta Daughters', 'Prune Nourry sculpture']},
 'pompidou': {'wp': [('fr','Centre Pompidou'), ('en','Centre Pompidou')], 'q': ['Centre Pompidou facade']},
 'walk': {'wp': [], 'q': ['Canal Saint-Denis', 'Plaine Saint-Denis']},
 'nuit': {'wp': [('fr','Nuit Blanche (Paris)'), ('en','Nuit Blanche')], 'q': ['Nuit Blanche Paris installation']},
 'orsay': {'wp': [('fr',"Musée d'Orsay"), ('en',"Musée d'Orsay")], 'q': ["Musée d'Orsay nef"]},
 'lu': {'wp': [('fr','Le Lieu unique'), ('en','Le Lieu unique')], 'q': ['Lieu unique Nantes tour LU']},
 'samoa': {'wp': [('fr','Île de Nantes'), ('en','Île de Nantes')], 'q': ['Île de Nantes Hangar à bananes']},
 'machines': {'wp': [('fr',"Les Machines de l'île"), ('en',"Les Machines de l'Île")], 'q': ['Grand Éléphant Nantes']},
 'qc': {'wp': [('fr','Quartier de la création')], 'q': ['Halles Alstom Nantes', 'Quartier de la création Nantes']},
 'van': {'wp': [('fr','Le Voyage à Nantes')], 'q': ['Voyage à Nantes ligne verte', 'Voyage à Nantes']},
 'mucem': {'wp': [('fr',"Musée des Civilisations de l'Europe et de la Méditerranée"), ('en','Mucem')], 'q': ['MuCEM passerelle']},
 'lieux': {'wp': [('fr','Cité des arts de la rue'), ('fr','Lieux publics')], 'q': ['Cité des arts de la rue Marseille']},
 'friche': {'wp': [('fr','Friche la Belle de Mai'), ('en','Friche la Belle de Mai')], 'q': ['Friche Belle de Mai toit']},
 'camargo': {'wp': [('fr','Fondation Camargo')], 'q': ['Fondation Camargo Cassis', 'Cassis port calanque']},
}
def pageimage(lang, title):
    u = f'https://{lang}.wikipedia.org/w/api.php?' + urllib.parse.urlencode({'action':'query','prop':'pageimages','piprop':'name','titles':title,'redirects':1,'format':'json'})
    for p in js(u).get('query',{}).get('pages',{}).values():
        if p.get('pageimage'): return p['pageimage']
def search(q, n=3):
    u = 'https://commons.wikimedia.org/w/api.php?' + urllib.parse.urlencode({'action':'query','list':'search','srnamespace':6,'srsearch':q+' filetype:bitmap','srlimit':n,'format':'json'})
    return [h['title'][5:] for h in js(u).get('query',{}).get('search',[])]
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
    meta[sid] = []
    for i, n in enumerate(names[:6]):
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
