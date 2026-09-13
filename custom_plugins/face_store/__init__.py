"""自定义人脸存储后端插件包。

在此目录下以「子包」（含 __init__.py 的目录）形式添加自定义后端，例如：

    custom_plugins/face_store/my_backend/__init__.py

子包的 __init__.py 需定义模块级 `INFO`（registry.base.PluginInfo 实例），
字段：name / display_name（中文名）/ description / origin='custom' / entry（FaceStore 类或实例）/ tags。
"""
