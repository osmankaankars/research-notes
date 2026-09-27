"""Preparation contracts, not evidence of a downloaded upstream dependency set."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import prepare_offline_inputs as prep

class PreparationTests(unittest.TestCase):
    def test_exact_upstream_inputs(self):
        plan=prep.input_plan()
        self.assertEqual(plan['core']['commit'],'b4305e5a5dd2fb79a27897ae30784a181d3a26cb')
        self.assertEqual(plan['random']['commit'],'bc2ddb552b4676d16997987a9bf2875c7b98d342')
        self.assertFalse(plan['executes_providers'])
        self.assertFalse(plan['contains_podman_runtime'])
    def test_known_file_mutation_stops(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp); (p/'go.mod').write_text('original');(p/'go.sum').write_text('pinned')
            before=prep.lock_hashes(p)
            prep.require_unchanged_locks(p,before)
            (p/'go.sum').write_text('changed')
            with self.assertRaisesRegex(RuntimeError,'lock changed'):
                prep.require_unchanged_locks(p,before)

if __name__=='__main__':unittest.main()
