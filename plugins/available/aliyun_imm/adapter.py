from biometrics.adapters.aliyun import AliyunIMMAdapter


class Plugin(AliyunIMMAdapter):
    def __init__(self, config=None):
        super().__init__(config=config)
