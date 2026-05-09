import asyncio
import logging
import re

from PIL import Image
from browseruse_bench.eval.model import encode_image

from browseruse_bench.utils import (
    load_eval_config,
    load_prompt,
    make_template_prompt,
    make_text_prompt,
)

logger = logging.getLogger(__name__)

# Load eval configuration (returns {} if file missing — all .get() have fallbacks)
_EVAL_CFG = load_eval_config("Online-Mind2Web")
_PROMPT_DIR = _EVAL_CFG.get("prompt_dir", "browseruse_bench/eval/online_mind2web/prompts")
MAX_IMAGE = _EVAL_CFG.get("api_max_images", 50)
_DETAIL = _EVAL_CFG.get("detail", "high")

# Pre-load all prompt templates and their PromptRefs at module level
_kp_system, _kp_system_ref = load_prompt(
    f"{_PROMPT_DIR}/identify_key_points_system.txt"
)
_kp_user, _kp_user_ref = load_prompt(
    f"{_PROMPT_DIR}/identify_key_points_user.txt"
)
_ji_system, _ji_system_ref = load_prompt(
    f"{_PROMPT_DIR}/judge_image_system.txt"
)
_ji_user, _ji_user_ref = load_prompt(
    f"{_PROMPT_DIR}/judge_image_user.txt"
)
_wj_system, _wj_system_ref = load_prompt(
    f"{_PROMPT_DIR}/webjudge_system.txt"
)
_wj_user, _wj_user_ref = load_prompt(
    f"{_PROMPT_DIR}/webjudge_user.txt"
)
_wj_user_no_img, _wj_user_no_img_ref = load_prompt(
    f"{_PROMPT_DIR}/webjudge_user_no_images.txt"
)


async def identify_key_points(task, model):
    text = _kp_user.format(task=task)
    messages = [
            {"role": "system", "content": _kp_system},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": text}
                ],
            }
        ]
    responses = await asyncio.to_thread(model.generate, messages)
    return responses[0]

async def judge_image(task, image_path, key_points, model):
    jpg_base64_str = encode_image(Image.open(image_path))

    text = _ji_user.format(task=task, key_points=key_points)

    messages = [
            {"role": "system", "content": _ji_system},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": text},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{jpg_base64_str}", "detail": _DETAIL},
                    },
                ],
            }
        ]

    responses = await asyncio.to_thread(model.generate, messages)
    return responses[0]

async def WebJudge_Online_Mind2Web_eval(task, last_actions, images_path, model, score_threshold):

    key_points = await identify_key_points(task, model)
    key_points = key_points.replace("\n\n", "\n")

    try:
        key_points = key_points.split("**Key Points**:")[1]
        key_points = "\n".join(line.lstrip() for line in key_points.splitlines())
    except Exception:
        key_points = key_points.split("Key Points:")[-1]
        key_points = "\n".join(line.lstrip() for line in key_points.splitlines())

    tasks = [judge_image(task, image_path, key_points, model) for image_path in images_path]
    image_responses = await asyncio.gather(*tasks)

    whole_content_img = []
    whole_thoughts = []
    record = []
    pattern = r"[1-5]"
    for response, image_path in zip(image_responses, images_path, strict=False):
        try:
            score_text = response.split("Score")[1]
            thought = response.split("**Reasoning**:")[-1].strip().lstrip("\n").split("\n\n")[0].replace('\n',' ')
            score = re.findall(pattern, score_text)[0]
            record.append({"Response": response, "Score": int(score)})
        except Exception as e:
            logger.error(f"Error processing response: {e}")
            score = 0
            record.append({"Response": response, "Score": 0})

        if int(score) >= score_threshold:
            jpg_base64_str = encode_image(Image.open(image_path))
            whole_content_img.append(
                {
                    'type': 'image_url',
                    'image_url': {"url": f"data:image/png;base64,{jpg_base64_str}", "detail": _DETAIL}
                }
            )
            if thought != "":
                whole_thoughts.append(thought)

    whole_content_img = whole_content_img[:MAX_IMAGE]
    whole_thoughts = whole_thoughts[:MAX_IMAGE]

    # Choose user prompt template based on whether images are available
    if len(whole_content_img) == 0:
        prompt = _wj_user_no_img
        user_prompt_ref = _wj_user_no_img_ref
    else:
        prompt = _wj_user
        user_prompt_ref = _wj_user_ref

    text = prompt.format(task=task, last_actions="\n".join(f"{i+1}. {action}" for i, action in enumerate(last_actions)), key_points=key_points, thoughts = "\n".join(f"{i+1}. {thought}" for i, thought in enumerate(whole_thoughts)))

    system_msg = _wj_system

    messages = [
        {"role": "system", "content": system_msg},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": text}]
                + whole_content_img
        }
    ]

    # Build PromptSnapshot objects for traceability
    user_prompt_params = {
        "task": task,
        "last_actions": "\n".join(f"{i+1}. {action}" for i, action in enumerate(last_actions)),
        "key_points": key_points,
        "thoughts": "\n".join(f"{i+1}. {thought}" for i, thought in enumerate(whole_thoughts)),
    }
    prompt_snapshots = {
        "identify_key_points_system": make_text_prompt(_kp_system, _kp_system_ref),
        "identify_key_points_user": make_template_prompt(_kp_user, _kp_user_ref, {"task": task}),
        "judge_image_system": make_text_prompt(_ji_system, _ji_system_ref),
        "judge_image_user": make_template_prompt(
            _ji_user, _ji_user_ref, {"task": task, "key_points": key_points}
        ),
        "webjudge_system": make_text_prompt(_wj_system, _wj_system_ref),
        "webjudge_user": make_template_prompt(prompt, user_prompt_ref, user_prompt_params),
    }

    return messages, text, system_msg, record, key_points, prompt_snapshots
