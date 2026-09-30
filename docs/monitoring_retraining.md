# งานคนที่ 5 การเฝ้าระวัง Drift และการเทรนใหม่

งานนี้ต่อจาก branch `GG` ของคนที่ 4 ระบบพยากรณ์ยอดขายราย SKU อีก 7 วันใช้ MAE เป็นตัวชี้วัดหลัก และรายงาน RMSE/WAPE เพิ่มเติม โมเดลใน `serving/` ตอนนี้เป็น **synthetic demo**; โมเดล LightGBM จริงและข้อมูลที่สร้างจาก pipeline ยังไม่ได้เก็บใน Git จึงต้องแยกผลเดโมกับผลจริง

## จุดเชื่อมต่อกับบริการ

`POST /predict` ที่สำเร็จจะบันทึก 1 แถวต่อคำทำนายเมื่อกำหนด `MONITORING_EVENTS_PATH` แต่ละแถวมีเวลา UTC, `request_id`, `row_index`, ชื่อ/รุ่นโมเดล, `data_kind`, ฟีเจอร์ที่ผ่าน validation และ prediction โดยไม่บันทึก target ที่ยังไม่เกิด การเขียนล้มเหลวเพิ่ม `serving_observation_write_failures_total` และ JSON log; API ยังคืนคำทำนายได้

ใน Docker Compose มี volume `monitoring_events`; นำ events ออกมาโดยรันจาก `serving/`:

```bash
docker compose cp serving:/app/artifacts/monitoring/events.jsonl ../artifacts/monitoring/events.jsonl
```

หากใช้ local API กำหนด `MONITORING_EVENTS_PATH` เป็น path ที่เขียนได้ก่อนเริ่ม API เช่น `artifacts/monitoring/events.jsonl` อย่า commit ไฟล์ที่มีฟีเจอร์จากผู้ใช้จริง ข้อมูล label ต้องมาจากยอดขายที่ทราบ **หลังวันทำนายครบ 7 วัน** ในไฟล์ CSV รูปแบบ:

```csv
request_id,row_index,actual,observed_at
request-001,0,17,2026-02-09T00:00:00+00:00
```

ขั้นตอนจับคู่ label ต้องใช้ `request_id + row_index` ที่ไม่ซ้ำกัน และ `actual` เป็นยอดขายรวมจริงในช่วง 7 วันต่อจากวันตัดข้อมูลตามนิยามโจทย์ API ของคนที่ 4 ยังรับเฉพาะฟีเจอร์ ไม่รับ SKU หรือ `forecast_origin_date`; ผู้ส่งคำขอต้องเก็บความสัมพันธ์ระหว่าง request ID, SKU และ origin date ภายนอกก่อนจะสร้าง label CSV นี้ ถ้าวันส่งคำขอไม่ใช่ origin date ให้ตรวจ horizon จาก origin date เพิ่มในระบบต้นทาง

## เกณฑ์ตรวจและนโยบายแจ้งเตือน

ปรับค่าได้ใน `config/monitoring.json`; ค่าเริ่มต้นเป็นเกณฑ์สาธิต ต้องเทียบกับข้อมูลใช้งานจริงก่อนนำไปใช้

| เรื่อง | เกณฑ์เริ่มต้น | ผล |
|---|---:|---|
| หน้าต่างเวลา | 7 วัน, อย่างน้อย 30 คำทำนาย | ข้อมูลไม่พอให้สถานะ `insufficient_data` |
| Data drift | PSI ฟีเจอร์ตัวเลข ≥ 0.20 หรือ TVD ฟีเจอร์หมวดหมู่ ≥ 0.20 | แจ้ง `data_drift` และรายชื่อฟีเจอร์ |
| คุณภาพโมเดล | มี label ที่ครบ horizon อย่างน้อย 30 แถว, MAE ≥ 1.25 เท่าค่าอ้างอิงและเพิ่มขึ้น ≥ 2 หน่วย | แจ้ง `performance_degradation`; รายงาน MAE/RMSE/WAPE |
| Concept drift | คุณภาพตกโดยฟีเจอร์ที่วัดยังไม่ drift | แจ้ง `suspected_concept_drift`; เป็นข้อสงสัย ไม่ใช่ข้อพิสูจน์เชิงสาเหตุ |
| Retraining | คุณภาพตก 2 หน้าต่างเวลาติดกัน | `retraining_trigger: true`; data drift เพียงอย่างเดียวไม่สั่งเทรน |
| สถานะบริการ | `/health`, 5xx rate > 1%, p95 bucket > 0.25 วินาที, หรือเขียน event ล้มเหลว | แจ้งเตือนระบบ; counters/p95 เป็นค่าตั้งแต่ process เริ่ม ไม่ใช่ SLO 5 นาที |

หากยังไม่มี label ให้แสดง `pending_mature_labels` โดยไม่วินิจฉัย concept drift หรือสั่ง retrain ถ้า data drift และคุณภาพตกพร้อมกัน รายงานทั้งสองอย่างแต่ไม่ฟันธงสาเหตุ การตรวจ `/metrics` ไม่มี throughput ช่วงสั้น; ใช้ `serving/scripts/load_test.py` ของคนที่ 4 ประเมิน p50/p95/throughput ตาม SLO ของบริการ

