import enum
import functools
import operator
import sys
from collections import namedtuple

from AnyQt import QtGui
from AnyQt.QtCore import Signal, Qt, QSize, QUrl
from PyQt5.QtGui import QIcon, QPixmap, QDesktopServices
from PyQt5.QtWidgets import QAbstractButton, QHBoxLayout, QPushButton, QStyle, QWidget, \
    QVBoxLayout, QLabel, QSizePolicy

from Orange.widgets.utils.buttons import SimpleButton
from Orange.widgets.utils.overlay import OverlayWidget, MessageWidget


class NotificationMessageWidget(QWidget):
    #: Emitted when a button with the AcceptRole is clicked
    accepted = Signal()
    #: Emitted when a button with the RejectRole is clicked
    rejected = Signal()
    #: Emitted when a button is clicked
    clicked = Signal(QAbstractButton)

    class StandardButton(enum.IntEnum):
        NoButton, Ok, Close = 0x0, 0x1, 0x2

    NoButton, Ok, Close = list(StandardButton)

    class ButtonRole(enum.IntEnum):
        InvalidRole, AcceptRole, RejectRole, DismissRole = 0, 1, 2, 3

    InvalidRole, AcceptRole, RejectRole, DismissRole = list(ButtonRole)

    _Button = namedtuple("_Button", ["button", "role", "stdbutton"])

    def __init__(self, parent=None, icon=QIcon(), title="", text="", wordWrap=False,
                 textFormat=Qt.PlainText, standardButtons=NoButton, acceptLabel="Ok",
                 rejectLabel="No", **kwargs):
        super().__init__(parent, **kwargs)
        self._title = title
        self._text = text
        self._icon = QIcon()
        self._wordWrap = wordWrap
        self._standardButtons = MessageWidget.NoButton
        self._buttons = []
        self._acceptLabel = acceptLabel
        self._rejectLabel = rejectLabel

        self._iconlabel = QLabel(objectName="icon-label")
        self._titlelabel = QLabel(objectName="title-label", text=title,
                                  wordWrap=wordWrap, textFormat=textFormat)
        self._textlabel = QLabel(objectName="text-label", text=text,
                                 wordWrap=wordWrap, textFormat=textFormat)
        self._textlabel.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self._textlabel.setOpenExternalLinks(True)

        if sys.platform == "darwin":
            self._titlelabel.setAttribute(Qt.WA_MacSmallSize)
            self._textlabel.setAttribute(Qt.WA_MacSmallSize)

        layout = QHBoxLayout()
        self._iconlabel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        layout.addWidget(self._iconlabel)
        layout.setAlignment(self._iconlabel, Qt.AlignTop)

        message_layout = QVBoxLayout()
        self._titlelabel.setSizePolicy(QtGui.QSizePolicy.Expanding, QtGui.QSizePolicy.Fixed)
        self._titlelabel.setContentsMargins(0, 1, 0, 0)
        message_layout.addWidget(self._titlelabel)
        self._textlabel.setSizePolicy(QtGui.QSizePolicy.Expanding, QtGui.QSizePolicy.Fixed)
        message_layout.addWidget(self._textlabel)

        self.button_layout = QHBoxLayout()
        self.button_layout.setAlignment(Qt.AlignLeft)
        message_layout.addLayout(self.button_layout)

        layout.addLayout(message_layout)
        layout.setSpacing(7)
        self.setLayout(layout)
        self.setIcon(icon)
        self.setStandardButtons(standardButtons)

    def setText(self, text):
        """
        Set the current message text.

        :type message: str
        """
        if self._text != text:
            self._text = text
            self._textlabel.setText(text)

    def text(self):
        """
        Return the current message text.

        :rtype: str
        """
        return self._text

    def setIcon(self, icon):
        """
        Set the message icon.

        :type icon: QIcon | QPixmap | QString | QStyle.StandardPixmap
        """
        if isinstance(icon, QStyle.StandardPixmap):
            icon = self.style().standardIcon(icon)
        else:
            icon = QIcon(icon)

        if self._icon != icon:
            self._icon = QIcon(icon)
            if not self._icon.isNull():
                size = self.style().pixelMetric(
                    QStyle.PM_SmallIconSize, None, self)
                pm = self._icon.pixmap(QSize(size, size))
            else:
                pm = QPixmap()

            self._iconlabel.setPixmap(pm)
            self._iconlabel.setVisible(not pm.isNull())

    def icon(self):
        """
        Return the current icon.

        :rtype: QIcon
        """
        return QIcon(self._icon)

    def setWordWrap(self, wordWrap):
        """
        Set the message text wrap property

        :type wordWrap: bool
        """
        if self._wordWrap != wordWrap:
            self._wordWrap = wordWrap
            self._textlabel.setWordWrap(wordWrap)

    def wordWrap(self):
        """
        Return the message text wrap property.

        :rtype: bool
        """
        return self._wordWrap

    def setTextFormat(self, textFormat):
        """
        Set message text format

        :type textFormat: Qt.TextFormat
        """
        self._textlabel.setTextFormat(textFormat)

    def textFormat(self):
        """
        Return the message text format.

        :rtype: Qt.TextFormat
        """
        return self._textlabel.textFormat()

    def changeEvent(self, event):
        # reimplemented
        if event.type() == 177:  # QEvent.MacSizeChange:
            ...
        super().changeEvent(event)

    def setStandardButtons(self, buttons):
        for button in NotificationMessageWidget.StandardButton:
            existing = self.button(button)
            if button & buttons and existing is None:
                self.addButton(button)
            elif existing is not None:
                self.removeButton(existing)

    def standardButtons(self):
        return functools.reduce(
            operator.ior,
            (slot.stdbutton for slot in self._buttons
             if slot.stdbutton is not None),
            MessageWidget.NoButton)

    def addButton(self, button, *rolearg):
        """
        addButton(QAbstractButton, ButtonRole)
        addButton(str, ButtonRole)
        addButton(StandardButton)

        Add and return a button
        """
        stdbutton = None
        if isinstance(button, QAbstractButton):
            if len(rolearg) != 1:
                raise TypeError("Wrong number of arguments for "
                                "addButton(QAbstractButton, role)")
            role = rolearg[0]
        elif isinstance(button, NotificationMessageWidget.StandardButton):
            if len(rolearg) != 0:
                raise TypeError("Wrong number of arguments for "
                                "addButton(StandardButton)")
            stdbutton = button
            if button == NotificationMessageWidget.Ok:
                role = NotificationMessageWidget.AcceptRole
                button = QPushButton(self._acceptLabel, default=False, autoDefault=False)
            elif button == NotificationMessageWidget.Close:
                role = NotificationMessageWidget.RejectRole
                button = QPushButton(self._rejectLabel, default=False, autoDefault=False)
        elif isinstance(button, str):
            if len(rolearg) != 1:
                raise TypeError("Wrong number of arguments for "
                                "addButton(str, ButtonRole)")
            role = rolearg[0]
            button = QPushButton(button, default=False, autoDefault=False)

        if sys.platform == "darwin":
            button.setAttribute(Qt.WA_MacSmallSize)

        self._buttons.append(NotificationMessageWidget._Button(button, role, stdbutton))
        button.clicked.connect(self._button_clicked)
        self._relayout()

        return button

    def _relayout(self):
        for slot in self._buttons:
            self.button_layout.removeWidget(slot.button)
        order = {
            NotificationWidget.AcceptRole: 0,
            NotificationWidget.RejectRole: 1,
        }
        ordered = sorted([b for b in self._buttons if
                          self.buttonRole(b) != NotificationMessageWidget.DismissRole],
                         key=lambda slot: order.get(slot.role, -1))

        prev = self._textlabel
        for slot in ordered:
            self.button_layout.addWidget(slot.button)
            QWidget.setTabOrder(prev, slot.button)

    def removeButton(self, button):
        """
        Remove a `button`.

        :type button: QAbstractButton
        """
        slot = [s for s in self._buttons if s.button is button]
        if slot:
            slot = slot[0]
            self._buttons.remove(slot)
            self.layout().removeWidget(slot.button)
            slot.button.setParent(None)

    def buttonRole(self, button):
        """
        Return the ButtonRole for button

        :type button: QAbstractButton
        """
        for slot in self._buttons:
            if slot.button is button:
                return slot.role
        else:
            return MessageWidget.InvalidRole

    def button(self, standardButton):
        """
        Return the button for the StandardButton.

        :type standardButton: StandardButton
        """
        for slot in self._buttons:
            if slot.stdbutton == standardButton:
                return slot.button
        else:
            return None

    def _button_clicked(self):
        button = self.sender()
        role = self.buttonRole(button)
        self.clicked.emit(button)

        if role == MessageWidget.AcceptRole:
            self.accepted.emit()
            self.close()
        elif role == MessageWidget.RejectRole:
            self.rejected.emit()
            self.close()


