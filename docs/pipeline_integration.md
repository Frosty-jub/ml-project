# Pipeline Integration Contract

**สถานะทางเทคนิค:** Integration และ Pipeline Orchestration ผ่านการทดสอบ local demonstration แล้ว

**สถานะข้อตกลงทีม:** รอเจ้าของข้อมูล โมเดล และ API ยืนยัน

**ปรับปรุงล่าสุด:** 2026-09-30

**ส่วนต่อยอด 2026-09-30:** ชุด Airflow แยกที่ `orchestration/airflow/compose.yaml` เชื่อม candidate จากแต่ละ run กับ Registry/bundle/candidate API/policy approval/production/rollback และ Monitoring ดู [คู่มือ orchestration](pipeline_orchestration.md) สถานะร่างและ owner sign-off ของเอกสารนี้ยังคงต้องยืนยันตามจริง

เอกสารนี้กำหนดข้อตกลงสำหรับเชื่อม data pipeline, โมเดลใน Model Registry, Model Serving และ Monitoring ก่อนนำไปจัดเป็น orchestration pipeline

## 1. ขอบเขตข้อมูลและโมเดล

- หนึ่ง record แทน SKU หนึ่งรายการ ณ `forecast_origin_date`
- ฟีเจอร์และลำดับฟีเจอร์อ้างอิง `feature_columns` ใน `reports/generated/feature_split_manifest.json` ซึ่งสร้างจาก data pipeline
- ห้ามใช้ `sku_id`, `forecast_origin_date` หรือ target `demand_next_7d_units` เป็นฟีเจอร์เข้าโมเดล
- API รับฟีเจอร์ที่ผ่าน feature engineering แล้ว ไม่รับข้อมูลธุรกรรมดิบและไม่สร้าง lag/rolling features เอง
- ผู้เรียก API ต้องเก็บ mapping ระหว่าง `request_id + row_index` กับ `sku_id + forecast_origin_date` ภายนอก เพื่อจับคู่ label เมื่อยอดขายจริงครบช่วง 7 วัน
- ต้องใช้ feature engineering และลำดับฟีเจอร์เดียวกับที่ใช้ตอนเทรน

`reports/generated/feature_split_manifest.json` ถูกสร้างแล้ว รายชื่อจริงที่ export เข้าโมเดลมี 12 ฟีเจอร์เรียงตาม manifest ได้แก่ `daily_sold_units`, `days_since_first_sale`, `sales_lag_1`, `sales_lag_7`, `sales_lag_14`, `sales_lag_28`, `sales_rolling_sum_7`, `sales_rolling_sum_14`, `sales_rolling_sum_28`, `day_of_week`, `month` และ `is_weekend`

## 2. สัญญา API

### Request

Endpoint มาตรฐานที่เสนอ: `POST /predict`

```json
{
  "records": [
    {
      "<feature_name_from_manifest>": 0
    }
  ]
}
```

- `records` มีหนึ่ง record ต่อหนึ่ง SKU ณ วันตัดข้อมูล
- แต่ละ record ต้องมีฟีเจอร์ครบตาม schema; runtime จัดคอลัมน์ DataFrame ตามลำดับ manifest ก่อนส่งเข้าโมเดล (ไม่อาศัยลำดับ key ของ JSON)
- ต้องยืนยันชนิดข้อมูล ค่าว่าง และขอบเขตค่าของแต่ละฟีเจอร์กับเจ้าของข้อมูลและโมเดล

### Response เมื่อสำเร็จ

```json
{
  "request_id": "<request-id>",
  "model_name": "demand-forecasting-7d",
  "model_version": "<registered-version>",
  "data_kind": "group_project",
  "predictions": [0.0]
}
```

- จำนวนค่าทำนายใน `predictions` ต้องเท่ากับจำนวน record
- `model_version` ต้องตรงกับเวอร์ชันที่ API โหลดจริง
- Request ที่ schema ไม่ถูกต้องต้องไม่ส่งเข้าโมเดล และตอบ `422`
- หากโมเดลโหลดไม่สำเร็จ API ต้องไม่รายงานสถานะพร้อมใช้งาน

## 3. สัญญาไฟล์โมเดล

Bundle สำหรับ API ใช้โครงสร้างต่อไปนี้ โดยเก็บแยกตามเวอร์ชัน:

```text
serving/artifacts/<version>/
├── model.joblib
├── metadata.json
└── sample_request.json
```

bundle ของกลุ่มบันทึก `FeatureOrderedModel` จาก Registry เป็น `model.joblib`; runtime เรียก wrapper ด้วย DataFrame ที่เรียงตาม manifest และยังรองรับ sklearn Pipeline สำหรับ bundle เดิมด้วย

`metadata.json` ต้องบันทึกอย่างน้อย:

