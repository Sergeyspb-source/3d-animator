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
## A worn piece is drawn by its layer (LAYER, the armour editor's order): as if nearer the camera, its place on the
## screen kept, by its rank among the layers worn on that skeleton (a step of DEPTH_MAX / their count, at most
## DEPTH_STEP, of the character's height). A piece under it that comes out over it in motion
## by less than that is hidden there, as a surface a little behind another; what is really in front (an arm before
## the cuirass) stays seen. SF3DEquip.layered = false before wear() keeps the pieces' own materials.
class_name SF3DEquip
extends RefCounted

static var layered := true
static var keep_off_body := true   # a shield strapped on kept out of the body by its arm (Grip.keep_off)
static var keep_flex := 30.0   # how far its elbow may bend (degrees) to lift it out first, before it is moved
static var keep_debug := false   # (the fitting room's --keepdebug: the correction printed every frame)
static var keep_apply := true   # (false: worked out, not applied - the fitting room's --nokeep with --keepdebug)
static var springs := true   # spring bones of hair and of hems (false: they stay with the head, the thighs - the fitting room's --nosprings)
const DEPTH_STEP := 0.012   # of the height, between two layers worn at most
const DEPTH_MAX := 0.045   # of the height, the top layer's push (a step of ~0.5 % with nine layers worn)
# the armour editor's LAYER (armour_gen_editor.html): the pelerine over the mail, under the cuirass and the pauldrons
const LAYER := {"undercloth": 0.5, "trousers": 1.0, "footwear": 1.5, "brayette": 2.0, "bracer": 3.0, "rerebrace": 3.0,
	"greave": 3.0, "cuisse": 3.0, "tassets": 3.0, "glove": 3.2, "codpiece": 2.5, "fauld": 2.8, "culet": 2.8,
	"elbow": 3.5, "gorget": 4.5, "pelerine": 3.9, "rondel": 5.2, "ailette": 5.6, "hauberk": 2.4, "coif": 3.8,
	"poleyn": 3.5, "cuirass": 4.0, "pauldron": 5.0, "helmet": 5.0, "tabard": 6.0, "skirt": 6.0, "cloak": 7.0,
	# everyday clothes: wraps under the breeches, a tunic over the trousers, a vest, an apron, a belt, a hooded capelet
	"wraps": 0.9, "tunic": 1.2, "vest": 2.2, "apron": 2.6, "belt": 2.9, "hood": 4.2}
static var _layer_shaders := {}   # cull mode -> Shader


static func skeleton_of(node: Node) -> Skeleton3D:
	if node is Skeleton3D:
		return node
	var found := node.find_children("*", "Skeleton3D", true, false)
	return found[0] if found.size() > 0 else null


## Puts the piece on the character: returns its meshes (now children of the character's Skeleton3D).
## mask: the body it hides (default: <piece>.mask.json beside the piece's file).
## layer: its layer set by hand (its .fit.json «layer»), else (-1) by its kind (LAYER).
static func wear(character: Node, piece: PackedScene, mask := "", layer := -1.0) -> Array[MeshInstance3D]:
	var out: Array[MeshInstance3D] = []
	var skel := skeleton_of(character)
	if skel == null or piece == null:
		push_warning("SF3DEquip: no skeleton under %s, or no piece" % character)
		return out
	var inst := piece.instantiate()
	var own := skeleton_of(inst)
	var cloth := _add_cloth_bones(own, skel) if own else []
	var hair_chains := _add_cloth_bones(own, skel, "Hair_") if own else []   # (a hairstyle made with springs)
	var hem_chains := _add_cloth_bones(own, skel, "Hem_") if own else []   # (a tunic's, a vest's, an apron's hem on springs)
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
	var kind := piece.resource_path.get_file().get_basename().trim_prefix("wear_").trim_prefix("proc_").get_slice("_", 0)
	for mi in out:
		mi.set_meta("sf3d_kind", kind)
	for mi in out:   # brows, lashes: fine hairs on the face - no shadows (a card's whole shape fell on the cheek)
		if kind in ["brows", "lashes"] or String(mi.name).begins_with("brows") or String(mi.name).begins_with("lashes"):
			mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	if layered and (LAYER.has(kind) or layer >= 0.0):   # (a weapon, a shield, a quiver: in a hand or on a strap, not in the layers)
		for mi in out:
			if not mi.has_meta("sf3d_hold"):
				mi.set_meta("sf3d_layer", layer if layer >= 0.0 else float(LAYER[kind]))
				_layer(mi, 0.0)
		_rank_layers(skel)
	if keep_off_body and kind == "shield":   # (the clips are made for a smaller one: kept off the legs and the body)
		for mi in out:
			_grip(skel).keep_flex = keep_flex
			_grip(skel).keep_debug = keep_debug
			_grip(skel).keep_apply = keep_apply
			_grip(skel).keep_off(mi, true)
	if not cloth.is_empty() and out.size() > 0:   # a cloak: its chains swing
		out[0].set_meta("sf3d_cloth", _cloth(skel, cloth, home_grid))
	if springs and not hair_chains.is_empty() and out.size() > 0:   # hair: its strands' chains swing (spring bones)
		out[0].set_meta("sf3d_springs", _hair_springs(skel, hair_chains))
	if springs and not hem_chains.is_empty() and out.size() > 0:   # a hem: its columns swing round the legs (spring bones)
		out[0].set_meta("sf3d_springs", _hem_springs(skel, hem_chains))
	if out.size() > 0:
		var path := mask if mask != "" else piece.resource_path.get_basename() + ".mask.json"
		var keys := _mask_keys(path)
		var press := _mask_press(path)
		if not keys.is_empty() or not press.is_empty():
			out[0].set_meta("sf3d_mask", keys)
			out[0].set_meta("sf3d_press", press)
			out[0].set_meta("sf3d_character", character)
			_hide_body(character)
	if out.size() > 0 and (kind in CINCH_BELTS or kind in CINCH_SOFT):   # a belt over clothes cinches them
		_cinch(skel)
	return out


# every layered piece on this skeleton pushed by the rank of its layer among the ones worn (taken off: theirs gone)
static func _rank_layers(skel: Skeleton3D) -> void:
	var meshes := skel.get_children().filter(func(n): return n is MeshInstance3D and n.has_meta("sf3d_layer"))
	var values := []
	for mi in meshes:
		if not float(mi.get_meta("sf3d_layer")) in values:
			values.append(float(mi.get_meta("sf3d_layer")))
	values.sort()
	var step := _height(skel) * minf(DEPTH_STEP, DEPTH_MAX / maxf(values.size(), 1.0))
	for mi in meshes:
		var push := step * (values.find(float(mi.get_meta("sf3d_layer"))) + 1)
		for s in mi.mesh.get_surface_count():
			var m := mi.get_surface_override_material(s) as ShaderMaterial
			if m and m.has_meta("sf3d_push"):
				m.set_meta("sf3d_push", push)
				if float(m.get_shader_parameter("sf3d_depth_push")) > 0.0 or bool(m.get_meta("sf3d_on", true)):
					m.set_shader_parameter("sf3d_depth_push", push)


static func _height(skel: Skeleton3D) -> float:   # the skeleton's height at rest
	var lo := INF
	var hi := -INF
	for i in skel.get_bone_count():
		var y := skel.get_bone_global_rest(i).origin.y
		lo = minf(lo, y)
		hi = maxf(hi, y)
	return maxf(hi - lo, 0.01) * 1.08   # (the head's top and the soles past the end joints)


# its surfaces drawn by LAYER_SHADER with their materials' looks and the layer's push (a blended, see-through one kept)
static func _layer(mi: MeshInstance3D, push: float) -> void:
	if mi.mesh == null:
		return
	for s in mi.mesh.get_surface_count():
		var m := mi.get_active_material(s) as BaseMaterial3D
		if m == null or m.transparency in [BaseMaterial3D.TRANSPARENCY_ALPHA, BaseMaterial3D.TRANSPARENCY_ALPHA_DEPTH_PRE_PASS]:
			continue
		var cull: String = ["cull_back", "cull_front", "cull_disabled"][m.cull_mode]
		if not _layer_shaders.has(cull):
			var sh := Shader.new()
			sh.code = LAYER_SHADER.replace("@CULL@", cull)
			_layer_shaders[cull] = sh
		var sm := ShaderMaterial.new()
		sm.shader = _layer_shaders[cull]
		var ch := func(c: int) -> Vector4: return Vector4(0.333, 0.333, 0.333, 0) if c == 4 else Vector4(float(c == 0), float(c == 1), float(c == 2), float(c == 3))
		sm.set_shader_parameter("albedo", m.albedo_color)
		sm.set_shader_parameter("texture_albedo", m.albedo_texture)
		sm.set_shader_parameter("use_albedo_texture", m.albedo_texture != null)
		sm.set_shader_parameter("use_vertex_color", m.vertex_color_use_as_albedo)
		sm.set_shader_parameter("metallic", m.metallic)
		sm.set_shader_parameter("roughness", m.roughness)
		sm.set_shader_parameter("texture_metallic", m.metallic_texture)
		sm.set_shader_parameter("metallic_channel", ch.call(m.metallic_texture_channel))
		sm.set_shader_parameter("texture_roughness", m.roughness_texture)
		sm.set_shader_parameter("roughness_channel", ch.call(m.roughness_texture_channel))
		sm.set_shader_parameter("use_normal", m.normal_enabled and m.normal_texture != null)
		sm.set_shader_parameter("texture_normal", m.normal_texture)
		sm.set_shader_parameter("normal_scale", m.normal_scale)
		if m.emission_enabled:
			sm.set_shader_parameter("emission", m.emission)
			sm.set_shader_parameter("texture_emission", m.emission_texture)
			sm.set_shader_parameter("emission_energy", m.emission_energy_multiplier)
		sm.set_shader_parameter("uv1_scale", m.uv1_scale)
		sm.set_shader_parameter("uv1_offset", m.uv1_offset)
		sm.set_shader_parameter("alpha_scissor", m.alpha_scissor_threshold if m.transparency == BaseMaterial3D.TRANSPARENCY_ALPHA_SCISSOR else -1.0)
		sm.set_shader_parameter("sf3d_depth_push", push)
		sm.set_meta("sf3d_push", push)
		mi.set_surface_override_material(s, sm)


