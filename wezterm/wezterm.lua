local wezterm = require("wezterm")
local mux = wezterm.mux
local config = wezterm.config_builder()

local is_windows = os.getenv("OS") and os.getenv("OS"):lower():find("windows")
local is_macos = wezterm.target_triple:lower():find("darwin") ~= nil

wezterm.on('gui-startup', function(cmd)
  if cmd and type(cmd.domain) == "table" and cmd.domain.DomainName then
    return
  end
  if not is_macos or (cmd and cmd.args and #cmd.args > 0) then
    mux.spawn_window(cmd or {})
    return
  end

  local screen_names = {}
  for name in pairs(wezterm.gui.screens().by_name) do
    screen_names[#screen_names + 1] = name
  end
  assert(#screen_names > 0, "GUI startup requires at least one display")
  table.sort(screen_names)

  for _, name in ipairs(screen_names) do
    local options = {}
    for key, value in pairs(cmd or {}) do
      options[key] = value
    end
    options.position = { x = 0, y = 0, origin = { Named = name } }
    local _, _, window = mux.spawn_window(options)
    local gui_window = window:gui_window()
    assert(gui_window, "Startup must create a GUI window")
    gui_window:maximize()
  end
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
	config.default_prog = { "/usr/bin/env", "-u", "HERDR_ENV", "/bin/zsh", "-lc", "exec herdr" }
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
