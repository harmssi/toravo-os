-- Toravo OS – Hyprland (Lua config, Hyprland >= 0.56).  Loaded from ~/.config/hypr/hyprland.lua via dofile().
-- Own changes belong in ~/.config/hypr/hyprland.lua AFTER the dofile line (they win).
local function readfile(p)
    local f = io.open(p, "r"); if not f then return nil end
    local s = f:read("*a"); f:close(); return s
end
local function trim(s) return s and (s:gsub("^%s+", ""):gsub("%s+$", "")) or nil end

local LITE   = os.getenv("TORAVO_LITE") == "1"                       -- no 3D acceleration (VM, very old GPU): no blur/shadows/animations
local NVIDIA = readfile("/proc/driver/nvidia/version") ~= nil
local KB     = trim(readfile("/etc/toravo/xkb_layout")) or "de"
local KBV    = trim(readfile("/etc/toravo/xkb_variant")) or ""

local terminal = LITE and "foot" or "kitty"

hl.monitor({ output = "", mode = "preferred", position = "auto", scale = "auto" })

hl.env("XCURSOR_SIZE", "24")
hl.env("HYPRCURSOR_SIZE", "24")
hl.env("QT_QPA_PLATFORM", "wayland;xcb")
hl.env("QT_QPA_PLATFORMTHEME", "qt6ct")
hl.env("GDK_BACKEND", "wayland,x11")
hl.env("MOZ_ENABLE_WAYLAND", "1")
hl.env("ELECTRON_OZONE_PLATFORM_HINT", "auto")
if NVIDIA then
    hl.env("LIBVA_DRIVER_NAME", "nvidia")
    hl.env("__GLX_VENDOR_LIBRARY_NAME", "nvidia")
    hl.env("NVD_BACKEND", "direct")
end

hl.on("hyprland.start", function()
    hl.exec_cmd("/usr/bin/toravo-autostart hyprland")
end)

-- Look: panels like in the trailer – dark, 12 px radius, 1-2 px border in the violet -> blue -> cyan gradient, no glass
hl.config({
    general = {
        gaps_in = 7,
        gaps_out = { top = 8, right = 16, bottom = 16, left = 16 },
        border_size = 2,
        col = {
            active_border   = { colors = { "rgba(8a5cf6ff)", "rgba(6f9be0ff)", "rgba(5ab0d0ff)" }, angle = 45 },
            inactive_border = "rgba(24213aff)",
        },
        resize_on_border = true,
        layout = "dwindle",
    },
    decoration = {
        rounding = 12,
        rounding_power = 2,
        active_opacity = 1.0,
        inactive_opacity = 1.0,
        shadow = { enabled = not LITE, range = 28, render_power = 3, color = "rgba(00000099)", color_inactive = "rgba(00000066)" },
        blur = { enabled = false },
        dim_inactive = false,
    },
    animations = { enabled = not LITE },
    dwindle = { preserve_split = true },
    misc = {
        disable_hyprland_logo = true,
        disable_splash_rendering = true,
        force_default_wallpaper = 0,
        background_color = "rgb(07070d)",
        focus_on_activate = true,
        enable_anr_dialog = true,
    },
    ecosystem = { no_update_news = true, no_donation_nag = true },
    cursor = { no_hardware_cursors = (LITE or NVIDIA) and 1 or 0 },
    input = {
        kb_layout = KB, kb_variant = KBV,
        follow_mouse = 1, sensitivity = 0,
        numlock_by_default = true,
        touchpad = { natural_scroll = true, tap_to_click = true },
    },
})

-- Subtle animations (short, ease-out, no bouncing)
hl.curve("toravo",  { type = "bezier", points = { {0.22, 1}, {0.36, 1} } })
hl.curve("linear",  { type = "bezier", points = { {0, 0}, {1, 1} } })
hl.animation({ leaf = "global",     enabled = true, speed = 6,   bezier = "toravo" })
hl.animation({ leaf = "windowsIn",  enabled = true, speed = 3.2, bezier = "toravo", style = "popin 94%" })
hl.animation({ leaf = "windowsOut", enabled = true, speed = 2.2, bezier = "linear", style = "popin 94%" })
hl.animation({ leaf = "windowsMove",enabled = true, speed = 3.5, bezier = "toravo" })
hl.animation({ leaf = "border",     enabled = true, speed = 4,   bezier = "toravo" })
hl.animation({ leaf = "fade",       enabled = true, speed = 3,   bezier = "toravo" })
hl.animation({ leaf = "layersIn",   enabled = true, speed = 2.6, bezier = "toravo", style = "fade" })
hl.animation({ leaf = "layersOut",  enabled = true, speed = 1.6, bezier = "linear", style = "fade" })
hl.animation({ leaf = "workspaces", enabled = true, speed = 3.2, bezier = "toravo", style = "slidefade 8%" })

