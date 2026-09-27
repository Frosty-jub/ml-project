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

ขอจากคนที่เทรนโมเดล: sklearn Pipeline ที่ **fit แล้ว** รวม preprocessing, ลำดับชื่อฟีเจอร์, ชนิด/ช่วงค่า/นโยบาย null, ตัวอย่างแถว และเวอร์ชันโมเดล ถ้าใช้ MLflow ให้คนที่ดูแล Registry export เวอร์ชันที่อนุมัติแล้วลงโฟลเดอร์นี้

ในโค้ดเทรน หลังประเมินผลเรียก:

```python
from scripts.export_model import export_bundle

export_bundle(
    pipeline=fitted_pipeline,
    sample=X_test.head(3),
    features=[
        {"name": "feature_a", "type": "number", "nullable": True},
        {"name": "feature_b", "type": "integer", "minimum": 0},
    ],
    destination="artifacts/group-v1",
    model_name="YOUR_GROUP_MODEL",
    model_version="v1",
    data_kind="group_project",
)
```

แทน schema ตัวอย่างด้วยฟีเจอร์จริง `features`, `sample.columns` และ `pipeline.feature_names_in_` ต้องตรงกัน ถ้า pipeline ไม่ได้ fit บน DataFrame ให้ปรับการเทรนให้เก็บชื่อฟีเจอร์อย่างชัดเจน ตัว exporter ตรวจ schema และลองทำนายก่อนส่งต่อ เก็บ `model.joblib`, `metadata.json`, `sample_request.json` และ checksum โมเดล ใช้ directory ใหม่ทุกเวอร์ชันเพื่อรักษาโมเดลเดิม

เมื่อมี bundle จริงที่ `artifacts/group-v1` ใช้ Compose override เพื่อเลือกและ mount โมเดลนั้นแบบอ่านอย่างเดียว:

```powershell
docker compose -f compose.yaml -f compose.model.yaml up --build -d --force-recreate
```

สำหรับรัน local กำหนด `$env:MODEL_DIR = "$PWD\artifacts\group-v1"` ก่อนเริ่มบริการ โมเดลโหลดครั้งเดียวตอนเริ่มต้น หากเปลี่ยนไฟล์ให้ restart และตรวจชื่อเวอร์ชันใน `/health` ยังไม่ได้ทำ hot reload หรือโหลด alias จาก MLflow อัตโนมัติ

รับเฉพาะ joblib จากทีมที่เชื่อถือได้ เพราะไฟล์ pickle/joblib สามารถรันโค้ดขณะโหลดได้ checksum ช่วยตรวจว่าโมเดลตรง metadata แต่ไม่ได้ยืนยันผู้สร้าง `scikit-learn` เวอร์ชันเทรนต้องตรงบริการ

API ทำ preprocessing ใน Pipeline เดียวกับตอนเทรน ฟีเจอร์ lag/rolling ต้องสร้างด้วยโค้ดร่วมของคนที่ 1 ก่อนส่งเข้า API เดโมไม่รับวันที่แล้วสร้างประวัติขึ้นเอง การใช้ Pipeline จึงไม่ใช่ข้อพิสูจน์ว่าฟีเจอร์ upstream ของกลุ่มตรงกันแล้ว ต้องตรวจการเชื่อมต่อจริงอีกครั้ง

## สถานะการเชื่อมกับโมเดลใน repository กลุ่ม

โค้ดกลุ่มมี Final Candidate LightGBM และ Model Registry `demand-forecasting-7d` อยู่แล้ว แต่ไฟล์โมเดล/ฐานข้อมูล MLflow ถูก ignore และสร้างจาก workflow ของกลุ่ม ตัวโหลดในเดโมนี้ยังไม่โหลด `models:/demand-forecasting-7d@production` โดยอัตโนมัติ ต้องทำ adapter สำหรับ MLflow pyfunc หรือ export fitted Pipeline พร้อม preprocessing และ schema จริงก่อนให้บริการยอดขาย 7 วัน

`src/demand_forecasting/serving_benchmark.py` ของกลุ่มเรียก `/invocations` ด้วย `dataframe_split` ส่วนเดโมรับ `/predict` ด้วย `records` และไม่มี endpoint `/invocations` ผล SLO ในโฟลเดอร์นี้จึงไม่ใช่หลักฐานผ่าน quality gate ของ Registry ต้องเชื่อม endpoint/ตัว benchmark และวัดโมเดลจริงก่อนใช้กับ promotion gate

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
