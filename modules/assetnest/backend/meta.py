"""元数据解析：A1111 / ComfyUI / InvokeAI / EXIF / safetensors。

只做只读解析，任何异常都不应中断索引。
"""
from __future__ import annotations

import json
import os
import re
import struct

from . import paths

MAX_TEXT = 8000
NEG_HINTS = ("worst quality", "low quality", "lowres", "bad anatomy", "watermark",
             "nsfw", "blurry", "bad hands", "text,", "deformed", "jpeg artifacts")

TEXT_ENCODE_CLASSES = {
    "CLIPTextEncode", "CLIPTextEncodeSDXL", "CLIPTextEncodeSDXLRefiner",
    "BNK_CLIPTextEncodeAdvanced", "TextEncodeQwenImageEdit", "TextEncodeQwenImageEditPlus",
    "T5TextEncode", "smZ CLIPTextEncode", "WanImageToTextEncode",
}


def _clean(s) -> str:
    if not isinstance(s, str):
        if s is None:
            return ""
        s = str(s)
    s = s.replace("\x00", "").strip()
    return s[:MAX_TEXT]


def _num(v, cast=float, default=0):
    try:
        return cast(v)
    except Exception:
        return default


def _split_params(line: str) -> dict:
    """按逗号切分 A1111 参数行，忽略引号内逗号。"""
    out, buf, quote = {}, [], False
    for ch in line:
        if ch == '"':
            quote = not quote
            continue
        if ch == "," and not quote:
            out_part = "".join(buf)
            buf = []
            if ":" in out_part:
                k, v = out_part.split(":", 1)
                out[k.strip()] = v.strip()
        else:
            buf.append(ch)
    tail = "".join(buf)
    if ":" in tail:
        k, v = tail.split(":", 1)
        out[k.strip()] = v.strip()
    return out


def parse_a1111(text: str) -> dict:
    text = _clean(text)
    if not text:
        return {}
    lines = text.splitlines()
    idx = None
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].lstrip().startswith("Steps:"):
            idx = i
            break
    params = _split_params(lines[idx]) if idx is not None else {}
    body = "\n".join(lines[:idx] if idx is not None else lines).strip()
    neg = ""
    m = re.search(r"(?:^|\n)Negative prompt:\s*", body)
    if m:
        pos = body[:m.start()].strip()
        neg = body[m.end():].strip()
    else:
        pos = body
    loras = []
    for mm in re.finditer(r"<lora:([^:>]+)(?::([-0-9.]+))?>", pos + " " + neg):
        name = mm.group(1).strip()
        if name and name not in [l[0] for l in loras]:
            loras.append((name, mm.group(2) or ""))
    size = params.get("Size", "")
    return {
        "positive": pos,
        "negative": neg,
        "model": params.get("Model", ""),
        "seed": params.get("Seed", ""),
        "sampler": params.get("Sampler", ""),
        "steps": _num(params.get("Steps", 0), int),
        "cfg": _num(params.get("CFG scale", 0)),
        "loras": [l[0] for l in loras],
        "meta": {
            "parser": "a1111",
            "size": size,
            "model_hash": params.get("Model hash", ""),
            "vae": params.get("VAE", ""),
            "clip_skip": params.get("Clip skip", ""),
            "denoise": params.get("Denoising strength", ""),
            "schedule": params.get("Schedule type", ""),
            "version": params.get("Version", ""),
            "params": params,
        },
    }


def _link_target(inputs: dict, key: str):
    v = inputs.get(key)
    if isinstance(v, list) and len(v) == 2 and isinstance(v[0], (str, int)):
        return str(v[0])
    return None


def _upstream_text(graph: dict, node_id: str, depth: int = 0) -> str:
    if depth > 8 or node_id not in graph:
        return ""
    node = graph[node_id]
    ins = node.get("inputs") or {}
    if isinstance(ins.get("text"), str):
        return ins["text"]
    for key in ("text", "text_g", "clip_l", "prompt", "string", "value", "conditioning"):
        tgt = _link_target(ins, key)
        if tgt:
            t = _upstream_text(graph, tgt, depth + 1)
            if t:
                return t
    for key, val in ins.items():
        tgt = _link_target(ins, key)
        if tgt:
            t = _upstream_text(graph, tgt, depth + 1)
            if t:
                return t
    return ""


