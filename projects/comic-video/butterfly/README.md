# 《蝴蝶生命循環》

漫畫轉影片工作流的第一篇。腳本與流程見上層 [`comic-video/README.md`](../README.md)，復盤筆記見 [docs/comic-to-video-workflow.md](../../../docs/comic-to-video-workflow.md)。

- 來源：社子文教基金會「科學天地／自然小探險隊」[《蝴蝶生命循環》](https://shezi.org.tw/science/butterfly-life-cycle/)（7 格）
- 成品：約 119 秒、672×384 草稿等級，10 段（S03、S05、S07 續接前段末幀；S10 用 Qwen-Image 首幀重做）

## 這篇的檔案

| 檔案 | 內容 |
|---|---|
| `config.json` | 角色、聲音、分格對應、段落表（`shots`） |
| `storyboard.md` | 分鏡：每段 ≤12 秒、秒級時間軸、台詞 |
| `prompts/` | 影片 prompt 定稿（`music.txt` 是配樂）；`prompts_text/` 是純文字擴寫備份 |
| `frame_prompts/S10_first.txt` | S10 首幀的 Qwen-Image prompt |
| `audio/lines.json` | 台詞、音檔、起秒、長度（合成與字幕的依據） |
| `butterfly.srt` | 繁體中文字幕 |

## 和現行流程不同的地方

這篇是流程定案前做的，有幾處和現在的做法不同：

- 大多數獨立段用 t2va，沒有先做首幀（畫風不一致的問題就是這樣來的）
- 送 TTS 沒有轉簡體（`config.json` 的 `t2s` 為 false），多音字用 `pronounce` 換字
- 沒有分鏡審查頁
