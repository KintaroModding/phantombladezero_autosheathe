"""Offline test of Scripts/main.lua with lupa (Lua 5.4) and small mocks of UE4SS and the game.

The mocks stand in for the UE4SS functions that the script uses (the game-thread loops LoopInGameThreadWithDelay, the
old LoopAsync, RegisterHook, RegisterLoadMapPostHook, FindFirstOf, StaticFindObject, UEHelpers) and for the game: the
player controller (from the ClientRestart hook or a search), the player with its weapon (IsArmed, Unarm), its anim
Blueprint's flags, its lock-on and movement, and a clock (game time and os.clock) that the test moves.

The checks: the loops and hooks; no search by name on the timer; the sheathe after SheatheDelay of quiet; every reason
to wait; the retries and the give-up; the controller kept, lost and found again; live settings; LogDetail lines. Then
the settings files a player may have instead of the shipped config.lua: main.lua must start, and every setting the
file does not give keeps its default; the shipped config.lua must hold exactly the defaults of main.lua.

Usage:
    python tests/test_main.py        (needs lupa: python -m pip install lupa)

Exit code: 0 = all checks passed, 1 = a check failed.
"""

import json
import sys
import tempfile
from pathlib import Path

from lupa import lua54

ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / "src" / "phantombladezero_autosheathe" / "Scripts" / "main.lua"
CONFIG = MAIN.parent / "config.lua"

MOCKS = r"""
LOG = {}
print = function(...) LOG[#LOG + 1] = table.concat({...}, "") end
CLOCK = 100
GAMETIME = 50
os.clock = function() return CLOCK end

LOOPS = {}
DELAYS = {}
ASYNC_LOOPS = 0
function LoopInGameThreadWithDelay(ms, callback) LOOPS[#LOOPS + 1] = callback DELAYS[#DELAYS + 1] = ms return #LOOPS end
function LoopAsync(ms, callback) ASYNC_LOOPS = ASYNC_LOOPS + 1 LOOPS[#LOOPS + 1] = callback DELAYS[#DELAYS + 1] = ms end
function ExecuteInGameThread(callback) callback() end
MAP_HOOKS = {}
function RegisterLoadMapPostHook(callback) MAP_HOOKS[#MAP_HOOKS + 1] = callback end
HOOKS = {}
function RegisterHook(path, callback) HOOKS[path] = callback return 1, 2 end
function RUN(ms) for i = 1, #LOOPS do if DELAYS[i] == ms then LOOPS[i]() end end end
-- `n` checks, each after 0.25 s of game time and real time.
function CHECK(n) for _ = 1, (n or 1) do CLOCK = CLOCK + 0.25 GAMETIME = GAMETIME + 0.25 RUN(250) end end
-- Checks for `seconds` of time.
function WAIT(seconds) CHECK(math.floor(seconds / 0.25 + 0.5)) end
function CONFIG() RUN(5000) end

local ObjectMeta = { __index = {
    IsValid = function(self) return self.valid ~= false end,
    GetFullName = function(self) return self.fullName or "Object /Game/Object" end,
} }
function Object(fields) return setmetatable(fields or {}, ObjectMeta) end

-- The anim Blueprint's flags (all false = the player is idle).
ANIM = Object({ GameplayTag_IsInCombat = false, GameplayTag_IsMelee = false, GameplayTag_IsDashing = false,
    GameplayTag_IsStance = false, GameplayTag_IsFocusing = false, GameplayTag_IsFiring = false,
    GameplayTag_IsReloading = false, GameplayTag_IsADS = false, GameplayTag_IsDialogue = false,
    CombatMontageActive = false })
MONTAGE = false
function ANIM:IsAnyMontagePlaying() return MONTAGE end
-- The player: the weapon drawn; Unarm puts it away unless UNARM_WORKS is false.
ARMED = true
ARMED_READABLE = true
UNARM_WORKS = true
UNARM_CALLS = 0
LOCKED = false
FALLING = false
IS_PLAYER = true
PLAYER_CLASS = Object({})
PAWN = Object({ Mesh = Object({}), PBZTargeting = Object({}), CharacterMovement = Object({}),
    IsControlByDialogue = false })
function PAWN.Mesh:GetAnimInstance() return ANIM end
function PAWN.PBZTargeting:HasLockTarget() return LOCKED end
function PAWN.CharacterMovement:IsFalling() return FALLING end
function PAWN:IsA(class) return IS_PLAYER and class == PLAYER_CLASS end
function PAWN:IsArmed()
    if not ARMED_READABLE then error("no such function") end
    return ARMED
end
function PAWN:Unarm()
    UNARM_CALLS = UNARM_CALLS + 1
    if UNARM_WORKS then ARMED = false end
    return true
end
CONTROLLER = Object({ Pawn = PAWN, fullName = "BP_PlayerController_C /Game/Maps/Level.Level:PersistentLevel.PC_0" })

-- Searches by name.
FIND_FIRST = 0
FIND_RESULT = CONTROLLER
function FindFirstOf(name) FIND_FIRST = FIND_FIRST + 1 return FIND_RESULT end
STATIC_FIND = 0
function StaticFindObject(path)
    STATIC_FIND = STATIC_FIND + 1
    if path == "/Script/ProjectPBZ.PBZCharacter_Player" then return PLAYER_CLASS end
    return Object({ valid = false })
end

STATICS = {}
function STATICS:GetTimeSeconds(context) return GAMETIME end
package.preload["UEHelpers"] = function()
    return { GetGameplayStatics = function() return STATICS end }
end
-- The game restarts the controller (ClientRestart): the hook gets it.
function RESTART(controller)
    HOOKS["/Script/Engine.PlayerController:ClientRestart"]({ get = function() return controller end })
end

function DESCRIBE(t)
    local names = {}
    for name in pairs(t) do names[#names + 1] = tostring(name) end
    table.sort(names)
    local parts = {}
    for i, name in ipairs(names) do parts[i] = name .. "=" .. tostring(t[name]) end
    return table.concat(parts, ", ")
end
"""

