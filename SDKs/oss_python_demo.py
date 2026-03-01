# -*- coding: utf-8 -*-
import os
from typing import Optional

import oss2

ENDPOINTS = {"CHINA_MAINLAND": "oss-rg-china-mainland.aliyuncs.com", "CN_SHANGHAI": "oss-cn-shanghai.aliyuncs.com"}


class AliOSSBucket:
    """阿里OSS Bucket的实例调用"""

    def __init__(self, endpoint, bucket_name, accessKeyId, accessKeySecret, internal_endpoint: Optional[str] = None):
        auth = oss2.Auth(accessKeyId, accessKeySecret)
        self.bucket = oss2.Bucket(auth, endpoint, bucket_name)
        self.endpoint_url = endpoint
        self.bucket_name = bucket_name
        self.internal_endpoint = internal_endpoint

    def getBucket(self):
        return self.bucket

    def get_file_link(self, object_name: str) -> str:
        return f"https://{self.bucket_name}.{self.endpoint_url}/{object_name}" if not self.internal_endpoint \
            else f"https://{self.bucket_name}.{self.internal_endpoint}/{object_name}"

    def upload_file(self, filePath, fileName):
        if (os.path.exists(filePath) and os.path.isfile(filePath)):
            file = open(filePath, "rb")
            data = file.read()
            self.bucket.put_object(fileName, data)
            # 上传完成后，确认上传的文件是否存在
            if self.exist(fileName):
                return True
        return False

    def upload_file_with_url(self, file_path: str, object_name: Optional[str] = None) -> str:
        if object_name:
            name_root, ext = os.path.splitext(object_name)
            candidate = object_name
        else:
            candidate = os.path.basename(file_path)
            name_root, ext = os.path.splitext(candidate)

        index = 1
        while self.exist(candidate):
            candidate = f"{name_root}-{index}{ext}"
            index += 1

        if self.upload_file(file_path, candidate):
            return self.get_file_link(candidate)

        raise RuntimeError(f"OSS failed to upload file {candidate} from {file_path}!")

    def get_file(self, fileName):
        if not self.exist(fileName):
            return "File not exists."
        return self.get_object(fileName).read()

    def delete_file(self, fileName):
        if not self.exist(fileName):
            return "File not exists."
        return self.delete_object(fileName)

    def traverse(self):
        file_list = []
        for object_info in oss2.ObjectIterator(self.bucket):
            file_list.append(object_info.key)
        return file_list

    def exist(self, fileName):
        return self.bucket.object_exists(fileName)
