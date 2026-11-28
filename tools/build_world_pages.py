"""Dựng world1.html / world2.html từ hai bản thiết kế (Evergrove Realm, Frostveil Caverns) và nối với luồng học thật.

Bản thiết kế là trang độc lập (ảnh nhúng sẵn, tiến độ chỉ nằm trong bộ nhớ). Script này chèn:
  - CSS/JS của web (auth, tiến độ, trợ lý AI, từ điển, từ vựng đã học, hướng dẫn) vào <head>;
  - js/pages/world-adventure.js: khôi phục tiến độ đã lưu và mở trợ lý AI khi bấm level;
  - vài sửa nhỏ trong mã thiết kế (bấm level -> mở bài học thật; chỉ hoạt hình qua màn khi đã PASS; nút quay lại về trang chủ).
Mỗi lần thay thế đều kiểm tra đúng một chỗ khớp, sai là dừng (không ghi đè trang đang chạy).

Chạy: python tools/build_world_pages.py <Evergrove_Realm.html> <Frostveil_Caverns.html>
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VER = "20261128n"

HEAD = """
<link rel="icon" type="image/png" href="assets/images/logoioc.png?v=1">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700&display=swap">
<link rel="stylesheet" href="css/style.css?v={v}">
<link rel="stylesheet" href="css/world-map.css?v={v}">
<link rel="stylesheet" href="css/chatbot.css?v={v}">
<style>
/* Lớp của web nằm trên bản đồ thiết kế */
.ai-chat-overlay{{z-index:10000!important}}
#iocLocked{{position:fixed;inset:0;z-index:60;display:grid;place-items:center;background:rgba(255,255,255,.94);backdrop-filter:blur(3px)}}
#iocLocked[hidden]{{display:none}}
#iocLocked .ioc-lk-card{{max-width:420px;margin:16px;text-align:center;font-family:"Be Vietnam Pro",system-ui,sans-serif;color:#3A2B33}}
#iocLocked .ioc-lk-ic{{width:56px;height:56px;margin:0 auto 10px;color:#9C8E95}}
#iocLocked h2{{font:800 26px "Baloo 2","Trebuchet MS",sans-serif;margin:0 0 8px}}
#iocLocked p{{margin:0 0 16px;line-height:1.55;color:#6E5A63}}
.hint{{z-index:61!important}}
.world-map-vocab-btn,.world-map-guide-btn{{z-index:9000!important;position:fixed!important;right:16px!important;left:auto!important;top:auto!important}}
.world-map-vocab-btn{{bottom:calc(16px + env(safe-area-inset-bottom,0px))!important}}
.world-map-guide-btn{{bottom:calc(64px + env(safe-area-inset-bottom,0px))!important}}
</style>
<script src="js/features/theme.js?v={v}"></script>
<script src="js/features/playtime.js?v={v}"></script>
<script src="js/features/course-progress.js?v={v}"></script>
<script src="js/features/question-history.js?v={v}"></script>
<script src="js/features/auth.js?v={v}"></script>
<script src="js/features/gesture.js?v={v}"></script>
<script src="js/features/chatbot.js?v={v}"></script>
<script src="js/features/dictionary.js?v={v}"></script>
<script src="js/features/vocab-list.js?v={v}"></script>
<script src="js/features/grading-guide.js?v={v}"></script>
<script src="js/features/sound-effects.js?v={v}"></script>
<script src="js/pages/world-adventure.js?v={v}"></script>
""".format(v=VER)


def rep(s: str, old: str, new: str, count: int = 1) -> str:
    n = s.count(old)
    if n != count:
        raise SystemExit(f"Không khớp ({n} chỗ, cần {count}): {old[:90]!r}")
    return s.replace(old, new)


def build_world1(src: str) -> str:
    s = rep(src, '<!doctype html><html lang="vi"><head>', '<!doctype html><html lang="vi" data-world="world-1"><head>' + HEAD)
    # Bấm level đang mở -> bài học thật; chỉ khi PASS mới chạy hoạt hình qua màn. Cổng (bước 0) và rương giữ như thiết kế.
    s = rep(s, "if(j===cur){ k==='chest'?openChest(j):complete(j); return }\n  const b=document.querySelector(`.node[data-j=\"${j}\"]`);",
            "if(j===cur){ if(k==='chest'){ openChest(j); return } if(steps[j].dn){ if(window.__iocPlay) window.__iocPlay(steps[j].dn,false,()=>complete(j)); return } complete(j); return }\n"
            "  if(done[j]&&steps[j].dn&&window.__iocPlay){ window.__iocPlay(steps[j].dn,true,null); return }\n"
            "  const b=document.querySelector(`.node[data-j=\"${j}\"]`);")
    # Khôi phục tiến độ đã lưu (số level đã PASS) sau khi bản đồ dựng xong.
    # Bấm sang mùa chưa tới: KHÔNG mở khóa (bản thiết kế đánh dấu xong mọi level trước đó). Hiện màn trắng "chưa mở".
    s = rep(s, "function jumpTo(k){ if(!AC) initAudio(); const S=SEASONS[k];\n  if(cur<S.first){ for(let j=0;j<S.first;j++) if(!done[j]) done[j]=steps[j].t==='chest'?true:(Math.random()<.6?3:2); KEYS.forEach(x=>{ if(SEASONS[x].first<=S.first) known[x]=true }); cur=S.first; $('mapBtn').hidden=false; $('intro').hidden=true }\n  showSeason(k);",
            "function iocLock(k){ let o=document.getElementById('iocLocked');\n"
            "  if(!k){ if(o) o.hidden=true; return }\n"
            "  if(!o){ o=document.createElement('div'); o.id='iocLocked'; o.innerHTML='<div class=\"ioc-lk-card\"><div class=\"ioc-lk-ic\">'+ICON.lock+'</div><h2 id=\"iocLkT\"></h2><p id=\"iocLkP\"></p><button class=\"cta\" id=\"iocLkB\"></button></div>'; document.body.appendChild(o);\n"
            "    document.getElementById('iocLkB').addEventListener('click',()=>{ iocLock(null); showSeason(steps[cur].s); setTimeout(()=>scrollToStep(cur,false),40) }) }\n"
            "  const now=steps[cur].s; document.getElementById('iocLkT').textContent=SEASONS[k].name+' chưa mở';\n"
            "  document.getElementById('iocLkP').textContent='Hoàn thành các level của mùa '+SEASONS[now].name+' để mở khóa mùa tiếp theo. Mỗi level chỉ mở khi bạn làm xong level trước.';\n"
            "  document.getElementById('iocLkB').textContent='Quay lại '+SEASONS[now].name; o.hidden=false; SFX.deny() }\n"
            "function jumpTo(k){ if(!AC) initAudio(); const S=SEASONS[k];\n  if(cur<S.first){ iocLock(k); return }\n  iocLock(null); showSeason(k);")
    s = rep(s, "$('goSpring').addEventListener('click',()=>{ if(!AC) initAudio(); showSeason('spring') });",
            "$('goSpring').addEventListener('click',()=>{ if(!AC) initAudio(); iocLock(null); showSeason('spring') });")
    s = rep(s, "$('goWinter').addEventListener('click',()=>jumpTo('winter'));",
            "$('goWinter').addEventListener('click',()=>jumpTo('winter'));\n"
            "addEventListener('load',()=>setTimeout(()=>{ try{ const c=window.__iocCompleted||0; if(c<=0) return;\n"
            "  let target=steps.findIndex(st=>st.dn===c+1); const all=target<0; if(all) target=steps.length-1;\n"
            "  for(let j=0;j<target;j++) if(!done[j]) done[j]=3; if(all) done[target]=3;\n"
            "  KEYS.forEach(x=>{ if(SEASONS[x].first<=target) known[x]=true }); cur=target; $('mapBtn').hidden=false; $('intro').hidden=true;\n"
            "  showSeason(steps[target].s); updateNodes(); setTimeout(()=>scrollToStep(target,false),60) }catch(e){ console.error('IOC restore',e) } },80));")
    # Ô cổng (bước đầu mùa xuân) là Level 1: mọi số level dời lên 1, mùa xuân 25 level, cả World 1 có 97 level.
    s = rep(s, "if(st.t==='lv'&&st.n!==1&&st.n!==SEASONS[st.s].badge) st.dn=++c", "if(st.t==='lv'&&st.n!==SEASONS[st.s].badge) st.dn=++c")
    s = rep(s, "Đi qua 24 level dưới tán anh đào", "Đi qua 25 level dưới tán anh đào")
    s = rep(s, '<div class="eyebrow">World 1 · Prototype</div>', '<div class="eyebrow">World 1</div>')
    s = s.replace("Đã hoàn thành · bấm vào để chơi lại (bản mẫu)", "Đã hoàn thành · bấm vào để chơi lại")
    return s


def build_world2(src: str) -> str:
    s = rep(src, '<!doctype html><html lang="vi"><head>', '<!doctype html><html lang="vi" data-world="world-2"><head>' + HEAD)
    s = rep(s, "if(j===cur){ k==='chest'?openChest(j):complete(j); return }\n  if(done[j]){",
            "if(j===cur){ if(k==='chest'){ openChest(j); return } if(st.t==='lv'){ if(window.__iocPlay) window.__iocPlay(st.n,false,()=>complete(j)); return } complete(j); return }\n"
            "  if(done[j]&&st.t==='lv'&&window.__iocPlay){ window.__iocPlay(st.n,true,null); return }\n  if(done[j]){")
    # Bản thiết kế mặc định nhảy thẳng tới level cuối để trình diễn: tắt, rồi khôi phục tiến độ thật.
    s = rep(s, "SKIP_TO_FINAL=true", "SKIP_TO_FINAL=false")
    s = rep(s, "if(SKIP_TO_FINAL){ const f=steps.length-1; for(let j=0;j<f;j++) done[j]=3; cur=f }",
            "if(SKIP_TO_FINAL){ const f=steps.length-1; for(let j=0;j<f;j++) done[j]=3; cur=f }\n"
            "{ const c=window.__iocCompleted||0; if(c>0){ const t=Math.min(c,steps.length-1); for(let j=0;j<t;j++) done[j]=3; if(c>=steps.length) done[t]=3; cur=t;"
            " const it=document.getElementById('intro'); if(it) it.hidden=true } }")
    s = rep(s, "scrollToX(steps[SKIP_TO_FINAL?steps.length-1:0].x,false)", "scrollToX(steps[Math.min(cur,steps.length-1)].x,false)")
    s = rep(s, "$('backBtn').addEventListener('click',()=>toast('','World 1','Bản demo này chỉ chứa World 2'));",
            "$('backBtn').addEventListener('click',()=>{ location.href='/' });")
    s = rep(s, 'aria-label="Quay lại World 1"', 'aria-label="Quay lại trang chủ"')
    s = rep(s, '<div class="eyebrow">World 2 · Giai đoạn 1 · Bản dựng cấu trúc</div>', '<div class="eyebrow">World 2</div>')
    return s


def main():
    w1, w2 = Path(sys.argv[1]), Path(sys.argv[2])
    out1 = build_world1(w1.read_text(encoding="utf-8"))
    out2 = build_world2(w2.read_text(encoding="utf-8"))
    (ROOT / "world1.html").write_text(out1, encoding="utf-8", newline="\n")
    (ROOT / "world2.html").write_text(out2, encoding="utf-8", newline="\n")
    print("ok", len(out1), len(out2))


if __name__ == "__main__":
    main()