- `model_name`, `model_version`, `data_kind`
- รายชื่อและลำดับฟีเจอร์
- checksum ของไฟล์โมเดล
- เวอร์ชัน dependency ที่จำเป็นต่อการโหลดโมเดล

**สถานะ implementation:** exporter โหลดเวอร์ชันที่ผ่าน quality gate จาก Registry แล้วบันทึก `FeatureOrderedModel` เป็น joblib พร้อม metadata, checksum และ sample request; Docker นำ source module และ dependencies ที่จำเป็นเข้า image การ export เปรียบเทียบผลทำนายกับ Registry ก่อนสำเร็จ

- [ ] เจ้าของโมเดลและ API ยืนยันแนวทาง export เป็น `FeatureOrderedModel` joblib และ schema นี้
- [x] ตรวจ dependency และ source code ของ Docker image ด้วยการ build และ start container ที่โหลด bundle จริงแล้ว

## 4. Metric และเกณฑ์ผ่าน

### คุณภาพโมเดล

- **Optimizing metric:** ค่าเฉลี่ย validation MAE บน 4 folds; ค่ายิ่งต่ำยิ่งดี
- เกณฑ์ใน `config/model_registry.json` ปัจจุบันกำหนดให้ชนะ baseline อย่างน้อย 3 ใน 4 folds
- โมเดลที่จะเลื่อนเป็น production ต้องมี validation folds เดียวกับ champion และ MAE ไม่แย่กว่า champion ตามค่า `maximum_champion_mae_regression_pct` ปัจจุบันซึ่งเท่ากับ 0%
- ใช้ validation folds สำหรับ gate นี้ ไม่ใช้ test set ในการเลือกหรือปรับโมเดล

### ประสิทธิภาพบริการ

ค่าปัจจุบันใน `config/model_registry.json` คือ p50 ≤ 200 ms, p95 ≤ 500 ms, throughput ≥ 100 predictions/second และ benchmark ต้องใหม่กว่า 24 ชั่วโมง

ส่วน `serving/slo.json` ระบุ SLO สำหรับเดโมเป็น p50 ≤ 100 ms, p95 ≤ 250 ms, throughput ≥ 20 requests/second และ error rate ≤ 1%

- `serving/slo.json` มีอยู่ก่อนงานคนที่ 6 ใน commit `e32b994` ของชุด FastAPI/Serving/Docker บน branch `Dec`; ตัวเลขไม่ได้ตั้งใหม่ในงาน orchestration
- Registry benchmark ใช้ batch 32, concurrency 4, measured 30 requests เพื่อเป็น serving promotion gate; API SLO ใช้ 1 record/request, concurrency 10, measured 500 requests เพื่อประเมินบริการ ทั้งสองต้องผ่านใน DAG ปัจจุบัน
- [ ] ทีมยืนยันการใช้เกณฑ์เดิมทั้งสองชุดตาม workload และหน้าที่ที่ระบุ ไม่จำเป็นต้องทำให้ตัวเลขหรือหน่วยเหมือนกัน
- [ ] ทีมยืนยันสถานะ SLO ทางการ; ไฟล์เดิมยังระบุ Proposed demo SLO และงานคนที่ 6 ไม่ลงชื่ออนุมัติแทนทีม
- [x] benchmark วัด API ที่ใช้โมเดลจริง ไม่ใช่ synthetic demo

## 5. ขั้นตอนส่งต่อระหว่างส่วนงาน

```text
ข้อมูลดิบ
  → ตรวจ schema และคุณภาพข้อมูล
  → สร้าง features และ manifest
  → เทรนและประเมินโมเดล
  → ตรวจ model quality gate
  → ลงทะเบียน candidate
  → export เวอร์ชัน candidate เป็น bundle
  → โหลด bundle ใน Model Serving
  → ตรวจ API และ benchmark
  → อนุมัติและ promote
  → ให้บริการและส่ง prediction observations ไป Monitoring
```

การเปลี่ยน Registry alias เพียงอย่างเดียวไม่ได้เปลี่ยนโมเดลที่ API โหลดอยู่ ชุด Airflow ปัจจุบันจึงเปลี่ยน deployment pointer หลังผ่าน gate และให้ selector ตรวจ bundle/name/version/checksum ก่อนโหลด พร้อมตรวจ health และ prediction parity หลังสลับ และทดสอบ rollback/restore จริง

## 6. หลักฐานว่า Integration ผ่าน

