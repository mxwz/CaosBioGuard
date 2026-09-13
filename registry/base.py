"""通用插件注册框架：以 Python 包为单位组织注册器与插件。

核心对象：
- PluginInfo：插件（应用）元信息数据类，含 origin（system/custom）区分原生/自定义。
- Registry：注册器基类，管理一个模块下的一组插件，支持自动发现。
- RegistryCenter：注册中心，统一管理所有注册器，提供对注册器与插件的增删改查（含代码级）。

业务方通过子类化 Registry 实现各自的选择/分发语义（通知按规则广播、人脸按配置选一、
工具按名分发），再统一登记到 RegistryCenter。
"""
import importlib
import logging
import os
import pkgutil
import re
import sys
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

ORIGIN_SYSTEM = 'system'   # 原生：随软件发布
ORIGIN_CUSTOM = 'custom'   # 自定义：后来编写


@dataclass
class PluginInfo:
    """插件（应用）元信息：描述一个注册到注册器中的应用/实现。

    - origin：'system' 原生 / 'custom' 自定义，用于区分来源并约束代码级删除权限。
    - entry：实现本体（类 / 实例 / 工厂 / 元数据 dict）。
    - path：源文件绝对路径，代码级增删改查的落点。
    """
    name: str
    display_name: str = ''
    description: str = ''
    origin: str = ORIGIN_SYSTEM
    entry: Any = None
    path: str = ''
    tags: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'display_name': self.display_name or self.name,
            'description': self.description,
            'origin': self.origin,
            'path': self.path,
            'tags': list(self.tags or []),
            'meta': self.meta,
        }


def validate_plugin_info(info: 'PluginInfo') -> list:
    """校验插件元信息格式，返回错误列表（空列表表示合法）。

    必填：name（合法标识符）、display_name（中文名）、description、origin（system/custom）、entry。
    """
    errors = []
    if not info.name:
        errors.append('缺少 name')
    elif not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', info.name):
        errors.append(f'name 非法（需为合法标识符）: {info.name}')
    if not info.display_name:
        errors.append('缺少 display_name（中文名）')
    if not info.description:
        errors.append('缺少 description（应用说明）')
    if info.origin not in (ORIGIN_SYSTEM, ORIGIN_CUSTOM):
        errors.append(f'origin 非法: {info.origin}')
    if info.entry is None:
        errors.append('缺少 entry（实现本体）')
    if not isinstance(info.tags, list):
        errors.append('tags 需为列表')
    return errors


class Registry:
    """注册器基类。

    子类声明 name / label，并可声明 system_plugin_package / custom_plugin_package
    以启用包级自动发现；公共能力（登记/查询/列表/发现）由本基类统一提供。
    """
    name = ''
    label = ''
    system_plugin_package = ''   # 原生插件所在包，如 'notify.channels'
    custom_plugin_package = ''   # 自定义插件所在包，如 'custom_plugins.notify'

    def __init__(self):
        self._items = {}  # name -> PluginInfo
        self._problems = []  # 发现过程中无效/异常的插件

    # ------------------------------------------------------------------
    # 登记 / 查询 / 列表
    # ------------------------------------------------------------------
    def register(self, item, name=None, *, display_name='', description='',
                 origin=ORIGIN_SYSTEM, entry=None, path='', tags=None, **meta):
        """登记一个插件。item 可为 PluginInfo，或任意实现（类/实例/dict）。"""
        if isinstance(item, PluginInfo):
            info = item
            if tags:
                info.tags = list(tags)
        else:
            def _attr(key, default=''):
                if isinstance(item, dict):
                    return item.get(key, default)
                return getattr(item, key, default)

            if tags is None:
                tags = _attr('tags', [])
            info = PluginInfo(
                name=name or _attr('name') or getattr(item, '__name__', ''),
                display_name=display_name or _attr('display_name') or _attr('label'),
                description=description or _attr('description'),
                origin=origin,
                entry=entry if entry is not None else item,
                path=path or _attr('path'),
                tags=list(tags or []),
                meta=meta,
            )
        if not info.name:
            raise ValueError('登记项缺少 name')
        self._items[info.name] = info
        return info

    def unregister(self, name):
        return self._items.pop(name, None)

    def get(self, name):
        return self._items.get(name)

    def resolve(self, name):
        """返回插件实现本体（entry）。"""
        info = self._items.get(name)
        return info.entry if info else None

    def items(self):
        return dict(self._items)

    def list(self):
        """返回所有已登记插件的元信息，供管理/UI 展示。"""
        return [info.to_dict() for info in self._items.values()]

    def problems(self):
        """返回发现过程中无效/异常的插件清单（供 UI 爆红提示）。"""
        return list(self._problems)

    # ------------------------------------------------------------------
    # 自动发现
    # ------------------------------------------------------------------
    def discover(self):
        """扫描 system/custom 插件包，收集并登记模块级 INFO；无效项进入 problems。"""
        self._problems = []
        for pkg in (self.system_plugin_package, self.custom_plugin_package):
            if not pkg:
                continue
            infos, problems = discover_plugin_infos(pkg)
            for info in infos:
                self.register(info)
            self._problems.extend(problems)
        return self.list()

    def reload(self):
        """重新发现（重载已导入模块）并合并登记。"""
        return self.discover()


def _short_name(fullname):
    return fullname.rsplit('.', 1)[-1]


