"""Blender boundary for optional RWT: extract original data or apply verified weights to a new copy."""
import bpy,sys,json,hashlib,struct
from pathlib import Path
import numpy as np


def geometry_hash(obj):
    h=hashlib.sha256()
    h.update(np.array([v.co[:] for v in obj.data.vertices],dtype=np.float32).tobytes())
    h.update(np.array([i for p in obj.data.polygons for i in p.vertices],dtype=np.int32).tobytes())
    for uv in obj.data.uv_layers: h.update(np.array([p.uv[:] for p in uv.data],dtype=np.float32).tobytes())
    return h.hexdigest()


# GPT: Open only an isolated process copy, with embedded scripts disabled; choose the actual skinned body rather than a bone widget.
def load_source(options):
    src=Path(options['source'])
    if src.suffix.lower()=='.blend': bpy.ops.wm.open_mainfile(filepath=str(src),load_ui=False,use_scripts=False)
    elif src.suffix.lower()=='.glb':
        bpy.ops.wm.read_homefile(use_empty=True);bpy.ops.import_scene.gltf(filepath=str(src))
    else: raise ValueError('Expected .glb or .blend')
    scene=bpy.context.scene;scene.frame_set(scene.frame_start);bpy.context.view_layer.update()
    candidates=[o for o in scene.objects if o.type=='MESH' and any(m.type=='ARMATURE' and m.object for m in o.modifiers)]
    if not candidates: raise ValueError('No skinned mesh with an armature')
    if options['mesh']:
        matches=[o for o in candidates if o.name==options['mesh']]
        if len(matches)!=1: raise ValueError('Mesh not found. Available: '+', '.join(o.name for o in candidates))
        body=matches[0]
    else:
        def rank(obj):
            ids={g.index for g in obj.vertex_groups if any(f in g.name.lower() for f in ['thumb','index','middle','ring','pinky'])}
            return sum(any(g.group in ids and g.weight>0 for g in v.groups) for v in obj.data.vertices),len(obj.data.vertices)
        body=max(candidates,key=rank)
    mods=[m for m in body.modifiers if m.type=='ARMATURE' and m.object]
    if len(mods)!=1: raise ValueError('Expected a single armature modifier on the selected mesh')
    return body,mods[0].object


def extract(options,body,rig):
    names=[b.name for b in rig.data.bones];index={n:i for i,n in enumerate(names)}
    old=np.zeros((len(body.data.vertices),len(names)),dtype=np.float32)
    for v in body.data.vertices:
        for g in v.groups:
            name=body.vertex_groups[g.group].name
            if name in index: old[v.index,index[name]]=g.weight
    mask=np.zeros(len(old),dtype=bool)
    if options['group']:
        group=body.vertex_groups.get(options['group'])
        if group is None: raise ValueError('Mask vertex group not found: '+options['group'])
        mask=np.array([any(g.group==group.index and g.weight>.5 for g in v.groups) for v in body.data.vertices])
    body.data.calc_loop_triangles();work=Path(options['work'])
    np.savez_compressed(work/'input.npz',vertices=np.array([tuple(body.matrix_world@v.co) for v in body.data.vertices],dtype=np.float32),faces=np.array([tuple(t.vertices) for t in body.data.loop_triangles]),skin=old,names=np.array(names,dtype=str),joints=np.array([tuple(rig.matrix_world@b.head_local) for b in rig.data.bones]),tails=np.array([tuple(rig.matrix_world@b.tail_local) for b in rig.data.bones]),mask=mask)
    info={'mesh':body.name,'rig':rig.name,'bones':names,'parents':[b.parent.name if b.parent else None for b in rig.data.bones],'geometry_uv_sha256':geometry_hash(body),'actions':[a.name for a in bpy.data.actions]}
    (work/'extract.json').write_text(json.dumps(info,indent=2),encoding='utf-8')


