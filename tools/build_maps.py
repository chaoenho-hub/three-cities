"""Build figure-ground site plans and city overview maps from OpenStreetMap (Overpass API).
Runs on GitHub Actions (needs network + shapely). Output: maps/*.json  (© OpenStreetMap contributors, ODbL)."""
import json, math, os, sys, time, urllib.parse, urllib.request
from shapely.geometry import Polygon, LineString, Point, box, MultiPolygon, GeometryCollection
from shapely.ops import polygonize, unary_union, linemerge, split

EP = ['https://overpass-api.de/api/interpreter', 'https://overpass.kumi.systems/api/interpreter',
      'https://maps.mail.ru/osm/tools/overpass/api/interpreter']
UA = {'User-Agent': 'three-cities-field-notes/1.0 (https://github.com/chaoenho-hub/three-cities)'}

def overpass(q):
    last = None
    for attempt in range(6):
        url = EP[attempt % len(EP)]
        try:
            req = urllib.request.Request(url, data=urllib.parse.urlencode({'data': q}).encode(), headers=UA)
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.loads(r.read())
        except Exception as e:
            last = e; print('  overpass retry', attempt, url, e, flush=True); time.sleep(15 + attempt * 10)
    raise last

SITES = {
 'brtf': ((48.8575, 2.3170), 'paris', None, 'addr'),
 '104': ((48.8899, 2.3714), 'paris', 'Centquatre|CENTQUATRE|104', None),
 'tokyo': ((48.8641, 2.2966), 'paris', 'Palais de Tokyo', None),
 'gpe': ((48.9183, 2.3437), 'paris', 'Saint-Denis Pleyel', None),
 'cartoucherie': ((48.8339, 2.4475), 'paris', 'Cartoucherie', None),
 'pompidou': ((48.8606, 2.3522), 'paris', 'Centre Pompidou|Centre Georges Pompidou|Centre national d.art et de culture', None),
 'orsay': ((48.8600, 2.3266), 'paris', "Musée d.Orsay", None),
 'lu': ((47.2153, -1.5455), 'nantes', 'Lieu Unique|lieu unique', None),
 'samoa': ((47.2058, -1.5570), 'nantes', None, None),
 'machines': ((47.2066, -1.5641), 'nantes', "Machines de l.[ÎI]le|Nefs", None),
 'qc': ((47.2045, -1.5520), 'nantes', None, None),
 'mucem': ((43.2969, 5.3610), 'marseille', 'Mucem|MuCEM|Musée des civilisations', None),
 'lieux': ((43.3350, 5.3743), 'marseille', 'Cité des [Aa]rts de la [Rr]ue', None),
 'friche': ((43.3105, 5.3907), 'marseille', 'Friche', None),
 'camargo': ((43.2147, 5.5389), 'marseille', 'Camargo', None),
}
# overview bbox: (lat0, lon0, lat1, lon1), drawn into 400 x 300
CITY = {
 'paris': (48.8265, 2.2650, 48.9255, 2.4785),
 'nantes': (47.1960, -1.5830, 47.2220, -1.5265),
 'marseille': (43.1930, 5.2650, 43.3470, 5.5960),
}
PLAN_W, PLAN_H = 900, 600  # metres

def ring_coords(geom):
    return [(p['lon'], p['lat']) for p in geom]

def elements_to_geoms(els):
    """Return list of (tags, geometry) with polygons for closed ways / multipolygons and lines for open ways."""
    out = []
    for e in els:
        t = e.get('tags', {})
        if e['type'] == 'way' and 'geometry' in e:
            c = ring_coords(e['geometry'])
            if len(c) >= 4 and c[0] == c[-1] and not is_linear(t):
                try:
                    p = Polygon(c)
                    if not p.is_valid: p = p.buffer(0)
                    out.append((t, p))
                except Exception: pass
            elif len(c) >= 2:
                out.append((t, LineString(c)))
        elif e['type'] == 'relation' and 'members' in e:
            outers, inners = [], []
            for m in e['members']:
                if m.get('type') != 'way' or 'geometry' not in m: continue
                ls = LineString(ring_coords(m['geometry'])) if len(m['geometry']) >= 2 else None
                if ls is None: continue
                (inners if m.get('role') == 'inner' else outers).append(ls)
            try:
                op = unary_union(list(polygonize(unary_union(outers)))) if outers else None
                ip = unary_union(list(polygonize(unary_union(inners)))) if inners else None
                if op is None or op.is_empty: continue
                g = op.difference(ip) if ip is not None and not ip.is_empty else op
                out.append((t, g))
            except Exception as ex:
                print('  relation fail', e.get('id'), ex)
    return out

