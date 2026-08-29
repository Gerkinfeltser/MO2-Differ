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
        QApplication, QLineEdit, QAction, QMessageBox, QTreeView,
    )
    from PyQt5.QtCore import Qt, QObject, QEvent
    from PyQt5.QtGui import QIcon, QCursor
except ImportError:
    from PyQt6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QComboBox, QTreeWidget,
        QTreeWidgetItem, QSplitter, QLabel, QMenu, QGroupBox,
        QApplication, QLineEdit, QMessageBox, QTreeView,
    )
    from PyQt6.QtCore import Qt, QObject, QEvent
    from PyQt6.QtGui import QIcon, QAction, QCursor

# Qt enum compatibility (PyQt5 uses flat enums, PyQt6 uses scoped)
_Vertical = getattr(Qt, "Vertical", None) or Qt.Orientation.Vertical
_UserRole = getattr(Qt, "UserRole", None) or Qt.ItemDataRole.UserRole
_WaitCursor = getattr(Qt, "WaitCursor", None) or Qt.CursorShape.WaitCursor
_CustomContextMenu = (
    getattr(Qt, "CustomContextMenu", None) or Qt.ContextMenuPolicy.CustomContextMenu
)
_NoInsert = (
    getattr(QComboBox, "NoInsert", None) or QComboBox.InsertPolicy.NoInsert
)
_MatchContains = (
    getattr(Qt, "MatchContains", None) or Qt.MatchFlag.MatchContains
)
_CaseInsensitive = (
    getattr(Qt, "CaseInsensitive", None) or Qt.CaseSensitivity.CaseInsensitive
)

_ShowEvent = getattr(QEvent, "Show", None) or QEvent.Type.Show
_ContextMenuEvent = getattr(QEvent, "ContextMenu", None) or QEvent.Type.ContextMenu

DEFAULT_EXCLUDES = ".fuz, .dds, .nif, .hkx, .pex, .bsa, .ba2, .esp, .esm, .esl, meta.ini, readme, license, changelog, .git"

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
        self._mod_combo.setInsertPolicy(_NoInsert)
        self._mod_combo.setMinimumWidth(300)
        self._mod_combo.completer().setFilterMode(_MatchContains)
        self._mod_combo.completer().setCaseSensitivity(_CaseInsensitive)
        self._mod_combo.activated.connect(
            lambda idx: self._on_mod_changed(self._mod_combo.itemText(idx))
        )
        bar.addWidget(self._mod_combo, 1)
        root.addLayout(bar)

        # include / exclude filter row
        filter_bar = QHBoxLayout()
        filter_bar.addWidget(QLabel("Include:"))
        self._include_edit = QLineEdit()
        self._include_edit.setPlaceholderText("e.g. .ini, textures")
        self._include_edit.setClearButtonEnabled(True)
        self._include_edit.textChanged.connect(self._apply_filter)
        filter_bar.addWidget(self._include_edit, 1)
        filter_bar.addWidget(QLabel("Exclude:"))
        self._exclude_edit = QLineEdit()
        self._exclude_edit.setText(DEFAULT_EXCLUDES)
        self._exclude_edit.setClearButtonEnabled(True)
        self._exclude_edit.textChanged.connect(self._apply_filter)
        filter_bar.addWidget(self._exclude_edit, 1)
        root.addLayout(filter_bar)

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

        self._apply_filter()
        for p in (self._win, self._lose, self._none):
            visible = sum(
                1 for i in range(p["tree"].topLevelItemCount())
                if not p["tree"].topLevelItem(i).isHidden()
            )
            total = p["tree"].topLevelItemCount()
            if visible == total:
                p["box"].setTitle(f"{p['title']} ({total})")
            else:
                p["box"].setTitle(f"{p['title']} ({visible}/{total})")

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

    @staticmethod
    def _parse_terms(text):
        return [t.strip().lower() for t in text.split(",") if t.strip()]

    def _apply_filter(self, _text=None):
        includes = self._parse_terms(self._include_edit.text())
        excludes = self._parse_terms(self._exclude_edit.text())

        for pane in (self._win, self._lose, self._none):
            tree = pane["tree"]
            for i in range(tree.topLevelItemCount()):
                row = tree.topLevelItem(i)
                rel = row.text(0).lower()

                if excludes and any(ex in rel for ex in excludes):
                    row.setHidden(True)
                    continue

                if includes and not any(inc in rel for inc in includes):
                    row.setHidden(True)
                    continue

                row.setHidden(False)

        for pane in (self._win, self._lose, self._none):
            tree = pane["tree"]
            visible = sum(
                1 for i in range(tree.topLevelItemCount())
                if not tree.topLevelItem(i).isHidden()
            )
            total = tree.topLevelItemCount()
            if visible == total:
                pane["box"].setTitle(f"{pane['title']} ({total})")
            else:
                pane["box"].setTitle(f"{pane['title']} ({visible}/{total})")


