# Auto Sheathe

Puts your weapon away a few seconds after a fight, with the game's own sheathe ability and animation. Settings in config.lua, live in game.

A [UE4SS](https://github.com/UE4SS-RE/RE-UE4SS) Lua mod for Phantom Blade Zero (Unreal Engine 5.7), made with
game version `CL-301524_JKS-17219` and UE4SS `v3.0.1-1195-g1ceefac8`, checked for game version `CL-302256_JKS-17280`
(Steam build 26367565) and UE4SS `v4.0.0`. This README is for developers; what the mod does and
how to install it are in [openmods.md](openmods.md), the mod page on [openmods](https://openmods.nexus).

## How it works

Every 0.25 s, on the game thread, `Scripts/main.lua` looks at the player. Once the weapon is drawn (`IsArmed()` of
`PBZCharacter_Player`) and nothing stops a sheathe for `SheatheDelay` seconds of game time, it calls the player's
`Unarm()`. `BP_RenewalPlayer_C` overrides it to activate the game's sheathe ability (`TryActivateAbilitiesByTag`), so
the animation and the game's rules apply. If the weapon is still drawn, it tries again after `RetrySeconds`, at most
`MaxTries` times; a new fight or the player's own action starts the tries over.

What stops it: the flags of the player's anim Blueprint `PBZ_ABP_Hun_Base_C` (`GameplayTag_IsInCombat`, the busy flags
in `BUSY`, `CombatMontageActive`), any montage (`WaitForMontages`), the pawn's `IsControlByDialogue`, falling
(`CharacterMovement`), and a lock target of `PBZTargeting` (`WaitForLockOn`).

No search by name on the timer: the player controller comes from a hook on `PlayerController:ClientRestart` and is
kept while it is valid and has the same full name; only while there is none, one `FindFirstOf("BP_PlayerController_C")`
at most every 5 s. The player class is found once.

Taken over from the user's UE4SS mod AutoSheathe 1 with the same rules; its ini became `config.lua` (read live), and its
two keys (HOME: sheathe now, END: reload) are gone.

## Deploy and test

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy.ps1     # copy the mod folder into the game's ue4ss\Mods
python tests\test_main.py                                 # offline test of main.lua (needs lupa)
```

`deploy.ps1` copies `src\phantombladezero_autosheathe\` to `<game folder>\platform\steam\ue4ss\Mods\phantombladezero_autosheathe\`. The game
folder is `$env:UE5_GAMES_DIR\PBZ`; `-GameDir` or `-ModsDir` override it. The mod folder holds
`enabled.txt`, so UE4SS starts it without an entry in `mods.txt`. An existing `Scripts\config.lua` in the game stays
(the tester's settings); `-ResetConfig` copies the shipped one. UE4SS loads Lua mods at game start. The mod writes
its lines into `ue4ss\UE4SS.log`, for example `[Auto Sheathe] 1.0 loaded.`

`tests\test_main.py` runs `main.lua` in Lua 5.4 ([lupa](https://pypi.org/project/lupa/)) with mocks of the UE4SS
functions that the script uses. It finds syntax and logic errors before a game start.

Versioning: every change raises the second number (1.0 -> 1.1) in `mod.json` and in `main.lua`:
`python scripts\bump_version.py`.

## Settings

`Scripts/config.lua` holds the player's settings, `DEFAULTS` in `main.lua` every setting with its default. Players and
mod managers keep their own `config.lua` across updates, so a new `main.lua` can meet an older file: a setting that
the file lacks, or has with another type, keeps its default, and the log says so (`ReadSettings`). Add each setting to
both files with the same value, and read it only from `Settings`, never as `config.X or default` (for a true/false
setting, `false or true` is true). `tests\test_main.py` checks that `config.lua` ships exactly the defaults, and runs
`main.lua` with a missing, empty, broken and wrong `config.lua`.

## Project layout

```
src/phantombladezero_autosheathe/   The UE4SS mod folder: Scripts/main.lua, Scripts/config.lua, enabled.txt
tests/test_main.py    Offline test of main.lua with mocks of UE4SS and the game
docs/                 Cover and screenshots
scripts/              bump_version.py
deploy.ps1            Copies the mod folder into the game's ue4ss\Mods
mod.json              Name, version, game, engine and UE4SS version
```

## License

MIT, see [LICENSE](LICENSE).
