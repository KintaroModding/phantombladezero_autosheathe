-- Auto Sheathe for Phantom Blade Zero.
--
-- Puts the player's weapon away a few seconds after a fight: once the weapon is drawn and the player is out of combat
-- and doing nothing for SheatheDelay seconds, the mod calls the player's own Unarm(). BP_RenewalPlayer_C overrides it
-- to activate the game's sheathe ability (TryActivateAbilitiesByTag), so the animation and the game's rules about when
-- it is allowed are the same as when the game does it. If the weapon is still drawn after a sheathe, the mod tries
-- again after RetrySeconds, at most MaxTries times, then waits for the next fight or draw. The only auto sheathe of
-- our Phantom Blade Zero mods (user decision 2026-11-01).
--
-- What stops it: the player's main anim Blueprint (PBZ_ABP_Hun_Base_C) copies the player's state into flags:
-- GameplayTag_IsInCombat, the busy flags in BUSY (attacking, dodging, blocking, aiming, dialogue, ...) and
-- CombatMontageActive; WaitForMontages also waits for any montage; the pawn's IsControlByDialogue; falling
-- (CharacterMovement); WaitForLockOn waits while BP_Player_Base_C.PBZTargeting has a lock target.
--
-- How: every CHECK_INTERVAL_MS on the game thread. Times are game time (GameplayStatics:GetTimeSeconds; they stop
-- while paused). No search by name on the timer: the player controller comes from the game's ClientRestart (a hook)
-- and is kept while it is valid; only while there is none (menus, a mod started mid-game) one FindFirstOf at most
-- every SEARCH_SECONDS. The player class is found once.
--
-- Taken over from the user's AutoSheathe 1 (an ini file and two keys): the same rules; the ini became config.lua, read
-- live, and the keys (HOME: sheathe now, END: reload) are gone (user decision 2026-11-01); the controller is kept
-- instead of being looked up by its path four times a second.
--
-- Settings: the player edits Scripts\config.lua. The mod reads it at start and again every CONFIG_INTERVAL_MS, so a
-- change shows without a restart; a broken or half-saved file keeps the last settings. DEFAULTS holds every setting
-- with its default. A player (or a mod manager) keeps their config.lua across updates, so a new main.lua can meet an
-- older file: a setting that the file lacks, or has with another type, keeps its default, and the log says so. Read a
-- setting only from Settings, never as `config.X or default`: for a true/false setting, `false or true` is true.

local MOD_NAME = "Auto Sheathe"
local VERSION = "1.0"
local CHECK_INTERVAL_MS = 250
local CONFIG_INTERVAL_MS = 5000
-- While there is no player controller, search for one at most this often.
local SEARCH_SECONDS = 5
-- A busy reason more than this long after a try (and every fight) starts the tries over; the montage of the mod's own
-- sheathe, just after a try, does not.
local RETRY_RESET_EXTRA_SECONDS = 2
local CONTROLLER_CLASS = "BP_PlayerController_C"
local PLAYER_CLASS = "/Script/ProjectPBZ.PBZCharacter_Player"
local CLIENT_RESTART = "/Script/Engine.PlayerController:ClientRestart"
-- Log at most this many error lines in total, and this many LogDetail lines per game start.
local MAX_ERROR_LOGS = 5
local MAX_DETAIL_LOGS = 400

-- Every setting with its default; config.lua ships the same names and values (tests\test_main.py checks it).
local DEFAULTS = {
    Enable = true,
    SheatheDelay = 4,
    WaitForLockOn = true,
    WaitForMontages = true,
    RetrySeconds = 3,
    MaxTries = 3,
    LogDetail = false,
}
-- Number settings outside their range are clamped.
local LIMITS = {
    SheatheDelay = { 0, 60 },
    RetrySeconds = { 0.5, 60 },
    MaxTries = { 1, 10 },
}

-- The busy flags of the anim Blueprint: any of them true = the player is doing something.
local BUSY = {
    { "GameplayTag_IsMelee", "attacking" },
    { "GameplayTag_IsDashing", "dodging" },
    { "GameplayTag_IsStance", "blocking" },
    { "GameplayTag_IsFocusing", "focusing" },
    { "GameplayTag_IsFiring", "firing" },
    { "GameplayTag_IsReloading", "reloading" },
    { "GameplayTag_IsADS", "aiming" },
    { "GameplayTag_IsDialogue", "in dialogue" },
}

