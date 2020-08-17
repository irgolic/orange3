import glob
import shutil
import sys
import os
import tempfile
from typing import Optional, List

import pandas

from jupyter_client import MultiKernelManager

from AnyQt.QtWidgets import (
    QListView, QSizePolicy, QMenu, QSplitter, QLineEdit,
    QAction, QToolButton, QFileDialog, QStyledItemDelegate,
    QStyleOptionViewItem, QPlainTextDocumentLayout,
    QLabel, QWidget, QHBoxLayout, QMessageBox, QAbstractItemView)
from AnyQt.QtGui import (
    QColor, QPalette, QFont, QTextDocument, QKeySequence,
    QFontMetrics, QDesktopServices, QPainter, QIcon)
from AnyQt.QtCore import Qt, QByteArray, QItemSelectionModel, QSize, \
    Signal, QUrl, QObject, QRectF

import pygments.style
from pygments.token import Comment, Keyword, Number, String, Punctuation, Operator, Error, Name
from qtconsole import styles
from qtconsole.client import QtHBChannel, QtKernelClient
from qtconsole.manager import QtKernelManager
from qtconsole.pygments_highlighter import PygmentsHighlighter
from traitlets import DottedObjectName, Type

from Orange.canvas import config
from Orange.widgets.data.utils.python_console import OrangeConsoleWidget
from Orange.widgets.data.utils.pythoneditor.editor import PythonEditor
from Orange.data import Table, pandas_compat
from Orange.base import Learner, Model
from Orange.widgets import gui
from Orange.widgets.utils import itemmodels
from Orange.widgets.settings import Setting
from Orange.widgets.utils.widgetpreview import WidgetPreview
from Orange.widgets.widget import OWWidget, Input, Output, Msg
from orangecanvas.gui.utils import message_question

# pylint: disable=too-many-lines,too-many-instance-attributes

__all__ = ["OWPythonScript"]


SCRIPTS_FOLDER_PATH = os.path.join(config.data_dir(), 'python_script_library/')
DEFAULT_FILENAME = 'scratch'


"""
Adapted from jupyter notebook, which was adapted from GitHub.

Highlighting styles are applied with pygments.

pygments does not support partial highlighting; on every character
typed, it performs a full pass of the code. If performance is ever
an issue, revert to prior commit, which uses Qutepart's syntax
highlighting implementation.
"""
SYNTAX_HIGHLIGHTING_STYLES = {
    'Light': {
        Error: '#f00',

        Keyword: 'bold #008000',

        Name: '#212121',
        Name.Function: '#00f',
        Name.Variable: '#05a',
        Name.Decorator: '#aa22ff',
        Name.Builtin: '#008000',
        Name.Builtin.Pseudo: '#05a',

        String: '#ba2121',

        Number: '#080',

        Operator: 'bold #aa22ff',
        Operator.Word: 'bold #008000',

        Comment: 'italic #408080',
    },
    'Dark': {
        # TODO
    }
}


def make_pygments_style(scheme_name):
    """
    Dynamically create a PygmentsStyle class,
    given the name of one of the above highlighting schemes.
    """
    return type(
        'PygmentsStyle',
        (pygments.style.Style,),
        {'styles': SYNTAX_HIGHLIGHTING_STYLES[scheme_name]}
    )


PygmentsStyle = make_pygments_style('Light')


