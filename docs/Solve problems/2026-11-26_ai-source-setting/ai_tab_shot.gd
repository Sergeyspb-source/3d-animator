extends SceneTree
## Shots of the settings' AI tab for the write-up: the panel drawn at 1280x720 (the game's base size) into a 2560x1440 SubViewport,
## Russian strings, one picture per source. No request is sent (the test button is not pressed).
const SettingsPanel = preload("res://game/ui/menu/settings_panel.gd")
const SettingsProfile = preload("res://game/settings/settings_profile.gd")
const Codec = preload("res://game/persistence/settings_codec.gd")
const NAMES: Array[String] = ["ai_tab_local", "ai_tab_openrouter", "ai_tab_opencode_go"]

func _initialize() -> void:
	var watchdog := Timer.new()
	watchdog.wait_time = 60.0
	watchdog.one_shot = true
	watchdog.autostart = true
	watchdog.timeout.connect(func() -> void:
		print("SHOT watchdog")
		quit(2))
	root.add_child(watchdog)
	_run.call_deferred()

func _frames(n: int) -> void:
	for i: int in n:
		await process_frame

func _run() -> void:
	var out: String = OS.get_environment("SHOT_OUT")
	TranslationServer.set_locale("ru_RU")
	var vp := SubViewport.new()
	vp.size = Vector2i(2560, 1440)
	vp.size_2d_override = Vector2i(1280, 720)
	vp.size_2d_override_stretch = true
	vp.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	root.add_child(vp)
	var bg := ColorRect.new()
	bg.color = Color(0.035, 0.035, 0.04)
	bg.size = Vector2(1280, 720)
	vp.add_child(bg)
	var profile := SettingsProfile.new("user://shot_settings.json")
	profile.settings = Codec.defaults()
	var panel := SettingsPanel.new()
	vp.add_child(panel)
	panel.open(profile)
	panel._tabs.current_tab = 4
	for i: int in NAMES.size():
		panel._ai._chosen(i)
		await _frames(8)
		var image: Image = vp.get_texture().get_image()
		var path: String = out.path_join(NAMES[i] + ".png")
		print("SHOT ", path, " ", image.get_size(), " err=", image.save_png(path), " key=", panel._ai._key.text)
	quit(0)
