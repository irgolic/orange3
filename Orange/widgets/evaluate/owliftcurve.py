"""
Lift Curve Widget
-----------------

"""
from collections import namedtuple

import numpy as np
import sklearn.metrics as skl_metrics

from AnyQt.QtWidgets import QListView, QFrame
from AnyQt.QtGui import QColor, QPen, QPalette, QFont
from AnyQt.QtCore import Qt

import pyqtgraph as pg

import Orange
from Orange.widgets import widget, gui, settings
from Orange.widgets.evaluate.contexthandlers import \
    EvaluationResultsContextHandler
from Orange.widgets.evaluate.utils import check_results_adequacy
from Orange.widgets.utils import colorpalettes
from Orange.widgets.evaluate.owrocanalysis import convex_hull
from Orange.widgets.utils.widgetpreview import WidgetPreview
from Orange.widgets.widget import Input
from Orange.widgets import report


CurvePoints = namedtuple(
    "CurvePoints",
    ["cases", "tpr", "thresholds"]
)
CurvePoints.is_valid = property(lambda self: self.cases.size > 0)

LiftCurve = namedtuple(
    "LiftCurve",
    ["points", "hull"]
)
LiftCurve.is_valid = property(lambda self: self.points.is_valid)


def liftCurve_from_results(results, clf_index, target):
    x, y, thresholds = lift_curve_from_results(results, target, clf_index)

    points = CurvePoints(x, y, thresholds)
    hull = CurvePoints(*convex_hull([(x, y, thresholds)]))
    return LiftCurve(points, hull)


PlotCurve = namedtuple(
    "PlotCurve",
    ["curve",
     "curve_item",
     "hull_item"]
)


