extends SceneTree
## Builds the SF3D effect scenes from the textures in res://sf3d_fx/ (run headless):
##   godot --headless --path <project> --script res://build_fx.gd
## Writes explosion.tscn, fire.tscn, smoke.tscn, magic_circle.tscn, hit_sparks.tscn next to the textures.

const DIR := "res://sf3d_fx/"
const GRID := 8


func flip_material(tex_name: String, additive := false, loop := false) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.albedo_texture = load(DIR + tex_name)
	m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	m.blend_mode = BaseMaterial3D.BLEND_MODE_ADD if additive else BaseMaterial3D.BLEND_MODE_MIX
	m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	m.billboard_mode = BaseMaterial3D.BILLBOARD_PARTICLES
	m.particles_anim_h_frames = GRID
	m.particles_anim_v_frames = GRID
	m.particles_anim_loop = loop
	m.vertex_color_use_as_albedo = true
	m.cull_mode = BaseMaterial3D.CULL_DISABLED
	m.no_depth_test = false
	return m


func sprite_material(tex_name: String) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.albedo_texture = load(DIR + tex_name)
	m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	m.blend_mode = BaseMaterial3D.BLEND_MODE_ADD
	m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	m.billboard_mode = BaseMaterial3D.BILLBOARD_PARTICLES
	m.vertex_color_use_as_albedo = true
	return m


func particles(name: String, mat: Material, amount: int, life: float, one_shot: bool, size: float) -> GPUParticles3D:
	var p := GPUParticles3D.new()
	p.name = name
	p.amount = amount
	p.lifetime = life
	p.one_shot = one_shot
	p.explosiveness = 1.0 if one_shot else 0.0
	p.local_coords = false
	var q := QuadMesh.new()
	q.size = Vector2(size, size)
	q.material = mat
	p.draw_pass_1 = q
	p.visibility_aabb = AABB(Vector3(-4, -1, -4), Vector3(8, 8, 8))
	return p


func pm(dir: Vector3, spread: float, v0: float, v1: float, grav: Vector3, s0: float, s1: float,
		anim: bool) -> ParticleProcessMaterial:
	var m := ParticleProcessMaterial.new()
	m.direction = dir
	m.spread = spread
	m.initial_velocity_min = v0
	m.initial_velocity_max = v1
	m.gravity = grav
	m.scale_min = s0
	m.scale_max = s1
	m.angle_min = -180.0
	m.angle_max = 180.0
	if anim:
		m.anim_speed_min = 1.0
		m.anim_speed_max = 1.0
	return m


func save(root: Node3D, file: String) -> void:
	root.set_script(load(DIR + "fx_player.gd"))
	for c in root.get_children():
		c.owner = root
	var ps := PackedScene.new()
	ps.pack(root)
	var err := ResourceSaver.save(ps, DIR + file)
	print("FX_SCENE ", file, " ", err)


func light(color: Color, energy: float, rng: float) -> OmniLight3D:
	var l := OmniLight3D.new()
	l.name = "Light"
	l.light_color = color
	l.light_energy = energy
	l.omni_range = rng
	l.position = Vector3(0, 1, 0)
	return l


