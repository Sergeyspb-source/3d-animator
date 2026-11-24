"""Runs INSIDE Blender (imported by blender_footwear_gen.py): everyday footwear beside the vendor generator's six forms
(vendor/blender_armour/Footwear), built on its last (footwear_last: the same measured form, so blender_footwear_gen
fits them to the feet as it fits the others): townsfolk's soft turnshoes with a lace tied round the ankle and a seam
over the instep, a craftsman's rough laced work boot on a thick sole with a welt, sandals - a sole and straps over the
toes, the instep, round the ankle and up the heel, the foot itself left bare; a mage's (a traveller's) tall pull-on
boot to below the knee, no laces, two straps buckled round it (the ankle, the top), its top hemmed.

    STYLES: style -> (the vendor variant its proportions start from, its own settings)
    TALL: style -> how far up the shin its top comes (a share of the way from the ankle to the knee, measured on the
        character: blender_footwear_gen sets the shaft's height by it, over what is worn on the shins - job «under»)
    config(cat, style) -> the validated settings (footwear_catalog.validate_config of that variant)
    tall(last, p, height) -> the shaft's height set past the vendor's bounds, the last's profile carried up to it
    build(style, p, mats, collection) -> builds the right shoe in the generator's frame (the ankle at the origin, the toe
    -Y, up +Z, the sole's bottom at -ankle_height: footwear_pair.canonical_meshes moves it there after)
"""
import math

from mathutils import Vector

STYLES = {"turnshoe": ("leather_shoe", {"shaft_height": .100}),
          "work_boot": ("ankle_boot", {"shaft_height": .160, "sole_thickness": .011, "leather_thickness": .0032}),
          "sandal": ("leather_shoe", {"shaft_height": .100, "sole_thickness": .011}),
          "tall_boot": ("ankle_boot", {"shaft_height": .210, "sole_thickness": .011, "leather_thickness": .0032})}
TALL = {"tall_boot": .74}


def config(cat, style):
    base, extra = STYLES[style]
    return cat.validate_config(base, dict(extra))


def tall(last, p, height):
    """A shaft taller than the vendor's last (its profile ends at .21 m): the last's top round carried straight up in
    rows 2 cm apart (the upper is made of rings at the profile's heights: one long band from .21 up would stay straight
    over the calf, the shaft fitted round the leg only at its two ends), the shaft's height set to height."""
    top = last.PROFILE[-1]
    if top[0] < height + .03:
        z, rows = top[0], []
        while z < height + .03:
            z = round(z + .02, 3)
            rows.append((z, *top[1:]))
        last.PROFILE = tuple(last.PROFILE) + tuple(rows)
    p["shaft_height"] = height


def _ring(last, p, z, lift=0.0, n=64):
    """The last's round at height z, lift out from it (a lace, a welt lying on the shoe)."""
    pts = []
    for j in range(n):
        q = last.last_point(p, math.tau * j / n, z)
        d = Vector((q.x, q.y, 0))
        pts.append(q + (d.normalized() * lift if d.length > 1e-9 else Vector()))
    return pts


def build(style, p, mats, collection):
    import footwear_last as last
    from footwear_fittings import ankle_strap
    from kettle_hat_details import tube
    from elbow_geometry import ribbon
    if style == "turnshoe":   # soft leather, no tongue: a lace round the ankle tied over the open throat, a seam over the instep
        last.sole(p, mats, collection)
        # the throat open: closed, the instep came out through it as the foot bent; with the foot hidden in the shoe
        # (p["hidden_foot"], blender_footwear_gen) the open throat showed a dark slit into the empty shoe: closed then
        last.upper(p, mats, collection, laced=not p.get("hidden_foot"))
        z = p["shaft_height"] - .014
        tube("Lace_Round", _ring(last, p, z, .0012), .0011, mats["liner"], collection, True)
        front = last.last_point(p, 0, z) + Vector((0, -.0015, 0))
        for s in (-1, 1):   # the bow's loops and ends
            tube(f"Lace_Loop_{s}", [front, front + Vector((s * .010, -.004, .006)), front + Vector((s * .016, -.003, -.001)), front], .0010, mats["liner"], collection)
            tube(f"Lace_End_{s}", [front, front + Vector((s * .004, -.004, -.012)), front + Vector((s * .007, -.003, -.024))], .0010, mats["liner"], collection)
        seam = [last.last_point(p, 0, zz) + Vector((0, -.0016, 0)) for zz in [.024 + .028 * i / 11 for i in range(12)]]   # (up to the throat)
        tube("Instep_Seam", seam, .0009, mats["liner"], collection)
    elif style == "work_boot":   # a thick sole with a welt round it, a laced shaft above the ankle, its top rolled
        last.sole(p, mats, collection)
        last.upper(p, mats, collection, laced=True)
        last.laces(p, mats, collection)
        tube("Welt", _ring(last, p, p["sole_thickness"] + .002, .0018), .0024, mats["leather"], collection, True)
        tube("Top_Roll", _ring(last, p, p["shaft_height"] - .004, .0012), .0028, mats["leather"], collection, True)
        ankle_strap(p, p["shaft_height"] - .03, mats, collection, "Boot_Strap")
    elif style == "tall_boot":   # a pull-on boot to below the knee: no laces (the throat closed), a welt, the top hemmed,
        # a strap buckled round the ankle and one round the top (the concept sheet's apprentice mage)
        last.sole(p, mats, collection)
        last.upper(p, mats, collection, laced=False)
        tube("Welt", _ring(last, p, p["sole_thickness"] + .002, .0018), .0024, mats["leather"], collection, True)
        tube("Top_Roll", _ring(last, p, p["shaft_height"] - .004, .0012), .0030, mats["leather"], collection, True)
        ankle_strap(p, .092, mats, collection, "Ankle_Strap")
        ankle_strap(p, p["shaft_height"] - .035, mats, collection, "Top_Strap")
    elif style == "sandal":   # a sole and straps, the foot bare
        last.sole(p, mats, collection)

        def over(y0, w, h, name, z0=None):   # a strap over the foot across it at y0 (half width w, height h)
            zb = p["sole_thickness"] + .002 if z0 is None else z0

            def mapper(u, v):
                a = math.pi * u
                x, z = -w * math.cos(a), zb + h * math.sin(a)
                return (x, y0 + (v - .5) * .014, z)
            ribbon(name, mapper, mats["leather"], collection, 48, (), .0024)
        front, back, width = last.profile(p, .009)
        over(-front * .62, width * 1.02, .030, "Toe_Strap")
        over(-front * .22, width * 1.02, .055, "Instep_Strap")
        ankle_strap(p, .072, mats, collection, "Ankle_Strap")

        def heel(u, v):   # up the heel (along u) from the sole to the ankle strap, v across it
            z = p["sole_thickness"] + (0.072 - p["sole_thickness"]) * u
            q = last.last_point(p, math.pi + (v - .5) * .35, z)
            d = Vector((q.x, q.y, 0))
            q = q + d.normalized() * .002
            return (q.x, q.y, q.z)
        ribbon("Heel_Strap", heel, mats["leather"], collection, 12, (), .0024)
    else:
        raise ValueError(f"Unknown footwear: {style}")
