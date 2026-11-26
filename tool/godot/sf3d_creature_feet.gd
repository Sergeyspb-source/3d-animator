extends SkeletonModifier3D
class_name SF3DCreatureFeet
## A creature's paws put on uneven ground while its clips play (a slope, steps, a rock): the clips are made on flat
## ground, this moves them onto the real one. Each paw's ground is cast for straight down under it (a physics ray), the
## body goes up or down to the lowest of them (so a downhill leg still reaches), each leg's two upper bones turn to
## reach (two-bone IK, bending the way the clip bends them) and a standing paw tilts to the ground under it; the clip's
## own lift is kept (a paw in its swing stays as high over the new ground). By the bones' names of SF3D creatures:
## hips, leg_FL_1 .. leg_BR_5 (any number of bones a leg, three at least; a bird's leg_BL / leg_BR).
## Use: a child of the creature's Skeleton3D (modifiers run after the AnimationPlayer). The rays hit what is in
## `collision_mask`; put the creature's own collider in another layer, or its RID in `exclude`.

## the layers the paws stand on
@export_flags_3d_physics var collision_mask := 1
## the ray starts this share of the leg's height above the paw and ends this share below it
@export var ray_above := 0.7
@export var ray_below := 0.9
## the body goes up or down at most this share of the leg's height
@export var max_shift := 0.6
## how much a standing paw tilts to the ground's slope (0 not at all, 1 fully), at most `max_tilt` degrees
@export_range(0.0, 1.0) var align := 0.8
@export var max_tilt := 35.0
## how fast the body and the paws follow a change of the ground (a second's share, larger - quicker)
@export var follow := 14.0
## bodies the rays ignore (the creature's own collider)
@export var exclude: Array[RID] = []

var _legs: Array = []      # [{upper, lower, paw, toe, ball_rest: Vector3, h: float}]
var _hips := -1
var _floor := 0.0          # the clips' flat ground, the skeleton's space (the skin's lowest point at rest)
var _h := 1.0              # the legs' height
var _shift := 0.0
var _raise: Array = []
var _tilt: Array = []
var _ready_done := false


func _setup() -> void:
	var sk := get_skeleton()
	if sk == null:
		return
	_legs.clear()
	_hips = sk.find_bone("hips")
	for k in ["FL", "FR", "BL", "BR"]:
		var chain := []
		var i := 1
		while sk.find_bone("leg_%s_%d" % [k, i]) >= 0:
			chain.append(sk.find_bone("leg_%s_%d" % [k, i]))
			i += 1
		if chain.size() < 3:
			continue
		# (a root first when there are five, or four with a short first one: a shoulder blade, a pelvis)
		var lens := []
		var total := 0.0
		for j in range(1, chain.size()):
			var l: float = sk.get_bone_rest(chain[j]).origin.length()
			lens.append(l)
			total += l
		var root: bool = chain.size() >= 5 or (chain.size() == 4 and lens[0] < 0.2 * total)
		var c: Array = chain.slice(1) if root else chain
		var leg := {"upper": c[0], "lower": c[1], "paw": c[2], "toe": c[3] if c.size() > 3 else -1}
		var ball: Vector3 = _rest_global(sk, leg["toe"] if leg["toe"] >= 0 else leg["paw"])
		leg["ball_rest"] = ball
		leg["h"] = _rest_global(sk, leg["upper"]).y - ball.y
		_legs.append(leg)
	if _legs.is_empty():
		return
	var hs := 0.0
	for leg in _legs:
		hs += leg["h"]
	_h = maxf(hs / _legs.size(), 1e-3)
	# the flat ground: the skin's lowest point at rest (in the skeleton's space), else the lowest paw
	_floor = INF
	var inv := sk.global_transform.affine_inverse()
	for m in sk.find_children("*", "MeshInstance3D", true, false):
		var mi := m as MeshInstance3D
		if mi.mesh == null:
			continue
		var b: AABB = inv * mi.global_transform * mi.get_aabb()
		_floor = minf(_floor, b.position.y)
	if _floor == INF:
		_floor = 1e9
		for leg in _legs:
			_floor = minf(_floor, (leg["ball_rest"] as Vector3).y)
	_raise.resize(_legs.size())
	_tilt.resize(_legs.size())
	for i in _legs.size():
		_raise[i] = 0.0
		_tilt[i] = Quaternion()
	_ready_done = true


func _rest_global(sk: Skeleton3D, b: int) -> Vector3:
	var t := sk.get_bone_rest(b)
	var p := sk.get_bone_parent(b)
	while p >= 0:
		t = sk.get_bone_rest(p) * t
		p = sk.get_bone_parent(p)
	return t.origin