func _initialize() -> void:
	# --- explosion: fireball + smoke + sparks + flash
	var ex := Node3D.new()
	ex.name = "Explosion"
	var fb := particles("Fireball", flip_material("explosion.png"), 5, 1.1, true, 3.4)
	fb.process_material = pm(Vector3.UP, 180, 0.2, 0.9, Vector3(0, 0.6, 0), 0.8, 1.3, true)
	fb.position.y = 1.0
	ex.add_child(fb)
	var sm := particles("Smoke", flip_material("smoke.png"), 6, 1.8, true, 3.2)
	sm.process_material = pm(Vector3.UP, 70, 0.4, 1.2, Vector3(0, 0.8, 0), 0.8, 1.4, true)
	sm.position.y = 1.2
	ex.add_child(sm)
	var sp := particles("Sparks", sprite_material("spark.png"), 40, 0.8, true, 0.35)
	sp.process_material = pm(Vector3.UP, 180, 3.0, 7.0, Vector3(0, -9.8, 0), 0.6, 1.4, false)
	sp.position.y = 1.0
	ex.add_child(sp)
	ex.add_child(light(Color(1.0, 0.6, 0.25), 6.0, 8.0))
	save(ex, "explosion.tscn")
	# --- fire: looping flames + embers + flickering light
	var fi := Node3D.new()
	fi.name = "Fire"
	var fl := particles("Flames", flip_material("fire.png", true, true), 7, 1.0, false, 2.0)
	var fm := pm(Vector3.UP, 10, 0.1, 0.3, Vector3(0, 0.3, 0), 0.8, 1.2, true)
	fm.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_SPHERE
	fm.emission_sphere_radius = 0.2
	fm.anim_offset_max = 1.0
	fm.angle_min = -8.0
	fm.angle_max = 8.0
	fl.process_material = fm
	fl.position.y = 0.9
	fi.add_child(fl)
	var em := particles("Embers", sprite_material("spark.png"), 16, 1.6, false, 0.18)
	em.process_material = pm(Vector3.UP, 25, 0.8, 1.8, Vector3(0, 0.5, 0), 0.6, 1.2, false)
	em.position.y = 0.6
	fi.add_child(em)
	fi.add_child(light(Color(1.0, 0.55, 0.2), 2.5, 6.0))
	save(fi, "fire.tscn")
	# --- smoke column (looping)
	var sc := Node3D.new()
	sc.name = "Smoke"
	var sp2 := particles("Puffs", flip_material("smoke.png"), 8, 3.0, false, 1.8)
	sp2.process_material = pm(Vector3.UP, 15, 0.4, 0.8, Vector3(0.2, 0.2, 0), 0.7, 1.3, true)
	sc.add_child(sp2)
	save(sc, "smoke.tscn")
	# --- magic circle on the ground + rising glow
	var mc := Node3D.new()
	mc.name = "MagicCircle"
	var circ := MeshInstance3D.new()
	circ.name = "Circle"
	var plane := PlaneMesh.new()
	plane.size = Vector2(3, 3)
	var cm := StandardMaterial3D.new()
	cm.albedo_texture = load(DIR + "magic_circle.png")
	cm.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	cm.blend_mode = BaseMaterial3D.BLEND_MODE_ADD
	cm.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	cm.emission_enabled = true
	cm.emission_texture = cm.albedo_texture
	cm.emission_energy_multiplier = 1.5
	cm.cull_mode = BaseMaterial3D.CULL_DISABLED
	plane.material = cm
	circ.mesh = plane
	circ.position.y = 0.02
	mc.add_child(circ)
	var glow := particles("Glow", flip_material("magic.png", true, false), 6, 1.4, false, 1.2)
	var gm := pm(Vector3.UP, 5, 0.6, 1.2, Vector3.ZERO, 0.6, 1.0, true)
	gm.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_RING
	gm.emission_ring_radius = 1.1
	gm.emission_ring_inner_radius = 0.9
	gm.emission_ring_height = 0.05
	gm.emission_ring_axis = Vector3.UP
	glow.process_material = gm
	mc.add_child(glow)
	mc.add_child(light(Color(0.4, 0.8, 1.0), 1.5, 5.0))
	save(mc, "magic_circle.tscn")
	# --- hit sparks: short burst for weapon hits
	var hit := Node3D.new()
	hit.name = "HitSparks"
	hit.position.y = 1.0
	var hs := particles("Sparks", sprite_material("spark.png"), 30, 0.5, true, 0.3)
	hs.process_material = pm(Vector3.UP, 70, 2.0, 5.0, Vector3(0, -6, 0), 0.6, 1.2, false)
	hit.add_child(hs)
	var hf := particles("Flash", flip_material("magic.png", true, false), 1, 0.35, true, 1.4)
	hf.process_material = pm(Vector3.UP, 0, 0, 0, Vector3.ZERO, 1.0, 1.0, true)
	hit.add_child(hf)
	hit.add_child(light(Color(1.0, 0.85, 0.6), 2.0, 3.0))
	save(hit, "hit_sparks.tscn")
	quit()