local UEHelpers = require("UEHelpers")

local errors = 0
local details = 0

local function Log(message)
    print(string.format("[%s] %s\n", MOD_NAME, message))
end

local function LogError(message)
    errors = errors + 1
    if errors <= MAX_ERROR_LOGS then
        Log(message)
    end
end

local Settings = {}

-- LogDetail lines; message is a function, so nothing is built while LogDetail is off.
local function Detail(message)
    if Settings.LogDetail and details < MAX_DETAIL_LOGS then
        details = details + 1
        Log(message())
    end
end

local function Valid(object)
    if object == nil then
        return false
    end
    local ok, valid = pcall(function()
        return object:IsValid()
    end)
    return ok and valid == true
end

-- A flag or a call: true or false, or nil when it cannot be read (a missing property never counts as true).
local function Bool(fn)
    local ok, value = pcall(fn)
    if not ok then
        return nil
    end
    return value == true
end

---------------------------------------------------------------------------------------------------------------------
-- Settings
---------------------------------------------------------------------------------------------------------------------

local function CopyDefaults()
    local settings = {}
    for name, value in pairs(DEFAULTS) do
        settings[name] = value
    end
    return settings
end

-- One line for the log: every setting, sorted by name.
local function Describe(settings)
    local names = {}
    for name in pairs(settings) do
        names[#names + 1] = name
    end
    table.sort(names)
    local parts = {}
    for i, name in ipairs(names) do
        parts[i] = name .. "=" .. tostring(settings[name])
    end
    return table.concat(parts, ", ")
end

-- Lua's line number and reason, without the chunk name.
local function Reason(message)
    message = tostring(message)
    local line, reason = message:match("config%.lua:(%d+): ([^\n]*)")
    return line and ("line " .. line .. ": " .. reason) or (message:gsub("%s*\n%s*", " "))
end

-- DEFAULTS with the values of config.lua's text over them; nil and the reason when the text is not a usable file.
local function ParseConfig(text)
    local chunk, problem = load(text, "=config.lua", "t", {})
    if not chunk then
        return nil, "config.lua not read (" .. Reason(problem) .. ")"
    end
    local ok, config = pcall(chunk)
    if not ok then
        return nil, "config.lua not read (" .. Reason(config) .. ")"
    end
    if type(config) ~= "table" then
        return nil, "config.lua does not return a table"
    end
    local settings = CopyDefaults()
    for name, value in pairs(config) do
        local default = DEFAULTS[name]
        local limit = LIMITS[name]
        if default == nil then
            Log("config.lua: unknown setting " .. tostring(name) .. " ignored.")
        elseif type(value) ~= type(default) then
            Log(string.format("config.lua: %s must be a %s; the default %s is used.", name, type(default),
                tostring(default)))
        elseif limit and value ~= value then
            Log(string.format("config.lua: %s is not a number; the default %s is used.", name, tostring(default)))
        elseif limit and (value < limit[1] or value > limit[2]) then
            local clamped = math.min(limit[2], math.max(limit[1], value))
            Log(string.format("config.lua: %s = %s is outside %s to %s; %s is used.", name, tostring(value),
                tostring(limit[1]), tostring(limit[2]), tostring(clamped)))
            settings[name] = clamped
        else
            settings[name] = value
        end
    end
    settings.MaxTries = math.floor(settings.MaxTries)
    return settings
end

local configPath = nil
-- The text of the last read; false: no file at the last read; nil: not read yet.
local configText = nil

-- Reads config.lua when its text changed since the last read. At start, a missing or broken file means the defaults;
-- later, a broken file keeps the last settings (a half-saved file), and a missing one means the defaults.
local function ReadConfig()
    local atStart = configText == nil
    configPath = configPath or package.searchpath("config", package.path)
    local text = false
    if configPath then
        local file = io.open(configPath, "rb")
        if file then
            text = file:read("a") or false
            file:close()
        end
    end
    if text == configText then
        return
    end
    configText = text
    local settings, problem
    if text == false then
        settings, problem = CopyDefaults(), nil
        Log("No config.lua; every setting uses its default.")
    else
        settings, problem = ParseConfig(text)
    end
    if not settings then
        if atStart then
            Log(problem .. "; every setting uses its default.")
            settings = CopyDefaults()
        else
            Log(problem .. "; the last settings stay.")
            return
        end
    end
    local line = Describe(settings)
    if atStart or line ~= Describe(Settings) then
        Log("Settings: " .. line)
    end
    Settings = settings
end

---------------------------------------------------------------------------------------------------------------------
-- The player
---------------------------------------------------------------------------------------------------------------------

-- The player controller, kept while it is valid and still the same object (UE4SS's IsValid only checks that its
-- address holds a live object), and its full name.
local controller, controllerName = nil, nil
local nextSearch = 0
local playerClass = nil

local function KeepController(object)
    if Valid(object) then
        controller, controllerName = object, object:GetFullName()
    end
end

local function GetController()
    if Valid(controller) and controller:GetFullName() == controllerName then
        return controller
    end
    controller = nil
    local now = os.clock()
    if now < nextSearch then
        return nil
    end
    nextSearch = now + SEARCH_SECONDS
    KeepController(FindFirstOf(CONTROLLER_CLASS))
    if controller then
        Detail(function() return "player controller found: " .. controllerName end)
    end
    return controller
end

-- The player's pawn, or nil (none yet, or not the player class: a cutscene's pawn, a vehicle).
local function GetPawn()
    local pc = GetController()
    if pc == nil then
        return nil
    end
    local pawn = pc.Pawn
    if not Valid(pawn) then
        return nil
    end
    if not Valid(playerClass) then
        playerClass = StaticFindObject(PLAYER_CLASS)
        if not Valid(playerClass) then
            playerClass = nil
            return nil
        end
    end
    if Bool(function() return pawn:IsA(playerClass) end) ~= true then
        return nil
    end
    return pawn
