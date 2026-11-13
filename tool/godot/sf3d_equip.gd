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
	var cloth := _add_cloth_bones(own, skel) if own else []
	var home_grid := {}
	for node in inst.find_children("*", "MeshInstance3D", true, false):
		var mi := node as MeshInstance3D
		if mi.skin == null:
			continue
		if "__clothhome" in String(mi.name):   # a cloak's grid of places: read, not worn
			home_grid = _home_grid(mi, own, skel)
			if "__clothhome__o" in String(mi.name):   # (its cuts, belt, rules: blender_armour_gen.py)
				home_grid["opts"] = String(mi.name).get_slice("__clothhome__o", 1).get_slice("__", 0)
			continue
		var rel := _relative(own if own else inst, mi)   # where it sat on its own skeleton
		_rebind(mi, own, skel)
		mi.get_parent().remove_child(mi)
		mi.owner = null
		skel.add_child(mi)
		mi.transform = rel
		mi.skeleton = NodePath("..")
		mi.set_meta("sf3d_piece", true)
		out.append(mi)
		var nm := String(mi.name)
		if "__arrow_" in nm:   # a quiver's arrow: shown while it is left (arrows())
			mi.set_meta("sf3d_arrow", int(nm.get_slice("__arrow_", 1).get_slice("__", 0)))
		var hold := nm.get_slice("__hold_", 1).get_slice("__", 0) if "__hold_" in nm else ""
		if hold != "":   # a weapon: the hands holding it close round its grip
			mi.set_meta("sf3d_hold", hold)
			_grip(skel).hold(hold, true)
			var two := nm.get_slice("__two_", 1).get_slice("__", 0).split("_") if "__two_" in nm else PackedStringArray()
			if two.size() == 10:   # in both hands: the other one reaches its grip on the haft
				var nums := []
				for k in range(1, 10):
					nums.append(float(two[k]) / 1000.0)
				mi.set_meta("sf3d_two", two[0])
				mi.set_meta("sf3d_two_nums", nums)
				_grip(skel).two_hand(hold.substr(0, 1), two[0], nums, true)
			var gr := nm.get_slice("__grasp_", 1).get_slice("__", 0).split("_") if "__grasp_" in nm else PackedStringArray()
			if gr.size() == 15:   # the fingers round its grip by contact (the editor's magnet): both hands holding it
				var degs := []
				for g in gr:
					degs.append(float(g))
				_grip(skel).grasp(hold.substr(0, 1), degs, true)
				mi.set_meta("sf3d_grasp", hold.substr(0, 1) + (two[0] if two.size() == 10 else ""))
				mi.set_meta("sf3d_grasp_degs", degs)
				if two.size() == 10:
					_grip(skel).grasp(two[0], degs, true)
			var pt := nm.get_slice("__point_", 1).get_slice("__", 0).split("_") if "__point_" in nm else PackedStringArray()
			if pt.size() == 3:   # a spear: its head kept forward
				mi.set_meta("sf3d_point", hold.substr(0, 1))
				mi.set_meta("sf3d_point_v", Vector3(float(pt[0]), float(pt[1]), float(pt[2])) / 1000.0)
				_grip(skel).point(hold.substr(0, 1), Vector3(float(pt[0]), float(pt[1]), float(pt[2])) / 1000.0, true)
	inst.free()
	if not cloth.is_empty() and out.size() > 0:   # a cloak: its chains swing
		out[0].set_meta("sf3d_cloth", _cloth(skel, cloth, home_grid))
	if out.size() > 0:
		var path := mask if mask != "" else piece.resource_path.get_basename() + ".mask.json"
		var keys := _mask_keys(path)
		if not keys.is_empty():
			out[0].set_meta("sf3d_mask", keys)
			out[0].set_meta("sf3d_character", character)
			_hide_body(character)
	return out


# A cloak's cloth bones («Cloth_<column>_<link>», blender_armour_gen.py) are the piece's own: they are added to the
# character's skeleton, each where it is in the piece at rest (the global rest kept: the character's GLB may be another
# export of the rig, its bones' axes turned). Returns the chains: [[bone names from the top down], ...].
static func _add_cloth_bones(own: Skeleton3D, skel: Skeleton3D) -> Array:
	var chains := {}
	for i in own.get_bone_count():   # parents come before their children in a skeleton
		var n := String(own.get_bone_name(i))
		if not n.begins_with("Cloth_"):
			continue
		if skel.find_bone(n) < 0:
			var pn := String(own.get_bone_name(own.get_bone_parent(i))) if own.get_bone_parent(i) >= 0 else ""
			var pi := skel.find_bone(pn)
			if pi < 0:
				continue
			var b := skel.add_bone(n)
			skel.set_bone_parent(b, pi)
			var rest := skel.get_bone_global_rest(pi).affine_inverse() * own.get_bone_global_rest(i)
			skel.set_bone_rest(b, rest)
			skel.set_bone_pose(b, rest)
		var parts := n.split("_")
		if parts.size() == 3:
			chains[int(parts[1])] = (chains.get(int(parts[1]), []) as Array) + [[int(parts[2]), n]]
	var out := []
	for c in chains:
		var links: Array = chains[c]
		links.sort_custom(func(a, b): return a[0] < b[0])
		out.append(links.map(func(x): return x[1]))
	return out


## The cloak as cloth, as the editor's «Cloth» (armour_gen_editor.html clothStep) and the game cloth of Unreal / Unity
## (Max Distance, Backstop): every point of the chains (their joints and ends) is a particle; each has an "animated
## place" carried by the trunk under it (the hips .. the chest, by its height) and the way out of the body there; it
## hangs, swings and is pushed by the limbs (capsules as thick as the skin round each bone), but goes no farther from its
## place than maxD (little at the top, much at the hem) and never inside it (the backstop): the cloak cannot be pushed
## into the body or hang through it, whatever the clip. The chains' bones are turned to point at their particles.
## Wind: sim.external_force = Vector3(...) (heights a second squared, in the world).
static func _cloth(skel: Skeleton3D, chains: Array, grid := {}) -> Cloth:
	var find := func(suffixes: Array) -> String:
		for i in skel.get_bone_count():
			for sfx in suffixes:
				if String(skel.get_bone_name(i)).ends_with(sfx):
					return String(skel.get_bone_name(i))
		return ""
	var h := 1.0
	var head := skel.find_bone(find.call(["Head"]))
	var hips := skel.find_bone(find.call(["Hips"]))
	if head >= 0 and hips >= 0:
		h = skel.get_bone_global_rest(head).origin.distance_to(skel.get_bone_global_rest(hips).origin) * 2.2   # about the height
	# the body's capsules: each from a bone's head to the next one's, as thick as the skin round it (the character's own
	# meshes: most of that bone's vertices within), so the cloth goes round the limbs as they are, the hands too
	var segs := []
	for pair in [[["Hips"], ["Spine"]], [["Spine"], ["Spine1"]], [["Spine1", "Chest"], ["Spine2", "UpperChest"]], [["Spine2", "UpperChest"], ["Neck"]]]:
		segs.append([find.call(pair[0]), find.call(pair[1])])
	for side in ["Left", "Right"]:
		for pair in [[["UpLeg", "UpperLeg"], ["Leg", "LowerLeg"]], [["Leg", "LowerLeg"], ["Foot"]], [["Shoulder"], ["Arm", "UpperArm"]], [["Arm", "UpperArm"], ["ForeArm", "LowerArm"]],
				[["ForeArm", "LowerArm"], ["Hand"]], [["Hand"], ["HandMiddle1", "MiddleProximal"]]]:
			segs.append([find.call(pair[0].map(func(x): return side + x)), find.call(pair[1].map(func(x): return side + x))])
	segs = segs.filter(func(sg): return sg[0] != "" and sg[1] != "")
	var thick := _thickness(skel, segs)
	var trunk := []   # the spine's joints from the hips up: a particle's place goes with the two its height is between
	for sfx in [["Hips"], ["Spine"], ["Spine1", "Chest"], ["Spine2", "UpperChest"], ["Neck"]]:
		var n: String = find.call(sfx)
		if n != "" and not trunk.has(skel.find_bone(n)):
			trunk.append(skel.find_bone(n))
	var sim := Cloth.new()
	sim.name = "SF3DCloth"
	skel.add_child(sim)
	sim.setup(skel, chains, segs.map(func(sg): return [skel.find_bone(sg[0]), skel.find_bone(sg[1]), float(thick.get(sg[0], .04 * h)) + (.015 * h if String(sg[0]).ends_with("Hand") else 0.0),
			2.4 if String(sg[0]).ends_with("Hand") else 1.0,
			0 if "Leg" in String(sg[0]) or "Foot" in String(sg[0]) or not ("Left" in String(sg[0]) or "Right" in String(sg[0])) else (1 if "Left" in String(sg[0]) else 2),
			float(thick.get(String(sg[0]) + "#full", thick.get(sg[0], .04 * h)))]), trunk, h, grid)   # an arm's side   # a hand's capsule on past the fingertips, fatter (the cloth's
	# points are sparse: the mesh between them is straight)
	return sim


