local wezterm = require("wezterm")
local mux = wezterm.mux
local config = wezterm.config_builder()

local is_windows = os.getenv("OS") and os.getenv("OS"):lower():find("windows")
local is_macos = wezterm.target_triple:lower():find("darwin") ~= nil

wezterm.on('gui-startup', function(cmd)
  local width_percent = 0.90
  local height_percent = 0.80

  local screen = wezterm.gui.screens().main

  local pixel_width = screen.width * width_percent
  local pixel_height = screen.height * height_percent

  mux.spawn_window({
    width = math.floor(pixel_width),
    height = math.floor(pixel_height),
    args = mcd and cmd.args or nil,
  })
end)

-- ui
config.color_scheme = "rose-pine-moon"
config.max_fps = 120
config.font = wezterm.font("Hack Nerd Font")
config.font_size = 13.0

config.enable_tab_bar = true
config.hide_tab_bar_if_only_one_tab = true
config.window_decorations = "RESIZE"
config.window_frame = {
	font = wezterm.font("Hack Nerd Font", { weight = "Bold" }),
}

config.inactive_pane_hsb = {
	saturation = 0.0,
	brightness = 0.5,
}

if is_windows then
	config.win32_system_backdrop = "Acrylic"
	config.window_background_opacity = 0.7
	config.window_frame.font_size = 10.0
end

if is_macos then
	config.window_background_opacity = 0.8
	config.macos_window_background_blur = 50
	config.window_frame.font_size = 13.0
end

--shell
if is_windows then
	config.default_domain = "WSL:Ubuntu-24.04"
end

--keys
local maximize_window = wezterm.action_callback(function(window, _pane)
	window:maximize()
end)

config.disable_default_key_bindings = true
config.leader = { key = "Space", mods = "CTRL" }
config.keys = {
	{
		key = "v",
		mods = "CMD",
		action = wezterm.action({ PasteFrom = "Clipboard" }),
	},
	{
		key = "c",
		mods = "LEADER",
		action = wezterm.action.SpawnTab("CurrentPaneDomain"),
	},
}

return config
