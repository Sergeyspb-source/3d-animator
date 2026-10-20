class_name FaceCurvesPlayer
extends Node
## Drives blend shapes of every MeshInstance3D under `face_root` from a FaceCurvesClip, clocked by the voice
## AudioStreamPlayer3D (never by frame counts, so lips do not drift on hitches). Curves whose names match a blend
## shape on a mesh drive it; others are ignored. Starts with the voice, holds the clip tail after it, then rests.

@export var audio: AudioStreamPlayer3D
@export var face_root: Node3D
## res:// path of a face-curves/1 JSON clip that matches the audio stream.
@export_file("*.json") var clip_path: String = ""

var clip: FaceCurvesClip
## Audio time of the current evaluation; < 0 means idle (face at rest).
var time: float = -1.0
var _was_playing: bool = false
## Per mesh: curve name -> blend shape index.
var _targets: Array[Dictionary] = []
var _meshes: Array[MeshInstance3D] = []


# GPT: load the clip and resolve blend-shape indices once; the face starts at rest.
func _ready() -> void:
	assert(audio != null and face_root != null, "FaceCurvesPlayer needs audio and face_root")
	clip = FaceCurvesClip.load_file(clip_path)
	assert(clip != null, "face clip failed validation: %s" % clip_path)
	for node: Node in face_root.find_children("*", "MeshInstance3D", true, false):
		var mi: MeshInstance3D = node as MeshInstance3D
		if mi.mesh == null:
			continue
		var map: Dictionary = {}
		for key: StringName in clip.curves:
			var index: int = mi.find_blend_shape_by_name(key)
			if index >= 0:
				map[key] = index
		if not map.is_empty():
			_meshes.append(mi)
			_targets.append(map)
	assert(not _meshes.is_empty(), "no blend shape under %s matches the face clip" % face_root.name)
	_apply_rest()


## Number of blend shapes this player drives (all meshes together).
func driven_shape_count() -> int:
	var n: int = 0
	for map: Dictionary in _targets:
		n += map.size()
	return n


func _process(delta: float) -> void:
	if audio.playing:
		# GPT: audio clock with mix-latency compensation; lead-in is folded into the clip's own time base.
		time = audio.get_playback_position() + AudioServer.get_time_since_last_mix() \
				- AudioServer.get_output_latency()
		_was_playing = true
	elif _was_playing:
		time = maxf(time, clip.duration) + delta
		if time > clip.end_time():
			_was_playing = false
			time = -1.0
			_apply_rest()
			return
	else:
		return
	evaluate(time)


## Pose the face at audio time `t` (also usable from tests and offline renders).
func evaluate(t: float) -> void:
	var values: Dictionary[StringName, float] = clip.sample(t)
	for m: int in _meshes.size():
		var map: Dictionary = _targets[m]
		for key: StringName in map:
			_meshes[m].set_blend_shape_value(map[key], values[key])


func _apply_rest() -> void:
	for m: int in _meshes.size():
		for index: int in _targets[m].values():
			_meshes[m].set_blend_shape_value(index, 0.0)
