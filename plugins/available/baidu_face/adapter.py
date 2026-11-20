from biometrics.adapters.baidu_face import BaiduFaceSDKAdapter


class Plugin(BaiduFaceSDKAdapter):
    """插件注册入口，实际能力由内置百度适配器提供。"""

    def __init__(self, config=None):
        super().__init__(config=config)