# a cloak's grid of places (blender_armour_gen.py «__clothhome»): a point per chain joint, its UV = (column / (columns - 1),
# joint / links), skinned with the cloak's own weights there (the trunk and the arms); at the character's rest it is where
# the editor sent it. Returns {Vector2i(column, joint): [[bone in skel, weight], ...], rest place, rest normal]}.
static func _home_grid(mi: MeshInstance3D, own: Skeleton3D, skel: Skeleton3D) -> Dictionary:
	var out := {}
	if mi.mesh == null or own == null:
		return out
	var binds := []
	for k in mi.skin.get_bind_count():
		var nm: StringName = mi.skin.get_bind_name(k)
		if nm == StringName() and mi.skin.get_bind_bone(k) >= 0:
			nm = own.get_bone_name(mi.skin.get_bind_bone(k))
		binds.append([skel.find_bone(nm), own.get_bone_global_rest(own.find_bone(nm)) * mi.skin.get_bind_pose(k)])
	var arr: Array = mi.mesh.surface_get_arrays(0)
	var V: PackedVector3Array = arr[Mesh.ARRAY_VERTEX]
	var Nn: PackedVector3Array = arr[Mesh.ARRAY_NORMAL]
	var UV: PackedVector2Array = arr[Mesh.ARRAY_TEX_UV]
	var B = arr[Mesh.ARRAY_BONES]
	var W = arr[Mesh.ARRAY_WEIGHTS]
	if B == null or W == null or UV.is_empty():
		return out
	var per: int = B.size() / V.size()
	var pts := []
	for vi in V.size():
		var ws := []
		var p := Vector3.ZERO
		var n := Vector3.ZERO
		for q in per:
			var w: float = W[vi * per + q]
			var bi: int = B[vi * per + q]
			if w <= 1e-4 or bi < 0 or bi >= binds.size() or binds[bi][0] < 0:
				continue
			ws.append([binds[bi][0], w])
			p += (binds[bi][1] as Transform3D) * V[vi] * w
			n += (binds[bi][1] as Transform3D).basis * Nn[vi] * w
		if ws.is_empty():
			continue
		var tw := 0.0
		for x in ws:
			tw += x[1]
		for x in ws:
			x[1] /= tw
		pts.append([UV[vi], ws, p / tw, n.normalized()])
	return {"pts": pts}


