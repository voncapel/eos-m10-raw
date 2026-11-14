"""Exercise the real CFG-tail function without importing USB modules."""
import ast
import os
from pathlib import Path
import unittest
from unittest.mock import patch

module = ast.parse(Path(__file__).with_name('m10x3raw.py').read_text())
fn = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == 'cfg_tail')
namespace = {'os': os}
exec(compile(ast.Module(body=[fn], type_ignores=[]), 'm10x3raw.py:cfg_tail', 'exec'), namespace)


class ConfigTests(unittest.TestCase):
    def test_legacy_tail_remains_empty(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(namespace['cfg_tail'](), '')

    def test_task_sampler_is_field_57(self):
        with patch.dict(os.environ, {'TSK': '1000'}, clear=True):
            words = namespace['cfg_tail']().split()
        self.assertEqual(len(words), 57 - 21)
        self.assertEqual(words[-1], '1000')
        self.assertEqual(words[-5:-1], ['0', '16', '0', '0'])  # HER EXM PBL SKICK


if __name__ == '__main__':
    unittest.main()