# ── context menu injection (fragile — depends on MO2 widget names) ───

class _MenuInjector(QObject):
    """Watches for QMenu Show events and injects a 'Conflict Diff' action
    when the menu originates from the main mod list."""

    def __init__(self, mod_list_widget, open_callback, log_fn=None):
        super().__init__()
        self._mod_list = mod_list_widget
        self._viewport = mod_list_widget.viewport()
        self._open_callback = open_callback
        self._armed = False
        self._log = log_fn or (lambda msg: None)

    def eventFilter(self, obj, event):
        etype = event.type()
        if etype == _ContextMenuEvent:
            is_ours = (obj is self._mod_list or obj is self._viewport)
            self._log(f"ContextMenu event on {type(obj).__name__} "
                      f"name={obj.objectName()!r} is_ours={is_ours}")
            if is_ours:
                self._armed = True
        elif etype == _ShowEvent and isinstance(obj, QMenu):
            self._log(f"QMenu Show, armed={self._armed}")
            if self._armed:
                self._armed = False
                obj.addSeparator()
                act = obj.addAction("Conflict Diff")
                act.triggered.connect(self._on_triggered)
                self._log("injected Conflict Diff action")
        return False

    def _on_triggered(self):
        idx = self._mod_list.currentIndex()
        if idx.isValid():
            mod_name = idx.sibling(idx.row(), 0).data()
            self._open_callback(mod_name)
        else:
            self._open_callback(None)


# ── plugin entry point ───────────────────────────────────────────────

class ConflictDiff(mobase.IPluginTool):

    def __init__(self):
        super().__init__()
        self._org = None
        self._parent = None

    def init(self, organizer):
        self._org = organizer
        self._injector = None
        self._debug_log = os.path.join(
            os.path.dirname(__file__), "conflict_diff_debug.log"
        )
        try:
            self._org.onUserInterfaceInitialized(self._on_ui_init)
            self._log("registered onUserInterfaceInitialized")
        except Exception as e:
            self._log(f"onUserInterfaceInitialized failed: {e}")
        return True

    def _log(self, msg):
        try:
            with open(self._debug_log, "a", encoding="utf-8") as f:
                f.write(f"{msg}\n")
        except Exception:
            pass

    def _on_ui_init(self, main_window=None):
        self._log(f"_on_ui_init called, main_window={main_window}")
        if main_window is None:
            main_window = QApplication.activeWindow()
            self._log(f"fallback activeWindow={main_window}")
        if main_window is None:
            self._log("no main window found")
            return

        # dump all tree views and their object names
        try:
            from PyQt5.QtWidgets import QAbstractItemView
        except ImportError:
            from PyQt6.QtWidgets import QAbstractItemView

        for widget in main_window.findChildren(QAbstractItemView):
            name = widget.objectName()
            cls = type(widget).__name__
            self._log(f"  found {cls} objectName={name!r}")

        # try to find the mod list
        found = None
        for name in ("modList", "modListView", "modListWidget", "leftPane"):
            widget = main_window.findChild(QAbstractItemView, name)
            if widget:
                found = widget
                self._log(f"matched widget: {name}")
                break

        if not found:
            # fallback: try all QTreeViews
            trees = main_window.findChildren(QTreeView)
            self._log(f"QTreeView fallback: {len(trees)} found")
            for t in trees:
                self._log(f"  QTreeView objectName={t.objectName()!r}")

        if found:
            self._injector = _MenuInjector(found, self._open_for_mod, self._log)
            found.installEventFilter(self._injector)
            found.viewport().installEventFilter(self._injector)
            QApplication.instance().installEventFilter(self._injector)
            self._log(f"injector installed on {found.objectName()!r}")
        else:
            self._log("no mod list widget found")

    def _open_for_mod(self, mod_name):
        dlg = ConflictDiffDialog(self._org, self._parent, selected_mod=mod_name)
        if hasattr(dlg, "exec"):
            dlg.exec()
        else:
            dlg.exec_()

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