def parse_comfy(prompt_text: str, wf_text: str = "") -> dict:
    graph = None
    for cand in (prompt_text, wf_text):
        if not cand:
            continue
        try:
            g = json.loads(cand)
        except Exception:
            continue
        if isinstance(g, dict) and g and all(isinstance(v, dict) for v in g.values()):
            if all("class_type" in v for v in g.values()):
                graph = g
                break
            if "nodes" in g and isinstance(g["nodes"], list):
                graph = {str(n.get("id")): {"class_type": n.get("type", ""),
                                            "inputs": n.get("widgets_values") and
                                            _widgets_to_inputs(n) or {},
                                            "_raw": n} for n in g["nodes"]}
                break
    if not graph:
        return {}
    texts, ckpt, loras = {}, "", []
    sampler = {"sampler": "", "steps": 0, "cfg": 0.0, "seed": "", "positive": "", "negative": ""}
    width = height = 0
    for nid, node in graph.items():
        ct = str(node.get("class_type") or "")
        ins = node.get("inputs") or {}
        if ct in TEXT_ENCODE_CLASSES or ct.endswith("CLIPTextEncode") or "TextEncode" in ct:
            t = _upstream_text(graph, nid)
            if t:
                texts[nid] = t
        if "CheckpointLoader" in ct or "UNETLoader" in ct or "CheckpointLoaderSimple" in ct:
            ckpt = ckpt or str(ins.get("ckpt_name") or ins.get("unet_name") or "")
        if "LoraLoader" in ct:
            name = ins.get("lora_name")
            if name and str(name) not in loras:
                loras.append(str(name))
        if "KSampler" in ct or ct.endswith("Sampler") or "SamplerCustom" in ct:
            sampler["sampler"] = str(ins.get("sampler_name") or sampler["sampler"])
            sampler["steps"] = _num(ins.get("steps", 0), int)
            sampler["cfg"] = _num(ins.get("cfg", 0))
            if ins.get("seed") not in (None, ""):
                sampler["seed"] = str(ins.get("seed"))
            elif ins.get("noise_seed") not in (None, ""):
                sampler["seed"] = str(ins.get("noise_seed"))
            ptgt = _link_target(ins, "positive")
            ntgt = _link_target(ins, "negative")
            if ptgt:
                sampler["positive"] = _upstream_text(graph, ptgt) or texts.get(ptgt, "")
            if ntgt:
                sampler["negative"] = _upstream_text(graph, ntgt) or texts.get(ntgt, "")
        if "EmptyLatentImage" in ct or "EmptySD3LatentImage" in ct:
            width = _num(ins.get("width", 0), int) or width
            height = _num(ins.get("height", 0), int) or height
    pos = sampler["positive"]
    neg = sampler["negative"]
    if not pos and texts:
        vals = list(texts.values())
        neg_first = [v for v in vals if any(h in v.lower() for h in NEG_HINTS)]
        rest = [v for v in vals if v not in neg_first]
        pos = (rest or vals)[0]
        neg = neg or (neg_first[0] if neg_first else "")
    if not neg and len(texts) > 1 and pos:
        others = [v for v in texts.values() if v != pos]
        cand = [v for v in others if any(h in v.lower() for h in NEG_HINTS)]
        neg = cand[0] if cand else (others[0] if others else "")
    return {
        "positive": _clean(pos),
        "negative": _clean(neg),
        "model": ckpt,
        "seed": sampler["seed"],
        "sampler": sampler["sampler"],
        "steps": sampler["steps"],
        "cfg": sampler["cfg"],
        "loras": [os.path.splitext(os.path.basename(l))[0] for l in loras],
        "meta": {"parser": "comfyui", "width": width, "height": height,
                 "nodes": len(graph), "loras": loras},
    }


def _widgets_to_inputs(node: dict) -> dict:
    """把 UI 格式的 widgets_values 粗映射为 inputs（仅用于兜底取文本）。"""
    wv = node.get("widgets_values")
    node_type = str(node.get("type") or "")
    if isinstance(wv, list) and wv and isinstance(wv[0], str) and "TextEncode" in node_type:
        return {"text": wv[0]}
    return {}


