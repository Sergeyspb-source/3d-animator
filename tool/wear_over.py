"""Blender: belts and what hangs on them over the clothes, whatever they were made over (2026-11-28, the user: «quivers,
sheaths must always stay on top of the clothes, not covered by them»; «the belt either under the clothes or over them -
here over»). A set put together from pieces made for different sets (the guards: a scabbard made over a shirt worn over a
mail shirt) had the mail come out over the belt, the scabbard half sunk in it.

    import wear_over
    stats = wear_over.over_clothes(worn, body, arm)   # worn: the pieces' meshes, each with o["kind"]; body: the skin's

At rest (the meshes' own vertices, in the world), round the torso's axis (hips -> neck, cells CELL_MM along it, NA ways
round):
1. the bands: each item's islands going round the body (round most of it, not more than BAND_SPAN_MM along it), their
   whole faces (a strap's points are at its edges, its top ones and its bottom ones at other angles);
2. where a band lies pulled tight (the editor's waistRing over clothes; the user: «the belt in a half circle, smoothly
   round the waist», «its upper edge on the clothes, not square to the ground»): in each of its rows the body's
   outermost, on it each soft piece's own thickness, over what is hard there - each row its own (tilted as the body is),
   snug round, its middle not under its edges' line;
3. the soft clothes (SOFT, a tassets skirt only of mail) pressed in under it, out of it at a slant (SLOPE) for TAPER_MM
   above and below, their thickness kept, never into what is under them, folds above and below; under it held to the
   body (its skin weights - a mail skirt's top made to bend with the thighs came out through the belt in a clip);
4. the band onto those rows (no deeper than the clothes as pressed), held to the body too; a ring that is no band (a
   strap across) out over what is under it way round by way round; what hangs from it (a scabbard, a pouch, a quiver)
   whole along its own way out, with the band it hangs from; a quiver's arrows as the quiver.
The cells between a mesh's points take their neighbours' (else a checkerboard pressed: the cloth in teeth).
The same rule as SF3DEquip._cinch (Godot) and the armour editor's cinchShown."""
import numpy as np

ITEMS = ("belt", "sheath")
SOFT = ("undercloth", "trousers", "tunic", "vest", "hauberk", "gambeson", "apron", "skirt")
SKIP = ("hair", "beard", "brows", "lashes", "weapon", "shield")
NA, CELL_MM, GAP_MM, SLOPE, TAPER_MM, REACH_MM, GATHER_MM, FOLDS, MAX_MM = 72, 4.0, 2.5, .6, 30.0, 75.0, 7.0, 9, 80.0
MAX_PEN_MM = 45.0   # deeper under something than this: not a layer under it (an arm held out past a quiver's strap)
CINCH_LAYER_MM, CINCH_GAP_MM = .5, 1.2   # over a soft piece's own thickness under a belt pulled tight; the belt off it
CINCH_MAX_MM = 20.0   # a soft piece pressed in under a belt at most (loose clothes of another set: 4 cm in, the layers swapped)
HARD_NEAR_MM = 15.0   # armour under a belt only where it lies on what is under it (a back plate's edge standing off: over the belt)
ARMOUR, ARMOUR_GAP_MM = ("cuirass",), 1.5   # what the soft clothes are always kept under; how far off its inside
BAND_TILT = .35   # across per along at most, a band pulled tight (stiff leather: not a lampshade over a seat)
BAND_SPAN_MM = 150.0   # along the body at most for a band (a quiver's strap from a shoulder to the hip goes round half of it)


def _pts(o):
    n = len(o.data.vertices)
    co = np.empty(n * 3)
    o.data.vertices.foreach_get("co", co)
    M = np.array(o.matrix_world)
    P = co.reshape(-1, 3)
    return P @ M[:3, :3].T + M[:3, 3]


def _put(o, P):
    M = np.array(o.matrix_world)
    Mi = np.linalg.inv(M)
    loc = P @ Mi[:3, :3].T + Mi[:3, 3]
    o.data.vertices.foreach_set("co", loc.reshape(-1))
    o.data.update()


def _limb_free(o):
    """which of its vertices move mostly with the torso or the legs, not an arm (an arm held out past a quiver's strap is
    not a layer under it)"""
    names = [g.name.lower() for g in o.vertex_groups]
    armg = np.array(["arm" in n or "hand" in n or "elbow" in n for n in names] + [False])
    out = np.ones(len(o.data.vertices), bool)
    if not armg.any():
        return out
    for v in o.data.vertices:
        best, bw = -1, 0.0
        for g in v.groups:
            if g.weight > bw:
                best, bw = g.group, g.weight
        if best >= 0 and armg[best]:
            out[v.index] = False
    return out


def _group(objs):
    """the meshes of one piece together (a quiver and its arrows: by the piece's id, else the name before «__»)"""
    by = {}
    for o in objs:
        key = str(o.get("pid", "")) or o.name.split("__")[0]
        by.setdefault(key, []).append(o)
    return [sorted(g, key=lambda o: ("__" in o.name, o.name)) for g in by.values()]


