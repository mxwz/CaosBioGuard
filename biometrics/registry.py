"""生物特征注册器：复用项目既有的 registry 框架，统一管理 9 个模态引擎。

与 ``registry/base.py`` 的关系：``BiometricRegistry`` 继承通用 ``Registry``，
只额外实现「按名取引擎」「可用性探测」「给 UI/API 的规格列表」三件事。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from registry.base import ORIGIN_SYSTEM, Registry

from .engines import ENGINE_CLASSES, FaceEngine
from .base import ModalityEngine


class BiometricRegistry(Registry):
    """9 模态引擎注册器。"""

    name = 'biometrics'
    label = '生物特征模态'

    def __init__(self, face_app=None):
        super().__init__()
        self._engines: Dict[str, ModalityEngine] = {}
        for cls in ENGINE_CLASSES:
            try:
                engine = cls(app=face_app) if cls is FaceEngine else cls()
                self.register_engine(engine)
            except Exception:
                # 单个引擎构造失败不应拖垮整个注册器
                continue

    def register_engine(self, engine: ModalityEngine, origin: str = ORIGIN_SYSTEM) -> None:
        self._engines[engine.name] = engine
        self.register(engine, name=engine.name, display_name=engine.label,
                      description=engine.spec.description, origin=origin,
                      entry=engine, tags=[engine.spec.kind])

    def resolve(self, name: str) -> ModalityEngine:
        """按名返回引擎实例；不存在抛 ``KeyError``。"""
        if name not in self._engines:
            raise KeyError(f'未注册的生物特征模态: {name}')
        return self._engines[name]

    def get_engine(self, name: str) -> Optional[ModalityEngine]:
        return self._engines.get(name)

    def engines(self) -> List[ModalityEngine]:
        return list(self._engines.values())

    def specs(self, with_availability: bool = True) -> List[dict]:
        """供 Web API / 小程序 / Kiosk 展示的模态清单。"""
        out = []
        for engine in self._engines.values():
            item = engine.spec.to_dict()
            if with_availability:
                try:
                    ok, reason = engine.check_available()
                except Exception as exc:
                    ok, reason = False, str(exc)
                item.update({'available': bool(ok), 'unavailable_reason': reason})
            out.append(item)
        return out

    def available_names(self) -> List[str]:
        names = []
        for engine in self._engines.values():
            try:
                if engine.check_available()[0]:
                    names.append(engine.name)
            except Exception:
                continue
        return names


def build_biometric_registry(face_app=None) -> BiometricRegistry:
    return BiometricRegistry(face_app=face_app)