## The layers' rule on or off for these meshes (a piece's, as wear() returns them): off, each is drawn where it is.
static func layers(meshes: Array, on: bool) -> void:
	for mi in meshes:
		if not is_instance_valid(mi) or mi.mesh == null:
			continue
		for s in mi.mesh.get_surface_count():
			var m := mi.get_surface_override_material(s) as ShaderMaterial
			if m and m.has_meta("sf3d_push"):
				m.set_meta("sf3d_on", on)
				m.set_shader_parameter("sf3d_depth_push", float(m.get_meta("sf3d_push")) if on else 0.0)


# a worn piece's look (the StandardMaterial3D features the GLB's materials use) with its layer's push (_layer)
const LAYER_SHADER := """shader_type spatial;
render_mode blend_mix, depth_draw_opaque, @CULL@, diffuse_burley, specular_schlick_ggx;
uniform vec4 albedo : source_color = vec4(1.0);
uniform sampler2D texture_albedo : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform bool use_albedo_texture = false;
uniform bool use_vertex_color = false;
uniform float metallic = 0.0;
uniform float roughness = 1.0;
uniform sampler2D texture_metallic : hint_default_white, filter_linear_mipmap_anisotropic, repeat_enable;
uniform vec4 metallic_channel = vec4(0.0, 0.0, 1.0, 0.0);
uniform sampler2D texture_roughness : hint_default_white, filter_linear_mipmap_anisotropic, repeat_enable;
uniform vec4 roughness_channel = vec4(0.0, 1.0, 0.0, 0.0);
uniform sampler2D texture_normal : hint_roughness_normal, filter_linear_mipmap_anisotropic, repeat_enable;
uniform bool use_normal = false;
uniform float normal_scale = 1.0;
uniform vec4 emission : source_color = vec4(0.0, 0.0, 0.0, 1.0);
uniform sampler2D texture_emission : source_color, hint_default_black, filter_linear_mipmap_anisotropic, repeat_enable;
uniform float emission_energy = 0.0;
uniform vec3 uv1_scale = vec3(1.0);
uniform vec3 uv1_offset = vec3(0.0);
uniform float alpha_scissor = -1.0;
uniform float sf3d_depth_push = 0.0;

void vertex() {
	UV = UV * uv1_scale.xy + uv1_offset.xy;
	// nearer the camera by the push along its own ray, its place on the screen kept; not in a shadow's pass (the light's
	// view: a pushed caster would shadow itself)
	// (POSITION written here is the only one: written on every path)
	bool shadow_pass = distance(INV_VIEW_MATRIX[3].xyz, MAIN_CAM_INV_VIEW_MATRIX[3].xyz) > 0.0001;
	vec4 v = MODELVIEW_MATRIX * vec4(VERTEX, 1.0);
	vec4 c = PROJECTION_MATRIX * v;
	if (sf3d_depth_push > 0.0 && !shadow_pass) {
		vec3 d = PROJECTION_MATRIX[3][3] > 0.5 ? vec3(0.0, 0.0, 1.0) : normalize(-v.xyz);
		vec4 p = PROJECTION_MATRIX * vec4(v.xyz + d * min(sf3d_depth_push, 0.9 * length(v.xyz)), 1.0);
		c.z = p.z / p.w * c.w;
	}
	POSITION = c;
}

void fragment() {
	vec4 a = albedo;
	if (use_albedo_texture) a *= texture(texture_albedo, UV);
	if (use_vertex_color) a *= COLOR;
	if (alpha_scissor >= 0.0 && a.a < alpha_scissor) discard;
	ALBEDO = a.rgb;
	METALLIC = metallic * dot(texture(texture_metallic, UV), metallic_channel);
	ROUGHNESS = roughness * dot(texture(texture_roughness, UV), roughness_channel);
	if (use_normal) {
		NORMAL_MAP = texture(texture_normal, UV).rgb;
		NORMAL_MAP_DEPTH = normal_scale;
	}
	EMISSION = (emission.rgb + texture(texture_emission, UV).rgb) * emission_energy;
}
"""


# A cloak's cloth bones («Cloth_<column>_<link>», blender_armour_gen.py) are the piece's own: they are added to the
# character's skeleton, each where it is in the piece at rest (the global rest kept: the character's GLB may be another
# export of the rig, its bones' axes turned). Returns the chains: [[bone names from the top down], ...].
static func _add_cloth_bones(own: Skeleton3D, skel: Skeleton3D, prefix := "Cloth_") -> Array:
	var chains := {}
	for i in own.get_bone_count():   # parents come before their children in a skeleton
		var n := String(own.get_bone_name(i))
		if not n.begins_with(prefix):   # (a cloak's «Cloth_», a hairstyle's «Hair_<chain>_<link>»: the same way)
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
		elif prefix in ["Hair_", "Hem_"]:   # (another hairstyle, hem worn before: its chains were elsewhere - this one's rest)
			var b := skel.find_bone(n)
			var pi := skel.get_bone_parent(b)
			if pi >= 0:
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


## A hairstyle's chains (blender_hair_gen.py «spring»: Hair_<chain>_<link> from the head down, the last a short end)
## as Godot's own spring bones (SpringBoneSimulator3D, VRM's way): each chain keeps to its rest shape (stiffness), loses
## its speed (drag), and goes round the head (a sphere as the skull: from the head's joint to its top), the neck, the
## chest and the shoulders (capsules as thick as the skin round those bones: _thickness), its joints HAIR_R of the height
## thick. Returns the simulator (taken off with the piece).
const HAIR_STIFF := 0.5   # (to its rest shape; 0.55 with drag 0.4 and no gravity, as HairDeck's VRM export, flung it out on a quick turn)
const HAIR_DRAG := 0.5
const HAIR_GRAVITY := 1.5   # (without it the strands kept their shape on the head: a head bowed in a clip stood them out behind)
const HAIR_R := 0.012   # a joint's radius, in heights


## After a jump of the pose (a clip seeked, the character put somewhere else, spawned): the springs start from it at
## rest instead of being flung by the jump.
static func reset_springs(node: Node) -> void:
	var skel := skeleton_of(node)
	if skel == null:
		return
	for sim in skel.find_children("*", "SpringBoneSimulator3D", false, false):
		(sim as SpringBoneSimulator3D).reset()


## Spring bones on or off (a character far off, in a crowd: their cost is ~4-5 µs a joint a frame on a laptop CPU -
## a hem ~0.2 ms, long hair ~0.5 ms a character; off, the hair and the hem stay as made on the head and the thighs).
## Turned on again they start from the pose then (reset).
static func springs_active(node: Node, on: bool) -> void:
	var skel := skeleton_of(node)
	if skel == null:
		return
	for sim in skel.find_children("*", "SpringBoneSimulator3D", false, false):
		var s := sim as SpringBoneSimulator3D
		if on and not s.active:
			s.reset()
		s.active = on


static func _bone_by(skel: Skeleton3D, suffixes: Array) -> String:
	for i in skel.get_bone_count():
		for sfx in suffixes:
			if String(skel.get_bone_name(i)).ends_with(sfx):
				return String(skel.get_bone_name(i))
	return ""


static func _hair_springs(skel: Skeleton3D, chains: Array) -> SpringBoneSimulator3D:
	var h := _height(skel)
	var spheres := []
	var head_n := _bone_by(skel, ["Head"])
	var top_n := _bone_by(skel, ["HeadTop_End", "Head_end", "head_top"])
	if head_n != "":   # the skull: a sphere half way up from the head's joint to its top
		var hp := skel.get_bone_global_rest(skel.find_bone(head_n)).origin
		var tp := skel.get_bone_global_rest(skel.find_bone(top_n)).origin if top_n != "" else hp + Vector3.UP * 0.15 * h
		var hh := hp.distance_to(tp)
		# the face: in front of the skull - the model faces +Z; the strands kept off it as made fell over it as the head bowed
		spheres = [[head_n, hp.lerp(tp, 0.52), 0.46 * hh], [head_n, hp.lerp(tp, 0.35) + Vector3(0, 0, 1) * 0.42 * hh, 0.36 * hh]]
	var segs := [[["Neck"], ["Head"]], [["Spine2", "UpperChest"], ["Neck"]], [["Spine1", "Chest"], ["Spine2", "UpperChest"]]]
	for side in ["Left", "Right"]:
		for pair in [[["Shoulder"], ["Arm", "UpperArm"]], [["Arm", "UpperArm"], ["ForeArm", "LowerArm"]]]:
			segs.append([pair[0].map(func(x): return side + x), pair[1].map(func(x): return side + x)])
	return _springs(skel, chains, "SF3DHairSprings", HAIR_STIFF, HAIR_DRAG, HAIR_GRAVITY, HAIR_R * h, spheres, segs)


## An everyday garment's hem (blender_armour_gen.py «hem_spring»: Hem_<column>_<joint> from the hips down, a tunic's, a
## vest's, an apron's) on spring bones, as hair: the legs (thighs, shins) and the pelvis as capsules push it as they move.
const HEM_STIFF := 3.0   # (0.6 with gravity 1.5: the hem hung straight from the thigh and the leg went through it)
const HEM_DRAG := 0.5
const HEM_GRAVITY := 0.5
const HEM_R := 0.006   # a joint's radius, in heights (cloth: thin)