-- Keys
local mod = "SUPER"
local function bind(k, d, o) hl.bind(k, d, o) end
bind(mod .. " + space",  hl.dsp.exec_cmd("toravo-commandbar"))
bind(mod .. " + Return", hl.dsp.exec_cmd(terminal))
bind(mod .. " + D",      hl.dsp.exec_cmd("fuzzel"))
bind(mod .. " + S",      hl.dsp.exec_cmd("toravo-studio"))
bind(mod .. " + E",      hl.dsp.exec_cmd("thunar"))
bind(mod .. " + B",      hl.dsp.exec_cmd("firefox"))
bind(mod .. " + L",      hl.dsp.exec_cmd("loginctl lock-session"))
bind(mod .. " + Q",      hl.dsp.window.close())
bind(mod .. " + F",      hl.dsp.window.fullscreen())
bind(mod .. " + V",      hl.dsp.window.float({ action = "toggle" }))
bind(mod .. " + J",      hl.dsp.layout("togglesplit"))
bind(mod .. " + SHIFT + E", hl.dsp.exec_cmd("toravo-power"))
bind("Print",            hl.dsp.exec_cmd("toravo-screenshot area"))
bind("SHIFT + Print",    hl.dsp.exec_cmd("toravo-screenshot full"))
for _, d in ipairs({ "left", "right", "up", "down" }) do
    bind(mod .. " + " .. d, hl.dsp.focus({ direction = d }))
    bind(mod .. " + SHIFT + " .. d, hl.dsp.window.swap({ direction = d }))
end
for i = 1, 10 do
    local key = i % 10
    bind(mod .. " + " .. key, hl.dsp.focus({ workspace = i }))
    bind(mod .. " + SHIFT + " .. key, hl.dsp.window.move({ workspace = i }))
end
bind(mod .. " + mouse_down", hl.dsp.focus({ workspace = "e+1" }))
bind(mod .. " + mouse_up",   hl.dsp.focus({ workspace = "e-1" }))
bind(mod .. " + mouse:272", hl.dsp.window.drag(),   { mouse = true })
bind(mod .. " + mouse:273", hl.dsp.window.resize(), { mouse = true })
bind("XF86AudioRaiseVolume", hl.dsp.exec_cmd("wpctl set-volume -l 1 @DEFAULT_AUDIO_SINK@ 5%+"), { locked = true, repeating = true })
bind("XF86AudioLowerVolume", hl.dsp.exec_cmd("wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-"),      { locked = true, repeating = true })
bind("XF86AudioMute",        hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle"),     { locked = true })
bind("XF86MonBrightnessUp",  hl.dsp.exec_cmd("brightnessctl -e4 -n2 set 5%+"), { locked = true, repeating = true })
bind("XF86MonBrightnessDown",hl.dsp.exec_cmd("brightnessctl -e4 -n2 set 5%-"), { locked = true, repeating = true })
bind("XF86AudioPlay",  hl.dsp.exec_cmd("playerctl play-pause"), { locked = true })
bind("XF86AudioNext",  hl.dsp.exec_cmd("playerctl next"),       { locked = true })
bind("XF86AudioPrev",  hl.dsp.exec_cmd("playerctl previous"),   { locked = true })

-- Window rules: Toravo tools float centered; installer is fullscreen by itself
hl.window_rule({ name = "toravo-setup",  match = { class = "^(de.toravo.Setup)$" },  float = true, size = "1180 800", center = true })
hl.window_rule({ name = "toravo-dialog", match = { class = "^(de.toravo.Dialog)$" }, float = true, center = true })
hl.window_rule({ name = "pavucontrol",   match = { class = "^(org.pulseaudio.pavucontrol)$" }, float = true, size = "900 600", center = true })
hl.window_rule({ name = "polkit",        match = { class = "^(hyprpolkitagent)$" }, float = true, center = true })
hl.window_rule({ name = "suppress-maximize", match = { class = ".*" }, suppress_event = "maximize" })
hl.layer_rule({ name = "toravo-desk",   match = { namespace = "^(toravo-desk)$" }, no_anim = true })
hl.layer_rule({ name = "toravo-cmdbar", match = { namespace = "^(toravo-commandbar)$" }, dim_around = true })