class VimIndicator(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.indicator_color = QColor('#33cc33')
        self.indicator_text = 'normal'

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(self.indicator_color)

        p.save()
        p.setPen(Qt.NoPen)
        fm = QFontMetrics(self.font())
        width = self.rect().width()
        height = fm.height() + 6
        rect = QRectF(0, 0, width, height)
        p.drawRoundedRect(rect, 5, 5)
        p.restore()

        textstart = (width - fm.width(self.indicator_text)) / 2
        p.drawText(textstart, height / 2 + 5, self.indicator_text)

    def minimumSizeHint(self):
        fm = QFontMetrics(self.font())
        width = fm.width(self.indicator_text) + 10
        height = fm.height() + 6
        return QSize(width, height)


class FakeSignatureMixin:
    def __init__(self, parent, highlighting_scheme, font):
        super().__init__(parent)
        self.highlighting_scheme = highlighting_scheme
        self.setFont(font)
        self.bold_font = QFont(font)
        self.bold_font.setBold(True)

        self.indentation_level = 0

        self._char_4_width = QFontMetrics(font).width('4444')

    def setIndent(self, margins_width):
        self.setContentsMargins(max(0,
                                    margins_width +
                                    (self.indentation_level - 1) * self._char_4_width),
                                0, 0, 0)


class FunctionSignature(FakeSignatureMixin, QLabel):
    def __init__(self, parent, highlighting_scheme, font, function_name="python_script"):
        super().__init__(parent, highlighting_scheme, font)
        self.signal_prefix = 'in_'

        # `def python_script(`
        self.prefix = ('<b style="color: ' +
                       self.highlighting_scheme[Keyword].split(' ')[-1] +
                       ';">def </b>'
                       '<span style="color: ' +
                       self.highlighting_scheme[Name.Function].split(' ')[-1] +
                       ';">' + function_name + '</span>'
                       '<span style="color: ' +
                       self.highlighting_scheme[Punctuation].split(' ')[-1] +
                       ';">(</span>')

        # `):`
        self.affix = ('<span style="color: ' +
                      self.highlighting_scheme[Punctuation].split(' ')[-1] +
                      ';">):</span>')

        self.update_signal_text({})

    def update_signal_text(self, signal_values_lengths):
        if not self.signal_prefix:
            return
        lbl_text = self.prefix
        if len(signal_values_lengths) > 0:
            for name, value in signal_values_lengths.items():
                if value == 1:
                    lbl_text += self.signal_prefix + name + ', '
                elif value > 1:
                    lbl_text += self.signal_prefix + name + 's, '
            lbl_text = lbl_text[:-2]  # shave off the trailing ', '
        lbl_text += self.affix
        if self.text() != lbl_text:
            self.setText(lbl_text)
            self.update()


class ReturnStatement(FakeSignatureMixin, QWidget):
    def __init__(self, parent, highlighting_scheme, font):
        super().__init__(parent, highlighting_scheme, font)

        self.indentation_level = 1
        self.signal_labels = {}
        self._prefix = None
        self.df_enabled = True

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # `return `
        ret_lbl = QLabel('<b style="color: ' + \
                         highlighting_scheme[Keyword].split(' ')[-1] + \
                         ';">return </b>', self)
        ret_lbl.setFont(self.font())
        ret_lbl.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(ret_lbl)

        # `out_data[, ]` * 4
        self.make_signal_labels('out_')

        layout.addStretch()
        self.setLayout(layout)

    def make_signal_labels(self, prefix):
        self._prefix = prefix
        # `in_data[, ]`
        for i, signal in enumerate(OWPythonScript.signal_names):
            # adding an empty b tag like this adjusts the
            # line height to match the rest of the labels
            signal_display_name = 'df' if signal == 'data' and self.df_enabled else signal
            signal_lbl = QLabel('<b></b>' + prefix + signal_display_name, self)
            signal_lbl.setFont(self.font())
            signal_lbl.setContentsMargins(0, 0, 0, 0)
            self.layout().addWidget(signal_lbl)

            self.signal_labels[signal] = signal_lbl

            if i >= len(OWPythonScript.signal_names) - 1:
                break

            comma_lbl = QLabel(', ')
            comma_lbl.setFont(self.font())
            comma_lbl.setContentsMargins(0, 0, 0, 0)
            comma_lbl.setStyleSheet('.QLabel { color: ' +
                                    self.highlighting_scheme[Punctuation].split(' ')[-1] +
                                    '; }')
            self.layout().addWidget(comma_lbl)

    def update_signal_text(self, signal_name, values_length):
        if not self._prefix:
            return
        lbl = self.signal_labels[signal_name]
        if signal_name == 'data' and self.df_enabled:
            signal_name = 'df'
        if values_length == 0:
            text = '<b></b>' + self._prefix + signal_name
        else:  # if values_length == 1:
            text = '<b>' + self._prefix + signal_name + '</b>'
        if lbl.text() != text:
            lbl.setText(text)
            lbl.update()

    def use_df_data_label(self, enabled):
        self.df_enabled = enabled
        lbl = self.signal_labels['data']
        if enabled:
            if lbl.text().startswith('<b></b>'):
                text = '<b></b>' + self._prefix + 'df'
            else:
                text = '<b>' + self._prefix + 'df</b>'
        else:
            if lbl.text().startswith('<b></b>'):
                text = '<b></b>' + self._prefix + 'data'
            else:
                text = '<b>' + self._prefix + 'data</b>'
        if lbl.text() != text:
            lbl.setText(text)
            lbl.update()


def read_file_content(filename, limit=None):
    try:
        with open(filename, encoding="utf-8", errors='strict') as f:
            text = f.read(limit)
            return text
    except (OSError, UnicodeDecodeError):
        return None


class Script:
    Modified = 1
    MissingFromFilesystem = 2

    def __init__(self, script, filename, flags=2):
        self._script = script
        self._filename = filename
        self.fullname = None
        self.flags = flags

        if not flags & self.MissingFromFilesystem:
            self._save_script()

    @property
    def script(self):
        return self._script

    @script.setter
    def script(self, script):
        self._script = script
        self._save_script()

    @property
    def filename(self):
        return self._filename

    @filename.setter
    def filename(self, filename):
        if self._filename == filename:
            return
        old_filename = self._filename
        self._filename = filename
        if self.flags & self.MissingFromFilesystem:
            return
        old_fullname = self.fullname
        self.fullname = os.path.join(SCRIPTS_FOLDER_PATH, filename)
        if os.path.exists(old_fullname):
            os.rename(old_fullname, self.fullname)
            OWPythonScript.script_state_manager.scriptRenamed.emit(old_filename, filename)

    def reload(self):
        if not os.path.exists(self.fullname):
            self.flags = self.MissingFromFilesystem
            return False
        with open(self.fullname) as f:
            self._script = f.read()
        return True

    def refresh(self, new_script, set_modified=True):
        if self.script != new_script:
            if set_modified:
                self.flags |= self.Modified
            self._script = new_script
        else:
            self.flags &= ~self.Modified

    def _save_script(self):
        self.fullname = os.path.join(SCRIPTS_FOLDER_PATH, self.filename)
        with open(self.fullname, 'w') as f:
            f.write(self._script)
        self.flags &= ~(self.Modified | self.MissingFromFilesystem)


class ScriptItemDelegate(QStyledItemDelegate):
    # pylint: disable=no-self-use
    def displayText(self, script, _locale):
        if script.flags & Script.MissingFromFilesystem:
            return '* ' + script.filename
        return script.filename

    def paint(self, painter, option, index):
        script = index.data(Qt.DisplayRole)
        if script.flags & Script.MissingFromFilesystem:
            option = QStyleOptionViewItem(option)
            option.palette.setColor(QPalette.Text, QColor(Qt.darkGray))
            option.font.setItalic(True)
        elif script.flags & Script.Modified:
            option = QStyleOptionViewItem(option)
            option.palette.setColor(QPalette.Text, QColor(Qt.red))
            option.palette.setColor(QPalette.HighlightedText, QColor(Qt.white))
            option.palette.setColor(QPalette.Highlight, QColor(Qt.darkRed))
        super().paint(painter, option, index)

    def createEditor(self, parent, _option, _index):
        return QLineEdit(parent)

    def setEditorData(self, editor, index):
        script = index.data(Qt.DisplayRole)
        editor.setText(script.filename)

    def setModelData(self, editor, model, index):
        filename = str(editor.text())
        script = index.data(Qt.DisplayRole)
        filename = uniqueify_filename(model, script, filename)
        script.filename = filename


class ScriptStateManager(QObject):
    scriptSaved = Signal(str, str)
    scriptRemoved = Signal(str)
    scriptRenamed = Signal(str, str)


def uniqueify_filename(model, curr_script, filename):
    script_names = []
    for script in model:
        if script == curr_script:
            continue
        script_names.append(script.filename)

    if filename.endswith('.py'):
        stem = filename[:-3]
    else:
        stem = filename

    if not stem:
        stem = DEFAULT_FILENAME

    template = stem + '{}'
    name = template.format('') + '.py'
    if name in script_names:
        i = 2
        while True:
            name = template.format('_' + str(i)) + '.py'
            if name not in script_names:
                break
            i += 1
    return name


def select_row(view, row):
    """
    Select a `row` in an item view
    """
    selmodel = view.selectionModel()
    selmodel.select(view.model().index(row, 0),
                    QItemSelectionModel.ClearAndSelect)


# TODO it takes a while for the kernel and client to start up,
# the default 3 second timeout seems too short.
# it's likely a bug that it takes that long, but for now,
# this monkeypatch making it a 10 second timeout works fine
class HBChannel(QtHBChannel):
    time_to_dead = 10.0


class KernelClient(QtKernelClient):
    hb_channel_class = Type(HBChannel)


class KernelManager(QtKernelManager):
    client_class = DottedObjectName('Orange.widgets.data.owpythonscript.KernelClient')


class OWPythonScript(OWWidget):
    name = "Python Script"
    description = "Write a Python script and run it on input data or models."
    icon = "icons/PythonScript.svg"
    priority = 3150
    keywords = ["program"]

    class Inputs:
        data = Input("Data", Table, replaces=["in_data"],
                     default=True, multiple=True)
        learner = Input("Learner", Learner, replaces=["in_learner"],
                        default=True, multiple=True)
        classifier = Input("Classifier", Model, replaces=["in_classifier"],
                           default=True, multiple=True)
        object = Input("Object", object, replaces=["in_object"],
                       default=False, multiple=True)

    class Outputs:
        data = Output("Data", Table, replaces=["out_data"])
        learner = Output("Learner", Learner, replaces=["out_learner"])
        classifier = Output("Classifier", Model, replaces=["out_classifier"])
        object = Output("Object", object, replaces=["out_object"])

    signal_names = ("data", "learner", "classifier", "object")

    settings_version = 3
    current_script: Optional[tuple] = Setting(None, schema_only=True)
    other_scratch_scripts: list = Setting([], schema_only=True)

    vimModeEnabled = Setting(False)
    orangeDataTablesEnabled = Setting(False)

    splitterState: Optional[bytes] = Setting(None)

    multi_kernel_manager = MultiKernelManager()
    multi_kernel_manager.kernel_manager_class = 'Orange.widgets.data.owpythonscript.KernelManager'

    script_state_manager = ScriptStateManager()

    def _handleScriptRemoved(self, filename):
        script = next(s for s in self.libraryList if s.filename == filename)
        if script in self._cachedDocuments:
            script.flags |= Script.MissingFromFilesystem
        else:
            self.libraryList.remove(script)
            if len(self.libraryList) == 0:
                self.addScript()
                select_row(self.libraryView, 0)

    def _handleScriptSaved(self, filename, new_script_text):
        try:
            # is this an already saved script?
            name_colliding_script = next(s for s in self.libraryList if s.filename == filename)
            if not name_colliding_script.flags & Script.MissingFromFilesystem:
                name_colliding_script.refresh(
                    new_script_text,
                    set_modified=name_colliding_script in self._cachedDocuments
                )
                return
            # else, this is a new script
            # the name could already appear as one of the scratch scripts
            else:
                name_colliding_script.filename = uniqueify_filename(
                    self.libraryList, None, filename
                )
        except StopIteration:
            pass
        self.libraryList.append(Script(new_script_text, filename, flags=0))

    def _handleScriptRenamed(self, old_filename, new_filename):
        try:
            script = next(s for s in self.libraryList if s.filename == old_filename)
            script.filename = new_filename
        except StopIteration:
            # Since the event that triggers this method is emitted from within
            # the Script class, the Python Script instance isn't disconnected
            # from the signal, so it's trigger in the current widget as well.
            # This isn't the cleanest, but it seemed to be the simplest
            # solution, as renaming scripts is fully handled by the
            # ScriptItemDelegate and Script classes
            pass

    class Warning(OWWidget.Warning):
        illegal_var_type = Msg('{} should be of type {}, not {}.')

    class Error(OWWidget.Error):
        load_error = Msg('Error loading {}.')

    def __init__(self):
        super().__init__()
        for name in self.signal_names:
            setattr(self, name, {})

        self._cachedDocuments = {}

        self.libraryList = itemmodels.PyListModel(
            [], self,
            flags=Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable
        )

        self.script_state_manager.scriptRemoved.connect(self._handleScriptRemoved)
        self.script_state_manager.scriptSaved.connect(self._handleScriptSaved)
        self.script_state_manager.scriptRenamed.connect(self._handleScriptRenamed)

        self.editor_controls = gui.vBox(self.controlArea, 'Editor options')
        # filled in after editor is constructed

        self.libraryBox = gui.vBox(self.controlArea, 'Library')
        self.libraryBox.layout().setSpacing(1)

        self.libraryView = QListView(
            editTriggers=QListView.DoubleClicked | QListView.EditKeyPressed,
            sizePolicy=QSizePolicy(QSizePolicy.Ignored,
                                   QSizePolicy.Preferred),
        )
        self.libraryView.setSelectionMode(QAbstractItemView.SingleSelection)
        self.libraryView.setItemDelegate(ScriptItemDelegate(self))
        self.libraryView.setModel(self.libraryList)

        self.libraryView.selectionModel().selectionChanged.connect(
            self.onSelectedScriptChanged
        )

        self.libraryBox.layout().addWidget(self.libraryView)

        def _icon(name):
            return QIcon(os.path.join(
                os.path.dirname(__file__), "icons/pythonscript", name
            ))

        actions_box = gui.hBox(self.libraryBox, box=True)

        icon = _icon('add.svg')
        self.addNewScriptAction = action = QAction(icon, 'Add', self)
        action.setToolTip("New script")
        action.triggered.connect(self.onAddScript)
        button = QToolButton(actions_box)
        button.setContentsMargins(0, 0, 0, 0)
        button.setDefaultAction(action)
        actions_box.layout().addWidget(button)

        icon = _icon('save.svg')
        action = QAction(icon, 'Save', self)
        action.setToolTip("Save changes to selected script")
        action.setShortcut(QKeySequence(QKeySequence.Save))
        action.triggered.connect(self.commitChangesToLibrary)
        button = QToolButton(actions_box)
        button.setContentsMargins(0, 0, 0, 0)
        button.setDefaultAction(action)
        actions_box.layout().addWidget(button)

        icon = _icon('restore.svg')
        self.restoreAction = action = QAction(icon, 'Restore', self)
        action.setEnabled(False)
        action.setToolTip("Restore saved script")
        action.triggered.connect(self.restoreSaved)
        button = QToolButton(actions_box)
        button.setContentsMargins(0, 0, 0, 0)
        button.setDefaultAction(action)
        actions_box.layout().addWidget(button)

        icon = _icon('more.svg')
        action = QAction(icon, "More", self)
        action.setToolTip('More actions')

        open_from_file = QAction("Open", self)
        open_from_file.setShortcut(QKeySequence.Open)
        open_from_file.triggered.connect(self.onAddScriptFromFile)

        save_to_file = QAction("Save As", self)
        save_to_file.setShortcut(QKeySequence.SaveAs)
        save_to_file.triggered.connect(self.saveScript)

        remove_script = QAction('Delete', self)
        remove_script.setShortcut(QKeySequence.Delete)
        remove_script.setToolTip("Remove script from library")
        remove_script.triggered.connect(self.onRemoveScript)

        reveal_folder = QAction(
            "Reveal in Finder" if sys.platform == 'darwin' else
            "Show in Explorer",
            self
        )
        reveal_folder.triggered.connect(self.revealFolder)

        reload_library = QAction('Reload Library', self)
        reload_library.triggered.connect(self.reloadLibrary)

        menu = QMenu(actions_box)
        menu.addAction(open_from_file)
        menu.addAction(save_to_file)
        menu.addAction(remove_script)
        menu.addAction(reveal_folder)
        menu.addAction(reload_library)
        action.setMenu(menu)
        button = QToolButton(actions_box)
        button.setContentsMargins(0, 0, 0, 0)
        button.setDefaultAction(action)
        button.setPopupMode(QToolButton.InstantPopup)
        actions_box.layout().addWidget(button)

        self.execute_button = gui.button(self.controlArea, self, 'Run',
                                         toolTip='Run script (⇧⏎)',
                                         callback=self.commit)

        self.run_action = run = QAction("Run script", self, triggered=self.commit,
                                        shortcut=QKeySequence(Qt.ControlModifier | Qt.Key_R))
        self.addAction(run)

        self.splitCanvas = QSplitter(Qt.Vertical, self.mainArea)
        self.mainArea.layout().addWidget(self.splitCanvas)

        self.defaultFont = defaultFont = 'Menlo'
        self.defaultFontSize = defaultFontSize = 13

        self.editorBox = gui.vBox(self, box=True)
        self.splitCanvas.addWidget(self.editorBox)

        syntax_highlighting_scheme = SYNTAX_HIGHLIGHTING_STYLES['Light']

        eFont = QFont(defaultFont)
        eFont.setPointSize(defaultFontSize)

        func_sig = FunctionSignature(self.editorBox,
                                     syntax_highlighting_scheme,
                                     eFont)
        self.func_sig = func_sig

        editor = PythonEditor(self)
        editor.setFont(eFont)

        # TODO should we care about displaying these warnings?
        # editor.userWarning.connect()

        self.vim_box = gui.hBox(self.editor_controls, spacing=20)
        self.vim_indicator = VimIndicator(self.vim_box)
        self.vim_indicator.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        def enable_vim_mode():
            editor.vimModeEnabled = self.vimModeEnabled
            self.vim_indicator.setVisible(self.vimModeEnabled)
        enable_vim_mode()

        gui.checkBox(self.vim_box, self, 'vimModeEnabled', 'Vim mode',
                     tooltip='All the cool programmers use vim mode.',
                     callback=enable_vim_mode)
        self.vim_box.layout().addWidget(self.vim_indicator)
        @editor.vimModeIndicationChanged.connect
        def _(color, text):
            self.vim_indicator.indicator_color = color
            self.vim_indicator.indicator_text = text
            self.vim_indicator.update()

        return_stmt = ReturnStatement(self.editorBox,
                                      syntax_highlighting_scheme,
                                      eFont)
        self.return_stmt = return_stmt

        def update_df_label_in_signatures():
            return_stmt.use_df_data_label(not self.orangeDataTablesEnabled)
            self.update_fake_function_signature_labels()
        update_df_label_in_signatures()

        gui.checkBox(self.editor_controls, self, 'orangeDataTablesEnabled',
                     'Use native data tables',
                     tooltip='By default, in_df and out_df (pandas.DataFrame) '
                             'replace in_data and out_data (Orange.data.table).',
                     callback=update_df_label_in_signatures)

        textEditBox = QWidget(self.editorBox)
        textEditBox.setLayout(QHBoxLayout())
        char_4_width = QFontMetrics(eFont).width('0000')

        @editor.viewport_margins_updated.connect
        def _(width):
            func_sig.setIndent(width)
            textEditMargin = max(0, char_4_width - width)
            return_stmt.setIndent(textEditMargin + width)
            textEditBox.layout().setContentsMargins(
                textEditMargin, 0, 0, 0
            )

        self.editor = editor
        textEditBox.layout().addWidget(self.editor)

        self.editorBox.layout().addWidget(func_sig)
        self.editorBox.layout().addWidget(textEditBox)
        self.editorBox.layout().addWidget(return_stmt)
        self.editorBox.setAlignment(Qt.AlignVCenter)
        self.saveAction = action = QAction("&Save", self.editor)
        action.setToolTip("Save script to file")
        action.setShortcut(QKeySequence(QKeySequence.Save))
        action.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        action.triggered.connect(self.saveScript)

        self.consoleBox = gui.vBox(self, 'Console')
        self.splitCanvas.addWidget(self.consoleBox)

        self._temp_connection_dir = tempfile.mkdtemp()
        self.multi_kernel_manager.connection_dir = self._temp_connection_dir
        self.kernel_id = kernel_id = self.multi_kernel_manager.start_kernel(
            extra_arguments=[
                '--IPKernelApp.kernel_class='
                'Orange.widgets.data.utils.python_kernel.OrangeIPythonKernel',
                '--matplotlib='
                'inline'
            ]
        )
        kernel_manager = self.multi_kernel_manager.get_kernel(kernel_id)

        kernel_client = kernel_manager.client()
        kernel_client.start_channels()

        jupyter_widget = OrangeConsoleWidget(style_sheet=styles.default_light_style_sheet)
        jupyter_widget.results_ready.connect(self.receive_outputs)

        jupyter_widget.kernel_manager = kernel_manager
        jupyter_widget.kernel_client = kernel_client

        jupyter_widget._highlighter.set_style(PygmentsStyle)
        jupyter_widget.font_family = defaultFont
        jupyter_widget.font_size = defaultFontSize
        jupyter_widget.reset_font()

        self.console = jupyter_widget
        self.consoleBox.layout().addWidget(self.console)
        self.consoleBox.setAlignment(Qt.AlignBottom)
        self.splitCanvas.setSizes([2, 1])
        self.setAcceptDrops(True)
        self.controlArea.layout().addStretch(10)

        self._restoreState()
        self.settingsAboutToBePacked.connect(self._saveState)

    def sizeHint(self) -> QSize:
        return super().sizeHint().expandedTo(QSize(800, 600))

    def _restoreState(self):
        scripts = []
        if not os.path.exists(SCRIPTS_FOLDER_PATH):
            os.makedirs(SCRIPTS_FOLDER_PATH)
        else:
            script_paths = glob.glob(os.path.join(SCRIPTS_FOLDER_PATH, '*.py'))
            scripts = []
            for pathname in script_paths:
                f = open(pathname, 'r')
                scripts += [Script(f.read(), os.path.basename(pathname), flags=0)]
                f.close()

        self.libraryList.wrap(scripts)

        if self.splitterState is not None:
            self.splitCanvas.restoreState(QByteArray(self.splitterState))

        if self.current_script is None:
            self.addScript(text="print('Hello world!')")
            i = len(self.libraryList) - 1
        else:
            text, filename = self.current_script
            for i, script in enumerate(scripts):
                if text == script.script and filename == script.filename:
                    break
            else:
                self.addScript(text=text, filename=filename)
                i = len(self.libraryList) - 1

        for script in self.other_scratch_scripts:
            self.addScript(text=script[0], filename=script[1])

        select_row(self.libraryView, i)

    def _saveState(self):
        self.splitterState = bytes(self.splitCanvas.saveState())
        current_index = self.selectedScriptIndex()
        script = self.libraryList[current_index]
        self.current_script = (self.editor.text, script.filename)
        self.other_scratch_scripts = [
            (s.script, s.filename) for i, s in enumerate(self.libraryList)
            if s.flags & Script.MissingFromFilesystem and i != current_index
        ]

    def handle_input(self, obj, sig_id, signal):
        sig_id = sig_id[0]
        dic = getattr(self, signal)
        if obj is None:
            if sig_id in dic.keys():
                del dic[sig_id]
        else:
            dic[sig_id] = obj

    @Inputs.data
    def set_data(self, data, sig_id):
        self.handle_input(data, sig_id, "data")

    @Inputs.learner
    def set_learner(self, data, sig_id):
        self.handle_input(data, sig_id, "learner")

    @Inputs.classifier
    def set_classifier(self, data, sig_id):
        self.handle_input(data, sig_id, "classifier")

    @Inputs.object
    def set_object(self, data, sig_id):
        self.handle_input(data, sig_id, "object")

    def handleNewSignals(self):
        self.update_fake_function_signature_labels()
        self.commit()

    def update_fake_function_signature_labels(self):
        display_names = ['df' if n == 'data' and not self.orangeDataTablesEnabled
                         else n
                         for n in self.signal_names]
        self.func_sig.update_signal_text({
            dn: len(getattr(self, n)) for n, dn in zip(self.signal_names,
                                                       display_names)
        })

    def selectedScriptIndex(self):
        rows = self.libraryView.selectionModel().selectedRows()
        if rows:
            return [i.row() for i in rows][0]
        else:
            return None

    def setSelectedScript(self, index):
        select_row(self.libraryView, index)

    def onAddScript(self, *_):
        self.addScript(text='')
        i = len(self.libraryList) - 1
        self.setSelectedScript(i)
        self.libraryView.edit(self.libraryList.index(i))

    def onAddScriptFromFile(self, *_):
        filenames, _ = QFileDialog.getOpenFileNames(
            self, 'Open Python Script',
            os.path.expanduser("~/"),
            'Python files (*.py)\nAll files(*.*)'
        )
        for f in filenames:
            self.addScriptFromFile(f)

    def addScriptFromFile(self, filename):
        name = os.path.basename(filename)
        if not name.endswith('.py'):
            return
        try:
            with open(filename) as f:
                contents = f.read()
        except (OSError, ValueError):
            self.Error.load_error(filename)
            return
        self.addScript(contents, name)
        i = len(self.libraryList) - 1
        self.setSelectedScript(i)

    def addScript(self, text=None, filename=DEFAULT_FILENAME):
        if text is None:
            text = self.editor.text
        filename = uniqueify_filename(self.libraryView.model(), -1, filename)
        script = Script(text, filename)
        self.libraryList.append(script)

    def onRemoveScript(self, *_):
        index = self.selectedScriptIndex()
        if index is None:
            return
        script = self.libraryList[index]
        answer = message_question(
            'Do you really want to delete ' + script.filename + '?',
            'Delete file?',
            buttons=QMessageBox.No | QMessageBox.Yes,
            default_button=QMessageBox.Yes
        )
        if answer == QMessageBox.No:
            return

        self.removeScript(index)

    def removeScript(self, index):
        script = self.libraryList[index]
        filename = script.filename
        del self.libraryList[index]

        if not script.flags & Script.MissingFromFilesystem:
            os.remove(os.path.join(SCRIPTS_FOLDER_PATH, filename))
            self.script_state_manager.scriptRemoved.disconnect(self._handleScriptRemoved)
            self.script_state_manager.scriptRemoved.emit(filename)
            self.script_state_manager.scriptRemoved.connect(self._handleScriptRemoved)

        if self.libraryList.rowCount() == 0:
            self.addScript()
        select_row(self.libraryView, max(index - 1, 0))

    def onSaveScriptToFile(self, *_):
        index = self.selectedScriptIndex()
        if index is not None:
            self.saveScript()

    def onSelectedScriptChanged(self, selected, _deselected):
        index = [i.row() for i in selected.indexes()]
        if index:
            current = index[0]
            self.editor.setDocument(self.documentForScript(current))
            script = self.libraryList[current]
            self.update_saved_script_actions(not script.flags & Script.MissingFromFilesystem)

    def update_saved_script_actions(self, enabled):
        if self.restoreAction.isEnabled() != enabled:
            self.restoreAction.setEnabled(enabled)

    def documentForScript(self, script=0):
        if not isinstance(script, Script):
            script = self.libraryList[script]
        if script not in self._cachedDocuments:
            doc = QTextDocument(self)
            doc.setDocumentLayout(QPlainTextDocumentLayout(doc))
            doc.setPlainText(script.script)
            highlighter = PygmentsHighlighter(doc)
            highlighter.set_style(PygmentsStyle)
            doc.highlighter = highlighter
            doc.setDefaultFont(QFont(self.defaultFont, pointSize=self.defaultFontSize))
            doc.modificationChanged[bool].connect(self.onModificationChanged)
            doc.setModified(False)
            self._cachedDocuments[script] = doc
        return self._cachedDocuments[script]

    def commitChangesToLibrary(self, *_):
        index = self.selectedScriptIndex()
        if index is not None:
            text = self.editor.text
            script = self.libraryList[index]

            self.update_saved_script_actions(True)

            script.script = text
            self.script_state_manager.scriptSaved.disconnect(self._handleScriptSaved)
            self.script_state_manager.scriptSaved.emit(script.filename, text)
            self.script_state_manager.scriptSaved.connect(self._handleScriptSaved)

            self.editor.document().setModified(False)
            self.libraryList.emitDataChanged(index)

    def onModificationChanged(self, modified):
        index = self.selectedScriptIndex()
        if index is not None:
            script = self.libraryList[index]
            if modified:
                script.flags |= Script.Modified
            else:
                script.flags &= ~Script.Modified
            self.libraryList.emitDataChanged(index)

    def restoreSaved(self):
        index = self.selectedScriptIndex()
        if index is not None:
            script = self.libraryList[index]
            file_found = script.reload()
            self.update_saved_script_actions(file_found)
            self.editor.text = script.script
            self.editor.document().setModified(False)
            # when restoring to an empty string,
            # onModificationChanged(False) is not called for some reason
            script.flags &= ~Script.Modified

    def saveScript(self):
        index = self.selectedScriptIndex()
        if index is not None:
            script = self.libraryList[index]
            filename = script.filename
        else:
            filename = os.path.expanduser("~/")

        filename, _ = QFileDialog.getSaveFileName(
            self, 'Save Python Script',
            filename,
            'Python files (*.py)\nAll files(*.*)'
        )

        if filename:
            fn = ""
            head, tail = os.path.splitext(filename)
            if not tail:
                fn = head + ".py"
            else:
                fn = filename

            f = open(fn, 'w')
            f.write(self.editor.text)
            f.close()

    @staticmethod
    def revealFolder():
        QDesktopServices.openUrl(QUrl.fromLocalFile(SCRIPTS_FOLDER_PATH))

    def reloadLibrary(self):
        scripts = []
        if not os.path.exists(SCRIPTS_FOLDER_PATH):
            os.makedirs(SCRIPTS_FOLDER_PATH)
        else:
            script_paths = glob.glob(os.path.join(SCRIPTS_FOLDER_PATH, '*.py'))
            scripts = []
            for pathname in script_paths:
                f = open(pathname, 'r')
                scripts += [Script(f.read(), os.path.basename(pathname), flags=0)]
                f.close()
        scripts.extend([
            s for s in self.libraryList
            if s.flags & Script.MissingFromFilesystem
        ])
        self.libraryList.wrap(scripts)
        if not scripts:
            self.addScript()
        select_row(self.libraryView, 0)

    def initial_locals_state(self):
        """
        Returns lists of input signals.
        """
        d = {}
        for name in self.signal_names:
            value = getattr(self, name)
            if len(value) == 0:
                continue
            all_values = list(value.values())
            if name == 'data' and not self.orangeDataTablesEnabled:
                name = 'df'
                all_values = [pandas_compat.table_to_frame(v, include_metas=True)
                              for v in all_values]
            d["in_" + name + "s"] = all_values
        return d

    def commit(self):
        self.Warning.clear()
        self.Error.clear()

        script = str(self.editor.text)
        self.console.run_script_with_locals(script, self.initial_locals_state())

    def receive_outputs(self, out_vars):
        for signal in self.signal_names:
            if signal == 'data' and not self.orangeDataTablesEnabled:
                out_name = "out_df"
                req_type = pandas.DataFrame
            else:
                out_name = "out_" + signal
                req_type = self.Outputs.__dict__[signal].type

            output = getattr(self.Outputs, signal)
            if out_name not in out_vars:
                self.return_stmt.update_signal_text(signal, 0)
                output.send(None)
                continue
            var = out_vars[out_name]

            if not isinstance(var, req_type):
                self.return_stmt.update_signal_text(signal, 0)
                output.send(None)
                actual_type = type(var)
                self.Warning.illegal_var_type(out_name,
                                              req_type.__module__ + '.' + req_type.__name__,
                                              actual_type.__module__ + '.' + actual_type.__name__)
                continue
            if req_type == pandas.DataFrame:
                var = pandas_compat.table_from_frame(var)

            self.return_stmt.update_signal_text(signal, 1)
            output.send(var)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.InsertLineSeparator):
            # run on Shift+Enter, Ctrl+Enter
            self.run_action.trigger()
            event.accept()
        else:
            super().keyPressEvent(event)

    def dragEnterEvent(self, event):  # pylint: disable=no-self-use
        urls = event.mimeData().urls()
        if urls:
            # try reading the file as text
            c = read_file_content(urls[0].toLocalFile(), limit=1000)
            if c is not None:
                event.acceptProposedAction()

    def dropEvent(self, event):
        """Handle file drops"""
        urls = event.mimeData().urls()
        for u in urls:
            self.addScriptFromFile(u.toLocalFile())

    @classmethod
    def migrate_settings(cls, settings, version):
        if version is not None and version < 2:
            scripts = settings.pop("libraryListSource")
            library = [(s.__dict__['script'],
                        '_'.join(s.__dict__['name'].split(' ')) + '.py')
                       for s in scripts]  # type: List[tuple]
            settings["current_script"] = library.pop(0)
            settings["other_scratch_scripts"] = library
        elif version < 3:
            scripts = settings.pop("scriptLibrary")  # type: List[dict]
            index = settings.pop("currentScriptIndex")
            library = [(s['script'], s['name'] + '.py')
                       for s in scripts]
            settings["current_script"] = library.pop(index)
            settings["other_scratch_scripts"] = library
            if 'scriptText' in settings:
                text = settings.pop("scriptText")
                settings["current_script"] = (text, settings["current_script"][1])

    def onDeleteWidget(self):
        super().onDeleteWidget()
        self.console.kernel_client.shutdown()
        self.console.kernel_client.stop_channels()
        self.multi_kernel_manager.interrupt_kernel(self.kernel_id)
        self.multi_kernel_manager.shutdown_kernel(self.kernel_id)
        self.script_state_manager.scriptRemoved.disconnect(self._handleScriptRemoved)
        self.script_state_manager.scriptSaved.disconnect(self._handleScriptSaved)
        self.script_state_manager.scriptRenamed.disconnect(self._handleScriptRenamed)
        shutil.rmtree(self._temp_connection_dir)


if __name__ == "__main__":  # pragma: no cover
    WidgetPreview(OWPythonScript).run()