class Cloth extends SkeletonModifier3D:
	const GRAVITY := 4.0   # heights a second squared (as the editor's: a real 10 makes it a tube; the links are not stiff)
	const DRAG := 0.03   # of its speed lost each 1/60 s
	const KEEP := [0.01, 0.08]   # how much it is pulled to its place each 1/60 s: at the hem .. at the collar (x (1 - v)²)
	const MAXD := [0.008, 0.2]   # how far it may go from its place, in heights: + this x how far down the cloak (0..1)
	const MAXD_ARM := 0.35   # over an arm: room for the arm to lift it (x its share of the arms' weights)
	const RIDE := 0.6   # how much a place over the shoulders and arms goes with the cloak's own weights
	const RIDE_V := [0.32, 0.52]   # .. fading out down the cloak (below, its own weights are the chest's only)
	const V0 := 0.42   # where the chains start, down the cloak: a cloak made before 2026-11-01 (no grid of places)
	const V0_TOP := 0.08   # .. and now (blender_armour_gen.py: under the collar)
	const ITER := 5
	const THICK := 0.015   # the cloth's thickness and gap round the capsules, in heights (the editor's .014)
	# an arm raised (out to the side and up, or forward): the cloak thrown back off it (as the editor's clothBack): the
	# whole cloak slid back round the neck, its collar too, each column's angle shrunk (to BACK at the most, behind the
	# shoulder joint), straight down from there, gathered in pleats: the arms in front of it all. RAISE: the upper arm's
	# way up (y of its direction) from which it starts, to which it is all thrown back
	const BACK := deg_to_rad(80.0)
	const RAISE := [-0.55, 0.25]
	# (the places so smoothed over the grid in BACK_SMOOTH passes)
	const SIDE_IN := 0.3   # a particle in a limb at the step's start no deeper than this share of it: still on its side (CLOTH_SIDE_IN)
	const FRICTION := 0.5   # a particle on a limb: its speed into it gone, along it so much of it (CLOTH_FRICTION): no shaking
	const LEG_RIDE := 0.7   # a skirt's place over a thigh goes with it so much (the editor's CLOTH_LEG_RIDE)
	const RELAX := 0.8   # below the armpit back out round so much (the editor's CLOTH_RELAX)
	const LEG0 := 0.25   # a thigh's capsule from so far down its bone (CLOTH_LEG0: no ball round the hip joint out of the hips' sides)
	const ARM0 := 0.15   # an upper arm's capsule, the arm down: from so far down its bone (CLOTH_ARM0: no ball over the shoulder)
	const BACK_SMOOTH := 6
	var external_force := Vector3.ZERO   # wind, heights a second squared
	var h := 1.0
	var nc := 0
	var nk := 0   # particles per column: the links' heads and the last one's end
	var bones := []   # [column][link] -> bone
	var tip := []   # each column's last link: its end in its own frame
	var dirs := []   # [column][link] -> the way to the next particle in the bone's own frame
	var home := []   # per particle: [[bone, weight, place in its rest frame, the way out in its rest frame], ...]
	var maxd := PackedFloat32Array()
	var keep := PackedFloat32Array()
	var LA := PackedInt32Array()   # the links: from, to, rest length, both ways (1) or only not longer (0)
	var LB := PackedInt32Array()
	var LL := PackedFloat32Array()
	var LS := PackedByteArray()
	var WI := PackedFloat32Array()   # each particle: 0 held (a column's top), 1 free
	var EA := PackedInt32Array()   # the grid's edges (down and across): their middles meet the limbs too (the points are
	var EB := PackedInt32Array()   # sparse: an arm would pass between them)
	var caps := []   # [bone, next bone, radius, how far on past the next bone (1: to it), an arm's side (0 none, 1 L, 2 R)]
	var sides := PackedInt32Array()   # per particle: the side of the arm its place rides on (0 none)
	var ride := PackedFloat32Array()   # .. and how much
	var arm_seg := [[-1, -1], [-1, -1]]   # the upper arms (L, R): bone, next bone: raised above the shoulder?
	var b_ang := PackedFloat32Array()   # thrown back: each particle's angle round the body (0: the back's middle),
	var b_s := PackedFloat32Array()   # .. how far down its column from the collar,
	var b_side := PackedInt32Array()   # .. the arm whose raising throws it back (0 L, 1 R, -1 the middle: both)
	var b_rowd := PackedFloat32Array()   # each row: its columns apart
	var b_half := PI   # the collar's farthest angle round
	var b_darm := 0.1   # the armpits: how far down from the collar's row
	var b_back := true   # thrown back off a raised arm (_back): hung from above the arms
	var b_cuts := []   # the columns c whose links to c + 1 are cut (a tabard's open sides) ..
	var b_kc := 999   # .. from this joint down
	var b_kb := -1   # a belt's joint row: held to its place
	var b_seam := PackedInt32Array()   # a seam's rows (the first and last columns one there)
	var P := PackedVector3Array()
	var Q := PackedVector3Array()
	var _pin_prev := PackedVector3Array()   # the collar's places a step ago (a raised arm pushes it on the side it was on)
	var _ready_p := false
	var _t := 0

	func setup(sk: Skeleton3D, chains: Array, capsules: Array, trunk: Array, height: float, grid := {}) -> void:
		h = height
		caps = capsules
		nc = chains.size()
		nk = (chains[0] as Array).size() + 1
		var rest := []   # the particles at rest (as the cloak was made), in the skeleton
		for c in nc:
			var col: Array = []
			var dd: Array = []
			for nm in chains[c]:
				col.append(sk.find_bone(nm))
			for k in col.size():
				rest.append(sk.get_bone_global_rest(col[k]).origin)
				dd.append(sk.get_bone_rest(col[k + 1]).origin if k + 1 < col.size() else Vector3.ZERO)
			var last: int = col[col.size() - 1]
			var t := sk.get_bone_rest(last).origin   # the end goes on as the link before it
			if t.length() < 1e-6:
				t = Vector3(0, .05 * h, 0)
			tip.append(t)
			dd[dd.size() - 1] = t
			rest.append(sk.get_bone_global_rest(last) * t)
			bones.append(col)
			dirs.append(dd)
		var mine := {}   # the cloak's own places (its grid), by particle
		for pt in grid.get("pts", []):
			var uv: Vector2 = pt[0]   # (glTF's v is upside down)
			mine[roundi(uv.x * (nc - 1)) * nk + roundi((1.0 - uv.y) * (nk - 1))] = pt
		var v0 := V0_TOP if mine.size() >= rest.size() else V0
		var ys := trunk.map(func(b): return sk.get_bone_global_rest(b).origin.y)
		var axis_a: Vector3 = sk.get_bone_global_rest(trunk[0]).origin
		var axis_b: Vector3 = sk.get_bone_global_rest(trunk[trunk.size() - 1]).origin
		var flip := 0.0   # the grid's normals: outwards
		for i in mine:
			flip += (mine[i][3] as Vector3).dot(mine[i][2] - Geometry3D.get_closest_point_to_segment(mine[i][2], axis_a, axis_b))
		var sgn := -1.0 if flip < 0 else 1.0
		for i in rest.size():
			var p: Vector3 = rest[i]
			var ws := []   # the trunk under it, by its height
			if p.y <= ys[0]:
				ws = [[trunk[0], 1.0]]
			elif p.y >= ys[ys.size() - 1]:
				ws = [[trunk[ys.size() - 1], 1.0]]
			else:
				for j in ys.size() - 1:
					if p.y >= ys[j] and p.y <= ys[j + 1]:
						var t: float = (p.y - ys[j]) / max(ys[j + 1] - ys[j], 1e-6)
						ws = [[trunk[j], 1.0 - t], [trunk[j + 1], t]]
						break
			var out := p - Geometry3D.get_closest_point_to_segment(p, axis_a, axis_b)
			out.y = 0
			out = out.normalized() if out.length() > 1e-6 else Vector3.BACK
			var v := v0 + (1.0 - v0) * float(i % nk) / float(nk - 1)
			# its place: on the trunk, and over the shoulders and arms partly on the cloak's own weights (a raised arm
			# lifts the cloth, it does not slide out under it); the collar's row all on them (it is the skinned collar's edge)
			var s := 0.0
			if mine.has(i):
				s = 1.0 if i % nk == 0 else RIDE * (1.0 - smoothstep(RIDE_V[0], RIDE_V[1], v))
			var hs := []   # [bone, weight, place in its rest frame, the way out there, 0 the trunk's / 1 the cloak's own]
			for w in ws:
				hs.append([w[0], float(w[1]) * (1.0 - s), sk.get_bone_global_rest(w[0]).affine_inverse() * p, sk.get_bone_global_rest(w[0]).basis.inverse() * out, 0])
			var arms := 0.0
			var by_side := [0.0, 0.0]
			if s > 0.0:
				var m: Array = mine[i]
				for w in m[1]:
					var R := sk.get_bone_global_rest(w[0])
					hs.append([w[0], float(w[1]) * s, R.affine_inverse() * (m[2] as Vector3), R.basis.inverse() * (m[3] as Vector3) * sgn, 1])
					var bn := String(sk.get_bone_name(w[0]))
					if bn.contains("Arm") or bn.contains("Shoulder"):
						arms += float(w[1])
						by_side[0 if bn.contains("Left") else 1] += float(w[1])
			home.append(hs)
			sides.append(0 if i % nk == 0 or arms < .05 else (1 if by_side[0] >= by_side[1] else 2))
			ride.append(s)
			maxd.append(maxf(MAXD[0] + MAXD[1] * v, arms * MAXD_ARM) * h)
			var f := 1.0 - v
			keep.append(KEEP[0] + (KEEP[1] - KEEP[0]) * f * f)
		for side in 2:   # the upper arms; the body's forward (across the legs, left from right, x up)
			for cp in caps:
				var nm := String(sk.get_bone_name(cp[0]))
				if int(cp[4]) == side + 1 and (nm.ends_with("Arm") or nm.ends_with("UpperArm")) and not nm.ends_with("ForeArm"):
					arm_seg[side] = [cp[0], cp[1]]
		var lu := -1
		var ru := -1
		for b in sk.get_bone_count():
			var nm := String(sk.get_bone_name(b))
			if nm.ends_with("LeftUpLeg") or nm.ends_with("LeftUpperLeg"):
				lu = b
			if nm.ends_with("RightUpLeg") or nm.ends_with("RightUpperLeg"):
				ru = b
		var f0 := Vector3.BACK
		if lu >= 0 and ru >= 0:
			f0 = (sk.get_bone_global_rest(lu).origin - sk.get_bone_global_rest(ru).origin).cross(Vector3.UP).normalized()
		# thrown back: the angles round the body (from behind), the columns' lengths down, the collar's row round
		var xr := Vector3.UP.cross(f0).normalized()
		var ang_of := func(q: Vector3) -> float:
			var o := q - Geometry3D.get_closest_point_to_segment(q, axis_a, axis_b)
			return atan2(o.dot(xr), -o.dot(f0))
		var la := 0.0
		if arm_seg[0][0] >= 0:
			la = ang_of.call(sk.get_bone_global_rest(arm_seg[0][1]).origin)
		for i in rest.size():
			var a: float = ang_of.call(rest[i])
			b_ang.append(a)
			b_side.append(-1 if absf(a) < 1e-3 else (0 if (a > 0) == (la > 0) else 1))
			b_s.append(0.0 if i % nk == 0 else b_s[i - 1] + (rest[i] as Vector3).distance_to(rest[i - 1]))
		b_half = 0.0
		for c in nc:
			b_half = maxf(absf(b_ang[c * nk]), b_half)
		for k in nk:
			var dsum := 0.0
			for c in range(1, nc):
				dsum += (rest[c * nk + k] as Vector3).distance_to(rest[(c - 1) * nk + k])
			b_rowd.append(dsum / maxf(1.0, nc - 1.0))
		var ring_y := 0.0
		for c in nc:
			ring_y += (rest[c * nk] as Vector3).y / nc
		var arm_y := []
		for sg in arm_seg:
			if sg[0] >= 0:
				arm_y.append(sk.get_bone_global_rest(sg[0]).origin.y)
		b_darm = (maxf(.02 * h, ring_y - (arm_y[0] + arm_y[-1]) * .5) if arm_y.size() > 0 else .05 * h) + .07 * h
		# thrown back off a raised arm only a cloth hung from above the arms (a cloak; not a skirt from the waist)
		b_back = arm_y.size() > 0 and ring_y > (arm_y[0] + arm_y[-1]) * .5 - .1 * h
		var opts := String(grid.get("opts", ""))   # the editor's rules (n, l), cuts (c<column>, k<joint>), belt (b<joint>)
		var legs := not b_back
		if opts != "":
			var toks := opts.split("-")
			b_back = not toks.has("n")
			legs = toks.has("l")
			for t in toks:
				if t.begins_with("c"):
					b_cuts.append(int(t.substr(1)))
				elif t.begins_with("k"):
					b_kc = int(t.substr(1))
				elif t.begins_with("b"):
					b_kb = int(t.substr(1))
		if legs:   # (LEG_RIDE)
			_ride_legs(sk, rest, v0)
		var id := func(c, k): return c * nk + k
		for c in nc:
			for k in nk:
				var pairs := []
				if k + 1 < nk:
					pairs.append([id.call(c, k + 1), true])
				if k + 2 < nk:
					pairs.append([id.call(c, k + 2), false])   # bending: it may fold, not stretch
				if c + 1 < nc:
					pairs.append([id.call(c + 1, k), false])   # across: folds gather, it does not stretch
					if k + 1 < nk:
						pairs.append([id.call(c + 1, k + 1), false])
					if k > 0:
						pairs.append([id.call(c + 1, k - 1), false])
				for pr in pairs:
					var c2: int = pr[0] / nk
					var k2: int = pr[0] % nk
					if c2 != c and b_cuts.has(mini(c, c2)) and mini(k, k2) >= b_kc:
						continue   # (not across a cut)
					LA.append(id.call(c, k))
					LB.append(pr[0])
					LL.append((rest[id.call(c, k)] as Vector3).distance_to(rest[pr[0]]))
					LS.append(1 if pr[1] else 0)
		for k in nk:   # a seam: the first and last columns where they are one (a skirt closed round) linked, at no distance
			if (rest[k] as Vector3).distance_to(rest[(nc - 1) * nk + k]) < .002 * h:
				b_seam.append(k)
				LA.append(k)
				LB.append((nc - 1) * nk + k)
				LL.append(0.0)
				LS.append(1)
		for i in rest.size():
			WI.append(0.0 if i % nk == 0 or i % nk == b_kb else 1.0)   # (the collar's row; a belt's)
		for c in nc:
			for k in nk:
				if k + 1 < nk:
					EA.append(id.call(c, k))
					EB.append(id.call(c, k + 1))
				if c + 1 < nc and k > 0 and not (b_cuts.has(c) and k >= b_kc):
					EA.append(id.call(c, k))
					EB.append(id.call(c + 1, k))
		P.resize(rest.size())
		Q.resize(rest.size())

	# a cloth hung below the arms (a skirt): its place over a thigh goes with the thigh, more the nearer (by the distance
	# from the thigh's line; between the legs half each): a knee raised lifts it, not comes through it (the editor's
	# CLOTH_LEG_RIDE)
	func _ride_legs(sk: Skeleton3D, rest: Array, v0: float) -> void:
		var legs := []
		for cp in caps:
			var nm := String(sk.get_bone_name(cp[0]))
			if nm.ends_with("UpLeg") or nm.ends_with("UpperLeg"):
				legs.append([cp[0], sk.get_bone_global_rest(cp[0]).origin, sk.get_bone_global_rest(cp[1]).origin])
		if legs.is_empty():
			return
		for i in rest.size():
			if i % nk == 0:
				continue
			var p: Vector3 = rest[i]
			var v := v0 + (1.0 - v0) * float(i % nk) / float(nk - 1)
			var lw := []
			var tot := 0.0
			for lg in legs:
				var q := Geometry3D.get_closest_point_to_segment(p, lg[1], lg[2])
				var w := 1.0 - smoothstep(.06 * h, .14 * h, p.distance_to(q))
				lw.append(w)
				tot += w
			var r := LEG_RIDE * minf(1.0, tot) * smoothstep(.05, .3, v)
			if r <= 0.0:
				continue
			var hs: Array = home[i]
			var R0 := sk.get_bone_global_rest(hs[0][0])
			var out: Vector3 = R0.basis * (hs[0][3] as Vector3)   # (its way out, in the skeleton)
			for w in hs:
				w[1] = float(w[1]) * (1.0 - r)
			for li in legs.size():
				if lw[li] > 0.0:
					var R := sk.get_bone_global_rest(legs[li][0])
					hs.append([legs[li][0], r * lw[li] / tot, R.affine_inverse() * p, R.basis.inverse() * out, 0])
			maxd[i] = maxf(maxd[i], r * .25 * h)

	func _raised(sk: Skeleton3D, G: Transform3D, side: int) -> float:   # an upper arm raised (out and up, or forward): 0 .. 1
		var sg: Array = arm_seg[side]
		if sg[0] < 0:
			return 0.0
		var d := G.basis * (sk.get_bone_global_pose(sg[1]).origin - sk.get_bone_global_pose(sg[0]).origin)
		return smoothstep(RAISE[0], RAISE[1], d.normalized().y)

	func _col_at(k: int, a: float) -> float:   # the fractional column at angle a in row k (as made)
		for c in nc - 1:
			var a0 := b_ang[c * nk + k]
			var a1 := b_ang[(c + 1) * nk + k]
			if (a - a0) * (a - a1) <= 0.0:
				return c + (clampf((a - a0) / (a1 - a0), 0.0, 1.0) if absf(a1 - a0) > 1e-9 else 0.0)
		return 0.0 if absf(a - b_ang[k]) < absf(a - b_ang[(nc - 1) * nk + k]) else nc - 1.0

	func _at(k: int, cf: float, pl: PackedVector3Array, ns: PackedVector3Array) -> Array:   # the place and the way out at a
		var c0 := clampi(int(floor(cf)), 0, nc - 2)   # fractional column cf of row k
		var t := clampf(cf - c0, 0.0, 1.0)
		return [pl[c0 * nk + k].lerp(pl[(c0 + 1) * nk + k], t), ns[c0 * nk + k].lerp(ns[(c0 + 1) * nk + k], t)]

	# a particle of the cloak thrown back by rb (0 .. 1) over the cloak's places now (pl, ns): its column's angle shrunk;
	# the collar's row there on the collar (the clasp's cords drawn out), the rest straight down from it as far as it
	# was; below the armpit back out round towards its own angle (RELAX: behind the arms, spread like wings, the front
	# edges falling at the sides), in soft pleats (each column in or out by the width it has to spare). The columns keep
	# their order round (none crosses another)
	func _back(i: int, rb: float, pl: PackedVector3Array, ns: PackedVector3Array) -> Array:
		var c := i / nk
		var a := b_ang[c * nk]
		var kk := 1.0 - rb * (1.0 - BACK / b_half) if b_half > BACK else 1.0
		if i % nk == 0:   # the collar
			var r0: Array = _at(0, _col_at(0, a * kk), pl, ns)
			return [r0[0], (r0[1] as Vector3).normalized()]
		var s := b_s[i]
		var left := s
		var ke := 1.0 - (1.0 - kk) * (1.0 - RELAX * smoothstep(b_darm, b_darm + .15 * h, s))
		var ang := a * ke
		var per := maxf(4.0, 8.0 * (nc - 1) / 32.0)   # (the pleats as wide as the editor's: one each 8 of its 32 lines)
		var amp := 2.0 * ke * sqrt(maxf(0.0, 1.0 / ke - 1.0)) * smoothstep(0.0, .08 * h, s) * sin(TAU * c / per) if ke < 1.0 else 0.0
		var p0: Array = _at(0, _col_at(0, ang), pl, ns)
		for row in range(1, nk):
			var p1: Array = _at(row, _col_at(row, ang), pl, ns)
			var L := (p0[0] as Vector3).distance_to(p1[0])
			if L >= left or row == nk - 1:
				var t := minf(1.5, left / L) if L > 1e-9 else 0.0
				var n: Vector3 = (p0[1] as Vector3).lerp(p1[1], minf(1.0, t)).normalized()
				return [(p0[0] as Vector3).lerp(p1[0], t) + n * (amp * b_rowd[row]), n]
			left -= L
			p0 = p1
		return [pl[i], ns[i]]

	# each particle's place and the way out there now, in the world. An arm raised: the places riding on it go back to
	# the trunk's, and the cloak is thrown back off it (_back: behind it, round the neck) over those places, then smoothed
	func _homes(sk: Skeleton3D, G: Transform3D, raised: Array) -> Array:
		var pl := PackedVector3Array()
		var ns := PackedVector3Array()
		var pose := {}
		for i in home.size():
			var p := Vector3.ZERO
			var n := Vector3.ZERO
			var r: float = raised[sides[i] - 1] if sides[i] > 0 else 0.0
			var kt := 1.0
			var km := 1.0
			if r > 0.0 and ride[i] < 1.0:
				kt = (1.0 - ride[i] + ride[i] * r) / (1.0 - ride[i])
				km = 1.0 - r
			for w in home[i]:
				if not pose.has(w[0]):
					pose[w[0]] = G * sk.get_bone_global_pose(w[0])
				var T: Transform3D = pose[w[0]]
				var k: float = float(w[1]) * (km if w[4] == 1 else kt)
				p += T * (w[2] as Vector3) * k
				n += T.basis * (w[3] as Vector3) * k
			pl.append(p)
			ns.append(n.normalized() if n.length_squared() > 1e-12 else Vector3.BACK)
		if raised[0] <= 0.0 and raised[1] <= 0.0:
			return [pl, ns]
		var hb := pl.duplicate()
		var nb := ns.duplicate()
		var wb := PackedFloat32Array()
		wb.resize(pl.size())
		for i in pl.size():
			var rb: float = (raised[0] + raised[1]) * .5 if b_side[i] < 0 else raised[b_side[i]]
			if rb > 0.0 and b_back:
				var bk := _back(i, rb, pl, ns)
				wb[i] = minf(1.0, 3.0 * rb)
				hb[i] = pl[i].lerp(bk[0], wb[i])
				nb[i] = ns[i].lerp(bk[1], wb[i])
		for _it in BACK_SMOOTH:   # (the rows' skew near the clasp: sharp between the cells)
			var h0 := hb.duplicate()
			var n0 := nb.duplicate()
			for i in pl.size():
				var k := i % nk
				if wb[i] <= 0.0 or k == 0:
					continue
				var sp := Vector3.ZERO
				var sn := Vector3.ZERO
				var cnt := 0
				for j in [i - nk if i >= nk else -1, i + nk if i + nk < pl.size() else -1, i - 1, i + 1 if k < nk - 1 else -1]:
					if j >= 0:
						sp += h0[j]
						sn += n0[j]
						cnt += 1
				hb[i] += (sp / cnt - h0[i]) * wb[i] * .5
				nb[i] += (sn / cnt - n0[i]) * wb[i] * .5
		for i in nb.size():
			nb[i] = nb[i].normalized() if nb[i].length_squared() > 1e-12 else ns[i]
		return [hb, nb]

	# p in a limb's capsule (a .. b, radius r): out of it on the side it was on at the step's start (prev: a limb pushes
	# the cloth, never through it); its side no telling (prev inside too): a raised arm's (cu) out on its place's side
	# (home), else out over the limb (nrm)
	func _cap_out(p: Vector3, prev: Vector3, a: Vector3, b: Vector3, r: float, cu: int, home: Vector3, nrm: Vector3, inward := false) -> Vector3:
		var q := Geometry3D.get_closest_point_to_segment(p, a, b)
		var dq := p - q
		if dq.length_squared() >= r * r:
			return p
		var ax := (b - a).normalized()
		var ps := prev - Geometry3D.get_closest_point_to_segment(prev, a, b)
		ps -= ax * ps.dot(ax)
		var si := SIDE_IN if cu == 1 else 0.9   # (a raised arm's; a limb hanging: out of it when it was)
		if ps.length_squared() >= si * si * r * r:
			ps = ps.normalized()
			var dn := dq.dot(ps)
			if dn < 0.0:
				dq -= ps * (2.0 * dn)
		elif cu == 1:
			dq = _to_place(dq, home - q, b - a)
		else:   # (inward: an arm hanging beside a cloth hung below the arms, a skirt: the arm outside it, the cloth in between)
			var nn := -nrm if inward else nrm
			var dn := dq.dot(nn)
			if dn < 0.0:
				dq -= nn * (2.0 * dn)
		return q + (dq.normalized() if dq.length_squared() > 1e-18 else nrm) * r

	static func _to_place(dq: Vector3, dh: Vector3, ax: Vector3) -> Vector3:   # dq mirrored to the side dh is on (across the axis)
		var an := ax.normalized()
		dh -= an * dh.dot(an)
		if dh.length_squared() < 1e-18:
			return dq
		dh = dh.normalized()
		var dn := dq.dot(dh)
		return dq - dh * (2.0 * dn) if dn < 0.0 else dq

	func _process_modification() -> void:
		var sk := get_skeleton()
		if sk == null or nc == 0:
			return
		var now := Time.get_ticks_usec()
		var dt := clampf((now - _t) / 1e6, 0.0, 1.0 / 20.0) if _t > 0 else 0.0
		_t = now
		var G := sk.global_transform
		var raised := [_raised(sk, G, 0), _raised(sk, G, 1)]
		var hm := _homes(sk, G, raised)
		var pl: PackedVector3Array = hm[0]
		var ns: PackedVector3Array = hm[1]
		var pins := PackedVector3Array()   # each column's top: its place (the collar's edge)
		for c in nc:
			pins.append(pl[c * nk])
		if not _ready_p:
			_ready_p = true
			for i in P.size():
				P[i] = pl[i]
				Q[i] = pl[i]
		var nca := caps.size()   # the capsules now: ends, radius
		var CA := PackedVector3Array()
		var CB := PackedVector3Array()
		var CR := PackedFloat32Array()
		var CR2 := PackedFloat32Array()
		var CU := PackedByteArray()   # a raised arm's: the cloth goes out on its place's side (thrown back: behind it, under it)
		var CI := PackedByteArray()   # an arm's beside a cloth hung below the arms (a skirt): the cloth goes inside it
		var CUP := PackedFloat32Array()   # .. and how raised (an arm's, not the shoulder's): it pushes the collar aside
		for cp in caps:
			var ca := G * sk.get_bone_global_pose(cp[0]).origin
			var cj := G * sk.get_bone_global_pose(cp[1]).origin
			var cb := ca + (cj - ca) * float(cp[3])
			var nm := String(sk.get_bone_name(cp[0]))
			var r0 := float(cp[2])
			if int(cp[4]) > 0 and nm.ends_with("Arm") and not nm.ends_with("ForeArm"):   # (an upper arm: down its bone, the arm down)
				ca += (cj - ca) * ARM0 * (1.0 - float(raised[int(cp[4]) - 1]))
			elif nm.ends_with("UpLeg") or nm.ends_with("UpperLeg"):   # a thigh hanging: down its bone (LEG0), thinner (beside
				var lu := smoothstep(-.97, -.8, (cj - ca).normalized().y)   # the hips, over shorts); raised (a stride, a squat): from
				ca += (cj - ca) * LEG0 * (1.0 - lu)   # its joint, as thick as its fuller side (the cloth lies on it there)
				r0 = lerpf(r0, float(cp[5]) if cp.size() > 5 else r0, lu)
			var r := (r0 + THICK * h) * G.basis.get_scale().x
			CA.append(ca)
			CB.append(cb)
			CR.append(r)
			CR2.append(r * r)
			var nm0 := String(sk.get_bone_name(cp[0]))   # (not the shoulder's girdle: the cloak lies on it)
			CU.append(1 if int(cp[4]) > 0 and not nm0.ends_with("Shoulder") and float(raised[int(cp[4]) - 1]) > .5 else 0)
			CUP.append(float(raised[int(cp[4]) - 1]) if int(cp[4]) > 0 and not nm0.ends_with("Shoulder") else 0.0)
			CI.append(0 if int(cp[4]) == 0 else (2 if not b_cuts.is_empty() else (1 if not b_back else 0)))   # (an arm's: 1 the cloth inside it, a skirt; 2 a tabard's cut)
		var sc := G.basis.get_scale().x
		var hh := h * sc
		var near := []   # each particle's capsules worth a look this frame: those near where it is going (it moves
		for i in P.size():   # little in a frame)
			var lst := PackedInt32Array()
			var pi := P[i] + (P[i] - Q[i])
			for ci in nca:
				var lim := CR[ci] + .05 * hh
				if Geometry3D.get_closest_point_to_segment(pi, CA[ci], CB[ci]).distance_squared_to(pi) < lim * lim:
					lst.append(ci)
			near.append(lst)
		var steps := maxi(1, ceili(dt * 30.0 - 0.01))   # one step up to 1/30 s (Verlet holds: the forces are mild)
		var sdt := dt / steps
		var acc := (Vector3(0, -GRAVITY, 0) + external_force) * hh * sdt * sdt
		for s in steps:
			for i in P.size():
				if WI[i] == 0.0:
					continue
				var vel := (P[i] - Q[i]) * (1.0 - DRAG * sdt * 60.0)
				Q[i] = P[i]
				P[i] += vel + acc + (pl[i] - P[i]) * keep[i] * sdt * 60.0
			if _pin_prev.size() != nc:
				_pin_prev = pins.duplicate()
			for c in nc:   # the collar held; a raised arm pushes it aside (the deltoid up under it would come up through it)
				var pp := pins[c]
				for ci in nca:
					if CUP[ci] >= .3 and b_back:
						pp = pp.lerp(_cap_out(pp, _pin_prev[c], CA[ci], CB[ci], CR[ci], CU[ci], pl[c * nk], ns[c * nk]), minf(1.0, (CUP[ci] - .3) / .4))
				P[c * nk] = pp
				Q[c * nk] = pp
				_pin_prev[c] = pp
				if b_kb > 0:   # a belt's row: on its place
					P[c * nk + b_kb] = pl[c * nk + b_kb]
					Q[c * nk + b_kb] = pl[c * nk + b_kb]
			var touch := PackedVector3Array()
			touch.resize(P.size())
			for it in ITER:
				for li in LA.size():
					var a := LA[li]
					var b := LB[li]
					var d := P[b] - P[a]
					var len := d.length()
					var rl := LL[li] * sc
					if len < 1e-9 or (len < rl and LS[li] == 0):
						continue
					var wa := WI[a]
					var wb := WI[b]
					if wa + wb == 0.0:
						continue
					var corr := d * ((len - rl) / len / (wa + wb))
					P[a] += corr * wa
					P[b] -= corr * wb
				for i in P.size():
					if WI[i] == 0.0:
						continue
					var off := P[i] - pl[i]   # no farther than maxD from its place, never inside it
					var md := maxd[i] * G.basis.get_scale().x
					if off.length() > md:
						off = off.normalized() * md
					var into := off.dot(ns[i])
					if into < -.002 * hh:
						off -= ns[i] * (into + .002 * hh)
					var p := pl[i] + off
					for ci in near[i]:   # the limbs push it out, last (_cap_out)
						var cu: int = 1 if CU[ci] == 1 or (CI[ci] == 2 and i % nk >= b_kc - 1) else 0   # (a tabard's panel by an arm at its cut: to its place's side)
						var p2 := _cap_out(p, Q[i], CA[ci], CB[ci], CR[ci], cu, pl[i], ns[i], CI[ci] == 1)
						if it == ITER - 1 and p2 != p:
							touch[i] = (p2 - p).normalized()
						p = p2
					P[i] = p
				for e in (EA.size() if it >= ITER - 2 else 0):   # the edges' middles (the last passes): both ends moved as the middle must
					var a := EA[e]
					var b := EB[e]
					var cand: PackedInt32Array = near[b] if near[b].size() >= near[a].size() else near[a]
					if cand.is_empty():
						continue
					var m := (P[a] + P[b]) * .5
					var nm := (ns[a] + ns[b]).normalized()
					for ci in cand:
						var mv := _cap_out(m, (Q[a] + Q[b]) * .5, CA[ci], CB[ci], CR[ci], CU[ci], (pl[a] + pl[b]) * .5, nm, CI[ci] == 1) - m
						if mv.length_squared() > 0.0:
							var wsum := WI[a] + WI[b]   # both free: each by it; one held: the other by twice it
							if wsum > 0.0:
								P[a] += mv * (2.0 * WI[a] / wsum)
								P[b] += mv * (2.0 * WI[b] / wsum)
							m = (P[a] + P[b]) * .5
			for k in b_seam:   # a seam's two sides one point (each pushed its own way by a thigh, the seam would open)
				var m := (P[k] + P[(nc - 1) * nk + k]) * .5
				var mq := (Q[k] + Q[(nc - 1) * nk + k]) * .5
				P[k] = m
				P[(nc - 1) * nk + k] = m
				Q[k] = mq
				Q[(nc - 1) * nk + k] = mq
			for i in P.size():   # (FRICTION)
				var tn := touch[i]
				if tn == Vector3.ZERO:
					continue
				var vel := P[i] - Q[i]
				var vn := vel.dot(tn)
				var vt := vel - tn * vn
				Q[i] = P[i] - (vt * (1.0 - FRICTION) + tn * maxf(0.0, vn))
		var Gi := G.affine_inverse()
		for c in nc:   # each link turned to point at the next particle
			var col: Array = bones[c]
			var parent := sk.get_bone_global_pose(sk.get_bone_parent(col[0]))
			for k in col.size():
				var b: int = col[k]
				var g := parent * sk.get_bone_rest(b)
				g.origin = Gi * P[c * nk + k]   # its head on its particle
				var want := Gi * P[c * nk + k + 1] - g.origin
				var have: Vector3 = g.basis * (dirs[c][k] as Vector3)
				if want.length() > 1e-9 and have.length() > 1e-9:
					g = Transform3D(Basis(Quaternion(have.normalized(), want.normalized())) * g.basis, g.origin)
				sk.set_bone_pose(b, parent.affine_inverse() * g)
				parent = g


