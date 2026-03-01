import json

from astrbot.core import LogManager

from .SDKs.nls_python_demo import NLSClient
from .SDKs.oss_python_demo import AliOSSBucket

logger = LogManager.GetLogger(log_name="astrbot")


def format_time(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    milliseconds = int((seconds - int(seconds)) * 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{milliseconds:03}"


def parse_nls_to_intermediate(response: dict, output_json: str):
    """
    将 nls 的结果解析为一种简化的中间 JSON 格式，包含原句信息和对应的词块。
    用户可以方便地修改这个中间文件中的词块(Text)。
    """
    words = response["Result"]["Words"]
    sentences = response["Result"]["Sentences"]

    intermediate_data = []

    for sentence in sentences:
        s_text = sentence["Text"]
        s_words = [w for w in words if w["BeginTime"] >= sentence["BeginTime"] and w["EndTime"] <= sentence["EndTime"]]

        words_list = []
        text_ptr = 0
        for w in s_words:
            w_len = len(w["Word"])
            match_idx = s_text.find(w["Word"], text_ptr)
            word_with_punct = w["Word"]
            if match_idx != -1:
                text_ptr = match_idx + w_len
                # 向后找标点
                while text_ptr < len(s_text) and s_text[text_ptr] in "，。,.？！?!":
                    word_with_punct += s_text[text_ptr]
                    text_ptr += 1
            words_list.append({
                "BeginTime": w["BeginTime"],
                "EndTime": w["EndTime"],
                "Text": word_with_punct
            })

        intermediate_data.append({
            "OriginalSentence": s_text,
            "Words": words_list
        })

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(intermediate_data, f, ensure_ascii=False, indent=4)


def process_intermediate_to_srt(input_json: str, output_srt: str, max_len: int = 20):
    """
    读取中间 JSON 文件并生成srt
    """
    interjections = {"啊", "呀", "呢", "吧", "嘻嘻", "哦", "嗯", "哎", "哇", "哈", "哼", "嗨", "哟", "呜", "嘘", "喂",
                     "嘛", "呃", "哎呀", "哎哟", "啦", "嘛", "惹"}

    with open(input_json, "r", encoding="utf-8") as f:
        intermediate_data = json.load(f)

    out_lines = []
    tokens = []

    # 将所有的 blocks 拍平，依据强标点重新断句
    for block in intermediate_data:
        for w in block.get("Words", []):
            begin = w["BeginTime"]
            end = w["EndTime"]
            word_with_punct = w["Text"]

            keep_punct = ""
            has_space = False
            word_clean = ""
            has_strong_stop = False

            for c in word_with_punct:
                if c in "，。,.":
                    has_space = True
                    if c in "。.":
                        has_strong_stop = True
                elif c in "？！?!":
                    keep_punct += c
                    has_strong_stop = True
                else:
                    word_clean += c

            is_interj = word_clean.strip() in interjections

            tokens.append({
                "word": word_clean,
                "begin": begin,
                "end": end,
                "has_space": has_space,
                "keep_punct": keep_punct,
                "is_interj": is_interj,
                "has_strong_stop": has_strong_stop
            })

    sentences_tokens = []
    current_sentence = []
    for t in tokens:
        current_sentence.append(t)
        if t["has_strong_stop"]:
            sentences_tokens.append(current_sentence)
            current_sentence = []
    if current_sentence:
        sentences_tokens.append(current_sentence)

    for sentence_tokens in sentences_tokens:
        if not sentence_tokens:
            continue

        full_text = "".join(
            t["word"] + t["keep_punct"] + (" " if t["has_space"] else "") for t in sentence_tokens).strip()
        char_count = len(full_text.replace(" ", ""))

        has_isolated_interj = False
        for i, t in enumerate(sentence_tokens):
            prev_has_space = (i > 0 and sentence_tokens[i - 1]["has_space"]) or i == 0
            if t["is_interj"] and prev_has_space and (t["has_space"] or i == len(sentence_tokens) - 1):
                has_isolated_interj = True
                break

        # 单行最大字数限制
        MAX_LEN = max_len

        # 允许最多到MAX_LEN字不强行切割
        if char_count <= MAX_LEN and not has_isolated_interj:
            out_lines.append((sentence_tokens[0]["begin"], sentence_tokens[-1]["end"], full_text))
        else:
            current_line = []
            current_len = 0

            for i, t in enumerate(sentence_tokens):
                t_str = t["word"] + t["keep_punct"] + (" " if t["has_space"] else "")
                t_len = len(t["word"]) + len(t["keep_punct"])  # 计算实际字数时不包含空格

                prev_has_space = (i > 0 and sentence_tokens[i - 1]["has_space"]) or i == 0
                is_isolated_interj = t["is_interj"] and prev_has_space and (
                        t["has_space"] or i == len(sentence_tokens) - 1)

                if is_isolated_interj:
                    if current_line:
                        text = "".join(
                            x["word"] + x["keep_punct"] + (" " if x["has_space"] else "") for x in current_line).strip()
                        if text:
                            out_lines.append((current_line[0]["begin"], current_line[-1]["end"], text))
                        current_line = []
                        current_len = 0

                    text = (t["word"] + t["keep_punct"]).strip()
                    if text:
                        out_lines.append((t["begin"], t["end"], text))
                    continue

                # 如果加上当前词会超过20字，强制在此切分
                if current_len + t_len > MAX_LEN and current_line:
                    text = "".join(
                        x["word"] + x["keep_punct"] + (" " if x["has_space"] else "") for x in current_line).strip()
                    out_lines.append((current_line[0]["begin"], current_line[-1]["end"], text))
                    current_line = [t]
                    current_len = t_len
                else:
                    current_line.append(t)
                    current_len += t_len

                # 如果超长句被切分时，遇到自然停顿（空格，原逗号句号）直接切分，不再要求最低字数，以防把后续内容和前一段硬凑导致越界错位
                if t["has_space"]:
                    text = "".join(
                        x["word"] + x["keep_punct"] + (" " if x["has_space"] else "") for x in current_line).strip()
                    out_lines.append((current_line[0]["begin"], current_line[-1]["end"], text))
                    current_line = []
                    current_len = 0

            if current_line:
                text = "".join(
                    x["word"] + x["keep_punct"] + (" " if x["has_space"] else "") for x in current_line).strip()
                if text:
                    out_lines.append((current_line[0]["begin"], current_line[-1]["end"], text))

    with open(output_srt, "w", encoding="utf-8") as file_srt:
        for i, (begin, end, text) in enumerate(out_lines):
            startTime = begin / 1000
            endTime = end / 1000
            file_srt.write(f"{i + 1}\n")
            file_srt.write(f"{format_time(startTime)} --> {format_time(endTime)}\n")
            file_srt.write(f"{text}\n\n")


def process_to_json(file_path: str, bucket: AliOSSBucket, nls_client: NLSClient) -> str:
    intermediate_name = file_path.rsplit(".", 1)[0] + "_intermediate.json"

    logger.info(f"Starting NLS processing for {file_path}...")
    response = nls_client.run_nls(bucket, file_path)

    with open(file_path.rsplit(".", 1)[0] + "_nls_raw.json", "w", encoding="utf-8") as f:
        json.dump(response, f, ensure_ascii=False, indent=4)

    logger.info("Parsing NLS response to intermediate JSON...")
    parse_nls_to_intermediate(response, intermediate_name)
    logger.info(f"Intermediate JSON generated: {intermediate_name}")

    return intermediate_name
