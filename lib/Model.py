##############################################################################
# Package: ormpy
# File:    Model.py
# Author:  Matthew Nizol
##############################################################################

""" Model.py provides a class to store a simplified ORM model
    consisting of a set of object types, a set of fact types, and a set of
    constraints.
"""

from lib.ObjectType import ObjectTypeSet
from lib.FactType import FactTypeSet
from lib.Constraint import ConstraintSet

class Model(object):
    """ Simplified representation of an ORM model. """

    def __init__(self):
        #: The set of object types in the model
        #: (:class:`lib.ObjectType.ObjectTypeSet`)
        self.object_types = ObjectTypeSet()

        #: The set of fact types in the model
        #: (:class:`lib.FactType.FactTypeSet`)
        self.fact_types = FactTypeSet()

        #: The set of constraints in the model
        #: (:class:`lib.Constraint.ConstraintSet`)
        self.constraints = ConstraintSet()


    def display(self):
        """ Prints the model to stdout. """
        self.object_types.display()
        self.fact_types.display()
        self.constraints.display()


