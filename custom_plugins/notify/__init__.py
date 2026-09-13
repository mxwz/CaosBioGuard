"""自定义通知渠道插件包。

在此目录下以「子包」（含 __init__.py 的目录）形式添加自定义渠道，例如：

    custom_plugins/notify/sms/__init__.py

子包的 __init__.py 需定义模块级 `INFO`（registry.base.PluginInfo 实例），
字段：name / display_name（中文名）/ description / origin='custom' / entry（NotifyChannel 实例）/ tags。
"""
