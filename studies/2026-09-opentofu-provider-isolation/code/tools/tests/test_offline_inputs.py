import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import offline_inputs as oi

class OfflineInputTests(unittest.TestCase):
    def bundle(self, root):
        for p in ('sources/opentofu.bundle', 'sources/random.bundle', 'fixture-lock/go.mod', 'fixture-lock/go.sum', 'modcache/cache/download/test.txt'):
            f=root/p; f.parent.mkdir(parents=True,exist_ok=True); f.write_text('fixed\n')
        return oi.seal(root, {'core': oi.CORE, 'random': oi.RANDOM}, fixture_input_digest='a'*64)
    def test_complete_inventory(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); pin=self.bundle(p)
            m=oi.verify(p,pin)
            self.assertEqual(m['core_commit'],oi.CORE)
            self.assertEqual(len(m['files']),5)
    def test_tamper_stops(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); pin=self.bundle(p); (p/'fixture-lock/go.sum').write_text('changed')
            with self.assertRaises(oi.InputError): oi.verify(p,pin)
    def test_extra_file_stops(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); pin=self.bundle(p); (p/'extra').write_text('x')
            with self.assertRaises(oi.InputError): oi.verify(p,pin)
    def test_pin_required(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); self.bundle(p)
            with self.assertRaises(oi.InputError): oi.verify(p,'0'*64)
    def test_symlinks_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); pin=self.bundle(p); (p/'fixture-lock/go.sum').unlink(); (p/'fixture-lock/go.sum').symlink_to('/etc/passwd')
            with self.assertRaises(oi.InputError): oi.verify(p,pin)
    def test_manifest_cannot_change_source_pin(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); self.bundle(p)
            f=p/'INPUTS.json'; m=json.loads(f.read_text());m['core_commit']='0'*40; f.write_text(json.dumps(m))
            pin=hashlib.sha256(f.read_bytes()).hexdigest()
            with self.assertRaises(oi.InputError): oi.verify(p,pin)
    def test_source_bundle_files_required(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); self.bundle(p)
            (p/'sources/opentofu.bundle').unlink()
            (p/'INPUTS.json').unlink()
            pin=oi.seal(p, {'core':oi.CORE,'random':oi.RANDOM}, 'a'*64)
            with self.assertRaises(oi.InputError): oi.verify(p,pin)
    def test_fixture_input_digest_checked(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); self.bundle(p)
            f=p/'INPUTS.json'; m=json.loads(f.read_text());m['fixture_input_go_mod_sha256']='bad'; f.write_text(json.dumps(m))
            pin=hashlib.sha256(f.read_bytes()).hexdigest()
            with self.assertRaises(oi.InputError): oi.verify(p,pin)
    def test_seal_does_not_follow_dangling_manifest_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp); root=base/'inputs'; root.mkdir()
            target=base/'outside'
            (root/'INPUTS.json').symlink_to(target)
            with self.assertRaises((oi.InputError,FileExistsError)):
                oi.seal(root,{'core':oi.CORE,'random':oi.RANDOM},'a'*64)
            self.assertFalse(target.exists())
    def test_offline_env(self):
        with tempfile.TemporaryDirectory() as d:
            e=oi.offline_environment(Path(d))
            self.assertEqual(e['GOPROXY'],'off')
            self.assertEqual(e['GOTOOLCHAIN'],'local')
            self.assertEqual(e['GOSUMDB'],'off')
            self.assertEqual(e['GONOPROXY'],'none')
            self.assertEqual(e['GOVCS'],'*:off')

if __name__=='__main__': unittest.main()
