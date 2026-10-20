// Wind for trees, bushes and grass made by SF3D (blender_vegetation.py).
// Vertex colour of the model:  R = bend (0 at the root .. 1 at the top),  G = leaf flutter,  B = phase per clump.
// Many copies of the same plant (MultiMesh or separate nodes) move out of step by their world position.
shader_type spatial;
render_mode cull_disabled;

uniform sampler2D albedo_texture : source_color, filter_linear_mipmap, repeat_enable;
uniform vec4 albedo_color : source_color = vec4(1.0);
uniform float roughness : hint_range(0.0, 1.0) = 0.85;

// global wind: set the same values on every plant (or make them global shader uniforms in the project)
uniform vec2 wind_direction = vec2(1.0, 0.3);
uniform float wind_strength = 0.06;   // sway of the top in metres per metre of plant height
uniform float wind_speed = 1.1;       // slow sway
uniform float gust_strength = 0.5;    // 0 = steady, 1 = strong gusts
uniform float flutter_strength = 0.012;  // leaf shiver in metres
uniform float flutter_speed = 7.0;

varying float v_flutter;

void vertex() {
	float bend = COLOR.r;
	float flutter = COLOR.g;
	float phase = COLOR.b * 6.2831853;
	vec3 world_pos = NODE_POSITION_WORLD;
	// object scale: sway is relative to the plant's size
	float scale_y = length(MODEL_MATRIX[1].xyz);
	float t = TIME * wind_speed + dot(world_pos.xz, vec2(0.21, 0.17));
	float gust = 1.0 + gust_strength * (0.5 + 0.5 * sin(TIME * 0.37 + world_pos.x * 0.05));
	float sway = (sin(t + phase * 0.25) + 0.35 * sin(2.31 * t + 1.7 + phase * 0.5)) * gust;
	vec3 dir_world = normalize(vec3(wind_direction.x, 0.0, wind_direction.y));
	vec3 dir_local = normalize((inverse(MODEL_MATRIX) * vec4(dir_world, 0.0)).xyz);
	float height = max(VERTEX.y, 0.0);
	VERTEX += dir_local * sway * wind_strength * bend * (height + 0.3);
	// the top dips a little as it bends, so branches do not stretch
	VERTEX.y -= abs(sway) * wind_strength * 0.25 * bend * bend * height;
	// leaves shiver along their normal
	float shiver = sin(TIME * flutter_speed + phase + VERTEX.x * 13.0 + VERTEX.z * 11.0);
	VERTEX += NORMAL * shiver * flutter_strength * flutter / max(scale_y, 0.001);
	v_flutter = flutter;
}

void fragment() {
	vec4 c = texture(albedo_texture, UV) * albedo_color;
	ALBEDO = c.rgb;
	ROUGHNESS = roughness;
	// foliage seen from behind is the same colour (thin leaves, open crowns)
	if (!FRONT_FACING) {
		NORMAL = -NORMAL;
	}
}
