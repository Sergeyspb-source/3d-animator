## The fitting room (built by landmarks.wardrobe() from the armour mode «Броня», which also puts in the texts of the
## interface language for the markers in the strings): the character with every fitted
## piece put on through SF3DEquip, its clips to play, the pieces on and off, and a camera that orbits the character
## (left drag), pans (right drag) and zooms (wheel).
##
## The clips in blocks: the character's own (the first) and the animation gallery's groups (tool/anim_gallery.py: its
## gallery.glb retargeted onto this character, gallery.json its blocks), each block an AnimationLibrary of its key;
## picking a block that has weapons in its clips puts on a piece of that kind (a two-hander, a sword, a shield).
##
## A picture, then quit: godot --path <project> -- --shot=out.png [--anim=walk | --anim=two_handed_sword/twohand_idle_loop] [--at=0.5] [--yaw=30] [--zoom=2] [--off=item,item]
## [--pitch=-0.5] [--rise=0.3] (the look down, the point looked at raised by that share of the height)
## [--focus=RightHand] (the point looked at: that bone, where the clip has it when the picture is taken)
extends Node3D

const Equip = preload("sf3d_equip.gd")

@export var character: PackedScene
@export var pieces: Array[PackedScene] = []

var _model: Node3D
var _player: AnimationPlayer
var _cam := Camera3D.new()
var _yaw := 0.0
var _pitch := -0.12
var _dist := 3.0
var _target := Vector3.ZERO
var _worn := {}   # piece name -> its meshes
var _repeat := true
var _list := ItemList.new()
var _block := OptionButton.new()
var _blocks := []   # [{key, label, weapons: [kinds], clips: [[the clip's name in the player, its label]]}]
var _boxes := {}   # piece -> its tick
var _args := {}   # --key=value after «--»
var _h := 1.0     # the character's height
const THROW_AT := 0.56   # where in a throwing clip the spear leaves the hand (blender_humanoid_anim.SPEAR_THROW's release)
var _flying := {}   # a thrown spear's mesh -> {copy: its flying copy, v: its velocity}
const NOCK := [0.22, 0.7]   # where in a shooting clip the arrow is on the string, the string drawn (blender_humanoid_anim.BOW_SHOOT)
var _bows := {}   # a bow's mesh -> {surf: its string's surface, tips: [the string's ends, in the mesh], string: [2 drawn halves], arrow}


func _ready() -> void:
	_model = character.instantiate()
	add_child(_model)
	var box := _bounds(_model)
	_target = box.get_center()
	_h = box.size.y
	_dist = maxf(box.size.y, box.size.x) * 1.2
	for a in OS.get_cmdline_user_args():
		var kv := a.trim_prefix("--").split("=", true, 1)
		_args[kv[0]] = kv[1] if kv.size() > 1 else ""
	for p in pieces:
		_worn[p.resource_path.get_file().get_basename().trim_prefix("wear_")] = Equip.wear(_model, p)
	for n in String(_args.get("off", "")).split(",", false):   # --off=item,item: put on, taken off at once (as unticked)
		if _worn.has(n):
			Equip.show(_worn[n], false)
	var players := _model.find_children("*", "AnimationPlayer", true, false)
	if players.size() > 0:
		_player = players[0]
		_player.animation_finished.connect(func(n): if _repeat: _player.play(n))
	_gallery()
	_stage(box)
	_ui()
	_place_camera()
	var args := _args
	var want := String(args.get("anim", ""))
	var at := [0, -1]   # the block and the clip played first: --anim's, else the first idle one of the own clips
	for b in _blocks.size():
		var clips: Array = _blocks[b]["clips"]
		for i in clips.size():
			var n := String(clips[i][0])
			if want != "" and (n == want or n.get_file() == want):
				at = [b, i]
				break
			if want == "" and b == 0 and at[1] < 0 and "idle" in n.to_lower():
				at = [b, i]
		if want != "" and at[1] >= 0:
			break
	if not _blocks.is_empty():
		_block.select(at[0])
		_show_block(at[0], at[0] > 0)   # (a gallery clip asked for: its block's weapons on, as when it is picked)
		var clip := maxi(at[1], 0)
		if _list.item_count > clip:
			_list.select(clip)
			_play(_list.get_item_metadata(clip))
	if args.has("shot"):
		_yaw = deg_to_rad(float(args.get("yaw", "0")))
		_dist /= float(args.get("zoom", "1"))
		_pitch = float(args.get("pitch", str(_pitch)))
		_target.y += float(args.get("rise", "0")) * box.size.y
		_place_camera()
		_shoot(args["shot"], float(args.get("at", "0.5")), String(args.get("focus", "")))