def discover_plugin_infos(package_name):
    """扫描 package 下的插件（仅接受含 __init__.py 的软件包子包），收集 INFO。

    返回 (infos, problems)：
    - infos：合法 PluginInfo 列表
    - problems：非包形式 / 导入失败 / 缺少 INFO / 校验不通过的问题插件（{name, path, error}）
    """
    infos = []
    problems = []
    try:
        pkg = importlib.import_module(package_name)
    except ImportError as e:
        logger.debug(f"插件包不可用，跳过: {package_name} ({e})")
        return infos, problems

    importlib.invalidate_caches()
    pkg_path = getattr(pkg, '__path__', None)
    if pkg_path is None:
        return infos, problems

    for _, fullname, ispkg in pkgutil.iter_modules(pkg_path, pkg.__name__ + '.'):
        if not ispkg:
            problems.append({
                'name': _short_name(fullname),
                'path': '',
                'error': '必须是软件包形式（含 __init__.py 的子包），不接受单个 .py 文件',
            })
            continue
        try:
            if fullname in sys.modules:
                mod = importlib.reload(sys.modules[fullname])
            else:
                mod = importlib.import_module(fullname)
        except Exception as e:
            logger.warning(f"加载插件失败 {fullname}: {e}")
            problems.append({'name': _short_name(fullname), 'path': '', 'error': f'导入失败: {e}'})
            continue

        info = getattr(mod, 'INFO', None)
        path = getattr(mod, '__file__', '') or ''
        if not isinstance(info, PluginInfo):
            problems.append({
                'name': _short_name(fullname),
                'path': path,
                'error': '缺少有效的 INFO（PluginInfo）',
            })
            continue

        if not info.path:
            info.path = path
        errors = validate_plugin_info(info)
        if errors:
            problems.append({
                'name': info.name or _short_name(fullname),
                'path': info.path,
                'error': '；'.join(errors),
            })
            continue

        infos.append(info)
    return infos, problems


class RegistryCenter:
    """注册中心：统一管理所有注册器，并提供统一调度与代码级 CRUD。"""

    def __init__(self):
        self._registries = {}

    # ------------------------------------------------------------------
    # 注册器管理
    # ------------------------------------------------------------------
    def register(self, registry):
        if not getattr(registry, 'name', ''):
            raise ValueError('注册器缺少 name')
        self._registries[registry.name] = registry
        return registry

    def unregister(self, name):
        return self._registries.pop(name, None)

    def get(self, name):
        return self._registries.get(name)

    def list(self):
        """返回所有注册器及旗下插件元信息（含是否支持自定义插件）。"""
        return [
            {
                'name': r.name,
                'label': r.label,
                'custom_plugin_package': r.custom_plugin_package,
                'items': r.list(),
                'problems': r.problems(),
            }
            for r in self._registries.values()
        ]

    def names(self):
        """返回所有注册器的名称与中文标签（供导航使用）。"""
        return [{'name': r.name, 'label': r.label} for r in self._registries.values()]

    def dispatch(self, registry_name, method, *args, **kwargs):
        """统一调度：对指定注册器调用其方法。"""
        registry = self._registries.get(registry_name)
        if not registry:
            raise KeyError(f'未注册的注册器: {registry_name}')
        fn = getattr(registry, method, None)
        if fn is None:
            raise AttributeError(f'注册器 {registry_name} 无方法 {method}')
        return fn(*args, **kwargs)

    # ------------------------------------------------------------------
    # 代码级 CRUD（插件源文件）
    # ------------------------------------------------------------------
    def read_plugin_source(self, registry_name, plugin_name):
        """读取插件源文件内容；不存在返回 None。"""
        info = self._plugin_info(registry_name, plugin_name)
        if not info or not info.path or not os.path.exists(info.path):
            return None
        with open(info.path, 'r', encoding='utf-8') as f:
            return f.read()

    def write_plugin(self, registry_name, plugin_name, code):
        """创建/更新自定义插件源文件，并重新发现登记。返回写入路径。"""
        registry = self._registries.get(registry_name)
        if not registry or not registry.custom_plugin_package:
            raise ValueError(f'注册器 {registry_name} 未声明 custom_plugin_package，不支持代码级写入')
        safe_name = sanitize_plugin_name(plugin_name)
        pkg_dir = package_dir(registry.custom_plugin_package)
        if not pkg_dir:
            raise RuntimeError(f'找不到自定义插件目录: {registry.custom_plugin_package}')
        os.makedirs(pkg_dir, exist_ok=True)
        path = os.path.join(pkg_dir, safe_name + '.py')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(code)
        registry.discover()
        return path

    def delete_plugin(self, registry_name, plugin_name):
        """删除自定义插件源文件并注销；原生插件（origin=system）拒绝删除。"""
        registry = self._registries.get(registry_name)
        info = self._plugin_info(registry_name, plugin_name)
        if not registry or not info:
            return False
        if info.origin != ORIGIN_CUSTOM:
            raise PermissionError(f'系统原生插件不可删除: {plugin_name}')
        if info.path and os.path.exists(info.path):
            os.remove(info.path)
        registry.unregister(plugin_name)
        return True

    def _plugin_info(self, registry_name, plugin_name):
        registry = self._registries.get(registry_name)
        if not registry:
            return None
        return registry.get(plugin_name)


def package_dir(package_name):
    """返回包的物理目录；不可导入返回 None。"""
    try:
        pkg = importlib.import_module(package_name)
    except ImportError:
        return None
    if not pkg.__file__:
        return None
    return os.path.dirname(pkg.__file__)


def sanitize_plugin_name(name):
    """校验插件名为合法 Python 标识符，防止路径穿越。"""
    name = str(name).strip()
    if not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', name):
        raise ValueError(f'非法插件名: {name}')
    return name