static func _hem_springs(skel: Skeleton3D, chains: Array) -> SpringBoneSimulator3D:
	var segs := [[["Hips"], ["Spine"]]]
	for side in ["Left", "Right"]:
		for pair in [[["UpLeg", "UpperLeg"], ["Leg", "LowerLeg"]], [["Leg", "LowerLeg"], ["Foot"]]]:
			segs.append([pair[0].map(func(x): return side + x), pair[1].map(func(x): return side + x)])
	return _springs(skel, chains, "SF3DHemSprings", HEM_STIFF, HEM_DRAG, HEM_GRAVITY, HEM_R * _height(skel), [], segs, true)


## Spring bones on chains (each [bone names from its root down]): spheres [[bone, centre at rest, radius], ...] and
## capsules [[bone suffixes, next bone suffixes], ...] (as thick as the skin round the bone: _thickness) as colliders.
## The chains' joints as made (the first of a chain is held by its parent): no collider may hold one of them at rest -
## pushed out every frame and pulled back by its stiffness the hair stood up in a bush (a collider a little too thick,
## a strand lying on the neck): each is made no thicker than its nearest joint allows, dropped if that leaves too little.
static func _springs(skel: Skeleton3D, chains: Array, nm: String, stiff: float, drag: float, grav: float, jr: float,
		spheres: Array, seg_names: Array, full := false) -> SpringBoneSimulator3D:
	var sim := SpringBoneSimulator3D.new()
	sim.name = nm
	skel.add_child(sim)
	sim.setting_count = chains.size()
	for s in chains.size():
		var links: Array = chains[s]
		sim.set_root_bone_name(s, links[0])
		sim.set_end_bone_name(s, links[links.size() - 1])
		sim.set_stiffness(s, stiff)
		sim.set_drag(s, drag)
		sim.set_gravity(s, grav)
		sim.set_radius(s, jr)
		sim.set_enable_all_child_collisions(s, true)
	var joints := []   # [rest place, the chain's parent bone]
	var parents := []
	for links in chains:
		var pb := skel.get_bone_parent(skel.find_bone(links[0]))
		parents.append(String(skel.get_bone_name(pb)) if pb >= 0 else "")
		for k in range(1, links.size()):
			joints.append([skel.get_bone_global_rest(skel.find_bone(links[k])).origin, parents[parents.size() - 1]])
	# (to the nearest joint from the segment a..b, less a joint's radius; a chain hanging from that collider's own bone - a
	# hem's column on a thigh - goes with it: not counted, and it does not collide with it)
	var room := func(a: Vector3, b: Vector3, own := "") -> float:
		var m := INF
		for jp in joints:
			if own != "" and jp[1] == own:
				continue
			m = minf(m, Geometry3D.get_closest_point_to_segment(jp[0], a, b).distance_to(jp[0]))
		return m - 1.05 * jr
	for sc in spheres:
		var r := minf(float(sc[2]), room.call(sc[1], sc[1]))
		if r > 0.0:
			var sp := SpringBoneCollisionSphere3D.new()
			sp.bone_name = sc[0]
			sp.position_offset = skel.get_bone_global_rest(skel.find_bone(sc[0])).affine_inverse() * (sc[1] as Vector3)
			sp.radius = r
			sim.add_child(sp)
	var segs := []
	for pair in seg_names:
		segs.append([_bone_by(skel, pair[0]), _bone_by(skel, pair[1])])
	segs = segs.filter(func(sg): return sg[0] != "" and sg[1] != "" and sg[0] != sg[1])
	var thick := _thickness(skel, segs)
	for sg in segs:   # a capsule from a bone's joint to the next one's
		var ga := skel.get_bone_global_rest(skel.find_bone(sg[0]))
		var a := ga.origin
		var b := skel.get_bone_global_rest(skel.find_bone(sg[1])).origin
		# (full: as thick as the limb's fuller side - a hem; the thin measure keeps a skirt's capsule off the buttocks, the
		# hem then let a thigh through in a stride)
		var r0 := float(thick.get(sg[0] + ("#full" if full and ("Leg" in sg[0]) else ""), thick.get(sg[0], 0.04 * _height(skel))))
		var r := minf(r0, room.call(a, b, sg[0]))
		if r < 0.25 * r0:   # (the chains lie on it: no use)
			continue
		var cap := SpringBoneCollisionCapsule3D.new()
		cap.name = "Col_" + String(sg[0])
		cap.bone_name = sg[0]
		cap.radius = r
		cap.height = a.distance_to(b) + 2.0 * r
		var local_dir := (ga.basis.inverse() * (b - a)).normalized()
		cap.position_offset = ga.affine_inverse() * ((a + b) * 0.5)
		cap.rotation_offset = Quaternion(Vector3.UP, local_dir) if local_dir.length() > 0.5 else Quaternion.IDENTITY
		sim.add_child(cap)
		for s in chains.size():   # (a chain on this bone: not against it)
			if parents[s] == sg[0]:
				var n := sim.get_exclude_collision_count(s)
				sim.set_exclude_collision_count(s, n + 1)
				sim.set_exclude_collision_path(s, n, NodePath(cap.name))
	return sim


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
	var skels := []
	for mi in meshes:
		for meta in ["sf3d_cloth", "sf3d_springs"]:   # (a cloak's cloth, hair's spring bones)
			if is_instance_valid(mi) and mi.has_meta(meta):
				var sim = mi.get_meta(meta)
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
			var sk := mi.get_parent() as Skeleton3D
			mi.get_parent().remove_child(mi)
			mi.queue_free()
			if sk and not sk in skels:
				skels.append(sk)
	if character:
		_hide_body(character)
	for sk in skels:   # (a belt off: the clothes under it as made)
		_cinch(sk)


## Shows or hides a piece put on (the body under it comes back while it is hidden).
static func show(meshes: Array, on: bool) -> void:
	var character: Node = null
	var skels := []
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
			if mi.get_parent() is Skeleton3D and not mi.get_parent() in skels:
				skels.append(mi.get_parent())
	if character:
		_hide_body(character)
	for sk in skels:   # (a belt hidden: the clothes under it as made; shown: cinched)
		_cinch(sk)


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
## A lower piece's part that came out over a higher one hidden while that one is shown: keys, its points (thousandths,
## its meshes' own axes) as blender_layer_hide.py finds them - the armour editor's rule; a triangle goes when a corner
## of it is out.
static func hide_under(lower: Array, upper: Array, keys: Array) -> void:
	var k := {}
	for p in keys:
		k[Vector3i(int(p[0]), int(p[1]), int(p[2]))] = true
	for mi in lower:
		if is_instance_valid(mi):
			var list: Array = mi.get_meta("sf3d_under", [])
			list.append([upper, k])
			mi.set_meta("sf3d_under", list)
	if lower.size() > 0 and is_instance_valid(lower[0]):
		_hide_pieces(lower[0].get_parent())


# the pieces' meshes without their triangles with a corner out over a shown higher piece (the full mesh kept aside)
static func _hide_pieces(skel: Node) -> void:
	for node in skel.get_children():
		if not (node is MeshInstance3D and node.has_meta("sf3d_under")):
			continue
		var mi := node as MeshInstance3D
		if not mi.has_meta("sf3d_full_mesh"):
			mi.set_meta("sf3d_full_mesh", _as_made(mi))   # (not as a pressing piece pressed it: _press_cloth, after this)
		var full: Mesh = mi.get_meta("sf3d_full_mesh")
		var hide := {}
		for e in mi.get_meta("sf3d_under"):
			if (e[0] as Array).any(func(u): return is_instance_valid(u) and u.visible):
				hide.merge(e[1])
		if hide.is_empty():
			mi.mesh = full
			continue
		var am := ArrayMesh.new()
		for b in full.get_blend_shape_count():   # (its shape keys kept: brows, lashes move with the face)
			am.add_blend_shape(full.get_blend_shape_name(b))
		if full is ArrayMesh:
			am.blend_shape_mode = (full as ArrayMesh).blend_shape_mode
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
				if not (hid[idx[t]] or hid[idx[t + 1]] or hid[idx[t + 2]]):
					keep.append(idx[t]); keep.append(idx[t + 1]); keep.append(idx[t + 2])
			if keep.is_empty():   # (a surface all out: one degenerate triangle keeps the surface, its material's place)
				keep = PackedInt32Array([idx[0], idx[0], idx[0]])
			arrays[Mesh.ARRAY_INDEX] = keep
			am.add_surface_from_arrays(full.surface_get_primitive_type(s), arrays, full.surface_get_blend_shape_arrays(s))
			am.surface_set_material(s, full.surface_get_material(s))
		mi.mesh = am
	_press_cloth(skel)   # (the last step every change of what is worn or shown ends with)


## Cloth worn under a piece that presses the skin in is pressed in with it (2026-11-27; SF3D's game_bake and the game's
## ArmourDressing do the same): the skin under a cuirass, a cuisse, a mail shirt goes into the body (its mask's moves), and a
## shirt over that skin stayed where it was and came out through the cuirass where the skin had. Each cloth vertex moves as
## the nearest pressed skin vertex within PRESS_REACH, and only by the pressing pieces on a higher layer than its own (a mail
## shirt is not pressed by its own mask); under two of them the deeper move. The mesh the steps before made is kept aside
## («sf3d_press_src»), so the cloth comes back when the cuirass comes off and is never pressed twice.
const PRESSED_UNDER := ["undercloth", "trousers", "brayette", "hauberk", "gambeson", "tunic", "vest"]
const PRESSING := ["cuirass", "cuisse", "rerebrace", "bracer", "greave", "pauldron", "brayette", "tassets", "pelerine", "hauberk", "footwear"]
const PRESS_REACH := 0.04   # of the body's height: a cloth vertex this near a pressed skin vertex moves as it