# a spear thrown (a clip with «throw» in its name): at the release it leaves the hand - a copy of it, not skinned, flies
# on from where it was along its way and falls; it is back in the hand when the clip starts again
func _process(dt: float) -> void:
	if _player == null:
		return
	var clip := String(_player.current_animation)
	var anim: Animation = _player.get_animation(clip) if clip != "" else null
	var t := _player.current_animation_position / anim.length if anim and anim.length > 0 else 0.0
	var throwing := "throw" in clip.to_lower()
	for mi in _spears():
		var f = _flying.get(mi)
		if throwing and t >= THROW_AT:
			if f == null:
				f = _launch(mi)
				if f.is_empty():
					continue
				_flying[mi] = f
			f["v"] += Vector3.DOWN * 9.8 * _h / 1.75 * dt
			var c: MeshInstance3D = f["copy"]
			c.global_position += f["v"] * dt
			var fwd: Vector3 = f["v"].normalized()
			c.global_basis = Basis(Quaternion(f["axis"], fwd)) * f["basis"]
		elif f != null:
			f["copy"].queue_free()
			_flying.erase(mi)
			mi.visible = true
	var shooting := "bow" in clip.to_lower() and t >= NOCK[0] and t < NOCK[1]
	for mi in _bow_meshes():
		_draw_bow(mi, shooting)


# a bow in a shooting clip: from the nock to the loose an arrow lies on the string, the string drawn to the right hand
# (its two halves from the tips to the fingers; the bow's own straight string hidden meanwhile)
func _bow_meshes() -> Array:
	var out := []
	for k in _worn:
		if String(k) == "bow" or String(k).begins_with("bow_"):
			for mi in _worn[k]:
				if is_instance_valid(mi) and mi.skin != null and "__hold_" in String(mi.name):
					out.append(mi)
	return out


func _bow_of(mi: MeshInstance3D) -> Dictionary:
	if _bows.has(mi):
		return _bows[mi]
	var b := {}
	var best := -1
	var fewest := 1 << 30
	for si in mi.mesh.get_surface_count():   # the string: the surface of the fewest vertices (a thin rope tip to tip)
		var n: int = (mi.mesh.surface_get_arrays(si)[Mesh.ARRAY_VERTEX] as PackedVector3Array).size()
		if n < fewest:
			fewest = n
			best = si
	if best >= 0 and mi.mesh.get_surface_count() > 1:
		var vs: PackedVector3Array = mi.mesh.surface_get_arrays(best)[Mesh.ARRAY_VERTEX]
		var box := AABB(vs[0], Vector3.ZERO)
		for v in vs:
			box = box.expand(v)
		var ax := 0 if box.size.x >= box.size.y and box.size.x >= box.size.z else (1 if box.size.y >= box.size.z else 2)
		var lo := Vector3.ZERO
		var hi := Vector3.ZERO
		var nl := 0
		var nh := 0
		for v in vs:   # the string's two ends: the middles of its vertices at either end
			if v[ax] < box.get_center()[ax]:
				lo += v
				nl += 1
			else:
				hi += v
				nh += 1
		b = {"surf": best, "tips": [lo / maxi(nl, 1), hi / maxi(nh, 1)], "string": [], "arrow": null}
		var rope := StandardMaterial3D.new()
		rope.albedo_color = Color(0.85, 0.8, 0.65)
		var wood := StandardMaterial3D.new()
		wood.albedo_color = Color(0.45, 0.3, 0.15)
		for i in 2:
			var c := MeshInstance3D.new()
			var cy := CylinderMesh.new()
			cy.top_radius = 0.0018 * _h
			cy.bottom_radius = 0.0018 * _h
			cy.height = 1.0
			cy.radial_segments = 5
			cy.material = rope
			c.mesh = cy
			c.visible = false
			add_child(c)
			b["string"].append(c)
		var ar := MeshInstance3D.new()
		var sh := CylinderMesh.new()
		sh.top_radius = 0.0028 * _h
		sh.bottom_radius = 0.0028 * _h
		sh.height = 1.0
		sh.radial_segments = 6
		sh.material = wood
		ar.mesh = sh
		ar.visible = false
		add_child(ar)
		b["arrow"] = ar
		b["hidden"] = StandardMaterial3D.new()
		b["hidden"].transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
		b["hidden"].albedo_color = Color(0, 0, 0, 0)
	_bows[mi] = b
	return b