# how thick the body is round each segment [bone, next bone]: the character's skinned meshes (not the pieces put on),
# each vertex on its strongest bone, its distance from that bone's segment at rest; a share of them (below: by the bone)
static func _thickness(skel: Skeleton3D, segs: Array) -> Dictionary:
	var seg := {}
	for sg in segs:
		seg[skel.find_bone(sg[0])] = [skel.get_bone_global_rest(skel.find_bone(sg[0])).origin, skel.get_bone_global_rest(skel.find_bone(sg[1])).origin, sg[0]]
	var dists := {}
	for mi in skel.find_children("*", "MeshInstance3D", true, false):
		if mi.has_meta("sf3d_piece") or mi.skin == null or mi.mesh == null:
			continue
		var to_skel := _relative(skel, mi)   # (in the tree or not yet)
		var binds := []
		for k in mi.skin.get_bind_count():
			var nm: StringName = mi.skin.get_bind_name(k)
			binds.append(skel.find_bone(nm) if nm != StringName() else mi.skin.get_bind_bone(k))
		for si in mi.mesh.get_surface_count():
			var arr: Array = mi.mesh.surface_get_arrays(si)
			var V: PackedVector3Array = arr[Mesh.ARRAY_VERTEX]
			var B = arr[Mesh.ARRAY_BONES]
			var W = arr[Mesh.ARRAY_WEIGHTS]
			if B == null or W == null or V.is_empty():
				continue
			var per: int = B.size() / V.size()
			for vi in V.size():
				var best := 0
				for q in per:
					if W[vi * per + q] > W[vi * per + best]:
						best = q
				var bi: int = B[vi * per + best]
				if bi < 0 or bi >= binds.size() or not seg.has(binds[bi]):
					continue
				var sgm: Array = seg[binds[bi]]
				var p: Vector3 = to_skel * V[vi]
				var d := Geometry3D.get_closest_point_to_segment(p, sgm[0], sgm[1]).distance_to(p)
				if not dists.has(sgm[2]):
					dists[sgm[2]] = []
				dists[sgm[2]].append(d)
	var out := {}
	for bn in dists:
		var ds: Array = dists[bn]
		ds.sort()
		# the arms: the 75th in a hundred (a cloak goes round them; as the editor's three rays in four); the trunk: the 25th (its nearest skin: the hips'
		# bone has the buttocks too, the spine's the shoulder blades: a capsule so thick would stand out of the back, a
		# skirt round it a box); the legs: the 30th (a thigh's bone has the buttock too: round the hip joint it would
		# push a skirt's top out into a shelf)
		var q := .25 if not ("Left" in String(bn) or "Right" in String(bn)) else (.3 if ("Leg" in String(bn) or "Foot" in String(bn)) else .75)
		out[bn] = ds[int(ds.size() * q)]
		out[String(bn) + "#full"] = ds[int(ds.size() * .75)]   # (a thigh raised: as thick as its fuller side)
	return out