PLAYER_CONFIGS = [
    ("no config.lua", None, "No config.lua"),
    ("an empty or older config.lua", "return {}\n", None),
    ("a broken config.lua", "return {\n    Enable =\n", "config.lua not read"),
    ("a config.lua without a table", "-- nothing here\n", "does not return a table"),
    ("a config.lua with wrong types", "wrong types", "must be a"),
    ("a config.lua with an unknown setting", "return { NoSuchSetting = 1 }\n", "unknown setting NoSuchSetting"),
]


def lua_path(path: Path) -> str:
    return "[[" + path.as_posix() + "]]"


class Run:
    """main.lua in a fresh Lua state, with config.lua read from config_folder; setup: Lua run right after main.lua
    loaded, before the first check (the game's state, the ClientRestart hook)."""

    def __init__(self, config_folder: Path, setup: str = ""):
        self.folder = config_folder
        self.lua = lua54.LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(MOCKS)
        self.lua.execute(f'package.path = {lua_path(config_folder)} .. "/?.lua"; package.cpath = ""')
        self.g = self.lua.globals()
        self.do(MAIN.read_text(encoding="utf-8"))
        if setup:
            self.do(setup)

    def do(self, code: str):
        """Runs Lua code; a Lua error that stops it becomes an "Error" line in the log, so the checks fail."""
        try:
            return self.lua.execute(code)
        except lua54.LuaError as error:
            self.g.LOG[len(self.g.LOG) + 1] = "Error: main.lua stopped: " + str(error).splitlines()[0]

    def eval(self, expression: str):
        return self.lua.eval(expression)

    def log(self):
        return [self.g.LOG[i].rstrip() for i in range(1, len(self.g.LOG) + 1)]

    def write_config(self, text: str):
        (self.folder / "config.lua").write_text(text, encoding="utf-8", newline="\n")


