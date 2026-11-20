import os
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

from biometrics import BioTemplateStore, CaptureRepository, PluginManager, PluginManifest
from biometrics.plugins import PluginPackage, import_template_package
from biometrics.plugins.manager import RegisteredPlugin
from biometrics.store import TemplateCipher
from cryptography.fernet import Fernet


PLUGIN_TOML = '''
schema_version = "1.0"
plugin_id = "caos.demo.face"
name = "演示人脸插件"
version = "1.0.0"
vendor = "demo"
modalities = ["face"]
platforms = ["windows-x64"]
adapter_class = "adapter.DemoAdapter"
capabilities = ["detect", "extract", "compare"]
permissions = ["camera", "files.plugin"]
enabled_by_default = false
'''

ADAPTER_PY = '''
from biometrics.adapters import VendorAdapter


class DemoAdapter(VendorAdapter):
    def __init__(self, config):
        super().__init__("face", "demo", config)

    def check_available(self):
        return True, "ok"

    def extract(self, sample):
        raise RuntimeError("test only")
'''

TEMPLATE_TOML = '''
subject = "张三"
modality = "fingerprint"
device_id = "WEB"
backend = "sdk"
quality = 0.88
raw_file = "raw/sample.jpg"
raw_mime = "image/jpeg"

[arrays.embedding]
file = "arrays/embedding.npy"
'''


class PluginProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='caos_plugin_test_'))
        self.source = self.tmp / 'source'
        self.source.mkdir()
        (self.source / 'plugin.toml').write_text(PLUGIN_TOML, encoding='utf-8')
        (self.source / 'adapter.py').write_text(ADAPTER_PY, encoding='utf-8')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_manifest(self):
        manifest = PluginManifest.load(self.source / 'plugin.toml')
        self.assertEqual(manifest.plugin_id, 'caos.demo.face')
        self.assertEqual(manifest.capability_set(), {'detect', 'extract', 'compare'})

    def test_unsigned_package_requires_explicit_allow(self):
        with self.assertRaises(PermissionError):
            PluginPackage.open(self.source)
        package = PluginPackage.open(self.source, allow_unsigned=True)
        self.assertFalse(package.signed)
        self.assertEqual(package.manifest.plugin_id, 'caos.demo.face')

    def test_plugin_manager_install_disable_and_enable(self):
        manager = PluginManager(
            plugin_root=self.tmp / 'installed',
            registry_db=self.tmp / 'dd' / 'plugins.db',
            trusted_key_dir=self.tmp / 'keys',
            allow_unsigned=True,
        )
        plugin = manager.install(self.source)
        self.assertIsInstance(plugin, RegisteredPlugin)
        self.assertFalse(plugin.enabled)
        plugin = manager.set_enabled(plugin.plugin_id, True)
        self.assertTrue(plugin.enabled)
        self.assertEqual(plugin.status, 'active')
        adapter = manager.load_adapter(plugin.plugin_id)
        self.assertEqual(adapter.check_available(), (True, 'ok'))
        plugin = manager.set_enabled(plugin.plugin_id, False)
        self.assertFalse(plugin.enabled)

    def test_standard_template_import(self):
        package = self.tmp / 'template'
        arrays = package / 'arrays'
        raw = package / 'raw'
        arrays.mkdir(parents=True)
        raw.mkdir(parents=True)
        np.save(arrays / 'embedding.npy', np.ones(8, dtype=np.float32))
        (raw / 'sample.jpg').write_bytes(b'jpeg-bytes')
        (package / 'template.toml').write_text(TEMPLATE_TOML, encoding='utf-8')

        cipher = TemplateCipher(Fernet.generate_key())
        store = BioTemplateStore(str(self.tmp / 'bio.db'), cipher=cipher)
        capture = CaptureRepository(str(self.tmp / 'capture.db'), cipher=cipher)
        result = import_template_package(package, store, capture)
        self.assertTrue(result.raw_saved)
        self.assertEqual(result.digest, result.template.digest())
        loaded = store.load('张三', 'fingerprint', 'WEB', backend='sdk')
        self.assertIsNotNone(loaded)
        active = capture.active_version('张三', 'fingerprint', 'WEB')
        self.assertEqual(active.image_bytes, b'jpeg-bytes')


if __name__ == '__main__':
    unittest.main()
