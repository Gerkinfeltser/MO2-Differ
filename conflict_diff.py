# Conflict Diff - MO2 Plugin
# Compare conflicting files between mods using VS Code's diff view.
#
# Installation:
#   1. Copy this file to <MO2>/plugins/conflict_diff.py
#   2. Restart MO2
#   3. Find "Conflict Diff" in the Tools menu
#
# Requirements:
#   - VS Code's `code` command must be on PATH
#     (VS Code installs this by default; if missing, re-run the VS Code installer
#      and check "Add to PATH", or set the full path in MO2's plugin settings)

import mobase
import os
import subprocess

try:
    from PyQt5.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QComboBox, QTreeWidget,
        QTreeWidgetItem, QSplitter, QLabel, QMenu, QGroupBox,
        QApplication, QLineEdit, QAction, QMessageBox, QCheckBox,
    )
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QIcon
except ImportError:
    from PyQt6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QComboBox, QTreeWidget,
        QTreeWidgetItem, QSplitter, QLabel, QMenu, QGroupBox,
        QApplication, QLineEdit, QMessageBox, QCheckBox,
    )
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QIcon, QAction

# Qt enum compatibility (PyQt5 uses flat enums, PyQt6 uses scoped)
_Vertical = getattr(Qt, "Vertical", None) or Qt.Orientation.Vertical
_UserRole = getattr(Qt, "UserRole", None) or Qt.ItemDataRole.UserRole
_WaitCursor = getattr(Qt, "WaitCursor", None) or Qt.CursorShape.WaitCursor
_CustomContextMenu = (
    getattr(Qt, "CustomContextMenu", None) or Qt.ContextMenuPolicy.CustomContextMenu
)

NOISE_FILES = frozenset({
    "meta.ini", "readme.md", "readme.txt", "readme",
    "license", "license.txt", "license.md",
    "changelog.md", "changelog.txt",
})

NOISE_PREFIXES = (
    ".git",
)

BINARY_EXTENSIONS = frozenset({
    ".dds", ".bsa", ".ba2", ".esp", ".esm", ".esl", ".fuz", ".wav", ".mp3",
    ".ogg", ".pex", ".dll", ".exe", ".hkx", ".nif", ".bto", ".btr", ".lip",
    ".xwm", ".png", ".jpg", ".jpeg", ".bmp", ".tga", ".psd", ".seq",
    ".strings", ".dlstrings", ".ilstrings", ".swf",
})


