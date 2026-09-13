"""自定义 Agent 工具插件包。

在此目录下以「子包」（含 __init__.py 的目录）形式添加自定义工具，例如：

    custom_plugins/agent_tools/my_tool/__init__.py

子包的 __init__.py 需定义模块级 `INFO`（registry.base.PluginInfo 实例），
字段：name / display_name（中文名）/ description / origin='custom' / entry（可调用对象，签名 fn(args)->dict）/ tags。
"""