## สั่งงานด้วยข้อมูลจริง

ติดตั้ง dependencies จาก `requirements.txt` และรันจาก root repository เมื่อเชื่อม serving กับ bundle `data_kind=group_project` ที่อนุมัติแล้ว ให้รวบรวมข้อมูลช่วงอ้างอิงของ **โมเดลรุ่นเดียวกัน** ซึ่งมี label ครบก่อน:

```bash
python -m src.demand_forecasting.monitoring reference --events artifacts/monitoring/reference_events.jsonl --labels artifacts/monitoring/reference_labels.csv --output artifacts/monitoring/reference.json
python -m src.demand_forecasting.monitoring check --events artifacts/monitoring/live_events.jsonl --labels artifacts/monitoring/live_labels.csv --reference artifacts/monitoring/reference.json --health-url http://localhost:18005 --output artifacts/monitoring/report.json
```

ถ้า `report.json` มี `retraining_trigger: true` ให้รัน:

```bash
python -m src.demand_forecasting.monitoring retrain --events artifacts/monitoring/live_events.jsonl --labels artifacts/monitoring/live_labels.csv --report artifacts/monitoring/report.json --current-model artifacts/training/final_candidate_model.joblib --params artifacts/training/final_candidate_params.json --output artifacts/monitoring/candidate-001
```

Retraining ใช้ LightGBM ตามพารามิเตอร์เดิม เลือก holdout จากวันล่าสุดประมาณ 20% และเว้น 7 วันระหว่าง train กับ holdout เพื่อป้องกัน label คาบเกี่ยว ประเมิน champion กับ candidate บน holdout เดียวกัน ไฟล์ `candidate_review.json` เก็บ MAE/RMSE/WAPE, hash ข้อมูลและเกณฑ์ `candidate_beats_champion`; `candidate_model.joblib` เป็นเพียง candidate **ไม่ register/promote อัตโนมัติ** ต้องให้คนที่ 3 ตรวจ quality gate และคนที่ 4 เชื่อม bundle ที่ใช้จริงก่อนนำขึ้นบริการ ควรมีหลายหน้าต่างหลังการเปลี่ยนแปลงเพื่อฝึกให้ครอบคลุมสภาพใหม่; หากข้อมูลน้อยคำสั่งจะหยุด

## สาธิตตั้งแต่ตรวจพบจนได้ candidate

สคริปต์ต่อไปสร้างข้อมูลสังเคราะห์ที่ label เปลี่ยนหลังวันที่ 14 แต่ฟีเจอร์ยังมีการกระจายใกล้เดิม ไม่ใช้ข้อมูล UCI และไม่เป็นหลักฐานคุณภาพโมเดลจริง:

```bash
python -m src.demand_forecasting.monitoring simulate --output-dir artifacts/monitoring/demo
python -m src.demand_forecasting.monitoring reference --events artifacts/monitoring/demo/reference_events.jsonl --labels artifacts/monitoring/demo/reference_labels.csv --output artifacts/monitoring/demo/reference.json
python -m src.demand_forecasting.monitoring check --events artifacts/monitoring/demo/live_events.jsonl --labels artifacts/monitoring/demo/live_labels.csv --reference artifacts/monitoring/demo/reference.json --output artifacts/monitoring/demo/report.json
python -m src.demand_forecasting.monitoring retrain --events artifacts/monitoring/demo/live_events.jsonl --labels artifacts/monitoring/demo/live_labels.csv --report artifacts/monitoring/demo/report.json --current-model artifacts/monitoring/demo/champion_model.joblib --params artifacts/monitoring/demo/params.json --output artifacts/monitoring/demo/candidate-v2 --allow-demo
```

ในการรันทดสอบนี้ MAE อ้างอิง 1.1494, ช่วงที่ 3–4 เพิ่มเป็น 15.0042 และ 15.1284 ขณะที่ PSI ของฟีเจอร์ทั้งสอง < 0.20; trigger เป็น true จาก 2 ช่วงติดกัน Candidate จากข้อมูลสังเคราะห์มี MAE 15.0457 เทียบ champion 15.1272 บน holdout 240 แถว แต่ยังไม่ใช่หลักฐานว่าคุณภาพเพียงพอสำหรับใช้งานจริง

ขอบเขตงานของคนที่ 6 คือกำหนด DAG/CI/CD และเรียกคำสั่งเหล่านี้อัตโนมัติตามรอบ ส่วนการ promotion/rollback อยู่ที่ทะเบียนโมเดลของคนที่ 3

เครื่องมือ AI ที่ใช้: OpenAI Codex ช่วยเขียนโค้ดบันทึก observations, ตัววัด drift, retraining candidate, tests และคู่มือนี้ สมาชิกต้องตรวจและอธิบายโค้ดก่อนส่งตามข้อกำหนดรายวิชา
