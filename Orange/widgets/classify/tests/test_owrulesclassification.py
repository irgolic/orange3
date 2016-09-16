# Test methods with long descriptive names can omit docstrings
# pylint: disable=missing-docstring
from PyQt4 import QtGui

from Orange.widgets.classify.owrules import OWRuleLearner
from Orange.widgets.tests.base import (WidgetTest, WidgetLearnerTestMixin,
                                       ParameterMapping)


class TestOWRulesClassification(WidgetTest, WidgetLearnerTestMixin):
    def setUp(self):
        self.widget = self.create_widget(OWRuleLearner,
                                         stored_settings={"auto_apply": False})
        self.init()

        self.radio_button_groups = self.widget.findChildren(QtGui.QButtonGroup)
        self.radio_buttons = self.widget.findChildren(QtGui.QRadioButton)
        self.spin_boxes = self.widget.findChildren(QtGui.QSpinBox)
        self.double_spin_boxes = self.widget.findChildren(QtGui.QDoubleSpinBox)
        self.combo_boxes = self.widget.findChildren(QtGui.QComboBox)

        self.parameters = [
            ParameterMapping("Evaluation measure", self.combo_boxes[0],
                             self.widget.storage_measures),
            ParameterMapping("Beam width", self.spin_boxes[0]),
            ParameterMapping("Minimum rule coverage", self.spin_boxes[1]),
            ParameterMapping("Maximum rule length", self.spin_boxes[2]),
        ]

    def test_rule_ordering_radio_buttons(self):
        # radio buttons are visible
        self.assertFalse(self.radio_buttons[0].isHidden())
        self.assertFalse(self.radio_buttons[1].isHidden())

        # by default, "Ordered" rule ordering should be checked
        self.assertTrue(self.radio_buttons[0].isChecked())
        self.assertFalse(self.radio_buttons[1].isChecked())

        # test rule_ordering value
        self.assertEqual(self.widget.rule_ordering, 0)

        # change the selection
        self.radio_buttons[1].click()
        self.assertFalse(self.radio_buttons[0].isChecked())
        self.assertTrue(self.radio_buttons[1].isChecked())
        self.assertEqual(self.widget.rule_ordering, 1)

    def test_covering_algorithm_radio_buttons(self):
        # radio buttons are visible
        self.assertFalse(self.radio_buttons[2].isHidden())
        self.assertFalse(self.radio_buttons[3].isHidden())

        # by default, "Exclusive" covering algorithm should be checked
        self.assertTrue(self.radio_buttons[2].isChecked())
        self.assertFalse(self.radio_buttons[3].isChecked())

        # test covering_algorithm value
        self.assertEqual(self.widget.covering_algorithm, 0)

        # gamma double spin not enabled
        self.assertFalse(self.double_spin_boxes[0].isEnabled())

        # change the selection
        self.radio_buttons[3].click()
        self.assertFalse(self.radio_buttons[2].isChecked())
        self.assertTrue(self.radio_buttons[3].isChecked())
        self.assertEqual(self.widget.covering_algorithm, 1)

        # gamma double spin is now enabled
        self.assertTrue(self.double_spin_boxes[0].isEnabled())

        # test gamma default value
        self.assertEqual(self.double_spin_boxes[0].value(), self.widget.gamma)

    def test_alpha_double_spin_boxes(self):
        """
        Due to the checkbox components of the double-spin boxes,
        standard ParameterMapping cannot be used for this specific
        widget.
        """
        # double spin boxes are visible
        self.assertFalse(self.double_spin_boxes[1].box.isHidden())
        self.assertFalse(self.double_spin_boxes[2].box.isHidden())

        # double spin boxes are not enabled
        self.assertFalse(self.double_spin_boxes[1].isEnabled())
        self.assertFalse(self.double_spin_boxes[2].isEnabled())

        # click the checkboxes
        self.double_spin_boxes[1].cbox.click()
        self.double_spin_boxes[2].cbox.click()

        # double spin boxes are now enabled
        self.assertTrue(self.double_spin_boxes[1].isEnabled())
        self.assertTrue(self.double_spin_boxes[2].isEnabled())

        # test values, make sure they are correct
        self.assertEqual(self.double_spin_boxes[1].value(),
                         self.widget.default_alpha)

        self.assertEqual(self.double_spin_boxes[2].value(),
                         self.widget.parent_alpha)