def _islands(o):
    """each vertex's island (connected by edges)"""
    n = len(o.data.vertices)
    par = np.arange(n)

    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x
    ed = np.empty(len(o.data.edges) * 2, dtype=np.int64)
    o.data.edges.foreach_get("vertices", ed)
    for a, b in ed.reshape(-1, 2):
        ra, rb = find(a), find(b)
        if ra != rb:
            par[rb] = ra
    # (and the vertices at one place: a glTF's are split at its UV seams and hard edges - a belt fell into dozens of bits)
    co = np.empty(n * 3)
    o.data.vertices.foreach_get("co", co)
    key = np.round(co.reshape(-1, 3) * 1e4).astype(np.int64)
    first = {}
    for i, kk in enumerate(map(tuple, key)):
        j = first.setdefault(kk, i)
        if j != i:
            ra, rb = find(j), find(i)
            if ra != rb:
                par[rb] = ra
    return np.array([find(i) for i in range(n)])


def _face_pts(o, P, keep, step):
    """points over its triangles no farther apart than step, of the vertices kept (a strap's points are at its edges,
    its top ones and its bottom ones at other angles round: its whole face)"""
    me = o.data
    me.calc_loop_triangles()
    tri = np.empty(len(me.loop_triangles) * 3, dtype=np.int64)
    me.loop_triangles.foreach_get("vertices", tri)
    tri = tri.reshape(-1, 3)
    tri = tri[keep[tri[:, 0]]]
    out = [P[np.unique(tri)]] if len(tri) else []
    for a, b, c in tri:
        A, B, C = P[a], P[b], P[c]
        n = int(np.clip(np.ceil(max(np.linalg.norm(A - B), np.linalg.norm(B - C), np.linalg.norm(C - A)) / step), 1, 32))
        p, q = np.meshgrid(np.arange(n + 1), np.arange(n + 1), indexing="ij")
        ok = p + q <= n
        w1, w2 = (p[ok] / n)[:, None], (q[ok] / n)[:, None]
        out.append(A + (B - A) * w1 + (C - A) * w2)
    return np.concatenate(out) if out else np.zeros((0, 3))


def _weights_of(body):
    """the body's points (world) in a KD-tree and their skin weights ({group: weight} each)"""
    from mathutils import Vector, kdtree
    pts, ws = [], []
    for o in body:
        names = [g.name for g in o.vertex_groups]
        pts.append(_pts(o))
        for v in o.data.vertices:
            ws.append({names[g.group]: g.weight for g in v.groups if g.weight > 1e-4 and g.group < len(names)})
    if not pts or not ws:
        return None
    P = np.concatenate(pts)
    tree = kdtree.KDTree(len(P))
    for k, p in enumerate(P):
        tree.insert(Vector(p), k)
    tree.balance()
    return tree, ws


def _hold(o, idx, at, f, bodyW, mm, keep=4):
    """its points idx (now at «at», in the world) bent with the body there: their skin weights moved toward the body's
    by f (1: the body's) - of its points within 30 mm, nearer ones more (the nearest alone jumped from one to the next:
    the clothes bent in streaks); the most weighty «keep» of them, summing to 1"""
    from mathutils import Vector
    tree, ws = bodyW
    R = 30 * mm
    vg = o.vertex_groups
    for k, p, fk in zip(idx, at, f):
        found = tree.find_range(Vector(p), R) or [tree.find(Vector(p))]
        body = {}
        for _, i, d in found:
            kw = (1 - d / R) ** 2 if d < R else 1.0
            for nm, w in ws[i].items():   # (not a leg's: between the buttocks both thighs pulled the belt apart in a clip)
                if not any(x in nm.lower() for x in ("leg", "foot", "toe")):
                    body[nm] = body.get(nm, 0.0) + w * kw
        tb = sum(body.values())
        if tb <= 1e-9:
            continue
        v = o.data.vertices[int(k)]
        own = {vg[g.group].name: g.weight for g in v.groups if g.group < len(vg)}
        to = sum(own.values())
        mix = {nm: w / tb * fk for nm, w in body.items()}
        for nm, w in own.items():
            mix[nm] = mix.get(nm, 0.0) + (w / to if to > 1e-9 else 0.0) * (1 - fk)
        top = sorted(mix.items(), key=lambda e: -e[1])[:keep]
        s = sum(w for _, w in top)
        for nm in own:
            vg[nm].remove([int(k)])
        for nm, w in top:
            g = vg.get(nm) or vg.new(name=nm)
            g.add([int(k)], w / s, "REPLACE")


def _soft(o):
    k = str(o.get("kind", ""))
    if k in SOFT:
        return True
    if k == "tassets":   # (of mail: soft; of plates: not pressed)
        names = [m.name.lower() for m in o.data.materials if m]
        return any(n.endswith("_mail") or "mail" in n for n in names) and not any(n.endswith("_plate") for n in names)
    return False


