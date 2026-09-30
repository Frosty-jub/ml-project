# งานคนที่ 4 — FastAPI + Model Serving + Docker

ชุดนี้จัดทำตามข้อกำหนดโครงงาน CP413008 โดยครอบคลุม API, request validation, การใช้ preprocessing ชุดเดียวกับตอนเทรน, คอนเทนเนอร์, health check, Metrics/Logs และการวัด p50/p95/throughput เทียบ SLO

**โมเดลสาธิตสร้างจากข้อมูลสังเคราะห์ ไม่ใช่โมเดลจริงของกลุ่ม** ทุก response ระบุ `data_kind: synthetic_demo_only` ต้องแทนที่ด้วยโมเดลและฟีเจอร์จริงก่อนส่งโครงงานฉบับสุดท้าย โค้ดนี้รองรับ sklearn Pipeline ที่ให้ผลทำนายเป็นตัวเลขหนึ่งค่าต่อหนึ่งแถว หากใช้ MLflow pyfunc หรือผลลัพธ์แบบอื่น ต้องปรับตัวโหลดและรูปแบบผลลัพธ์

คำสั่งในหน้านี้รันจากโฟลเดอร์ `serving/` ใช้ environment และ dependencies แยกจากการเทรนที่ root ไม่ได้เปลี่ยนเวอร์ชัน Python หรือไลบรารีของโค้ดกลุ่ม

## เริ่มด้วย Docker

ติดตั้งและเปิด Docker Desktop ในโหมด Linux containers จากนั้นเปิด PowerShell ในโฟลเดอร์นี้:

```powershell
docker compose up --build -d
docker compose ps
```

เปิด http://localhost:18005/docs เพื่อทดลอง API และ http://localhost:18005/health เพื่อตรวจโมเดล Docker สร้างโมเดลสาธิตตอน build ด้วย seed ที่กำหนดไว้ จึงไม่ต้อง commit model binary Compose มี health check และ restart policy ใช้พอร์ต 18005 บนเครื่อง ส่วนภายในคอนเทนเนอร์ใช้พอร์ต 8000

```powershell
Invoke-RestMethod http://localhost:18005/health
Invoke-RestMethod -Method Post -Uri http://localhost:18005/predict -ContentType 'application/json' -Body (Get-Content -Raw -Encoding UTF8 examples/valid_request.json)
docker compose logs --tail 30 serving
```

หยุดระบบด้วย `docker compose down` ซึ่งไม่ลบไฟล์โมเดลใน `artifacts` หากพอร์ตชน ให้กำหนด `$env:SERVING_PORT = '18006'` ก่อนรัน แล้วเปลี่ยน URL ตามนั้น หยุด Docker ก่อนใช้ local mode ที่พอร์ตเดียวกัน

## เริ่มบน Windows โดยไม่ใช้ Docker

ต้องมี Python 3.13 ใช้สคริปต์เตรียม environment แล้วเริ่ม API:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_local.ps1
```

สคริปต์ตรวจ Python ของ Anaconda ในเครื่องนี้โดยอัตโนมัติ หรือระบุ `-PythonExecutable 'C:\path\to\python.exe'` เปิดเทอร์มินัลอีกหน้าสำหรับคำสั่งทดสอบ คำสั่งต่อไปนี้ใช้ Python ใน `.venv`

## Endpoint และผลลัพธ์

| Endpoint | หน้าที่ | ผลลัพธ์ |
|---|---|---|
| `POST /predict` | ทำนายหนึ่งรายการหรือ batch สูงสุดตาม schema | 200 พร้อม predictions / 422 ข้อมูลผิด / 503 โมเดลไม่พร้อม / 500 โมเดลทำนายล้มเหลว |
| `GET /health` | ตรวจว่าโหลดโมเดลพร้อมให้บริการหรือไม่ | 200 พร้อมชื่อ/เวอร์ชัน/ชนิดข้อมูล หรือ 503 |
| `GET /schema` | ชื่อ ชนิด ช่วงค่า และเงื่อนไข null ของฟีเจอร์ | 200 หรือ 503 |
| `GET /metrics` | Prometheus counters, readiness และ latency histogram | 200 |
| `GET /docs` | Swagger UI สำหรับทดลอง API | 200 |

ตัวอย่างคำขอ:

```json
{"records":[{"lag_1":160.0,"lag_7":155.0,"rolling_mean_7":150.0,"day_of_week":2}]}
```

ผลลัพธ์มี `request_id`, `model_name`, `model_version`, `data_kind` และ `predictions` ซึ่งเรียงตามลำดับแถว ไม่ส่งตัวเลขผลทำนายที่แต่งขึ้นในคู่มือ ผลจริงอยู่ใน `reports/http_evidence*.json`

ระบบปฏิเสธฟีเจอร์หาย/เกิน, numeric string, boolean ในช่องตัวเลข, NaN/Infinity, ค่านอกช่วง, ชนิดผิด และ batch ใหญ่เกินกำหนด ค่า `lag_1: null` อนุญาตเฉพาะโมเดลสาธิตซึ่งมี imputer ฝึกไว้แล้ว ในงานจริงต้องกำหนดตาม schema ของกลุ่ม

การตรวจข้อมูลเสียจะหยุด **คำขอนั้น** ด้วย 422 และบันทึก log บริการยังรับคำขอที่ถูกต้องต่อได้ การหยุด data pipeline ทั้งกระบวนการเป็นส่วนของคนที่ทำ validation/orchestration

## ทดสอบและวัด SLO

เกณฑ์ใน `slo.json` เป็นข้อเสนอสำหรับเดโม: p50 ≤ 100 ms, p95 ≤ 250 ms, throughput ≥ 20 requests/s, error rate ≤ 1% สำหรับหนึ่งแถวต่อคำขอ, 500 คำขอ, concurrency 10 ต้องให้กลุ่มยืนยันหรือปรับให้ตรงความต้องการผู้ใช้จริง

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.lock
.\.venv\Scripts\python.exe -m pytest -q --junitxml=reports/test_results.xml
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m scripts.verify_http
.\.venv\Scripts\python.exe -m scripts.load_test --requests 500 --concurrency 10 --environment docker --output reports/load_test_docker.json
```

