# 《密度是什麼？一樣大，不一定一樣重！》

漫畫轉影片工作流的第二篇（製作中）。腳本與流程見上層 [`comic-video/README.md`](../README.md)，復盤筆記見 [docs/comic-to-video-workflow.md](../../../docs/comic-to-video-workflow.md)。

- 來源：社子文教基金會「科學天地／自然小探險隊」[《密度是什麼？》](https://shezi.org.tw/science/density/)（7 格）
- 規格：11 段約 130 秒、672×384 草稿等級；S01、S03、S05、S06、S07、S09、S11 用 Qwen-Image 首幀，S02、S04、S08、S10 續接前段末幀

## 這篇的檔案

| 檔案 | 內容 |
|---|---|
| `config.json` | 角色、聲音、分格對應、段落表（`shots`） |
| `storyboard.md` | 分鏡（含原作勘誤） |
| `prompts/`、`frame_prompts/` | 影片 prompt、首幀 prompt |
| `review.json` | 分鏡審查的建議 seed 與理由（`review.py` 讀） |
| `audio/lines.json` | 台詞、音檔、起秒、長度 |

## 這篇的決定

- 小明、小美、旁白沿用《蝴蝶》的參考音；林博士選台灣腔候選（TW2）
- 原作第 4 格石頭標「密度比水小」，應為比水大，台詞已改正
- S08「湯匙」繁體送 TTS 唸不出來，轉簡體才正確 → 從這篇起送 TTS 一律轉簡體
- 首幀選定：S01 seed2、S03 seed2、S05 seed2、S06 seed3、S07 seed2、S09 seed3、S11 seed2