func _bone_world(sk: Skeleton3D, suffix: String) -> Vector3:
	for i in sk.get_bone_count():
		if sk.get_bone_name(i).ends_with(suffix):
			return sk.global_transform * sk.get_bone_global_pose(i).origin
	return Vector3.INF


func _rod(c: MeshInstance3D, a: Vector3, b: Vector3) -> void:   # a unit cylinder from a to b
	var d := b - a
	if d.length() < 1e-5:
		c.visible = false
		return
	var y := d.normalized()
	var x := y.cross(Vector3.UP if absf(y.dot(Vector3.UP)) < 0.9 else Vector3.RIGHT).normalized()
	c.global_transform = Transform3D(Basis(x, y * d.length(), x.cross(y)), (a + b) * 0.5)   # (its own y stretched)
	c.visible = true


func _draw_bow(mi: MeshInstance3D, on: bool) -> void:
	var b := _bow_of(mi)
	if b.is_empty():
		return
	var sk := Equip.skeleton_of(_model)
	var hand := _bone_world(sk, "RightHandMiddle1") if sk else Vector3.INF
	if hand == Vector3.INF and sk:
		hand = _bone_world(sk, "RightHand")
	if not on or sk == null or hand == Vector3.INF:
		mi.set_surface_override_material(b["surf"], null)
		for c in b["string"]:
			c.visible = false
		b["arrow"].visible = false
		return
	var kb := _bind_of(mi, sk, b["surf"])
	if kb[1] < 0:
		return
	var M := sk.global_transform * sk.get_bone_global_pose(kb[1]) * mi.skin.get_bind_pose(kb[0])
	var t0: Vector3 = M * (b["tips"][0] as Vector3)
	var t1: Vector3 = M * (b["tips"][1] as Vector3)
	mi.set_surface_override_material(b["surf"], b["hidden"])
	_rod(b["string"][0], t0, hand)
	_rod(b["string"][1], t1, hand)
	var grip: Vector3 = (t0 + t1) * 0.5   # the arrow from the string at the fingers past the grip
	var way := (grip - hand).normalized()
	_rod(b["arrow"], hand - way * 0.01 * _h, grip + way * 0.12 * _h)


func _spears() -> Array:   # the held spears' meshes (their names carry «__point_»: SF3DEquip keeps their heads forward)
	var out := []
	for k in _worn:
		for mi in _worn[k]:
			if is_instance_valid(mi) and "__point_" in String(mi.name):
				out.append(mi)
	return out


# the skin's bind a rigid held thing is on (its first vertex's strongest: the skin lists the whole skeleton's) and its bone
func _bind_of(mi: MeshInstance3D, sk: Skeleton3D, surf := 0) -> Array:
	var arr := mi.mesh.surface_get_arrays(surf)
	var bs = arr[Mesh.ARRAY_BONES]
	var ws = arr[Mesh.ARRAY_WEIGHTS]
	var k := 0
	if bs is PackedInt32Array and ws is PackedFloat32Array and bs.size() >= 4:
		var n: int = bs.size() / maxi(1, (arr[Mesh.ARRAY_VERTEX] as PackedVector3Array).size())
		for j in n:
			if ws[j] > ws[k]:
				k = j
		k = bs[k]
	var nm := mi.skin.get_bind_name(k)
	return [k, sk.find_bone(nm) if nm != StringName() else mi.skin.get_bind_bone(k)]


