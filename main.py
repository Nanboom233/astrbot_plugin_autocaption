import os
from typing import Optional

import yaml
from astrbot.api import AstrBotConfig
from astrbot.api import logger
from astrbot.api import message_components as Comp
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

from .SDKs.nls_python_demo import NLSClient
from .SDKs.oss_python_demo import AliOSSBucket
from nls import process_intermediate_to_srt, process_to_json


def load_metadata():
    yaml_path = os.path.join(os.path.dirname(__file__), "metadata.yaml")
    if not os.path.exists(yaml_path):
        raise FileNotFoundError(f"metadata.yaml 未找到: {yaml_path}")

    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data:
        raise ValueError("metadata.yaml 为空或格式错误")

    required_keys = ["name", "author", "desc", "version", "repo"]
    for key in required_keys:
        if key not in data:
            raise ValueError(f"metadata.yaml 缺少必要字段: {key}")

    return data


PLUGIN_META = load_metadata()
SUPPORT_EXTENSINS = ["mp3", "wav", "flac", "aac", "ogg", "json"]  # 支持音频文件类型 + JSON


@register(
    PLUGIN_META["name"],
    PLUGIN_META["author"],
    PLUGIN_META["desc"],
    str(PLUGIN_META["version"]).lstrip("v"),
    PLUGIN_META["repo"]
)
class AutoCaptions(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

    def _require_config(self, key: str) -> str:
        value = self.config.get(key) if self.config else None
        if not value:
            raise ValueError(f"缺少配置: {key}")
        return value

    def _build_nls_clients(self) -> tuple[AliOSSBucket, NLSClient]:
        access_key_id = self._require_config("ALI_ACCESSKEYID")
        access_key_secret = self._require_config("ALI_ACCESSKEYSECRET")
        app_key = self._require_config("ALI_APPKEY")
        endpoint = self._require_config("ALI_OSS_ENDPOINT")
        bucket_name = self._require_config("ALI_OSS_BUCKET")
        internal_endpoint = self.config.get("ALI_OSS_INTERNAL_ENDPOINT") if self.config else None
        internal_endpoint = internal_endpoint or None

        bucket = AliOSSBucket(
            endpoint=endpoint,
            bucket_name=bucket_name,
            accessKeyId=access_key_id,
            accessKeySecret=access_key_secret,
            internal_endpoint=internal_endpoint,
        )
        nls_client = NLSClient(access_key_id, access_key_secret, app_key)
        return bucket, nls_client

    def get_file_type(self, file_path: str) -> Optional[str]:
        """安全获取文件扩展名（优先MIME检测，后备扩展名）"""

        # 首先检查文件是否存在
        if not os.path.isfile(file_path):
            raise FileNotFoundError

        try:
            # 方案1：使用python-magic（推荐）
            import magic
            mime = magic.from_file(file_path, mime=True)

            # 处理常见的MIME类型映射
            mime_to_ext = {
                'application/pdf': 'pdf',
                'image/jpeg': 'jpg',
                'image/png': 'png',
                'image/gif': 'gif',
                'text/plain': 'txt',
                'application/zip': 'zip',
                'application/x-rar-compressed': 'rar',
                'application/x-tar': 'tar',
                'application/gzip': 'gz'
            }

            # 处理常见的MIME类型映射
            if 'vnd.openxmlformats-officedocument' in mime:
                # 提取具体的Office文档类型
                if 'wordprocessingml' in mime:
                    return 'docx'
                elif 'spreadsheetml' in mime:
                    return 'xlsx'
                elif 'presentationml' in mime:
                    return 'pptx'

            # 检查映射表
            if mime in mime_to_ext:
                return mime_to_ext[mime]

            # 通用处理：从MIME类型中提取扩展名
            if '/' in mime:
                mime_type = mime.split("/")[-1]
                # 处理复合类型如vnd.ms-excel
                if mime_type.startswith('vnd.'):
                    mime_type = mime_type[4:]
                if mime_type.startswith('x-'):
                    mime_type = mime_type[2:]
                return mime_type

            return mime

        except ImportError:
            # 方案2：后备使用扩展名
            ext = os.path.splitext(file_path)[1]
            if ext:
                return ext[1:].lower()  # 去掉点号并转为小写
            else:
                raise ImportError

    def complete_filename(self, file_path: str) -> str:
        """补全文件名（如果缺少扩展名则自动添加）"""
        if not os.path.isfile(file_path):
            return file_path

        # 如果已经有扩展名，直接返回
        if os.path.splitext(file_path)[1]:
            return file_path

        # 获取文件类型并补全扩展名
        file_type = self.get_file_type(file_path)
        if file_type:
            return f"{file_path}.{file_type}"

        return file_path  # 无法确定类型，返回原文件名

    # code edited from https://github.com/zz6zz666/astrbot_plugin_file_reader_pro
    # MIT License
    @filter.event_message_type(filter.EventMessageType.ALL)  # type: ignore
    async def on_receive_file(self, event: AstrMessageEvent):
        """当获取到有文件时"""
        messages = getattr(event.message_obj, "message", [])
        if not any(isinstance(item, Comp.File) for item in messages):
            return

        whitelist_sids = await self.get_kv_data("whitelist_sid", [])
        if event.unified_msg_origin not in whitelist_sids:
            return

        accept_prefix = self.config.get("accept_file_prefix") if self.config else None

        for item in messages:
            if not isinstance(item, Comp.File):  # 判断有无File组件
                continue

            remote_name = item.name or ""
            if accept_prefix and not remote_name.startswith(accept_prefix):
                continue

            try:
                file_path = await item.get_file()  # 获取文件
                if not file_path:
                    yield event.plain_result("文件获取失败")
                    continue

                _, raw_file_name = os.path.split(file_path)
                # 确保local_name只包含文件名，不包含路径
                local_name = os.path.basename(raw_file_name)

                # 获取完整文件名以确定正确的文件类型
                completed_name = self.complete_filename(file_path)
                # 检查文件类型是否支持
                file_ext = os.path.splitext(completed_name)[1][1:].lower() \
                    if os.path.splitext(completed_name)[1] else ""
                if file_ext and file_ext not in SUPPORT_EXTENSINS:
                    logger.warning(f"不支持的文件类型: {file_ext}")
                    yield event.plain_result(f"不支持的文件类型: {file_ext}")
                    continue

                file_size = os.path.getsize(file_path)
                logger.info(
                    f"接收到文件: {local_name}, 文件路径：{file_path}, 大小：{file_size / 1024 / 1024:.2f}MB")

                if file_ext == "json":
                    output_srt = file_path.rsplit(".", 1)[0] + ".srt"
                    process_intermediate_to_srt(file_path, output_srt)
                    yield event.chain_result([
                        Comp.File(name=os.path.basename(output_srt), file=output_srt)
                    ])
                    continue

                bucket, nls_client = self._build_nls_clients()
                intermediate_json = process_to_json(file_path, bucket, nls_client)
                output_srt = file_path.rsplit(".", 1)[0] + ".srt"
                process_intermediate_to_srt(intermediate_json, output_srt)
                yield event.chain_result([
                    Comp.File(name=os.path.basename(intermediate_json), file=intermediate_json),
                    Comp.File(name=os.path.basename(output_srt), file=output_srt),
                ])
            except ValueError as e:
                logger.error(f"配置错误: {str(e)}")
                yield event.plain_result(str(e))
            except Exception as e:
                logger.error(f"处理文件失败: {str(e)}")
                yield event.plain_result(f"处理文件失败: {str(e)}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("switch_caption")
    async def switch_caption(self, event: AstrMessageEvent):
        sid = event.unified_msg_origin
        whitelist_sids = await self.get_kv_data("whitelist_sid", [])
        if whitelist_sids is None:
            whitelist_sids = []

        if sid in whitelist_sids:
            whitelist_sids.remove(sid)
            await self.put_kv_data("whitelist_sid", whitelist_sids)
            yield event.plain_result("自动字幕已关闭")
            return

        whitelist_sids.append(sid)
        await self.put_kv_data("whitelist_sid", whitelist_sids)
        yield event.plain_result("自动字幕已开启")