def parse_invoke(text: str) -> dict:
    try:
        data = json.loads(text)
    except Exception:
        return {}
    pos = ""
    try:
        steps = data["sd-metadata"]["image"]["steps"]
        pos = " ".join(s.get("prompt", "") for s in steps if isinstance(s, dict))
    except Exception:
        pass
    if not pos:
        try:
            pos = " ".join(p.get("prompt", "") for p in data.get("prompt", []))
        except Exception:
            return {}
    return {"positive": _clean(pos), "negative": "", "meta": {"parser": "invokeai"}}


def _exif_user_comment(im) -> str:
    try:
        ex = im.getexif()
        raw = ex.get(0x9286)
        if not raw:
            return ""
        if isinstance(raw, str):
            return raw
        raw = bytes(raw)
        if raw.startswith(b"UNICODE\x00"):
            return raw[8:].decode("utf-16-le", "ignore").strip("\x00")
        if raw.startswith(b"ASCII\x00\x00\x00"):
            return raw[8:].decode("utf-8", "ignore")
        if raw.startswith(b"\xef\xbb\xbf"):
            return raw[3:].decode("utf-8", "ignore")
        for enc in ("utf-8", "utf-16-le", "gbk"):
            try:
                t = raw.decode(enc).strip("\x00")
                if t and sum(ch.isprintable() or ch in "\n\r\t" for ch in t) > len(t) * 0.8:
                    return t
            except Exception:
                continue
    except Exception:
        pass
    return ""


def probe_image(path: str) -> dict:
    from PIL import Image

    out = {"width": 0, "height": 0}
    with Image.open(path) as im:
        out["width"], out["height"] = im.size
        txt = {}
        for k, v in (im.info or {}).items():
            if isinstance(v, str) and v.strip():
                txt[str(k)] = v
        if hasattr(im, "text"):
            try:
                for k, v in (im.text or {}).items():
                    if isinstance(v, str) and v.strip():
                        txt.setdefault(str(k), v)
            except Exception:
                pass
        comment = _exif_user_comment(im)
    if comment:
        txt.setdefault("exif:UserComment", comment)

    parsed = {}
    if txt.get("parameters"):
        parsed = parse_a1111(txt["parameters"])
    elif txt.get("exif:UserComment"):
        parsed = parse_a1111(txt["exif:UserComment"])
    if not parsed and (txt.get("prompt") or txt.get("workflow")):
        parsed = parse_comfy(txt.get("prompt", ""), txt.get("workflow", ""))
    if not parsed and txt.get("sd-metadata"):
        parsed = parse_invoke(txt["sd-metadata"])
    if not parsed:
        for key in ("Description", "Comment", "comment", "prompt", "Prompt"):
            val = txt.get(key)
            if isinstance(val, str):
                if val.lstrip().startswith("{") and ("class_type" in val or "nodes" in val):
                    parsed = parse_comfy(val)
                elif "Steps:" in val or val.strip():
                    parsed = parse_a1111(val)
                if parsed:
                    break
    merged = {**out, **parsed}
    meta = merged.get("meta") or {}
    meta["keys"] = sorted(txt.keys())[:20]
    if txt.get("Software"):
        meta["software"] = txt["Software"]
    merged["meta"] = meta
    return merged


def probe_video(path: str, ffmpeg: str = "") -> dict:
    return {}


def safetensors_meta(path: str) -> dict:
    """读取 safetensors 头部 __metadata__（LoRA 的 ss_ 字段）。"""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
            if len(head) < 8:
                return {}
            n = struct.unpack("<Q", head)[0]
            if n <= 0 or n > 64 * 1024 * 1024:
                return {}
            raw = f.read(n)
        hdr = json.loads(raw.decode("utf-8", "ignore"))
        md = hdr.get("__metadata__") or {}
        tensors = [k for k in hdr.keys() if k != "__metadata__"]
        return {"meta": md, "tensor_count": len(tensors),
                "dtype": hdr.get(tensors[0], {}).get("dtype", "") if tensors else ""}
    except Exception:
        return {}


