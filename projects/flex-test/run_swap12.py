import sys, json, time, glob
from pathlib import Path
R = Path(sys.argv[1]); S = Path(sys.argv[2])
sys.path.insert(0, str(R / "scripts"))
import runner, runner_spark
src = glob.glob(str(R / "outputs/*1793624126_88db*.mp4"))[0]
prompt = ("Replace the young woman with wavy brown hair and a beige cardigan in <Video 1> with the character from <Picture 1>. "
  "Keep the reference character face, hair, glasses, short beard and dark blue denim shirt from <Picture 1>, not the beige cardigan.\n\n"
  "integrated_multimodal_description: [Shot 1] A softly lit indoor medium close-up with a blurred wooden chair in the background, exactly as in <Video 1>. "
  "The man from <Picture 1> follows the pose, gaze, expression, lip movement, camera zoom and timing of <Video 1>: he looks slightly downward, then slowly lifts his gaze to the lens and speaks softly. Only this one man appears.")
job = {"id": "swap12_test", "title": "swap 12s test", "mode": "reference",
  "reference_images": [str(R / "projects/flex-test/swap_char.png")], "reference_audios": [], "reference_videos": [src],
  "character_swap": True, "aspect": "landscape", "text_encoder": "heretic", "first_frame_fit": "crop",
  "resolution": "draft", "prompt": prompt, "duration_seconds": 12, "seed": 164723, "output_name": "swap12_test.mp4"}
m = S / "swap12_manifest.json"; m.write_text(json.dumps({"jobs": [job]}, ensure_ascii=False), encoding="utf-8")
t = time.time()
res = runner.run_batch(m, session=None, gpu="A100", high_mem=True, stop_on_complete=True,
  progress_path=S / "swap12_progress.json", output_dir=S / "out", exec_timeout=3600, transport=runner_spark.SPARK)
print("ELAPSED", round(time.time() - t), "s"); print(json.dumps(res, ensure_ascii=False, indent=1))