สคริปต์โหลดทดสอบส่ง HTTP จริง มี warmup 20 ครั้งไม่นับผล, ใช้ keep-alive, รายงาน p50/p95 เฉพาะคำขอทำนายสำเร็จ, รายงาน error rate ครบทุกคำขอ และคำนวณ throughput จากจำนวนคำขอสำเร็จ/เวลารวม ไม่ใช้เวลา inference ภายในโมเดลแทนเวลาตอบกลับ API สคริปต์คืน exit code 1 เมื่อไม่ผ่าน SLO เพื่อให้คนที่ 6 ใช้เป็น gate ได้ ผลขึ้นกับเครื่องและภาระงาน ช่วงทดสอบสั้นไม่ยืนยัน availability ระยะยาว

## เปลี่ยนเป็นโมเดลจริงของกลุ่ม

โมเดลของกลุ่มบันทึกเป็น `FeatureOrderedModel` ครอบ LightGBM ไม่ใช่ sklearn Pipeline แบบโมเดลสังเคราะห์ของ Serving คำสั่ง export ต่อไปนี้โหลดเวอร์ชันจาก MLflow Registry ตรวจ gate และ feature manifest แล้วสร้าง bundle แบบ `model.joblib`:

```powershell
# Run from repository root with the project's .venv active.
python serving\scripts\export_model.py --version 1 --destination serving\artifacts\group-v1-joblib
```

`--version` ต้องเป็นเวอร์ชันที่มี `gate_passed=true` ใน Registry โฟลเดอร์ bundle มี `model.joblib`, `metadata.json` และ `sample_request.json`; metadata บันทึกชื่อ/เวอร์ชันโมเดล, feature schema, scikit-learn/LightGBM versions และ checksum ตัว export เปรียบเทียบ prediction ของ bundle กับ Registry model ก่อนจบคำสั่ง

ฟีเจอร์ต้องตรงกับ `feature_columns` ใน `reports/generated/feature_split_manifest.json` และเรียงตามลำดับเดียวกับโมเดล ห้ามส่ง `sku_id`, `forecast_origin_date` หรือ target เข้าโมเดล API รับเฉพาะฟีเจอร์ที่สร้างด้วย data pipeline แล้ว ไม่สร้าง lag หรือ rolling features เอง

เมื่อมี bundle จริงที่ `artifacts/group-v1-joblib` ใช้ Compose override เพื่อเลือกและ mount โมเดลนั้นแบบอ่านอย่างเดียว:

```powershell
docker compose -f compose.yaml -f compose.model.yaml up --build -d --force-recreate
```

สำหรับรัน local กำหนด `$env:MODEL_DIR = "$PWD\artifacts\group-v1-joblib"` ก่อนเริ่มบริการ โมเดลโหลดครั้งเดียวตอนเริ่มต้น หากเปลี่ยนไฟล์ให้ restart และตรวจชื่อเวอร์ชันใน `/health` ยังไม่ได้ทำ hot reload หรือโหลด alias จาก MLflow อัตโนมัติ

การ export เวอร์ชัน 1 สร้าง bundle ใน `serving/artifacts/group-v1-joblib` แล้ว Docker/API checks, Registry parity benchmark และ load test 500 requests กับ bundle นี้ผ่าน โดยบันทึกหลักฐานไว้ใน `reports/http_evidence.json` และ `reports/load_test_group_v1.json`

