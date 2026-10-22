extends Node3D
## A character built by SF3D (landmark rig): blinks on its own and speaks lines made in SF3D's lip-sync tab.
## The .tscn next to this script holds the model; the lines are the <stem>.face.json files (+ their audio, same stem)
## in the same folder. say("stem") plays the voice and drives the face with the project's FaceCurvesPlayer
## (game/characters/face_curves_player.gd or tool/godot/face_curves_*.gd from SF3D): no class_name here, so every
## character folder can carry its own copy of this script.

## Seconds between blinks (random in this range); 0 turns blinking off.
@export var blink_min: float = 2.0
@export var blink_max: float = 6.0
## Length of one blink, seconds.
@export var blink_time: float = 0.16
## Chance that a blink is doubled.
@export_range(0.0, 1.0) var double_blink: float = 0.15
## Bus and volume of the voice.
@export var voice_bus: StringName = &"Master"
@export var voice_db: float = 0.0
## Line to say when the scene starts ("" = none).
@export var say_on_ready: String = ""

var _blink_meshes: Array[MeshInstance3D] = []
var _blink_idx: Array[PackedInt32Array] = []
var _next_blink: float = 0.0
var _blink_t: float = -1.0
var _blinks_left: int = 0
var _voice: AudioStreamPlayer3D
var _player: Node
var _lines: Dictionary = {}   # stem -> [clip json path, audio path]


func _ready() -> void:
	process_priority = 10   # after the FaceCurvesPlayer child: blinks add to the line's face, not under it
	for node: Node in find_children("*", "MeshInstance3D", true, false):
		var mi: MeshInstance3D = node as MeshInstance3D
		if mi.mesh == null:
			continue
		var idx := PackedInt32Array()
		for key: String in ["eyeBlinkLeft", "eyeBlinkRight"]:
			var i: int = mi.find_blend_shape_by_name(key)
			if i >= 0:
				idx.append(i)
		if not idx.is_empty():
			_blink_meshes.append(mi)
			_blink_idx.append(idx)
	_find_lines()
	_schedule_blink()
	if say_on_ready != "":
		say(say_on_ready)


## Names of the lines found next to the scene.
func lines() -> PackedStringArray:
	if _lines.is_empty():
		_find_lines()
	return PackedStringArray(_lines.keys())


## Play a line (its stem, e.g. "beggar_plea_ru"). Returns false when there is no such line or no FaceCurvesPlayer
## class in the project.
func say(stem: String) -> bool:
	if _lines.is_empty():   # say() may come before _ready()
		_find_lines()
	if not _lines.has(stem):
		push_warning("%s: no line '%s' (have: %s)" % [name, stem, ", ".join(lines())])
		return false
	var script: Script = _player_script()
	if script == null:
		push_warning("%s: FaceCurvesPlayer is not in the project; copy SF3D tool/godot/face_curves_*.gd" % name)
		return false
	if _player != null:
		_player.queue_free()
	if _voice == null:
		_voice = AudioStreamPlayer3D.new()
		_voice.name = "Voice"
		add_child(_voice)
	_voice.stop()
	_voice.bus = voice_bus
	_voice.volume_db = voice_db
	_voice.stream = load(_lines[stem][1])
	_player = Node.new()
	_player.set_script(script)
	_player.name = "FaceCurves"
	_player.set("audio", _voice)
	_player.set("face_root", self)
	_player.set("clip_path", _lines[stem][0])
	add_child(_player)
	_voice.play()
	return true


func is_speaking() -> bool:
	return _voice != null and _voice.playing


func _process(delta: float) -> void:
	if blink_max <= 0.0 or _blink_meshes.is_empty():
		return
	if _blink_t < 0.0:
		_next_blink -= delta
		if _next_blink <= 0.0:
			_blink_t = 0.0
			_blinks_left = 2 if randf() < double_blink else 1
		return
	_blink_t += delta
	var x: float = _blink_t / blink_time
	var v: float = sin(clampf(x, 0.0, 1.0) * PI)   # close and open again
	_set_blink(v)
	if x >= 1.0:
		_set_blink(0.0)
		_blinks_left -= 1
		_blink_t = 0.0 if _blinks_left > 0 else -1.0
		if _blinks_left <= 0:
			_schedule_blink()


# The face curves of a line may blink too: the larger value wins, so the timer never cancels the line's own blink.
func _set_blink(v: float) -> void:
	for m: int in _blink_meshes.size():
		for i: int in _blink_idx[m]:
			var line_v: float = 0.0
			if _player != null and is_speaking():
				line_v = _blink_meshes[m].get_blend_shape_value(i)
			_blink_meshes[m].set_blend_shape_value(i, maxf(v, line_v) if v > 0.0 else line_v)


func _schedule_blink() -> void:
	_next_blink = randf_range(blink_min, maxf(blink_min, blink_max))


func _player_script() -> Script:
	for c: Dictionary in ProjectSettings.get_global_class_list():
		if c.get("class") == &"FaceCurvesPlayer":
			return load(c["path"])
	return null


# <stem>.face.json + an audio file with the same stem, next to the scene (works in exports: audio by resource name)
func _find_lines() -> void:
	var dir: String = scene_file_path.get_base_dir()
	if dir == "":
		return
	for f: String in DirAccess.get_files_at(dir):
		if not f.ends_with(".face.json"):
			continue
		var stem: String = f.trim_suffix(".face.json")
		for ext: String in [".ogg", ".mp3", ".wav"]:
			var audio: String = dir.path_join(stem + ext)
			if ResourceLoader.exists(audio):
				_lines[stem] = [dir.path_join(f), audio]
				break
