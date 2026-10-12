# Illusion of Competence (IOC)

Ứng dụng web học từ vựng tiếng Anh bậc B2/C1. Mỗi level kiểm tra người học qua 3 bước độ khó tăng dần (trắc nghiệm nhận diện, rồi 2 câu hỏi mở đòi phân biệt và vận dụng), đối chiếu với mức độ tự tin người học tự chấm trước khi biết điểm phần sau, rồi suy ra 1 trong 3 trạng thái: `DETECTED` (tự tin cao hơn năng lực đo được), `UNDERCONFIDENT` (tự tin thấp hơn), `CALIBRATED` (khớp nhau). Công thức tính nằm ở `server/scoring.py`, chạy bằng code thuần, không qua AI.

## Stack

- Frontend: HTML/CSS/JS thuần, không framework, không build step.
- Backend: Python, FastAPI (`server/main.py`).
- Database: PostgreSQL, qua `psycopg` (`server/db.py`).
- AI: OpenAI Responses API (`server/ai_client.py`).
- Đăng nhập: Google Identity Services ở client, xác thực lại token ở server bằng `google-auth`.
- Thanh toán: ảnh QR tĩnh + webhook SePay xác nhận chuyển khoản.

FastAPI vừa phục vụ API vừa phục vụ file tĩnh (`index.html`, `world1.html`, `world2.html`, `js/`, `css/`, `assets/`) trên cùng 1 origin. Các route trả file tĩnh nằm cuối `server/main.py` (`GET /`, `/index.html`, `/world1.html`, `/world2.html`).

## Cấu trúc thư mục

```
index.html, world1.html, world2.html
css/
js/
  core/      App.js, main.js, data.js
  features/  auth.js, chatbot.js, world-map.js, playtime.js, course-progress.js,
             gesture.js, particles.js, bg-music.js, sound-effects.js, question-history.js
  pages/     home.js, course.js, analysis.js, profile.js, world1.js, world2.js
assets/
database/
  vocab b2 database/   vocab-b2-001.json ... 097.json
  vocab c1 database/   vocab-c1-001.json ... 121.json
server/
  main.py              toàn bộ route API
  db.py                truy cập Postgres
  engine_prompts.py     dựng prompt gửi cho AI
  analysis_prompts.py   prompt cho trang phân tích điểm yếu
  ai_client.py          gọi OpenAI Responses API
  ai_json.py            parse JSON AI trả về
  scoring.py            công thức PASS/RETRY, DETECTED/UNDERCONFIDENT/CALIBRATED
  session_store.py      session tạm thời cho 1 lượt làm bài, lưu trong RAM
  config.py             đường dẫn và biến môi trường dùng chung
  requirements.txt
Procfile
requirements.txt
```

## Luồng 1 lượt học

Trạng thái 1 lượt học lưu trong `session_store.py` (dict trong RAM, không phải database), đi qua các bước:

1. `POST /api/chat/start`: AI dạy nhóm từ của level, dựa đúng nội dung file KB tương ứng (`server/config.py`: `get_kb_path` map `world_id` + `level` sang đúng file JSON trong `database/`).
2. `POST /api/chat/begin-recognition`: AI sinh 20 câu trắc nghiệm điền từ. Đáp án giữ trong session ở server, không gửi về client.
3. `POST /api/chat/submit-recognition`: chấm 20 câu bằng code, đối chiếu với session, không qua AI.
4. `POST /api/chat/submit-confidence`: lưu điểm tự tin người học tự khai, trước khi biết điểm 2 câu hỏi mở.
5. `POST /api/chat/submit-open-ended`: AI chấm 2 câu hỏi mở (Distinction, Application) theo rubric nhiều tiêu chí, rồi `scoring.py` tính Overall/Gap/PASS-RETRY.

Nếu RETRY, frontend có thể gọi thêm vòng ôn tập trước khi làm lại bước 2:

- `POST /api/chat/begin-remediation`: AI phân tích câu sai và điểm yếu, sinh bài ôn tập nhỏ.
- `POST /api/chat/submit-remediation-mcq`, `submit-remediation-open-ended`: chấm bài ôn tập, không tính vào kết quả chính thức.

Sau đó `/begin-recognition` được gọi lại cho 1 lượt test đầy đủ mới, lặp tới khi PASS.

## Sinh câu hỏi: tránh lặp, tránh AI tự bịa đáp án

- Mỗi file JSON trong `database/` chỉ định nghĩa nghĩa, điểm phân biệt, ví dụ cho 1 nhóm từ. Prompt gửi AI (`engine_prompts.py`) chỉ chứa đúng nội dung file đó.
- Lịch sử câu đã sinh cho level đó lưu ở client (`js/features/question-history.js`), gửi kèm mỗi lần gọi `begin-recognition` để AI tránh lặp ý ngay từ lúc sinh.
- Sau khi AI trả câu hỏi, server so khớp văn bản bằng `difflib` để chặn 2 câu giống hệt nhau (`server/main.py`, hàm `_find_duplicate`). Không có lượt gọi AI riêng để kiểm tra "lặp ý" vì tốn thêm 1 lượt gọi mỗi batch mà hiệu quả không tương xứng.
- Đáp án đúng được xác định bằng 1 lượt AI riêng, không biết AI sinh câu đã định chọn đáp án nào (`server/main.py`, hàm `_determine_and_verify_answers`), rồi 1 lượt AI khác xác minh lại độc lập. Hai lượt mâu thuẫn hoặc độ tin cậy dưới ngưỡng thì sinh lại đáp án cho đúng câu đó.

