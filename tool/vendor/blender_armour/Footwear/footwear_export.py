"""Individual portable exports, six views and an editable paired presentation."""
import json
import bpy
from mathutils import Vector
from kettle_hat_review import mesh_report,validate_glb,studio

# //#GPT: Export one anatomical side at its canonical ankle origin, excluding the review studio.
def export_side(root,objects,output,stem):
    bpy.context.view_layer.update()
    report = mesh_report(objects)
    for obj in bpy.context.scene.objects:
        obj.select_set(False)
    for obj in [root,*root.children_recursive]:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = root
    path = output/f"{stem}.glb"
    bpy.ops.export_scene.gltf(filepath=str(path),export_format="GLB",use_selection=True,
                             export_apply=True,export_extras=True,export_cameras=False,
                             export_lights=False,export_materials="EXPORT")
    report["glb"] = validate_glb(path,len(objects))
    report["blender_version"] = bpy.app.version_string
    (output/f"validation_{stem.rsplit('_',1)[-1]}.json").write_text(
        json.dumps(report,indent=2),encoding="utf-8")
    print("FOOTWEAR_EXPORT_OK",stem,report["triangles"],flush=True)

# //#GPT: Include the walking sole and the open shaft, rather than hiding those surfaces.
def render_single(right,left,output,render):
    for obj in left:
        obj.hide_render = True
    center = studio(right)
    camera = bpy.context.scene.camera
    views = {"front":(0,-1,0.18),"side":(1,0,0.08),"back":(0,1,0.18),
             "hero":(0.85,-1,0.70),"sole":(0,-0.10,-1),"top":(0,-0.10,1)}
    directory = output/"renders"
    directory.mkdir(exist_ok=True)
    if render:
        for name,direction in views.items():
            camera.location = center+Vector(direction).normalized()*1.3
            camera.rotation_euler = (center-camera.location).to_track_quat("-Z","Y").to_euler()
            bpy.context.scene.render.filepath = str(directory/f"{name}.png")
            bpy.ops.render.render(write_still=True)
            print("FOOTWEAR_RENDER_OK",name,flush=True)
    for obj in left:
        obj.hide_render = False

# //#GPT: Space the pair only in the saved BLEND; separate GLBs remain ready for placement.
def save_pair(right_root,left_root,right,left,output,kind,render):
    extent = max(abs(v.co.x) for o in right for v in o.data.vertices)
    right_root.location.x,left_root.location.x = -extent-0.020,extent+0.020
    bpy.context.view_layer.update()
    points = [o.matrix_world@Vector(c) for o in right+left for c in o.bound_box]
    low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    center = (low+high)/2
    camera = bpy.context.scene.camera
    camera.data.ortho_scale = max(high-low)*1.35
    camera.location = center+Vector((0.75,-1,0.75)).normalized()*1.3
    camera.rotation_euler = (center-camera.location).to_track_quat("-Z","Y").to_euler()
    if render:
        bpy.context.scene.render.filepath = str(output/"renders/pair.png")
        bpy.ops.render.render(write_still=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output/f"{kind}.blend"))