static func _press_cloth(skel: Node) -> void:
	var pressers := []   # [its layer, its moves] of each shown pressing piece
	var cloth := []
	var character: Node = null
	for node in skel.get_children():
		if not (node is MeshInstance3D and node.has_meta("sf3d_kind")):
			continue
		var k := String(node.get_meta("sf3d_kind"))
		if node.has_meta("sf3d_character"):
			character = node.get_meta("sf3d_character")
		if k in PRESSING and node.visible and not (node.get_meta("sf3d_press", {}) as Dictionary).is_empty():
			pressers.append([float(node.get_meta("sf3d_layer", LAYER.get(k, 0.0))), node.get_meta("sf3d_press")])
		if k in PRESSED_UNDER:
			cloth.append(node)
	if cloth.is_empty():
		return
	if character == null or not is_instance_valid(character):
		character = skel.get_parent()
	var body := _skin_mesh(character)
	var reach := PRESS_REACH * _height(skel as Skeleton3D) if skel is Skeleton3D else PRESS_REACH
	for mi in cloth:
		var src: Mesh = _as_made(mi)
		var own := float(mi.get_meta("sf3d_layer", LAYER.get(String(mi.get_meta("sf3d_kind")), 0.0)))
		var press := {}
		for p in pressers:
			if float(p[0]) > own:
				_merge_deeper(press, p[1])
		var out: Mesh = src
		if not press.is_empty() and body != null and src != null:
			var key := [src.get_instance_id(), press.size(), press.hash()]
			if mi.get_meta("sf3d_press_key", []) == key:   # (the same mesh under the same presses: pressed already)
				out = mi.get_meta("sf3d_press_done")
			else:
				out = _follow(src, press, _relative(character, body).affine_inverse() * _relative(character, mi), reach)
				mi.set_meta("sf3d_press_key", key)
				mi.set_meta("sf3d_press_done", out)
		mi.set_meta("sf3d_press_src", src)
		mi.set_meta("sf3d_press_out", out)
		mi.mesh = out


# a piece's mesh as the steps before the cloth press made it (its pressed one is not made again from itself)
static func _as_made(mi: MeshInstance3D) -> Mesh:
	if mi.has_meta("sf3d_press_out") and mi.mesh == mi.get_meta("sf3d_press_out"):
		return mi.get_meta("sf3d_press_src")
	return mi.mesh


# `from`'s moves put into `into`; a place two pieces press (a cuirass over a mail shirt) keeps the deeper move, not the first
static func _merge_deeper(into: Dictionary, from: Dictionary) -> void:
	if into.is_empty():
		into.merge(from)
		return
	for k in from:
		if not into.has(k) or (from[k] as Vector3).length_squared() > (into[k] as Vector3).length_squared():
			into[k] = from[k]


# the character's skin: its mesh (not a piece's) with the most vertices, as made - the masks' places are its own
static func _skin_mesh(character: Node) -> MeshInstance3D:
	var best: MeshInstance3D = null
	var most := -1
	for node in character.find_children("*", "MeshInstance3D", true, false):
		var mi := node as MeshInstance3D
		if mi.has_meta("sf3d_piece") or mi.mesh == null:
			continue
		var m: Mesh = mi.get_meta("sf3d_body_mesh", mi.mesh)
		var n := 0
		for s in m.get_surface_count():
			n += m.surface_get_array_len(s)
		if n > most:
			most = n
			best = mi
	return best


# `full` (a cloth mesh; `xf` its places into the skin mesh's) with each vertex moved as the nearest pressed skin place
# within `reach` (a grid of cells that size over the pressed places)
static func _follow(full: Mesh, press: Dictionary, xf: Transform3D, reach: float) -> Mesh:
	var cell := maxf(reach, 1e-4)
	var grid := {}
	var lo := Vector3(INF, INF, INF)
	var hi := -lo
	for k in press:
		var at := Vector3(k) * 0.001
		lo = lo.min(at)
		hi = hi.max(at)
		var c := Vector3i((at / cell).floor())
		if not grid.has(c):
			grid[c] = []
		grid[c].append([at, press[k]])
	lo -= Vector3.ONE * reach
	hi += Vector3.ONE * reach
	var back := xf.basis.inverse()
	var am := ArrayMesh.new()
	for b in full.get_blend_shape_count():
		am.add_blend_shape(full.get_blend_shape_name(b))
	if full is ArrayMesh:
		am.blend_shape_mode = (full as ArrayMesh).blend_shape_mode
	for s in full.get_surface_count():
		var arrays := full.surface_get_arrays(s)
		var verts: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
		for i in verts.size():
			var p := xf * verts[i]
			if p.x < lo.x or p.y < lo.y or p.z < lo.z or p.x > hi.x or p.y > hi.y or p.z > hi.z:
				continue
			var c := Vector3i((p / cell).floor())
			var best := reach * reach
			var d = null
			for dx in [-1, 0, 1]:
				for dy in [-1, 0, 1]:
					for dz in [-1, 0, 1]:
						for e in grid.get(c + Vector3i(dx, dy, dz), []):
							var q := p.distance_squared_to(e[0])
							if q < best:
								best = q
								d = e[1]
			if d != null:
				verts[i] += back * (d as Vector3)
		arrays[Mesh.ARRAY_VERTEX] = verts
		am.add_surface_from_arrays(full.surface_get_primitive_type(s), arrays, full.surface_get_blend_shape_arrays(s))
		am.surface_set_material(s, full.surface_get_material(s))
	return am


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
			if p.size() == 3:   # (of six: a vertex moved, _mask_press)
				keys[Vector3i(int(p[0]), int(p[1]), int(p[2]))] = true
	return keys


## The body's vertices a piece moves while it is on (an ear laid against the head, under a helmet: body_mask.head_cover):
## the mask's entries of six - where the vertex is and how far it goes, thousandths of a unit.
static func _mask_press(path: String) -> Dictionary:
	var moved := {}
	if not FileAccess.file_exists(path):
		return moved
	var data = JSON.parse_string(FileAccess.get_file_as_string(path))
	if data is Array:
		for p in data:
			if p.size() == 6:
				moved[Vector3i(int(p[0]), int(p[1]), int(p[2]))] = Vector3(p[3], p[4], p[5]) * 0.001
	return moved


static func _press_at(moved: Dictionary, v: Vector3) -> Variant:   # (found as _in_mask finds a place)
	var opts := []
	for c in [v.x, v.y, v.z]:
		var q: float = c * 1000.0
		var r := roundi(q)
		var f := q - r
		opts.append([r, r + (1 if f > 0 else -1)] if absf(f) > 0.3 else [r])
	for a in opts[0]:
		for b in opts[1]:
			for c in opts[2]:
				var k := Vector3i(a, b, c)
				if moved.has(k):
					return moved[k]
	return null


## The body's meshes without the triangles whose three corners every shown piece's mask hides (the full mesh is kept
## aside, so pieces can come off again).
static func _hide_body(character: Node) -> void:
	var skel := skeleton_of(character)
	if skel == null:
		return
	var hide := {}   # (and the pieces' parts out over shown higher ones: _hide_pieces, at the end)
	var press := {}
	for node in skel.get_children():
		if node is MeshInstance3D and node.has_meta("sf3d_mask") and node.visible:
			hide.merge(node.get_meta("sf3d_mask"))
			_merge_deeper(press, node.get_meta("sf3d_press", {}))   # (under two pressing pieces: the deeper move)
	for node in character.find_children("*", "MeshInstance3D", true, false):
		var mi := node as MeshInstance3D
		if mi.has_meta("sf3d_piece") or mi.mesh == null:
			continue
		if not mi.has_meta("sf3d_body_mesh"):
			mi.set_meta("sf3d_body_mesh", mi.mesh)
		var full: Mesh = mi.get_meta("sf3d_body_mesh")
		if hide.is_empty() and press.is_empty():
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
			if not press.is_empty():   # (after the look-ups: the masks are written for the places at rest)
				for i in verts.size():
					var d = _press_at(press, verts[i])
					if d != null:
						verts[i] += d
						taken += 1
				arrays[Mesh.ARRAY_VERTEX] = verts
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
	_hide_pieces(skel)


## A belt worn over clothes cinches them (the user: «a belt over clothes must draw them in at the waist»), whatever was
## made with what: each soft piece under a shown belt (CINCH_SOFT, a lower layer) pressed in under its band at rest -
## its outside no farther out than the band's inside, coming out of it at a slant above and below (CINCH_SLOPE), its
## thickness kept, never into the body - and gathered in folds above and below it where it had to be pressed (one made
## under that belt fits it already: nothing added again). As the armour editor's cinchPoints, here by the meshes'
## points in cells round the torso's axis (hips to neck) instead of rays. The band: the belt's rows that go all round
## (its pouches, its buckle's frame do not). The soft pieces' meshes as made kept aside («sf3d_cinch_base»).
const CINCH_SOFT := ["undercloth", "trousers", "tunic", "vest"]
const CINCH_BELTS := ["belt"]
const CINCH_SLOPE := 0.6   # across per along
const CINCH_TAPER := 30.0   # mm so far above and below the band (past it free: breeches' legs, a skirt's flare)
const CINCH_GATHER := 7.0   # mm (on a man 1.75 m tall): the folds out at the band's edges
const CINCH_REACH := 75.0   # mm the folds reach up and down
const CINCH_FOLDS := 9   # round the body
const CINCH_NA := 72


