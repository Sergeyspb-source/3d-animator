extends SceneTree
## Builds the dungeon kit scenes from res://dungeon_kit/kit.glb + kit.json (run headless):
##   godot --headless --path <project> --script res://build_kit.gd
## Writes pieces/<name>.tscn (mesh + collision), dungeon_kit.meshlib and, if plan.json exists, dungeon_demo.tscn.

const DIR := "res://dungeon_kit/"


func _box(b: Array) -> Array:
	var s := BoxShape3D.new()
	s.size = Vector3(b[3], b[4], b[5])
	return [s, Transform3D(Basis(), Vector3(b[0], b[1], b[2]))]


func _ramp(c: float, h: float, floor_t: float) -> Array:
	var a := c / 2.0
	var s := ConvexPolygonShape3D.new()
	s.points = PackedVector3Array([
		Vector3(-a, -floor_t, a), Vector3(a, -floor_t, a), Vector3(-a, -floor_t, -a), Vector3(a, -floor_t, -a),
		Vector3(-a, 0, a), Vector3(a, 0, a), Vector3(-a, h, -a), Vector3(a, h, -a)])
	return [s, Transform3D()]


func _own(n: Node, owner_node: Node) -> void:
	for ch in n.get_children():
		ch.owner = owner_node
		_own(ch, owner_node)


func _initialize() -> void:
	var info = JSON.parse_string(FileAccess.get_file_as_string(DIR + "kit.json"))
	var c: float = info.cell
	var h: float = info.height
	var glb: PackedScene = load(DIR + "kit.glb")
	var inst := glb.instantiate()
	var meshes := {}
	for n in inst.find_children("*", "MeshInstance3D", true, false):
		meshes[String(n.name)] = n.mesh
	DirAccess.make_dir_recursive_absolute(DIR + "pieces")
	var lib := MeshLibrary.new()
	var item := 0
	for pname in info.pieces.keys():
		if not meshes.has(pname):
			print("KIT_MISSING ", pname)
			continue
		var shapes: Array = []
		for b in info.pieces[pname].boxes:
			shapes.append(_box(b))
		if pname == "stairs":
			shapes = [_ramp(c, h, info.floor_thick)]
		var root := Node3D.new()
		root.name = pname
		var mi := MeshInstance3D.new()
		mi.name = "Mesh"
		mi.mesh = meshes[pname]
		root.add_child(mi)
		var body := StaticBody3D.new()
		body.name = "Body"
		root.add_child(body)
		var flat: Array = []
		for s in shapes:
			var cs := CollisionShape3D.new()
			cs.name = "Shape"
			cs.shape = s[0]
			cs.transform = s[1]
			body.add_child(cs)
			flat.append(s[0])
			flat.append(s[1])
		if pname == "door":
			root.set_script(load(DIR + "dungeon_door.gd"))
		_own(root, root)
		var ps := PackedScene.new()
		ps.pack(root)
		print("KIT_SCENE ", pname, " ", ResourceSaver.save(ps, DIR + "pieces/" + pname + ".tscn"))
		if pname != "door":
			lib.create_item(item)
			lib.set_item_name(item, pname)
			lib.set_item_mesh(item, meshes[pname])
			lib.set_item_shapes(item, flat)
			item += 1
	print("KIT_LIB ", ResourceSaver.save(lib, DIR + "dungeon_kit.meshlib"))

	if FileAccess.file_exists(DIR + "plan.json"):
		var plan = JSON.parse_string(FileAccess.get_file_as_string(DIR + "plan.json"))
		var world := Node3D.new()
		world.name = "DungeonDemo"
		for p in plan.pieces:
			var sc: PackedScene = load(DIR + "pieces/" + p.piece + ".tscn")
			var n: Node3D = sc.instantiate()
			var pos := Vector3((p.x + 0.5) * c, p.y * h, (p.z + 0.5) * c)
			var rot: float = deg_to_rad(90.0 * p.rot)
			if p.piece == "door":
				pos += Vector3(info.door.hinge_x, 0, info.door.hinge_z).rotated(Vector3.UP, rot)
			n.position = pos
			n.rotation.y = rot
			world.add_child(n)
			n.owner = world
		for l in plan.lights:
			var o := OmniLight3D.new()
			o.name = "Torch"
			o.light_color = Color(1.0, 0.62, 0.3)
			o.light_energy = 2.2
			o.omni_range = 7.5
			o.position = Vector3((l.x + 0.5) * c, l.y * h + 2.2, (l.z + 0.5) * c)
			world.add_child(o)
			o.owner = world
		var env := WorldEnvironment.new()
		env.name = "Env"
		var e := Environment.new()
		e.background_mode = Environment.BG_COLOR
		e.background_color = Color(0.02, 0.02, 0.03)
		e.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
		e.ambient_light_color = Color(0.5, 0.52, 0.62)
		e.ambient_light_energy = 0.35
		env.environment = e
		world.add_child(env)
		env.owner = world
		var ps2 := PackedScene.new()
		ps2.pack(world)
		print("KIT_DEMO ", ResourceSaver.save(ps2, DIR + "dungeon_demo.tscn"))
	quit()
