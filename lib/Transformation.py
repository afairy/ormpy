##############################################################################
# Package: ormpy
# File:    Transformation.py
# Author:  Matthew Nizol
##############################################################################
""" The Transformation.py module provides classes that transform a 
    :class:`lib.Model.Model` in various ways.  

    .. warning:: The transformations in this module modify the source Model
       in place.  There is currently no means to reverse a Transformation.
"""

from lib.Model import Model
from lib.Constraint import ValueConstraint, UniquenessConstraint, \
                           FrequencyConstraint, MandatoryConstraint, \
                           SubsetConstraint, EqualityConstraint
from lib.FactType import Role, FactType, RoleSequence
from lib.ObjectType import ObjectifiedType
from lib.SubtypeGraph import SubtypeGraph

import itertools

class Transformation(object):
    """ A transformation of an ORM Model. """

    def __init__(self, model=None, *args, **kwargs):
        super(Transformation, self).__init__(*args, **kwargs)

        self.model = model #: ORM model to transform

        self.removed = set() #: Set of elements removed by this transformation
        self.modified = set() #: Set of elements modified by this transformation
        self.added = set() #: Set of elements added by this transformation

    def execute(self):
        """ Execute the transformation. """
        raise NotImplementedError()

    @property
    def model_changed(self):
        """ True iff model is changed by this transformation. """
        return len(self.removed | self.modified | self.added) > 0

    def _add(self, element):
        """ Add an element to the model. """
        self.added.add(element)
        self.model.add(element)

    def _remove(self, element):
        """ Remove an element from the model. """
        self.removed.add(element)
        self.model.remove(element)

    def _modified(self, element):
        """ Tag an element as modified. The actual modification must be 
            performed external to this method.  """
        self.modified.add(element)


###############################################################################
# Value Constraint Transformation
###############################################################################
class ValueConstraintTransformation(Transformation):
    """ A transformation of an ORM model that moves, removes, and modifies
        value constraints to be consistent with ORM- rules.  Specifically, this 
        transformation affects role value constraints and subtype value
        constraints as discussed in the below subsections.

        **Role value constraints:**

        ORM- does not support role value constraints, only value
        constraints on types.  However, if the value constraint covers a 
        role for an object type that plays no other roles and either:

        1) The type is not independent (so the role is implicitly mandatory) 
        2) The role is covered by an explicit mandatory constraint

        Then the value constraint can be treated as an object type value
        constraint.  Role value constraints that meet this criteria are thus
        moved to the object type.  If the object type that meets this test is 
        *already* covered by a value constraint, then we cover that object type 
        with the intersection of the two constraints.  All other role value
        constraints are removed from the model.

        **Subtype value constraints:**

        ORM- supports at most one value constraint on a non-primitive type 
        within the same subtype graph.  Thus, this transformation updates each 
        subtype graph, retaining the value constraint (if any) on the root 
        type and retaining at most one value constraint on any subtype of the 
        root.  All other value constraints on subtypes of that root are 
        removed.  Then, the remaining subtype value constraint is updated to 
        remove any elements not in the root value constraint's domain, and the
        root value constraint is re-ordered so that the subtype value
        constraint's elements are listed first.  This latter reordering is
        necessary to ensure that the ORM- algorithm populates each subtype
        using only elements from its root type's population.
    """

    def __init__(self, subtype_graph=None, *args, **kwargs):
        super(ValueConstraintTransformation, self).__init__(*args, **kwargs)
    
        #: A :class:`lib.SubtypeGraph.SubtypeGraph` corresponding to 
        #: :attr:`self.model`.
        self.subtype_graph = subtype_graph or SubtypeGraph(self.model)

        # Dictionary to keep track of whether we've already found a value 
        # constraint for a non-primitive type in the same subtype graph
        self._graph_has_subtype_vc = {}

    def execute(self):
        """ Execute the transformation. """
        for cons in self.model.constraints.of_type(ValueConstraint):
            element = cons.covers[0]
            if isinstance(element, Role):
                self._transform_role_value_constraint(cons, element)
            elif not element.primitive:
                self._transform_subtype_value_constraint(cons, element)

        return self.model_changed

    def _transform_role_value_constraint(self, cons, role):
        obj = role.player         

        if len(obj.roles) == 1 and (role.mandatory or not obj.independent):
            self._modified(cons) # Mark as modified
            cons.rollback() # Undo side effects -- e.g. uncover role
            cons.covers = [obj] # Move constraint to object type

            # Intersect cons with any existing value constraint on object type.
            # Leave the (now extra) value constraints on the model---the domain
            # of the object type will consist of the intersection after commit()
            for cons2 in self._value_constraints(obj):
                cons.domain &= cons2.domain
            
            cons.commit() # Commit side effects
        else: # Remove all other role value constraints
            self._remove(cons)

    def _transform_subtype_value_constraint(self, cons, subtype):
        root = self.subtype_graph.root_of[subtype]
        root_value_constraints = self._value_constraints(root)
 
        if self._graph_has_subtype_vc.get(root): # Only one subtype VC permitted
            self._remove(cons)
        elif len(root_value_constraints) == 0:
            # NOTE: Requiring that the root has a value constraint if a subtype 
            # does is more restrictive than theoretically necessary.  However,  
            # it would be a bit of a challege to implement the necessary set 
            # intersection and set difference (see else clause below) if 
            # root.domain is of infinite size like IntegerDomain.
            self._remove(cons)
        else:
            assert len(root_value_constraints) == 1

            self._graph_has_subtype_vc[root] = True
            root_cons = root_value_constraints[0]

            # Lazily mark these as modified, even though it's possible the below 
            # set operations will have no effect.
            self._modified(cons)
            self._modified(root_cons)

            # Limit the subtype value constraint to those elements also in root.
            cons.rollback()
            cons.domain &= root_cons.domain  
            cons.commit() 

            # Force the root domain to begin with the subtype domain's elements.
            root_cons.rollback()
            root_only = root_cons.domain - cons.domain
            root_cons.domain = cons.domain + root_only 
            root_cons.commit()   

    @staticmethod
    def _value_constraints(object_type):
        """ Return the value constraints (if any) covering an object type. """
        vc = lambda x: isinstance(x, ValueConstraint)
        return filter(vc, object_type.covered_by)