def proxydoc(func):
    return functools.wraps(func, assigned=["__doc__"], updated=[])


class NotificationWidget(OverlayWidget):
    #: Emitted when a button with an Accept role is clicked
    accepted = Signal()
    #: Emitted when a button with a Reject role is clicked
    rejected = Signal()
    #: Emitted when a button with a Dismiss role is clicked
    dismissed = Signal()
    #: Emitted when a button is clicked
    clicked = Signal(QAbstractButton)

    NoButton, Ok, Close = list(NotificationMessageWidget.StandardButton)
    InvalidRole, AcceptRole, RejectRole, DismissRole = \
        list(NotificationMessageWidget.ButtonRole)

    # first element is currently displayed
    notification_queue = []

    def __init__(self, parent=None, title="", text="", icon=QIcon(),
                 alignment=Qt.AlignRight | Qt.AlignBottom, wordWrap=True,
                 standardButtons=NoButton, acceptLabel="Ok", rejectLabel="No", **kwargs):
        super().__init__(parent, alignment=alignment, **kwargs)
        self._margin = 10  # used in stylesheet and for dismiss button

        layout = QHBoxLayout()
        layout.setContentsMargins(6, 6, 6, 6)

        self.setStyleSheet("""
                            NotificationWidget {
                                margin: """ + str(self._margin) + """px;
                                background: #626262;
                                border: 1px solid #999999;
                                border-radius: 8px;
                            }
                            NotificationWidget QLabel#text-label {
                                color: white;
                            }
                            NotificationWidget QLabel#title-label {
                                color: white;
                                font-weight: bold;
                            }""")

        self._msgwidget = NotificationMessageWidget(
            parent=self, title=title, text=text, icon=icon, wordWrap=wordWrap,
            standardButtons=standardButtons, acceptLabel=acceptLabel, rejectLabel=rejectLabel
        )
        self._msgwidget.accepted.connect(self.accepted)
        self._msgwidget.rejected.connect(self.rejected)
        self._msgwidget.clicked.connect(self.clicked)

        self._dismiss_button = SimpleButton(parent=self,
                                            icon=QIcon(self.style().standardIcon(
                                                QStyle.SP_TitleBarCloseButton)))
        self._dismiss_button.setFixedSize(18, 18)
        self._dismiss_button.clicked.connect(self.dismissed)

        def dismiss_handler():
            self.clicked.emit(self._dismiss_button)
        self._dismiss_button.clicked.connect(dismiss_handler)

        layout.addWidget(self._msgwidget)
        self.setLayout(layout)

        self.clicked.connect(self._next_notif)

        self.setFixedWidth(400)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        corner_margin = 6
        x = self.width() - self._dismiss_button.width() - self._margin - corner_margin
        y = self._margin + corner_margin
        self._dismiss_button.move(x, y)

    def show(self):
        if self in self.notification_queue:
            return
        self.notification_queue.append(self)
        # if only notification, display
        if len(self.notification_queue) == 1:
            super().show()

    def display(self):
        super().show()

    @staticmethod
    def _next_notif():
        q = NotificationWidget.notification_queue
        current = q.pop()
        current.hide()
        if q:
            notif = q[0]
            notif.display()

    @proxydoc(MessageWidget.setText)
    def setText(self, text):
        self._msgwidget.setText(text)

    @proxydoc(MessageWidget.text)
    def text(self):
        return self._msgwidget.text()

    @proxydoc(MessageWidget.setIcon)
    def setIcon(self, icon):
        self._msgwidget.setIcon(icon)

    @proxydoc(MessageWidget.icon)
    def icon(self):
        return self._msgwidget.icon()

    @proxydoc(MessageWidget.textFormat)
    def textFromat(self):
        return self._msgwidget.textFormat()

    @proxydoc(MessageWidget.setTextFormat)
    def setTextFormat(self, textFormat):
        self._msgwidget.setTextFormat(textFormat)

    @proxydoc(MessageWidget.setStandardButtons)
    def setStandardButtons(self, buttons):
        self._msgwidget.setStandardButtons(buttons)

    @proxydoc(MessageWidget.addButton)
    def addButton(self, *args):
        return self._msgwidget.addButton(*args)

    @proxydoc(MessageWidget.removeButton)
    def removeButton(self, button):
        self._msgwidget.removeButton(button)

    @proxydoc(MessageWidget.buttonRole)
    def buttonRole(self, button):
        return self._msgwidget.buttonRole(button)

    @proxydoc(MessageWidget.button)
    def button(self, standardButton):
        return self._msgwidget.button(standardButton)
