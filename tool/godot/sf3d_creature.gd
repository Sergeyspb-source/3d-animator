extends Node3D
## The creature's viewer (creatures.godot_view): the model with its clips as the game shows them - a clip list, the
## speed, looping, a floor grid at the paws with shadows, an orbiting camera (left button turns, right one pans, the
## wheel zooms). For checks: godot --path <proj> -- --anim=<clip> --at=<seconds> --yaw=<deg> --pitch=<rad>
## --zoom=<k> --target=<x,y,z> --variant=<name> --blink=<0..1> --shot=<png> (the clip played from its start for «at» seconds, the frame saved, quit).

@export var creature: PackedScene
## the colouring's variants (creatures.paint_save: the same model, other pictures) and their names
@export var variants: Array[PackedScene] = []
@export var variant_names: PackedStringArray = []

var _model: Node3D
var _player: AnimationPlayer
var _cam: Camera3D
var _target := Vector3.ZERO
var _yaw := 0.6
var _pitch := -0.25
var _dist := 3.0
var _list: ItemList
var _speed: HSlider
var _loop: CheckBox
var _args := {}
var _variant: OptionButton
var _lids: Array = []   # [mesh, blend shape index] of the eyelids' blink keys (blender_creature_eyes.py)
var _blink_in := 2.0
var _blink_t := -1.0


func _ready() -> void:
	for a in OS.get_cmdline_user_args():
		var kv := a.trim_prefix("--").split("=", true, 1)
		_args[kv[0]] = kv[1] if kv.size() > 1 else ""
	_load(creature)
	var box := _bounds(_model)
	var h := maxf(box.size.y, maxf(box.size.x, box.size.z))
	_target = box.get_center()
	_dist = h * 1.6
	_world(box, h)
	_ui()
	_cam = Camera3D.new()
	_cam.near = h / 500.0
	_cam.far = h * 100.0
	add_child(_cam)
	_cam.current = true
	_yaw = deg_to_rad(float(_args.get("yaw", str(rad_to_deg(_yaw)))))
	_pitch = float(_args.get("pitch", str(_pitch)))
	_dist /= float(_args.get("zoom", "1"))
	if _args.has("target"):   # (a check's close look: --target=x,y,z, the world point the camera looks at)
		var xyz := String(_args["target"]).split(",")
		_target = Vector3(float(xyz[0]), float(xyz[1]), float(xyz[2]))
	_place_camera()
	var want := String(_args.get("anim", "walk"))
	for i in _list.item_count:   # a clip asked for (its name's end), else the walk, else the first
		if _list.get_item_text(i).ends_with(want):
			_list.select(i)
			_play(i)
			break
	if _player and not _player.is_playing() and _list.item_count:
		_list.select(0)
		_play(0)
	if _args.has("variant") and _variant:   # (a check: --variant=<its name or number, 1 the first>)
		var want_v := String(_args["variant"])
		for i in variant_names.size():
			if variant_names[i] == want_v or str(i + 1) == want_v:
				_variant.select(i + 1)
				_pick_variant(i + 1)
	if _args.has("shot"):
		await get_tree().create_timer(float(_args.get("at", "0.5"))).timeout
		await RenderingServer.frame_post_draw
		get_viewport().get_texture().get_image().save_png(_args["shot"])
		get_tree().quit()


func _load(scene: PackedScene) -> void:   # the model (the base or a variant) in place of the one shown
	if _model:
		_model.queue_free()
	_model = scene.instantiate()
	add_child(_model)
	var found := _model.find_children("*", "AnimationPlayer", true, false)
	_player = found[0] if found.size() > 0 else null
	_lids.clear()
	for m in _model.find_children("*", "MeshInstance3D", true, false):
		var mi := m as MeshInstance3D
		if mi.mesh == null:
			continue
		for k in ["eyeBlinkLeft", "eyeBlinkRight"]:
			var i := mi.find_blend_shape_by_name(k)
			if i >= 0:
				_lids.append([mi, i])


func _pick_variant(i: int) -> void:   # the same clip at the same time on the variant picked (0 = the base)
	var clip: String = _player.current_animation if _player else ""
	var at: float = _player.current_animation_position if _player and clip != "" else 0.0
	var speed: float = _player.speed_scale if _player else 1.0
	_load(creature if i == 0 else variants[i - 1])
	if _player and clip != "":
		_player.speed_scale = speed
		_player.play(clip)
		_player.seek(at, true)


func _bounds(n: Node) -> AABB:   # the meshes' box in the world, at rest
	var box := AABB()
	var first := true
	for m in n.find_children("*", "MeshInstance3D", true, false):
		var b: AABB = (m as MeshInstance3D).global_transform * (m as MeshInstance3D).get_aabb()
		box = b if first else box.merge(b)
		first = false
	return box


