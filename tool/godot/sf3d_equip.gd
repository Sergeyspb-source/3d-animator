## Armour made in the armour mode «Броня» (blender_wear_fit.py) on a character in the game. The piece's GLB holds
## the character's skeleton and the pieces skinned to it; wear() moves every skinned mesh of it under the
## character's own Skeleton3D, so the piece follows every animation of the character, by bone names.
##
##     var bracers := SF3DEquip.wear($Goblin, preload("res://goblin_wear_bracer.glb"))   # put on
##     SF3DEquip.take_off(bracers)                                                      # take off
##     SF3DEquip.show(bracers, false)                                                   # hidden for a while
##
## The character and the piece must come from the same rigged model (the same skeleton, the same rest pose).
## What of the body a piece hides (<piece>.mask.json next to its GLB, made with it: tool/body_mask.py) is taken away
## while the piece is on and shown: the skin under it (it would poke through in motion), cords and ears sticking out.
class_name SF3DEquip
extends RefCounted


static func skeleton_of(node: Node) -> Skeleton3D:
	if node is Skeleton3D:
		return node
	var found := node.find_children("*", "Skeleton3D", true, false)
	return found[0] if found.size() > 0 else null


## Puts the piece on the character: returns its meshes (now children of the character's Skeleton3D).
## mask: the body it hides (default: <piece>.mask.json beside the piece's file).
static func wear(character: Node, piece: PackedScene, mask := "") -> Array[MeshInstance3D]:
	var out: Array[MeshInstance3D] = []
	var skel := skeleton_of(character)
	if skel == null or piece == null:
		push_warning("SF3DEquip: no skeleton under %s, or no piece" % character)
		return out
	var inst := piece.instantiate()
	var own := skeleton_of(inst)
	for node in inst.find_children("*", "MeshInstance3D", true, false):
		var mi := node as MeshInstance3D
		if mi.skin == null:
			continue
		var rel := _relative(own if own else inst, mi)   # where it sat on its own skeleton
		mi.get_parent().remove_child(mi)
		mi.owner = null
		skel.add_child(mi)
		mi.transform = rel
		mi.skeleton = NodePath("..")
		mi.set_meta("sf3d_piece", true)
		out.append(mi)
	inst.free()
	if out.size() > 0:
		var path := mask if mask != "" else piece.resource_path.get_basename() + ".mask.json"
		var keys := _mask_keys(path)
		if not keys.is_empty():
			out[0].set_meta("sf3d_mask", keys)
			out[0].set_meta("sf3d_character", character)
			_hide_body(character)
	return out


static func take_off(meshes: Array) -> void:
	var character: Node = null
	for mi in meshes:
		if is_instance_valid(mi):
			if mi.has_meta("sf3d_character"):
				character = mi.get_meta("sf3d_character")
			mi.get_parent().remove_child(mi)
			mi.queue_free()
	if character:
		_hide_body(character)


## Shows or hides a piece put on (the body under it comes back while it is hidden).
static func show(meshes: Array, on: bool) -> void:
	var character: Node = null
	for mi in meshes:
		if is_instance_valid(mi):
			mi.visible = on
			if mi.has_meta("sf3d_character"):
				character = mi.get_meta("sf3d_character")
	if character:
		_hide_body(character)


## A position in a mask (thousandths of a unit), the next thousandth too where a coordinate is near the cells' edge
## (Blender's import moves vertices by ~1e-5).
static func _in_mask(hide: Dictionary, v: Vector3) -> bool:
	var opts := []
	for c in [v.x, v.y, v.z]:
		var q: float = c * 1000.0
		var r := roundi(q)
		var f := q - r
		opts.append([r, r + (1 if f > 0 else -1)] if absf(f) > 0.3 else [r])
	for a in opts[0]:
		for b in opts[1]:
			for c in opts[2]:
				if hide.has(Vector3i(a, b, c)):
					return true
	return false


static func _mask_keys(path: String) -> Dictionary:
	var keys := {}
	if not FileAccess.file_exists(path):
		return keys
	var data = JSON.parse_string(FileAccess.get_file_as_string(path))
	if data is Array:
		for p in data:
			keys[Vector3i(int(p[0]), int(p[1]), int(p[2]))] = true
	return keys


## The body's meshes without the triangles whose three corners every shown piece's mask hides (the full mesh is kept
## aside, so pieces can come off again).
static func _hide_body(character: Node) -> void:
	var skel := skeleton_of(character)
	if skel == null:
		return
	var hide := {}
	for node in skel.get_children():
		if node is MeshInstance3D and node.has_meta("sf3d_mask") and node.visible:
			hide.merge(node.get_meta("sf3d_mask"))
	for node in character.find_children("*", "MeshInstance3D", true, false):
		var mi := node as MeshInstance3D
		if mi.has_meta("sf3d_piece") or mi.mesh == null:
			continue
		if not mi.has_meta("sf3d_body_mesh"):
			mi.set_meta("sf3d_body_mesh", mi.mesh)
		var full: Mesh = mi.get_meta("sf3d_body_mesh")
		if hide.is_empty():
			mi.mesh = full
			continue
		var am := ArrayMesh.new()
		for b in full.get_blend_shape_count():
			am.add_blend_shape(full.get_blend_shape_name(b))
		if full is ArrayMesh:
			am.blend_shape_mode = (full as ArrayMesh).blend_shape_mode
		var taken := 0
		for s in full.get_surface_count():
			var arrays := full.surface_get_arrays(s)
			var verts: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
			var idx = arrays[Mesh.ARRAY_INDEX]
			if idx == null or (idx as PackedInt32Array).is_empty():
				idx = PackedInt32Array(range(verts.size()))
			var hid := PackedByteArray()
			hid.resize(verts.size())
			for i in verts.size():
				hid[i] = 1 if _in_mask(hide, verts[i]) else 0
			var keep := PackedInt32Array()
			for t in range(0, idx.size(), 3):
				if hid[idx[t]] and hid[idx[t + 1]] and hid[idx[t + 2]]:
					taken += 1
					continue
				keep.append(idx[t]); keep.append(idx[t + 1]); keep.append(idx[t + 2])
			arrays[Mesh.ARRAY_INDEX] = keep
			am.add_surface_from_arrays(full.surface_get_primitive_type(s), arrays, full.surface_get_blend_shape_arrays(s))
			am.surface_set_material(s, full.surface_get_material(s))
		mi.mesh = am if taken > 0 else full


static func _relative(from: Node, node: Node3D) -> Transform3D:   # node's transform in from's space, outside the tree
	var t := Transform3D.IDENTITY
	var n: Node = node
	while n != null and n != from:
		if n is Node3D:
			t = (n as Node3D).transform * t
		n = n.get_parent()
	return t
