"""Evidence-gate tests only; these do not run OpenTofu or containers."""
import ast
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / 'run_lab.py'
spec = importlib.util.spec_from_file_location('run_lab', PATH)
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)

class LabEvidenceTests(unittest.TestCase):
    def test_only_container_exists_exit_one_means_absent(self):
        lab.require_container_absent(1)
        for status in (0, 2, 125, -9):
            with self.subTest(status=status), self.assertRaises(RuntimeError):
                lab.require_container_absent(status)

    def test_success_record_is_written_only_after_cleanup(self):
        tree = ast.parse(PATH.read_text())
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
        final_try = max(n.end_lineno for n in main.body if isinstance(n, ast.Try) and n.finalbody)
        writes = [n for n in ast.walk(main) if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute) and n.func.attr == 'write_text'
                  and 'summary.json' in ast.unparse(n.func.value)]
        self.assertEqual(len(writes), 1)
        self.assertGreater(writes[0].lineno, final_try)

class ImageIdEvidenceTests(unittest.TestCase):
    def test_image_id_is_not_parsed_from_human_console_output(self):
        source=PATH.read_text()
        self.assertIn('--iidfile',source)
        self.assertNotIn("capture=True).strip().splitlines()[-1]",source)

    def test_immutable_image_id_has_full_hex_digest(self):
        self.assertEqual(lab.require_image_id('sha256:'+'a'*64+'\n'),'sha256:'+'a'*64)
        for value in ('latest','sha256:'+'x'*64,'a'*64,'sha256:'+'a'*63,'sha256:'+'a'*64+'\nextra'):
            with self.subTest(value=value),self.assertRaises(RuntimeError):lab.require_image_id(value)
