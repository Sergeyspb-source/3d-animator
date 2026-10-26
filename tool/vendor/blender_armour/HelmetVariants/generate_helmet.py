"""Generate one of five medieval helmet prototypes in an isolated Blender process."""
import argparse
import importlib
import json
import math
import sys
from pathlib import Path
import bpy

HERE = Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/"KettleHat"))
sys.path.insert(0,str(HERE))
from kettle_hat_details import make_materials
from kettle_hat_review import review_and_export
from generate_kettle_hat import prepare_meshes

STYLES = {
    "open_bascinet":{"height":0.139,"peak_sweep":0.015,"neck_z":-0.095},
    "barbute":{"height":0.119,"peak_sweep":0.005,"neck_z":-0.110},
    "visored_bascinet":{"height":0.142,"peak_sweep":0.016,"neck_z":-0.055,
                        "visor_projection":0.060},
    "sallet":{"height":0.102,"peak_sweep":0.008,"neck_z":-0.088,
              "tail_length":0.085},
    "armet":{"height":0.109,"peak_sweep":0.002,"neck_z":-0.075,
             "visor_projection":0.039,"crest":0.002}
}
DEFAULTS = {"rx":0.100,"ry":0.118,"height":0.125,"brow_z":0.065,
            "neck_z":-0.095,"crest":0.003,"peak_sweep":0.012,"tail_length":0,
            "thickness":0.002,"segments":128,"crown_rings":24,
            "strap_width":0.015,"strap_drop":0.145,"visor_angle":0,
            "cheek_angle":0,"visor_projection":0.035}
BOUNDS = {"rx":(0.085,0.12),"ry":(0.10,0.14),"height":(0.09,0.18),
          "brow_z":(0.060,0.080),"neck_z":(-0.125,-0.035),"crest":(0,0.006),
          "peak_sweep":(0,0.025),"tail_length":(0,0.11),
          "thickness":(0.0015,0.0035),"segments":(64,160),"crown_rings":(16,36),
          "strap_width":(0.012,0.022),"strap_drop":(0.135,0.18),
          "visor_angle":(0,65),"cheek_angle":(0,35),"visor_projection":(0.025,0.075)}

# //#GPT: Reject unsupported names and non-finite or excessive geometry parameters.
def validate_config(kind,config):
    if kind not in STYLES:
        raise ValueError(f"Unknown helmet: {kind}")
    if not isinstance(config,dict) or set(config)-set(DEFAULTS):
        raise ValueError("Configuration must contain only documented parameters")
    p = {**DEFAULTS,**STYLES[kind],**config}
    for key,value in p.items():
        low,high = BOUNDS[key]
        if isinstance(value,bool) or not isinstance(value,(int,float)):
            raise ValueError(f"Invalid numeric type: {key}")
        if not math.isfinite(value) or not low<=value<=high:
            raise ValueError(f"Parameter outside supported range: {key}")
    if not isinstance(p["segments"],int) or p["segments"]%8:
        raise ValueError("segments must be an integer multiple of 8")
    if not isinstance(p["crown_rings"],int):
        raise ValueError("crown_rings must be an integer")
    if p["strap_drop"]<abs(p["neck_z"])+0.015:
        raise ValueError("Chinstrap must extend below the shell")
    if kind!="sallet" and p["tail_length"]!=0:
        raise ValueError("tail_length applies to sallet only")
    if kind not in {"armet","visored_bascinet"} and p["visor_angle"]!=0:
        raise ValueError("This helmet has no visor")
    if kind!="armet" and p["cheek_angle"]!=0:
        raise ValueError("Only armet has hinged cheek plates")
    return p

# //#GPT: Build only the requested construction and retain the movable part hierarchy.
def build(kind,p,texture_dir):
    collection = bpy.data.collections.new(f"{kind}_Model")
    bpy.context.scene.collection.children.link(collection)
    root = bpy.data.objects.new(kind,None)
    collection.objects.link(root)
    mats = make_materials(texture_dir)
    print("MATERIALS_READY",flush=True)
    importlib.import_module(kind).build(p,mats,collection)
    print("CONSTRUCTION_READY",flush=True)
    geometry = [o for o in collection.objects if o.type in {"MESH","CURVE"}]
    prepare_meshes([o for o in geometry if o.name!="Aventail_Rings"])
    print("MESH_PREPARATION_READY",flush=True)
    for obj in collection.objects:
        if obj!=root and obj.parent is None:
            obj.parent = root
    root["units"],root["front_blender"] = "metres","-Y"
    root["prototype"] = True
    root["construction"] = kind
    root["articulation"] = "Editable pivots; collision-free movement not certified"
    bpy.context.view_layer.update()
    return root,[o for o in collection.objects if o.type=="MESH"]

# //#GPT: Preserve existing outputs and avoid touching the user's interactive scene.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind",choices=STYLES,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--config",type=Path)
    parser.add_argument("--reference",type=Path)
    parser.add_argument("--skip-render",action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
    args.out = args.out.resolve()
    if not bpy.app.background:
        raise RuntimeError("Use Blender --background in a separate process")
    config = json.loads(args.config.read_text(encoding="utf-8")) if args.config else {}
    p = validate_config(args.kind,config)
    if any((args.out/f"{args.kind}.{ext}").exists() for ext in ("blend","glb")):
        raise FileExistsError("Choose a new --out directory; assets will not be overwritten")
    args.out.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.context.scene.unit_settings.system = "METRIC"
    print("HELMET_BUILD_START",args.kind,flush=True)
    root,objects = build(args.kind,p,args.out/"textures")
    (args.out/"parameters.json").write_text(json.dumps(p,indent=2),encoding="utf-8")
    review_and_export(root,objects,args.out,args.reference,not args.skip_render,stem=args.kind)
    print("HELMET_BUILD_OK",args.kind,flush=True)

if __name__=="__main__":
    main()
