# MO2-Differ

A Mod Organizer 2 plugin that lets you diff conflicting files between mods using VS Code.

Opens a three-pane conflict browser — winning conflicts, losing conflicts, and non-conflicted files — similar to MO2's built-in Conflicts tab. Right-click any text-based conflicting file and choose **Diff in VS Code** to compare both versions side by side.

## Install

1. Copy `conflict_diff.py` into your MO2 `plugins/` directory (or symlink it).
2. Restart MO2.

## Access

- **Tools > Conflict Diff** — opens the dialog, optionally pre-selecting the currently highlighted mod.
- **Right-click a mod > Conflict Diff** — opens the dialog pre-loaded with that mod.

## Requirements

- Mod Organizer 2 (2.4.x+ with PyQt5, or 2.5.x with PyQt6)
- [VS Code](https://code.visualstudio.com/) — the plugin looks for `Code.exe` at standard install locations, falling back to `code` / `code.cmd` on PATH.

## Usage

1. Select a mod from the dropdown at the top of the dialog. The dropdown is searchable — type to filter mod names by substring.
2. The three panes populate with the mod's file conflicts:
   - **Winning file conflicts** — files where the selected mod overwrites another mod.
   - **Losing file conflicts** — files where another mod overwrites the selected mod.
   - **Non-conflicted files** — files unique to the selected mod.
3. Right-click a conflicting file for options:
   - **Diff in VS Code** — opens both versions in VS Code's built-in diff viewer (text files only; binary formats like `.dds`, `.nif`, `.esp` are excluded).
   - **Open** — opens the file with its default application.
   - **Open in Explorer** — reveals the file in Windows Explorer.
   - **Open (from \<other mod\>)** — opens the other mod's version of the file.

### Filtering

Two filter fields sit below the mod selector:

- **Include** — comma-separated terms. Only files matching at least one term are shown (e.g. `.ini, textures`).
- **Exclude** — comma-separated terms. Files matching any term are hidden. Pre-populated with common noise: `.fuz, .dds, .nif, .hkx, .pex, .bsa, .ba2, .esp, .esm, .esl, meta.ini, readme, license, changelog, .git`. Edit freely.

Both fields work together: excludes are checked first, then includes. Pane titles show `(visible/total)` when a filter is active.

## Known Limitations

- **BSA/BA2 archives** — if the other version of a file lives inside a packed archive rather than as a loose file, the diff will show a "file not found" warning. Only loose file conflicts are supported.
- **Large mods** — scanning a mod with thousands of files may briefly freeze the UI while conflicts are enumerated.
- **Priority direction** — winner detection assumes MO2's convention that higher priority number = wins (bottom of load order overwrites). If conflicts appear in the wrong pane, this assumption may need to be inverted for your MO2 version.
- **Context menu injection** — the right-click menu entry on the mod list is injected via a Qt event filter, which is fragile across MO2 versions. The Tools menu entry always works as a fallback.

## Development

The plugin is a single Python file implementing MO2's `IPluginTool` interface. No build step required — edit `conflict_diff.py` and restart MO2 to pick up changes.

Debug logging can be enabled by checking for `conflict_diff_debug.log` next to the plugin file.

### Roadmap

- [x] Open dialog pre-filtered to the currently selected mod
- [x] Searchable mod dropdown (filter by mod name)
- [x] Include/exclude filter fields (comma-separated, VS Code style)
- [x] Right-click context menu integration on main mod list
