## The fitting room (built by landmarks.wardrobe() from the armour mode «Броня», which also puts in the texts of the
## interface language for the markers in the strings): the character with every fitted
## piece put on through SF3DEquip, its clips to play, the pieces on and off, and a camera that orbits the character
## (left drag), pans (right drag) and zooms (wheel).
##
## A picture, then quit: godot --path <project> -- --shot=out.png [--anim=walk] [--at=0.5] [--yaw=30] [--zoom=2]
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
var _args := {}   # --key=value after «--»
var _h := 1.0     # the character's height


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
	var players := _model.find_children("*", "AnimationPlayer", true, false)
	if players.size() > 0:
		_player = players[0]
		_player.animation_finished.connect(func(n): if _repeat: _player.play(n))
	_stage(box)
	_ui()
	_place_camera()
	var args := _args
	var clips := _clips()
	var first: int = clips.find(args.get("anim", ""))
	if first < 0:   # the idle clip first, if there is one
		for i in clips.size():
			if "idle" in String(clips[i]).to_lower():
				first = i
				break
	first = maxi(first, 0)
	if clips.size() > 0:
		_list.select(first)
		_play(clips[first])
	if args.has("shot"):
		_yaw = deg_to_rad(float(args.get("yaw", "0")))
		_dist /= float(args.get("zoom", "1"))
		_pitch = float(args.get("pitch", str(_pitch)))
		_target.y += float(args.get("rise", "0")) * box.size.y
		_place_camera()
		_shoot(args["shot"], float(args.get("at", "0.5")), String(args.get("focus", "")))


func _clips() -> Array:
	return Array(_player.get_animation_list()) if _player else []


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
	var box := VBoxContainer.new()
	panel.add_child(box)
	box.add_child(_label("{{js:gd.animations}}"))
	_list.custom_minimum_size = Vector2(230, 240)
	for c in _clips():
		_list.add_item(c)
	_list.item_selected.connect(func(i): _play(_list.get_item_text(i)))
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
	for name in _worn:
		var cb := CheckBox.new()
		cb.text = name
		cb.button_pressed = true
		cb.toggled.connect(func(on): Equip.show(_worn[name], on))
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