## Tài khoản và key

- Chưa đăng nhập: dùng được trang tĩnh, không gọi được route AI (0 key).
- Đăng nhập Google lần đầu được cấp 15 key (`server/db.py`, hàm `upsert_user`).
- `begin-recognition` trừ 2 key, `begin-remediation` trừ 1 key (`server/main.py`, hàm `_require_keys` và `_charge_keys`). Các route AI khác yêu cầu đăng nhập nhưng không trừ key.
- Mua thêm key qua `POST /api/keys/create-payment`, trả về URL ảnh QR tĩnh gắn sẵn số tiền cho từng gói.

## Xác nhận thanh toán qua webhook SePay

QR tĩnh không gắn được nội dung chuyển khoản riêng cho từng giao dịch, nên `POST /api/webhooks/sepay` đối chiếu theo 2 lớp (`server/main.py`, hàm `sepay_webhook`):

1. Nếu nội dung chuyển khoản chứa đúng 1 mã tham chiếu đang chờ, khớp theo mã đó.
2. Nếu không, đối chiếu theo số tiền, chỉ xét các giao dịch đã `verified = true` (`server/db.py`, hàm `mark_payment_verified`, được set khi client gọi `GET /api/keys/payment-status` ít nhất 1 lần, tức có người đang mở QR chờ thật). Trong các giao dịch khớp số tiền và đã verified, ưu tiên giao dịch tạo trước (FIFO).

Giao dịch pending quá 3 phút tự chuyển sang `expired` (`server/db.py`: `PENDING_PAYMENT_TTL_MINUTES`, hàm `expire_stale_pending_payments`) và không còn được xét ở 2 lớp trên.

`finalize_payment` (`server/db.py`) đánh dấu `paid` và cộng key trong cùng 1 transaction, để không rơi vào trạng thái đã đánh dấu paid nhưng chưa cộng key nếu có lỗi giữa chừng. Webhook trả `{"success": true}` cho mọi trường hợp không khớp được giao dịch (đúng hợp đồng API của SePay, để họ không gọi lại vô ích), chỉ trả lỗi 500 khi có exception ngoài dự kiến.

## Bản đồ level

World 1 (`world1.html`) có 97 level ứng với 97 file trong `database/vocab b2 database/`. World 2 (`world2.html`) có 121 level ứng với `database/vocab c1 database/`. Cả 2 trang dùng chung engine vẽ bản đồ `js/features/world-map.js`, chỉ khác tham số khai ở `js/pages/world1.js` và `world2.js` (`worldId`, `totalLevels`, ảnh nền, theme màu).

Tiến độ (level đã qua, kết quả từng level, từ vựng đã học, thời gian học) lưu ở client qua `localStorage`, đồng bộ lên server theo tài khoản Google qua `POST /api/progress/save` và `GET /api/progress/load` (`server/db.py`, bảng `progress`, cột `data_json`).

## API

| Nhóm | Endpoint |
|---|---|
| Đăng nhập | `POST /api/auth/google`, `POST /api/auth/logout`, `GET /api/auth/me` |
| Luồng học 1 level | `POST /api/chat/start`, `begin-recognition`, `submit-recognition`, `submit-confidence`, `submit-open-ended` |
| Ôn tập | `POST /api/chat/begin-remediation`, `submit-remediation-mcq`, `submit-remediation-open-ended` |
| Từ vựng | `GET /api/vocab/{world_id}/{level}` |
| Phân tích điểm yếu | `POST /api/analysis/generate` |
| Tiến độ | `POST /api/progress/save`, `GET /api/progress/load` |
| Key Shop | `POST /api/keys/create-payment`, `GET /api/keys/payment-status/{reference_code}`, `POST /api/webhooks/sepay` |
| Góp ý | `POST /api/feedback` |

## Database

PostgreSQL, định nghĩa trong `server/db.py` (hàm `init_db`):

- `users`: tài khoản Google, số key, số lần mua.
- `sessions`: token đăng nhập.
- `progress`: tiến độ học dạng JSON, 1 dòng mỗi user.
- `pending_payments`: giao dịch Key Shop, cột `status` nhận `pending`/`paid`/`expired`.
- `feedback`: nội dung góp ý gửi qua `POST /api/feedback`.

## Chạy local

Cần Python 3.11+, 1 connection string Postgres, 1 API key OpenAI.

```bash
pip install -r requirements.txt
cd server
cp .env.example .env   # điền OPENAI_API_KEY, GOOGLE_CLIENT_ID, DATABASE_URL
uvicorn main:app --reload --port 8000
```

Mở `http://localhost:8000`. Phần Key Shop (`BANK_*`, `SEPAY_API_KEY`) để trống được khi phát triển cục bộ: thiếu `SEPAY_API_KEY` thì webhook tự từ chối mọi request, không cần tắt code.

## Deploy

`Procfile` chạy `uvicorn main:app --host 0.0.0.0 --port $PORT`, dùng được trên các nền tảng kiểu buildpack Python (Render, Railway). Cần `DATABASE_URL` trỏ tới Postgres thật vì ổ đĩa trên hosting free tier không giữ file SQLite qua các lần restart. Google OAuth Client cần khai domain thật trong mục Authorized JavaScript origins. Webhook SePay cần trỏ về `https://<domain>/api/webhooks/sepay`, header `Authorization: Apikey <SEPAY_API_KEY>` khớp biến môi trường.