- [x] `/health` แสดง `model_name` และ `model_version` ของโมเดลจริง ไม่ใช่ synthetic demo
- [x] `/schema` ตรงกับ feature manifest ทั้ง 12 ฟีเจอร์
- [x] API ทำนาย record จาก validation split ได้
- [x] ผล API ตรงกับผลจากโมเดล Registry สำหรับ input เดียวกันภายใน tolerance `rtol=1e-5`, `atol=1e-5`
- [x] Input ที่ผิด schema ได้ `422` และไม่เข้าสู่โมเดล
- [x] `/metrics` บันทึกคำขอและผลการทำนาย
- [x] ตรวจ Monitoring event จริงแล้ว พบ `request_id`, `row_index`, model version, features และ prediction
- [x] benchmark และหลักฐาน SLO มาจาก API ที่ใช้โมเดลจริง
- [x] load test แยกด้วย `serving/scripts/load_test.py` ใช้ payload จาก bundle จริงครบ 500 requests
- [x] คู่มือระบุวิธีสร้าง bundle เลือกเวอร์ชัน และเริ่มบริการด้วย bundle นั้น

### หลักฐาน Integration เดิม วันที่ 2026-09-29 (Registry บน host)

- Candidate Registry version `1` ผ่าน quality gate: validation MAE 16.2275 เทียบ baseline 20.8549 และชนะครบ 4/4 folds
- ลงทะเบียนเป็น `demand-forecasting-7d` version `1` แล้ว โดยยังไม่มี alias สำหรับ production
- Export bundle ไปที่ `serving/artifacts/group-v1-joblib` และ prediction parity check กับ Registry ผ่าน
- Docker image build และ container start ด้วย `model.joblib` bundle version `1` สำเร็จ; HTTP evidence ผ่านครบใน `serving/reports/http_evidence.json`
- Registry-versus-HTTP parity benchmark ผ่านทุก gate: p50 `12.80 ms`, p95 `30.56 ms`, throughput `8,792.56 predictions/s` (`274.77 requests/s`), batch size `32`, concurrency `4`, `30/30` measured requests สำเร็จ
- Load test ของ bundle `model.joblib` ผ่าน proposed demo SLO: 500/500 requests สำเร็จ, concurrency `10`, p50 `23.99 ms`, p95 `28.81 ms`, throughput `411.66 requests/s`, error rate `0%`; หลักฐานอยู่ใน `serving/reports/load_test_group_v1.json`
- ผล benchmark ของรอบนี้ผ่านทั้งสองชุดเกณฑ์; การยืนยัน SLO ทางการเป็นสถานะข้อตกลงของทีม แยกจากผลผ่านทางเทคนิค
- ตรวจ monitoring volume แล้วพบ observation records ที่มี `request_id`, `row_index`, model version, features และ prediction
- ณ รอบหลักฐานเดิม version `1` ยังไม่มี production alias ข้อมูลนี้เป็นประวัติของ Registry บน host ไม่ใช่สถานะของ Airflow stack ด้านล่าง

### ผล Pipeline Orchestration วันที่ 2026-09-30 (Registry ใน Airflow stack)

- รอบ `acceptance_normal_20260930_final` ผ่าน 16/16 tasks ตั้งแต่ข้อมูลดิบจนถึง serving และรายงาน
- Candidate version `4` ถูก deploy ตาม quality/serving policy เดิม; rollback ไป version `3` และ restore version `4` ผ่าน prediction parity ทั้งคู่ ตัวเลข version มาจาก Registry ของ stack นี้
- Production API ของ stack อยู่ที่ port `18015`; candidate API อยู่ที่ `18016`; Airflow อยู่ที่ `18090` แยกจาก serving เดิม port `18005`
- Load test 500/500 requests, p50 34.28 ms, p95 50.25 ms, throughput 281.05 requests/s, error 0%; ตรวจ Monitoring events ตรงกับ receipts 520/520 รวม warmup
- `bad_data` หยุดที่ prepare_data และ `bad_quality` หยุดที่ candidate_quality_gate พร้อม failure alerts โดยไม่ลงทะเบียนหรือเปลี่ยน production
- Clean-volume bootstrap ผ่าน 16/16 tasks และ automated tests ผ่าน 17 ข้อ
- Drift/retraining เป็น simulation ที่ระบุ synthetic_demo_only ตามการสาธิตที่รายวิชาอนุญาต; daily monitoring รายงาน pending_inputs เมื่อยังไม่มี inputs จริง ไม่สร้าง labels ขึ้นเอง
- หลักฐานรวม: `reports/orchestration/acceptance_index.json`; รายงานอธิบาย: `reports/pipeline_orchestration_completed_20260930.md`; ขอบเขตและที่มาของโค้ด: `docs/orchestration_scope_check.md` และ `docs/orchestration_source_map.md`
- งานทางเทคนิคของ Pipeline Orchestration, Integration และ CI/CD สำหรับ local demonstration ทำครบและมีหลักฐานในรายงาน Petch; การยืนยันจากเจ้าของงานยังบันทึกตามจริงในหัวข้อ 7 และไม่ถือเป็น production approval

## 7. การยืนยันจากเจ้าของงาน

- เจ้าของข้อมูล: ____________________
- เจ้าของโมเดล/Registry: ____________________
- เจ้าของ API/Serving: ____________________
- ผู้รวมระบบ: ____________________
- วันที่ยืนยัน: ____________________
