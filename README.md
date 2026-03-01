# NLS 自动字幕姬（astrbot_plugin_autocaption）

基于阿里云 NLS 语音转写 + OSS 的 AstrBot 插件。支持在指定会话中自动处理上传的音频文件，生成可编辑的中间 JSON 与 SRT 字幕。

## 功能

- 监听文件消息，按会话开关启用/停用自动字幕
- 音频文件：调用 NLS 生成中间 JSON，再转换为 SRT
- JSON 文件：直接转换为 SRT（用于二次编辑后重传）

## 依赖与前置条件

- **AstrBot** >= 4.18.3
- 可用的 **阿里云 OSS** 与 **NLS** 账号
- 本机可用的 `ffmpeg`（用于音频转码）

## 配置项

在 AstrBot 管理面板填写以下配置：

| 配置项 | 说明 | 是否必填 |
| --- | --- | --- |
| `ALI_ACCESSKEYID` | 阿里云 AccessKeyId | 必填 |
| `ALI_ACCESSKEYSECRET` | 阿里云 AccessKeySecret | 必填 |
| `ALI_APPKEY` | 阿里云 NLS AppKey | 必填 |
| `ALI_OSS_ENDPOINT` | OSS Endpoint | 必填 |
| `ALI_OSS_BUCKET` | OSS Bucket 名称 | 必填 |
| `ALI_OSS_INTERNAL_ENDPOINT` | OSS 内部 Endpoint/自定义链接 | 可选 |
| `accept_file_prefix` | 仅处理此前缀开头的文件名 | 可选（默认 `&caption`） |

## 使用方法

1. 在目标会话中由管理员执行：
   ```
   /switch_caption
   ```
   该命令用于切换当前会话是否启用自动字幕。

2. 发送文件，文件名需以配置的前缀开头（默认 `&caption`）：
   - `&caption 会议录音.mp3`

3. 处理结果：
   - **音频文件**：返回 `*_intermediate.json` 与 `*.srt`
   - **JSON 文件**：返回 `*.srt`

> 你可以编辑返回的 `*_intermediate.json` 后重新发送（仍需前缀），以生成更符合需求的 SRT。

## 支持的文件类型

- 音频：`mp3`, `wav`, `flac`, `aac`, `ogg`, `m4a`
- JSON：`json`（中间结果）

## 注意事项

- 文件会先上传至 OSS，NLS 与 OSS 可能产生费用。
- 缺少必填配置时会直接返回错误提示。
