"""Runs INSIDE Blender: the procedural material of the editor's look (blender_armour_gen.py's pieces, and the pieces the
vendor generators make when another material is chosen for them: blender_texbake.bake_made)."""
from pathlib import Path

import bpy


def node_mat(name, spec, R, job, pattern=None, unit=1.0):
    """A procedural material for the bake from the editor's spec {kind: metal|leather (cloth too), col, spot (rust, patina
    or scuffs), rough, metal, pattern}; pattern: an image (red: height, green: how much light gets in) laid by the UV map
    «pattern» (mail rings, quilting), unit: its tile's size. Returns (material, metallic)."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for nd in list(nt.nodes):
        nt.nodes.remove(nd)
    N, L = nt.nodes.new, nt.links.new
    out = N("ShaderNodeOutputMaterial")
    bsdf = N("ShaderNodeBsdfPrincipled")
    L(bsdf.outputs[0], out.inputs[0])
    tc = N("ShaderNodeTexCoord")
    mp = N("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (1 / R, 1 / R, 1 / R)
    seed = int(job.get("seed", 1))   # another variant: the noise from elsewhere
    mp.inputs["Location"].default_value = (seed * 3.17, seed * 1.93, seed * 2.41)
    L(tc.outputs["Object"], mp.inputs[0])
    wear = float(job.get("wear", .35))
    kind, col, rough, metal, spot = spec["kind"], tuple(spec["col"]), float(spec["rough"]), float(spec["metal"]), tuple(spec["spot"])
    # large blotches, fine grain, rust or scuffs
    big = N("ShaderNodeTexNoise"); big.inputs["Scale"].default_value = 1.5; big.inputs["Detail"].default_value = 6
    fine = N("ShaderNodeTexNoise"); fine.inputs["Scale"].default_value = 14; fine.inputs["Detail"].default_value = 8
    vor = N("ShaderNodeTexVoronoi"); vor.inputs["Scale"].default_value = 9 if kind == "metal" else 28
    for t in (big, fine, vor):
        L(mp.outputs[0], t.inputs[0])
    dark = tuple(c * (.38 if kind == "metal" else .55) for c in col)   # dirt and tarnish
    mix1 = N("ShaderNodeMix"); mix1.data_type = "RGBA"
    mix1.inputs[6].default_value = (*col, 1); mix1.inputs[7].default_value = (*dark, 1)
    L(big.outputs["Fac"], mix1.inputs[0])
    tex = spec.get("tex") or None   # a library material (matlib: ambientCG, Poly Haven): its maps, a sample of «tile» on a side
    timg = {}
    if tex and tex.get("color") and Path(tex["color"]).exists():
        tco = N("ShaderNodeTexCoord"); tmp = N("ShaderNodeMapping")
        tile = max(1e-4, float(tex.get("tile") or R))
        tmp.inputs["Scale"].default_value = (1 / tile, 1 / tile, 1 / tile)
        L(tco.outputs["Object"], tmp.inputs[0])
        for key in ("color", "normal", "rough", "metal"):
            if tex.get(key) and Path(tex[key]).exists():
                t = N("ShaderNodeTexImage"); t.image = bpy.data.images.load(tex[key], check_existing=True)
                t.image.colorspace_settings.name = "sRGB" if key == "color" else "Non-Color"
                t.projection = "BOX"; t.projection_blend = .3; t.extension = "REPEAT"
                L(tmp.outputs[0], t.inputs[0]); timg[key] = t
        # its colour under the same dirt and wear as the procedural one: the colour, and darker where dirty
        dk = N("ShaderNodeMix"); dk.data_type = "RGBA"; dk.blend_type = "MULTIPLY"; dk.inputs[0].default_value = 1.0
        dk.inputs[7].default_value = (.55, .55, .55, 1) if kind != "metal" else (.4, .4, .4, 1)
        L(timg["color"].outputs[0], dk.inputs[6])
        L(timg["color"].outputs[0], mix1.inputs[6]); L(dk.outputs[2], mix1.inputs[7])
    # rust (metal) or worn light scuffs (leather), where the large noise passes a threshold set by the wear
    ramp = N("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = max(.0, .72 - .35 * wear)
    ramp.color_ramp.elements[1].position = min(1.0, ramp.color_ramp.elements[0].position + .08)
    L(fine.outputs["Fac"], ramp.inputs[0])
    mix2 = N("ShaderNodeMix"); mix2.data_type = "RGBA"
    mix2.inputs[7].default_value = (*spot, 1)
    if "color" in timg:   # a library material's scuffs: its own colour, lighter (not the procedural one's rust or tint)
        lt = N("ShaderNodeMix"); lt.data_type = "RGBA"; lt.blend_type = "SCREEN"; lt.inputs[0].default_value = 1.0
        lt.inputs[7].default_value = (.3, .28, .25, 1) if kind != "metal" else (.45, .45, .45, 1)
        L(timg["color"].outputs[0], lt.inputs[6]); L(lt.outputs[2], mix2.inputs[7])
    L(mix1.outputs[2], mix2.inputs[6])
    L(ramp.outputs[0], mix2.inputs[0])
    # worn edges: bright metal where the surface is convex (Cycles' pointiness)
    geo = N("ShaderNodeNewGeometry")
    edge = N("ShaderNodeValToRGB")
    edge.color_ramp.elements[0].position = .52
    edge.color_ramp.elements[1].position = .62
    L(geo.outputs["Pointiness"], edge.inputs[0])
    edgef = N("ShaderNodeMath"); edgef.operation = "MULTIPLY"; edgef.inputs[1].default_value = wear * (1.0 if kind == "metal" else .5)
    L(edge.outputs[0], edgef.inputs[0])
    mix3 = N("ShaderNodeMix"); mix3.data_type = "RGBA"
    hi = tuple(min(1, c * 1.9 + .08) for c in col)
    mix3.inputs[7].default_value = (*hi, 1)
    L(mix2.outputs[2], mix3.inputs[6]); L(edgef.outputs[0], mix3.inputs[0])
    colour = mix3.outputs[2]
    if pattern is not None:   # the gaps between the rings, the sunk seams darker
        uvm = N("ShaderNodeUVMap"); uvm.uv_map = "pattern"
        img = N("ShaderNodeTexImage"); img.image = pattern; img.extension = "REPEAT"
        L(uvm.outputs[0], img.inputs[0])
        sep = N("ShaderNodeSeparateColor"); L(img.outputs[0], sep.inputs[0])
        mul = N("ShaderNodeMix"); mul.data_type = "RGBA"; mul.blend_type = "MULTIPLY"; mul.inputs[0].default_value = 1.0
        L(colour, mul.inputs[6]); L(sep.outputs[1], mul.inputs[7])
        colour = mul.outputs[2]
    L(colour, bsdf.inputs["Base Color"])
    rr = N("ShaderNodeMapRange")
    rr.inputs[3].default_value = max(.05, rough - .12); rr.inputs[4].default_value = min(1, rough + .2)
    L(ramp.outputs[0], rr.inputs[0])
    L(rr.outputs[0], bsdf.inputs["Roughness"])
    bsdf.inputs["Metallic"].default_value = metal
    if "rough" in timg:   # the library's roughness (a little more where worn)
        ad = N("ShaderNodeMath"); ad.operation = "ADD"; ad.use_clamp = True
        sc = N("ShaderNodeMath"); sc.operation = "MULTIPLY"; sc.inputs[1].default_value = .15
        L(ramp.outputs[0], sc.inputs[0]); L(timg["rough"].outputs[0], ad.inputs[0]); L(sc.outputs[0], ad.inputs[1])
        L(ad.outputs[0], bsdf.inputs["Roughness"])
    if "metal" in timg:
        L(timg["metal"].outputs[0], bsdf.inputs["Metallic"])
    bump = N("ShaderNodeBump")   # hammered (as much as «hammer» says; 0 polished) / grain
    bump.inputs["Strength"].default_value = 1.2 * float(spec.get("bump", .5)) if kind == "metal" else .55
    bump.inputs["Distance"].default_value = .02 * R
    L(vor.outputs["Distance"], bump.inputs["Height"])
    normal = bump.outputs[0]
    if "color" in timg:   # the library's relief instead of the grain: a bump from its colour's lightness (its normal map,
        # box-projected, would be turned against the bake's own UVs' tangents; a bump is right whichever way it lies)
        bw = N("ShaderNodeRGBToBW"); L(timg["color"].outputs[0], bw.inputs[0])
        tb = N("ShaderNodeBump"); tb.inputs["Strength"].default_value = .45; tb.inputs["Distance"].default_value = .004 * float(tex.get("tile") or R)
        L(bw.outputs[0], tb.inputs["Height"])
        normal = tb.outputs[0]
    if pattern is not None:   # the rings' or the quilting's own relief over it
        b2 = N("ShaderNodeBump"); b2.inputs["Strength"].default_value = .9; b2.inputs["Distance"].default_value = .04 * unit
        L(sep.outputs[0], b2.inputs["Height"]); L(normal, b2.inputs["Normal"])
        normal = b2.outputs[0]
    L(normal, bsdf.inputs["Normal"])
    return m, metal