def _stack_press(OUT, INN, wall, flo, cap, mm, layers):
    """the soft pieces' stack (OUT, INN: each piece's outside, inside in the cells) pressed in under the wall as one: in the
    order of their layers (between equal ones as they lie in most of the cells - each cell's own order flipped at a skirt's
    top edge: shards; pressed one by one they had swapped places), each its thickness and
    0.5 mm apart, the outermost no farther out than the wall, none deeper than cap, none into the body (flo: what is under
    them), and in that order where the wall needs no press too; cells needing more than MAX_PEN_MM left (not under it: a
    skirt off the legs, a sleeve). Each piece's press"""
    pres = np.isfinite(OUT) & np.isfinite(INN)
    TH = np.where(pres, np.clip(OUT - INN, .5 * mm, 25 * mm), 0)
    HI = np.where(pres, OUT, -np.inf)
    MID = np.where(pres, (OUT + INN) / 2, np.inf)
    gp = .5 * mm
    zone = np.isfinite(wall) & (pres.sum(0) >= 2)
    rk = np.argsort(np.argsort(MID, axis=0), axis=0).astype(float)
    # (by their layers' numbers - the set's own say: a shirt let down over the breeches; how they lie in most cells only
    # between equal ones - the breeches' wide waistband taken for the outer one came out below the belt)
    key = np.array([layers[k] + 1e-3 * (rk[k][zone & pres[k]].mean() if (zone & pres[k]).any() else 0) for k in range(len(OUT))])
    for i, j in zip(*np.where(np.isfinite(wall) & pres.any(0) & np.isfinite(flo))):
        ks = [k for k in np.argsort(key, kind="stable") if pres[k, i, j]]
        if OUT[ks[-1], i, j] - wall[i, j] > MAX_PEN_MM * mm:
            continue   # (loose enough or not: the order kept - a breeches' top came out through the shirt in teeth under
                       # the belt, where the shirt needed no press)
        lo, himin = flo[i, j] + gp, {}
        for k in ks:   # (the least each can be: on what is under it)
            himin[k] = lo + TH[k, i, j]
            lo = himin[k] + gp
        top = wall[i, j]
        for k in reversed(ks):   # (from the outside in: under the wall, under the one over it)
            HI[k, i, j] = max(min(OUT[k, i, j], top), himin[k], OUT[k, i, j] - cap)
            top = HI[k, i, j] - TH[k, i, j] - gp
        below = -np.inf
        for k in ks:   # (and in their order: one that could not go deeper keeps those over it out)
            HI[k, i, j] = max(HI[k, i, j], below + TH[k, i, j] + gp)
            below = HI[k, i, j]
    # (out as well, by 25 mm at most: one over a piece that could not go deeper under it lies over it - a shirt over the
    # breeches' thick waistband, which stood out through it under the belt as a torn strip)
    return np.where(pres, np.clip(OUT - HI, -25 * mm, None), 0)


def _frame(body, arm):
    """the torso's axis (hips -> neck) and its cells: (A, u, p1, p2, mm) or None"""
    bone = lambda w: next((b for b in arm.data.bones if b.name.lower().split(":")[-1] == w or b.name.lower().endswith("_" + w)), None)
    hb, nb_ = bone("hips"), bone("neck")
    if not hb or not nb_:
        return None
    A = np.array(arm.matrix_world @ hb.head_local)
    B = np.array(arm.matrix_world @ nb_.head_local)
    u = (B - A) / np.linalg.norm(B - A)
    p1 = np.array([0, -1, 0.]) if abs(u[1]) < .9 else np.array([1, 0, 0.])
    p1 = p1 - u * p1.dot(u)
    p1 /= np.linalg.norm(p1)
    bodyP = np.concatenate([_pts(o) for o in body])
    return A, u, p1, np.cross(u, p1), (bodyP[:, 2].max() - bodyP[:, 2].min()) / 1.75 / 1000


