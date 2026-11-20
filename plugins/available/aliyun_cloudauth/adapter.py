from biometrics.adapters.aliyun import AliyunCloudAuthAdapter


class Plugin(AliyunCloudAuthAdapter):
    def __init__(self, config=None):
        super().__init__(config=config)