class OWLiftCurve(widget.OWWidget):
    name = "Lift Curve"
    description = "Construct and display a lift curve " \
                  "from the evaluation of classifiers."
    icon = "icons/LiftCurve.svg"
    priority = 1020
    keywords = []

    class Inputs:
        evaluation_results = Input("Evaluation Results", Orange.evaluation.Results)

    settingsHandler = EvaluationResultsContextHandler()
    target_index = settings.ContextSetting(0)
    selected_classifiers = settings.ContextSetting([])

    display_convex_hull = settings.Setting(False)
    display_cost_func = settings.Setting(True)

    fp_cost = settings.Setting(500)
    fn_cost = settings.Setting(500)
    target_prior = settings.Setting(50.0)

    graph_name = "plot"

    def __init__(self):
        super().__init__()

        self.results = None
        self.classifier_names = []
        self.colors = []
        self._curve_data = {}

        box = gui.vBox(self.controlArea, "Plot")
        tbox = gui.vBox(box, "Target Class")
        tbox.setFlat(True)

        self.target_cb = gui.comboBox(
            tbox, self, "target_index", callback=self._on_target_changed,
            contentsLength=8, searchable=True)

        cbox = gui.vBox(box, "Classifiers")
        cbox.setFlat(True)
        self.classifiers_list_box = gui.listBox(
            cbox, self, "selected_classifiers", "classifier_names",
            selectionMode=QListView.MultiSelection,
            callback=self._on_classifiers_changed)

        gui.checkBox(box, self, "display_convex_hull",
                     "Show lift convex hull", callback=self._replot)

        self.plotview = pg.GraphicsView(background="w")
        self.plotview.setFrameStyle(QFrame.StyledPanel)

        self.plot = pg.PlotItem(enableMenu=False)
        self.plot.setMouseEnabled(False, False)
        self.plot.hideButtons()

        pen = QPen(self.palette().color(QPalette.Text))

        tickfont = QFont(self.font())
        tickfont.setPixelSize(max(int(tickfont.pixelSize() * 2 // 3), 11))

        axis = self.plot.getAxis("bottom")
        axis.setTickFont(tickfont)
        axis.setPen(pen)
        axis.setLabel("P Rate")

        axis = self.plot.getAxis("left")
        axis.setTickFont(tickfont)
        axis.setPen(pen)
        axis.setLabel("TP Rate")

        self.plot.showGrid(True, True, alpha=0.1)
        self.plot.setRange(xRange=(0.0, 1.0), yRange=(0.0, 1.0), padding=0.05)

        self.plotview.setCentralItem(self.plot)
        self.mainArea.layout().addWidget(self.plotview)

    @Inputs.evaluation_results
    def set_results(self, results):
        """Set the input evaluation results."""
        self.closeContext()
        self.clear()
        self.results = check_results_adequacy(results, self.Error)
        if self.results is not None:
            self._initialize(results)
            self.openContext(self.results.domain.class_var,
                             self.classifier_names)
            self._setup_plot()

    def clear(self):
        """Clear the widget state."""
        self.plot.clear()
        self.results = None
        self.target_cb.clear()
        self.classifier_names = []
        self.colors = []
        self._curve_data = {}

    def _initialize(self, results):
        N = len(results.predicted)

        names = getattr(results, "learner_names", None)
        if names is None:
            names = ["#{}".format(i + 1) for i in range(N)]

        self.colors = colorpalettes.get_default_curve_colors(N)

        self.classifier_names = names
        self.selected_classifiers = list(range(N))
        for i in range(N):
            item = self.classifiers_list_box.item(i)
            item.setIcon(colorpalettes.ColorIcon(self.colors[i]))

        self.target_cb.addItems(results.data.domain.class_var.values)
        self.target_index = 0

    def plot_curves(self, target, clf_idx):
        if (target, clf_idx) not in self._curve_data:
            curve = liftCurve_from_results(self.results, clf_idx, target)
            color = self.colors[clf_idx]
            pen = QPen(color, 1)
            pen.setCosmetic(True)
            shadow_pen = QPen(pen.color().lighter(160), 2.5)
            shadow_pen.setCosmetic(True)
            item = pg.PlotDataItem(
                curve.points[0], curve.points[1],
                pen=pen, shadowPen=shadow_pen,
                symbol="+", symbolSize=3, symbolPen=shadow_pen,
                antialias=True
            )
            hull_item = pg.PlotDataItem(
                curve.hull[0], curve.hull[1],
                pen=pen, antialias=True
            )
            self._curve_data[target, clf_idx] = \
                PlotCurve(curve, item, hull_item)

        return self._curve_data[target, clf_idx]

    def _setup_plot(self):
        target = self.target_index
        selected = self.selected_classifiers
        curves = [self.plot_curves(target, clf_idx) for clf_idx in selected]

        for curve in curves:
            self.plot.addItem(curve.curve_item)

        if self.display_convex_hull:
            hull = convex_hull([c.curve.hull for c in curves])
            self.plot.plot(hull[0], hull[1], pen="y", antialias=True)

        pen = QPen(QColor(100, 100, 100, 100), 1, Qt.DashLine)
        pen.setCosmetic(True)
        self.plot.plot([0, 1], [0, 1], pen=pen, antialias=True)

        warning = ""
        if not all(c.curve.is_valid for c in curves):
            if any(c.curve.is_valid for c in curves):
                warning = "Some lift curves are undefined"
            else:
                warning = "All lift curves are undefined"

        self.warning(warning)

    def _replot(self):
        self.plot.clear()
        if self.results is not None:
            self._setup_plot()

    def _on_target_changed(self):
        self._replot()

    def _on_classifiers_changed(self):
        self._replot()

    def send_report(self):
        if self.results is None:
            return
        caption = report.list_legend(self.classifiers_list_box,
                                     self.selected_classifiers)
        self.report_items((("Target class", self.target_cb.currentText()),))
        self.report_plot()
        self.report_caption(caption)


def lift_curve_from_results(results, target, clf_idx, subset=slice(0, -1)):
    actual = results.actual[subset]
    scores = results.probabilities[clf_idx][subset][:, target]
    yrate, tpr, thresholds = lift_curve(actual, scores, target)
    return yrate, tpr, thresholds


def lift_curve(ytrue, ypred, target=1):
    P = np.sum(ytrue == target)
    N = ytrue.size - P

    if P == 0 or N == 0:
        # Undefined TP and FP rate
        return np.array([]), np.array([]), np.array([])

    fpr, tpr, thresholds = skl_metrics.roc_curve(ytrue, ypred, pos_label=target)
    rpp = fpr * (N / (P + N)) + tpr * (P / (P + N))
    return rpp, tpr, thresholds


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.evaluate.utils import results_for_preview
    WidgetPreview(OWLiftCurve).run(results_for_preview())