def settings_lines(log):
    return [line.split("] Settings: ", 1)[1] for line in log if "] Settings: " in line]


def main() -> None:
    version = json.loads((ROOT / "mod.json").read_text(encoding="utf-8"))["version"]
    failures = []

    def check(condition, text):
        print(("ok    " if condition else "FAIL  ") + text)
        if not condition:
            failures.append(text)

    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        shipped_text = CONFIG.read_text(encoding="utf-8")

        def folder(name, text=shipped_text):
            f = temp / name
            f.mkdir()
            if text is not None:
                (f / "config.lua").write_text(text, encoding="utf-8", newline="\n")
            return f

        # --- The mod as players get it.
        r = Run(folder("shipped"))
        log = r.log()
        for line in log:
            print("      log: " + line)
        e = r.eval
        check(list(r.g.DELAYS.values()) == [250, 5000] and r.g.ASYNC_LOOPS == 0 and len(r.g.MAP_HOOKS) == 1
              and e("HOOKS['/Script/Engine.PlayerController:ClientRestart'] ~= nil"),
              "game-thread loops: the check every 0.25 s, the config read every 5 s; the ClientRestart and map hooks")
        check(any(f"{version} loaded." in line for line in log), f"load line with the version {version} of mod.json")
        shipped = e(f"DESCRIBE(dofile({lua_path(CONFIG)}))")
        check(settings_lines(log) == [shipped] and not any("config.lua" in line for line in log),
              "one settings line with the shipped values, no warning")

        # --- The sheathe.
        r.do("CHECK(1)")
        check(e("FIND_FIRST") == 1, "no controller from the game yet: one search at the first check")
        r.do("WAIT(3.5)")
        check(e("UNARM_CALLS") == 0, "drawn and idle for less than 4 s: no sheathe")
        r.do("WAIT(0.75)")
        check(e("UNARM_CALLS") == 1 and not e("ARMED"), "after 4 s of quiet: Unarm(), the weapon is away")
        r.do("ARMED = true WAIT(30)")
        check(e("FIND_FIRST") == 1 and e("STATIC_FIND") == 1,
              "no search by name on the timer: the controller is kept, the player class found once (130 checks)")

        # --- Reasons to wait.
        reasons = [
            ("in combat", "ANIM.GameplayTag_IsInCombat = true"),
            ("attacking", "ANIM.GameplayTag_IsMelee = true"),
            ("dodging", "ANIM.GameplayTag_IsDashing = true"),
            ("blocking", "ANIM.GameplayTag_IsStance = true"),
            ("aiming", "ANIM.GameplayTag_IsADS = true"),
            ("in dialogue", "ANIM.GameplayTag_IsDialogue = true"),
            ("a combat montage", "ANIM.CombatMontageActive = true"),
            ("any montage", "MONTAGE = true"),
            ("controlled by dialogue", "PAWN.IsControlByDialogue = true"),
            ("in the air", "FALLING = true"),
            ("locked on", "LOCKED = true"),
        ]
        for name, setup in reasons:
            w = Run(folder("wait" + name.replace(" ", "_")), "RESTART(CONTROLLER) " + setup)
            w.do("WAIT(10)")
            check(w.eval("UNARM_CALLS") == 0, f"{name}: no sheathe")
        c = Run(folder("combat"), "RESTART(CONTROLLER) ANIM.GameplayTag_IsInCombat = true")
        c.do("WAIT(10) ANIM.GameplayTag_IsInCombat = false WAIT(3.75)")
        check(c.eval("UNARM_CALLS") == 0, "after a fight: the 4 s start when it ends")
        c.do("WAIT(0.5)")
        check(c.eval("UNARM_CALLS") == 1, "... and the weapon goes away 4 s after the fight")
        m = Run(folder("montageoff", shipped_text.replace("WaitForMontages = true,", "WaitForMontages = false,")
                       .replace("WaitForLockOn = true,", "WaitForLockOn = false,")), "RESTART(CONTROLLER) MONTAGE = true LOCKED = true")
        m.do("WAIT(4.5)")
        check(m.eval("UNARM_CALLS") == 1, "WaitForMontages and WaitForLockOn false: a montage and a lock-on do not wait")
        n = Run(folder("notplayer"), "RESTART(CONTROLLER) IS_PLAYER = false")
        n.do("WAIT(10)")
        check(n.eval("UNARM_CALLS") == 0, "a pawn that is not the player class (cutscene, vehicle): nothing")
        a = Run(folder("away"), "RESTART(CONTROLLER) ARMED = false")
        a.do("WAIT(10)")
        check(a.eval("UNARM_CALLS") == 0, "the weapon already away: nothing")

        # --- Retries.
        t = Run(folder("retry"), "RESTART(CONTROLLER) UNARM_WORKS = false")
        t.do("WAIT(4.25)")
        check(t.eval("UNARM_CALLS") == 1, "the weapon still drawn after a sheathe: first try")
        t.do("WAIT(3)")
        check(t.eval("UNARM_CALLS") == 2, "... a second try 3 s later")
        t.do("WAIT(30)")
        check(t.eval("UNARM_CALLS") == 3, "... at most 3 tries, then it waits")
        t.do("ANIM.GameplayTag_IsInCombat = true CHECK(1) ANIM.GameplayTag_IsInCombat = false WAIT(4.25)")
        check(t.eval("UNARM_CALLS") == 4, "a new fight starts the tries over")

        # --- The controller.
        k = Run(folder("lost"), "RESTART(CONTROLLER)")
        k.do("CHECK(1) CONTROLLER.valid = false FIND_RESULT = nil CHECK(4)")
        check(k.eval("FIND_FIRST") == 1, "the controller gone and none found: one search ...")
        k.do("WAIT(4)")
        check(k.eval("FIND_FIRST") == 1, "... not again within 5 s (real time)")
        k.do("WAIT(1.25)")
        check(k.eval("FIND_FIRST") == 2, "... then again")
        s = Run(folder("reused"), "RESTART(CONTROLLER)")
        s.do("CONTROLLER.fullName = 'Actor /Game/Maps/Level.Level:PersistentLevel.Other' FIND_RESULT = nil WAIT(5)")
        check(s.eval("UNARM_CALLS") == 0 and s.eval("FIND_FIRST") == 1,
              "the kept controller's address now holds another object: not used, searched instead")
        p = Run(folder("mapload"), "RESTART(CONTROLLER)")
        p.do("MAP_HOOKS[1]() CHECK(1)")
        check(p.eval("FIND_FIRST") == 1, "after a map load: the controller is searched again")
        p.do("RESTART(CONTROLLER) WAIT(10)")
        check(p.eval("FIND_FIRST") == 1 and p.eval("UNARM_CALLS") == 1, "... or comes with ClientRestart, no search")
        u = Run(folder("unreadable"), "RESTART(CONTROLLER) ARMED_READABLE = false")
        u.do("WAIT(10)")
        check(u.eval("UNARM_CALLS") == 0 and sum("IsArmed() cannot be read" in line for line in u.log()) == 1,
              "IsArmed() unreadable (a game update): nothing, logged once")

        # --- Live settings.
        l = Run(folder("live"), "RESTART(CONTROLLER)")
        l.write_config(shipped_text.replace("SheatheDelay = 4,", "SheatheDelay = 1,"))
        l.do("CONFIG() WAIT(1.25)")
        check(l.eval("UNARM_CALLS") == 1, "SheatheDelay = 1 (live): the weapon goes away after 1 s")
        l.write_config(shipped_text.replace("Enable = true,", "Enable = false,"))
        l.do("CONFIG() ARMED = true WAIT(10)")
        check(l.eval("UNARM_CALLS") == 1, "Enable = false (live): nothing")
        l.write_config("return {\n    Enable =\n")
        l.do("CONFIG()")
        check(any("config.lua not read (line" in line and "the last settings stay" in line for line in l.log()),
              "a broken (half-saved) file keeps the last settings")
        l.write_config("return { SheatheDelay = 500, MaxTries = 2.7 }\n")
        l.do("CONFIG()")
        check(any("SheatheDelay = 500 is outside 0 to 60; 60 is used" in line for line in l.log())
              and any("MaxTries=2," in line for line in settings_lines(l.log())),
              "a delay out of range is clamped (60); MaxTries is a whole number")

        # --- LogDetail.
        d = Run(folder("detail", shipped_text.replace("LogDetail = false,", "LogDetail = true, ")), "RESTART(CONTROLLER)")
        d.do("ANIM.GameplayTag_IsInCombat = true CHECK(1) ANIM.GameplayTag_IsInCombat = false WAIT(4.5)")
        log = d.log()
        for line in log[-5:]:
            print("      log: " + line)
        check(any("weapon drawn" in line for line in log) and any("waiting: in combat" in line for line in log)
              and any("quiet - sheathing in 4.0 s" in line for line in log)
              and any("sheathe (try 1 after 4.0 s quiet): Unarm() returned true" in line for line in log)
              and any("weapon away" in line for line in log) and not any("Error" in line for line in log),
              "LogDetail: drawn, waiting, quiet, the sheathe, away")
        quiet = Run(folder("quiet"), "RESTART(CONTROLLER)")
        quiet.do("WAIT(10)")
        check(not any("sheathe" in line or "weapon" in line for line in quiet.log()),
              "LogDetail off: a sheathe writes no line")

        # --- The settings files a player may have.
        folders = {}
        for case, content, _ in PLAYER_CONFIGS:
            if content == "wrong types":
                content = r.eval(f"""(function()
                    local lines = {{}}
                    for name, value in pairs(dofile({lua_path(CONFIG)})) do
                        lines[#lines + 1] = string.format("    [%q] = %s,", name, type(value) == "string" and "0" or '"wrong"')
                    end
                    return "return {{\\n" .. table.concat(lines, "\\n") .. "\\n}}\\n"
                end)()""")
            folders[case] = folder(f"player{len(folders)}", content)
        defaults = settings_lines(Run(folders["an empty or older config.lua"]).log())
        check(defaults == [shipped], f"config.lua ships exactly the defaults of main.lua ({defaults})")
        count = len(list(r.eval(f"dofile({lua_path(CONFIG)})").keys()))
        for case, _, expected in PLAYER_CONFIGS:
            run = Run(folders[case], "RESTART(CONTROLLER)")
            run.do("WAIT(4.5) CONFIG()")
            log = run.log()
            fine = (settings_lines(log) == defaults and len(run.g.LOOPS) == 2 and run.eval("UNARM_CALLS") == 1
                    and not any("Error" in line for line in log))
            if expected is None:
                fine = fine and not any("config.lua" in line for line in log)
            else:
                fine = fine and sum(expected in line for line in log) == (count if case.endswith("wrong types") else 1)
            check(fine, f"{case}: starts with the defaults and sheathes"
                  + (f", logs '{expected}' once per setting" if case.endswith("wrong types")
                     else (f", logs '{expected}' once" if expected else ", no warning")))
            if not fine:
                for line in log:
                    print("      log: " + line)
        off = Run(folder("off", "return { Enable = false }\n"), "RESTART(CONTROLLER)")
        off.do("WAIT(10)")
        check(len(off.g.LOOPS) == 2 and off.eval("UNARM_CALLS") == 0
              and any("does nothing until it is true" in line for line in off.log()),
              "Enable = false at start: the loops run (live settings), no sheathe")

    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