static func _cinch(skel: Skeleton3D) -> void:
	if skel == null:
		return
	var soft: Array = []
	var belts: Array = []
	for node in skel.get_children():
		if node is MeshInstance3D and node.has_meta("sf3d_kind"):
			var k := String(node.get_meta("sf3d_kind"))
			if k in CINCH_BELTS:
				belts.append(node)
			elif k in CINCH_SOFT:
				soft.append(node)
	for mi in soft + belts:   # (as made first)
		if not mi.has_meta("sf3d_cinch_base"):
			mi.set_meta("sf3d_cinch_base", mi.get_meta("sf3d_full_mesh") if mi.has_meta("sf3d_full_mesh") else _as_made(mi))   # (not pressed: _press_cloth)
	var lay := func(mi) -> float: return float(mi.get_meta("sf3d_layer", LAYER.get(String(mi.get_meta("sf3d_kind")), 0.0)))
	soft.sort_custom(func(x, y): return lay.call(x) < lay.call(y))   # (inside first: each lies over those under it)
	var shown := belts.filter(func(bt): return bt.visible)
	var ctx := {}
	if not shown.is_empty():
		var hips := _bone_named(skel, "hips")
		var neck := _bone_named(skel, "neck")
		if hips >= 0 and neck >= 0:
			var a := skel.get_bone_global_rest(hips).origin
			var b := skel.get_bone_global_rest(neck).origin
			if a.distance_to(b) > 1e-4:
				var u := (b - a).normalized()
				var p1 := (Vector3.FORWARD if absf(u.dot(Vector3.FORWARD)) < 0.9 else Vector3.RIGHT)
				p1 = (p1 - u * p1.dot(u)).normalized()
				ctx = _cinch_ctx({"a": a, "u": u, "p1": p1, "p2": u.cross(p1), "mm": _height(skel) / 1.75 / 1000.0}, shown)
	var low := 99.0
	for bt in shown:
		low = minf(low, lay.call(bt))
	for mi in soft:
		var base: Mesh = mi.get_meta("sf3d_cinch_base")
		var pressed: Mesh = base if ctx.is_empty() or lay.call(mi) >= low else _cinch_mesh(skel, mi, base, ctx)
		_set_mesh(mi, pressed)
	# the belt out over the clothes pressed under it where they are thicker than its room (made over one layer, worn
	# over three): each way round by what they stand out of its band's inside, all of it (its pouches with it)
	for bt in belts:
		var base: Mesh = bt.get_meta("sf3d_cinch_base")
		_set_mesh(bt, base if ctx.is_empty() or not bt.visible else _belt_out(bt, base, ctx))
	_hide_pieces(skel)


static func _set_mesh(mi: MeshInstance3D, m: Mesh) -> void:
	mi.mesh = m
	if mi.has_meta("sf3d_full_mesh"):
		mi.set_meta("sf3d_full_mesh", m)


static func _bone_named(skel: Skeleton3D, word: String) -> int:   # «mixamorig_Hips» (the import's «:» -> «_»), «Hips», «hips»
	for i in skel.get_bone_count():
		var n := skel.get_bone_name(i).to_lower()
		if n == word or n.ends_with("_" + word) or n.ends_with(":" + word):
			return i
	return -1


# a point in the cells round the axis: [along (m), angle (rad), radius]
static func _cyl(ax: Dictionary, p: Vector3) -> Vector3:
	var d: Vector3 = p - ax["a"]
	var s: float = d.dot(ax["u"])
	d -= ax["u"] * s
	return Vector3(s, atan2(d.dot(ax["p2"]), d.dot(ax["p1"])), d.length())


static func _cells(nr: int, na: int, v: float) -> Array:
	var g := []
	for i in nr:
		var row := []
		row.resize(na)
		row.fill(v)
		g.append(row)
	return g


static func _col(ang: float) -> int:
	return posmod(int(floor((ang / TAU + 1.0) * CINCH_NA)), CINCH_NA)


# the belts' band (their rows that go all round, from their points binned), the wall it makes in cells round the axis
# (its inside, out of it at a slant up to CINCH_TAPER), and the stack of what is pressed under it so far: {} if none
static func _cinch_ctx(ax: Dictionary, belts: Array) -> Dictionary:
	var mm: float = ax["mm"]
	var NA := CINCH_NA
	var ds := 4.0 * mm
	var bp := []
	var s_lo := INF
	var s_hi := -INF
	for bt in belts:
		var m: Mesh = bt.get_meta("sf3d_cinch_base")
		var tr: Transform3D = bt.transform
		for sfc in m.get_surface_count():
			for v in m.surface_get_arrays(sfc)[Mesh.ARRAY_VERTEX]:
				var c := _cyl(ax, tr * v)
				bp.append(c)
				s_lo = minf(s_lo, c.x)
				s_hi = maxf(s_hi, c.x)
	if bp.is_empty():
		return {}
	var nb := int((s_hi - s_lo) / ds) + 1
	var bmin := _cells(nb, NA, INF)
	for c in bp:
		var i := mini(nb - 1, int((c.x - s_lo) / ds))
		var j := _col(c.y)
		bmin[i][j] = minf(bmin[i][j], c.z)
	var band := []
	for i in nb:
		var filled := 0
		for j in NA:
			if bmin[i][j] < INF:
				filled += 1
		if filled >= int(NA * 0.75):
			band.append(i)
	if band.is_empty():
		return {}
	var b0: float = s_lo + band[0] * ds
	var b1: float = s_lo + (band[-1] + 1) * ds
	var reach := CINCH_REACH * mm
	var S0 := b0 - reach - 40.0 * mm
	var NR := int((b1 + reach + 40.0 * mm - S0) / ds) + 1
	var wall := _cells(NR, NA, INF)
	var band_in := _cells(NR, NA, INF)   # (the band's own inside, its rows)
	for i in band:
		var r := int((s_lo + i * ds + 0.5 * ds - S0) / ds)
		if r < 0 or r >= NR:
			continue
		var src: Array = bmin[i]
		for j in NA:
			var w: float = src[j]
			if w == INF:   # (a gap round: the nearest of its row)
				for k in range(1, NA / 2):
					w = minf(src[posmod(j + k, NA)], src[posmod(j - k, NA)])
					if w < INF:
						break
			band_in[r][j] = minf(band_in[r][j], w)
			wall[r][j] = minf(wall[r][j], w - 0.8 * mm)
	var sl := CINCH_SLOPE * ds
	for i in range(1, NR):
		for j in NA:
			wall[i][j] = minf(wall[i][j], wall[i - 1][j] + sl)
	for i in range(NR - 2, -1, -1):
		for j in NA:
			wall[i][j] = minf(wall[i][j], wall[i + 1][j] + sl)
	for i in NR:
		var si := S0 + (i + 0.5) * ds
		if si < b0 - CINCH_TAPER * mm or si > b1 + CINCH_TAPER * mm:
			for j in NA:
				wall[i][j] = INF
	return {"ax": ax, "mm": mm, "ds": ds, "S0": S0, "NR": NR, "b0": b0, "b1": b1, "wall": wall, "band_in": band_in,
		"stack": _cells(NR, NA, -INF)}


static func _cinch_mesh(skel: Skeleton3D, mi: MeshInstance3D, base: Mesh, ctx: Dictionary) -> Mesh:
	var ax: Dictionary = ctx["ax"]
	var mm: float = ctx["mm"]
	var ds: float = ctx["ds"]
	var S0: float = ctx["S0"]
	var NR: int = ctx["NR"]
	var NA := CINCH_NA
	var wall: Array = ctx["wall"]
	var stack: Array = ctx["stack"]
	var tr: Transform3D = mi.transform
	var arrs := []
	var outer := _cells(NR, NA, -INF)
	var inner := _cells(NR, NA, INF)
	for sfc in base.get_surface_count():
		var arrays := base.surface_get_arrays(sfc)
		arrs.append(arrays)
		for v in arrays[Mesh.ARRAY_VERTEX]:
			var c := _cyl(ax, tr * v)
			var i := int((c.x - S0) / ds)
			if i < 0 or i >= NR:
				continue
			var j := _col(c.y)
			outer[i][j] = maxf(outer[i][j], c.z)
			inner[i][j] = minf(inner[i][j], c.z)
	# what is under it: the body's outermost there (not an arm past it) and the pieces pressed under the belt before it
	var floor_ := _cells(NR, NA, -INF)
	for node in skel.find_children("*", "MeshInstance3D", true, false):
		var bm := node as MeshInstance3D
		if bm.has_meta("sf3d_piece") or bm.mesh == null:
			continue
		var m: Mesh = bm.get_meta("sf3d_body_mesh") if bm.has_meta("sf3d_body_mesh") else bm.mesh
		var btr := _relative(skel, bm)
		for sfc in m.get_surface_count():
			for v in m.surface_get_arrays(sfc)[Mesh.ARRAY_VERTEX]:
				var c := _cyl(ax, btr * v)
				var i := int((c.x - S0) / ds)
				if i < 0 or i >= NR:
					continue
				var j := _col(c.y)
				if inner[i][j] < INF and c.z <= inner[i][j] + 5.0 * mm:
					floor_[i][j] = maxf(floor_[i][j], c.z)
	var press := _cells(NR, NA, 0.0)
	var most := 0.0
	for i in NR:
		for j in NA:
			var fl: float = maxf(floor_[i][j], stack[i][j])
			if wall[i][j] < INF and outer[i][j] > -INF and fl > -INF:   # (nothing under it there - between the legs: not drawn in)
				var m: float = outer[i][j] - wall[i][j]
				if m > 0.0:
					press[i][j] = clampf(minf(m, inner[i][j] - fl - 0.5 * mm), 0.0, m)
					most = maxf(most, press[i][j])
	var pressed := most >= 1.5 * mm   # (else made under it, or loose enough: as it is, no folds added again)
	var at := func(s: float, ang: float) -> float:
		var x := (s - S0) / ds - 0.5
		if x < 0.0 or x > NR - 1:
			return 0.0
		var i := mini(NR - 2, int(floor(x)))
		var f := x - i
		var y := (ang / TAU + 1.0) * NA - 0.5
		var j := posmod(int(floor(y)), NA)
		var g: float = y - floor(y)
		var j1 := (j + 1) % NA
		return (press[i][j] * (1.0 - g) + press[i][j1] * g) * (1.0 - f) + (press[i + 1][j] * (1.0 - g) + press[i + 1][j1] * g) * f
	var b0: float = ctx["b0"]
	var b1: float = ctx["b1"]
	var sc := 0.5 * (b0 + b1)
	var half := 0.5 * (b1 - b0)
	var reach := CINCH_REACH * mm
	var inv := tr.affine_inverse()
	var am := ArrayMesh.new()
	for b in base.get_blend_shape_count():
		am.add_blend_shape(base.get_blend_shape_name(b))
	if base is ArrayMesh:
		am.blend_shape_mode = (base as ArrayMesh).blend_shape_mode
	for sfc in base.get_surface_count():
		var arrays: Array = arrs[sfc]
		var verts: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
		var moved := PackedByteArray()
		moved.resize(verts.size())
		for k in verts.size():
			var p: Vector3 = tr * verts[k]
			var c := _cyl(ax, p)
			var r := c.z
			var rn: float = r
			if pressed and r > 1e-6:
				rn = r - float(at.call(c.x, c.y))
				var off := absf(c.x - sc) - half
				if off > 0.0 and off < reach:   # the folds: out only, those below between those above
					var ph := 0.0 if c.x > sc else 0.5
					var fo := maxf(0.0, sin(c.y * CINCH_FOLDS / 2.0 + ph * PI / 2.0 + 0.3 * sin(c.y * 3.0)))
					var fi := int(round(c.y * CINCH_FOLDS / TAU * 2.0))
					var hv := float(posmod(fi * 374761393 + 5 * 668265263 + 31, 1000)) / 1000.0
					rn += CINCH_GATHER * mm * smoothstep(0.0, 12.0 * mm, off) * pow(1.0 - off / reach, 1.4) * fo * fo * (0.6 + 0.4 * hv)
			var i2 := int((c.x - S0) / ds)   # (the stack: its outside as it is now)
			if i2 >= 0 and i2 < NR:
				var j2 := _col(c.y)
				stack[i2][j2] = maxf(stack[i2][j2], rn + 0.5 * mm)
			if absf(rn - r) < 1e-6:
				continue
			var d: Vector3 = p - ax["a"]
			var dr: Vector3 = d - ax["u"] * d.dot(ax["u"])
			verts[k] = inv * (p + dr / r * (rn - r))
			moved[k] = 1
		arrays[Mesh.ARRAY_VERTEX] = verts
		if arrays[Mesh.ARRAY_NORMAL] != null:
			arrays[Mesh.ARRAY_NORMAL] = _normals_near(arrays, moved)
		am.add_surface_from_arrays(base.surface_get_primitive_type(sfc), arrays, base.surface_get_blend_shape_arrays(sfc))
		am.surface_set_material(sfc, base.surface_get_material(sfc))
	return am if pressed else base


