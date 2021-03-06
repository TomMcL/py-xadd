from __future__ import print_function

import sympy
import pysmt.environment
import pysmt.shortcuts as smt
from pysmt.typing import INT

from pyxadd.diagram import TerminalNode, InternalNode, Diagram
from pyxadd.test import LinearTest
from pyxadd.variables import VariableFinder

"""
Reducers can exploit the fact that they do not change the relative ordering of tests.
Therefore, they can work "in place" and do not need to recontruct the diagram using multiplication and summation.
"""

class Reducer(object):
    def __init__(self, pool):
        self._pool = pool

    @property
    def pool(self):
        return self._pool

    def reduce(self, node_id, variables=None):
        raise NotImplementedError()

    def _get_variables(self, node_id):
        return VariableFinder(Diagram(self.pool, node_id)).walk()


# TODO Does it produce diagrams in correct form?
# noinspection PyPep8Naming
class LinearReduction(Reducer):
    def __init__(self, pool):
        Reducer.__init__(self, pool)
        self.variables = None

    @property
    def columns(self):
        return len(self.variables)

    def reduce(self, node_id, variables=None):
        if variables is None:
            self.variables = self._get_variables(node_id)
        else:
            self.variables = list(str(v) for v in variables)
        return self._reduce(node_id, [], [])

    def _reduce(self, node_id, coefficients, constants):
        node = self.pool.get_node(node_id)
        if isinstance(node, TerminalNode):

            return node_id
        elif isinstance(node, InternalNode):
            true_coefficients, true_constants = self._combine(coefficients, constants, node.test, True)
            if not self._is_feasible(true_coefficients, true_constants):
                # Only false branch is true
                return self._reduce(node.child_false, coefficients, constants)

            false_coefficients, false_constants = self._combine(coefficients, constants, node.test, False)
            if not self._is_feasible(false_coefficients, false_constants):
                # Only true branch is true
                return self._reduce(node.child_true, coefficients, constants)

            true_reduced = self._reduce(node.child_true, true_coefficients, true_constants)
            false_reduced = self._reduce(node.child_false, false_coefficients, false_constants)
            return self.pool.internal(node.test, true_reduced, false_reduced)
        else:
            raise RuntimeError("Unexpected node {} of type {}".format(node, type(node)))

    def _combine(self, coefficients, constants, test, test_true):
        new_coefficients, new_constant = self._test_to_linear_leq_constraint(test, test_true)
        combined_coefficients = []
        for i in range(0, len(new_coefficients)):
            if i >= len(coefficients):
                combined_coefficients.append([new_coefficients[i]])
            else:
                combined_coefficients.append(coefficients[i] + [new_coefficients[i]])
        combined_constants = constants + [new_constant]
        return combined_coefficients, combined_constants

    def _test_to_linear_leq_constraint(self, test, test_true):
        # Assumes integer variables / constraints
        operator = test.operator if test_true else ~test.operator
        operator = operator.to_canonical()
        constant = operator.rhs
        coefficients = list(operator.coefficient(var) for var in self.variables)
        return coefficients, constant

    def _is_feasible(self, coefficients, constants):
        # TODO substitute variable for value if it can be only one value
        import cvxopt
        # if len(coefficients) > len(constants):
        #     return True  # TODO Not 100% sure about this
        cvxopt.solvers.options["show_progress"] = False
        A = cvxopt.matrix(coefficients)
        b = cvxopt.matrix(constants)
        c = cvxopt.matrix([0.0] * len(self.variables))
        try:
            status = cvxopt.solvers.lp(c, A, b, solver="cvxopt_glpk")["status"]
            return "infeasible" not in status
        except ValueError as _:
            return True
        except TypeError as e:
            print(coefficients, constants)
            raise e