# the floor as a 3D program has it: a grid (a tenth of the creature's size, every tenth line stronger) at the paws,
# the X axis red and the forward one green, the shadow on it; a dark graded sky
func _world(box: AABB, h: float) -> void:
	var env := WorldEnvironment.new()
	var e := Environment.new()
	e.background_mode = Environment.BG_COLOR
	e.background_color = Color(0.17, 0.18, 0.2)
	e.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	e.ambient_light_color = Color(0.55, 0.55, 0.6)
	e.ambient_light_energy = 0.7
	e.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	env.environment = e
	add_child(env)
	var sun := DirectionalLight3D.new()
	sun.light_energy = 1.6
	sun.shadow_enabled = true
	sun.directional_shadow_max_distance = h * 12.0
	sun.rotation = Vector3(deg_to_rad(-55), deg_to_rad(35), 0)
	add_child(sun)
	var unit := pow(10.0, round(log(h) / log(10.0))) / 10.0
	var size := maxf(ceil(h * 8.0 / (unit * 10.0)), 2.0) * unit * 10.0
	var floor_y := box.position.y
	var plane := MeshInstance3D.new()
	var pm := PlaneMesh.new()
	pm.size = Vector2(size, size)
	plane.mesh = pm
	var sh := Shader.new()
	sh.code = """shader_type spatial;
render_mode cull_disabled;
uniform float unit = 0.1;
uniform vec3 base : source_color = vec3(0.22, 0.23, 0.25);
uniform vec3 minor : source_color = vec3(0.32, 0.33, 0.36);
uniform vec3 major : source_color = vec3(0.45, 0.47, 0.5);
varying vec3 wp;
void vertex() { wp = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz; }
float line(vec2 p, float step) {
	vec2 g = abs(fract(p / step - 0.5) - 0.5) / fwidth(p / step);
	return 1.0 - clamp(min(g.x, g.y), 0.0, 1.0);
}
void fragment() {
	vec3 c = mix(base, minor, line(wp.xz, unit));
	c = mix(c, major, line(wp.xz, unit * 10.0));
	float ax = 1.0 - clamp(abs(wp.z) / fwidth(wp.z), 0.0, 1.0);
	float az = 1.0 - clamp(abs(wp.x) / fwidth(wp.x), 0.0, 1.0);
	c = mix(c, vec3(0.82, 0.25, 0.31), ax);
	c = mix(c, vec3(0.42, 0.64, 0.23), az);
	ALBEDO = c;
	ROUGHNESS = 0.95;
}"""
	var mat := ShaderMaterial.new()
	mat.shader = sh
	mat.set_shader_parameter("unit", unit)
	plane.material_override = mat
	plane.position = Vector3(0, floor_y, 0)
	add_child(plane)


func _ui() -> void:
	var panel := PanelContainer.new()
	panel.position = Vector2(10, 10)
	panel.custom_minimum_size = Vector2(250, 0)
	add_child(panel)
	var v := VBoxContainer.new()
	panel.add_child(v)
	if variants.size() > 0:
		var vl := Label.new()
		vl.text = "{{js:gd.creature_variant}}"
		v.add_child(vl)
		_variant = OptionButton.new()
		_variant.add_item("{{js:gd.creature_base}}")
		for n in variant_names:
			_variant.add_item(n)
		_variant.item_selected.connect(_pick_variant)
		v.add_child(_variant)
	var t := Label.new()
	t.text = "{{js:gd.creature_clips}}"
	v.add_child(t)
	_list = ItemList.new()
	_list.custom_minimum_size = Vector2(240, 420)
	v.add_child(_list)
	if _player:
		for n in _player.get_animation_list():
			if n != "RESET":
				_list.add_item(n)
	_list.item_selected.connect(_play)
	_loop = CheckBox.new()
	_loop.text = "{{js:gd.creature_loop}}"
	_loop.button_pressed = true
	_loop.toggled.connect(func(_on): _play(_list.get_selected_items()[0] if _list.get_selected_items().size() else 0))
	v.add_child(_loop)
	var s := Label.new()
	s.text = "{{js:gd.creature_speed}}"
	v.add_child(s)
	_speed = HSlider.new()
	_speed.min_value = 0.1
	_speed.max_value = 2.0
	_speed.step = 0.05
	_speed.value = 1.0
	_speed.value_changed.connect(func(x): if _player: _player.speed_scale = x)
	v.add_child(_speed)
	var hint := Label.new()
	hint.text = "{{js:gd.creature_mouse}}"
	hint.autowrap_mode = TextServer.AUTOWRAP_WORD
	hint.custom_minimum_size = Vector2(240, 0)
	v.add_child(hint)


func _play(i: int) -> void:
	if _player == null or i < 0 or i >= _list.item_count:
		return
	var n := _list.get_item_text(i)
	var a := _player.get_animation(n)
	if a:
		a.loop_mode = Animation.LOOP_LINEAR if _loop.button_pressed else Animation.LOOP_NONE
	_player.play(n)
	_player.seek(0.0, true)


func _process(delta: float) -> void:   # now and then a blink (2.5 - 5.5 s apart): closing 0.08 s, shut 0.05 s, opening 0.12 s
	if _lids.is_empty():
		return
	if _args.has("blink"):   # (a check: --blink=<0..1>, the lids held there)
		for l in _lids:
			(l[0] as MeshInstance3D).set_blend_shape_value(l[1], float(_args["blink"]))
		return
	if _blink_t < 0.0:
		_blink_in -= delta
		if _blink_in <= 0.0:
			_blink_t = 0.0
		return
	_blink_t += delta
	var v := 0.0
	if _blink_t < 0.08:
		v = _blink_t / 0.08
	elif _blink_t < 0.13:
		v = 1.0
	elif _blink_t < 0.25:
		v = 1.0 - (_blink_t - 0.13) / 0.12
	else:
		_blink_t = -1.0
		_blink_in = randf_range(2.5, 5.5)
	for l in _lids:
		(l[0] as MeshInstance3D).set_blend_shape_value(l[1], v)


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
		else:
			return
		_place_camera()