def probe_model(path: str) -> dict:
    out = {"model": "", "meta": {}}
    if path.lower().endswith(".safetensors"):
        d = safetensors_meta(path)
        if d:
            md = {k: v for k, v in d["meta"].items() if k.startswith("ss_") or k in
                  ("modelspec.title", "modelspec.description", "format", "modelspec.architecture")}
            out["meta"] = {"parser": "safetensors", "tensors": d["tensor_count"],
                           "dtype": d["dtype"], **md}
            base = md.get("ss_base_model_version") or md.get("modelspec.architecture") or ""
            name = md.get("ss_output_name") or os.path.splitext(os.path.basename(path))[0]
            out["model"] = name
            parts = []
            if md.get("ss_network_module"):
                parts.append(str(md["ss_network_module"]).split(".")[-1])
            if md.get("ss_network_dim"):
                parts.append("dim " + str(md["ss_network_dim"]))
            if md.get("ss_network_alpha"):
                parts.append("alpha " + str(md["ss_network_alpha"]))
            if base:
                parts.append(str(base))
            out["positive"] = " · ".join(parts)
            tags = []
            if md.get("ss_tag_frequency"):
                try:
                    tf = json.loads(md["ss_tag_frequency"]) if isinstance(md["ss_tag_frequency"], str) \
                        else md["ss_tag_frequency"]
                    for bucket in tf.values():
                        if isinstance(bucket, dict):
                            tags += list(bucket.keys())
                except Exception:
                    pass
            out["meta"]["tags"] = tags[:40]
            out["meta"]["trigger"] = md.get("ss_trigger_words") or md.get("modelspec.trigger_words") or ""
    return out


def sidecar_for(path: str) -> dict:
    """同名 .txt / .json / .civitai.info 旁车信息。"""
    stem, ext = os.path.splitext(path)
    out = {}
    cands = [stem + ".txt", path + ".txt", stem + ".json", path + ".json",
             stem + ".civitai.info"]
    for cand in cands:
        if not os.path.isfile(cand):
            continue
        try:
            with open(cand, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read(200000)
        except Exception:
            continue
        if not text.strip():
            continue
        low = cand.lower()
        if low.endswith(".txt"):
            if "Steps:" in text or "Negative prompt:" in text:
                out.update(parse_a1111(text))
            out.setdefault("meta", {})["sidecar"] = os.path.basename(cand)
        elif low.endswith(".json") or low.endswith("civitai.info"):
            try:
                data = json.loads(text)
            except Exception:
                continue
            if isinstance(data, dict):
                if "class_type" in data or any(isinstance(v, dict) and "class_type" in v
                                               for v in data.values()):
                    out.update(parse_comfy(json.dumps(data)))
                if "prompt" in data and isinstance(data["prompt"], str):
                    out.setdefault("positive", data["prompt"])
                if "meta" in data and isinstance(data["meta"], dict):
                    m = data["meta"]
                    out.setdefault("positive", m.get("prompt", ""))
                    out.setdefault("negative", m.get("negativePrompt", ""))
                    out.setdefault("model", (data.get("model") or {}).get("name", "")
                                   if isinstance(data.get("model"), dict) else "")
                    out.setdefault("steps", _num(m.get("steps", 0), int))
                    out.setdefault("cfg", _num(m.get("cfgScale", 0)))
                    out.setdefault("seed", str(m.get("seed", "")))
                    out.setdefault("sampler", m.get("sampler", ""))
                    out.setdefault("meta", {})["civitai"] = True
                break
        out.setdefault("meta", {})["sidecar"] = os.path.basename(cand)
    return out


def extract(path: str, kind: str) -> dict:
    """统一入口，返回可写入 assets 的字段字典。"""
    result = {"width": 0, "height": 0, "duration": 0.0, "positive": "", "negative": "",
              "model": "", "seed": "", "sampler": "", "steps": 0, "cfg": 0.0, "loras": [],
              "meta": {}}
    try:
        if kind == "image":
            result.update(probe_image(path))
        elif kind == "model":
            result.update(probe_model(path))
    except Exception as e:
        result["meta"] = {"error": str(e)[:200]}
    try:
        sc = sidecar_for(path) if kind in ("image", "video") else {}
        if sc:
            meta = result.get("meta") or {}
            for k, v in sc.items():
                if k == "meta":
                    meta.update(v)
                elif v and not result.get(k):
                    result[k] = v
            result["meta"] = meta
    except Exception:
        pass
    meta = result.get("meta") or {}
    if result.get("loras"):
        meta["loras"] = result["loras"]
    result["meta"] = meta
    return result