end

local function GetAnim(pawn)
    local anim = nil
    pcall(function()
        local mesh = pawn.Mesh
        if Valid(mesh) then
            anim = mesh:GetAnimInstance()
        end
    end)
    return Valid(anim) and anim or nil
end

local function GameTime(pawn)
    local ok, t = pcall(function()
        return UEHelpers.GetGameplayStatics():GetTimeSeconds(pawn)
    end)
    if ok and type(t) == "number" then
        return t
    end
    return os.clock()
end

local function LockedOn(pawn)
    return Bool(function()
        local targeting = pawn.PBZTargeting
        return Valid(targeting) and targeting:HasLockTarget()
    end)
end

local function Falling(pawn)
    return Bool(function()
        local movement = pawn.CharacterMovement
        return Valid(movement) and movement:IsFalling()
    end)
end

-- What the player is doing, or nil when nothing stops a sheathe.
local function BusyReason(pawn, anim)
    if Bool(function() return anim.GameplayTag_IsInCombat end) then
        return "in combat"
    end
    for _, flag in ipairs(BUSY) do
        local name = flag[1]
        if Bool(function() return anim[name] end) then
            return flag[2]
        end
    end
    if Bool(function() return anim.CombatMontageActive end) then
        return "combat montage"
    end
    if Settings.WaitForMontages and Bool(function() return anim:IsAnyMontagePlaying() end) then
        return "montage playing"
    end
    if Bool(function() return pawn.IsControlByDialogue end) then
        return "controlled by dialogue"
    end
    if Falling(pawn) then
        return "in the air"
    end
    if Settings.WaitForLockOn and LockedOn(pawn) then
        return "locked on"
    end
    return nil
end

---------------------------------------------------------------------------------------------------------------------
-- The sheathe
---------------------------------------------------------------------------------------------------------------------

-- quietSince: game time since the player is idle with the weapon drawn; nextTry, lastTry: game times of the tries;
-- tries, gaveUp: the tries since the last fight or draw; armed: the weapon state of the last check; reason: the last
-- busy reason (to log each change once); armedMissLogged: IsArmed() was unreadable once.
local T = {}
local function ResetState()
    T = { quietSince = nil, nextTry = 0, lastTry = -1000, tries = 0, gaveUp = false, armed = nil, reason = false,
        armedMissLogged = false }
end
ResetState()

local function Sheathe(pawn, why)
    local ok, result = pcall(function()
        return pawn:Unarm()
    end)
    if ok then
        Detail(function() return string.format("sheathe (%s): Unarm() returned %s", why, tostring(result)) end)
    else
        LogError(string.format("sheathe (%s): Unarm() failed: %s", why, tostring(result)))
    end
end

