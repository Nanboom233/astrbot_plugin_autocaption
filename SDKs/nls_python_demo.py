# -*- coding: utf8 -*-
import json
import os
import shutil
import time
from typing import Optional

from aliyunsdkcore.acs_exception.exceptions import ClientException
from aliyunsdkcore.acs_exception.exceptions import ServerException
from aliyunsdkcore.client import AcsClient
from aliyunsdkcore.request import CommonRequest
from astrbot.core import LogManager

import ffmpeg
import static_ffmpeg

from .oss_python_demo import AliOSSBucket

logger = LogManager.GetLogger(log_name="astrbot")


class NLSClient:
    def __init__(self, access_key_id: str, access_key_secret: str, app_key: str):
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret
        self.app_key = app_key

    def fileTrans(self, fileLink):
        # 地域ID，固定值。
        REGION_ID = "cn-shanghai"
        PRODUCT = "nls-filetrans"
        DOMAIN = "filetrans.cn-shanghai.aliyuncs.com"
        API_VERSION = "2018-08-17"
        POST_REQUEST_ACTION = "SubmitTask"
        GET_REQUEST_ACTION = "GetTaskResult"
        # 请求参数
        KEY_APP_KEY = "appkey"
        KEY_FILE_LINK = "file_link"
        KEY_VERSION = "version"
        KEY_ENABLE_WORDS = "enable_words"
        # 是否开启智能分轨
        KEY_AUTO_SPLIT = "auto_split"
        # 响应参数
        KEY_TASK = "Task"
        KEY_TASK_ID = "TaskId"
        KEY_STATUS_TEXT = "StatusText"
        KEY_RESULT = "Result"
        # 状态值
        STATUS_SUCCESS = "SUCCESS"
        STATUS_RUNNING = "RUNNING"
        STATUS_QUEUEING = "QUEUEING"
        # 创建AcsClient实例
        client = AcsClient(self.access_key_id, self.access_key_secret, REGION_ID)
        # 提交录音文件识别请求
        postRequest = CommonRequest()
        postRequest.set_domain(DOMAIN)
        postRequest.set_version(API_VERSION)
        postRequest.set_product(PRODUCT)
        postRequest.set_action_name(POST_REQUEST_ACTION)
        postRequest.set_method('POST')
        # 新接入请使用4.0版本，已接入（默认2.0）如需维持现状，请注释掉该参数设置。
        # 设置是否输出词信息，默认为false，开启时需要设置version为4.0。
        task = {KEY_APP_KEY: self.app_key, KEY_FILE_LINK: fileLink, KEY_VERSION: "4.0", KEY_ENABLE_WORDS: False,
                "enable_sample_rate_adaptive": True, "sentence_max_length": 20,
                "enable_words": True}
        # 开启智能分轨，如果开启智能分轨，task中设置KEY_AUTO_SPLIT为True。
        # task = {KEY_APP_KEY : appKey, KEY_FILE_LINK : fileLink, KEY_VERSION : "4.0", KEY_ENABLE_WORDS : False, KEY_AUTO_SPLIT : True}
        task = json.dumps(task)

        # print(task)

        postRequest.add_body_params(KEY_TASK, task)
        taskId = ""
        try:
            postResponse = client.do_action_with_exception(postRequest)
            postResponse = json.loads(postResponse)

            # print(postResponse)

            statusText = postResponse[KEY_STATUS_TEXT]
            if statusText == STATUS_SUCCESS:
                logger.debug("录音文件识别请求成功响应！")
                taskId = postResponse[KEY_TASK_ID]
            else:
                logger.error("录音文件识别请求失败！")
                return
        except ServerException as e:
            logger.error(str(e))
        except ClientException as e:
            logger.error(str(e))
        # 创建CommonRequest，设置任务ID。
        getRequest = CommonRequest()
        getRequest.set_domain(DOMAIN)
        getRequest.set_version(API_VERSION)
        getRequest.set_product(PRODUCT)
        getRequest.set_action_name(GET_REQUEST_ACTION)
        getRequest.set_method('GET')
        getRequest.add_query_param(KEY_TASK_ID, taskId)
        # 提交录音文件识别结果查询请求
        # 以轮询的方式进行识别结果的查询，直到服务端返回的状态描述符为"SUCCESS"、"SUCCESS_WITH_NO_VALID_FRAGMENT"，
        # 或者为错误描述，则结束轮询。
        statusText = ""
        while True:
            try:
                getResponse = client.do_action_with_exception(getRequest)
                getResponse = json.loads(getResponse)
                statusText = getResponse[KEY_STATUS_TEXT]
                if statusText == STATUS_RUNNING or statusText == STATUS_QUEUEING:
                    # 继续轮询
                    time.sleep(10)
                else:
                    # 退出轮询
                    break
            except ServerException as e:
                logger.error(str(e))
            except ClientException as e:
                logger.error(str(e))
        if statusText == STATUS_SUCCESS:
            logger.debug("录音文件识别成功!")
        else:
            logger.error("录音文件识别失败!,请检查输出")
        return getResponse

    @staticmethod
    def read_path(file_path: str) -> tuple[str, str]:
        file_path = file_path.replace("\"", "").replace("\'", "").strip()
        if (not file_path) or (not os.path.isfile(file_path)):
            raise ValueError("Invalid file path!")
        absPath = os.path.abspath(file_path)
        return os.path.dirname(file_path), os.path.basename(absPath)

    @staticmethod
    def convert_to_mp3(input_path: str, output_path: Optional[str] = None) -> str:
        input_path = input_path.replace("\"", "").replace("'", "").strip()
        if (not input_path) or (not os.path.isfile(input_path)):
            raise ValueError("Invalid file path!")

        abs_input = os.path.abspath(input_path)
        abs_output = os.path.abspath(output_path) if output_path else os.path.splitext(abs_input)[0] + ".mp3"

        try:
            static_ffmpeg.add_paths()
        except Exception as exc:
            raise EnvironmentError("Failed to set up ffmpeg via static-ffmpeg.") from exc

        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            raise EnvironmentError("ffmpeg not found in PATH. Please install ffmpeg and try again.")

        try:
            (
                ffmpeg
                .input(abs_input)
                .output(abs_output, ar=16000, acodec="libmp3lame")
                .global_args("-y", "-loglevel", "quiet")
                .run(cmd=ffmpeg_path, capture_stdout=True, capture_stderr=True)
            )
        except ffmpeg.Error as exc:
            raise RuntimeError(f"ffmpeg failed to convert {abs_input} to mp3") from exc

        if not os.path.exists(abs_output):
            raise RuntimeError(f"ffmpeg failed to convert {abs_input} to mp3")

        return abs_output

    def run_nls(self, bucket: AliOSSBucket, file_path: str) -> dict:
        dir_name, base_name = self.read_path(file_path)
        full_path = os.path.join(dir_name, base_name)
        logger.debug(f"Converting {base_name} to mp3...")
        mp3_path = self.convert_to_mp3(full_path)
        logger.debug(f"Converted {base_name} to mp3")

        file_link = bucket.upload_file_with_url(mp3_path)

        logger.debug("Processing with NLS...")
        response = self.fileTrans(file_link)
        if response["StatusText"] != "SUCCESS":
            raise RuntimeError("Failed to process file!")
        logger.debug("Processed with NLS successfully")

        return response
