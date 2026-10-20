extends Node3D
## Root script of the SF3D effect scenes (sf3d_fx/*.tscn).
## Starts every particle system when the effect appears; one-shot effects can remove themselves when done.
## Children named "Circle" spin, children named "Light" flicker (fire) or fade out (one-shot flashes).

@export var auto_free := false        ## remove the effect when its particles are finished (one-shot effects)
@export var spin_degrees := 25.0      ## rotation speed of a "Circle" child, degrees per second
@export var light_energy := 2.0

var _t := 0.0
var _life := 0.0


func _ready() -> void:
	for c in find_children("*", "GPUParticles3D", true, false):
		c.restart()
		_life = max(_life, c.lifetime + (0.0 if c.one_shot else 999.0))
	if auto_free and not Engine.is_editor_hint():
		get_tree().create_timer(_life + 0.3).timeout.connect(queue_free)


func restart() -> void:
	_t = 0.0
	for c in find_children("*", "GPUParticles3D", true, false):
		c.restart()


func _process(delta: float) -> void:
	_t += delta
	var circle := get_node_or_null("Circle")
	if circle:
		circle.rotate_y(deg_to_rad(spin_degrees) * delta)
		var m: Material = circle.get_active_material(0)
		if m is StandardMaterial3D:
			m.emission_energy_multiplier = 1.5 + 0.6 * sin(_t * 3.0)
	var light := get_node_or_null("Light") as OmniLight3D
	if light:
		if auto_free or name.begins_with("Explosion") or name.begins_with("Hit"):
			light.light_energy = light_energy * max(0.0, 1.0 - _t / 0.5)
		else:
			light.light_energy = light_energy * (0.85 + 0.15 * sin(_t * 17.0) + 0.1 * sin(_t * 7.3))