def is_linear(t):
    return ('highway' in t and t.get('area') != 'yes') or 'railway' in t or t.get('natural') == 'coastline' or 'barrier' in t

class Frame:
    def __init__(self, lat0, lon0, lat1, lon1, W, H):
        self.lat0, self.lon0, self.lat1, self.lon1, self.W, self.H = lat0, lon0, lat1, lon1, W, H
    def xy(self, lon, lat):
        return ((lon - self.lon0) / (self.lon1 - self.lon0) * self.W, (self.lat1 - lat) / (self.lat1 - self.lat0) * self.H)
    def tx(self, g):
        import numpy as np, shapely
        def f(c):
            return np.column_stack(((c[:, 0] - self.lon0) / (self.lon1 - self.lon0) * self.W, (self.lat1 - c[:, 1]) / (self.lat1 - self.lat0) * self.H))
        return shapely.transform(g, f)
    def bbox(self):
        return box(self.lon0, self.lat0, self.lon1, self.lat1)

def fmt(v, nd):
    s = ('%.' + str(nd) + 'f') % v
    if '.' in s: s = s.rstrip('0').rstrip('.')
    return '0' if s in ('-0', '') else s

def path_ring(coords, nd, close=True):
    pts = [(round(x, nd), round(y, nd)) for x, y in coords]
    ded = [pts[0]]
    for p in pts[1:]:
        if p != ded[-1]: ded.append(p)
    if close and len(ded) < 4: return ''
    if not close and len(ded) < 2: return ''
    if close and ded[0] == ded[-1]: ded = ded[:-1]
    s = 'M' + fmt(ded[0][0], nd) + ' ' + fmt(ded[0][1], nd)
    px, py = ded[0]
    for x, y in ded[1:]:
        s += 'l' + fmt(x - px, nd) + ' ' + fmt(y - py, nd); px, py = x, y
    return s + ('z' if close else '')

def polys(g):
    if g.is_empty: return []
    if isinstance(g, Polygon): return [g]
    if isinstance(g, (MultiPolygon, GeometryCollection)):
        r = []
        for x in g.geoms: r += polys(x)
        return r
    return []

def lines(g):
    if g.is_empty: return []
    if isinstance(g, LineString): return [g]
    if hasattr(g, 'geoms'):
        r = []
        for x in g.geoms: r += lines(x)
        return r
    return []

def poly_path(gs, nd, tol):
    out = []
    for g in gs:
        for p in polys(g):
            p = p.simplify(tol, preserve_topology=True)
            if p.is_empty or p.area < tol * tol * 2: continue
            for q in polys(p):
                out.append(path_ring(q.exterior.coords, nd))
                for h in q.interiors: out.append(path_ring(h.coords, nd))
    return ''.join(out)

def line_path(gs, nd, tol):
    out = []
    for g in gs:
        for l in lines(g):
            l = l.simplify(tol)
            out.append(path_ring(l.coords, nd, close=False))
    return ''.join(out)

def sea_from_coast(coast_lines, bb):
    """Split bbox polygon by coastline; pieces on the right side of coastline direction are sea."""
    if not coast_lines: return None
    merged = linemerge(unary_union(coast_lines))
    segs = lines(merged)
    if not segs: return None
    pieces = list(polys(split(bb, unary_union([s for s in segs]))))
    if len(pieces) < 2: return None
    votes = {i: 0 for i in range(len(pieces))}
    eps = 1e-5
    for s in segs:
        cs = list(s.coords)
        for a, b in zip(cs[:-1], cs[1:]):
            dx, dy = b[0] - a[0], b[1] - a[1]
            n = math.hypot(dx, dy)
            if n == 0: continue
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            r = Point(mx + dy / n * eps, my - dx / n * eps)
            l = Point(mx - dy / n * eps, my + dx / n * eps)
            for i, pc in enumerate(pieces):
                if pc.contains(r): votes[i] += 1
                if pc.contains(l): votes[i] -= 1
    sea = [pieces[i] for i, v in votes.items() if v > 0]
    return unary_union(sea) if sea else None

WATER = lambda t: t.get('natural') == 'water' or t.get('waterway') == 'riverbank' or t.get('landuse') == 'basin' or t.get('water') in ('river', 'canal', 'harbour', 'basin')
GREEN = lambda t: t.get('leisure') in ('park', 'garden', 'pitch', 'playground') or t.get('landuse') in ('grass', 'forest', 'recreation_ground', 'cemetery', 'meadow', 'village_green') or t.get('natural') in ('wood', 'scrub', 'grassland', 'heath')
MAJOR = {'motorway', 'trunk', 'primary', 'secondary', 'motorway_link', 'trunk_link', 'primary_link'}
MID = {'tertiary', 'residential', 'unclassified', 'living_street', 'pedestrian', 'secondary_link', 'tertiary_link'}
MINOR = {'service', 'footway', 'path', 'cycleway', 'steps', 'track'}

