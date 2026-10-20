class_name FaceCurvesClip
extends RefCounted
## One validated face-curves/1 clip (3d-animator skill format): blend-shape curves sampled at `fps`.
## Index i is at audio time i / fps - lead_in. Presentation data only: never gameplay truth or save state.

const FORMAT := "face-curves/1"

var id: String = ""
var fps: float = 60.0
var lead_in: float = 0.0
var tail: float = 0.0
var duration: float = 0.0
var frames: int = 0
## Curve name -> samples (0..1), all of length `frames`.
var curves: Dictionary[StringName, PackedFloat32Array] = {}


## Load and validate a clip; returns null and reports the file/field on any error.
static func load_file(path: String) -> FaceCurvesClip:
	var text: String = FileAccess.get_file_as_string(path)
	if text.is_empty():
		push_error("%s: cannot read face clip" % path)
		return null
	var data: Variant = JSON.parse_string(text)
	if not data is Dictionary:
		push_error("%s: root is not a JSON object" % path)
		return null
	return from_dict(data, path)


# GPT: explicit structure checks at the JSON boundary (AGENTS §7/§10); no silent fallback to an empty face.
static func from_dict(d: Dictionary, path: String = "<dict>") -> FaceCurvesClip:
	if d.get("format") != FORMAT:
		push_error("%s: format must be %s" % [path, FORMAT])
		return null
	for field: String in ["fps", "lead_in", "tail", "duration", "frames"]:
		if not (d.get(field) is float or d.get(field) is int):
			push_error("%s: field '%s' must be a number" % [path, field])
			return null
	var clip := FaceCurvesClip.new()
	clip.id = str(d.get("id", ""))
	clip.fps = float(d.fps)
	clip.lead_in = float(d.lead_in)
	clip.tail = float(d.tail)
	clip.duration = float(d.duration)
	clip.frames = int(d.frames)
	if clip.fps <= 0.0 or clip.frames < 2:
		push_error("%s: fps must be > 0 and frames >= 2" % path)
		return null
	if not d.get("curves") is Dictionary or (d.curves as Dictionary).is_empty():
		push_error("%s: 'curves' must be a non-empty object" % path)
		return null
	for key: Variant in d.curves:
		var samples: Variant = d.curves[key]
		if not samples is Array or (samples as Array).size() != clip.frames:
			push_error("%s: curves.%s must be an array of %d numbers" % [path, key, clip.frames])
			return null
		clip.curves[StringName(key)] = PackedFloat32Array(samples)
	return clip


## Total playable span in audio time: [-lead_in, duration + tail].
func end_time() -> float:
	return duration + tail


## Curve values at audio time `t` (seconds), linearly interpolated and clamped to the clip.
func sample(t: float) -> Dictionary[StringName, float]:
	var f: float = clampf((t + lead_in) * fps, 0.0, float(frames - 1))
	var i: int = mini(int(f), frames - 2)
	var w: float = f - float(i)
	var out: Dictionary[StringName, float] = {}
	for key: StringName in curves:
		var c: PackedFloat32Array = curves[key]
		out[key] = lerpf(c[i], c[i + 1], w)
	return out