###############################################################################
# Absorption
###############################################################################
class AbsorptionTransformation(Transformation):
    """ An absorption transformation as described by McGill et al. (2011).
        Replaces compound refererence schemes with absorption fact types. """

    def __init__(self, *args, **kwargs):
        super(AbsorptionTransformation, self).__init__(*args, **kwargs)

        # Get list of objectified fact types
        self.nested_fact_types = {obj.nested_fact_type for obj in 
            self.model.object_types if isinstance(obj, ObjectifiedType)}

    def execute(self):
        """ Execute the transformation. """
        candidates = self.model.constraints.of_type(UniquenessConstraint)

        for euc in filter(self._pattern, candidates): 
            # Name prefixes for new constraints.  self._add() will 
            # automatically assign a unique numeric suffix.
            uc_name = "Absorption_UC_for_" + euc.name
            mc_name = "Absorption_MC_for_" + euc.name

            # Get root player
            root_player = self._other_role(euc.covers[0]).player

            # Build absorption fact type
            fact_type = AbsorptionFactType(root_player, name=euc.name)

            # Cover the root role with an IUC and a mandatory constraint
            self._add(UniquenessConstraint(covers=[fact_type.root_role], name=uc_name))
            self._add(MandatoryConstraint(covers=[fact_type.root_role], name=mc_name))

            # Loop over covered roles, move to absorption fact type
            new_roles = []

            for old_role in euc.covers:
                new_role = fact_type.add_role(old_role.player)
                new_roles.append(new_role)

                old_fact_type_name = old_role.fact_type.fullname
                fact_type.fact_type_names[new_role.name] = old_fact_type_name

                if old_role.mandatory:
                    self._add(MandatoryConstraint(covers=[new_role], name=mc_name))

                # Remove original fact type from the model. Can't call 
                # self._remove here because fact_type.rollback is unimplemented
                self._remove_fact_type(old_role.fact_type) 

            self._add(UniquenessConstraint(covers=new_roles, name=uc_name,
                                           identifier_for=euc.identifier_for))
            self._add(fact_type)
            #self._remove(euc) # Removed when we remove first fact type.

        return self.model_changed

    def _pattern(self, euc):
        """ Check if euc matches absorption pattern. """

        if euc.internal:
            return False

        obj_type = None

        for role in euc.covers:
            # Covered fact type must be binary
            if role.fact_type.arity() != 2:
                return False

            # Covered roles may only be *also* covered by a mandatory constraint
            for cons in role.covered_by:
                if cons != euc and not self._simple_mandatory(cons):
                    return False

            # All other roles must be played by the same object type.
            role2 = self._other_role(role)
            obj_type = obj_type or role2.player # First player among other roles
            
            if role2.player != obj_type:
                return False

            # Other role must be covered only by simple IUC and simple mandatory
            if len(role2.covered_by) != 2:
                return False
 
            if any(filter(self._simple_iuc, role2.covered_by)) == False:
                return False

            if any(filter(self._simple_mandatory, role2.covered_by)) == False:
                return False

            # Fact type cannot be objectified
            if role.fact_type in self.nested_fact_types:
                return False                

        return True

    def _remove_fact_type(self, fact_type):
        """ Remove fact_type from self.model.

            IMPORTANT: This is implemented here rather than via a remove 
                       method of fact_type because I haven't decided how to 
                       handle fact type rollback/removal in the general case.
                       
                       Specifically, this method does not consider join paths or
                       objectifications that may be on the fact type, but since
                       (a) _pattern() forbids objectification and (b) absorption
                       assumes there are no join paths, this is OK.
        """
        for role in fact_type.roles:
            # To remove constraints, I first need to make a copy of covered_by
            map(self._remove, [cons for cons in role.covered_by])
            role.player.roles.remove(role)

        self.model.fact_types.remove(fact_type)
        self.removed.add(fact_type)

    def _simple_iuc(self, cons):
        """ Returns True if cons is a simple internal uniqueness constraint. """
        return isinstance(cons, UniquenessConstraint) and len(cons.covers) == 1

    def _simple_mandatory(self, cons):
        """ Returns True if cons is a simple mandatory constraint. """
        return isinstance(cons, MandatoryConstraint) and cons.simple

    def _other_role(self, role):
        """ Returns the other role in a binary fact type. """
        return (set(role.fact_type.roles) - set([role])).pop() 

