extends Node3D
## A destructible object of the SF3D pipeline (barrel, crate, vase...).
## Children: Whole (the intact model with its collision) and Chunks (rigid-body pieces). Chunks are kept out of the
## tree until the object breaks. Call take_damage(amount, hit_point) from your combat code, or destroy(hit_point).
## Signal `destroyed` is emitted once (spawn loot there).

signal destroyed(position: Vector3)

@export var max_health := 20.0
@export var mass_total := 20.0            ## kg, split between the pieces by volume
@export var burst_impulse := 3.5          ## speed given to the pieces, away from the hit point (m/s)
@export var spin := 4.0                   ## random spin of the pieces (rad/s)
@export var debris_time := 5.0            ## seconds the pieces stay before they shrink away
@export var fade_time := 1.0
@export_flags_3d_physics var debris_layer := 4      ## pieces live on layer 3 so they do not push the player
@export_flags_3d_physics var debris_mask := 1       ## ...but still land on the world (layer 1)
@export var dust_scene: PackedScene                 ## optional one-shot effect at the break; default sf3d_fx/smoke

var health := 0.0
var broken := false
var _chunks: Node3D


func _ready() -> void:
	health = max_health
	_chunks = get_node_or_null("Chunks")
	if _chunks:
		remove_child(_chunks)
		for c in _chunks.get_children():
			if c is RigidBody3D:
				c.collision_layer = debris_layer
				c.collision_mask = debris_mask
				c.mass = max(0.05, mass_total * float(c.get_meta("share", 1.0 / max(1, _chunks.get_child_count()))))


func take_damage(amount: float, hit_point: Vector3 = Vector3.INF) -> void:
	if broken:
		return
	health -= amount
	if health <= 0.0:
		destroy(hit_point)


func destroy(hit_point: Vector3 = Vector3.INF) -> void:
	if broken:
		return
	broken = true
	var whole := get_node_or_null("Whole")
	if whole:
		whole.queue_free()
	if _chunks:
		add_child(_chunks)
		var origin: Vector3 = hit_point if hit_point.is_finite() else global_position + Vector3(0, 0.4, 0)
		for c in _chunks.get_children():
			if not c is RigidBody3D:
				continue
			var dir: Vector3 = (c.global_position - origin)
			dir = (dir.normalized() + Vector3.UP * 0.35).normalized()
			c.linear_velocity = dir * burst_impulse * randf_range(0.6, 1.2)
			c.angular_velocity = Vector3(randf_range(-1, 1), randf_range(-1, 1), randf_range(-1, 1)) * spin
	_spawn_dust()
	destroyed.emit(global_position)
	await get_tree().create_timer(debris_time).timeout
	if not is_inside_tree() or not _chunks:
		return
	var tw := create_tween().set_parallel(true)
	for c in _chunks.get_children():
		tw.tween_property(c, "scale", Vector3.ONE * 0.01, fade_time)
	await tw.finished
	queue_free()


func _spawn_dust() -> void:
	var fx: PackedScene = dust_scene
	if fx == null and ResourceLoader.exists("res://sf3d_fx/smoke.tscn"):
		fx = load("res://sf3d_fx/smoke.tscn")
	if fx == null:
		return
	var n := fx.instantiate()
	get_parent().add_child(n)
	n.global_position = global_position + Vector3(0, 0.4, 0)
	if "auto_free" in n:
		n.auto_free = true
