import unittest

from xadd.diagram import Diagram, Pool
from xadd.operation import Multiplication, Summation
from xadd.test import Test, Operators
from xadd.view import export
from xadd.walk import WalkingProfile, ParentsWalker


class TestDiagram(unittest.TestCase):
    def setUp(self):
        pool = Pool()
        self.test1 = pool.bool_test(Test("x", ">="))
        self.test2 = pool.bool_test(Test("x + 2", "="))
        self.test3 = pool.bool_test(Test("x + 1", "<="))
        self.test4 = pool.bool_test(Test("x - 5", "<="))
        self.x = pool.terminal("x")

        p1 = pool.apply(Multiplication, self.test1, self.test4)
        p2 = pool.apply(Multiplication, pool.invert(self.test1), self.test2)
        p3 = pool.apply(Multiplication, pool.apply(Multiplication, pool.apply(Multiplication,
                                                                              pool.invert(self.test1),
                                                                              pool.invert(self.test2)),
                                                   self.test3),
                        self.test4)

        result = pool.apply(Summation, pool.apply(Summation, p1, p2), p3)
        result = pool.apply(Multiplication, result, self.x)
        self.diagram = Diagram(pool, result)

    def test_evaluation(self):
        self.assertEqual(4, self.diagram.evaluate([("x", 4)]))

    def test_multiplication(self):
        pool = Pool()
        two = pool.terminal("2")
        x = pool.terminal("x")

        test1 = pool.bool_test(Test("x", Operators.get(">=")))
        test2 = pool.apply(Multiplication, pool.bool_test(Test("x - 5", Operators.get("<="))), x)

        product = pool.apply(Multiplication, test1, test2)
        result = Diagram(pool, pool.apply(Multiplication, product, two))

        for i in range(0, 10):
            evaluated = result.evaluate({"x": i})
            if 0 <= i <= 5:
                self.assertEqual(2 * i, evaluated)
            else:
                self.assertEqual(0, evaluated)

    def test_not(self):
        pool = Pool()
        dd_true = Diagram(pool, pool.bool_test(Test("x", ">=")))
        dd_false = Diagram(pool, pool.invert(dd_true.root_node.node_id))

        for i in range(-5, 6):
            assignment = {"x": i}
            self.assertEqual((dd_true.evaluate(assignment) + 1) % 2, dd_false.evaluate(assignment))

    def test_construct(self):
        self.check_diagram(self.diagram, self.diagram.pool.zero_id, self.x)

    def test_summation(self):
        result = self.diagram + self.diagram
        self.check_diagram(result, result.pool.zero_id, result.pool.terminal("2*x"))

    def check_diagram(self, diagram, zero_term, x_term):
        pool = diagram.pool
        layers = WalkingProfile.extract_layers(diagram, ParentsWalker(diagram).walk())
        self.assertEqual(5, len(layers))

        self.assertEqual(1, len(layers[0]), layers[0])
        self.assertEqual(pool.get_node(self.test1).test, pool.get_node(layers[0][0]).test, layers[0])

        self.assertEqual(1, len(layers[1]), layers[1])
        self.assertEqual(pool.get_node(self.test2).test, pool.get_node(layers[1][0]).test, layers[1])

        self.assertEqual(1, len(layers[2]), layers[2])
        self.assertEqual(pool.get_node(self.test3).test, pool.get_node(layers[2][0]).test, layers[2])

        self.assertEqual(1, len(layers[3]), layers[3])
        self.assertEqual(pool.get_node(self.test4).test, pool.get_node(layers[3][0]).test, layers[3])

        self.assertEqual(2, len(layers[4]))
        self.assertTrue(zero_term in layers[4], layers[4])
        self.assertTrue(x_term in layers[4], layers[4])


if __name__ == '__main__':
    unittest.main()