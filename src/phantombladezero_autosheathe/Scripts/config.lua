-- Settings of Auto Sheathe. Change a value and save the file: the mod reads it again every 5 seconds, so the change
-- shows in the game without a restart. A file it cannot read (for example while it is saved) keeps the last settings.
-- A setting that this file does not have keeps its default, so an older copy of the file still works after an update.
return {
    Enable = true,          -- false: the game as normal, the weapon stays drawn until you put it away
    SheatheDelay = 4,       -- seconds drawn, out of combat and doing nothing, before it is put away (0 to 60)
    WaitForLockOn = true,   -- true: never while you are locked on to an enemy
    WaitForMontages = true, -- true: never while any animation plays (attacks, dodges and blocking always wait)
    RetrySeconds = 3,       -- if the weapon is still drawn after a sheathe, try again after this long (0.5 to 60)
    MaxTries = 3,           -- at most this many tries, then wait for the next fight or draw (1 to 10)
    LogDetail = false,      -- true: ue4ss\UE4SS.log names each change (drawn, waiting, quiet, sheathe), for tests
}