class SmtReduce(Reducer):
    def __init__(self, pool, solver=None):
        Reducer.__init__(self, pool)
        self.variables = None
        self.operator_dict = dict()
        self.solver = solver

    @property
    def columns(self):
        return len(self.variables)

    def reduce(self, node_id, variables=None):
        if variables is None:
            variables = self._get_variables(node_id)
        self.variables = variables
        with smt.Solver(name=self.solver) as solver:
            return self._reduce(self.pool.get_node(node_id), solver).node_id

    def _reduce(self, node, solver):
        if isinstance(node, TerminalNode):
            # Reached end of the path, path is consistent
            return node
        elif isinstance(node, InternalNode):
            print("TESTING {} AND {}".format(node.test.operator, ~node.test.operator))
            smt_test_true, smt_test_false = (self._test_to_smt(op) for op in (node.test.operator, ~node.test.operator))

            def reduce_branch(true):
                solver.push()
                solver.add_assertion(smt_test_true if true else smt.Not(smt_test_false))
                child_node = self.pool.get_node(node.child_true if true else node.child_false)
                reduced_node = self._reduce(child_node, solver)
                solver.pop()
                return reduced_node

            if not solver.solve([smt_test_true]):
                #print(smt_test_true, "not possible, pursue false branch")
                return reduce_branch(False)

            if not solver.solve([smt_test_false]):
                #print(smt_test_false, "not possible, pursue true branch")
                return reduce_branch(True)

            # print(smt_test, "possible, pursue both branches")
            node_id = self.pool.internal(node.test, reduce_branch(True).node_id, reduce_branch(False).node_id)
            return self.pool.get_node(node_id)
        else:
            raise RuntimeError("Unknown node {} of type {}".format(node, type(node)))

    def _test_to_smt(self, operator):
        operator = operator.to_canonical()

        # FIXME Integer rounding only applicable if x >= 0

        def to_symbol(s):
            return smt.Symbol(s, typename=smt.types.INT)
        
        import math
        items = [smt.Times(smt.Int(int(math.floor(v))), to_symbol(k)) for k, v in operator.lhs.items()]
        lhs = smt.Plus(items)
        rhs = smt.Int(int(math.floor(operator.rhs)))

        assert operator.symbol == "<="

        return smt.LE(lhs, rhs)

    def _exp_to_smt(self, expression):
        if isinstance(expression, sympy.Add):
            return smt.Plus([self._exp_to_smt(arg) for arg in expression.args])
        elif isinstance(expression, sympy.Mul):
            return smt.Times(*[self._exp_to_smt(arg) for arg in expression.args])
        elif isinstance(expression, sympy.Symbol):
            return smt.Symbol(str(expression), INT)

        try:
            expression = int(expression)
            return smt.Int(expression)
        except ValueError:
            pass
        raise RuntimeError("Could not parse {} of type {}".format(expression, type(expression)))


def is_simple(diagram):
    profile = diagram.profile
    for node_id in profile:
        node = diagram.node(node_id)
        if isinstance(node, InternalNode) and isinstance(node.test, LinearTest) and len(node.test.variables) > 1:
            return False
    return True


class SimpleBoundReducer(Reducer):
    def __init__(self, pool, ignore_multiple_variables=True):
        Reducer.__init__(self, pool)
        self._ignore_multiple_variables = ignore_multiple_variables

    def reduce(self, node_id, variables=None):
        return self._reduce(node_id, dict())

    def _reduce(self, node_id, bounds):
        """
        :param int node_id:
        :param dict bounds:
        :return:
        """
        node = self.pool.get_node(node_id)
        if isinstance(node, TerminalNode):
            # Test if singular bounds
            expression = node.expression
            values = dict()
            for symbol in expression.free_symbols:
                lb, ub = bounds.get(str(symbol), (None, None))
                if lb is not None and ub is not None and lb == ub:
                    values[symbol] = lb
                else:
                    break
            if len(values) == len(expression.free_symbols):
                return self.pool.terminal(expression.subs(values))
            else:
                return node_id

        elif isinstance(node, InternalNode):
            # Test if there are infeasible paths
            test = node.test
            if isinstance(test, LinearTest) and len(test.variables) == 1:
                # Linear one variable test
                var, = test.variables
                lb, ub = bounds.get(var, (None, None))
                lb_true, ub_true = test.update_bounds(var, lb, ub, test=True)
                if None not in (lb_true, ub_true) and lb_true > ub_true:
                    # Test is redundant, true branch is impossible, continue with false branch
                    return self._reduce(node.child_false, bounds)

                lb_false, ub_false = test.update_bounds(var, lb, ub, test=False)
                if None not in (lb_false, ub_false) and lb_false > ub_false:
                    # Test is redundant, false branch is impossible, continue with true branch
                    return self._reduce(node.child_true, bounds)

                true_bounds = dict(bounds)
                true_bounds[var] = lb_true, ub_true

                false_bounds = dict(bounds)
                false_bounds[var] = lb_false, ub_false

                true_reduced = self._reduce(node.child_true, true_bounds)
                false_reduced = self._reduce(node.child_false, false_bounds)
                return self.pool.internal(node.test, true_reduced, false_reduced)
            else:
                # Non linear or multiple variable test
                if not self._ignore_multiple_variables and isinstance(test, LinearTest):
                    raise RuntimeError("Multiple variables not allowed ({})".format(test))
                return self.pool.internal(node.test, bounds, bounds)

        else:
            raise RuntimeError("Unexpected node {} of type {}".format(node, type(node)))