class ConflictDiffDialog(QDialog):

    def __init__(self, organizer, parent=None, selected_mod=None):
        super().__init__(parent)
        self._org = organizer
        self.setWindowTitle("Conflict Diff")
        self.setMinimumSize(780, 560)
        self.resize(920, 680)
        self._build_ui()
        self._populate_mod_list(selected_mod)

    # ── UI construction ──────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)

        # mod selector + filter
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Mod:"))
        self._mod_combo = QComboBox()
        self._mod_combo.setEditable(True)
        self._mod_combo.setInsertPolicy(QComboBox.NoInsert)
        self._mod_combo.setMinimumWidth(300)
        self._mod_combo.completer().setFilterMode(
            getattr(Qt, "MatchContains", None) or Qt.MatchFlag.MatchContains
        )
        self._mod_combo.completer().setCaseSensitivity(
            getattr(Qt, "CaseInsensitive", None) or Qt.CaseSensitivity.CaseInsensitive
        )
        self._mod_combo.activated.connect(
            lambda idx: self._on_mod_changed(self._mod_combo.itemText(idx))
        )
        bar.addWidget(self._mod_combo, 1)
        bar.addWidget(QLabel("Filter:"))
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("filter files… (prefix ! or ^ to exclude)")
        self._filter_edit.setClearButtonEnabled(True)
        self._filter_edit.textChanged.connect(self._apply_filter)
        bar.addWidget(self._filter_edit)
        self._hide_noise = QCheckBox("Hide noise")
        self._hide_noise.setToolTip(
            "Hide commonly-conflicting files: meta.ini, README, LICENSE, .git, etc."
        )
        self._hide_noise.setChecked(True)
        self._hide_noise.toggled.connect(lambda: self._apply_filter(self._filter_edit.text()))
        bar.addWidget(self._hide_noise)
        root.addLayout(bar)

        # three panes
        splitter = QSplitter(_Vertical)

        self._win = self._make_pane("Winning file conflicts", has_other=True)
        splitter.addWidget(self._win["box"])

        self._lose = self._make_pane("Losing file conflicts", has_other=True)
        splitter.addWidget(self._lose["box"])

        self._none = self._make_pane("Non-conflicted files", has_other=False)
        splitter.addWidget(self._none["box"])

        root.addWidget(splitter, 1)

    def _make_pane(self, title, has_other):
        box = QGroupBox(title)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(4, 8, 4, 4)

        cols = ["File", "Other Mod"] if has_other else ["File"]
        tree = QTreeWidget()
        tree.setColumnCount(len(cols))
        tree.setHeaderLabels(cols)
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        tree.setSortingEnabled(True)
        tree.setContextMenuPolicy(_CustomContextMenu)
        tree.customContextMenuRequested.connect(
            lambda pos, t=tree, o=has_other: self._context_menu(pos, t, o)
        )
        hdr = tree.header()
        hdr.setStretchLastSection(True)
        if has_other:
            hdr.resizeSection(0, 460)

        lay.addWidget(tree)
        return {"box": box, "tree": tree, "title": title}

    # ── data ─────────────────────────────────────────────────────────

    def _populate_mod_list(self, selected_mod=None):
        ml = self._org.modList()
        active = sorted(
            (m for m in ml.allMods() if ml.state(m) & mobase.ModState.ACTIVE),
            key=str.lower,
        )
        self._mod_combo.blockSignals(True)
        self._mod_combo.addItem("— select a mod —")
        self._mod_combo.addItems(active)
        if selected_mod:
            idx = self._mod_combo.findText(selected_mod)
            if idx >= 0:
                self._mod_combo.setCurrentIndex(idx)
        self._mod_combo.blockSignals(False)
        if selected_mod and self._mod_combo.currentText() == selected_mod:
            self._on_mod_changed(selected_mod)

    def _on_mod_changed(self, name):
        if not name or name.startswith("—"):
            return
        for p in (self._win, self._lose, self._none):
            p["tree"].clear()

        QApplication.setOverrideCursor(_WaitCursor)
        try:
            self._scan(name)
        finally:
            QApplication.restoreOverrideCursor()

        for p in (self._win, self._lose, self._none):
            n = p["tree"].topLevelItemCount()
            p["box"].setTitle(f"{p['title']} ({n})")

    def _scan(self, mod_name):
        mods_path = self._org.modsPath()
        mod_dir = os.path.join(mods_path, mod_name)
        if not os.path.isdir(mod_dir):
            return

        ml = self._org.modList()

        for dirpath, dirs, files in os.walk(mod_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for fname in files:
                abs_path = os.path.join(dirpath, fname)
                rel = os.path.relpath(abs_path, mod_dir).replace("\\", "/")

                if rel.lower() == "meta.ini":
                    continue

                origins = self._org.getFileOrigins(rel)

                if len(origins) <= 1:
                    item = QTreeWidgetItem([rel])
                    item.setData(0, _UserRole, self._row_data(
                        rel, mod_name, abs_path, None, None,
                    ))
                    self._none["tree"].addTopLevelItem(item)
                    continue

                # highest priority number wins in MO2 (bottom of load order)
                winner = max(origins, key=lambda m: ml.priority(m))

                if winner == mod_name:
                    others = [m for m in origins if m != mod_name]
                    for other in others:
                        other_abs = os.path.join(mods_path, other, rel)
                        item = QTreeWidgetItem([rel, other])
                        item.setData(0, _UserRole, self._row_data(
                            rel, mod_name, abs_path, other, other_abs,
                        ))
                        self._win["tree"].addTopLevelItem(item)
                else:
                    other_abs = os.path.join(mods_path, winner, rel)
                    item = QTreeWidgetItem([rel, winner])
                    item.setData(0, _UserRole, self._row_data(
                        rel, mod_name, abs_path, winner, other_abs,
                    ))
                    self._lose["tree"].addTopLevelItem(item)

    @staticmethod
    def _row_data(rel, mod, abs_path, other_mod, other_abs):
        return {
            "rel": rel,
            "mod": mod,
            "abs": abs_path,
            "other_mod": other_mod,
            "other_abs": other_abs,
        }

    # ── context menu ─────────────────────────────────────────────────

    def _context_menu(self, pos, tree, has_other):
        item = tree.itemAt(pos)
        if not item:
            return
        d = item.data(0, _UserRole)
        if not d:
            return

        menu = QMenu(tree)

        if has_other and d.get("other_mod"):
            ext = os.path.splitext(d["rel"])[1].lower()
            if ext not in BINARY_EXTENSIONS:
                act = menu.addAction("Diff in VS Code")
                act.triggered.connect(lambda: self._diff(d["abs"], d["other_abs"]))
                menu.addSeparator()

        a_open = menu.addAction("Open")
        a_open.triggered.connect(lambda: os.startfile(d["abs"]))

        a_expl = menu.addAction("Open in Explorer")
        a_expl.triggered.connect(
            lambda: subprocess.Popen(["explorer", "/select,", os.path.normpath(d["abs"])])
        )

        if has_other and d.get("other_abs") and os.path.isfile(d["other_abs"]):
            a_open2 = menu.addAction(f"Open (from {d['other_mod']})")
            a_open2.triggered.connect(lambda: os.startfile(d["other_abs"]))

        global_pos = tree.viewport().mapToGlobal(pos)
        if hasattr(menu, "exec"):
            menu.exec(global_pos)
        else:
            menu.exec_(global_pos)

    def _diff(self, path1, path2):
        if not path2:
            return
        missing = [p for p in (path1, path2) if not os.path.isfile(p)]
        if missing:
            QMessageBox.warning(
                self,
                "File not found",
                "Cannot diff — file not found on disk (may be inside a BSA/BA2 "
                "archive):\n\n" + "\n".join(missing),
            )
            return
        code_cmd = self._find_vscode()
        if not code_cmd:
            QMessageBox.warning(
                self,
                "VS Code not found",
                "Could not find VS Code.\n\n"
                "Make sure VS Code is installed, or set the path in the plugin source.",
            )
            return
        try:
            subprocess.Popen([code_cmd, "--diff", path1, path2])
        except OSError as e:
            QMessageBox.warning(self, "Launch failed", str(e))

    @staticmethod
    def _find_vscode():
        # prefer Code.exe directly to avoid cmd.exe flash from code.cmd
        exe_candidates = [
            os.path.join(os.environ.get("PROGRAMFILES", ""), "Microsoft VS Code", "Code.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Microsoft VS Code", "Code.exe"),
        ]
        for c in exe_candidates:
            if os.path.isfile(c):
                return c
        import shutil
        found = shutil.which("code") or shutil.which("code.cmd")
        if found:
            return found
        return None

    # ── filter ───────────────────────────────────────────────────────

    def _is_noise(self, rel_path):
        basename = rel_path.rsplit("/", 1)[-1].lower()
        if basename in NOISE_FILES:
            return True
        parts = rel_path.lower().split("/")
        return any(p.startswith(pfx) for p in parts for pfx in NOISE_PREFIXES)

    def _apply_filter(self, text):
        text = text.strip()
        hide_noise = self._hide_noise.isChecked()

        negate = False
        pattern = ""
        if text:
            negate = text.startswith("!") or text.startswith("^")
            pattern = text[1:].strip().lower() if negate else text.lower()

        for pane in (self._win, self._lose, self._none):
            tree = pane["tree"]
            for i in range(tree.topLevelItemCount()):
                row = tree.topLevelItem(i)
                rel = row.text(0).lower()

                if hide_noise and self._is_noise(rel):
                    row.setHidden(True)
                    continue

                if not pattern:
                    row.setHidden(False)
                else:
                    match = pattern in rel
                    row.setHidden(match if negate else not match)


# ── plugin entry point ───────────────────────────────────────────────

class ConflictDiff(mobase.IPluginTool):

    def __init__(self):
        super().__init__()
        self._org = None
        self._parent = None

    def init(self, organizer):
        self._org = organizer
        return True

    def name(self):
        return "Conflict Diff"

    def author(self):
        return "SkyrimNet"

    def description(self):
        return "Compare conflicting files between mods in VS Code diff view"

    def version(self):
        return mobase.VersionInfo(1, 0, 0, 0)

    def requirements(self):
        return []

    def settings(self):
        return []

    def displayName(self):
        return "Conflict Diff"

    def tooltip(self):
        return "Opens a conflict browser with VS Code diff support"

    def icon(self):
        return QIcon()

    def setParentWidget(self, widget):
        self._parent = widget

    def display(self):
        selected = self._get_selected_mod()
        dlg = ConflictDiffDialog(self._org, self._parent, selected_mod=selected)
        if hasattr(dlg, "exec"):
            dlg.exec()
        else:
            dlg.exec_()

    def _get_selected_mod(self):
        try:
            ml = self._org.modList()
            mods = ml.allMods()
            for mod in mods:
                if ml.state(mod) & 0x10:  # ModState.SELECTED (not always in mobase)
                    return mod
        except Exception:
            pass
        return None


def createPlugin():
    return ConflictDiff()
