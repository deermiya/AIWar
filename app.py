"""
AI 狼人杀 - Flask 后端
用法：
  1. pip install flask requests google-genai python-dotenv
  2. 在下方填入你的 API Key
  3. python app.py
  4. 浏览器打开 http://localhost:15000
"""

from flask import Flask, request, jsonify, send_file, Response
import requests
import time
import os
import asyncio
from google import genai
from dotenv import load_dotenv

# 加载 .env 配置文件
load_dotenv()

app = Flask(__name__)

# ╔══════════════════════════════════════════════╗
# ║        在这里填入你的 API Key                ║
# ╚══════════════════════════════════════════════╝

DOUBAO_KEY     = os.environ.get("DOUBAO_KEY")
DEEPSEEK_KEY   = os.environ.get("DEEPSEEK_KEY")
GEMINI_KEY     = os.environ.get("GEMINI_KEY")
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY")




# ╔══════════════════════════════════════════════╗
# ║        各 AI 的 API 配置                     ║
# ╚══════════════════════════════════════════════╝

PROVIDERS = {
    "Doubao": {
        "url":   "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
        "key":   DOUBAO_KEY,
        "model": "doubao-seed-character-251128",
    },
    "DeepSeek": {
        "url":   "https://api.deepseek.com/chat/completions",
        "key":   DEEPSEEK_KEY,
        "model": "deepseek-chat",
    },
    "Gemini": {
        "url":   "https://openrouter.ai/api/v1/chat/completions",
        "key":   OPENROUTER_KEY,
        "model": "google/gemini-3-flash-preview",
    },
    "ChatGPT": {
        "url":   "https://openrouter.ai/api/v1/chat/completions",
        "key":   OPENROUTER_KEY,
        "model": "openai/gpt-5.4",
    },
    "Claude": {
        "url":   "https://openrouter.ai/api/v1/chat/completions",
        "key":   OPENROUTER_KEY,
        "model": "anthropic/claude-sonnet-4.6",
    },
    "Grok": {
        "url":   "https://openrouter.ai/api/v1/chat/completions",
        "key":   OPENROUTER_KEY,
        "model": "x-ai/grok-4.20",
    },
}



# ╔══════════════════════════════════════════════╗
# ║  本地 TTS 音色配置（CosyVoice API 模式）     ║
# ╚══════════════════════════════════════════════╝
# CosyVoice (刘悦版) 提供两种模式：
# 1. 预设音色：直接写 speaker 的名字，例如 "中文女", "中文男", "joker老师"
# 2. 零样本克隆：提供 ref_audio_path（参考音频路径）和 prompt_text（参考文本）

COSYVOICE_URL = "http://127.0.0.1:9880"
BASE_AUDIO_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "ref_audios"))

VOICE_MAP = {
    "Doubao": {
        "speaker": "豆包1",
    },
    "DeepSeek": {
        "speaker": "书折",
    },
    "ChatGPT": {
        "speaker": "jok老师",
    },
    "Claude": {
        "speaker": "东北大哥",
    },
    "Gemini": {
        "speaker": "王力宏1号",
    },
    "Grok": {
        "speaker": "四川女声",
    },
}


@app.route("/")
def index():
    return send_file("index.html")


@app.route("/static/icons/<path:filename>")
def serve_icon(filename):
    return send_file(os.path.join("static", "icons", filename))


@app.route("/api/chat", methods=["POST"])
def chat():
    """通用聊天接口，前端传 player 名字 + prompt，后端路由到对应 API"""
    data = request.json
    player = data.get("player", "")
    system_msg = data.get("system", "")
    user_msg = data.get("message", "")

    if player not in PROVIDERS:
        return jsonify({"error": f"未知玩家: {player}"}), 400

    cfg = PROVIDERS[player]


    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cfg['key']}",
    }

    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": 500,
        "temperature": 0.9,
    }

    try:
        resp = requests.post(cfg["url"], headers=headers, json=payload, timeout=60)
        if resp.status_code == 429:
            time.sleep(4)
            resp = requests.post(cfg["url"], headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        result = resp.json()
        if "choices" not in result:
            err = result.get("error", {})
            msg = err.get("message", str(result)) if isinstance(err, dict) else str(err)
            return jsonify({"error": f"{player}: {msg}"}), 500
        content = result["choices"][0]["message"]["content"]
        return jsonify({"content": content, "player": player, "model": cfg["model"]})
    except requests.exceptions.Timeout:
        return jsonify({"error": f"{player} 响应超时"}), 504
    except Exception as e:
        return jsonify({"error": f"{player}: {str(e)}"}), 500


TTS_CACHE = {}

@app.route("/api/tts", methods=["POST"])
def tts():
    """文字转语音接口，代理到本地 CosyVoice"""
    data = request.json
    player = data.get("player", "")
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "文本为空"}), 400

    cache_key = (player, text)
    if cache_key in TTS_CACHE: 
        return Response(TTS_CACHE[cache_key], mimetype="audio/wav")

    cfg = VOICE_MAP.get(player)
    if not cfg:
        return jsonify({"error": f"找不到玩家 {player} 的音色配置"}), 400

    # 构建匹配刘悦版 CosyVoice 的 payload
    payload = {
        "text": text
    }
    if "speaker" in cfg:
        payload["speaker"] = cfg["speaker"]
    elif "ref_audio_path" in cfg:
        payload["ref_audio_path"] = cfg["ref_audio_path"]
        payload["prompt_text"] = cfg.get("prompt_text", "")

    try:
        # 刘悦的 CosyVoice 服务默认将兼容 API 挂在 9880
        resp = requests.post(COSYVOICE_URL + "/", json=payload, timeout=60)
        
        # 捕捉 500 内部错误，通常是因为音色不存在或音频路径不对
        if resp.status_code == 500:
            return jsonify({"error": f"CosyVoice 生成失败，请检查音色名(speaker)或参考音频路径是否正确"}), 500
            
        resp.raise_for_status()
        audio = resp.content
        TTS_CACHE[cache_key] = audio
        return Response(audio, mimetype="audio/wav")
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"本地 TTS 异常: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"error": f"TTS: {str(e)}"}), 500

@app.route("/api/health")
def health():
    """检查各 API 配置状态"""
    status = {}
    for name, cfg in PROVIDERS.items():
        has_key = cfg["key"] not in ("", "在这里填入你的Key")
        status[name] = {
            "model": cfg["model"],
            "key_configured": has_key,
            "url": cfg["url"],
        }
    return jsonify(status)


if __name__ == "__main__":
    print("\nDEER杯AI狼人杀 服务器启动中...")
    print("打开浏览器访问: http://localhost:15000")
    print("按 Ctrl+C 停止服务器\n")
    app.run(debug=True, port=15000)
