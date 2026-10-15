local function startup(screens, command, target, missing_window)
  local handler
  local spawned = {}
  local host = {
    target_triple = target or "aarch64-apple-darwin",
    config_builder = function() return {} end,
    font = function(name) return name end,
    action_callback = function(callback) return callback end,
    action = setmetatable({ SpawnTab = function(domain) return domain end }, {
      __call = function(_, action) return action end,
    }),
    gui = { screens = function() return screens end },
    on = function(event, callback)
      assert(event == "gui-startup")
      assert(type(callback) == "function")
      handler = callback
    end,
    mux = {
      spawn_window = function(options)
        local record = { options = options, maximized = false }
        spawned[#spawned + 1] = record
        return nil, nil, {
          gui_window = function()
            if missing_window then return nil end
            return { maximize = function() record.maximized = true end }
          end,
        }
      end,
    },
  }
  package.loaded.wezterm = host
  local config = dofile("wezterm/wezterm.lua")
  assert(type(handler) == "function", "startup handler must be registered")
  assert(type(config) == "table", "configuration must load")
  handler(command)
  return spawned, config
end

local laptop = { name = "Built-in Retina Display", x = 0, y = 0, width = 3024, height = 1964 }
local external = { name = "External Display", x = -3840, y = -300, width = 3840, height = 2160 }
local single = { main = laptop, active = laptop, by_name = { [laptop.name] = laptop } }
local dual = { main = external, active = laptop, by_name = {
  [laptop.name] = laptop,
  [external.name] = external,
} }
local failures = 0

local function check(name, callback)
  local passed, message = pcall(callback)
  if passed then
    print("PASS " .. name)
  else
    failures = failures + 1
    print("FAIL " .. name .. ": " .. tostring(message))
  end
end

check("laptop creates one maximized Herdr window", function()
  local windows, config = startup(single)
  assert(#windows == 1, "one display requires one window")
  assert(windows[1].maximized, "window must fill the display")
  assert(windows[1].options.position.origin.Named == laptop.name)
  assert(table.concat(config.default_prog, " ") == "/usr/bin/env -u HERDR_ENV /bin/zsh -lc exec herdr")
  assert(windows[1].options.width == nil, "pixel dimensions must not be used as terminal columns")
end)

check("two displays create distinct maximized windows in one session", function()
  local windows, config = startup(dual)
  assert(#windows == 2, "two displays require two windows")
  local seen = {}
  for _, window in ipairs(windows) do
    local position = window.options.position
    local name = position.origin.Named
    assert(dual.by_name[name], "window must target a connected display")
    assert(not seen[name], "each display must receive only one window")
    assert(position.x == 0 and position.y == 0)
    assert(window.maximized)
    assert(window.options.args == nil, "all windows must inherit the shared default program")
    seen[name] = true
  end
  assert(config.default_prog[#config.default_prog] == "exec herdr")
end)

check("startup metadata is copied without mutating the caller", function()
  local command = { domain = "DefaultDomain",
    set_environment_variables = { EXAMPLE = "value" }, position = { x = 42, y = 23 } }
  local windows = startup(dual, command)
  assert(#windows == 2)
  assert(command.position.x == 42 and command.position.y == 23)
  for _, window in ipairs(windows) do
    assert(window.options ~= command)
    assert(window.options.domain == "DefaultDomain")
    assert(window.options.set_environment_variables == command.set_environment_variables)
  end
end)

check("explicit commands execute once with all launch options intact", function()
  local command = { args = { "printf", "%s", "argument with spaces" }, cwd = "/tmp",
    domain = "DefaultDomain", position = { x = 17, y = 29 } }
  local windows = startup(dual, command)
  assert(#windows == 1, "explicit commands must not execute on every display")
  assert(windows[1].options == command, "the complete command must be preserved")
end)

check("named-domain launches are left to native WezTerm startup", function()
  local command = { domain = { DomainName = "local" }, args = { "printf", "once" } }
  local windows = startup(dual, command)
  assert(#windows == 0, "native startup already executes named-domain commands")
  assert(command.domain.DomainName == "local")
  local attach_windows = startup(dual, { domain = { DomainName = "local" } })
  assert(#attach_windows == 0, "native startup also owns named-domain attachment")
end)

check("cwd launches preserve the default program materialized by WezTerm", function()
  local _, config = startup(single)
  local command = { cwd = "/tmp/project with spaces", domain = "DefaultDomain",
    args = config.default_prog }
  local windows = startup(dual, command)
  assert(#windows == 1)
  assert(windows[1].options == command)
end)

check("Linux retains one default shell window", function()
  local windows, config = startup(dual, nil, "x86_64-unknown-linux-gnu")
  assert(#windows == 1)
  assert(config.default_prog == nil, "Herdr default must be scoped to macOS")
end)

check("new Herdr clients do not inherit the nested-session marker", function()
  local _, config = startup(single)
  local command = "HERDR_ENV=1 "
  for index, argument in ipairs(config.default_prog) do
    if index == #config.default_prog then break end
    command = command .. "'" .. argument:gsub("'", "'\\''") .. "' "
  end
  local passed = os.execute(command .. "'test \"${HERDR_ENV+x}\" != x'")
  assert(passed == true or passed == 0, "new outer clients must not look like nested Herdr")
end)

check("startup rejects an impossible empty display enumeration", function()
  local ok, message = pcall(startup, { by_name = {} })
  assert(not ok)
  assert(tostring(message):find("at least one display", 1, true))
end)

check("startup rejects a missing GUI window", function()
  local ok, message = pcall(startup, single, nil, nil, true)
  assert(not ok)
  assert(tostring(message):find("GUI window", 1, true))
end)

assert(failures == 0, tostring(failures) .. " startup checks failed")