local function Check()
    if not Settings.Enable then
        return
    end
    local pawn = GetPawn()
    if pawn == nil then
        if T.armed ~= nil then
            ResetState()
        end
        return
    end
    local anim = GetAnim(pawn)
    if anim == nil then
        return
    end
    local armed = Bool(function() return pawn:IsArmed() end)
    if armed == nil then
        if not T.armedMissLogged then
            T.armedMissLogged = true
            Log("IsArmed() cannot be read (a game update?); the mod does nothing.")
        end
        return
    end
    if armed ~= T.armed then
        Detail(function() return "weapon " .. (armed and "drawn" or "away") end)
        T.armed = armed
        T.quietSince, T.tries, T.gaveUp = nil, 0, false
    end
    if not armed then
        return
    end

    local now = GameTime(pawn)
    local reason = BusyReason(pawn, anim)
    if reason ~= nil then
        if reason ~= T.reason then
            Detail(function() return "waiting: " .. reason end)
        end
        T.reason = reason
        T.quietSince = nil
        -- A new fight or the player's own action starts the tries over; the montage of our own sheathe does not.
        if reason == "in combat" or now - T.lastTry > Settings.RetrySeconds + RETRY_RESET_EXTRA_SECONDS then
            T.tries, T.gaveUp = 0, false
        end
        return
    end
    if T.quietSince == nil then
        T.quietSince = now
        Detail(function() return string.format("quiet - sheathing in %.1f s", Settings.SheatheDelay) end)
        T.reason = nil
    end
    if now - T.quietSince < Settings.SheatheDelay or now < T.nextTry then
        return
    end
    if T.tries >= Settings.MaxTries then
        if not T.gaveUp then
            T.gaveUp = true
            Detail(function() return string.format("still drawn after %d tries - waiting for the next fight or draw",
                T.tries) end)
        end
        return
    end
    T.tries = T.tries + 1
    T.lastTry = now
    T.nextTry = now + Settings.RetrySeconds
    Sheathe(pawn, string.format("try %d after %.1f s quiet", T.tries, now - T.quietSince))
end

---------------------------------------------------------------------------------------------------------------------
-- Start
---------------------------------------------------------------------------------------------------------------------

Settings = CopyDefaults()
Log(VERSION .. " loaded.")
local read, problem = pcall(ReadConfig)
if not read then
    LogError("Error while reading config.lua: " .. tostring(problem))
end
if not Settings.Enable then
    Log("Enable = false in config.lua: the mod does nothing until it is true.")
end

local function CheckStep()
    local ok, err = pcall(Check)
    if not ok then
        LogError("Error: " .. tostring(err))
    end
end

local function ConfigStep()
    local ok, err = pcall(ReadConfig)
    if not ok then
        LogError("Error while reading config.lua: " .. tostring(err))
    end
end

-- The game restarts the player controller with each new pawn (a map load, a respawn): keep that controller.
local hooked, hookProblem = pcall(RegisterHook, CLIENT_RESTART, function(context)
    local ok, err = pcall(function()
        KeepController(context:get())
        ResetState()
    end)
    if not ok then
        LogError("Error in ClientRestart: " .. tostring(err))
    end
end)
if not hooked then
    Log("No hook on ClientRestart (" .. tostring(hookProblem) .. "); the controller is searched instead.")
end

RegisterLoadMapPostHook(function()
    local ok, err = pcall(function()
        -- The old world's controller is gone: the next check finds the new one (or ClientRestart brings it).
        controller, controllerName = nil, nil
        nextSearch = 0
        ResetState()
    end)
    if not ok then
        LogError("Error after the map load: " .. tostring(err))
    end
end)

-- Both loops run on the game thread (UE4SS's Delayed Action API): no Lua on a second thread (Witch Time's crash
-- lesson, knowledge\engine\ue4ss.md). A UE4SS without it gets the old LoopAsync loops, and the log says so.
if type(LoopInGameThreadWithDelay) == "function" then
    LoopInGameThreadWithDelay(CHECK_INTERVAL_MS, CheckStep)
    LoopInGameThreadWithDelay(CONFIG_INTERVAL_MS, ConfigStep)
else
    Log("This UE4SS has no game-thread loops (LoopInGameThreadWithDelay): the older LoopAsync is used; a newer UE4SS "
        .. "is safer.")
    LoopAsync(CHECK_INTERVAL_MS, function()
        ExecuteInGameThread(CheckStep)
        -- false keeps the loop running.
        return false
    end)
    LoopAsync(CONFIG_INTERVAL_MS, function()
        ExecuteInGameThread(ConfigStep)
        return false
    end)
end
