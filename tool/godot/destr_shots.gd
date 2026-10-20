extends SceneTree
## Renders a destructible breaking (windowed run): screenshots before and after the break.
##   godot --path <project> --script res://destr_shots.gd -- <name> <out_dir> <height>

func _wait(sec: float) -> void:
	var t0 := Time.get_ticks_msec()
	while Time.get_ticks_msec() - t0 < sec * 1000.0:
		await process_frame


func _initialize() -> void:
	var a := OS.get_cmdline_user_args()
	var name: String = a[0]
	var out: String = a[1]
	var h: float = float(a[2])
	DirAccess.make_dir_recursive_absolute(out)
	var root := get_root()
	root.size = Vector2i(900, 640)
	var env := WorldEnvironment.new()
	var e := Environment.new()
	e.background_mode = Environment.BG_COLOR
	e.background_color = Color(0.16, 0.18, 0.24)
	e.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	e.ambient_light_color = Color(0.45, 0.45, 0.5)
	env.environment = e
	root.add_child(env)
	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-50, -30, 0)
	sun.light_energy = 1.1
	root.add_child(sun)
	var floor_body := StaticBody3D.new()
	var fm := MeshInstance3D.new()
	var pm := PlaneMesh.new()
	pm.size = Vector2(16, 16)
	fm.mesh = pm
	if ResourceLoader.exists("res://mats/cobblestone/cobblestone.tres"):
		fm.material_override = load("res://mats/cobblestone/cobblestone.tres")
	floor_body.add_child(fm)
	var fs := CollisionShape3D.new()
	var box := BoxShape3D.new()
	box.size = Vector3(16, 1, 16)
	fs.shape = box
	fs.position.y = -0.5
	floor_body.add_child(fs)
	root.add_child(floor_body)
	var obj: Node3D = load("res://sf3d_destructibles/%s/%s.tscn" % [name, name]).instantiate()
	root.add_child(obj)
	var cam := Camera3D.new()
	root.add_child(cam)
	cam.current = true
	var d: float = h * 2.0 + 0.8
	cam.look_at_from_position(Vector3(d * 0.6, h * 0.9 + 0.3, d), Vector3(0, h * 0.35, 0))
	await _wait(0.6)
	root.get_texture().get_image().save_png(out + "/before.png")
	obj.destroy(Vector3(0.3, h * 0.6, 0.6))
	for i in [0.12, 0.4, 1.4]:
		await _wait(i if i < 1.0 else 1.0)
		root.get_texture().get_image().save_png(out + "/break_%s.png" % str(i))
	print("DESTR_SHOTS done")
	quit()