class AbsorptionFactType(FactType):
    """ The fact type created by an absorption transformation. """

    def __init__(self, root_player=None, *args, **kwargs):
        super(AbsorptionFactType, self).__init__(*args, **kwargs)  

        #: Role played by the identified object type
        self.root_role = FactType.add_role(self, root_player)       

        #: Original fact type name for each role
        self.fact_type_names = {}  

###############################################################################
# Disjunctive Reference Transformation
###############################################################################
class DisjunctiveRefTransformation(Transformation):
    """ Sets all ref roles in a disjunctive reference scheme to mandatory,
        and removes any inclusive-or constraints on those roles.  """

    def __init__(self, *args, **kwargs):
        super(DisjunctiveRefTransformation, self).__init__(*args, **kwargs)

    def execute(self):
        """ Execute the transformation. """
        ior = lambda x: isinstance(x, MandatoryConstraint) and not x.simple

        name = "DisjunctiveRefTransformed_MC"

        for obj in self.model.object_types:
            for role in obj.ref_roles:
                if not role.mandatory:
                    self._add(MandatoryConstraint(covers=[role], name=name))

                map(self._remove, filter(ior, role.covered_by))

        return self.model_changed

###############################################################################
# Overlapping Internal Frequency Constraint (IFC) Transformation
###############################################################################
class OverlappingIFCTransformation(Transformation):
    """ Uses IFC-Strengthening transformations to remove overlapping part of 
        internal frequency constraints whereever possible.  Recall that
        internal uniqueness constraints (IUCs) are a special case of IFC. """

    def __init__(self, *args, **kwargs):
        super(OverlappingIFCTransformation, self).__init__(*args, **kwargs)

    def execute(self):
        """ Execute the transformation. """
        is_ifc = lambda x: isinstance(x, FrequencyConstraint) and x.internal

        for fact_type in self.model.fact_types:
            # Get IFCs covering this fact type
            ifc_set = {cons for role in fact_type.roles
                            for cons in role.covered_by if is_ifc(cons)}

            # Sort set so we process more restrictive constraints first
            ifc_set = sorted(ifc_set, key=lambda x: (len(x.covers), x.name))

            # Compare each pair of IFCs that cover the fact type
            for pair in itertools.combinations(ifc_set, 2):
                covers0 = set(pair[0].covers)
                covers1 = set(pair[1].covers)

                # Don't process a constraint we've already removed
                if set(pair) - set(self.model.constraints):
                    continue

                # Case 1: No overlap
                if not(covers0 & covers1):
                    continue

                # Case 2: pair[0] contains pair[1]
                elif not(covers1 - covers0):
                    self._contained_overlap(inner=pair[1], outer=pair[0])

                # Case 3: pair[1] contains pair[0]
                elif not(covers0 - covers1):
                    self._contained_overlap(inner=pair[0], outer=pair[1])

                # Case 4: Non-containing overlap
                else:
                    self._non_contained_overlap(pair)

        return self.model_changed

    def _contained_overlap(self, inner, outer):
        """ Outer constraint covers all roles covered by inner constraint. """

        # If both inner and outer constraints can be replaced by IUCs, then we
        # can just convert the inner to an IUC and remove the outer.
        if inner.min_freq == outer.min_freq == 1:
            # Save list of reference roles played by the identified type.
            try:
                ref_roles = outer.identifier_for.ref_roles
            except AttributeError:
                ref_roles = None

            self._remove(outer)

            # Preserve the set of reference roles: strengthening an IFC doesn't
            # change the nature of what is and is not a ref role.
            if ref_roles:
                outer.identifier_for.ref_roles = ref_roles

            if inner.max_freq > 1:
                inner.rollback()
                inner.max_freq = 1 # Force inner to act as IUC
                inner.commit()
                self._modified(inner)

        # If only the outer can be replaced by an IUC, then convert it and 
        # shorten it to just cover the roles not covered by the inner constraint
        elif outer.min_freq == 1:
            self._shorten(outer, inner)

    def _non_contained_overlap(self, pair):
        """ Constraints overlap but each covers at least one role not covered
            by the other constraint. """
        pair = sorted(pair, key=lambda x: (x.min_freq, x.name))
        if pair[0].min_freq > 1: # At least one must be convertible to an IUC
            return
        self._shorten(*pair)

    def _shorten(self, this, other):
        """ Shorten this constraint relative to other constraint. """
        shortlist = set(this.covers) - set(other.covers)
        if this.min_freq == 1 and shortlist:
            this.rollback()
            this.max_freq = 1
            this.covers = list(shortlist)
            this.commit()
            self._modified(this)

