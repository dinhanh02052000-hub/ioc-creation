# Illusion of Competence (IOC)

Ứng dụng học từ vựng tiếng Anh (bậc B2/C1) giúp người học phát hiện **"ảo tưởng về năng lực"** — cảm giác đã hiểu/nhớ một từ trong khi thực ra chưa vận dụng được. Thay vì chỉ chấm đúng/sai, hệ thống so sánh **mức độ tự tin do người học tự khai báo** với **năng lực thực tế đo được qua 3 vòng kiểm tra độ khó tăng dần**, rồi kết luận một trong ba trạng thái: `DETECTED` (ảo tưởng năng lực), `UNDERCONFIDENT` (tự ti quá mức), hoặc `CALIBRATED` (tự đánh giá đúng).

Backend dùng AI (OpenAI) để soạn nội dung học/câu hỏi theo thời gian thực dựa trên một "Knowledge Base" (KB) từ vựng cố định cho từng level — AI không được tự bịa nghĩa từ, chỉ diễn đạt lại nội dung trong KB.

## Mục lục

- [Kiến trúc tổng quan](#kiến-trúc-tổng-quan)
- [Cấu trúc thư mục](#cấu-trúc-thư-mục)
- [Luồng học & cơ chế phát hiện illusion](#luồng-học--cơ-chế-phát-hiện-illusion)
- [Pipeline sinh nội dung bằng AI](#pipeline-sinh-nội-dung-bằng-ai)
- [Tài khoản, "key" và Key Shop](#tài-khoản-key-và-key-shop)
- [Bản đồ thế giới & tiến độ học](#bản-đồ-thế-giới--tiến-độ-học)
- [API tham khảo](#api-tham-khảo)
- [Lược đồ database](#lược-đồ-database)
- [Chạy ở máy local](#chạy-ở-máy-local)
- [Triển khai (deploy)](#triển-khai-deploy)

## Kiến trúc tổng quan

| Lớp | Công nghệ |
|---|---|
| Frontend | HTML + CSS + vanilla JavaScript thuần (không framework, không build step) |
| Backend | Python, [FastAPI](https://fastapi.tiangolo.com/) (`server/main.py`), phục vụ luôn cả API lẫn file tĩnh |
| Database | PostgreSQL (khuyến nghị [Neon](https://neon.tech) — free tier serverless) |
| AI | OpenAI Responses API (model cấu hình qua biến môi trường) |
| Đăng nhập | Google OAuth (Google Identity Services, phía client) |
| Thanh toán | VietQR (ảnh QR tĩnh) + webhook [SePay](https://sepay.vn) xác nhận chuyển khoản tự động |

Frontend và backend **chạy cùng 1 origin** (FastAPI tự serve `index.html`, `world1.html`, `world2.html`, `js/`, `css/`, `assets/`) — không cần cấu hình CORS phức tạp hay deploy 2 nơi riêng biệt.

## Cấu trúc thư mục

```
index.html, world1.html, world2.html   # 3 trang chính (SPA-lite, mỗi world map là 1 file riêng)
css/                                    # style theo từng khu vực (style.css, world-map.css, chatbot.css...)
js/
  core/        # khung ứng dụng: App.js (khởi tạo), main.js (điều phối + Key Shop), data.js (dữ liệu tĩnh)
  features/    # khối chức năng dùng lại được: auth, chatbot (luồng AI quiz), world-map, playtime,
               # course-progress, gesture, particles, bg-music, sound-effects, question-history...
  pages/       # mỗi file render 1 trang vào #main-content: home, course, analysis, profile, world1, world2
assets/                                 # ảnh, âm thanh
database/
  vocab b2 database/   vocab-b2-001.json ... 097.json   # 97 level, World 1
  vocab c1 database/   vocab-c1-001.json ... 121.json   # 121 level, World 2
server/
  main.py              # toàn bộ API (FastAPI) — điểm vào chính
  db.py                # lớp truy cập Postgres (users, sessions, progress, pending_payments, feedback)
  engine_prompts.py     # xây dựng prompt gửi cho AI (dạy nội dung, sinh câu hỏi, chấm điểm)
  analysis_prompts.py   # prompt cho trang "Phân tích điểm yếu"
  ai_client.py          # gọi OpenAI Responses API
  ai_json.py            # parse JSON trả về từ AI (chịu lỗi định dạng)
  scoring.py            # logic tính PASS/RETRY + DETECTED/UNDERCONFIDENT/CALIBRATED (code thuần, không AI)
  session_store.py      # session tạm thời cho 1 lượt làm bài (in-memory)
  config.py             # đường dẫn + biến môi trường dùng chung
  requirements.txt
  hacker prompt/        # script quản trị nội bộ (gitignored, KHÔNG lên GitHub — xem bên dưới)
Procfile                                # lệnh khởi động cho Render/Railway/Heroku-style hosting
requirements.txt                        # trỏ sang server/requirements.txt
```

## Luồng học & cơ chế phát hiện illusion

Mỗi lượt học 1 level gồm các bước (trạng thái lưu trong `session_store.py`):

1. **Học nội dung** (`/api/chat/start`) — AI dạy nhóm từ của level đó bằng tiếng Việt, dựa trên KB.
2. **Nhận diện (Recognition)** — 20 câu trắc nghiệm điền từ, chấm bằng code (không AI). Đây là phép đo "nhận diện mặt chữ", mức độ dễ nhất.
3. **Tự đánh giá độ tự tin** — người học tự chấm điểm tự tin của bản thân trước khi biết kết quả phần Phân biệt/Vận dụng.
4. **Phân biệt (Distinction) & Vận dụng (Application)** — 2 câu hỏi mở, khó hơn, đòi hỏi vận dụng thực sự chứ không chỉ nhận diện. AI chấm theo rubric chi tiết (nhiều tiêu chí điểm riêng).
5. **Kết luận** (`scoring.py`, code thuần — **không để AI tự quyết định kết quả**):
   - Tính `Overall` = tổng hợp điểm 3 phần.
   - Tính `Gap` = độ tự tin tự khai − năng lực thực đo.
   - `|Gap|` vượt ngưỡng → `RETRY`, ngược lại → `PASS`.
   - Dấu của `Gap` quyết định nhãn hiển thị: `DETECTED` (quá tự tin) hay `UNDERCONFIDENT` (tự ti) — chỉ ảnh hưởng hiển thị, không ảnh hưởng PASS/RETRY.
6. Nếu `RETRY`: có thể học thêm 1 vòng **ôn tập trọng tâm** (`/begin-remediation`) xoáy sâu vào đúng những từ hay nhầm, rồi làm lại từ bước 2 cho tới khi `PASS`.

## Pipeline sinh nội dung bằng AI

Toàn bộ nội dung câu hỏi được sinh **thời gian thực theo từng lượt** (không có sẵn trong database), nhằm tránh học sinh học thuộc đáp án qua các lần làm lại. Một số nguyên tắc thiết kế:

- **Knowledge Base cố định**: mỗi file JSON trong `database/` định nghĩa 1 nhóm từ (nghĩa, cách phân biệt, ví dụ). AI chỉ được dùng đúng nội dung này, không tự bịa nghĩa.
- **Chống lặp câu hỏi hai lớp**:
  1. Nhét lịch sử câu đã sinh (lưu phía client, `js/features/question-history.js`) vào prompt để AI chủ động tránh lặp ý.
  2. So khớp văn bản bằng `difflib` (code thuần, miễn phí) để chặn tuyệt đối 2 câu **giống y nguyên** — không dùng thêm 1 lượt gọi AI riêng để kiểm tra lặp ý (đã thử, tốn token và chậm mà lợi ích không tương xứng).
- **Đa dạng chủ đề & cấu trúc câu bằng thiết kế, không bằng kiểm tra sau**: mỗi câu trong 20 câu MCQ được gán sẵn 1 lĩnh vực riêng (y tế, công nghệ, môi trường...) và được yêu cầu luân phiên qua nhiều kiểu cấu trúc ngữ pháp, để tự nhiên tránh lặp mà không cần sinh lại cả batch.
- **Xác định đáp án đúng độc lập với việc sinh câu hỏi** (`_determine_and_verify_answers` trong `main.py`): một lượt AI tự suy luận đáp án chỉ từ KB (không biết AI sinh câu đã "định" chọn gì), rồi một lượt AI khác xác minh lại độc lập. Nếu 2 lượt mâu thuẫn hoặc độ tin cậy thấp, câu đó được sinh lại — tách biệt khỏi việc sinh câu hỏi để tránh 1 model tự tin xác nhận lại chính sai lầm của mình.
- **Chấm điểm cuối cùng luôn là code thuần** (`scoring.py`) — AI chỉ chấm điểm thành phần theo rubric, không bao giờ tự quyết định PASS/RETRY hay nhãn illusion.

## Tài khoản, "key" và Key Shop

- Khách chưa đăng nhập dùng được các trang tĩnh nhưng **không dùng được tính năng AI** (0 key).
- Đăng nhập Google lần đầu được tặng 15 key.
- Mỗi lượt kiểm tra (`begin-recognition`) tốn 2 key, mỗi lượt ôn tập (`begin-remediation`) tốn 1 key; các endpoint AI khác miễn phí nhưng vẫn yêu cầu đăng nhập.
- **Key Shop**: mua thêm key qua chuyển khoản ngân hàng thật, xác nhận **tự động hoàn toàn** (không qua thao tác tay của admin) nhờ webhook SePay:
  - Mỗi gói key có sẵn 1 ảnh QR tĩnh (số tiền cố định, không có nội dung chuyển khoản riêng theo từng giao dịch).
  - Webhook đối chiếu giao dịch theo 2 lớp: (1) nội dung chuyển khoản nếu khách có sửa được, (2) số tiền — ưu tiên khớp cho giao dịch đăng ký trước (FIFO) **trong số các giao dịch đã được xác minh** (`verified = true`, tức có bằng chứng người dùng thật đang mở màn hình QR chờ, không phải giao dịch rác/test bị bỏ quên).
  - Giao dịch chưa thanh toán sau vài phút tự chuyển sang `expired`, loại khỏi diện so khớp — tránh tồn đọng rác gây khớp nhầm.
  - Toàn bộ nguyên tắc: **không bao giờ mất giao dịch, không bao giờ cộng 2 lần, thà không tự cộng còn hơn cộng nhầm người**.

## Bản đồ thế giới & tiến độ học

- World 1 (`world1.html`, 97 level) và World 2 (`world2.html`, 121 level) dùng chung 1 engine vẽ bản đồ (`js/features/world-map.js`) — chỉ khác file cấu hình (`js/pages/world1.js` / `world2.js`).
- Tiến độ (level đã qua, kết quả từng level, từ vựng đã học, tổng thời gian học...) được đồng bộ lên server theo tài khoản Google (`/api/progress/save`, `/api/progress/load`), đảm bảo không mất dữ liệu khi đổi thiết bị.

## API tham khảo

Toàn bộ định nghĩa nằm trong `server/main.py`.

| Nhóm | Endpoint |
|---|---|
| Đăng nhập | `POST /api/auth/google`, `POST /api/auth/logout`, `GET /api/auth/me` |
| Luồng học 1 level | `POST /api/chat/start`, `begin-recognition`, `submit-recognition`, `submit-confidence`, `submit-open-ended` |
| Ôn tập trọng tâm | `POST /api/chat/begin-remediation`, `submit-remediation-mcq`, `submit-remediation-open-ended` |
| Từ vựng | `GET /api/vocab/{world_id}/{level}` |
| Phân tích điểm yếu | `POST /api/analysis/generate` |
| Tiến độ | `POST /api/progress/save`, `GET /api/progress/load` |
| Key Shop | `POST /api/keys/create-payment`, `GET /api/keys/payment-status/{reference_code}`, `POST /api/webhooks/sepay` |
| Góp ý | `POST /api/feedback` |
| Trang tĩnh | `GET /`, `/index.html`, `/world1.html`, `/world2.html` |

## Lược đồ database

PostgreSQL, 5 bảng chính (xem `server/db.py`):

- `users` — tài khoản Google, số key, số lần mua.
- `sessions` — token đăng nhập.
- `progress` — tiến độ học (JSON) theo từng user.
- `pending_payments` — giao dịch Key Shop (`pending` / `paid` / `expired`).
- `feedback` — góp ý người dùng gửi qua form.

## Chạy ở máy local

Yêu cầu: Python 3.11+, 1 database Postgres (VD tạo free tại Neon), 1 API key OpenAI.

```bash
# 1. Cài dependency
pip install -r requirements.txt

# 2. Tạo file server/.env (copy từ server/.env.example) và điền:
#    OPENAI_API_KEY, GOOGLE_CLIENT_ID, DATABASE_URL (bắt buộc)
#    Phần Key Shop (BANK_*, SEPAY_API_KEY) có thể để trống khi dev — webhook
#    sẽ tự từ chối an toàn nếu SEPAY_API_KEY trống, không cần xoá code gì.

# 3. Chạy server (cũng tự phục vụ luôn frontend tĩnh)
cd server
uvicorn main:app --reload --port 8000
```

Mở `http://localhost:8000`.

## Triển khai (deploy)

- `Procfile` đã cấu hình sẵn cho các nền tảng kiểu Render/Railway (`uvicorn main:app --host 0.0.0.0 --port $PORT`).
- Bắt buộc dùng Postgres thật (VD Neon) khi deploy — ổ đĩa trên hosting free tier là tạm thời, SQLite sẽ mất sạch dữ liệu mỗi lần server khởi động lại.
- Google OAuth cần khai báo đúng domain thật trong mục "Authorized JavaScript origins" của OAuth Client trên Google Cloud Console.
- Webhook SePay cần trỏ về đúng domain thật (`https://<domain>/api/webhooks/sepay`) và cấu hình `Authorization: Apikey <SEPAY_API_KEY>` khớp với biến môi trường.

---

Thư mục `server/hacker prompt/` chứa các script quản trị nội bộ (xem/sửa key, đối soát thanh toán, xem feedback...) — được `.gitignore` loại khỏi repo, không xuất hiện trên GitHub.
