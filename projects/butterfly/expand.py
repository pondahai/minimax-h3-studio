"""把 storyboard.md 每段送 8002 擴寫成影片 prompt，輸出 prompts/SXX.txt。"""
import base64, json, re, sys, urllib.request
from pathlib import Path

HERE = Path(__file__).parent
URL = "http://100.89.149.50:8002/v1/chat/completions"

SYSTEM = """你是影片生成提示詞擴寫器。輸入是一段 12 秒以內的分鏡表（秒數區間、畫面、鏡頭、聲音）。
請輸出一段給文生影片模型用的中文提示詞，規則：
1. 必須逐條保留每個時間區段，格式「X–Y秒：…」，秒數不得合併、刪改或重排。
2. 每個區段補充細節：主體外觀、動作過程、表情、光線、色彩、質感、鏡頭運動。
3. 開頭用一句話寫整體風格：明亮日系兒童科普動畫風、色彩飽和、森林花園、柔和陽光。
4. 角色外觀固定：小明＝卡其探險帽、棕短髮、綠背心、藍背包；小美＝棕色雙馬尾、粉紅外套、紅格子衫；阿柴＝橘白柯基、綠色葉子領巾；蝴蝶＝橘黑相間的帝王斑蝶。
5. 不要寫台詞內容與字幕，不要在畫面中出現文字（循環圖示可用圖形箭頭表示）。
6. 若有「末幀」描述，最後一個區段要明確寫出最後畫面的構圖。
7. 附圖是原漫畫對應分格，只用來參考角色外觀、配色、場景與畫風；忽略圖中所有文字、對話框、編號與標題，
   動作與時間軸一律以分鏡表為準，不要加入分鏡表沒有的角色或情節。
8. 這部片的人聲另外用 TTS 配，影片音軌不能有任何人聲：結尾加一句「音訊：無對白、無人聲，只有自然環境音與輕快的兒童配樂」，
   角色描述不要寫說話、驚呼、喊叫等發聲動作，改寫成表情與肢體動作。
只輸出提示詞本身。"""

PANEL_DIR = Path(r"C:/Users/USER/AppData/Local/Temp/claude/C--Users-USER--claude-spares-spare-8GoJbr/887e5e5d-4281-4e05-aa9c-c44258457d77/scratchpad/butterfly")
PANELS = {"S01": "header", "S02": "panel-02", "S03": "panel-03", "S04": "panel-03", "S05": "panel-04",
          "S06": "panel-05", "S07": "panel-05", "S08": "panel-06", "S09": "panel-07", "S10": "panel-07"}


def shots():
    text = (HERE / "storyboard.md").read_text(encoding="utf-8")
    for block in re.split(r"\n(?=### S\d+)", text)[1:]:
        block = block.split("\n**總長")[0].strip()
        yield re.match(r"### (S\d+)", block).group(1), block


def expand(sid, block):
    img = base64.b64encode((PANEL_DIR / f"{PANELS[sid]}.png").read_bytes()).decode()
    user = [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img}"}},
            {"type": "text", "text": block}]
    body = json.dumps({
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        "temperature": 0.6, "max_tokens": 1500,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    req = urllib.request.Request(URL, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)["choices"][0]["message"]["content"].strip()


if __name__ == "__main__":
    out = HERE / "prompts"
    out.mkdir(exist_ok=True)
    only = set(sys.argv[1:])
    for sid, block in shots():
        if only and sid not in only:
            continue
        result = expand(sid, block)
        (out / f"{sid}.txt").write_text(result, encoding="utf-8")
        print(f"== {sid}\n{result}\n", flush=True)