###############################################################################
# External Uniqueness Constraint (EUC) Strengthening Transformation
###############################################################################
class EUCStrengtheningTransformation(Transformation):
    """ Uses EUC-Strengthening transformations to remove external uniqueness 
        constraints whereever possible.  """

    def __init__(self, *args, **kwargs):
        super(EUCStrengtheningTransformation, self).__init__(*args, **kwargs)

    def execute(self):
        """ Execute the transformation. """
        is_euc = lambda x: isinstance(x, UniquenessConstraint) and not x.internal

        for euc in filter(is_euc, self.model.constraints):
            join_path = euc.covers.join_path
            name = "Strengthened_IUC_from_" + euc.name

            try:
                first_role = self._first_role(euc, join_path)
            except KeyError:
                continue # Some problem with this EUC.  Don't transform.

            # Preserve the ref roles identified by the EUC
            try:
                ref_roles = euc.identifier_for.ref_roles
            except AttributeError:
                ref_roles = None

            # Replace EUC with an internal uniqueness constraint on first_role
            self._remove(euc)

            # Restore the reference roles, because strengthening an EUC doesn't 
            # change the nature of what is and is not a reference role.
            if ref_roles:
                euc.identifier_for.ref_roles = ref_roles

            # The IUC does not become the identifying constraint because it 
            # doesn't cover all of the reference roles.
            self._add(UniquenessConstraint(covers=[first_role], name=name))

            # Cover each in-role of the join path with an internal uniqueness
            # constraint (IUC).  An in-role is the second role in a join pair.
            for join_pair in join_path.joins:
                if not join_pair[1].unique:
                    self._add(UniquenessConstraint(covers=[join_pair[1]], name=name))

        return self.model_changed

    def _first_role(self, euc, join_path):
        """ Return role covered by EUC in first fact type on join path.  Raise
            KeyError if the EUC doesn't cover a role in the first fact type. """
        if not join_path:
            raise KeyError("No join path for EUC")
        else:
            fact_roles = set(join_path.fact_types[0].roles)
            covers = set(euc.covers)
            return (covers & fact_roles).pop() # Raises KeyError if empty