def under_armour(worn, body, arm, log=print):
    """The soft clothes worn under a cuirass (ARMOUR) pressed in under its inside, ARMOUR_GAP_MM off it, out of it at a
    slant (SLOPE) for TAPER_MM past its edges: one stack, in the order they lie, none into the body (_stack_press). A set put
    together from pieces made for others (the guards): a shirt made over a thin undershirt, worn under a tight brigandine,
    stood out through its back by 17-37 mm (the user, muscular_06: «a grey patch of the shirt over the brigandine in the
    middle of the back»); the layers' push hides it in Godot, a bake is one mesh"""
    covers = [o for o in worn if str(o.get("kind", "")) in ARMOUR]
    fr_ = _frame(body, arm) if covers else None
    if not fr_:
        return {}
    lay = min(float(c.get("layer", 4.0)) for c in covers)
    soft = sorted([o for o in worn if _soft(o) and float(o.get("layer", 0)) < lay], key=lambda q: float(q.get("layer", 0)))
    if not soft:
        return {}
    A, u, p1, p2, mm = fr_
    ds = CELL_MM * mm

    def cyl(P):
        d = P - A
        s = d @ u
        d = d - np.outer(s, u)
        return s, np.arctan2(d @ p2, d @ p1), np.linalg.norm(d, axis=1)
    col = lambda ang: np.floor((ang / (2 * np.pi) + 1) * NA).astype(int) % NA
    CP = [(_pts(c), _limb_free(c)) for c in covers]
    cs = np.concatenate([cyl(P)[0][lf] for P, lf in CP])
    S0g = cs.min() - (TAPER_MM + 40) * mm
    NR = int((cs.max() + (TAPER_MM + 40) * mm - S0g) / ds) + 1

    def binned(P, ok, lo=False):
        s, a, r = cyl(P)
        i = ((s - S0g) / ds).astype(int)
        m = (i >= 0) & (i < NR) & ok
        c = np.full((NR, NA), np.inf if lo else -np.inf)
        (np.minimum if lo else np.maximum).at(c, (i[m], col(a)[m]), r[m])
        return c

    def grow(c, lo=False, times=3):
        none = np.inf if lo else -np.inf
        for _ in range(times):
            g = c.copy()
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    sh = np.roll(np.roll(c, dj, 1), di, 0)
                    if di == 1:
                        sh[0] = none
                    elif di == -1:
                        sh[-1] = none
                    g = np.minimum(g, sh) if lo else np.maximum(g, sh)
            c = np.where(c == none, g, c)
        return c
    cin = np.full((NR, NA), np.inf)
    for P, lf in CP:
        cin = np.minimum(cin, binned(P, lf, True))
    cin = grow(cin, True)
    wall = cin - ARMOUR_GAP_MM * mm
    sl = SLOPE * ds
    for i in range(1, NR):
        wall[i] = np.minimum(wall[i], wall[i - 1] + sl)
    for i in range(NR - 2, -1, -1):
        wall[i] = np.minimum(wall[i], wall[i + 1] + sl)
    tr = int(TAPER_MM * mm / ds)
    for j in range(NA):   # (past its edges only TAPER_MM: breeches' legs, a skirt's flare free)
        rr = np.where(np.isfinite(cin[:, j]))[0]
        if not len(rr):
            wall[:, j] = np.inf
            continue
        wall[:max(0, rr.min() - tr), j] = np.inf
        wall[rr.max() + tr + 1:, j] = np.inf
    info = []
    for o in soft:
        P, lf = _pts(o), _limb_free(o)
        info.append((o, P, lf, grow(binned(P, lf)), grow(binned(P, lf, True), True)))
    OUT = np.stack([q[3] for q in info])
    INN = np.stack([q[4] for q in info])
    innermost = np.where(np.isfinite(OUT) & np.isfinite(INN), INN, np.inf).min(0)
    fs, fa, frr = cyl(np.concatenate([_pts(o) for o in body]))
    fi = ((fs - S0g) / ds).astype(int)
    fok = (fi >= 0) & (fi < NR)
    fj = col(fa)
    flo = np.full((NR, NA), -np.inf)
    sel = fok.copy()
    sel[fok] = frr[fok] <= innermost[fi[fok], fj[fok]] + 5 * mm
    np.maximum.at(flo, (fi[sel], fj[sel]), frr[sel])
    # (and round the waist below it, where two of them lie one on the other with no armour over them: in their layers'
    # order all the same - the breeches' thick waistband of another set stood out over the shirt let down over them, a
    # torn strip under the belt; the shirt over it)
    pres2 = (np.isfinite(OUT) & np.isfinite(INN)).sum(0) >= 2
    wall = np.where(np.isfinite(wall) | ~pres2, wall, np.where(np.isfinite(OUT), OUT, -np.inf).max(0) + mm)
    PRESS = _stack_press(OUT, INN, wall, grow(flo), MAX_PEN_MM * mm, mm, [float(o.get("layer", 0)) for o in soft])
    stats = {}
    for n, (o, P, lf, _, _) in enumerate(info):
        press = PRESS[n]
        if np.abs(press).max() < .5 * mm:
            continue
        s, ang, r = cyl(P)
        x = (s - S0g) / ds - .5
        i0 = np.clip(np.floor(x).astype(int), 0, NR - 2)
        f = np.clip(x - i0, 0, 1)
        y = (ang / (2 * np.pi) + 1) * NA - .5
        j0 = np.floor(y).astype(int) % NA
        g = y - np.floor(y)
        j1 = (j0 + 1) % NA
        m = (press[i0, j0] * (1 - g) + press[i0, j1] * g) * (1 - f) + (press[i0 + 1, j0] * (1 - g) + press[i0 + 1, j1] * g) * f
        m[(x < 0) | (x > NR - 1) | ~lf] = 0
        d = P - A
        d = d - np.outer(d @ u, u)
        nrm = np.linalg.norm(d, axis=1, keepdims=True)
        nrm[nrm < 1e-9] = 1
        _put(o, P - d / nrm * m[:, None])
        stats[o.name] = [round(float(press.max() / mm), 1), int((np.abs(m) > .5 * mm).sum())]
    log("UNDER_ARMOUR " + str(stats))
    return stats