API รับฟีเจอร์ที่ผ่าน feature engineering แล้ว ตัว `FeatureOrderedModel` ตรวจลำดับคอลัมน์และจัดชนิดข้อมูลก่อนทำนาย แต่ไม่สร้าง lag/rolling features เอง ฟีเจอร์เหล่านั้นต้องสร้างด้วย data pipeline ก่อนเรียก API และต้องตรงกับ `reports/generated/feature_split_manifest.json`

## สถานะการเชื่อมกับโมเดลใน repository กลุ่ม

ตัว Serving โหลด bundle ที่ `MODEL_DIR` ระบุ ส่วน benchmark ของ Registry ใช้ `POST /predict` แบบ `records` ตรวจ `model_name`/`model_version` และเทียบผลกับโมเดลเวอร์ชันที่เลือก ใช้ URL ฐาน เช่น `http://127.0.0.1:18005`:

```powershell
python -m src.demand_forecasting.registry benchmark 1 --url http://127.0.0.1:18005
```

`config/model_registry.json` และ `serving/slo.json` ยังมีค่า SLO คนละชุด ทีมต้องยืนยัน SLO ของบริการจริงก่อนใช้ผล benchmark อนุมัติ promotion

## ส่งต่อให้คนที่ 5 และ 6

คนที่ 5 scrape `/metrics` มี `serving_requests_total`, `serving_request_duration_seconds_bucket`, `serving_predictions_total`, `serving_prediction_failures_total`, `serving_model_ready` และดู JSON logs บน stdout

ตัวอย่าง p95 ใน Prometheus:

```promql
histogram_quantile(0.95, sum by (le) (rate(serving_request_duration_seconds_bucket{route="/predict"}[5m])))
```

ค่า histogram เป็นเวลาภายในบริการ ส่วน benchmark เป็นเวลาตอบกลับจากฝั่ง client จึงอาจต่างกัน เปลี่ยน 0.95 เป็น 0.50 สำหรับ p50 และใช้ `sum(rate(serving_requests_total{route="/predict",status="200"}[5m]))` สำหรับ requests/s

Logs มีเวลา UTC, request ID, route, status และ latency โดยไม่บันทึกข้อมูลผู้ใช้ทุกฟีเจอร์ ถ้าคนที่ 5 ต้องตรวจ drift ต้องเพิ่มช่องทางเก็บฟีเจอร์/ผลทำนาย/ground truth ตามข้อตกลงกลุ่ม Metrics นี้วัดสถานะบริการ ไม่ได้ตรวจ data/concept drift หรือ MAE ของข้อมูลจริงเอง

คนที่ 6 รวม compose ของกลุ่ม ใช้ service name `serving:8000` เรียกภายใน Docker network และใช้ pytest/load_test เป็นส่วนหนึ่งของ CI/CD README นี้ไม่อ้างว่าระบบครบ end-to-end ทั้งกลุ่ม

เลือก online request/response เพราะผู้ใช้เรียกผลทำนายตามต้องการ พร้อมรองรับ small batch เพื่อลด overhead ต้องยืนยันรูปแบบบริการกับโจทย์จริง ใช้ worker เดียวเพื่อให้ metrics ถูกต้อง และโหลดโมเดลหนึ่งชุดต่อ process งาน inference ใช้ lock ให้โมเดลทำงานทีละคำขอเพื่อลด CPU contention สำหรับเดโมนี้ ส่วน HTTP/validation ยังรับพร้อมกันได้ หากโมเดลจริงต้องการ parallel inference ให้ปรับและ benchmark ใหม่ หากเพิ่มหลาย worker ต้องตั้ง Prometheus multiprocess ก่อน

## หลักฐานและการนำเสนอ

อ่าน `docs/DEMO_TH.md` สำหรับลำดับสาธิต และ `docs/VERIFICATION_TH.md` สำหรับผลทดสอบจริง เก็บประวัติ commit และ branch ใน repository กลุ่ม รวมถึง PR ของงานส่วนนี้ก่อนส่ง

เครื่องมือ AI: ใช้ OpenAI Codex ช่วยเขียน API, model handoff, Docker, validation, tests, load test และคู่มือ ต้องระบุในรายงานตามข้อกำหนดรายวิชา และสมาชิกต้องอธิบายโค้ดที่ส่งได้

แหล่งอ้างอิงเทคนิค: [FastAPI Docker](https://fastapi.tiangolo.com/deployment/docker/), [FastAPI lifespan testing](https://fastapi.tiangolo.com/advanced/testing-events/), [Prometheus histogram](https://prometheus.github.io/client_python/instrumenting/histogram/)
