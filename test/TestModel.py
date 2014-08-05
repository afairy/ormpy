##############################################################################
# Package: ormpy
# File:    TestModel.py
# Author:  Matthew Nizol
##############################################################################

""" This file contains unit tests for :class:`lib.Model.Model` """

import sys
from unittest import TestCase

from lib.Model import Model
from lib.ObjectType import ObjectType
from lib.FactType import FactType
from lib.Constraint import Constraint

class TestModel(TestCase):
    """ Unit tests for the Model class. """

    def setUp(self):
        pass

    def test_display_empty(self):
        """ Test Display of an empty model. """
        model = Model()
        model.display()
        output = sys.stdout.getvalue().strip()
        self.assertEqual(output, "Object Types:\nFact Types:\nConstraints:")


    def test_display_nonempty(self):
        """ Test Display of non-empty model. """
        model = Model()
        model.object_types.add(ObjectType(name="O1"))
        model.fact_types.add(FactType(name="F1"))
        model.fact_types.add(FactType(name="F2"))
        model.constraints.add(Constraint(name="C1"))
        model.display()

        output = sys.stdout.getvalue().strip()
        self.assertEqual(output, "Object Types:\n    O1\nFact Types:\n    F1\n    F2\nConstraints:\n    C1")
