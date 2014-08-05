##############################################################################
# Package: ormpy
# File:    FactType.py
# Author:  Matthew Nizol
##############################################################################

""" This module provides a class for ORM fact types.  
"""

from lib.ModelElement import ModelElementSet, ModelElement

class FactTypeSet(ModelElementSet):
    """ Container for a set of fact types. """

    def __init__(self):
        super(FactTypeSet, self).__init__(name="Fact Types")


class FactType(ModelElement):
    """ An ORM Fact Type. """

    def __init__(self, uid=None, name=None):
        super(FactType, self).__init__(uid=uid, name=name)