func _process_modification_with_delta(delta: float) -> void:
	var sk := get_skeleton()
	if sk == null:
		return
	if not _ready_done:
		_setup()
		if not _ready_done:
			return
	var xf := sk.global_transform
	var up_w := xf.basis.y.normalized()
	var up_s := (xf.basis.inverse() * up_w).normalized()
	var space := sk.get_world_3d().direct_space_state
	var k := 1.0 - exp(-follow * delta)
	# the ground under each paw: how far above (+) or below the clips' flat ground, its slope
	var ground := []
	var normal := []
	for leg in _legs:
		var ball: Vector3 = sk.get_bone_global_pose(leg["toe"] if leg["toe"] >= 0 else leg["paw"]).origin
		var flat := xf * Vector3(ball.x, _floor, ball.z)
		var q := PhysicsRayQueryParameters3D.create(flat + up_w * ray_above * _h * xf.basis.get_scale().y,
				flat - up_w * ray_below * _h * xf.basis.get_scale().y, collision_mask, exclude)
		var hit := space.intersect_ray(q)
		if hit.is_empty():
			ground.append(0.0)
			normal.append(up_s)
		else:
			ground.append((xf.affine_inverse() * (hit["position"] as Vector3)).y - _floor)
			normal.append((xf.basis.inverse() * (hit["normal"] as Vector3)).normalized())
	var low := INF
	for g in ground:
		low = minf(low, g)
	_shift = lerpf(_shift, clampf(low, -max_shift * _h, max_shift * _h), k)
	if _hips >= 0 and absf(_shift) > 1e-6:
		var t := sk.get_bone_global_pose(_hips)
		t.origin += up_s * _shift
		sk.set_bone_global_pose(_hips, t)
	for i in _legs.size():
		var leg: Dictionary = _legs[i]
		_raise[i] = lerpf(_raise[i], ground[i] - _shift, k)
		var ball_b: int = leg["toe"] if leg["toe"] >= 0 else leg["paw"]
		var B := sk.get_bone_global_pose(ball_b).origin
		var lift := (B - leg["ball_rest"] as Vector3).dot(up_s)
		# a standing paw (the clip holds it low) tilts to the ground: about the ball, so the ball stays on it
		var stand := clampf(1.0 - lift / (0.06 * _h), 0.0, 1.0)
		var want := Quaternion()
		var n: Vector3 = normal[i]
		if align > 0.0 and n.dot(up_s) < 0.9999:
			var full := Quaternion(up_s, n)
			var ang := minf(full.get_angle(), deg_to_rad(max_tilt))
			want = Quaternion(full.get_axis().normalized(), ang * align * stand) if full.get_angle() > 1e-5 else Quaternion()
		_tilt[i] = (_tilt[i] as Quaternion).slerp(want, k)
		var tq: Quaternion = _tilt[i]
		var A := sk.get_bone_global_pose(leg["upper"]).origin
		var K := sk.get_bone_global_pose(leg["lower"]).origin
		var paw_t := sk.get_bone_global_pose(leg["paw"])
		var W := paw_t.origin
		var Bt: Vector3 = B + up_s * float(_raise[i])
		var Wt: Vector3 = Bt + tq * (W - B)
		_reach(sk, leg, A, K, W, Wt, Basis(tq) * paw_t.basis)


func _reach(sk: Skeleton3D, leg: Dictionary, A: Vector3, K: Vector3, W: Vector3, Wt: Vector3, paw_basis: Basis) -> void:
	var l1 := A.distance_to(K)
	var l2 := K.distance_to(W)
	var d := Wt - A
	var dist := clampf(d.length(), absf(l1 - l2) * 1.02 + 1e-5, (l1 + l2) * 0.999)
	var u := d.normalized()
	var pole := (K - A) - u * (K - A).dot(u)   # (the way the clip bends the knee)
	if pole.length() < 1e-6:
		pole = u.cross(Vector3.RIGHT)
	pole = pole.normalized()
	var ca := (l1 * l1 + dist * dist - l2 * l2) / (2.0 * l1 * dist)
	var a := acos(clampf(ca, -1.0, 1.0))
	var K2 := A + (u * cos(a) + pole * sin(a)) * l1
	var W2 := A + u * dist
	var up_t := sk.get_bone_global_pose(leg["upper"])
	if (K - A).length() > 1e-6 and (K2 - A).length() > 1e-6:
		var q1 := Quaternion((K - A).normalized(), (K2 - A).normalized())
		sk.set_bone_global_pose(leg["upper"], Transform3D(Basis(q1) * up_t.basis, A))
	var lo_t := sk.get_bone_global_pose(leg["lower"])
	var Wc := sk.get_bone_global_pose(leg["paw"]).origin
	if (Wc - lo_t.origin).length() > 1e-6 and (W2 - lo_t.origin).length() > 1e-6:
		var q2 := Quaternion((Wc - lo_t.origin).normalized(), (W2 - lo_t.origin).normalized())
		sk.set_bone_global_pose(leg["lower"], Transform3D(Basis(q2) * lo_t.basis, lo_t.origin))
	sk.set_bone_global_pose(leg["paw"], Transform3D(paw_basis, W2))
