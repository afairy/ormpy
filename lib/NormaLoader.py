##############################################################################
# Package: ormpy
# File:    NormaLoader.py
# Author:  Matthew Nizol
##############################################################################

""" Module for importing .orm files produced by the NORMA_ modeling tool,
    which is a plugin for Visual Studio.

    .. _NORMA: http://sourceforge.net/projects/orm

    NormaLoader.py has been tested on the .orm file format that utilizes the
    following namespaces:

    * ormRoot: http://schemas.neumont.edu/ORM/2006-04/ORMRoot 
    * orm: http://schemas.neumont.edu/ORM/2006-04/ORMCore

    NormaLoader intentionally ignores much of the .orm file structure when
    loading the file into a :class:`lib.Model.Model` object (much of the .orm
    file is not relevant to the analyses performed by ORMPY).  All information
    outside of the <orm:ORMModel> node is ignored, which includes things
    like diagram (shape) data and extensions.  NormaLoader also ignores the 
    following (not necessarily exhaustive) list of items:

    * Sample (instance) data
    * Model elements not explicitly modeled by the modeler (implicit elements)
    * Model errors reported by NORMA
    * Informal model notes
    * Multiple readings for a fact type
    * Derivation rules for subtypes, fact types, and roles
    * Constraints outside the scope of ORM-- or its extensions

    A list of important model elements (such as derivations 
    and constraints) that are ignored by NormaLoader is contained in the
    *omissions* attribute after loading the input file.
"""

import xml.etree.cElementTree as xml
from datetime import datetime, date, time

from lib.Model import Model
import lib.ObjectType as ObjectType
import lib.FactType as FactType
import lib.Constraint as Constraint

