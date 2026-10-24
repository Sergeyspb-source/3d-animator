## Armour made in the armour mode «Броня» (blender_wear_fit.py) on a character in the game. The piece's GLB holds
## the character's skeleton and the pieces skinned to it; wear() moves every skinned mesh of it under the
## character's own Skeleton3D, so the piece follows every animation of the character, by bone names.
##
##     var bracers := SF3DEquip.wear($Goblin, preload("res://goblin_wear_bracer.glb"))   # put on
##     SF3DEquip.take_off(bracers)                                                      # take off
##
## The character and the piece must come from the same rigged model (the same skeleton, the same rest pose).
class_name SF3DEquip
extends RefCounted


static func skeleton_of(node: Node) -> Skeleton3D:
	if node is Skeleton3D:
		return node
	var found := node.find_children("*", "Skeleton3D", true, false)
	return found[0] if found.size() > 0 else null


## Puts the piece on the character: returns its meshes (now children of the character's Skeleton3D).
static func wear(character: Node, piece: PackedScene) -> Array[MeshInstance3D]:
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
		out.append(mi)
	inst.free()
	return out


static func take_off(meshes: Array) -> void:
	for mi in meshes:
		if is_instance_valid(mi):
			mi.queue_free()


static func _relative(from: Node, node: Node3D) -> Transform3D:   # node's transform in from's space, outside the tree
	var t := Transform3D.IDENTITY
	var n: Node = node
	while n != null and n != from:
		if n is Node3D:
			t = (n as Node3D).transform * t
		n = n.get_parent()
	return t
