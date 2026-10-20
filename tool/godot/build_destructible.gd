extends SceneTree
## Builds res://sf3d_destructibles/<name>/<name>.tscn from <name>_destructible.glb + fracture.json (run headless):
##   godot --headless --path <project> --script res://build_destructible.gd -- <name>

const ROOT := "res://sf3d_destructibles/"


func _own(n: Node, owner_node: Node) -> void:
	for ch in n.get_children():
		ch.owner = owner_node
		_own(ch, owner_node)


func _initialize() -> void:
	var name := ""
	for a in OS.get_cmdline_user_args():
		name = a
	var dir := ROOT + name + "/"
	var info = JSON.parse_string(FileAccess.get_file_as_string(dir + "fracture.json"))
	var glb: PackedScene = load(dir + name + "_destructible.glb")
	var inst := glb.instantiate()
	var whole_mesh: Mesh = null
	var chunk_nodes := {}
	for n in inst.find_children("*", "MeshInstance3D", true, false):
		if String(n.name) == "Whole":
			whole_mesh = n.mesh
		elif String(n.name).begins_with("chunk_"):
			chunk_nodes[String(n.name)] = n

	var root := Node3D.new()
	root.name = name.capitalize().replace(" ", "")
	root.set_script(load(ROOT + "destructible.gd"))
	for k in info.get("props", {}):
		root.set(k, info.props[k])
	var whole := Node3D.new()
	whole.name = "Whole"
	root.add_child(whole)
	var wm := MeshInstance3D.new()
	wm.name = "Mesh"
	wm.mesh = whole_mesh
	whole.add_child(wm)
	var sb := StaticBody3D.new()
	sb.name = "Body"
	whole.add_child(sb)
	var cs := CollisionShape3D.new()
	cs.name = "Shape"
	cs.shape = whole_mesh.create_convex_shape(true, true)
	sb.add_child(cs)

	var chunks := Node3D.new()
	chunks.name = "Chunks"
	root.add_child(chunks)
	for d in info.chunks:
		var n: MeshInstance3D = chunk_nodes.get(d.name)
		if n == null:
			continue
		var rb := RigidBody3D.new()
		rb.name = d.name
		rb.position = n.position
		rb.set_meta("share", d.share)
		chunks.add_child(rb)
		var mi := MeshInstance3D.new()
		mi.name = "Mesh"
		mi.mesh = n.mesh
		rb.add_child(mi)
		var c := CollisionShape3D.new()
		c.name = "Shape"
		c.shape = n.mesh.create_convex_shape(true, true)
		rb.add_child(c)
	_own(root, root)
	var ps := PackedScene.new()
	ps.pack(root)
	print("DESTR_SCENE ", name, " ", ResourceSaver.save(ps, dir + name + ".tscn"), " chunks=", chunks.get_child_count())
	quit()
