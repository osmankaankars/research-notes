"""Source-transform tests only. These do NOT compile or execute OpenTofu."""
import importlib.util
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('overlay',Path(__file__).parents[1]/'install.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
class OverlayTests(unittest.TestCase):
 def test_blob_algorithm_matches_git(self):
  self.assertEqual(mod.blob_id(b''),'e69de29bb2d1d6434b8b29ae775ad8c2e48c5391')
 def test_unknown_or_missing_bytes_rejected(self):
  with self.assertRaises(ValueError):mod.generate({})
  with self.assertRaises(ValueError):mod.generate({p:b'invalid' for p in mod.PINNED})
 def test_anchor_cannot_match_twice(self):
  with self.assertRaises(ValueError):mod.once('a a','a','b')
 def test_schema_context_separation(self):
  s='package plugins\nfunc f(){\n\treturn f()\n}\n'+'p.providerFactories.NewInstance(addr)\n'*3
  out=mod.transform('internal/plugins/provider.go',s)
  self.assertEqual(out.count('newForSchema(ctx, addr)'),1)
  self.assertEqual(out.count('newForContext(ctx, addr)'),2)
  self.assertIn('legacy launch entry has no authority scope',out)
 def test_each_validation_instance_gets_full_scope(self):
  s='package tofu\nimport (\n)\n'+mod.VALIDATE_OLD+'\nevalCtx.Providers().NewConfiguredProvider(ctx, n.Addr.Provider, configVal)'
  out=mod.transform('internal/tofu/node_provider.go',s)
  self.assertIn('n.instances[key] = instance',out)
  self.assertIn('providerIsolationContext(ctx, n.Addr, key, providercell.Validation)',out)
  self.assertIn('providerIsolationContext(ctx, n.Addr, providerKey, providercell.Configured)',out)
  self.assertIn('if !providercell.Enabled()',out)
 def test_factory_has_no_unrestricted_fallback(self):
  s='import (\n)\nfunc (m *Meta) providerFactories() (map[addrs.Provider]providers.Factory, error) {\n\t\tfactory := providerFactory(cached)\n}\nfunc providerFactory(meta *providercache.CachedProvider) providers.Factory {\n}\n'
  out=mod.transform('internal/command/meta_providers.go',s)
  self.assertIn('isolatedProviderFactory(cached, isolatedPolicy)',out)
  self.assertIn('development overrides and unmanaged reattachment are unsupported',out)
  self.assertIn('unscoped provider launcher is disabled',out)
 def test_provisioners_disabled_in_strict_mode(self):
  out=mod.transform('internal/command/plugins.go','import (\n)\nfunc (m *Meta) provisionerFactories() map[string]provisioners.Factory {\n}\n')
  self.assertIn('return map[string]provisioners.Factory{}',out)
 def test_custom_runner_does_not_mix_cmd_and_runner(self):
  text=(mod.ROOT/'integration/templates/command/provider_isolation.go.in').read_text()
  self.assertIn('RunnerFunc:',text)
  self.assertNotIn('Cmd:',text)
  self.assertIn('SkipHostEnv:      true',text) if 'SkipHostEnv:      true' in text else self.assertRegex(text,r'SkipHostEnv:\s+true')
  self.assertRegex(text,r'AutoMTLS:\s+true')
 def test_helper_tracks_canonical_instance_key(self):
  self.assertIn('key.String()',mod.GRAPH_HELPER)
  self.assertIn('key!=addrs.NoKey',mod.GRAPH_HELPER)
  self.assertIn('Configuration:addr.String()',mod.GRAPH_HELPER)
if __name__=='__main__':unittest.main()