func _launch(mi: MeshInstance3D) -> Dictionary:   # the spear's copy where it is now, its velocity along its head's way
	var sk := Equip.skeleton_of(_model)
	if sk == null or mi.skin == null:
		return {}
	var kb := _bind_of(mi, sk)
	var k: int = kb[0]
	var bone: int = kb[1]
	if bone < 0:
		return {}
	var c := MeshInstance3D.new()
	c.mesh = mi.mesh
	for i in mi.get_surface_override_material_count():
		c.set_surface_override_material(i, mi.get_surface_override_material(i))
	add_child(c)
	c.global_transform = sk.global_transform * sk.get_bone_global_pose(bone) * mi.skin.get_bind_pose(k)
	var box := mi.mesh.get_aabb()
	var ax := Vector3.ZERO   # its long axis (the mesh's longest side), the head's end the farther from the hand
	var sz := box.size
	ax = Vector3.RIGHT if sz.x >= sz.y and sz.x >= sz.z else (Vector3.UP if sz.y >= sz.z else Vector3.BACK)
	var hand := (sk.global_transform * sk.get_bone_global_pose(bone)).origin
	var world_ax := (c.global_basis * ax).normalized()
	var centre := c.global_transform * box.get_center()
	if (centre - hand).dot(world_ax) < 0:
		world_ax = -world_ax
	mi.visible = false
	return {"copy": c, "v": world_ax * 9.0 * _h / 1.75 + Vector3.UP * 1.5 * _h / 1.75, "axis": world_ax, "basis": c.global_basis}


func _clips() -> Array:
	return Array(_player.get_animation_list()) if _player else []


# the gallery's clips: from its GLB (the same skeleton, imported the same way) into the character's player, a library a
# block; a track kept when its bone is in the character's skeleton, its path made the character's own
func _gallery() -> void:
	if _player == null:
		return
	_blocks = [{"key": "", "label": "{{js:gd.own_clips}}", "weapons": [], "clips": _clips().map(func(c): return [c, c])}]
	if not FileAccess.file_exists("res://gallery.json") or not ResourceLoader.exists("res://gallery.glb"):
		return
	var d = JSON.parse_string(FileAccess.get_file_as_string("res://gallery.json"))
	var scene = load("res://gallery.glb")
	var sk := Equip.skeleton_of(_model)
	if not (d is Dictionary) or not (scene is PackedScene) or sk == null:
		return
	var inst: Node = scene.instantiate()
	var found := inst.find_children("*", "AnimationPlayer", true, false)
	if found.is_empty():
		inst.free()
		return
	var src: AnimationPlayer = found[0]
	var sk_path := String(_player.get_node(_player.root_node).get_path_to(sk))
	for b in d.get("blocks", []):
		var lib := AnimationLibrary.new()
		var clips := []
		var kinds := []
		for c in b["clips"]:
			var id := String(c["id"])
			if not src.has_animation(id):   # (Godot's import takes a «_loop» off a clip's name, looping it)
				for cut in ["_loop", "-loop", "loop"]:
					if id.ends_with(cut) and src.has_animation(id.trim_suffix(cut)):
						id = id.trim_suffix(cut)
						break
			if not src.has_animation(id):
				continue
			var a: Animation = src.get_animation(id).duplicate(true)
			for t in range(a.get_track_count() - 1, -1, -1):
				var bone := a.track_get_path(t).get_concatenated_subnames()
				if bone == "" or sk.find_bone(bone) < 0:
					a.remove_track(t)
				else:
					a.track_set_path(t, NodePath(sk_path + ":" + bone))
			a.loop_mode = Animation.LOOP_LINEAR if c.get("loop", false) else Animation.LOOP_NONE
			lib.add_animation(id, a)
			clips.append([String(b["key"]) + "/" + id, String(c.get("label", id))])
			for w in c.get("weapons", []):
				if not w in kinds:
					kinds.append(w)
		if not clips.is_empty():
			_player.add_animation_library(String(b["key"]), lib)
			_blocks.append({"key": b["key"], "label": b.get("label", b["key"]), "weapons": kinds, "clips": clips})
	inst.free()


# a block's clips into the list; picked by hand, its weapons put on
func _show_block(b: int, arm := true) -> void:
	_list.clear()
	for c in _blocks[b]["clips"]:
		var i := _list.add_item(String(c[1]))
		_list.set_item_metadata(i, c[0])
		_list.set_item_tooltip(i, String(c[0]))
	if arm:
		for w in _blocks[b]["weapons"]:
			_arm(String(w))


