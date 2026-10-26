"""Build a matched pair of modular medieval elbow armour in isolated background Blender."""
import argparse
import json
import sys
from pathlib import Path
import bmesh
import bpy
from mathutils import Matrix

HERE = Path(__file__).resolve().parent
for folder in ("KettleHat","HelmetVariants"):
    sys.path.insert(0,str(HERE.parent/folder))
sys.path.insert(0,str(HERE))
from kettle_hat_details import make_materials
from generate_kettle_hat import prepare_meshes
from elbow_catalog import VARIANTS,validate_config
from elbow_builders import build
from elbow_export import export_side,render_single,save_pair

# //#GPT: Bake primitive transforms before mirroring so both sides keep positive unit transforms.
def canonical_meshes(objects):
    bpy.context.view_layer.update()
    for obj in objects:
        world = obj.matrix_world.copy()
        for vertex in obj.data.vertices:
            vertex.co = world@vertex.co
        obj.matrix_world = Matrix.Identity(4)
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()

# //#GPT: Mirror actual coordinates and winding, keeping the anatomical pivot at the joint centre.
def mirrored_pair(objects,collection,p):
    right_root = bpy.data.objects.new("Elbow_Right",None)
    left_root = bpy.data.objects.new("Elbow_Left",None)
    collection.objects.link(right_root)
    collection.objects.link(left_root)
    left = []
    for obj in objects:
        base = obj.name
        obj.name = "R_"+base
        obj.parent = right_root
        clone = obj.copy()
        clone.data = obj.data.copy()
        clone.name = "L_"+base
        collection.objects.link(clone)
        for vertex in clone.data.vertices:
            vertex.co.x *= -1
        bm = bmesh.new()
        bm.from_mesh(clone.data)
        bmesh.ops.reverse_faces(bm,faces=list(bm.faces))
        bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
        bm.to_mesh(clone.data)
        bm.free()
        clone.parent = left_root
        clone.data.update()
        left.append(clone)
    for root,side in ((right_root,"right"),(left_root,"left")):
        root["side"],root["units"],root["prototype"] = side,"metres",True
        root["outer_direction"],root["arm_axis"] = "-Y","+Z"
        root["anatomical_origin"] = "Elbow joint centre"
        for name,sign in (("Upper_Attach",1),("Lower_Attach",-1)):
            socket = bpy.data.objects.new(f"{name}_{side}",None)
            collection.objects.link(socket)
            socket.parent = root
            socket.location.z = sign*(p["half_height"]+0.030)
    return right_root,left_root,left

# //#GPT: Preserve existing assets and produce canonical side exports plus an editable spaced pair.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind",choices=VARIANTS,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--config",type=Path)
    parser.add_argument("--skip-render",action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
    if not bpy.app.background:
        raise RuntimeError("Use a separate Blender --background process")
    output = args.out.resolve()
    config = json.loads(args.config.read_text(encoding="utf-8")) if args.config else {}
    p = validate_config(args.kind,config)
    protected = (f"{args.kind}.blend",f"{args.kind}_left.glb",f"{args.kind}_right.glb")
    if any((output/name).exists() for name in protected):
        raise FileExistsError("Use a new --out directory; existing assets are preserved")
    output.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.context.scene.unit_settings.system = "METRIC"
    collection = bpy.data.collections.new("Elbow_Armour")
    bpy.context.scene.collection.children.link(collection)
    print("ELBOW_BUILD_START",args.kind,flush=True)
    mats = make_materials(output/"textures")
    build(args.kind,p,mats,collection)
    geometry = [o for o in collection.objects if o.type in {"MESH","CURVE"}]
    prepare_meshes([o for o in geometry if o.name!="Mail_Rings"])
    right = [o for o in collection.objects if o.type=="MESH"]
    canonical_meshes(right)
    right_root,left_root,left = mirrored_pair(right,collection,p)
    (output/"parameters.json").write_text(json.dumps(p,indent=2),encoding="utf-8")
    (output/"asset.json").write_text(json.dumps({"kind":args.kind,"sides":["left","right"],
        "units":"metres","origin":"joint centre","pose":"straight static prototype"},indent=2),encoding="utf-8")
    export_side(right_root,right,output,args.kind+"_right")
    export_side(left_root,left,output,args.kind+"_left")
    render_single(right,left,output,not args.skip_render)
    save_pair(right_root,left_root,right,left,output,args.kind,not args.skip_render)
    print("ELBOW_BUILD_OK",args.kind,flush=True)

if __name__=="__main__":
    main()