def bboxq(lat0, lon0, lat1, lon1):
    return '%.6f,%.6f,%.6f,%.6f' % (lat0, lon0, lat1, lon1)

def find_site(sid, ll, rx, mode):
    lat, lon = ll
    if mode == 'addr':
        q = '[out:json][timeout:60];(way["addr:housenumber"="78"]["addr:street"~"Universit"](around:1500,%f,%f);node["addr:housenumber"="78"]["addr:street"~"Universit"](around:1500,%f,%f););out geom;' % (lat, lon, lat, lon)
    else:
        q = '[out:json][timeout:60];nwr["name"~"%s",i](around:1500,%f,%f);out geom;' % (rx, lat, lon)
    els = overpass(q).get('elements', [])
    best = None
    for e in els:
        t = e.get('tags', {})
        if e['type'] == 'node':
            g = Point(e['lon'], e['lat']); area = 0
        else:
            gg = elements_to_geoms([e])
            if not gg: continue
            g = gg[0][1]
            if not isinstance(g, (Polygon, MultiPolygon)): continue
            area = g.area
        d = g.centroid.distance(Point(lon, lat))
        score = (0 if ('building' in t or 'tourism' in t or 'amenity' in t or 'railway' in t or 'public_transport' in t or e['type'] != 'node' or mode == 'addr') else 1, d)
        if best is None or score < best[0]:
            best = (score, e, g, t)
    if not best: return None
    _, e, g, t = best
    c = g.representative_point() if not isinstance(g, Point) else g
    return {'type': e['type'], 'id': e['id'], 'name': t.get('name', t.get('addr:street', '')), 'll': [round(c.y, 6), round(c.x, 6)], 'geom': g, 'tags': {k: t[k] for k in list(t)[:12]}}

def plan_query(lat0, lon0, lat1, lon1):
    b = bboxq(lat0, lon0, lat1, lon1)
    return ('[out:json][timeout:180][maxsize:536870912];('
            'way["building"](%(b)s);relation["building"](%(b)s);'
            'way["natural"="water"](%(b)s);relation["natural"="water"](%(b)s);way["waterway"="riverbank"](%(b)s);way["landuse"="basin"](%(b)s);'
            'way["leisure"~"^(park|garden|pitch|playground)$"](%(b)s);relation["leisure"="park"](%(b)s);'
            'way["landuse"~"^(grass|forest|recreation_ground|cemetery|meadow|village_green)$"](%(b)s);relation["landuse"~"^(forest|grass)$"](%(b)s);'
            'way["natural"~"^(wood|scrub|grassland)$"](%(b)s);'
            'way["highway"](%(b)s);way["railway"~"^(rail|light_rail|tram)$"](%(b)s);way["natural"="coastline"](%(b)s);'
            ');out geom;') % {'b': b}

def overview_query(lat0, lon0, lat1, lon1):
    b = bboxq(lat0, lon0, lat1, lon1)
    return ('[out:json][timeout:240][maxsize:1073741824];('
            'way["natural"="water"](%(b)s);relation["natural"="water"](%(b)s);way["waterway"="riverbank"](%(b)s);way["landuse"="basin"](%(b)s);'
            'way["leisure"="park"](%(b)s);relation["leisure"="park"](%(b)s);'
            'way["landuse"~"^(forest|cemetery|recreation_ground)$"](%(b)s);relation["landuse"="forest"](%(b)s);way["natural"="wood"](%(b)s);relation["natural"="wood"](%(b)s);'
            'way["highway"~"^(motorway|trunk|primary|secondary|motorway_link|trunk_link)$"](%(b)s);'
            'way["railway"="rail"][!"service"](%(b)s);way["natural"="coastline"](%(b)s);'
            ');out geom;') % {'b': b}

def tunnel(t): return t.get('tunnel') in ('yes', 'building_passage', 'culvert') or t.get('layer', '0').startswith('-')