# A piece made on an older build of the rig may name bones the character has no more (the lips of a face rig taken
# out since): each such bind goes to its nearest parent the character has, with that parent's bind pose (a piece's
# skin on them has no weight, or follows the head), so Godot does not report every one of them.
static func _rebind(mi: MeshInstance3D, own: Skeleton3D, skel: Skeleton3D) -> void:
	var skin := mi.skin
	var missing := []
	for i in skin.get_bind_count():
		if skin.get_bind_name(i) != StringName() and skel.find_bone(skin.get_bind_name(i)) < 0:
			missing.append(i)
	if missing.is_empty():
		return
	skin = skin.duplicate()
	var index := {}
	for i in skin.get_bind_count():
		index[skin.get_bind_name(i)] = i
	for i in missing:
		var to := StringName()
		var b := own.find_bone(skin.get_bind_name(i)) if own else -1
		while b >= 0:
			b = own.get_bone_parent(b)
			if b >= 0 and skel.find_bone(own.get_bone_name(b)) >= 0:
				to = StringName(own.get_bone_name(b))
				break
		if to == StringName():
			to = StringName(skel.get_bone_name(0))
		skin.set_bind_name(i, to)
		if index.has(to):
			skin.set_bind_pose(i, skin.get_bind_pose(index[to]))
	mi.skin = skin


