"""Generate six handed footwear prototypes in isolated background Blender."""
import argparse
import json
import sys
from pathlib import Path
import bpy

HERE = Path(__file__).resolve().parent
for folder in ("KettleHat","HelmetVariants","ElbowArmor"):
    sys.path.insert(0,str(HERE.parent/folder))
sys.path.insert(0,str(HERE))
from kettle_hat_details import make_materials
from generate_kettle_hat import prepare_meshes
from footwear_catalog import VARIANTS,validate_config
from footwear_builders import build
from footwear_pair import canonical_meshes,mirrored_pair
from footwear_export import export_side,render_single,save_pair

# //#GPT: Preserve earlier outputs and avoid modifying the user's interactive Blender scene.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind",choices=VARIANTS,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--config",type=Path)
    parser.add_argument("--skip-render",action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
    if not bpy.app.background:
        raise RuntimeError("Run in a separate Blender --background process")
    output = args.out.resolve()
    config = json.loads(args.config.read_text(encoding="utf-8")) if args.config else {}
    p = validate_config(args.kind,config)
    protected = (f"{args.kind}.blend",f"{args.kind}_right.glb",f"{args.kind}_left.glb")
    if any((output/name).exists() for name in protected):
        raise FileExistsError("Use a new --out directory; existing assets are preserved")
    output.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.context.scene.unit_settings.system = "METRIC"
    collection = bpy.data.collections.new("Footwear_Model")
    bpy.context.scene.collection.children.link(collection)
    print("FOOTWEAR_BUILD_START",args.kind,flush=True)
    mats = make_materials(output/"textures")
    build(args.kind,p,mats,collection)
    geometry = [o for o in collection.objects if o.type in {"MESH","CURVE"}]
    prepare_meshes([o for o in geometry if o.name!="FootMail_Rings"])
    right = [o for o in collection.objects if o.type=="MESH"]
    canonical_meshes(right,p)
    right_root,left_root,left = mirrored_pair(right,collection,p)
    (output/"parameters.json").write_text(json.dumps(p,indent=2),encoding="utf-8")
    (output/"asset.json").write_text(json.dumps({"kind":args.kind,"sides":["left","right"],
        "units":"metres","origin":"ankle joint centre","ground_z":-p["ankle_height"],
        "pose":"static unrigged prototype"},indent=2),encoding="utf-8")
    export_side(right_root,right,output,args.kind+"_right")
    export_side(left_root,left,output,args.kind+"_left")
    render_single(right,left,output,not args.skip_render)
    save_pair(right_root,left_root,right,left,output,args.kind,not args.skip_render)
    print("FOOTWEAR_BUILD_OK",args.kind,flush=True)

if __name__=="__main__":
    main()
