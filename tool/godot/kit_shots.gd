extends SceneTree
## Renders the views listed in res://dungeon_kit/shots.json of the demo scene (windowed run, for previews).

func _wait(sec: float) -> void:
	var t0 := Time.get_ticks_msec()
	while Time.get_ticks_msec() - t0 < sec * 1000.0:
		await process_frame


func _v3(a: Array) -> Vector3:
	return Vector3(a[0], a[1], a[2])


func _initialize() -> void:
	var cfg = JSON.parse_string(FileAccess.get_file_as_string("res://dungeon_kit/shots.json"))
	DirAccess.make_dir_recursive_absolute(cfg.out)
	var root := get_root()
	root.size = Vector2i(1000, 700)
	var world = load("res://dungeon_kit/dungeon_demo.tscn").instantiate()
	root.add_child(world)
	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-60, 25, 0)
	sun.light_energy = 1.2
	root.add_child(sun)
	var cam := Camera3D.new()
	cam.fov = 70
	root.add_child(cam)
	cam.current = true
	await _wait(0.5)
	for v in cfg.views:
		for ch in world.get_children():
			if String(ch.name).begins_with("ceiling"):
				ch.visible = not v.hide_ceiling
		sun.visible = v.sun
		cam.look_at_from_position(_v3(v.pos), _v3(v.look))
		await _wait(0.4)
		root.get_texture().get_image().save_png(cfg.out + "/" + v.name + ".png")
	quit()