static func take_off(meshes: Array) -> void:
	var character: Node = null
	for mi in meshes:
		if is_instance_valid(mi) and mi.has_meta("sf3d_cloth"):
			var sim = mi.get_meta("sf3d_cloth")
			if is_instance_valid(sim):
				sim.queue_free()
		if is_instance_valid(mi) and mi.has_meta("sf3d_hold"):
			_grip(mi.get_parent()).hold(mi.get_meta("sf3d_hold"), false)
			if mi.has_meta("sf3d_two"):
				_grip(mi.get_parent()).two_hand("", mi.get_meta("sf3d_two"), [], false)
			if mi.has_meta("sf3d_point"):
				_grip(mi.get_parent()).point(mi.get_meta("sf3d_point"), Vector3.ZERO, false)
			if mi.has_meta("sf3d_grasp"):
				for sd in String(mi.get_meta("sf3d_grasp")):
					_grip(mi.get_parent()).grasp(sd, [], false)
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
			mi.visible = on and bool(mi.get_meta("sf3d_arrow_on", true))
			# a weapon hidden lets its hands go: the fist, the other hand on its haft, its head kept forward, the fingers
			# round its grip (hidden in the fitting room, a two-hander's other hand still reached for it - the arms
			# drawn behind the back)
			if mi.has_meta("sf3d_hold") and bool(mi.get_meta("sf3d_held_on", true)) != on:
				mi.set_meta("sf3d_held_on", on)
				var g := _grip(mi.get_parent())
				g.hold(mi.get_meta("sf3d_hold"), on)
				if mi.has_meta("sf3d_two"):
					g.two_hand(String(mi.get_meta("sf3d_hold")).substr(0, 1), mi.get_meta("sf3d_two"), mi.get_meta("sf3d_two_nums", []), on)
				if mi.has_meta("sf3d_point"):
					g.point(mi.get_meta("sf3d_point"), mi.get_meta("sf3d_point_v", Vector3.ZERO), on)
				if mi.has_meta("sf3d_grasp"):
					for sd in String(mi.get_meta("sf3d_grasp")):
						g.grasp(sd, mi.get_meta("sf3d_grasp_degs", []), on)
			if mi.has_meta("sf3d_character"):
				character = mi.get_meta("sf3d_character")
	if character:
		_hide_body(character)


## A quiver's arrows (its meshes «…__arrow_<k>»): the first n shown, the rest hidden — the game spends them so.
## Returns how many arrows the piece has.
##
##     SF3DEquip.arrows(quiver, SF3DEquip.arrows(quiver, 0) - 1)   # (the count, then one fewer)
static func arrows(meshes: Array, n: int) -> int:
	var total := 0
	for mi in meshes:
		if is_instance_valid(mi) and mi.has_meta("sf3d_arrow"):
			total += 1
			var on := int(mi.get_meta("sf3d_arrow")) <= n
			var was: bool = mi.get_meta("sf3d_arrow_on", true)
			mi.set_meta("sf3d_arrow_on", on)
			mi.visible = on and (mi.visible or not was)
	return total


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


