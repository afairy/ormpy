##############################################################################
# Package: ormpy
# File:    TestNormaLoader.py
# Author:  Matthew Nizol
##############################################################################

""" This file contains unit tests for the lib.NormaLoader class """

import os
from unittest import TestCase
from datetime import datetime, date, time

from lib.NormaLoader import NormaLoader
from lib.ModelElement import ModelElement
from lib.FactType import FactType

import lib.ObjectType as ObjectType

class TestNormaLoader(TestCase):
    """ Unit tests for the NormaLoader class. """

    def setUp(self):
        self.data_dir = os.getenv("ORMPY_TEST_DATA_DIR")

    def test_bad_filename_extension(self):
        """ Confirm that exception is raised when input file has .txt extension 
            rather than .orm extension. """
        with self.assertRaises(Exception) as ex:
            NormaLoader("test.txt")
        self.assertEqual(ex.exception.message, 
            "Input filename must have .orm extension.")

    def test_bad_root_element(self):
        """ Confirm that exception is raised when the root element of the
            XML is not <ormRoot:ORM2>. """
        with self.assertRaises(Exception) as ex:
            NormaLoader(self.data_dir + "bad_root_element.orm")
        self.assertEqual(ex.exception.message, 
            "Root of input file must be <ormRoot:ORM2>.")

    def test_no_model_element(self):
        """ Confirm that exception is raised when the XML does not contain an
            ORMModel element. 
        """
        with self.assertRaises(Exception) as ex:
            NormaLoader(self.data_dir + "no_model_element.orm")
        self.assertEqual(ex.exception.message, 
            "Cannot find <orm:ORMModel> in input file.")

    def test_empty_model(self):
        """ Confirm a successful parse on a small input file. """
        model = NormaLoader(self.data_dir + "empty_model.orm").model
        self.assertEqual(model.object_types.count(), 0)
        self.assertEqual(model.fact_types.count(), 0)
        self.assertEqual(model.constraints.count(), 0)

    def test_adding_invalid_element(self):
        """ Confirm exception is raised if an invalid object is passed to
            the _add() method."""
        loader = NormaLoader(self.data_dir + "empty_model.orm")
        with self.assertRaises(Exception) as ex:
            loader._add(ModelElement(uid="123", name="ABC"))
        self.assertEqual(ex.exception.message, "Unexpected model element type")
        
    def test_subtypes(self):
        """ Confirm that subtype derivation rule omission note
            is added to self.omissions and that subtype constraints load 
            properly. """
        loader = NormaLoader(self.data_dir + "subtype_with_derivation.orm")
        model = loader.model

        self.assertItemsEqual(loader.omissions, 
            ["Subtype derivation rule for B"])

        cons1 = model.constraints.get("BIsASubtypeOfA")
        self.assertIs(cons1.subtype, model.object_types.get("B"))
        self.assertIs(cons1.supertype, model.object_types.get("A"))
        self.assertIs(cons1.covers[0], cons1.subtype)
        self.assertTrue(cons1.preferred_id)

        self.assertFalse(model.constraints.get("BIsASubtypeOfC").preferred_id)        

    def test_subtype_exception(self):
        """ Confirm subtype exception fires for corrupted data. """
        with self.assertRaises(Exception) as ex:
            loader = NormaLoader(self.data_dir + "corrupted_subtype.orm")
        self.assertEquals(ex.exception.message, 
            "Cannot load subtype constraint.")
        
    def test_load_object_types(self):
        """ Test of object type load. """
        loader = NormaLoader(self.data_dir + "object_type_tests.orm")
        model = loader.model

        # No derivation rules
        self.assertItemsEqual(loader.omissions, [])
        
        # Overall count
        self.assertEqual(model.object_types.count(), 10)

        # Independent Entity
        this = model.object_types.get("D") 
        self.assertTrue(this.independent)
        self.assertEquals(this.identifying_constraint, 
            "_5D7B0A6D-EF11-43C0-9EB3-398933165BC4")
        self.assertIsInstance(this, ObjectType.EntityType)

        # Non-independent Entity
        this = model.object_types.get("C")
        self.assertFalse(this.independent)

        # Independent value
        this = model.object_types.get("V2")
        self.assertTrue(this.independent)
        self.assertEquals(this.uid, "_FD295AC2-D845-48E4-9E09-2E48EC99E3F3")
        self.assertIsInstance(this, ObjectType.ValueType)

        # Non-independent value
        this = model.object_types.get("V1")
        self.assertFalse(this.independent)

        # Implicit value (created by unary fact type): should not be loaded
        this = model.object_types.get("A exists")
        self.assertIsNone(this)

        # Objectified Independent
        this = model.object_types.get("CHasV1")
        self.assertTrue(this.independent)
        self.assertIsInstance(this, ObjectType.ObjectifiedType)

        # Objectified Non-independent
        this = model.object_types.get("V1HasV2")
        self.assertFalse(this.independent)
        self.assertEquals(this.identifying_constraint, 
            "_CC5D22B1-DBA7-4383-80F2-29CEAE58A998")
        self.assertEquals(this.nested_fact_type, 
            "_B6D10F36-FFE2-4B86-BEA4-02F7FCA655F9")

        # Implicit Objectified (Created by ternary, should not load)
        this = model.object_types.get("V1HasDHasV2") 
        self.assertIsNone(this)

    def test_data_type_load(self):
        """ Confirm data types are loaded properly for Value Types. """
        model = NormaLoader(self.data_dir + "data_types.orm").model
        ot = model.object_types

        self.assertIsInstance(ot.get("A").data_type, int) # data type undefined
        self.assertIsInstance(ot.get("B").data_type, bool)      # True or false
        self.assertIsInstance(ot.get("C").data_type, bool)      # Yes or no
        self.assertIsInstance(ot.get("D").data_type, int)       # auto counter
        self.assertIsInstance(ot.get("E").data_type, float)     # float
        self.assertIsInstance(ot.get("F").data_type, float)     # money
        self.assertIsInstance(ot.get("G").data_type, int)       # big int
        self.assertIsInstance(ot.get("H").data_type, datetime)  # timestamp
        self.assertIsInstance(ot.get("I").data_type, date)      # date
        self.assertIsInstance(ot.get("J").data_type, time)      # time
        self.assertIsInstance(ot.get("K").data_type, str)       # text

        # Confirm scale and length are read
        special = ot.get("Special")
        self.assertIsInstance(special.data_type, float)  # float
        self.assertEquals(special.data_type_scale, "35")
        self.assertEquals(special.data_type_length, "29")

    def test_unknown_data_type(self):
        """ Confirm that data type defaults to int() if the actual type 
            is unexpected. """
        model = NormaLoader(self.data_dir + "unknown_data_types.orm").model
        self.assertIsInstance(model.object_types.get("A").data_type, int)
        self.assertIsInstance(model.object_types.get("B").data_type, int)

    def test_value_constraint_on_types(self):
        """ Confirm that value constraints on value types are loaded. """
        model = NormaLoader(
            self.data_dir + "test_value_type_value_constraint.orm").model
        cons1 = model.constraints.get("ValueConstraint1")
        
        self.assertEquals(cons1.uid, "_9F61B75E-FB59-456F-97A9-E4CF104FABE5")
        self.assertIs(cons1.covers[0], model.object_types.get("A"))

        self.assertEquals(cons1.ranges[0].min_value, "1")
        self.assertEquals(cons1.ranges[0].max_value, "2")
        self.assertFalse(cons1.ranges[0].min_open)
        self.assertFalse(cons1.ranges[0].max_open)

        self.assertEquals(cons1.ranges[1].min_value, "5")
        self.assertEquals(cons1.ranges[1].max_value, "6")
        self.assertTrue(cons1.ranges[1].min_open)
        self.assertFalse(cons1.ranges[1].max_open) 

        self.assertEquals(cons1.ranges[2].min_value, "10")
        self.assertEquals(cons1.ranges[2].max_value, "20")
        self.assertFalse(cons1.ranges[2].min_open)
        self.assertTrue(cons1.ranges[2].max_open)  

        self.assertEquals(cons1.ranges[3].min_value, "100")
        self.assertEquals(cons1.ranges[3].max_value, "200")
        self.assertTrue(cons1.ranges[3].min_open)
        self.assertTrue(cons1.ranges[3].max_open) 

    def test_load_fact_types(self):
        """ Confirm fact types load successfully. """
        loader = NormaLoader(self.data_dir + "fact_type_tests.orm")
        model = loader.model

        # Confirm reference scheme fact type loads
        ftype1 = model.fact_types.get("AHasA_id")
        self.assertEquals(ftype1.uid, "_8C96FD40-5E82-4E8F-B5EE-C6CEE8BCF74B")
        self.assertIsInstance(ftype1, FactType)  

        # Confirm derivation rule added to omissions
        self.assertItemsEqual(loader.omissions, 
            ["Fact type derivation rule for AHasB",
             "Fact type derivation rule for AHasA_id"])

        # Check role player
        typea = model.object_types.get("A")
        typeb = model.object_types.get("B")
        ahasb = model.fact_types.get("AHasB")
        self.assertIs(ahasb.roles[0].player, typea)
        self.assertIs(ahasb.roles[1].player, typeb)

        # Check role fact type
        self.assertIs(ahasb.roles[0].fact_type, ahasb)
        self.assertIs(ahasb.roles[1].fact_type, ahasb)

        # Check that implicit role added to unary is removed
        aexists = model.fact_types.get("AExists")
        self.assertIs(aexists.roles[0].player, typea)
        self.assertEquals(aexists.arity(), 1)

        # Test role value constraint
        cons1 = model.constraints.get("RoleValueConstraint1")

        self.assertEquals(cons1.ranges[0].min_value, "A")
        self.assertEquals(cons1.ranges[0].max_value, "B")
        self.assertFalse(cons1.ranges[0].min_open)
        self.assertFalse(cons1.ranges[0].max_open)

        self.assertEquals(cons1.ranges[1].min_value, "C")
        self.assertEquals(cons1.ranges[1].max_value, "E")
        self.assertTrue(cons1.ranges[1].min_open)
        self.assertFalse(cons1.ranges[1].max_open) 

        self.assertEquals(cons1.ranges[2].min_value, "F")
        self.assertEquals(cons1.ranges[2].max_value, "G")
        self.assertFalse(cons1.ranges[2].min_open)
        self.assertTrue(cons1.ranges[2].max_open) 

    def test_forced_implicit(self):
        """ Exercise branch in _load_fact_types when arity() = 0. """
        loader = NormaLoader(self.data_dir + "forced_implicit_binary.orm")
        model = loader.model
        
        # The object types are both marked implicit so the corresponding
        # fact type should not load either.
        self.assertEquals(model.object_types.count(), 0)
        self.assertEquals(model.fact_types.count(), 0)
      
    def test_derivation_source(self):
        """ Confirm depricated DerivationSource element is ignored. """
        loader = NormaLoader(self.data_dir + "derivation_source.orm")
        self.assertItemsEqual(loader.omissions,
            ["Role derivation rule within AHasB"])

    def test_constraints_omitted(self):
        """ Confirm omitted constraints get saved to omissions list."""
        loader = NormaLoader(self.data_dir + "omitted_constraints.orm")
        self.assertItemsEqual(loader.omissions,
            ["Equality constraint EqualityConstraint1",
             "Exclusion constraint ExclusionConstraint1",
             "Exclusion constraint ExclusiveOrConstraint1",
             "Inclusive-Or constraint InclusiveOrConstraint1",
             "Inclusive-Or constraint InclusiveOrConstraint2",
             "Ring constraint RingConstraint1"])
  
 

        

    
        


        
        
 
        