# GPT: Verify outside/finger invariants before exporting up to eight influences, keeping every source action and the shared rig.
def apply(options,body,rig):
    work=Path(options['work']);out=Path(options['output']);source=np.load(work/'input.npz',allow_pickle=False);data=np.load(work/'weights.npz',allow_pickle=False)
    meta=json.loads((work/'extract.json').read_text(encoding='utf-8'));names=list(source['names']);roi=data['roi'];weights=data['weights']
    assert body.name==meta['mesh'] and [b.name for b in rig.data.bones]==names
    assert [b.parent.name if b.parent else None for b in rig.data.bones]==meta['parents']
    assert geometry_hash(body)==meta['geometry_uv_sha256']
    for i in np.where(roi)[0]:
        for j,name in enumerate(names):
            group=body.vertex_groups.get(name)
            if group is None: group=body.vertex_groups.new(name=name)
            if weights[i,j]>0: group.add([int(i)],float(weights[i,j]),'REPLACE')
            else: group.remove([int(i)])
    actual=np.zeros_like(weights);index={n:i for i,n in enumerate(names)}
    for v in body.data.vertices:
        for g in v.groups:
            name=body.vertex_groups[g.group].name
            if name in index: actual[v.index,index[name]]=g.weight
    finger=np.array([any(f in n.lower() for f in ['thumb','index','middle','ring','pinky']) for n in names])
    assert np.array_equal(actual[~roi],source['skin'][~roi])
    assert np.array_equal(actual[:,finger],source['skin'][:,finger])
    assert np.max(np.abs(actual-weights))<1e-7 and geometry_hash(body)==meta['geometry_uv_sha256']
    assert [a.name for a in bpy.data.actions]==meta['actions']
    out.mkdir(parents=True,exist_ok=True);bpy.ops.wm.save_as_mainfile(filepath=str(out/'review.blend'))
    widgets={b.custom_shape for b in rig.pose.bones if b.custom_shape}
    bpy.ops.object.select_all(action='DESELECT');rig.select_set(True)
    meshes=[]
    for obj in bpy.context.scene.objects:
        bound=obj.type=='MESH' and any(m.type=='ARMATURE' and m.object==rig for m in obj.modifiers)
        if obj.type=='MESH' and obj not in widgets and (bound or not obj.hide_render): obj.select_set(True);meshes.append(obj.name)
    bpy.context.view_layer.objects.active=rig
    bpy.ops.export_scene.gltf(filepath=str(out/'model.glb'),export_format='GLB',use_selection=True,use_active_scene=True,export_animations=True,export_animation_mode='ACTIONS',export_force_sampling=True,export_influence_nb=8,export_all_influences=False)
    binary=(out/'model.glb').read_bytes();n=struct.unpack_from('<I',binary,12)[0];doc=json.loads(binary[20:20+n])
    assert doc.get('skins') and any(len(s['joints'])==len(names) for s in doc['skins'])
    report=json.loads((work/'solve.json').read_text(encoding='utf-8'))
    report.update({'mesh':body.name,'bones':len(names),'finger_bones':int(finger.sum()),'geometry_uv_unchanged':True,'animations_unchanged_in_blend':True,'exported_animations':[a.get('name','') for a in doc.get('animations',[])],'exported_meshes':meshes,'source':options['source'],'source_sha256':options['source_sha256'],'blend':str(out/'review.blend'),'glb':str(out/'model.glb')})
    (out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print('RWT_APPLIED',json.dumps(report),flush=True)


if __name__=='__main__':
    args=sys.argv[sys.argv.index('--')+1:];mode=args[0];options=json.loads(Path(args[1]).read_text(encoding='utf-8'))
    assert hashlib.sha256(Path(options['source']).read_bytes()).hexdigest()==options['source_sha256'],'Source changed during operation'
    body,rig=load_source(options)
    if mode=='extract': extract(options,body,rig)
    elif mode=='apply': apply(options,body,rig)
    else: raise ValueError('Unknown RWT worker mode')