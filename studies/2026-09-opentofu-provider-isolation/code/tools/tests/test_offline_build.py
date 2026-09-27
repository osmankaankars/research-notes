"""Build-input transport checks. These tests do not compile OpenTofu."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build


class OfflineBuildTests(unittest.TestCase):
    def test_actual_local_git_bundle_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'source'; source.mkdir()
            def git(*args):
                return subprocess.check_output(['git','-c','user.name=Offline Test',
                    '-c','user.email=test@localhost','-C',str(source),*args],stderr=subprocess.STDOUT,text=True)
            git('init','-b','input')
            (source/'marker.txt').write_text('exact input\n')
            git('add','marker.txt'); git('commit','-m','test input')
            commit=git('rev-parse','HEAD').strip()
            inp=root/'inputs'; (inp/'sources').mkdir(parents=True)
            git('bundle','create',str(inp/'sources/opentofu.bundle'),'HEAD')
            calls=[]
            def run(args,**kw):
                calls.append(args)
                subprocess.run(args,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,env=build.base_environment(root))
            dest=root/'checkout'
            build.clone_offline('opentofu/opentofu',commit,dest,inp,run,build.base_environment(root))
            self.assertEqual((dest/'marker.txt').read_text(),'exact input\n')
            self.assertFalse(any('https://' in str(x) for a in calls for x in a))
            with self.assertRaisesRegex(RuntimeError,'commit mismatch'):
                build.clone_offline('opentofu/opentofu','0'*40,root/'wrong',inp,run,build.base_environment(root))

    def test_environment_does_not_inherit_secret_or_proxy(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict('os.environ',{'FAKE_PRIVATE_SECRET':'not-a-real-key','GOPROXY':'https://wrong.invalid',
                                         'GOTOOLCHAIN':'auto','GIT_CONFIG_COUNT':'99','AWS_ACCESS_KEY_ID':'canary'}):
                e=build.base_environment(Path(tmp))
                self.assertNotIn('FAKE_PRIVATE_SECRET',e)
                self.assertNotIn('AWS_ACCESS_KEY_ID',e)
                self.assertNotIn('GIT_CONFIG_COUNT',e)
                self.assertEqual(e['GOTOOLCHAIN'],'local')
                self.assertEqual(e['GOWORK'],'off')

    def test_compiler_probe_does_not_create_output_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'future-build'
            version=build.installed_compiler_version()
            self.assertIn('go version go',version)
            self.assertFalse(output.exists())

    def test_telemetry_is_actually_off_in_private_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            env=build.base_environment(Path(tmp))
            build.disable_telemetry(env)
            mode=subprocess.check_output(['go','telemetry'],env=env,text=True).strip()
            self.assertEqual(mode,'off')

    def test_argument_contract_requires_pin_with_inputs(self):
        with self.assertRaises(ValueError): build.check_offline_arguments(Path('/tmp/inputs'),None)
        with self.assertRaises(ValueError): build.check_offline_arguments(None,'a'*64)
        build.check_offline_arguments(None,None)
        build.check_offline_arguments(Path('/tmp/inputs'),'a'*64)


if __name__=='__main__':unittest.main()
