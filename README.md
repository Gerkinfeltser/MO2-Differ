# MO2-Differ

A Mod Organizer 2 plugin that lets you diff conflicting files between mods using VS Code.

Adds a **Tools > Conflict Diff** menu entry that opens a three-pane conflict browser (winning, losing, non-conflicted) similar to MO2's built-in Conflicts tab. Right-click any text-based conflicting file and choose **Diff in VS Code** to compare both versions side by side.

## Install

1. Copy `conflict_diff.py` into your MO2 `plugins/` directory (or symlink it).
2. Restart MO2.
3. **Tools > Conflict Diff**.

## Requirements

- Mod Organizer 2 (2.4.x+ with PyQt5, or 2.5.x with PyQt6)
- VS Code with `code` on PATH (the plugin also checks standard install locations)