def over_clothes(worn, body, arm, log=print):
    bone = lambda w: next((b for b in arm.data.bones if b.name.lower().split(":")[-1] == w or b.name.lower().endswith("_" + w)), None)
    hb, nb_ = bone("hips"), bone("neck")
    ua = under_armour(worn, body, arm, log)   # (the clothes under a cuirass first: the belt lies on them as they are then)
    items = [o for o in worn if str(o.get("kind", "")) in ITEMS]
    if not items or not hb or not nb_:
        return {"under_armour": ua} if ua else {}
    A = np.array(arm.matrix_world @ hb.head_local)
    B = np.array(arm.matrix_world @ nb_.head_local)
    u = (B - A) / np.linalg.norm(B - A)
    p1 = np.array([0, -1, 0.]) if abs(u[1]) < .9 else np.array([1, 0, 0.])
    p1 = p1 - u * p1.dot(u)
    p1 /= np.linalg.norm(p1)
    p2 = np.cross(u, p1)
    bodyP = np.concatenate([_pts(o) for o in body])
    mm = (bodyP[:, 2].max() - bodyP[:, 2].min()) / 1.75 / 1000
    ds = CELL_MM * mm

    def cyl(P):
        d = P - A
        s = d @ u
        d = d - np.outer(s, u)
        return s, np.arctan2(d @ p2, d @ p1), np.linalg.norm(d, axis=1)

    def radial(P):
        d = P - A
        d = d - np.outer(d @ u, u)
        n = np.linalg.norm(d, axis=1, keepdims=True)
        n[n < 1e-9] = 1
        return d / n
    col = lambda ang: np.floor((ang / (2 * np.pi) + 1) * NA).astype(int) % NA
    soft = sorted([o for o in worn if o not in items and _soft(o)], key=lambda q: float(q.get("layer", 0)))
    under = [o for o in worn if o not in items and str(o.get("kind", "")) not in SKIP]
    stats = {"pressed": {}, "items_out_mm": {}, "soft": [o.name for o in soft], "under_armour": ua}
    # 1. the bands: each item's islands going round the body as a band (round most of it, not far along it - a quiver's
    # strap from a shoulder to the hip goes round half of it), their whole faces (a strap's points are at its edges)
    allI = [(o, _pts(o)) for o in items]
    IS = np.concatenate([cyl(P)[0] for _, P in allI])
    S0g, S1g = IS.min() - (REACH_MM + 60) * mm, IS.max() + (REACH_MM + 60) * mm
    NR = int((S1g - S0g) / ds) + 1
    rowof = lambda s: np.clip(((s - S0g) / ds).astype(int), 0, NR - 1)

    def binned(P, ok=None, lo=False):
        s, a, r = cyl(P)
        i = ((s - S0g) / ds).astype(int)
        m = (i >= 0) & (i < NR)
        if ok is not None:
            m &= ok
        c = np.full((NR, NA), np.inf if lo else -np.inf)
        (np.minimum if lo else np.maximum).at(c, (i[m], col(a)[m]), r[m])
        return c

    def grow(c, lo=False, times=3):   # (cells between a mesh's points: their neighbours')
        none = np.inf if lo else -np.inf
        for _ in range(times):
            g = c.copy()
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    sh = np.roll(np.roll(c, dj, 1), di, 0)
                    if di == 1:
                        sh[0] = none
                    elif di == -1:
                        sh[-1] = none
                    g = np.minimum(g, sh) if lo else np.maximum(g, sh)
            c = np.where(c == none, g, c)
        return c

    def cell_at(c, s, ang):   # (between the four cells round it, unset ones left out)
        x = np.clip((s - S0g) / ds - .5, 0, NR - 1.001)
        i = np.floor(x).astype(int)
        f = x - i
        y = (ang / (2 * np.pi) + 1) * NA - .5
        j = np.floor(y).astype(int) % NA
        g = y - np.floor(y)
        j1, i1 = (j + 1) % NA, np.minimum(i + 1, NR - 1)
        num, den = np.zeros(len(s)), np.zeros(len(s))
        for v, w in ((c[i, j], (1 - f) * (1 - g)), (c[i, j1], (1 - f) * g), (c[i1, j], f * (1 - g)), (c[i1, j1], f * g)):
            okv = np.isfinite(v)
            num += np.where(okv, v * w, 0)
            den += np.where(okv, w, 0)
        return np.where(den > 1e-9, num / np.maximum(den, 1e-12), c[np.clip(np.round(x).astype(int), 0, NR - 1), np.round(y).astype(int) % NA])

    def snug(row, ok):   # (moving means of seven ways round, never in: round the body, not into a back's hollow)
        orig = np.where(ok, row, -np.inf)
        for _ in range(2):
            row = np.maximum(orig, sum(np.roll(row, d) for d in range(-3, 4)) / 7)
        return row

    band_in = np.full((NR, NA), np.inf)
    bands = {}
    for o, P in allI:
        s, a, r = cyl(P)
        j = col(a)
        isl = _islands(o)
        ring = np.zeros(len(P), bool)
        for k in np.unique(isl):
            sel = isl == k
            if len(np.unique(j[sel])) >= .6 * NA and np.ptp(s[sel]) <= BAND_SPAN_MM * mm:
                ring |= sel
        if ring.any():
            bands[o.name] = ring
            s2, a2, r2 = cyl(_face_pts(o, P, ring, .5 * ds))
            np.minimum.at(band_in, (rowof(s2), col(a2)), r2)
    stats["band_cells"] = int(np.isfinite(band_in).sum())
    have = np.isfinite(band_in).any(0)
    if have.any():
        for j in np.where(~have)[0]:   # (a way round the band misses: its nearest neighbour's)
            for k in range(1, NA // 2):
                q = (j + k) % NA if have[(j + k) % NA] else (j - k) % NA if have[(j - k) % NA] else -1
                if q >= 0:
                    band_in[:, j] = band_in[:, q]
                    break
    r0, r1 = np.full(NA, -1), np.full(NA, -1)
    for j in range(NA):
        rr = np.where(np.isfinite(band_in[:, j]))[0]
        if len(rr):
            r0[j], r1[j] = rr.min(), rr.max()
    b0 = np.where(r0 >= 0, S0g + r0 * ds, np.nan)
    b1 = np.where(r0 >= 0, S0g + (r1 + 1) * ds, np.nan)
    bodyW = _weights_of(body)
    # 2. where the band lies pulled tight (the editor's waistRing over clothes): the body's outermost, on it each soft
    # piece's own thickness, over what is hard there; each row its own (tilted as the body is: its upper edge on the
    # clothes), snug round, its middle not under its edges' line
    tight = np.full((NR, NA), np.inf)
    if (r0 >= 0).any():
        own = np.full((NR, NA), -np.inf)
        for o in body:
            own = np.maximum(own, binned(_pts(o), _limb_free(o)))
        own = grow(own)
        hard = np.full((NR, NA), -np.inf)
        th = np.zeros((NR, NA))
        for o in under:
            P, lf = _pts(o), _limb_free(o)
            if o not in soft:
                hard = np.maximum(hard, binned(P, lf))
                continue
            hi, lo = binned(P, lf), binned(P, lf, True)
            t = grow(np.where(np.isfinite(hi), hi - lo, -np.inf))
            th += np.where(np.isfinite(t), np.clip(t, .5 * mm, 25 * mm) + CINCH_LAYER_MM * mm, 0)
        hard = grow(hard)
        soft_t = np.where(np.isfinite(own), own + th, -np.inf)
        hard = np.where(np.isfinite(soft_t) & (hard > soft_t + HARD_NEAR_MM * mm), -np.inf, hard)   # (a plate's edge standing off: the belt under it)
        T = np.maximum(soft_t, hard)
        for i in range(NR):
            row = T[i].copy()
            v = row[np.isfinite(row)]
            if not len(v):
                continue
            ok = np.isfinite(row) & (row <= np.median(v) + 60 * mm)   # (not an arm by the body there)
            idx = np.where(ok)[0]
            for j in np.where(~ok)[0]:
                d = np.minimum((idx - j) % NA, (j - idx) % NA)
                row[j] = row[idx[d == d.min()]].max()
            T[i] = snug(row, ok)
        for j in range(NA):
            if r0[j] < 0 or not (np.isfinite(T[r0[j], j]) and np.isfinite(T[r1[j], j])):
                continue
            ii = np.arange(r0[j], r1[j] + 1)
            f = (ii - r0[j]) / max(1, r1[j] - r0[j])
            # (a strap stiff across: a straight line from edge to edge, tilted BAND_TILT at most - over a seat's top its
            # lower edge stood out as a lampshade, torn into teeth in the bake; what bulges under it is pressed in)
            a_, b_ = T[r0[j], j], T[r1[j], j]
            wdt = (r1[j] - r0[j]) * ds
            a_, b_ = min(a_, b_ + BAND_TILT * wdt), min(b_, a_ + BAND_TILT * wdt)
            line = a_ + (b_ - a_) * f
            tight[ii, j] = np.clip(T[ii, j], line, line + 2 * mm) + CINCH_GAP_MM * mm
    # 3. the soft clothes pressed in under it (its inside, out of it at a slant up to TAPER_MM above and below), their
    # thickness kept, never into what is under them, folds above and below; under it held to the body (its skin weights:
    # a mail skirt's top made to bend with the thighs came out through the belt in a clip)
    if np.isfinite(tight).any() and soft:
        wall = tight - .8 * mm
        sl = SLOPE * ds
        for i in range(1, NR):
            wall[i] = np.minimum(wall[i], wall[i - 1] + sl)
        for i in range(NR - 2, -1, -1):
            wall[i] = np.minimum(wall[i], wall[i + 1] + sl)
        si = S0g + (np.arange(NR) + .5) * ds
        for j in range(NA):
            if r0[j] < 0:
                wall[:, j] = np.inf
            else:
                wall[(si < b0[j] - TAPER_MM * mm) | (si > b1[j] + TAPER_MM * mm), j] = np.inf
        fs, fa, fr = cyl(np.concatenate([_pts(o) for o in body]))
        fi = ((fs - S0g) / ds).astype(int)
        fok = (fi >= 0) & (fi < NR)
        fj = col(fa)
        reach = REACH_MM * mm
        info = []
        for o in soft:
            P = _pts(o)
            s, ang, r = cyl(P)
            ii = ((s - S0g) / ds).astype(int)
            lf = _limb_free(o)   # (not a sleeve: a quiver's strap over a shoulder does not draw in what goes along an arm)
            ok = (ii >= 0) & (ii < NR) & lf
            jj = col(ang)
            outer = np.full((NR, NA), -np.inf)
            inner = np.full((NR, NA), np.inf)
            np.maximum.at(outer, (ii[ok], jj[ok]), r[ok])
            np.minimum.at(inner, (ii[ok], jj[ok]), r[ok])
            info.append((o, P, s, ang, r, lf, grow(outer), grow(inner, True)))
        # the stack in each cell pressed as one: in the order the pieces lie there (not by their layers' numbers - a
        # shirt worn over the breeches, pressed first under them, came out through them), each its thickness and 0.5 mm
        # apart, the outermost no farther out than the wall, none deeper than CINCH_MAX_MM, none into the body
        OUT = np.stack([q[6] for q in info])
        INN = np.stack([q[7] for q in info])
        pres = np.isfinite(OUT) & np.isfinite(INN)
        innermost = np.where(pres, INN, np.inf).min(0)
        flo = np.full((NR, NA), -np.inf)
        sel = fok.copy()
        sel[fok] = fr[fok] <= innermost[fi[fok], fj[fok]] + 5 * mm
        np.maximum.at(flo, (fi[sel], fj[sel]), fr[sel])
        flo = grow(flo)
        PRESS = _stack_press(OUT, INN, wall, flo, CINCH_MAX_MM * mm, mm, [float(o.get("layer", 0)) for o in soft])
        for n, (o, P, s, ang, r, lf, _, _) in enumerate(info):
            press = PRESS[n]
            jj2 = col(ang)
            sc_ = np.nan_to_num((b0[jj2] + b1[jj2]) / 2)
            off = np.where(np.isfinite(b0[jj2]), np.abs(s - sc_) - np.nan_to_num((b1[jj2] - b0[jj2]) / 2), 1e9)
            rn = r.copy()
            if np.abs(press).max() >= 1.5 * mm:
                x = (s - S0g) / ds - .5
                i0 = np.clip(np.floor(x).astype(int), 0, NR - 2)
                f = np.clip(x - i0, 0, 1)
                y = (ang / (2 * np.pi) + 1) * NA - .5
                j0 = np.floor(y).astype(int) % NA
                g = y - np.floor(y)
                j1 = (j0 + 1) % NA
                m = (press[i0, j0] * (1 - g) + press[i0, j1] * g) * (1 - f) + (press[i0 + 1, j0] * (1 - g) + press[i0 + 1, j1] * g) * f
                m[(x < 0) | (x > NR - 1)] = 0
                ph = np.where(s > sc_, 0, .5)
                fo = np.maximum(0, np.sin(ang * FOLDS / 2 + ph * np.pi / 2 + .3 * np.sin(ang * 3)))
                fidx = np.round(ang * FOLDS / (2 * np.pi) * 2).astype(np.int64)
                hv = ((fidx * 374761393 + 5 * 668265263 + 31) % 1000) / 1000
                t2 = np.clip(off / (12 * mm), 0, 1)
                smt = t2 * t2 * (3 - 2 * t2)
                gath = np.where((off > 0) & (off < reach), GATHER_MM * mm * smt * np.clip(1 - off / reach, 0, 1) ** 1.4 * fo * fo * (.6 + .4 * hv), 0)
                rn = np.where(lf, r - m + gath, r)
                _put(o, P + radial(P) * (rn - r)[:, None])
                stats["pressed"][o.name] = round(float(press.max() / mm), 1)
            # (held wholly up to TAPER_MM over and under the band, then let go as far again - a mail skirt's top over the
            # belt, held for a few mm only, still came out through the breeches with the thighs)
            t2 = np.clip(off / (TAPER_MM * mm) - 1, 0, 1)   # (below it too: a mail skirt let go at once came out over the belt)
            hf = 1 - t2 * t2 * (3 - 2 * t2)
            hold = lf & (hf > 0) & (off < 2 * TAPER_MM * mm)
            if hold.any() and bodyW:
                _hold(o, np.where(hold)[0], (P + radial(P) * (rn - r)[:, None])[hold], hf[hold], bodyW, mm)
    # 4. the items over what is under them: a band onto the tight rows (no deeper than the clothes as pressed), its
    # thickness kept, held to the body; a ring that is no band (a strap across) out way round by way round; what hangs
    # whole along its own way out, with the band it hangs from; a quiver's arrows as the quiver
    flo = np.full((NR, NA), -np.inf)
    flos = np.full((NR, NA), -np.inf)   # (the soft clothes and the body: what a band lies on)
    for o in under + list(body):
        c = binned(_pts(o), _limb_free(o))
        flo = np.maximum(flo, c)
        if o in body or o in soft:
            flos = np.maximum(flos, c)
    fl2 = flo.copy()
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            fl2 = np.maximum(fl2, np.roll(np.roll(flo, di, 0), dj, 1))
    gap = GAP_MM * mm
    tgt = np.full((NR, NA), np.inf)
    if np.isfinite(tight).any():
        flg = grow(flos)
        lift = np.where(np.isfinite(flg) & (flg + gap - tight <= MAX_PEN_MM * mm), np.maximum(tight, flg + gap), tight)
        tgt = np.where(np.isfinite(tight), lift, np.inf)
        for i in range(NR):
            okr = np.isfinite(tgt[i])
            if okr.any():
                v = np.where(okr, tgt[i], 0)
                cnt = sum(np.roll(okr, d) for d in range(-3, 4))
                for _ in range(2):
                    mean = sum(np.roll(v, d) for d in range(-3, 4)) / np.maximum(cnt, 1)
                    v = np.where(okr, np.maximum(np.where(okr, tgt[i], 0), mean), 0)
                tgt[i] = np.where(okr, v, np.inf)
    for grp in _group(items):
        Ps = [_pts(o) for o in grp]
        P = np.concatenate(Ps)
        s, a, r = cyl(P)
        i = rowof(s)
        j = col(a)
        need = np.where(np.isfinite(fl2[i, j]), fl2[i, j] + gap - r, -np.inf)
        need[need > MAX_PEN_MM * mm] = -np.inf
        off, isl, bmask = 0, [], []
        for o, Po in zip(grp, Ps):   # (islands of each mesh; a quiver's arrows: islands of their own, moved as the quiver)
            isl.append(_islands(o) + off)
            bmask.append(bands.get(o.name, np.zeros(len(Po), bool)))
            off += len(Po)
        isl, bmask = np.concatenate(isl), np.concatenate(bmask)
        move = np.zeros(len(P))
        dirs = radial(P)
        if bmask.any() and np.isfinite(tgt).any():
            # (each way round the band moved as a whole: its lower and its upper edge each by one amount, the points between
            # on the line between them, smoothed round - moved point by point by its cell its round strap was crushed flat
            # and ragged; a line that keeps every row of it out of what is under it)
            mlo, mhi = np.full(NA, np.nan), np.full(NA, np.nan)
            for jj in range(NA):
                if r0[jj] < 0:
                    continue
                rows = np.arange(r0[jj], r1[jj] + 1)
                nd_ = tgt[rows, jj] - band_in[rows, jj]
                ok_ = np.isfinite(nd_)
                if not ok_.any():
                    continue
                f_ = (rows - r0[jj]) / max(1, r1[jj] - r0[jj])
                lo_ = nd_[ok_][0] if ok_[0] else np.nanmin(nd_)
                hi_ = nd_[ok_][-1] if ok_[-1] else np.nanmin(nd_)
                lift = np.max(nd_[ok_] - (lo_ + (hi_ - lo_) * f_[ok_]))
                mlo[jj], mhi[jj] = lo_ + max(lift, 0), hi_ + max(lift, 0)
            for arr in (mlo, mhi):
                if np.isnan(arr).all():
                    arr[:] = 0
                idx = np.where(~np.isnan(arr))[0]
                for jj in np.where(np.isnan(arr))[0]:
                    d_ = np.minimum((idx - jj) % NA, (jj - idx) % NA)
                    arr[jj] = arr[idx[np.argmin(d_)]]
                arr[:] = sum(np.roll(arr, q) for q in (-2, -1, 0, 1, 2)) / 5
            yb = (a[bmask] / (2 * np.pi) + 1) * NA - .5
            j0b = np.floor(yb).astype(int) % NA
            gb = yb - np.floor(yb)
            j1b = (j0b + 1) % NA
            lo_v = mlo[j0b] * (1 - gb) + mlo[j1b] * gb
            hi_v = mhi[j0b] * (1 - gb) + mhi[j1b] * gb
            jn = np.round(yb).astype(int) % NA
            bb0, bb1 = np.nan_to_num(b0[jn]), np.nan_to_num(b1[jn])
            fb = np.clip((s[bmask] - bb0) / np.maximum(bb1 - bb0, 1e-9), 0, 1)
            move[bmask] = np.clip(lo_v + (hi_v - lo_v) * fb, -40 * mm, MAX_MM * mm)
        bidx = np.where(bmask)[0]
        for k in np.unique(isl):
            sel = (isl == k) & ~bmask
            if not sel.any():
                continue
            js = np.unique(j[sel])
            if len(js) >= NA // 2:   # (round the body, no band: way round by way round)
                per = np.full(NA, 0.0)
                np.maximum.at(per, j[sel], np.clip(need[sel], 0, None))
                o_k = int(np.searchsorted(np.cumsum([len(q) for q in Ps]), np.where(sel)[0][0], side="right"))
                base = sum(len(q) for q in Ps[:o_k])
                keep = np.zeros(len(Ps[o_k]), bool)
                keep[np.where(sel)[0] - base] = True
                fs2, fa2, fr2 = cyl(_face_pts(grp[o_k], Ps[o_k], keep, .5 * ds))   # (its whole face: what is under it all)
                fi2 = ((fs2 - S0g) / ds).astype(int)
                okf = (fi2 >= 0) & (fi2 < NR)
                fj2 = col(fa2)
                ef = fl2[fi2[okf], fj2[okf]] + gap - fr2[okf]
                okk = np.isfinite(ef) & (ef <= MAX_PEN_MM * mm)
                np.maximum.at(per, fj2[okf][okk], np.clip(ef[okk], 0, None))
                per = np.maximum.reduce([np.roll(per, q) for q in (-2, -1, 0, 1, 2)])
                move[sel] = np.minimum(per[j[sel]], MAX_MM * mm)
            else:   # (hanging from it: whole, along its own way out - with the band it hangs from, in as well)
                nk = float(need[sel].max()) if np.isfinite(need[sel]).any() else -np.inf
                dk = radial(P[sel].mean(0)[None])[0]
                dirs[sel] = dk
                mk = max(nk, 0.0)
                if len(bidx):
                    d2 = ((P[sel][:, None, :] - P[bidx][None, :, :]) ** 2).sum(2)
                    q = np.unravel_index(np.argmin(d2), d2.shape)
                    if d2[q] < (25 * mm) ** 2:
                        mk = max(nk, float(move[bidx[q[1]]]))
                move[sel] = float(np.clip(mk, -40 * mm, MAX_MM * mm))
        # (bits lying in or on another island - arrows in a quiver - move as the island they are in)
        if len(grp) > 1:
            n0 = len(Ps[0])
            for k in np.unique(isl[n0:]):
                sel = isl == k
                c = P[sel].mean(0)
                q = int(np.argmin(((P[:n0] - c) ** 2).sum(1)))
                move[sel] = move[q]
                dirs[sel] = dirs[q]
        most = float(np.abs(move).max()) if len(move) else 0.0
        if most > 1e-6:
            off = 0
            for o, Po in zip(grp, Ps):
                n = len(Po)
                _put(o, Po + dirs[off:off + n] * move[off:off + n, None])
                off += n
        off = 0
        for o, Po in zip(grp, Ps):   # (a band held to the body: bent with it, not with the hips alone)
            bm = bmask[off:off + len(Po)]
            if bm.any() and bodyW:
                _hold(o, np.where(bm)[0], (Po + dirs[off:off + len(Po)] * move[off:off + len(Po), None])[bm], np.ones(int(bm.sum())), bodyW, mm)
            off += len(Po)
        stats["items_out_mm"][grp[0].name] = round(most / mm, 1)
    log("WEAR_OVER " + str(stats))
    return stats
