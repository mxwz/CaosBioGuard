"""拔插式生物识别 SDK 插件。"""

from .archive import safe_extract_zip
from .manifest import PluginManifest
from .package import PluginPackage, verify_plugin_signature
from .manager import PluginManager
from .template_import import TemplateImportResult, import_template_package

__all__ = [
    'safe_extract_zip',
    'PluginManifest',
    'PluginPackage',
    'PluginManager',
    'TemplateImportResult',
    'import_template_package',
    'verify_plugin_signature',
]
