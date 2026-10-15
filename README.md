# Steam Workshop Downloader

Download Steam Workshop items for any game that supports Workshop downloads through SteamCMD. Choose the game's Steam App ID, or let the downloader detect it from the items. Accept individual Workshop IDs/links, lists, collections, or combinations of them.

The scripts download and validate files. Installing/enabling mods and arranging the game's load order are separate steps. Steam's ownership and access rules still apply; anonymous access varies by game.

## Requirements and setup (Windows)

1. Install [Python](https://www.python.org/downloads/windows/) **3.10 or newer**, with Python on PATH. Verify in a new PowerShell window:

   ```powershell
   python --version
   ```

2. Download [SteamCMD for Windows](https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip), extract it into this project folder, and run `steamcmd.exe` once to let it update. Type `quit` when finished. You can instead keep SteamCMD elsewhere and pass `-SteamCmdPath`.

3. Open PowerShell in the project folder. No `pip install` is needed; the Python code uses only the standard library. All examples below assume this working directory.

4. If Windows blocks the PowerShell script, use the batch launcher or invoke it with a process-local policy override:

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\download-mods.ps1 -AppId 1158310 -Source 2871648329 -PrepareOnly
   ```

SteamCMD binaries, downloaded game/mod files, account data, logs, and reports are local only and excluded from Git. A fresh clone contains the downloader, tests, documentation, and examples; install SteamCMD separately.

## Quick start: Crusader Kings III collection

The included example points to [The Immersion Collection](https://steamcommunity.com/sharedfiles/filedetails/?id=3354778107), for **CK3 App ID `1158310`**.

First preview the current item list without starting SteamCMD:

```powershell
.\download-mods.ps1 -AppId 1158310 -ListFile .\examples\ck3-immersion.txt -PrepareOnly
```

Then download using your Steam account name:

```powershell
.\download-mods.ps1 -AppId 1158310 -ListFile .\examples\ck3-immersion.txt -SteamUser YOUR_STEAM_ACCOUNT
```

Enter your password and Steam Guard code directly in SteamCMD's local prompts. Do not put them in command arguments, scripts, lists, or Git. An account that owns the selected game may be required. SteamCMD manages its own local account cache.

Or **double-click `download-mods.cmd`**. Enter the game App ID (blank means detect), an item/collection link or list-file path, and your Steam account name (blank means anonymous). For multiple links at this prompt, separate them with spaces, commas, or semicolons. Paste a list path without surrounding quote characters.

On October 15, 2026, the direct CK3 collection resolved to 37 accessible mods. Its linked collection is a separate Fallen Eagle edition and is excluded by default. Anonymous downloads failed locally with SteamCMD's `Missing decryption key`; this is an authentication/access limitation, not a completed download. Counts and contents can change; every invocation resolves Steam's live metadata.

The collection author asks users to follow the listed mod order and notes DLC requirements. Review the collection's current instructions before enabling its mods.

## Choose another game

Use the App ID from the Steam store URL: in `https://store.steampowered.com/app/1158310/...`, the game App ID is `1158310`. A Workshop URL's `id=...` value identifies a mod or collection, not the game.

You can supply **any positive numeric App ID**, but the game must expose downloadable Workshop content to SteamCMD. No fixed supported-game list is hardcoded. Each accessible item's game ID is checked before downloads begin; mixed-game batches are rejected. Run a separate command for each game.

For example, the existing local Cities: Skylines manifest still works:

```powershell
.\download-mods.ps1 -ListFile .\modlist.json -PrepareOnly
.\download-mods.ps1 -AppId 255710 -ListFile .\modlist.json -SteamUser YOUR_STEAM_ACCOUNT
```

`modlist.json` is an existing local file and is not shipped in Git. Omitting `-AppId` uses the JSON manifest's `appId`, or detects the game from the first accessible Workshop item. All remaining items must match.

## Individual items, lists, and collections

Download one item by ID or full URL:

```powershell
.\download-mods.ps1 -AppId 1158310 -Source 2871648329 -SteamUser YOUR_STEAM_ACCOUNT
.\download-mods.ps1 -Source 'https://steamcommunity.com/sharedfiles/filedetails/?id=2871648329' -PrepareOnly
```

Pass multiple IDs/links as a PowerShell array, or as one delimited string:

```powershell
.\download-mods.ps1 -AppId 1158310 -Source @('2871648329', '3030427202') -PrepareOnly
.\download-mods.ps1 -AppId 1158310 -Source '2871648329,3030427202' -PrepareOnly
```

Pass a collection link exactly like an individual link:

```powershell
.\download-mods.ps1 -AppId 1158310 -Source 'https://steamcommunity.com/sharedfiles/filedetails/?id=3354778107' -PrepareOnly
```

Collections expand in Steam's `sortorder`. Duplicates are removed while preserving first occurrence. By default only a collection's direct mod entries are included. To also expand linked/nested collections, add `-RecursiveCollections`; these links can point to alternative or incompatible mod sets. Expansion handles cycles and rejects excessive nesting. Explicitly providing several collection links expands each one even without that flag. Required-item/dependency links on individual mods are not fetched automatically.

### Text lists

Create a local file such as `my-mods.txt`. Use one or several IDs/links per line. Blank lines and full-line `#` comments are ignored; inline comments are not supported.

```text
# Items and collections can be mixed
2871648329
3030427202
https://steamcommunity.com/sharedfiles/filedetails/?id=3354778107
```

```powershell
.\download-mods.ps1 -AppId 1158310 -ListFile .\my-mods.txt -PrepareOnly
```

### JSON lists

The old manifest format is supported. See [`examples/items.json`](examples/items.json):

```json
{
  "appId": "1158310",
  "mods": [
    {"id": "2871648329"},
    {"url": "https://steamcommunity.com/sharedfiles/filedetails/?id=3354778107"}
  ]
}
```

`items` can be used instead of `mods`. Entries can also be plain ID/URL strings, and a top-level array of entries works too. An optional `name` field is accepted; names are refreshed from Steam. Text and JSON files accept UTF-8, including a BOM.

Combine files and direct inputs:

```powershell
.\download-mods.ps1 -AppId 1158310 -ListFile @('.\my-mods.txt', '.\examples\items.json') -Source 3030427202 -PrepareOnly
```

Unavailable/deleted/private items cause a clear error before SteamCMD starts. To continue with the accessible entries, add **`-SkipUnavailable`**. Skipped entries remain in the manifest and download report as `Unavailable`; a download run with skipped entries returns exit code 1. Missing API response records still stop resolution. Private collection contents that Steam does not disclose cannot be expanded by this public metadata API.

## Output, verification, and updates

Mod files are stored relative to the selected SteamCMD executable:

```text
<SteamCMD folder>/steamapps/workshop/content/<App ID>/<Workshop ID>/
```

Each invocation creates a unique output folder:

```text
runs/<App ID>/<UTC timestamp>-<unique suffix>/
    manifest.json            resolved IDs, titles, order, source IDs, skipped entries
    workshop-downloads.txt   SteamCMD commands (no login/password)
    steamcmd.log             current run's console output (download runs only)
    download-report.csv      per-item status, Steam result, file count, bytes, path
    summary.json             verified/total counts and SteamCMD exit status
```

`-PrepareOnly` still needs internet for metadata, but needs no SteamCMD installation and downloads no payloads. It writes only the manifest and command file.

A download is **Verified downloaded** only when SteamCMD reports success for that item in the current run **and** its content directory contains nonempty files. Existing files without fresh success are reported as **Files present; download not verified**. SteamCMD can exit 0 even when individual items failed, so use the report and the downloader's exit code.

To update/retry, run the same command again. SteamCMD's `validate` requests validation; existing content stays in its normal location. A collection link refreshes its membership each time. To retry the exact accessible IDs from a prior run instead, use that run's `manifest.json` with `-ListFile` (unavailable entries were never downloadable and are not in its `mods` array). Removed collection members are not deleted from disk. Each run keeps a separate report.

Exit codes: **0** = preparation succeeded, or all selected downloads verified and SteamCMD exited 0; **1** = incomplete, interrupted, timed out, or skipped downloads / nonzero SteamCMD exit; **2** = invalid input, metadata, filesystem, or launch error. PowerShell and batch launchers forward the exit code; the batch launcher pauses before closing.

Only one downloader should use a SteamCMD directory at a time. A local `.workshop-downloader.lock` prevents overlapping runs from this tool. After a crash, remove that file only after confirming no download process is running. A separately launched SteamCMD is outside this lock's control.

## Options

| PowerShell option | Python option | Meaning |
|---|---|---|
| `-AppId ID` | `--app-id ID` | Select game; otherwise detect |
| `-Source @(...)` | positional IDs/URLs | One or more items or collections |
| `-ListFile @(...)` | `--list FILE` (repeatable) | TXT/JSON lists |
| `-SteamUser NAME` | `--steam-user NAME` | Account name; default `anonymous` |
| `-SteamCmdPath PATH` | `--steamcmd PATH` | Executable; default project's `steamcmd.exe` |
| `-OutputDirectory PATH` | `--output PATH` | Reports/manifests; default project's `runs` |
| `-PrepareOnly` | `--prepare-only` | Resolve and preview |
| `-SkipUnavailable` | `--skip-unavailable` | Record unavailable entries and continue |
| `-RecursiveCollections` | `--recursive-collections` | Include linked/nested collections |
| `-TimeoutSeconds N` | `--timeout-seconds N` | Whole SteamCMD session limit; default 0 = unlimited |

PowerShell aliases: `-Items` and `-Collection` mean `-Source`; `-Manifest` means `-ListFile`. `-SteamCmdPath` controls the mod download location as well as the executable. `-OutputDirectory` changes only generated manifests/reports.

Python examples (also avoid PowerShell array/quoting differences):

```powershell
python .\workshop.py --app-id 1158310 --prepare-only 2871648329 3030427202
python .\workshop.py --app-id 1158310 --steam-user YOUR_STEAM_ACCOUNT --list .\examples\ck3-immersion.txt
python .\workshop.py --help
```

The Python core can use a compatible SteamCMD executable on other operating systems through `--steamcmd`; the included launchers target Windows. Linux/macOS execution has not been verified here.

## Troubleshooting

- **`Missing decryption key`, `Access Denied`, `No subscription`, or item `Failure`:** retry using an account that owns the game, complete Steam Guard locally, and inspect SteamCMD's `logs/workshop_log.txt`. Successful metadata resolution does not establish payload access. Some games/items may remain unavailable through SteamCMD even with login.
- **Password/Steam Guard prompt:** run the command in your own interactive terminal. The downloader deliberately has no password argument. If needed, sign in once by running `steamcmd.exe +login YOUR_STEAM_ACCOUNT +quit`, then retry. Do not share or commit Steam's account cache.
- **Wrong App ID:** use the store's game App ID and split mixed-game lists. Explicit App IDs and JSON `appId` values must agree.
- **Item unavailable:** open its Workshop page with an authorized Steam account. Use `-SkipUnavailable` to download the remaining visible entries; this does not grant access to private/deleted content.
- **No progress:** use `-TimeoutSeconds 300` for unattended attempts. An interrupted/timed-out session records the results observed so far and returns 1. SteamCMD authentication can require user input.
- **Downloaded but missing in the game:** SteamCMD stores Workshop files, but does not subscribe your desktop Steam client or register mods with a game's launcher. Follow the game's manual mod installation instructions; CK3 also needs launcher registration and the intended playset/load order.

## Development and Git exclusions

Run the offline tests:

```powershell
python -m unittest discover -s tests -v
```

Tests cover input validation, legacy lists, collection order/nesting/cycles, wrong-game rejection, unavailable items, command generation, and verification that stale files cannot count as fresh successful downloads. Live Steam metadata and download checks are separate from the offline suite.

`.gitignore` is an **allowlist**: only the named source/docs files, `tests/test_*.py`, and curated `examples/*.txt` / `examples/*.json` can be added normally. All other current and future game folders/files are ignored, including `steamapps`, `config`, `userdata`, `runs`, SteamCMD binaries, caches, local mod lists, backups, and credentials. Add future project source deliberately to the allowlist. Files already tracked by Git are not affected by ignore rules; avoid `git add -f` for local runtime data.

Before committing, inspect `git status --short` and `git diff --cached --stat`. The downloader never performs Git operations itself.

References: [SteamCMD documentation](https://developer.valvesoftware.com/wiki/SteamCMD), [Valve's ISteamRemoteStorage API](https://partner.steamgames.com/doc/webapi/ISteamRemoteStorage).