###############################################################################
# Unsupported Subset Removal Transformation
###############################################################################
class UnsupportedSubsetRemoval(Transformation):
    """ A transformations that removes unsupported subset constraints. """

    def __init__(self, *args, **kwargs):
        super(UnsupportedSubsetRemoval, self).__init__(*args, **kwargs)
        self._subtype_graph = SubtypeGraph(self.model)

    def execute(self, remove_joins=True):
        """ Execute the transformation. """
        self._remove_unsupported_subsets(remove_joins)
        self._remove_subset_cycles()
        return self.model_changed

    def _remove_unsupported_subsets(self, remove_joins=True):
        """ Remove subset constraints from the model that we cannot support."""

        for cons in self.model.constraints.of_type(SubsetConstraint):   
            # Remove join subsets (materialization should have happened earlier)
            try:            
                if remove_joins and (cons.subset.join_path or cons.superset.join_path):
                    self._remove(cons)
                    continue
            except AttributeError:
                pass
            
            # Remove if cons covers same role more than once
            if len(set(cons.covers)) < len(cons.covers):
                self._remove(cons)
                continue

            # Check each pair of subset and superset roles
            for subset, superset in zip(cons.subset, cons.superset): 
                # Confirm subset role and superset role are compatible
                if not self._compatible(subset, superset):
                    self._remove(cons)
                    continue

                # If subset role is non-reference and player is subject to IDMC:
                # Strengthen role to mandatory if superset is a ref role OR 
                # played by a subtype.
                #
                # NOTE: In theory, we could relax this if the ref role / subtype
                #       role is in turn a subset of a non-ref role.
                obj = subset.player
                subject_to_idmc = obj.subject_to_idmc and \
                                  not subset.mandatory and \
                                  subset in obj.non_ref_roles
                superset_is_ref = superset in superset.player.ref_roles
                superset_is_subtype = not superset.player.primitive

                if subject_to_idmc and (superset_is_ref or superset_is_subtype):
                    #self._remove(cons)
                    self._add(MandatoryConstraint(name="subset_mc", covers=[subset]))
        
    def _remove_subset_cycles(self):
        """ Remove subset constraints that form cycles in the model.
            Credit: DFS algorithm, Cormen et al. 2003 (p. 541) """

        # Create set of roles that participate in some subset constraint
        V = {role for cons in self.model.constraints.of_type(SubsetConstraint)
                  for role in cons.covers}

        # Initially color all vertices as WHITE
        color = {role: "WHITE" for role in V}
        backedges = set()

        # Visit each unvisited (WHITE) node
        for role in V:
            if color[role] == "WHITE":
                self._visit(role, color, backedges)        

        # Remove back edges, which create cycles in subset graph
        for cons in backedges:
            self._remove(cons)

    def _visit(self, role, color, backedges):
        """ DFS visit algorithm per Cormen et al. p541 (2003). """
        color[role] = "GRAY" # Mark role as partially visited.

        for child, cons in direct_subsets(role):
            if color[child] == "GRAY": # Cycle!
                backedges.add(cons)
            elif color[child] == "WHITE": # Unvisited
                self._visit(child, color, backedges)
        
        color[role] = "BLACK" # Mark role as completely visited.

    def _compatible(self, role1, role2):
        return self._subtype_graph.compatible(role1.player, role2.player)