static func _belt_out(bt: MeshInstance3D, base: Mesh, ctx: Dictionary) -> Mesh:
	var NA := CINCH_NA
	var stack: Array = ctx["stack"]
	var band_in: Array = ctx["band_in"]
	var ex := PackedFloat32Array()
	ex.resize(NA)
	for i in ctx["NR"]:
		for j in NA:
			if band_in[i][j] < INF and stack[i][j] > -INF:
				ex[j] = maxf(ex[j], stack[i][j] - band_in[i][j])
	var ex2 := ex.duplicate()
	var most := 0.0
	for j in NA:   # (a little wider round: no step at a fold's top)
		for k in range(-2, 3):
			ex2[j] = maxf(ex2[j], ex[posmod(j + k, NA)])
		most = maxf(most, ex2[j])
	var mm: float = ctx["mm"]
	if most < 0.2 * mm:
		return base
	var ax: Dictionary = ctx["ax"]
	var tr: Transform3D = bt.transform
	var inv := tr.affine_inverse()
	var am := ArrayMesh.new()
	for sfc in base.get_surface_count():
		var arrays := base.surface_get_arrays(sfc)
		var verts: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
		for k in verts.size():
			var p: Vector3 = tr * verts[k]
			var c := _cyl(ax, p)
			if c.z < 1e-6:
				continue
			var y := (c.y / TAU + 1.0) * NA - 0.5
			var j := posmod(int(floor(y)), NA)
			var g: float = y - floor(y)
			var e: float = ex2[j] * (1.0 - g) + ex2[(j + 1) % NA] * g
			var d: Vector3 = p - ax["a"]
			var dr: Vector3 = d - ax["u"] * d.dot(ax["u"])
			verts[k] = inv * (p + dr / c.z * e)
		arrays[Mesh.ARRAY_VERTEX] = verts
		am.add_surface_from_arrays(base.surface_get_primitive_type(sfc), arrays, base.surface_get_blend_shape_arrays(sfc))
		am.surface_set_material(sfc, base.surface_get_material(sfc))
	return am