# a piece of a gallery weapon kind ticked (its hands' other pieces unticked by the tick): by its name, else by its grip
func _arm(kind: String) -> void:
	var pick := ""
	for name in _boxes:
		var n := String(name).to_lower()
		var named := n.begins_with("shield") if kind == "shield" else (kind in n and not (kind == "sword" and "greatsword" in n))
		if named:
			pick = name
			break
	if pick == "" and kind != "shield":
		for name in _boxes:
			var n := String(name).to_lower()
			if "spear" in n or "bow" in n or "shield" in n:
				continue
			var two := false
			var held := false
			for mi in _worn[name]:
				if is_instance_valid(mi) and mi.has_meta("sf3d_hold"):
					held = true
					two = two or String(mi.get_meta("sf3d_two", "")) != ""
			if held and two == (kind == "greatsword"):
				pick = name
				break
	if pick != "" and not _boxes[pick].button_pressed:
		_boxes[pick].button_pressed = true


func _play(clip: String) -> void:
	if _player:
		_player.play(clip)


func _bounds(root: Node) -> AABB:
	var box := AABB()
	var first := true
	for n in root.find_children("*", "MeshInstance3D", true, false):
		var b: AABB = n.global_transform * n.get_aabb()
		box = b if first else box.merge(b)
		first = false
	return box


func _stage(box: AABB) -> void:
	var env := WorldEnvironment.new()
	env.environment = Environment.new()
	env.environment.background_mode = Environment.BG_COLOR
	env.environment.background_color = Color(0.17, 0.18, 0.2)
	env.environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.environment.ambient_light_color = Color(0.55, 0.57, 0.62)
	add_child(env)
	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-50, 35, 0)
	sun.shadow_enabled = true
	add_child(sun)
	var floor := MeshInstance3D.new()
	var plane := PlaneMesh.new()
	plane.size = Vector2.ONE * maxf(box.size.y, 1.0) * 4
	floor.mesh = plane
	var mat := StandardMaterial3D.new()
	mat.albedo_color = Color(0.32, 0.33, 0.35)
	mat.roughness = 0.95
	floor.material_override = mat
	floor.position.y = box.position.y
	add_child(floor)
	_cam.near = maxf(box.size.y, 0.01) * 0.01
	_cam.far = maxf(box.size.y, 1.0) * 50
	add_child(_cam)
	_cam.current = true


func _ui() -> void:
	var layer := CanvasLayer.new()
	add_child(layer)
	var panel := PanelContainer.new()
	panel.position = Vector2(10, 10)
	layer.add_child(panel)
	# (scrolled: many pieces put on go on past the window's bottom; the wheel over it scrolls it, not the camera)
	var scroll := ScrollContainer.new()
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	panel.add_child(scroll)
	var fit := func(): scroll.custom_minimum_size = Vector2(260, maxf(200.0, get_viewport().get_visible_rect().size.y - 40.0))
	fit.call()
	get_viewport().size_changed.connect(fit)
	var box := VBoxContainer.new()
	box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.add_child(box)
	box.add_child(_label("{{js:gd.animations}}"))
	for b in _blocks:   # (the gallery's groups: each checked on its own)
		_block.add_item(String(b["label"]))
	_block.item_selected.connect(func(b):
		_show_block(b)
		if _list.item_count > 0:
			_list.select(0)
			_play(_list.get_item_metadata(0)))
	if _blocks.size() > 1:
		box.add_child(_block)
	_list.custom_minimum_size = Vector2(230, 240)
	_list.item_selected.connect(func(i): _play(_list.get_item_metadata(i)))
	box.add_child(_list)
	var rep := CheckBox.new()
	rep.text = "{{js:gd.loop}}"
	rep.button_pressed = true
	rep.toggled.connect(func(on): _repeat = on)
	box.add_child(rep)
	box.add_child(_label("{{js:gd.speed}}"))
	var speed := HSlider.new()
	speed.min_value = 0.1
	speed.max_value = 2.0
	speed.step = 0.05
	speed.value = 1.0
	speed.value_changed.connect(func(v): if _player: _player.speed_scale = v)
	box.add_child(speed)
	box.add_child(_label("{{js:gd.pieces}}"))
	var boxes := _boxes
	for name in _worn:
		var cb := CheckBox.new()
		cb.text = name
		cb.button_pressed = not (name in String(_args.get("off", "")).split(",", false))
		# one thing in a hand: ticking a weapon unticks the others held in a hand it takes (a two-hander takes both)
		cb.toggled.connect(func(on):
			if on:
				for other in boxes:
					if other != name and boxes[other].button_pressed and _hands(other).any(func(h): return h in _hands(name)):
						boxes[other].button_pressed = false
			Equip.show(_worn[name], on))
		boxes[name] = cb
		box.add_child(cb)
		var meshes: Array = _worn[name]
		if not meshes.is_empty() and meshes[0].has_meta("sf3d_cloth"):   # a cloak: a wind from the front swings it
			var sim = meshes[0].get_meta("sf3d_cloth")
			box.add_child(_label("{{js:gd.wind}}"))
			var wind := HSlider.new()
			wind.min_value = 0
			wind.max_value = 1
			wind.step = 0.05
			wind.value = float(_args.get("wind", "0"))
			var blow := func(v): if is_instance_valid(sim): sim.external_force = Vector3(0, 0.4 * v, -3.0 * v)   # heights/s², against SF3DEquip.Cloth.GRAVITY's 4
			blow.call(wind.value)
			wind.value_changed.connect(blow)
			box.add_child(wind)
		var total := Equip.arrows(_worn[name], 1 << 20)
		if total > 0:   # a quiver: how many arrows are left
			box.add_child(_label("{{js:gd.arrows}}"))
			var ar := HSlider.new()
			ar.min_value = 0
			ar.max_value = total
			ar.step = 1
			ar.value = total
			ar.value_changed.connect(func(v): Equip.arrows(_worn[name], int(v)))
			box.add_child(ar)
	box.add_child(_label("{{js:gd.mouse_hint}}"))
	var taken := []   # (put on together, two in a hand: the first kept, the others unticked)
	for name in boxes:
		if not boxes[name].button_pressed:
			continue
		var hs := _hands(name)
		if hs.any(func(h): return h in taken):
			boxes[name].button_pressed = false
		else:
			taken.append_array(hs)