## The fingers closed round a held grip, after the animation, every frame, as the procedural editor's «Fist» pose and its
## grip (armour_gen_editor.html GRIP_DEG): every finger bends in its own plane towards the palm (about its direction x
## the palm's normal), each joint by its degrees. Finger bones are found by name: Mixamo's (mixamorig:LeftHandIndex1)
## or Godot's humanoid ones (LeftIndexProximal).
## The fist remembered in the markup (landmarks.fist_hand, res://fist.json beside the character, or set to `fist`) is
## taken over the angles: each finger bone's turn and a knuckle's shift in the hand's frame (across: little finger ->
## index, along: wrist -> knuckles, palm: the thumb's side), whatever the bones' own axes.
class Grip extends SkeletonModifier3D:
	const FINGER := [60.0, 75.0, 55.0]
	const THUMB := [25.0, 35.0, 35.0]
	var _held := {}   # "L" / "R" -> how many held things
	var _two := {}   # the other hand of a weapon in both hands: its side -> {from: the holding side, n: its grip's numbers}
	var _point := {}   # a spear's holding side -> its head's way in the hand's frame
	const POINT_MAX := 30.0   # how far from forward a spear's head may turn, degrees
	var fist := {}   # "index1_L" -> {q: [x, y, z, w], o: [a, b, c]}
	var _fist_read := false
	var _player: AnimationPlayer = null   # the character's: a throw is one-handed (the other hand not onto the haft)

	func _clip() -> String:
		if _player == null or not is_instance_valid(_player):
			var sk := get_skeleton()
			var root: Node = sk.owner if sk and sk.owner else sk
			var found: Array = root.find_children("*", "AnimationPlayer", true, false) if root else []
			_player = found[0] if found.size() > 0 else null
		return String(_player.current_animation).to_lower() if _player else ""

	func _fist() -> Dictionary:
		if not _fist_read:
			_fist_read = true
			if fist.is_empty() and FileAccess.file_exists("res://fist.json"):
				var d = JSON.parse_string(FileAccess.get_file_as_string("res://fist.json"))
				if d is Dictionary:
					fist = d
		return fist

	func hold(sides: String, on: bool) -> void:
		for s in sides:
			_held[s] = max(0, int(_held.get(s, 0)) + (1 if on else -1))

	## a weapon in both hands (armour_gen_editor.html twoCode): the other hand's grip on the haft, the haft's way and
	## where the grip lies in a hand, in the holding hand's frame over its length
	func two_hand(from: String, side: String, nums: Array, on: bool) -> void:
		if on:
			_two[side] = {"from": from, "n": nums}
		else:
			_two.erase(side)
		hold(side, on)

	## the fingers' degrees round a grip (armour_gen_editor.html graspOf: index, middle, ring, little finger, thumb, three
	## joints each), over the fist and the default angles
	var _grasp := {}
	func grasp(side: String, degs: Array, on: bool) -> void:
		if on:
			_grasp[side] = degs
		else:
			_grasp.erase(side)

	## a spear held (armour_gen_editor.html pointCode): its head's way in the holding hand's frame
	func point(side: String, a: Vector3, on: bool) -> void:
		if on:
			_point[side] = a
		else:
			_point.erase(side)

	# The clips are made for any weapon: a swing turns the hand and, with it, a spear's head backwards. Its head is kept
	# within POINT_MAX of the way the hips face: the hand turned about the wrist by as little as that takes.
	func _keep_forward(sk: Skeleton3D, side: String, a: Vector3) -> void:
		var M := _palm(sk, side)
		var fwd := _forward(sk)
		if M.is_empty() or fwd == Vector3.ZERO:
			return
		var A := ((M["F"] as Basis) * a).normalized()
		var ang := A.angle_to(fwd)
		if ang <= deg_to_rad(POINT_MAX):
			return
		var axis := A.cross(fwd)
		if axis.length() < 1e-6:
			axis = Vector3.UP
		var hand: int = M["hand"]
		var G := sk.get_bone_global_pose(hand)
		var G2 := Transform3D(Basis(Quaternion(axis.normalized(), ang - deg_to_rad(POINT_MAX))) * G.basis, G.origin)
		var pa := sk.get_bone_global_pose(sk.get_bone_parent(hand))
		sk.set_bone_pose_rotation(hand, (pa.affine_inverse() * G2).basis.get_rotation_quaternion())

	func _carry(sk: Skeleton3D, t: Dictionary) -> void:   # the holding hand turned (about the wrist) so the haft points down, a little forward
		var M := _palm(sk, t["from"])
		var fwd := _forward(sk)
		if M.is_empty() or fwd == Vector3.ZERO:
			return
		var n: Array = t["n"]
		var A := ((M["F"] as Basis) * Vector3(n[3], n[4], n[5])).normalized()
		var D := (Vector3.DOWN * 0.85 + fwd * 0.5).normalized()
		var ang := A.angle_to(D)
		var axis := A.cross(D)
		if ang < 1e-3 or axis.length() < 1e-6:
			return
		var hand: int = M["hand"]
		var G := sk.get_bone_global_pose(hand)
		var G2 := Transform3D(Basis(Quaternion(axis.normalized(), ang)) * G.basis, G.origin)
		var pa := sk.get_bone_global_pose(sk.get_bone_parent(hand))
		sk.set_bone_pose_rotation(hand, (pa.affine_inverse() * G2).basis.get_rotation_quaternion())

	func _forward(sk: Skeleton3D) -> Vector3:   # the way the hips face: across them (right to left) x up the spine
		var l := -1
		var r := -1
		var hips := -1
		var head := -1
		for i in sk.get_bone_count():
			var n := String(sk.get_bone_name(i))
			if n.ends_with("LeftUpLeg") or n.ends_with("LeftUpperLeg"):
				l = i
			elif n.ends_with("RightUpLeg") or n.ends_with("RightUpperLeg"):
				r = i
			elif n.ends_with("Hips"):
				hips = i
			elif n.ends_with("Head"):
				head = i
		if l < 0 or r < 0 or hips < 0 or head < 0:
			return Vector3.ZERO
		var up := sk.get_bone_global_pose(head).origin - sk.get_bone_global_pose(hips).origin
		return (sk.get_bone_global_pose(l).origin - sk.get_bone_global_pose(r).origin).cross(up).normalized()

	# the hand's frame as it is now (its knuckles at rest under it): {H, F: across, along, palm as columns, hl}
	func _palm(sk: Skeleton3D, side: String) -> Dictionary:
		var hand := -1
		for i in sk.get_bone_count():
			if sk.get_bone_name(i).ends_with(("Left" if side == "L" else "Right") + "Hand"):
				hand = i
		var i1 := _bone(sk, side, "Index", 1)
		var p1 := _bone(sk, side, "Pinky", 1)
		if p1 < 0:
			p1 = _bone(sk, side, "Ring", 1)
		var t1 := _bone(sk, side, "Thumb", 1)
		if hand < 0 or i1 < 0 or p1 < 0:
			return {}
		var G := sk.get_bone_global_pose(hand)
		var H := G.origin
		var I := G * sk.get_bone_pose(i1).origin
		var P := G * sk.get_bone_pose(p1).origin
		var across := (I - P).normalized()
		var K := (I + P) * 0.5
		var palm := across.cross((K - H).normalized()).normalized()
		if t1 >= 0 and (G * sk.get_bone_pose(t1).origin - H).dot(palm) < 0:
			palm = -palm
		return {"hand": hand, "H": H, "F": Basis(across, palm.cross(across).normalized(), palm), "hl": (K - H).length()}

	# the other hand onto the haft, as the procedural editor's reach(): its frame turned to the grip's (the thumb towards
	# the head, the palm to the haft from its shoulder's side), the wrist where the grip lies in it, the arm's two bones
	# bent to bring it there (the elbow where the clip has it, else down and out). The clips are made for one hand: when
	# the other cannot reach the haft, the holding hand comes towards it first (its turn, and the weapon's, kept).
	func _reach(sk: Skeleton3D, side: String, t: Dictionary, follow := false) -> void:
		var M := _palm(sk, t["from"])
		var P := _palm(sk, side)
		if M.is_empty() or P.is_empty():
			return
		var hand: int = P["hand"]
		var fore := sk.get_bone_parent(hand)
		var arm := sk.get_bone_parent(fore)
		if fore < 0 or arm < 0:
			return
		var Sh := sk.get_bone_global_pose(arm).origin
		var l := sk.get_bone_global_pose(fore).origin.distance_to(Sh) + sk.get_bone_global_pose(hand).origin.distance_to(sk.get_bone_global_pose(fore).origin)
		var g := _grip_for(M, P, t["n"], Sh)
		var over: float = (g["W"] as Vector3).distance_to(Sh) - 0.9 * l
		if over > 0.0:
			var mh: int = M["hand"]
			_arm_to(sk, mh, sk.get_bone_global_pose(mh).origin + (Sh - g["W"]).normalized() * over, Basis(), 1.0)
			M = _palm(sk, t["from"])
			g = _grip_for(M, P, t["n"], Sh)
		var w := smoothstep(0.0, 0.25 * l, 1.3 * l - (g["W"] as Vector3).distance_to(Sh))
		# follow: a mocap clip (the gallery's, «<block>/<clip>») - only as much as the clip itself brings this hand to the
		# grip: one that keeps it away (drawing the sword from the back, sheathing it) is followed, not wrung after the
		# grip behind the back. (The character's own procedural clips are made for one hand: there it is always brought.)
		if follow:
			w *= 1.0 - smoothstep(0.6 * l, 1.1 * l, sk.get_bone_global_pose(hand).origin.distance_to(g["W"]))
		if w <= 0.0:
			return
		_arm_to(sk, hand, g["W"], Basis(), w)   # the wrist there, then the hand's turn onto the grip's frame
		var Ft: Basis = g["Ft"]
		_arm_to(sk, hand, g["W"], (Ft * _palm_at(sk, side, sk.get_bone_global_pose(hand)).inverse()).orthonormalized(), w)

	# the second grip as the holding hand is now: {W: the other wrist's place, Ft: the other hand's frame there}
	func _grip_for(M: Dictionary, P: Dictionary, n: Array, Sh: Vector3) -> Dictionary:
		var Fm: Basis = M["F"]
		var T: Vector3 = M["H"] + Fm * Vector3(n[0], n[1], n[2]) * float(M["hl"])
		var A: Vector3 = (Fm * Vector3(n[3], n[4], n[5])).normalized()
		var c := Vector3(n[6], -n[7], n[8])   # the mirror hand: its frame's second way runs the other way along it
		var palm := T - Sh
		palm = (palm - A * palm.dot(A)).normalized()
		var Ft := Basis(A, palm.cross(A).normalized(), palm)
		return {"W": T - Ft * c * float(P["hl"]), "Ft": Ft}

	# two bones: the wrist towards Wt (as near as the arm allows; w of the way), the hand's world turn kept, then turned
	func _arm_to(sk: Skeleton3D, hand: int, Wt: Vector3, turn: Basis, w: float) -> void:
		var fore := sk.get_bone_parent(hand)
		var arm := sk.get_bone_parent(fore)
		var Ga := sk.get_bone_global_pose(arm)
		var Sh := Ga.origin
		var E := sk.get_bone_global_pose(fore).origin
		var Gh0 := sk.get_bone_global_pose(hand)
		var l1 := E.distance_to(Sh)
		var l2 := Gh0.origin.distance_to(E)
		var nd := Wt - Sh
		var d := clampf(nd.length(), absf(l1 - l2) * 1.01, (l1 + l2) * 0.999)
		nd = nd.normalized()
		var x := (l1 * l1 - l2 * l2 + d * d) / (2.0 * d)
		var h := sqrt(maxf(0.0, l1 * l1 - x * x))
		var pole := (E - Sh) - nd * (E - Sh).dot(nd)
		if pole.length() < 0.2 * l1:
			pole = Vector3(0, -1, 0) + Vector3(1 if "Left" in String(sk.get_bone_name(hand)) else -1, 0, 0) * 0.6 + Vector3(0, 0, -0.3)
			pole -= nd * pole.dot(nd)
		pole = pole.normalized()
		var En := Sh + nd * x + pole * h
		var Wn := Sh + nd * d
		var pa := sk.get_bone_global_pose(sk.get_bone_parent(arm)) if sk.get_bone_parent(arm) >= 0 else Transform3D()
		var Ga2 := Transform3D(Basis(Quaternion.IDENTITY.slerp(Quaternion((E - Sh).normalized(), (En - Sh).normalized()), w)) * Ga.basis, Sh)
		sk.set_bone_pose_rotation(arm, (pa.affine_inverse() * Ga2).basis.get_rotation_quaternion())
		var Gf := Ga2 * sk.get_bone_pose(fore)
		var Gh := Gf * sk.get_bone_pose(hand)
		var Gf2 := Transform3D(Basis(Quaternion.IDENTITY.slerp(Quaternion((Gh.origin - Gf.origin).normalized(), (Wn - Gf.origin).normalized()), w)) * Gf.basis, Gf.origin)
		sk.set_bone_pose_rotation(fore, (Ga2.affine_inverse() * Gf2).basis.get_rotation_quaternion())
		var Gh2 := Gf2 * sk.get_bone_pose(hand)
		var Gh3 := Transform3D(Basis(Quaternion.IDENTITY.slerp(Quaternion(turn), w)) * Gh0.basis, Gh2.origin)
		sk.set_bone_pose_rotation(hand, (Gf2.affine_inverse() * Gh3).basis.get_rotation_quaternion())

	func _palm_at(sk: Skeleton3D, side: String, G: Transform3D) -> Basis:   # the hand's frame were it at G
		var I := G * sk.get_bone_pose(_bone(sk, side, "Index", 1)).origin
		var p1 := _bone(sk, side, "Pinky", 1)
		var P := G * sk.get_bone_pose(p1 if p1 >= 0 else _bone(sk, side, "Ring", 1)).origin
		var across := (I - P).normalized()
		var palm := across.cross(((I + P) * 0.5 - G.origin).normalized()).normalized()
		var t1 := _bone(sk, side, "Thumb", 1)
		if t1 >= 0 and (G * sk.get_bone_pose(t1).origin - G.origin).dot(palm) < 0:
			palm = -palm
		return Basis(across, palm.cross(across).normalized(), palm)

	func _bone(sk: Skeleton3D, side: String, finger: String, joint: int) -> int:
		var word := "Left" if side == "L" else "Right"
		var godot_joint: String = ["", "Metacarpal", "Proximal", "Distal"][joint] if finger == "Thumb" else ["", "Proximal", "Intermediate", "Distal"][joint]
		for i in sk.get_bone_count():
			var n := sk.get_bone_name(i)
			if n.ends_with(word + "Hand" + finger + str(joint)) or (godot_joint != "" and n.ends_with(word + finger + godot_joint)):
				return i
		return -1

	func _process_modification() -> void:
		var sk := get_skeleton()
		if sk == null:
			return
		for side in _point:   # a spear's head forward first: the other hand reaches the haft where it is then
			_keep_forward(sk, side, _point[side])
		var clip := _clip()
		var throwing := "throw" in clip   # (thrown from one hand: the other one is not brought to the haft)
		# idle, walking, running: a two-hander carried in one hand, its point down and a little forward (the clips hold the
		# hand as for a one-hander: reached for by the other hand, the holding arm was wrung across the body)
		# (the gallery's two-handed clips - its block «two_handed_sword/», the procedural «twohand_» - hold the sword in
		# both hands: not carried)
		var resting := not ("twohand" in clip or "two_handed" in clip) and ["idle", "walk", "run"].any(func(w): return w in clip)
		for side in _two:   # the other hands onto their hafts first: their fingers close then
			if resting:
				_carry(sk, _two[side])
			elif not throwing:
				_reach(sk, side, _two[side], "/" in clip)
		for side in _held:
			if int(_held[side]) <= 0:
				continue
			var hand := -1
			for i in sk.get_bone_count():
				if sk.get_bone_name(i).ends_with(("Left" if side == "L" else "Right") + "Hand"):
					hand = i
			var i1 := _bone(sk, side, "Index", 1)
			var p1 := _bone(sk, side, "Pinky", 1)
			if p1 < 0:
				p1 = _bone(sk, side, "Ring", 1)
			var t1 := _bone(sk, side, "Thumb", 1)
			if hand < 0 or i1 < 0 or p1 < 0:
				continue
			if not _grasp.has(side) and _fist().keys().any(func(k): return String(k).ends_with("_" + side)):
				_closed(sk, side, i1, p1, t1, hand)
				continue
			var H := sk.get_bone_global_pose(hand).origin
			var I := sk.get_bone_global_pose(i1).origin
			var P := sk.get_bone_global_pose(p1).origin
			var across := (I - P).normalized()
			var along := ((I + P) * 0.5 - H).normalized()
			var palm := across.cross(along).normalized()
			if t1 >= 0 and (sk.get_bone_global_pose(t1).origin - H).dot(palm) < 0:
				palm = -palm
			var turns := []   # [bone, its axis in its own space, angle], all taken before any is turned
			for finger in ["Index", "Middle", "Ring", "Pinky", "Thumb"]:
				var b1 := _bone(sk, side, finger, 1)
				var b2 := _bone(sk, side, finger, 2)
				if b1 < 0 or b2 < 0:
					continue
				var to := palm   # the thumb closes into the fist: towards the palm and across it, to the little finger
				if finger == "Thumb":
					to = (palm * 0.6 + (P - I).normalized() * 0.8).normalized()
				var axis := (sk.get_bone_global_pose(b2).origin - sk.get_bone_global_pose(b1).origin).cross(to).normalized()
				var degs: Array = THUMB if finger == "Thumb" else FINGER
				if _grasp.has(side):
					var gi: int = ["Index", "Middle", "Ring", "Pinky", "Thumb"].find(finger)
					degs = (_grasp[side] as Array).slice(gi * 3, gi * 3 + 3)
				for j in [1, 2, 3]:
					var b := _bone(sk, side, finger, j)
					if b >= 0:
						turns.append([b, (sk.get_bone_global_pose(b).basis.inverse() * axis).normalized(), deg_to_rad(degs[j - 1])])
			for t in turns:
				sk.set_bone_pose_rotation(t[0], sk.get_bone_pose_rotation(t[0]) * Quaternion(t[1], t[2]))


	# the remembered fist on one hand: each finger's bones from the knuckle out, at rest under the hand as it is now
	# (rc), turned by the fist's turn read in the hand's frame now; the knuckle shifted by a share of the hand's length
	func _closed(sk: Skeleton3D, side: String, i1: int, p1: int, t1: int, hand: int) -> void:
		var under := func(b: int) -> Transform3D: return sk.get_bone_global_pose(sk.get_bone_parent(b)) * sk.get_bone_rest(b)
		var H := sk.get_bone_global_pose(hand).origin
		var I: Vector3 = under.call(i1).origin
		var P: Vector3 = under.call(p1).origin
		var across := (I - P).normalized()
		var K := (I + P) * 0.5
		var palm := across.cross((K - H).normalized()).normalized()
		if t1 >= 0 and (under.call(t1).origin - H).dot(palm) < 0:
			palm = -palm
		var F := Basis(across, palm.cross(across).normalized(), palm)
		var hl := (K - H).length()
		for finger in ["Thumb", "Index", "Middle", "Ring", "Pinky"]:
			var pg := Transform3D()   # the parent as just set
			var rc := Transform3D()   # the bone at rest under the hand
			for j in [1, 2, 3]:
				var b := _bone(sk, side, finger, j)
				if b < 0:
					break
				if j == 1:
					pg = sk.get_bone_global_pose(sk.get_bone_parent(b))
					rc = pg * sk.get_bone_rest(b)
				else:
					rc = rc * sk.get_bone_rest(b)
				var e: Dictionary = fist.get(finger.to_lower() + str(j) + "_" + side, {})
				var turn := Basis()
				if e.has("q"):
					var q: Array = e["q"]
					turn = F * Basis(Quaternion(q[0], q[1], q[2], q[3])) * F.inverse()
				var origin := rc.origin if j == 1 else pg * sk.get_bone_rest(b).origin
				if j == 1 and e.has("o"):
					var o: Array = e["o"]
					origin += F * Vector3(o[0], o[1], o[2]) * hl
				var g := Transform3D(turn * rc.basis, origin)
				var loc := pg.affine_inverse() * g
				sk.set_bone_pose_rotation(b, loc.basis.get_rotation_quaternion())
				sk.set_bone_pose_position(b, loc.origin)
				pg = g


static func _grip(skel: Skeleton3D) -> Grip:
	for c in skel.get_children():
		if c is Grip:
			return c
	var g := Grip.new()
	g.name = "SF3DGrip"
	skel.add_child(g)
	return g
