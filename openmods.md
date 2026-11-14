# Auto Sheathe

Puts your weapon away a few seconds after a fight, with the game's own sheathe animation. Settings in config.lua, live in game.

## What it does

Your weapon goes away by itself a few seconds after a fight, with the game's own sheathe animation.

- Once the weapon is drawn and you are out of combat and doing nothing for 4 seconds (a setting), the mod puts it
  away the way the game does: the same ability, the same animation, the same rules about when it is allowed.
- It never cuts anything off: it waits while you are in combat, attacking, dodging, blocking, aiming, in dialogue, in
  the air, locked on to an enemy, or while any animation plays.
- If the weapon is still drawn after a sheathe, it tries again after 3 seconds, at most 3 times, then waits for the
  next fight or draw.

It is a UE4SS Lua script: it calls the game's own sheathe while the game runs. It replaces no game file and does not
touch your save.

## Screenshots

![Auto Sheathe](docs/cover.png)

## How to install

1. Install UE4SS for Phantom Blade Zero, for example [UE4SS](https://github.com/KintaroModding/ue4ss) (its zip
   `phantombladezero_ue4ss_<version>.zip`: the official UE4SS build with a config that makes it run in this game).
2. Download the zip of the latest release on GitHub (`phantombladezero_autosheathe_<version>.zip`).
3. Unpack it into the game folder `platform\steam\`, next to the game's exe. It adds the folder
   `ue4ss\Mods\phantombladezero_autosheathe\` (with the file `enabled.txt`, UE4SS starts it by itself).
4. Start the game.

To check that it runs: `platform\steam\ue4ss\UE4SS.log` has the line `[Auto Sheathe] <version> loaded.`

To update the mod, replace the folder with the one of the new release; to keep your settings, put your old
`Scripts\config.lua` back (a setting that it does not have keeps its default). To remove it, delete the folder
`ue4ss\Mods\phantombladezero_autosheathe\`.

## How to use

Nothing to do: the mod works as soon as you load a game. Draw your weapon, fight, and walk on.

## Settings

The settings are in `platform\steam\ue4ss\Mods\phantombladezero_autosheathe\Scripts\config.lua`. Open it with a
text editor, change a value and save: the mod reads the file every 5 seconds, so you see the change in the game
without a restart. A file it cannot read (for example a typo) keeps the last settings. `UE4SS.log` shows the settings
in use in the line `[Auto Sheathe] Settings: ...`, and names each value it could not use.

| Setting | Default | What it does |
|---|---|---|
| `Enable` | `true` | `false`: the game as normal, the weapon stays drawn until you put it away |
| `SheatheDelay` | `4` | Seconds with the weapon drawn, out of combat and doing nothing, before it is put away (0 to 60) |
| `WaitForLockOn` | `true` | `true`: never while you are locked on to an enemy |
| `WaitForMontages` | `true` | `true`: never while any animation plays (attacks, dodges and blocking always wait) |
| `RetrySeconds` | `3` | If the weapon is still drawn after a sheathe, try again after this many seconds (0.5 to 60) |
| `MaxTries` | `3` | At most this many tries, then wait for the next fight or draw (1 to 10) |
| `LogDetail` | `false` | `true`: `UE4SS.log` names each change (drawn, waiting, quiet, sheathe), for tests |

## Compatibility

- Game version: Steam build 26367565 (`CL-302256_JKS-17280`).
- UE4SS `v4.0.0`. First tested in game with UE4SS `v3.0.1-1195-g1ceefac8`.
- Use only one auto sheathe: a mod with its own auto sheathe would put the weapon away twice.

## Known issues

None yet.

## How to build

There is nothing to build: `src\phantombladezero_autosheathe\Scripts\main.lua` is the mod. `tests\test_main.py` runs the script
outside the game with Lua 5.4 ([lupa](https://pypi.org/project/lupa/)) and mocks of UE4SS:
`python tests\test_main.py`. `README.md` has the details.

## Credits

Made by Kintaro. MIT license: you may use, change and share this mod. UE4SS is made by the
[UE4SS-RE team](https://github.com/UE4SS-RE/RE-UE4SS). Phantom Blade Zero belongs to its makers.