def build_layers(geoms, fr, nd, tol, kind):
    bbg = fr.bbox()
    water, green, bld, coast = [], [], [], []
    roads = {'a': [], 'b': [], 'c': []}
    rail = []
    for t, g in geoms:
        try:
            if t.get('natural') == 'coastline': coast.append(g); continue
            if 'building' in t and kind == 'plan':
                if isinstance(g, (Polygon, MultiPolygon)): bld.append((t, g)); continue
            if 'highway' in t and isinstance(g, LineString):
                if tunnel(t): continue
                h = t['highway']
                k = 'a' if h in MAJOR else 'b' if h in MID else 'c' if h in MINOR else None
                if k: roads[k].append(g.intersection(bbg))
                continue
            if 'railway' in t and isinstance(g, LineString):
                if tunnel(t): continue
                rail.append(g.intersection(bbg)); continue
            if isinstance(g, (Polygon, MultiPolygon)):
                if WATER(t): water.append(g.intersection(bbg))
                elif GREEN(t):
                    if kind == 'overview' and g.area < 2e-6: continue
                    green.append(g.intersection(bbg))
        except Exception as ex:
            print('  layer fail', ex)
    sea = sea_from_coast(coast, bbg)
    if sea is not None: water.append(sea)
    T = fr.tx
    out = {
        'water': poly_path([T(unary_union(water))] if water else [], nd, tol),
        'green': poly_path([T(unary_union(green))] if green else [], nd, tol),
        'rail': line_path([T(g) for g in rail], nd, tol),
        'ra': line_path([T(g) for g in roads['a']], nd, tol),
        'rb': line_path([T(g) for g in roads['b']], nd, tol),
        'rc': line_path([T(g) for g in roads['c']], nd, tol) if kind == 'plan' else '',
    }
    return out, bld

os.makedirs('maps', exist_ok=True)
report = {}
only = sys.argv[1:]
for city, (lat0, lon0, lat1, lon1) in CITY.items():
    if only and city not in only: continue
    print('overview', city, flush=True)
    fr = Frame(lat0, lon0, lat1, lon1, 400, 300)
    els = overpass(overview_query(lat0, lon0, lat1, lon1)).get('elements', [])
    layers, _ = build_layers(elements_to_geoms(els), fr, 1, 0.35, 'overview')
    layers['bbox'] = [lat0, lon0, lat1, lon1]
    json.dump(layers, open('maps/%s.json' % city, 'w'), separators=(',', ':'))
    report[city] = {'elements': len(els), 'bytes': os.path.getsize('maps/%s.json' % city)}
    time.sleep(8)

for sid, (ll, city, rx, mode) in SITES.items():
    if only and sid not in only and city not in only: continue
    print('site', sid, flush=True)
    found = None
    if rx or mode:
        try: found = find_site(sid, ll, rx, mode)
        except Exception as ex: print('  find fail', ex)
        time.sleep(4)
    lat, lon = (found['ll'] if found else ll)
    dlat = PLAN_H / 2 / 110574.0
    dlon = PLAN_W / 2 / (111320.0 * math.cos(math.radians(lat)))
    fr = Frame(lat - dlat, lon - dlon, lat + dlat, lon + dlon, PLAN_W, PLAN_H)
    els = overpass(plan_query(lat - dlat, lon - dlon, lat + dlat, lon + dlon)).get('elements', [])
    geoms = elements_to_geoms(els)
    layers, bld = build_layers(geoms, fr, 0, 0.7, 'plan')
    # highlight: buildings inside the found area, or the building containing / nearest the point
    hl, rest = [], []
    target = found['geom'] if found else None
    pt = Point(lon, lat)
    area_t = target if target is not None and isinstance(target, (Polygon, MultiPolygon)) else None
    for t, g in bld:
        inside = False
        if area_t is not None:
            try: inside = area_t.buffer(0).intersection(g).area > 0.5 * g.area
            except Exception: inside = False
        elif g.buffer(0).contains(pt):
            inside = True
        (hl if inside else rest).append(g)
    if not hl and area_t is None:
        near = sorted(rest, key=lambda g: g.distance(pt))
        if near and near[0].distance(pt) < 0.0004:
            hl.append(near[0]); rest.remove(near[0])
    bbg = fr.bbox()
    layers['bld'] = poly_path([fr.tx(g.intersection(bbg)) for g in rest], 0, 0.7)
    layers['hl'] = poly_path([fr.tx(g.intersection(bbg)) for g in hl], 0, 0.7)
    layers['area'] = poly_path([fr.tx(area_t.intersection(bbg))], 0, 0.7) if area_t is not None and not hl else ''
    layers['bbox'] = [fr.lat0, fr.lon0, fr.lat1, fr.lon1]
    layers['ll'] = [lat, lon]
    json.dump(layers, open('maps/%s.json' % sid, 'w'), separators=(',', ':'))
    report[sid] = {'found': {k: v for k, v in found.items() if k != 'geom'} if found else None, 'll': [lat, lon],
                   'buildings': len(bld), 'highlight': len(hl), 'elements': len(els), 'bytes': os.path.getsize('maps/%s.json' % sid)}
    print('  ', json.dumps(report[sid], ensure_ascii=False)[:400], flush=True)
    time.sleep(8)

json.dump(report, open('maps/report.json', 'w'), ensure_ascii=False, indent=1)
