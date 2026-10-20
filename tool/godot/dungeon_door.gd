extends Node3D
## Door leaf of the SF3D dungeon kit. The node origin is the hinge, so rotating about Y swings the door.
## Call toggle() / set_open(true) from your interaction code.

@export var open_angle := -100.0    ## degrees about Y when open (negative = opens away from +Z side)
@export var duration := 0.45

var is_open := false
var _closed_y := 0.0
var _tween: Tween


func _ready() -> void:
	_closed_y = rotation_degrees.y


func toggle() -> void:
	set_open(not is_open)


func set_open(value: bool) -> void:
	is_open = value
	if _tween:
		_tween.kill()
	_tween = create_tween().set_trans(Tween.TRANS_SINE).set_ease(Tween.EASE_IN_OUT)
	_tween.tween_property(self, "rotation_degrees:y", _closed_y + (open_angle if value else 0.0), duration)
