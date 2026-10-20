@tool
extends Node3D
## Put this script on the root of an imported SF3D plant (tree, bush, grass) - or call
## WindFoliage.apply(node) for any node - and its meshes sway in the wind.
## The plant's GLB carries the wind map in its vertex colours (made by SF3D, category "Растительность").
class_name WindFoliage

const SHADER := preload("wind_foliage.gdshader")

@export var wind_strength := 0.06:
	set(v):
		wind_strength = v
		_set_param("wind_strength", v)
@export var wind_speed := 1.1:
	set(v):
		wind_speed = v
		_set_param("wind_speed", v)
@export var wind_direction := Vector2(1.0, 0.3):
	set(v):
		wind_direction = v
		_set_param("wind_direction", v)
@export var flutter_strength := 0.012:
	set(v):
		flutter_strength = v
		_set_param("flutter_strength", v)

var _materials: Array[ShaderMaterial] = []


func _ready() -> void:
	_materials = apply(self)
	for p in ["wind_strength", "wind_speed", "wind_direction", "flutter_strength"]:
		_set_param(p, get(p))


func _set_param(name: String, value) -> void:
	for m in _materials:
		m.set_shader_parameter(name, value)


## Replaces the materials of every MeshInstance3D under `root` with the wind shader, keeping the albedo texture.
static func apply(root: Node) -> Array[ShaderMaterial]:
	var out: Array[ShaderMaterial] = []
	var stack: Array[Node] = [root]
	while stack:
		var n: Node = stack.pop_back()
		stack.append_array(n.get_children())
		if not (n is MeshInstance3D) or n.mesh == null:
			continue
		var mi := n as MeshInstance3D
		for s in mi.mesh.get_surface_count():
			var src: Material = mi.get_active_material(s)
			var sm := ShaderMaterial.new()
			sm.shader = SHADER
			if src is BaseMaterial3D:
				sm.set_shader_parameter("albedo_texture", src.albedo_texture)
				sm.set_shader_parameter("albedo_color", src.albedo_color)
				sm.set_shader_parameter("roughness", src.roughness)
			mi.set_surface_override_material(s, sm)
			out.append(sm)
	return out
