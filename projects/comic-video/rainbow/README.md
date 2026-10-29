# 《彩虹為什麼會出現？》

漫畫轉影片工作流的第三篇（待驗收）。腳本與流程見上層 [`comic-video/README.md`](../README.md)，復盤筆記見 [docs/comic-to-video-workflow.md](../../../docs/comic-to-video-workflow.md)。

- 來源：社子文教基金會「科學天地／自然小探險隊」[《彩虹為什麼會出現？》](https://shezi.org.tw/science/rainbow/)（7 格）
- 規格：10 段 120 秒、672×384 草稿等級；S07 續接 S06 末幀，其他段用 Qwen-Image 首幀；S02 加尾幀（首尾幀）

## 這篇的檔案

| 檔案 | 內容 |
|---|---|
| `config.json` | 角色、聲音、分格對應（含切塊）、每格角色 `panel_cast`、段落表 |
| `storyboard.md` | 分鏡（人寫，含原作處理） |
| `storyboard_8002*.md` | 8002 寫分鏡的試驗稿：整篇送、逐格第一版、逐格第二版（含每輪原始輸出） |
| `prompts/`、`frame_prompts/` | 影片 prompt（含配樂 `music_official.txt`）、首幀與尾幀 prompt |
| `review.json` | 首幀建議 seed 與理由 |
| `audio/lines.json`、`rainbow.srt` | 台詞排定時間、字幕 |

## 這篇的決定

- 四個角色的聲音都沿用《密度》
- 阿柴在原作有台詞，改給小明；第 4 格的虛線圓示意圖改成旁白；杯子改塑膠杯並加「不要直視太陽」
- 首幀：S01 seed1、S02 seed1、S03 seed3、S04 seed1、S05 seed3、S06 seed3、S08 seed3、S09 seed3、S10 seed3；S02 尾幀 seed2
- 重跑：S02（小美外觀走樣 → 加尾幀）、S05（太陽出現在彩虹前方 → 兩次才修好）、S07（續接後變室內 → 改 prompt 場景）
- 配樂：music1（seed 1，鐵琴＋烏克麗麗＋鋼琴）
