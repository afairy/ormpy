##############################################################################
# Package: ormpy
# File:    LogiQL.py
# Author:  Matthew Nizol
##############################################################################

""" This module provides a class to generate a LogiQL workspace from an OrmPy
    Population object.
"""

import os
import platform
import logging
import textwrap
import subprocess

from lib.Constraint import *
from lib.ObjectType import ObjectType
from lib.FactType import FactType, Role
from lib.SubtypeGraph import SubtypeGraph

class LogiQL(object):
    """ Generate a LogiQL workspace from an OrmPy Population. """

    def __init__(self, model=None, population=None, dirname=None, make=True, 
                 *args, **kwargs):
        super(LogiQL, self).__init__(*args, **kwargs)

        # Important: use list() constructor here so we create new list objects
        self.object_types = list(model.object_types)
        self.fact_types = list(model.fact_types)
        self.constraints = list(model.constraints)

        if population: # Drop ignored constraints
            self._remove_ignored_constraints(population) 

        self.type_graph = SubtypeGraph(model=model)
        self.projname = os.path.basename(dirname)
        self.logger = logging.getLogger(__name__)

        # Set up important paths
        self.rootdir = dirname
        self.importdir = os.path.join(dirname, "import")
        self.logicdir = os.path.join(dirname, "model")

        # Create workspace        
        self._create_logiql_workspace(population, make)        

    def _remove_ignored_constraints(self, population):
        """ Remove constraints that were ignored during ORM- calculations. """

        ignored = {cons.name for cons in population._model.ignored}
        to_delete = {cons for cons in self.constraints if cons.name in ignored}

        for cons in to_delete:
            self.constraints.remove(cons) 

    def _create_logiql_workspace(self, population, make):
        """ Write logiql files to output directories. """
        self._create_output_directories()

        self._write_project_files(import_logic=population is not None)
        self._write_types()
        self._write_predicates()
        self._write_constraints() 

        if population:       
            self._write_import_logic()
            population.write_csv(self.importdir)       
            if make: self._build_workspace()

    def _create_output_directories(self):
        """ Create output directories. """
        self._create_directory(self.rootdir)
        self._create_directory(self.importdir)
        self._create_directory(self.logicdir)

    def _create_directory(self, dirname):
        """ Create output directory if it doesn't exist. """
 
        # See http://stackoverflow.com/a/14364249
        try: 
            os.makedirs(dirname)
        except OSError:
            if not os.path.isdir(dirname): raise    

    def _write_project_files(self, import_logic=True):
        """ Write LogiBlox project files. """

        # .project file
        basename = self.projname
        filename = os.path.join(self.rootdir, basename + ".project")

        with open(filename, 'w') as out:
            out.write(basename + ", projectname\n")
            out.write("model, module\n")
            if import_logic: out.write("import.logic, execute\n")             

        # config.py file
        filename = os.path.join(self.rootdir, "config.py")

        config_contents = """\
            from lbconfig.api import *
            lbconfig_package('{0}', version='0.1', default_targets=['lb-libraries'])
            depends_on(logicblox_dep)
            lb_library(name='{0}', srcdir='.')
            check_lb_workspace(name='{0}', libraries=['{0}'])
            """.format(basename)

        with open(filename, 'w') as out:           
            out.write(textwrap.dedent(config_contents))

    def _write_types(self):
        """ Convert ORMMinusModel object types to LogiQL .logic file.  Note, we 
            treat everything as an entity type."""
        
        if len(self.object_types) == 0:
            return

        filename = os.path.join(self.logicdir, "types.logic")

        with open(filename, 'w') as out:
            begin_block(out, "types")
            begin_export(out) 
           
            # Write out logic for primitive object types
            for obj in filter(lambda x: x.primitive, self.object_types):
                rule = "{0}(x), {1}(x: v) -> string(v)."
                write_logic(out, rule.format(obj.name, constructor(obj)))              

            # Write out subtypes
            is_subtype = lambda x: isinstance(x, SubtypeConstraint)
            subtypes = filter(is_subtype, self.constraints)

            for cons in subtypes:
                head = cons.subtype.name
                tail = cons.supertype.name
                rule = "{0}(x) -> {1}(x)."
                write_logic(out, rule.format(head, tail))

            end_export(out, more=len(subtypes) > 0)

            if len(subtypes) > 0:
                begin_clauses(out)
                for cons in subtypes:
                    rule = "lang:entity(`{0})."
                    write_logic(out, rule.format(cons.subtype.name))
                end_clauses(out)
            
            end_block(out)

    def _write_predicates(self):
        """ Convert ORMMinusModel fact types to LogiQL .logic file. """

        if len(self.fact_types) == 0:
            return

        filename = os.path.join(self.logicdir, "predicates.logic")

        with open(filename, 'w') as out:
            begin_block(out, "predicates")
            begin_export(out)

            for pred in self.fact_types:
                args = role_names_to_csv(pred.roles)
                types = role_types_to_csv(pred.roles)
                rule = "{0}({1}) -> {2}." 
                write_logic(out, rule.format(pred.name, args, types))

            end_export(out)
            end_block(out)

    def _write_constraints(self):
        """ Convert ORMMinusModel constraints to LogiQL .logic file.  The 
            methods for each type of constraint are based upon examples at
            https://developer.logicblox.com/content/docs4/core-reference/webhelp/integrity-constraints.html. """

        if len(self.constraints) == 0:
            return

        filename = os.path.join(self.logicdir, "constraints.logic")
        
        with open(filename, 'w') as out:
            begin_block(out, "constraints")
            begin_clauses(out)

            # Dummy constraint so that clauses block is never empty
            write_comment(out, "Dummy constraint")
            write_logic(out, "string(x) -> string(x).")

            # Write implicit disjunctive mandatory constraints
            for obj in self.object_types:
                logic = self._idmc_to_logic(obj)
                if logic:
                    comment = "Implicit disjunctive mandatory constraint for {0}"
                    write_comment(out, comment.format(obj.name))
                    write_logic(out, logic)
                
            # Write logic based upon the constraint type
            # TODO: Handle all constraint types
            for cons in self.constraints:
                if isinstance(cons, SubtypeConstraint):
                    continue # Handled in types.logic
                elif isinstance(cons, MandatoryConstraint):
                    logic = self._mandatory_cons_to_logic(cons)
                elif isinstance(cons, ValueConstraint):
                    logic = self._value_cons_to_logic(cons)
                elif isinstance(cons, UniquenessConstraint):
                    logic = self._uniq_cons_to_logic(cons)
                elif isinstance(cons, SubsetConstraint):
                    logic = self._subset_cons_to_logic(cons)
                elif isinstance(cons, CardinalityConstraint):
                    logic = self._card_cons_to_logic(cons)
                else:
                    logic = None # Unhandled constraint

                if logic:
                    write_comment(out, cons.name)
                    write_logic(out, logic)
                else:
                    write_comment(out, "Not implemented: {0}".format(cons.name))
                    self._log_constraint(cons)

            end_clauses(out)
            end_block(out)

    def _idmc_to_logic(self, obj):
        """ Return LogiQL representing implicit disjunctive mandatory constraint
            for a given object type. """
        if obj.subject_to_idmc:
            head = type_name(obj)
            tail = []
            roles = sorted(obj.non_ref_roles, key=lambda x: x.fact_type.name)
            for role in roles:
                tail.append(pred_with_args(role.fact_type, [role], "x"))
            return "{0}(x) -> {1}.".format(head, '; '.join(tail))
        else:
            return None

    def _mandatory_cons_to_logic(self, cons):
        """ Return LogiQL representation of mandatory constraint.  
            If the constraint covers roles, the format is:
                 Type(x) -> Pred1(_, x); Pred2(_, x); Pred3(_, x).
            If the constraint covers subtypes, the format is:
                 Supertype(x) -> Subtype1(x); Subtype2(x); Subtype3(x). 
        """
        subtype = lambda x: isinstance(x, SubtypeConstraint)

        # Note: I wrote code for the Subtype case before I realized I hadn't
        # implemented IOR on Subtypes in NormaLoader yet.  So, I return
        # immediately here since I have no easy way to test the subtype case.
        if subtype(cons.covers[0]): 
            return None

        #if subtype(cons.covers[0]):
        #    head = type_name(cons.covers[0].supertype)
        #else:
        head = type_name(cons.covers[0].player)         
        
        tail = []
        for covered in cons.covers:
            #if subtype(covered):
            #    name = type_name(covered.subtype)
            #    tail.append("{0}(x)".format(name))
            #else:
            role = covered
            tail.append(pred_with_args(role.fact_type, [role], "x"))

        return "{0}(x) -> {1}.".format(head, '; '.join([t for t in tail]))  

    def _value_cons_to_logic(self, cons):
        """ Return LogiQL representation of value constraint. 
            If value constraint covers object type, the format is:
                Type_constructor(_: v) -> v = "val1"; v = "val2"; v = "val3".
            If value constraint covers a role, the format is:
                Pred(_, x), Type_constructor(x: v) -> v = "val1"; v = "val2".
        """
        element = cons.covers[0]
        if isinstance(element, ObjectType):
            head = "{0}(_:v)".format(constructor(element, local=False))
        else: # Covers a role
            pred = pred_with_args(element.fact_type, [element], "x")
            head = "{0}, {1}(x:v)".format(pred, constructor(element, local=False))

        domain = cons.domain.draw(cons.domain.max_size)
        tail = '; '.join(['v="{0}"'.format(v) for v in domain])

        return "{0} -> {1}.".format(head, tail)

    def _uniq_cons_to_logic(self, cons):
        """ Return LogiQL representation of uniqueness constraint. 
            If the constraint is internal and covers roles r & s, the format is:
               P(r, x, y, s), P(r, x2, y2, s) -> x=x2, y=y2.
        """
        if not cons.internal: # External uniqueness 
            result = self._materialize_join(cons.name, cons.covers)
            pred, covered, rule = result # Unpack tuple
            local = True
        else: # Internal uniqueness
            pred = cons.covers[0].fact_type  
            covered = cons.covers
            rule = ""
            local = False

        uncovered = [r for r in pred.roles if r not in covered]

        pred1 = pred_with_args(pred, default="{0}_", local=local)
        pred2 = pred_with_args(pred, uncovered, "{0}_2", default="{0}_", local=local)
        equals = ', '.join(["{0}_ = {0}_2".format(r.name) for r in uncovered])

        rule += "{0}, {1} -> {2}.".format(pred1, pred2, equals)
        return rule

    def _subset_cons_to_logic(self, cons):
        """ Return LogiQL representation of subset constraint. 
            The format, if there is not a join, is:
               Subset(_, x, y, _) -> Superset(_, _, y, _, x)
        """
        rule = ""

        # Subset role sequence
        if (hasattr(cons.subset, 'join_path') and cons.subset.join_path != None):
            result = self._materialize_join(cons.name + "_subset", cons.subset)
            pred, roles, join_rule = result # Unpack tuple
            rule += join_rule
            subset_pred = pred_with_args(pred, roles, "__index__", local=True)
        else:
            pred = cons.subset[0].fact_type
            subset_pred = pred_with_args(pred, cons.subset, "__index__")

        # Superset role sequence
        if (hasattr(cons.superset, 'join_path') and cons.superset.join_path != None):
            result = self._materialize_join(cons.name + "_superset", cons.superset)
            pred, roles, join_rule = result # Unpack tuple
            rule += join_rule
            superset_pred = pred_with_args(pred, roles, "__index__", local=True)
        else:
            pred = cons.superset[0].fact_type
            superset_pred = pred_with_args(pred, cons.superset, "__index__")

        rule += "{0} -> {1}.".format(subset_pred, superset_pred)

        # If it is also an Equality Constraint, add reverse subset constraint
        if isinstance(cons, EqualityConstraint):
            rule += "\n{0} -> {1}.".format(superset_pred, subset_pred)

        return rule

    def _card_cons_to_logic(self, cons):
        """ Return LogiQL representation of cardinality constraint. """
        
        element = cons.covers[0]        
        rule = ""

        if isinstance(element, ObjectType):            
            source = type_name(element)
        elif isinstance(element, Role) and len(cons.covers)==1:
            source = "{0}_projection".format(cons.name)
            pred = pred_with_args(element.fact_type, [element], "x")            
            rule += "{0}(x) <- {1}.\n".format(source, pred)
        else: # Unsupported
            return None
 
        head = "{0}_cardinality[] = n".format(cons.name)
        rule += "{0} <- agg<< n = count() >> {1}(_).\n".format(head, source)  

        tail = []
        for rng in cons.ranges:
            range_str = "{0} <= n".format(str(rng.lower))
            if rng.upper: 
                range_str += ", n <= {0}".format(str(rng.upper))
            tail.append("({0})".format(range_str))
                        
        rule += "{0} -> {1}.".format(head, '; '.join(tail))

        return rule

    def _materialize_join(self, suffix, role_seq):
        """ Materialize a join path.  Returns a triple consisting of the 
            join fact type (which is *not* added to the model), a list of 
            roles on the join fact type corresponding to *role_seq*, and 
            a corresponding LogiQL rule. 
        """
        JoinFact = FactType(name="JoinFact_" + suffix)
        name = {} # Mapping of roles from *role_seq* to their name in *JoinFact*
        projected = [] # List of roles in *JoinFact* corresponding to *role_seq*

        # Create dictionary FROM covered roles TO name and add roles to JoinFact
        #
        # IMPORTANT: We add covered roles to the join fact type before 
        # adding any other roles from the join path to ensure that the covered 
        # roles appear in the same order as in the constraint's "covered" list.
        for role in role_seq:
            name[role] = "{0}_{1}".format(role.fact_type.name, role.name)
            new_role = JoinFact.add_role(role.player, name[role])
            projected.append(new_role)

        # Add remaining roles in join path to join fact type
        for fact_type in role_seq.join_path.fact_types:
            for role in fact_type.roles:
                if role not in name:
                    name[role] = "{0}_{1}".format(fact_type.name, role.name)
                    JoinFact.add_role(role.player, name[role])

        # Generate role equality constraint for each join 
        joins = ["{0} = {1}".format(name[role1], name[role2]) 
                  for role1, role2 in role_seq.join_path.joins]

        # Create IDB rule for join fact type
        # See https://developer.logicblox.com/content/docs4/core-reference/webhelp/rules.html
        head = pred_with_args(JoinFact, default="{0}", local=True)        
        tail = []
        for fact_type in role_seq.join_path.fact_types:
            args = ', '.join([name[role] for role in fact_type.roles])
            tail.append("{0}({1})".format(pred_name(fact_type), args))
        rule = "{0} <- {1}.\n\n".format(head, ', '.join(tail + joins))

        return JoinFact, projected, rule

    def _write_import_logic(self):
        """ Import logic. """
        filename = os.path.join(self.rootdir, "import.logic")

        with open(filename, 'w') as out:
            for obj in self.object_types:
                self._write_type_import_logic(out, obj)
             
            for pred in self.fact_types:
                self._write_pred_import_logic(out, pred)

    def _write_type_import_logic(self, stream, obj):
        """ Write import logic for a type. """
        template =  """\
           {0}[offset] = v -> int(offset), string(v).
           lang:physical:filePath[`{0}] = "{1}".
           lang:physical:fileMode[`{0}] = "import".
           +{2}(x), +{3}(x: v) <- {0}[_] = v.
           """

        stream.write("// Import code for {0}\n".format(obj.name))

        in_name = "_import_types_" + obj.name
        csv_name = os.path.join(self.importdir, obj.fullname + '.csv')
        entity_name = type_name(obj)
        constr_name = constructor(self.type_graph.root_of[obj], local=False)

        text = template.format(in_name, csv_name, entity_name, constr_name)
        stream.write(textwrap.dedent(text))
        stream.write("\n")

    def _write_pred_import_logic(self, stream, pred):
        """ Write import logic for a predicate. """

        template = """\
            {0}(offset; {1}) -> int(offset), {2}.
            lang:physical:filePath[`{0}] = "{3}".
            lang:physical:fileMode[`{0}] = "import".
            lang:physical:columnNames[`{0}] = "{1}".
            +{4} <- {0}(_; {1}), {5}.
            """

        # LogicBlox gives a warning if we use semi-colon syntax for unaries.
        template_unary = """\
            {0}[offset] = {1} -> int(offset), {2}.
            lang:physical:filePath[`{0}] = "{3}".
            lang:physical:fileMode[`{0}] = "import".
            lang:physical:columnNames[`{0}] = "{1}".
            +{4} <- {0}[_] = {1}, {5}.
            """

        stream.write("// Import code for {0}\n".format(pred.name))

        in_name = "_import_predicates_" + pred.name
        in_args = role_names_to_csv(pred.roles)
        in_types = role_names_to_csv(pred.roles, template="string({0})")

        csv_name = os.path.join(self.importdir, pred.fullname + '.csv')

        out_pred = pred_with_args(pred, default="{0}_")

        out_types = []
        for r in pred.roles:
            root = constructor(self.type_graph.root_of[r.player], local=False)
            root_format = "{0}({1}_ : {1})".format(root, r.name)
            type_format = "{0}({1}_)".format(type_name(r.player), r.name)
            out_types.extend([root_format, type_format])
        out_types = ', '.join(out_types)
                       
        if pred.arity() == 1:
            text = template_unary
        else:
            text = template

        text = text.format(in_name, in_args, in_types, csv_name, out_pred, out_types)

        stream.write(textwrap.dedent(text))
        stream.write("\n")


    def _log_constraint(self, cons):
        """ Write a log message about an unimplemented constraint. """
        msg = "Constraint not implemented in LogiQL output: {0}"
        self.logger.warning(msg.format(cons.name))
        
    def _build_workspace(self):
        """ Build workspace.  Assumes a Linux environment. """

        # NOTE: I purposefully don't have unit tests for this method because
        # compiling and building a LogicBlox workspace takes > 1 second.

        if platform.system() == 'Linux':
            filename = os.path.join(self.rootdir, "build.sh")

            with open(filename, 'w') as out:
                script_contents = """\
                    #!/bin/bash
                    cd {0}
                    lb config
                    make clean
                    make 
                    make check-ws-{1} 
                    """.format(self.rootdir, self.projname)
                out.write(textwrap.dedent(script_contents))
            
            subprocess.check_call(["chmod", "+x", filename])
            subprocess.check_call([filename])
        else:
            self.logger.warning("Cannot build workspace on non-Linux platform.")
       