func _hands(name: String) -> Array:   # the hands a piece holds in ("L", "R"): its grip's, and a two-hander's other one
	var out := []
	for mi in _worn.get(name, []):
		if is_instance_valid(mi) and mi.has_meta("sf3d_hold"):
			for h in String(mi.get_meta("sf3d_hold")) + String(mi.get_meta("sf3d_two", "")):
				if not h in out:
					out.append(h)
	if out.is_empty() and name.begins_with("shield"):   # a shield strapped on the forearm: its hand is not free (a shield's on the left)
		out.append("L")
	return out


func _label(text: String) -> Label:
	var l := Label.new()
	l.text = text
	return l


func _place_camera() -> void:
	var dir := Basis.from_euler(Vector3(_pitch, _yaw, 0)) * Vector3(0, 0, 1)
	_cam.look_at_from_position(_target + dir * _dist, _target)


func _unhandled_input(e: InputEvent) -> void:
	if e is InputEventMouseMotion:
		if e.button_mask & MOUSE_BUTTON_MASK_LEFT:
			_yaw -= e.relative.x * 0.01
			_pitch = clampf(_pitch - e.relative.y * 0.01, -1.4, 1.4)
		elif e.button_mask & MOUSE_BUTTON_MASK_RIGHT:
			var b := _cam.global_transform.basis
			_target += (-b.x * e.relative.x + b.y * e.relative.y) * _dist * 0.0015
		else:
			return
		_place_camera()
	elif e is InputEventMouseButton and e.pressed:
		if e.button_index == MOUSE_BUTTON_WHEEL_UP:
			_dist *= 0.9
		elif e.button_index == MOUSE_BUTTON_WHEEL_DOWN:
			_dist /= 0.9
		_place_camera()


func _shoot(path: String, at: float, focus := "") -> void:
	await get_tree().create_timer(at).timeout
	if focus != "":   # the camera on a bone as the clip has it now
		var sk := Equip.skeleton_of(_model)
		for i in (sk.get_bone_count() if sk else 0):
			if sk.get_bone_name(i).ends_with(focus):
				_target = sk.global_transform * sk.get_bone_global_pose(i).origin
				_place_camera()
				break
		await RenderingServer.frame_post_draw
	await RenderingServer.frame_post_draw
	get_viewport().get_texture().get_image().save_png(path)
	get_tree().quit()