# the surface's normals where it moved taken again from its faces (the folds seen), the same at one place (its seams)
static func _normals_near(arrays: Array, moved: PackedByteArray) -> PackedVector3Array:
	var verts: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	var nrm: PackedVector3Array = arrays[Mesh.ARRAY_NORMAL]
	if nrm.size() != verts.size():
		return nrm
	var idx = arrays[Mesh.ARRAY_INDEX]
	if idx == null or (idx as PackedInt32Array).is_empty():
		idx = PackedInt32Array(range(verts.size()))
	var near := moved.duplicate()
	for t in range(0, idx.size(), 3):   # (and the corners of the faces they are in)
		if moved[idx[t]] or moved[idx[t + 1]] or moved[idx[t + 2]]:
			near[idx[t]] = 1; near[idx[t + 1]] = 1; near[idx[t + 2]] = 1
	var key := func(v: Vector3) -> Vector3i: return Vector3i(roundi(v.x * 1e5), roundi(v.y * 1e5), roundi(v.z * 1e5))
	var acc := {}
	for t in range(0, idx.size(), 3):
		var a: int = idx[t]
		var b: int = idx[t + 1]
		var c: int = idx[t + 2]
		if not (near[a] or near[b] or near[c]):
			continue
		var fn := (verts[c] - verts[a]).cross(verts[b] - verts[a])   # (Godot's front faces: clockwise)
		for q in [a, b, c]:
			if near[q]:
				var kq: Vector3i = key.call(verts[q])
				acc[kq] = acc.get(kq, Vector3.ZERO) + fn
	var out := nrm.duplicate()
	for q in verts.size():
		if near[q]:
			var n: Vector3 = acc.get(key.call(verts[q]), Vector3.ZERO)
			if n.length_squared() > 1e-20:
				n = n.normalized()
				out[q] = n if n.dot(nrm[q]) >= 0.0 else -n
	return out


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

	# Things strapped on kept off the legs: a clip made for a small shield takes a big one through a knee. The thing is
	# about 400 of its points (in the bone leading it); the thighs and shins are capsules (radii measured on the skin,
	# KEEP_GAP of the height added for the armour on them); how far it is in: all its points' depths in them. It is
	# moved only as a body moves, by five ways in the order they are preferred (KEEP_WAYS, a price each): the forearm
	# turned about itself so the thing's foot goes out from the body and its top in (the clips hold a shield's foot in
	# front of the legs: swung out it clears them, upright, as one holds a big shield); the arm turned in the shoulder
	# about the upright (a door), out to the side, forward and up; the elbow bent. Never the foot in, never the elbow
	# straightened alone (it turned a tower shield edge on, its foot into the knee), nothing that bends the elbow sideways
	# (moved whole with the forearm kept parallel, the arm looked broken). Each frame every way is tried KEEP_PROBE_DEG
	# ahead (ahead: with a knee mid-shield nothing gains until its edge is past) and a step goes the ways that gain most
	# for their price. The correction is carried from frame to frame and only stepped: still in - a step out, taken if
	# it leaves it less in (or a little more while the way ahead clears it well); clear - a step back to the clip while
	# it stays clear; a new clip starts from none.
	const KEEP_GAP := 0.02
	const KEEP_STEP_DEG := 2.5   # how far a way may go in a frame
	const KEEP_PROBE_DEG := 15.0   # how far ahead each way is tried
	const KEEP_BACK := 0.02   # the share of it given back in a frame once clear (if that stays clear)
	const KEEP_SLACK := 0.02   # of the height: how clear it must stay for a step back
	const KEEP_SHOW := 0.3   # the share of the way to the solve the shown arm goes in a frame
	# [the way, how far it may go (degrees), its price]: the forearm about itself (the foot out), the arm about the
	# upright (either way), out to the side, forward-up, the elbow bent (as far as keep_flex)
	const KEEP_WAYS := [["roll", 40.0, 1.0], ["yaw", 40.0, 1.5], ["out", 30.0, 2.0], ["lift", 35.0, 2.5], ["bend", 30.0, 3.0]]
	var _keep := []   # [{mi, bone: the bone leading it, arm: its upper arm, fore: its forearm, hand, box: [centre, Basis of its ways, half sizes] in that bone's rest frame}]
	var _caps := []   # [[bone, its child, radius]] - measured once
	var _keep_h := 1.0   # the skeleton's height
	var keep_flex := 30.0   # (SF3DEquip.keep_flex, given by wear())
	var keep_debug := false
	var keep_apply := true
	var _keep_q := {}   # an upper arm -> {x: its correction now (radians: roll, yaw, out, lift, bend - KEEP_WAYS), xs: as shown}
	var _keep_clip := ""   # (the clip it was solved for: another one starts from none)

	## a thing strapped on (a shield): kept off the body while it is shown
	func keep_off(mi: MeshInstance3D, on: bool) -> void:
		_keep = _keep.filter(func(k): return is_instance_valid(k["mi"]) and k["mi"] != mi)
		var sk := mi.get_parent() as Skeleton3D
		if not on or sk == null or mi.mesh == null or mi.skin == null:
			return
		var votes := {}
		var verts := []
		var binds := []
		for s in mi.mesh.get_surface_count():
			var a := mi.mesh.surface_get_arrays(s)
			var V: PackedVector3Array = a[Mesh.ARRAY_VERTEX]
			var Bn = a[Mesh.ARRAY_BONES]
			var Wt = a[Mesh.ARRAY_WEIGHTS]
			if Bn == null or Wt == null or V.is_empty():
				continue
			var per := int((Bn as PackedInt32Array).size() / V.size())
			for i in V.size():
				var best := -1
				var bw := -1.0
				for k in per:
					if Wt[i * per + k] > bw:
						bw = Wt[i * per + k]
						best = Bn[i * per + k]
				votes[best] = int(votes.get(best, 0)) + 1
				verts.append(V[i])
				binds.append(best)
		if votes.is_empty():
			return
		var lead: int = votes.keys().reduce(func(x, y): return x if votes[x] >= votes[y] else y)
		var bname := mi.skin.get_bind_name(lead)
		var bone := sk.find_bone(bname) if bname != StringName() else mi.skin.get_bind_bone(lead)
		if bone < 0:
			return
		var side := "Left" if "Left" in sk.get_bone_name(bone) else "Right"
		var arm := -1
		var b := bone
		while b >= 0 and arm < 0:   # its upper arm: up the chain from the bone leading it
			if String(sk.get_bone_name(b)).ends_with(side + "Arm"):
				arm = b
			b = sk.get_bone_parent(b)
		var fore := -1
		var hand := -1
		for i in sk.get_bone_count():
			if sk.get_bone_parent(i) == arm and String(sk.get_bone_name(i)).ends_with(side + "ForeArm"):
				fore = i
		for i in sk.get_bone_count():
			if fore >= 0 and sk.get_bone_parent(i) == fore and String(sk.get_bone_name(i)).ends_with(side + "Hand"):
				hand = i
		if arm < 0 or fore < 0 or hand < 0:
			return
		var bind := mi.skin.get_bind_pose(lead)
		var pts := PackedVector3Array()
		var step := maxi(1, int(verts.size() / 2000))
		for i in range(0, verts.size(), step):
			pts.append(bind * (verts[i] as Vector3))
		var few := PackedVector3Array()   # (about 400 of its points: the shape itself, a curved shield's too)
		for i in range(0, pts.size(), maxi(1, int(pts.size() / 400))):
			few.append(pts[i])
		_keep.append({"mi": mi, "bone": bone, "arm": arm, "fore": fore, "hand": hand, "box": _box_of(pts), "pts": few, "left": side == "Left"})

	# the box round points: their middle, their main ways (the covariance's, by power steps) and the half sizes on them
	func _box_of(pts: PackedVector3Array) -> Array:
		var c := Vector3.ZERO
		for p in pts:
			c += p
		c /= maxf(pts.size(), 1)
		var cov := [Vector3.ZERO, Vector3.ZERO, Vector3.ZERO]
		for p in pts:
			var d := p - c
			cov[0] += d * d.x
			cov[1] += d * d.y
			cov[2] += d * d.z
		var mul := func(v: Vector3) -> Vector3: return Vector3(cov[0].dot(v), cov[1].dot(v), cov[2].dot(v))
		var a := Vector3(1, 0.3, 0.2).normalized()
		for it in 40:
			a = (mul.call(a) as Vector3).normalized()
		var b := a.cross(Vector3.UP if absf(a.y) < 0.9 else Vector3.RIGHT).normalized()
		for it in 40:
			b = (mul.call(b) as Vector3)
			b = (b - a * b.dot(a)).normalized()
		var axes := Basis(a, b, a.cross(b).normalized())
		# its extents from the 2nd to the 98th of its points on each way: the straps and the grip behind a shield, a
		# boss's point, do not make the slab thick
		var lo := Vector3.ZERO
		var hi := Vector3.ZERO
		for ax in 3:
			var vals := []
			for p in pts:
				vals.append((axes.transposed() * (p - c))[ax])
			vals.sort()
			lo[ax] = vals[int(0.02 * (vals.size() - 1))]
			hi[ax] = vals[int(0.98 * (vals.size() - 1))]
		return [c + axes * ((lo + hi) * 0.5), axes, (hi - lo) * 0.5]

	# the capsules round the legs', the body's and the head's bones: a bone to its child, the radius the skin's (the
	# legs' 75th share of their points' distances, the body's 40th: its front is nearer than its sides)
	func _measure_caps(sk: Skeleton3D) -> void:
		var pairs := [["LeftUpLeg", "LeftLeg", .75], ["LeftLeg", "LeftFoot", .75], ["RightUpLeg", "RightLeg", .75],
			["RightLeg", "RightFoot", .75]]
		var find := func(sfx: String) -> int:
			for i in sk.get_bone_count():
				var n := String(sk.get_bone_name(i))
				if n.ends_with(sfx) and not (sfx == "Spine" and n.ends_with("Spine1")) and not (sfx == "Leg" and n.ends_with("UpLeg")):
					return i
			return -1
		var body: MeshInstance3D = null
		for c in sk.get_children():
			if c is MeshInstance3D and not c.has_meta("sf3d_piece") and c.skin and c.mesh and (body == null or c.mesh.get_faces().size() > body.mesh.get_faces().size()):
				body = c
		var lo := INF
		var hi := -INF
		for i in sk.get_bone_count():
			lo = minf(lo, sk.get_bone_global_rest(i).origin.y)
			hi = maxf(hi, sk.get_bone_global_rest(i).origin.y)
		_keep_h = (hi - lo) * 1.08
		var gap := KEEP_GAP * _keep_h
		var dists := {}   # pair index -> distances of the skin's points led by its bone
		var of_bone := {}
		for k in pairs.size():
			var a: int = find.call(pairs[k][0])
			var b: int = find.call(pairs[k][1])
			if a >= 0 and b >= 0:
				of_bone[a] = k
				dists[k] = []
				_caps.append([a, b, 0.0, k])
		if body:
			var A := body.mesh.surface_get_arrays(0)
			var V: PackedVector3Array = A[Mesh.ARRAY_VERTEX]
			var Bn = A[Mesh.ARRAY_BONES]
			var Wt = A[Mesh.ARRAY_WEIGHTS]
			if Bn != null and Wt != null and not V.is_empty():
				var per := int((Bn as PackedInt32Array).size() / V.size())
				for i in range(0, V.size(), maxi(1, int(V.size() / 20000))):
					var best := -1
					var bw := -1.0
					for k in per:
						if Wt[i * per + k] > bw:
							bw = Wt[i * per + k]
							best = Bn[i * per + k]
					var bn := body.skin.get_bind_name(best)
					var bone := sk.find_bone(bn) if bn != StringName() else body.skin.get_bind_bone(best)
					if not of_bone.has(bone):
						continue
					var cap: Array = _caps.filter(func(c): return c[0] == bone)[0]
					var P := sk.get_bone_global_rest(bone) * (body.skin.get_bind_pose(best) * V[i])
					var a := sk.get_bone_global_rest(cap[0]).origin
					var b := sk.get_bone_global_rest(cap[1]).origin
					var t := clampf((P - a).dot(b - a) / maxf((b - a).length_squared(), 1e-9), 0.0, 1.0)
					if t > .15 and t < .85:
						dists[of_bone[bone]].append(P.distance_to(a + (b - a) * t))
		for c in _caps:
			var d: Array = dists[c[3]]
			d.sort()
			var share: float = pairs[c[3]][2]
			c[2] = (d[int(share * (d.size() - 1))] if d.size() > 8 else 0.06 * (hi - lo)) + gap

	# its points (as posed) against the capsules: the push that takes them out - every point in a capsule pushed out of
	# it, the ways averaged by how deep each is (a smooth push: not the deepest point's jumps) - and where it touches
	func _pts_push(pts: PackedVector3Array, caps: Array) -> Array:
		var total := 0.0   # (all the points' depths: how far in it is, for a step's check)
		var wsum := 0.0
		var push := Vector3.ZERO
		var at := Vector3.ZERO
		var tau := 0.01 * _keep_h
		for p in pts:
			for cp in caps:
				var A: Vector3 = cp[0]
				var ab: Vector3 = (cp[1] as Vector3) - A
				var t := clampf((p - A).dot(ab) / maxf(ab.length_squared(), 1e-9), 0.0, 1.0)
				var Q := A + ab * t
				var d := p.distance_to(Q)
				var pen: float = float(cp[2]) - d
				if pen <= 0.0:
					continue
				var w := exp(minf(pen / tau, 30.0))
				wsum += w
				push += (p - Q) / maxf(d, 1e-6) * pen * w
				at += p * w
				total += pen
		if wsum <= 0.0:
			return [Vector3.ZERO, Vector3.ZERO, 0.0]
		return [push / wsum, at / wsum, total]

	# how far its points are in the capsules, all their depths (the solver's measure: no ways, no weights)
	func _depth(pts: PackedVector3Array, caps: Array) -> float:
		var total := 0.0
		for cp in caps:
			var A: Vector3 = cp[0]
			var ab: Vector3 = (cp[1] as Vector3) - A
			var l2 := maxf(ab.length_squared(), 1e-9)
			var r: float = cp[2]
			for p in pts:
				var t := clampf((p - A).dot(ab) / l2, 0.0, 1.0)
				var d2 := p.distance_squared_to(A + ab * t)
				if d2 < r * r:
					total += r - sqrt(d2)
		return total

	# the box (its centre C, ways R, half sizes e, as posed) against the capsules (kept for a measure: a curved shield's
	# box is too thick to push by)
	func _box_push(C: Vector3, R: Basis, e: Vector3, caps: Array) -> Array:
		var wsum := 0.0
		var push := Vector3.ZERO
		var at := Vector3.ZERO
		var tau := 0.01 * _keep_h
		for cp in caps:
			var A: Vector3 = cp[0]
			var B: Vector3 = cp[1]
			var r: float = cp[2]
			for k in 9:
				var L := A.lerp(B, k / 8.0)
				var l := R.transposed() * (L - C)
				var q := Vector3(clampf(l.x, -e.x, e.x), clampf(l.y, -e.y, e.y), clampf(l.z, -e.z, e.z))
				var pen := 0.0
				var way := Vector3.ZERO
				var Q := C + R * q
				if q.is_equal_approx(l):   # (the axis inside the box: out through its nearest face)
					var dd := e - l.abs()
					var ax := 0 if dd.x <= dd.y and dd.x <= dd.z else (1 if dd.y <= dd.z else 2)
					pen = dd[ax] + r
					way = -R[ax] * signf(l[ax] if l[ax] != 0.0 else 1.0)
				else:
					var d := L.distance_to(Q)
					pen = r - d
					way = (Q - L) / maxf(d, 1e-6)
				if pen <= 0.0:
					continue
				var w := exp(minf(pen / tau, 30.0))
				wsum += w
				push += way * pen * w
				at += Q * w
		if wsum <= 0.0:
			return [Vector3.ZERO, C]
		return [push / wsum, at / wsum]

	func _keep_off_body(sk: Skeleton3D) -> void:
		if _keep.is_empty():
			return
		if _caps.is_empty():
			_measure_caps(sk)
		var t0 := Time.get_ticks_usec()
		_keep_body(sk)
		if keep_debug:
			print("KEEPTIME %d" % (Time.get_ticks_usec() - t0))

	func _keep_body(sk: Skeleton3D) -> void:
		var none := [0.0, 0.0, 0.0, 0.0, 0.0]
		var clip := _clip()
		if clip != _keep_clip:   # (another clip: its own correction from none, the shown arm going there smoothly)
			_keep_clip = clip
			for a in _keep_q:
				_keep_q[a]["x"] = none.duplicate()
		var caps := _caps.map(func(c): return [sk.get_bone_global_pose(c[0]).origin, sk.get_bone_global_pose(c[1]).origin, c[2]])
		# (a step back only where it stays clear by KEEP_SLACK: at the edge in and out by turns, every frame, it shook)
		var wide := caps.map(func(c): return [c[0], c[1], float(c[2]) + KEEP_SLACK * _keep_h])
		var up := (sk.global_transform.basis.inverse() * Vector3.UP).normalized()
		var fwd := _forward(sk)
		fwd = fwd - up * fwd.dot(up)
		fwd = fwd.normalized() if fwd.length() > 1e-6 else up.cross(Vector3.RIGHT).normalized()
		var lat := up.cross(fwd).normalized()   # (the character's left)
		var lim := []
		for w in KEEP_WAYS:
			lim.append(deg_to_rad(keep_flex if w[0] == "bend" else float(w[1])))
		for k in _keep:
			if not is_instance_valid(k["mi"]) or not k["mi"].visible:
				continue
			var arm: int = k["arm"]
			var fore: int = k["fore"]
			var G := sk.get_bone_global_pose(k["bone"])
			var Ga := sk.get_bone_global_pose(arm)
			var Gf := sk.get_bone_global_pose(fore)
			var S := Ga.origin
			var E := Gf.origin
			var Wh := sk.get_bone_global_pose(k["hand"]).origin
			var fa := (Wh - E).normalized()   # the forearm's own way
			var hinge := (S - E).cross(Wh - E)   # (turned by +, the elbow opens)
			hinge = hinge.normalized() if hinge.length() > 1e-6 else Vector3.ZERO
			var P0 := PackedVector3Array()
			var foot := Vector3.ZERO   # (its lowest point)
			for p in k["pts"]:
				var q := G * (p as Vector3)
				P0.append(q)
				if foot == Vector3.ZERO or q.dot(up) < foot.dot(up):
					foot = q
			var outw := lat * (1.0 if k["left"] else -1.0)   # out from the body on its side
			var shoulder := func(x: Array) -> Quaternion:   # the arm in the shoulder: about the upright, out, forward-up
				return Quaternion(up, x[1]) * Quaternion(fwd, x[2]) * Quaternion(lat, x[3])
			var elbow := func(x: Array) -> Quaternion:   # the forearm: about itself, then about the elbow's hinge
				var qh := Quaternion(hinge, x[4]) if hinge != Vector3.ZERO else Quaternion.IDENTITY
				return qh * Quaternion(fa, x[0])
			var Pp := PackedVector3Array()   # (every third point: for the ways tried ahead)
			for i in range(0, P0.size(), 3):
				Pp.append(P0[i])
			var moved := func(x: Array, pts: PackedVector3Array) -> PackedVector3Array:
				var qa: Quaternion = shoulder.call(x)
				var qf: Quaternion = elbow.call(x)
				var out := PackedVector3Array()
				for p in pts:
					out.append(S + qa * ((E - S) + qf * (p - E)))
				return out
			var depth_at := func(x: Array, cs: Array, pts: PackedVector3Array) -> float:
				return _depth(moved.call(x, pts), cs)
			# the ways each goes (+1 / -1; the door both): the foot out, the hand out, forward-up, the elbow closing
			var sg := func(v: float, d: float) -> float: return d if absf(v) < 1e-6 else signf(v)
			var dirs := [[sg.call(fa.cross(foot - E).dot(outw), 1.0)], [1.0, -1.0],
				[sg.call(fwd.cross(Wh - S).dot(outw), 1.0 if k["left"] else -1.0)],
				[sg.call(lat.cross(Wh - S).dot(fwd + up), -1.0)], [-1.0]]
			var st: Dictionary = _keep_q.get(arm, {"x": none.duplicate(), "xs": none.duplicate()})
			var x: Array = (st["x"] as Array).duplicate()
			if keep_apply:
				var depth: float = depth_at.call(x, caps, P0)
				if depth > 0.0:
					var best := 0.0   # (the best gain ahead for its price, and that share in)
					var ahead := 0.0
					var score := []
					var dp: float = depth_at.call(x, caps, Pp)
					for i in 5:
						var sc_i := []
						for d in dirs[i]:
							# tried a third, two thirds and all the way ahead: a way that is deeper in on the way is no
							# way out past the leg but through it (its gain only as far as the first third)
							var path := []
							var span := 0.0
							for f in [1.0 / 3.0, 2.0 / 3.0, 1.0]:
								var xp := x.duplicate()
								xp[i] = clampf(float(x[i]) + float(d) * deg_to_rad(KEEP_PROBE_DEG) * f, -float(lim[i]), float(lim[i]))
								span = absf(float(xp[i]) - float(x[i]))
								path.append(float(depth_at.call(xp, caps, Pp)))
							if span < deg_to_rad(0.5) or dp <= 0.0:
								continue
							var through: bool = maxf(path[0], path[1]) > dp * 1.02
							var gain: float = (dp - float(path[0] if through else path[2])) / dp
							var v: float = gain / (float(KEEP_WAYS[i][2]) * rad_to_deg(span / 3.0 if through else span))
							sc_i.append([v, float(d)])
							if v > best:
								best = v
								ahead = 0.0 if through else gain
						score.append(sc_i)
					if best > 0.0:
						# a step: the ways gaining at least half the best's, each by its share of it
						var dx := none.duplicate()
						for i in 5:
							for c in score[i]:
								if float(c[0]) >= 0.5 * best:
									dx[i] = float(dx[i]) + float(c[1]) * deg_to_rad(KEEP_STEP_DEG) * float(c[0]) / best
						for scale in [1.0, 0.5]:
							var x2 := []
							for i in 5:
								x2.append(clampf(float(x[i]) + float(dx[i]) * scale, -float(lim[i]), float(lim[i])))
							var d2: float = depth_at.call(x2, caps, P0)
							# (less in; or, while the way ahead - never deeper on it - clears a good share, hardly more: a knee
							# mid-shield, nothing gains until the edge is past)
							if d2 < depth * 0.99 or (ahead >= 0.15 and d2 <= depth * 1.03):
								x = x2
								break
				else:   # clear: a step back, if it stays clear
					var xb := x.map(func(v): return float(v) * (1.0 - KEEP_BACK))
					if float(depth_at.call(xb, wide, P0)) <= 0.0:
						x = xb
			else:
				x = none.duplicate()
			# shown: following the solve smoothly (its steps come every few frames: a staircase, seen as a shake)
			var xs := []
			for i in 5:
				xs.append(lerpf(float((st["xs"] as Array)[i]), float(x[i]), KEEP_SHOW))
			_keep_q[arm] = {"x": x, "xs": xs}
			if keep_debug:
				print("KEEP %.3f roll %.1f yaw %.1f out %.1f lift %.1f bend %.1f" % [_player.current_animation_position if _player and _player.current_animation != "" else 0.0, rad_to_deg(x[0]), rad_to_deg(x[1]), rad_to_deg(x[2]), rad_to_deg(x[3]), rad_to_deg(x[4])])
			if xs.all(func(v): return absf(float(v)) < 1e-5):
				continue
			# applied: the upper arm turned in the shoulder; the forearm with it, about itself and the elbow's hinge
			var qs: Quaternion = shoulder.call(xs)
			var par := sk.get_bone_parent(arm)
			var pa := sk.get_bone_global_pose(par) if par >= 0 else Transform3D()
			var Ga2 := Transform3D(Basis(qs) * Ga.basis, S)
			sk.set_bone_pose_rotation(arm, (pa.affine_inverse() * Ga2).basis.get_rotation_quaternion())
			var Bf := Basis(qs * (elbow.call(xs) as Quaternion)) * Gf.basis
			sk.set_bone_pose_rotation(fore, (Ga2.affine_inverse() * Transform3D(Bf, S + qs * (E - S))).basis.get_rotation_quaternion())
		if keep_debug:   # (where the things are now, by the hips, and how far in still: their motion measured outside)
			var hips := sk.get_bone_global_pose(0)
			for k in _keep:
				if is_instance_valid(k["mi"]) and k["mi"].visible:
					var Gk := sk.get_bone_global_pose(k["bone"])
					var c: Vector3 = hips.affine_inverse() * (Gk * ((k["box"] as Array)[0] as Vector3))
					var Pk := PackedVector3Array()
					for p in k["pts"]:
						Pk.append(Gk * (p as Vector3))
					var left := _pts_push(Pk, caps)
					print("THING %.4f %.5f %.5f %.5f in %.5f" % [_player.current_animation_position if _player and _player.current_animation != "" else 0.0, c.x / _keep_h, c.y / _keep_h, c.z / _keep_h, (left[0] as Vector3).length() / _keep_h])

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
		_keep_off_body(sk)   # (a shield's arm first: the hands' grips after it)
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