################################################################################
# Utility Methods
################################################################################
def constructor(entity, local=True):
    if local: return "{0}_constructor".format(entity.name)
    else: return "model:types:{0}_constructor".format(entity.name)

def begin_block(stream, block_name):
    stream.write("block(`{0}) {{\n".format(block_name))

def end_block(stream):
    stream.write("} <-- .\n")

def begin_export(stream):
    stream.write("  export(`{\n") 

def end_export(stream, more=False):
    if more:
        stream.write("  }),\n")
    else:
        stream.write("  })\n")

def begin_clauses(stream):
    stream.write("  clauses(`{\n") 

def end_clauses(stream):
    stream.write("  })\n")

def write_comment(stream, comment):
    stream.write("    // {0}\n".format(comment))

def write_logic(stream, logic):
    logic = logic.replace('\n', '\n' + (4 * ' ')) # Indent multi-line logic
    stream.write("    {0}\n\n".format(logic))

def type_name(obj_type):
    return "model:types:{0}".format(obj_type.name)

def pred_name(pred, local=False):
    if local:
        return pred.name
    else:
        return "model:predicates:{0}".format(pred.name)

def pred_with_args(pred, roles1=None, template1="{0}", 
                   roles2=None, template2="{0}", default="_", local=False):
    """ Returns formatted predicate name with arguments (e.g. "P(r1, _, r3)") 
        * pred is a fact_type object.  
        * roles1 is a list containing a subset of the roles in pred
        * template1 is applied to a role's name if it is in the roles1 list
        * roles2 is a list containing a subset of the roles in pred
        * template2 is applied to a role's name if it is in the roles2 list
        * If a role is in neither roles1 nor roles2, the default format is used
    """
    args = []
    
    for role in pred.roles:
        if roles1 and role in roles1: 
            template = template1  
            if template == '__index__': template = "_" + str(roles1.index(role))
        elif roles2 and role in roles2: 
            template = template2
            if template == '__index__': template = "_" + str(roles2.index(role))
        else: 
            template = default

        if "{0}" in template:
            args.append(template.format(role.name))
        else:
            args.append(template)
            
    return "{0}({1})".format(pred_name(pred, local), ', '.join(args))

def role_names_to_csv(roles, template="{0}"):
    return ', '.join([template.format(r.name) for r in roles])

def role_types_to_csv(roles, template="model:types:{0}({1})"):
    return ', '.join([template.format(r.player.name, r.name) for r in roles])