class NormaLoader(object):
    """ Loads an .orm file produced by the NORMA modeling tool into a
        :class:`lib.Model.Model`.  There are no public methods in this class.  
        An .orm file can be loaded via the constructor.  For example: :: 
 
            loader = NormaLoader("/path/to/file/example.orm")
            model = loader.model     
    """

    ###########################################################################
    # Constructor: Only public method!
    ###########################################################################
    def __init__(self, filename):
        """ Initialize object and load *filename*. """
        
        # Public attributes

        #: The ORM model (:class:`lib.Model.Model`) loaded from the .orm file.
        self.model = Model() 

        #: List of items in the .orm file omitted by the NormaLoader
        self.omissions = []  

        # Private attributes

        # NORMA namespace constants.  If the .ORM file is based on updated
        # namespaces, we will not load it.
        self._ns_root = "{http://schemas.neumont.edu/ORM/2006-04/ORMRoot}"
        self._ns_core = "{http://schemas.neumont.edu/ORM/2006-04/ORMCore}"

        self._elements = {}   # Dictionary of {id, element} pairs 
    
        self._loader = {}
        self._data_types = {}

        # Executable part of constructor: build mappings and load file
        self._build_mappings()
        self._load(filename)
    
    ###########################################################################
    # Private Utility Functions
    ###########################################################################
    def _build_mappings(self):
        """ Build mappings used by instances of the class.
        """
        # Mapping from XML node tag to loader functions
        self._loader = {
            'EntityType'            : self._load_entity_type,
            'ValueType'             : self._load_value_type,
            'ObjectifiedType'       : self._load_objectified_type,
            'NestedPredicate'       : self._load_nested_fact_type,
            'SubtypeDerivationRule' : self._load_subtype_derivation,
            'PreferredIdentifier'   : self._load_preffered_identifier,
            'ConceptualDataType'    : self._load_conceptual_data_type,
            'ValueRestriction'      : self._load_child_nodes,
            'ValueConstraint'       : self._load_value_restriction,
            'RoleValueConstraint'   : self._load_value_restriction,
            'Fact'                  : self._load_fact,
            'FactRoles'             : self._load_child_nodes,
            'Role'                  : self._load_role,
            'RolePlayer'            : self._load_role_player,
            'DerivationRule'        : self._load_facttype_derivation,
            'DerivationSource'      : self._load_role_derivation,
            'SubtypeFact'           : self._load_subtype_fact,
            'EqualityConstraint'    : self._load_equality_constraint,     
            'ExclusionConstraint'   : self._load_exclusion_constraint,   
            'SubsetConstraint'      : self._load_subset_constraint, 
            'FrequencyConstraint'   : self._load_frequency_constraint,
            'MandatoryConstraint'   : self._load_mandatory_constraint,
            'UniquenessConstraint'  : self._load_uniqueness_constraint,
            'RingConstraint'        : self._load_ring_constraint             
        }

        # Mapping from XML types defined in ORMCode namespace to Python types
        self._data_types = {
            "UnspecifiedDataType"                         : int,
            "FixedLengthTextDataType"                     : str,
            "VariableLengthTextDataType"                  : str,
            "LargeLengthTextDataType"                     : str,
            "SignedIntegerNumericDataType"                : int,
            "SignedSmallIntegerNumericDataType"           : int,
            "SignedLargeIntegerNumericDataType"           : int,
            "UnsignedIntegerNumericDataType"              : int,
            "UnsignedTinyIntegerNumericDataType"          : int,
            "UnsignedSmallIntegerNumericDataType"         : int,
            "UnsignedLargeIntegerNumericDataType"         : int,
            "AutoCounterNumericDataType"                  : int,
            "FloatingPointNumericDataType"                : float,
            "SinglePrecisionFloatingPointNumericDataType" : float,
            "DoublePrecisionFloatingPointNumericDataType" : float,
            "DecimalNumericDataType"                      : float,
            "MoneyNumericDataType"                        : float,
            "FixedLengthRawDataDataType"                  : str,
            "VariableLengthRawDataDataType"               : str,
            "LargeLengthRawDataDataType"                  : str,
            "PictureRawDataDataType"                      : str,
            "OleObjectRawDataDataType"                    : str,
            "AutoTimestampTemporalDataType"               : self._datetime,
            "TimeTemporalDataType"                        : time,
            "DateTemporalDataType"                        : self._date,
            "DateAndTimeTemporalDataType"                 : self._datetime,
            "TrueOrFalseLogicalDataType"                  : bool,
            "YesOrNoLogicalDataType"                      : bool,
            "RowIdOtherDataType"                          : int,
            "ObjectIdOtherDataType"                       : int
        }

    @staticmethod
    def _date():
        """ Return default date.  The constructor for date() requires 
            year, month, and day and so we cannot simply pass the name
            of the class to self._data_types.  """
        return date(1900, 1, 1)

    @staticmethod
    def _datetime():
        """ Return default datetime. The constructor for datetime() 
            requires year, month, and day and so we cannot simply pass
            the name of the class to self._data_types.  """
        return datetime(1900, 1, 1)

    def _add(self, model_element):
        """ Add model element to appropriate part of the model. """
        # Add to the elements dictionary by uid
        self._elements[model_element.uid] = model_element

        # Add to the appropriate set in the model
        if isinstance(model_element, ObjectType.ObjectType):
            self.model.object_types.add(model_element)
        elif isinstance(model_element, FactType.FactType):
            self.model.fact_types.add(model_element)
        elif isinstance(model_element, Constraint.Constraint):
            self.model.constraints.add(model_element)
        else: 
            raise Exception("Unexpected model element type")

    @staticmethod
    def _construct(xml_node, model_element_type):
        """ Construct a new model element from the XML node. """
        uid = xml_node.get("id")
        name = xml_node.get("Name")

        if name is None: # Some nodes use "_Name" instead
            name = xml_node.get("_Name") 

        return model_element_type(uid=uid, name=name)


    def _load(self, filename):
        """ Loads the .orm file named *filename* into *self.model* """
        root = self._parse_norma_file(filename)
        self._load_data_types(root)
        self._load_object_types(root)
        self._load_fact_types(root)
        self._load_constraints(root)

    def _parse_norma_file(self, filename):
        """ Parse a NORMA File and return the ORMModel node. """
        if filename.split(".")[-1].upper() != "ORM":
            raise Exception("Input filename must have .orm extension.")

        tree = xml.parse(filename)
        root = tree.getroot()

        if root.tag != self._ns_root + "ORM2":
            raise Exception("Root of input file must be <ormRoot:ORM2>.")

        model_node = root.find(self._ns_core + "ORMModel")

        if model_node is None:
            raise Exception("Cannot find <orm:ORMModel> in input file.")
        else:
            return model_node

    def _load_data_types(self, parent):
        """ Load the data types in the model so that we can assign the
            conceptual data type to each value type. """

        data_type_node = parent.find(self._ns_core + "DataTypes")
        if data_type_node:
            for child in data_type_node:
                data_type = self._local_tag(child) # Data type node tag
                data_id = child.get("id")

                # Look-up Python data type
                try:
                    python_type = self._data_types[data_type]()
                except KeyError:
                    python_type = int() # Default to int

                # Store type by ID for later retrieval
                self._elements[data_id] = python_type
            

    def _load_child_nodes(self, parent, target):
        """ Call the loader function associated with each child node of the 
            *parent* node.  *target* is the object into which the XML data
            will be loaded.
        """
        if parent is None:
            return

        for child in parent:
            tag = self._local_tag(child) # Get current node's tag

            try:
                self._loader[tag](child, target) # Call loader function
            except KeyError:
                pass # No loading function defined.


    def _local_tag(self, xml_node):
        """ Strips namespace from a node's tag. """
        return xml_node.tag.replace(self._ns_core, "")

    ##########################################################################
    # Private Functions to Load Object Types
    ##########################################################################
    def _load_object_types(self, xml_node):
        """ Load the collection of object types. """
        object_types_node = xml_node.find(self._ns_core + "Objects")
        self._load_child_nodes(object_types_node, self.model)

    def _load_entity_type(self, xml_node, target):
        """ Loads an entity type rooted at xml_node """
        self._load_object_type(xml_node, ObjectType.EntityType)

    def _load_value_type(self, xml_node, target):
        """ Loads a value type rooted at xml_node """
        self._load_object_type(xml_node, ObjectType.ValueType)

    def _load_objectified_type(self, xml_node, target):
        """ Loads an objectified type rooted at xml_node """
        self._load_object_type(xml_node, ObjectType.ObjectifiedType)

    def _load_object_type(self, xml_node, target_type):
        """ Loads object type rooted at xml_node into target type. """ 

        # Construct object type of appropriate underlying type
        object_type = self._construct(xml_node, target_type)

        object_type.independent = (xml_node.get("IsIndependent") == "true")
        object_type.implicit = (xml_node.get("IsImplicitBooleanValue") == "true")

        # Load inner xml nodes.  Note, some of these may also set implicit=true
        self._load_child_nodes(xml_node, object_type) 

        # Add object type the model, unless it is an implicit object type
        if not object_type.implicit:
            self._add(object_type)

    @staticmethod
    def _load_nested_fact_type(xml_node, object_type):
        """ Loads NestedPredicate xml_node into object_type. """
        if xml_node.get("IsImplied") == "true":
            object_type.implicit = True 
        object_type.nested_fact_type = xml_node.get("ref") # GUID of fact type

    def _load_subtype_derivation(self, xml_node, object_type):
        """ Loads SubtypeDerivationRule into object_type. """
        self.omissions.append("Subtype derivation rule for " + object_type.name)

    @staticmethod
    def _load_preffered_identifier(xml_node, object_type):
        """ Loads PreferredIdentifier into object_type. """
        # GUID for uniq constraint corresponding to preferred reference scheme
        object_type.identifying_constraint = xml_node.get("ref")  
        
    def _load_conceptual_data_type(self, xml_node, object_type):
        """ Load ConceptualDataType for a ValueType. """
        ref = xml_node.get("ref")  # GUID for data type

        try: # Look-up pre-loaded data type
            object_type.data_type = self._elements[ref] 
        except KeyError:
            object_type.data_type = int() # Default to int

        object_type.data_type_scale = xml_node.get("Scale")
        object_type.data_type_length = xml_node.get("Length")

    def _load_value_restriction(self, xml_node, object_type):
        """ Load value constraint on value type. """
        cons = self._construct(xml_node, Constraint.ValueConstraint)
        cons.cover(object_type)
        
        for value_range in xml_node.find(self._ns_core + "ValueRanges"):
            cons.add_range(
                min_value = value_range.get("MinValue"),
                max_value = value_range.get("MaxValue"),
                min_open = (value_range.get("MinInclusion") == "Open"),
                max_open = (value_range.get("MaxInclusion") == "Open")
            )           

        self._add(cons) # Add constraint to model
    
    ##########################################################################
    # Private Functions to Load Fact Types
    ##########################################################################
    def _load_fact_types(self, xml_node):
        """ Load the collection of fact types. """
        fact_types_node = xml_node.find(self._ns_core + "Facts")
        self._load_child_nodes(fact_types_node, self.model)

    def _load_fact(self, xml_node, fact_type_set):
        """ Load a fact node into a fact type in the model. """
        fact_type = self._construct(xml_node, FactType.FactType)
        self._load_child_nodes(xml_node, fact_type)

        # If no roles are added, it must be an entirely implicit fact type:
        if fact_type.arity() > 0:
            self._add(fact_type)

    def _load_facttype_derivation(self, xml_node, fact_type):
        """ Load a fact type derivation rule. """
        self.omissions.append("Fact type derivation rule for " + fact_type.name)

    def _load_role(self, xml_node, fact_type):
        """ Load a role in a fact type. """
        role = self._construct(xml_node, FactType.Role)
        role.fact_type = fact_type

        self._load_child_nodes(xml_node, role)

        # Only add role if the role player exists (i.e. if it was an implicit
        # object type, we do not want the associated role).  For example,
        # NORMA binarizes unary roles; this check reverts the fact type to
        # unary.
        if role.player:
            fact_type.add(role)

    def _load_role_player(self, xml_node, role):
        """ Add the role player to the role. """
        uid = xml_node.get("ref")

        try:
            object_type = self._elements[uid]
        except KeyError:
            object_type = None  # Object type must have been implicit.

        role.player = object_type

    def _load_role_derivation(self, xml_node, role):
        """ Load a role derivation rule. """
        name = role.fact_type.name
        self.omissions.append("Role derivation rule within " + name)
        

    def _load_subtype_fact(self, xml_node, fact_type_set):
        """ Load a subtype fact, which indicates a subtype constraint. """
        cons = self._construct(xml_node, Constraint.SubtypeConstraint)
        
        # Get super and sub type XML nodes
        supertype_node = xml_node.find(self._ns_core + "FactRoles/" + 
            self._ns_core + "SupertypeMetaRole/" + 
            self._ns_core + "RolePlayer")
        subtype_node = xml_node.find(self._ns_core + "FactRoles/" +
            self._ns_core + "SubtypeMetaRole/" +
            self._ns_core + "RolePlayer")

        # Look-up the corresponding object types
        try:
            cons.supertype = self._elements[supertype_node.get("ref")]
            cons.subtype = self._elements[subtype_node.get("ref")]
        except KeyError:
            raise Exception("Cannot load subtype constraint.")

        cons.cover(cons.subtype) # Constraint only constrains subtype

        # Does this subtype constraint provide a path to the preferred ID?
        pref = (xml_node.get("PreferredIdentificationPath") == "true")
        cons.preferred_id = pref

        self._add(cons) # Add subtype constraint to model

    ##########################################################################
    # Private Functions to Load Constraints
    ##########################################################################
    def _load_constraints(self, xml_node):
        """ Load the collection of contraints. """
        constraints_node = xml_node.find(self._ns_core + "Constraints")
        self._load_child_nodes(constraints_node, self.model)

    def _load_equality_constraint(self, xml_node, constraint_set):
        """ Load equality constraint. """
        self.omissions.append("Equality constraint " + xml_node.get("Name"))

    def _load_exclusion_constraint(self, xml_node, constraint_set):
        """ Load exclusion constraint. """
        self.omissions.append("Exclusion constraint " + xml_node.get("Name"))
    
    def _load_subset_constraint(self, xml_node, constraint_set):
        """ Load subset constraint. """
        pass

    def _load_frequency_constraint(self, xml_node, constraint_set):
        """ Load frequency constraint. """
        pass

    def _load_mandatory_constraint(self, xml_node, constraint_set):
        """ Load mandatory constraint. """
        cons = self._construct(xml_node, Constraint.MandatoryConstraint)

        # Ignore implied mandatory (do not even add to omissions)
        if xml_node.get("IsImplied") == "true":
            return

        role_seq = xml_node.find(self._ns_core + "RoleSequence")

        # Ignore if part of exclusive-or or inclusive-or constraint
        if len(role_seq) > 1:
            self.omissions.append("Inclusive-Or constraint " + cons.name)
            return

    def _load_uniqueness_constraint(self, xml_node, constraint_set):
        """ Load uniqueness constraint. """
        pass

    def _load_ring_constraint(self, xml_node, constraint_set):
        """ Load ring constraint. """
        self.omissions.append("Ring constraint " + xml_node.get("Name"))

    def _load_constraint(self, xml_node, constraint_set):
        """ Load a constraint into the model. """
        pass      


