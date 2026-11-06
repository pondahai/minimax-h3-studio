# 八戒的台詞改原速：align.json 裡八戒那幾句只留首錨點，尾錨點照 TTS 原長（atempo=1）
import json,sys
p=sys.argv[1];A=json.load(open(p,encoding='utf8'))
for k,v in A.items():
    if '八戒' in k:
        (t0,v0),(t1,_)=v[0],v[-1]; A[k]=[[t0,v0],[t1,round(v0+t1-t0,3)]]; print(k,A[k])
json.dump(A,open(p,'w',encoding='utf8'),ensure_ascii=False)