###############################################################################
# Tuple Subset Transformation
###############################################################################
class TupleSubsetTransformation(Transformation):
    """ Add implied simple subset (or equality) constraints for each tuple 
        subset (or equality), and strengthen roles with IUCs as needed.  """

    def __init__(self, *args, **kwargs):
        super(TupleSubsetTransformation, self).__init__(*args, **kwargs)

    def execute(self):
        """ Execute the transformation. """ 
        for cons in filter(self._tuple_subset, self.model.constraints):
            name = "Added_due_to_" + cons.name
            cons_type = type(cons) # SubsetConstraint or EqualityConstraint

            n_super_uniq = 0 # Number of superset roles covered by simple IUC

            # Loop over each pair of (subset, superset) roles
            for subset, superset in zip(cons.subset, cons.superset):
                # Add implied simple subset or equality constraint
                # TODO: Not certain this is needed. May be redundant/overkill.
                self._add(cons_type(name=name, subset=[subset], superset=[superset]))

                # For now, take easy approach and cover all subset roles with
                # simple IUC.
                if not subset.unique:
                    self._add(UniquenessConstraint(name=name, covers=[subset]))

                if superset.unique:
                    n_super_uniq += 1

            # If none of the superset roles are unique, and this is an 
            # equality constraint, strengthen the last superset role
            if n_super_uniq == 0 and isinstance(cons, EqualityConstraint):
                self._add(UniquenessConstraint(name=name, covers=[superset]))

        return self.model_changed

    @staticmethod
    def _tuple_subset(cons):
        """ Returns True iff constraint is a tuple subset. """
        return isinstance(cons, SubsetConstraint) and len(cons.subset) > 1


###############################################################################
# Root Role Transformation
###############################################################################
class RootRoleTransformation(Transformation):
    """ Add root_role attribute to each role in the model that has a root role.
        If a role has more than one root, correct this via the addition of
        SubsetConstraints. 

        IMPORTANT: We assume here that the subset graph contains no cycles.  
        More specifically, we assume that UnsupportedSubsetRemoval and 
        TupleSubsetTransformation were executed earlier. """

    def __init__(self, *args, **kwargs):
        super(RootRoleTransformation, self).__init__(*args, **kwargs)

    def execute(self):
        """ Execute the transformation.  """ 
      
        # Find current list of roots
        roots = {role for fact in self.model.fact_types
                      for role in fact.roles if is_root(role)}

        pairs = [] # Initial list of (root, subsets) pairs
        final = [] # Final list of (root, subsets) pairs

        # For each root, determine its direct and indirect subset roles
        for root in roots:
            subsets = set()
            self._get_subsets(root, subsets)  # CRITICAL: Assumes no cycles!  
            pairs.append( (root, subsets) )

        # Sort pairs list.  See _sort_key() docstring for justification.
        pairs.sort(key=self._sort_key) 

        # Correct overlap between root subsets by adding Subset Constraints
        while pairs:
            root1, subsets1 = pairs.pop()

            for pair in list(pairs):
                root2, subsets2 = pair
                if subsets1 & subsets2: # Overlap between subsets                    
                    self._add(SubsetConstraint(name="From_RootRoleTransform",
                                              subset=[root2], superset=[root1]))
                    subsets1 |= subsets2 | set([root2])
                    pairs.remove(pair)
                
            final.append( (root1, subsets1) )

        # Add an attribute to each role containing its root role
        for root, subset in final:
            for role in subset:
                role.root_role = root

        return self.model_changed

    @staticmethod
    def _sort_key(pair):
        """ Sort by whether the root player is subject to the IDMC, then by
            whether the root is non-reference, then by the size of the subset.
            In this way, we will process all non-ref, primitive, non-independent
            roots before we process anything else. """
        root = pair[0]
        obj = root.player
        subsets = pair[1]
        return (obj.subject_to_idmc, root in obj.non_ref_roles, len(subsets))

    def _get_subsets(self, role, subsets):
        """ Add all direct and indirect subset roles of *role* to subsets. """
        for child, cons in direct_subsets(role):
            subsets.add(child)
            self._get_subsets(child, subsets)        

