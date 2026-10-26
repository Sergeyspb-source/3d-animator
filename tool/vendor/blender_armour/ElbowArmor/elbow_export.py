"""Canonical left/right exports and a separate presentation scene with both elbows."""
import json
import bpy
from mathutils import Vector
from kettle_hat_review import mesh_report,validate_glb,studio

# //#GPT: Export one zero-centred elbow at a time, with no studio or partner geometry.
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
    print("ELBOW_EXPORT_OK",stem,report["triangles"],flush=True)
    return report

# //#GPT: Show the outer cup and the fastening side with consistent orthographic framing.
def render_single(right,left,output,render):
    for obj in left:
        obj.hide_render = True
    center = studio(right)
    camera = bpy.context.scene.camera
    views = {"front":(0,-1,0.07),"side":(1,0.10,0.08),"back":(0,1,0.07),
             "hero":(0.85,-1,0.65),"inside":(-0.4,1,0.65)}
    directory = output/"renders"
    directory.mkdir(exist_ok=True)
    if render:
        for name,direction in views.items():
            camera.location = center+Vector(direction).normalized()*1.3
            camera.rotation_euler = (center-camera.location).to_track_quat("-Z","Y").to_euler()
            bpy.context.scene.render.filepath = str(directory/f"{name}.png")
            bpy.ops.render.render(write_still=True)
            print("ELBOW_RENDER_OK",name,flush=True)
    for obj in left:
        obj.hide_render = False

# //#GPT: Store a spaced pair for editing without changing the canonical exported socket origins.
def save_pair(right_root,left_root,right,left,output,kind,render):
    extent = max(abs(v.co.x) for o in right for v in o.data.vertices)
    right_root.location.x = -extent-0.020
    left_root.location.x = extent+0.020
    bpy.context.view_layer.update()
    objects = right+left
    points = [o.matrix_world@Vector(c) for o in objects for c in o.bound_box]
    low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    center = (low+high)/2
    camera = bpy.context.scene.camera
    camera.data.ortho_scale = max(high-low)*1.25
    camera.location = center+Vector((0.25,-1,0.45)).normalized()*1.3
    camera.rotation_euler = (center-camera.location).to_track_quat("-Z","Y").to_euler()
    if render:
        bpy.context.scene.render.filepath = str(output/"renders/pair.png")
        bpy.ops.render.render(write_still=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output/f"{kind}.blend"))