###############################################################################
# Join Materialization
###############################################################################
class JoinMaterialization(Transformation):
    """ Transformation to convert a join path to a join fact type. """

    def __init__(self, *args, **kwargs):
        super(JoinMaterialization, self).__init__(*args, **kwargs)

    def execute(self):
        """ Execute the transformation. """

        # For now, we'll just support subset and equality constraints
        for cons in self.model.constraints.of_type(SubsetConstraint):
            if getattr(cons.subset, 'join_path', None):
                self._materialize(cons, cons.subset)
   
            if getattr(cons.superset, 'join_path', None):
                self._materialize(cons, cons.superset)                

        return self.model_changed

    def _materialize(self, cons, roleseq):
        """ Materialize the join path. """

        join_path = getattr(roleseq, 'join_path', None)

        if not join_path or len(join_path.fact_types) < 2:
            return

        joinfact = JoinFactType(name=cons.name + "_join_fact")
        
        # Initialize list of equality constraints that will cover join fact type
        eq_list = [EqualityConstraint(name="join_eq", subset=[], superset=[])]

        # Add first fact type to join fact type
        for role in join_path.fact_types[0].roles:
            new_role = joinfact.add_role(player=role.player)
            joinfact.corr[role] = new_role

            eq_list[0].subset.append(role)
            eq_list[0].superset.append(new_role)
        
        # Build out the full join fact type
        for join in join_path.joins:
            eq = EqualityConstraint(name="join_eq", subset=[], superset=[])

            for role in join[1].fact_type.roles:
                if role is join[1]:
                    new_role = joinfact.corr[join[0]]
                else:
                    new_role = joinfact.add_role(player=role.player)
                    
                joinfact.corr[role] = new_role 

                eq.subset.append(role)
                eq.superset.append(new_role)

            eq_list.append(eq)

        new_seq = [joinfact.corr[role] for role in roleseq]

        # Ensure join constraint still covers same number of roles!
        if len(set(new_seq)) != len(roleseq):
            return # We haven't changed anything yet.  BAIL OUT!

        # Update the constraint to cover join fact roles instead of orig roles
        cons.rollback()
        del roleseq[:] # Empty out the role sequence
        roleseq.extend(new_seq)
        roleseq.join_path = None # Join path is gone now

        # Cover join roles on original and join fact type with simple IUCs
        # Must be done *after* we validate new_seq length above
        for join in join_path.joins:
            self._make_unique(join[0])
            self._make_unique(join[1])
            self._make_unique(joinfact.corr[join[0]])
    
        # Commit changes
        self._add(joinfact)
        map(self._add, eq_list)
        self._modified(cons) 
        cons.commit()       

    def _make_unique(self, role):
        """ Cover role with a simple IUC if it is not already unique. """
        if not role.unique:
            self._add(UniquenessConstraint(name="join_uc", covers=[role]))        

class JoinFactType(FactType):
    """ A join fact type produced by a join materialization transformation. """

    def __init__(self, *args, **kwargs):
        super(JoinFactType, self).__init__(*args, **kwargs)
        self.corr = {} # Correlation between old roles and new roles

    def commit(self):
        """ Commit side effects. """
        for orig_role in self.corr:
            ref_roles = orig_role.player.ref_roles
            new_role = self.corr[orig_role]

            if orig_role in ref_roles and new_role not in ref_roles:
                ref_roles.append(new_role)

        FactType.commit(self)

    def rollback(self):
        """ Rollback side effects. """
        raise NotImplementedError()    

###############################################################################
# Utility Functions
###############################################################################
def subset_triples(role):
    """ Generator function that yields all triples (cons, subset role, 
        superset role) in which role plays one of the roles. """
    subset_cons = lambda x: isinstance(x, SubsetConstraint)
    for cons in filter(subset_cons, role.covered_by):
        for subset, superset in zip(cons.subset, cons.superset):
            if subset == role or superset == role:
                yield cons, subset, superset  

def direct_subsets(role):
    """ Return the list of edges (subset constraints) and nodes (roles)
        adjacent to role, where role is the superset. """
    for cons, subset, superset in subset_triples(role):
        if superset == role:
            yield subset, cons

def is_root(role):
    """ Return True iff the role is a root role. """
    for cons, subset, superset in subset_triples(role):
        if subset == role:
            return False
    return True
        
