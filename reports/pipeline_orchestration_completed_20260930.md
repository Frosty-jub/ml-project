# ผลงาน Pipeline Orchestration และคู่มืออ่านลำดับงาน

วันที่: 30 กันยายน 2026 — โปรเจกต์ `C:\Users\User\ml-project`

## 1. ข้อสรุปที่พิสูจน์แล้ว

Pipeline Orchestration สำหรับ local demonstration ทำงานครบทั้ง flow แล้ว: normal DAG ผ่าน 16/16 tasks, ทดสอบ bad data และ failed quality gate ได้ผล failed ตามที่คาดโดย production ไม่เปลี่ยน, ทดสอบ daily monitoring DAG และ bootstrap บน named volumes ใหม่สำเร็จ งาน CI/CD ยังไม่ได้เริ่ม

นี่เป็นผลทางเทคนิคของระบบสาธิต การลงชื่อยืนยันของเจ้าของโมเดล/API และ SLO ยังต้องให้สมาชิกยืนยันเอง Drift/retraining ใช้ข้อมูลสังเคราะห์ที่ติดป้ายชัดเจน ไม่ใช่หลักฐานว่ามี mature labels จากผู้ใช้งานจริง

| การทดสอบ | Run ID | ผล |
|---|---|---|
| ครบวงจร | `acceptance_normal_20260930_final` | success, 16/16 tasks |
| ข้อมูลยอดขายติดลบ | `acceptance_bad_data_20260930` | failed ที่ prepare_data ตามคาด; ไม่ register/deploy |
| โมเดลไม่ผ่านเกณฑ์ | `acceptance_bad_quality_20260930` | failed ที่ candidate_quality_gate ตามคาด; ไม่ register/deploy |
| Monitoring รายวัน | `acceptance_monitoring_20260930` | success, 3/3 tasks; pending_inputs และไม่ retrain |
| เริ่มจาก volumes ว่าง | `acceptance_clean_20260930` | success, 16/16 tasks; Registry และ bundle สร้างเอง |
| Automated tests | unit_tests_20260930.txt | 17 tests ผ่าน |

## 2. ผลโมเดลและ API ของรอบ normal

- Registry: `demand-forecasting-7d` version **4** (อ่านจากผลลงทะเบียน ไม่กำหนดเลขเอง)
- Validation MAE: **16.2275**; baseline **20.8549**; ชนะ **4 folds**
- Bundle: `model.joblib`, `metadata.json`, `sample_request.json`; ตรวจ source hash, bundle SHA-256 และ feature order
- Registry/API prediction parity ผ่านก่อน deploy หลัง deploy ตอน rollback และหลัง restore
- Load test: **500/500 requests**, p50 **34.28 ms**, p95 **50.25 ms**, throughput **281.05 requests/s**, errors **0.00%**
- จับคู่ Monitoring events ตาม request_id/row_index **520/520** รวม warmup 20 และ measured 500
- Rollback ไป version **3** และ restore version **4** ผ่าน prediction parity ทั้งคู่
- Drift จำลอง: ตรวจ feature drift เมื่อยังไม่มี labels โดยไม่ retrain; เมื่อ policy ตรวจ performance/concept change พร้อม mature labels จำลองจึง retrain เป็น candidate สำหรับ review และไม่ promote

เลข version ของ Registry ใน stack ทดสอบ bootstrap แยกจาก Registry ของ stack หลัก และทั้งสองแยกจาก MLflow เดิมบน Windows/serving port 18005 จึงไม่ควรเทียบเลข version โดยละเลย Registry ที่ใช้

## 3. ลำดับงานและไฟล์ที่รับผิดชอบ

```text
initialize → prepare_data → experiment_2 → experiment_3 → verify_full_folds
→ candidate_quality_gate → register_models → export_bundles → benchmark_candidates
→ approve_and_deploy → rollback_drill → verify_monitoring
→ simulate_drift → check_drift → retrain_candidate → write_run_report
```

| ไฟล์ | ใช้ทำอะไร |
|---|---|
| orchestration/airflow/dags/demand_forecasting_e2e.py | จัด dependency ของ 16 tasks และ DAG monitoring รายวัน; ส่งต่อเฉพาะ environment ของ project interpreter |
| orchestration/airflow/run_stage.py | เรียกงานสมาชิกคนที่ 1–5 ตามลำดับ; เชื่อม Registry/bundle/API/Monitoring; เก็บผลแยก run ID |
| orchestration/airflow/compose.yaml | สร้าง Airflow, candidate API, production API และ shared volumes |
| orchestration/airflow/Dockerfile และ requirements.lock | สร้าง image และล็อก dependencies สำหรับ training/serving |
| serving/app/selector.py และ main.py | โหลด bundle ตาม deployment pointer และตรวจชื่อ/version/checksum ก่อนสลับโมเดล |
| serving/scripts/load_test.py | วัด SLO และเก็บ receipts สำหรับตรวจ events ครบทุก request |
| scripts/start_orchestration.ps1 | build image และเปิด stack |
| scripts/verify_orchestration.ps1 | trigger DAG, ตรวจสถานะจริง, เก็บ JSON และ task logs; ตรวจ failure ที่คาดไว้ |
| scripts/run_orchestration.ps1 | เริ่ม stack และรัน flow ด้วยคำสั่งเดียว |
| scripts/verify_clean_orchestration.ps1 | ทดสอบ stack ใหม่ที่ไม่มี volumes; หยุดเฉพาะชุดทดสอบเมื่อเสร็จ |
| tests/test_orchestration.py | ตรวจ switch/rollback/checksum, candidate mismatch, event completeness และ dependency compatibility |
| docs/pipeline_orchestration.md | คู่มือ architecture, คำสั่ง, SLO, monitoring inputs และการกู้คืน |
| docs/orchestration_source_map.md | แยกไฟล์ทีมที่เรียกใช้กับโค้ดและข้อมูลทดสอบที่ Codex เพิ่ม |
| docs/orchestration_scope_check.md | เทียบแต่ละส่วนกับข้อกำหนดรายวิชาและงานคนที่ 6 |

โมเดลและเกณฑ์เลือกโมเดลมาจากโค้ด/config ของทีม คนที่ 6 เชื่อมขั้นตอนเหล่านั้น ไม่ได้เปลี่ยนเป็นโมเดลสาธิต synthetic-demand-demo

## 4. ปัญหาที่พบและการแก้

1. รอบ `acceptance_normal_20260930_0701` ล้มที่การอ่าน Git revision ใน workspace ที่ไม่มี `.git` แก้ด้วย source_revision.json ที่บันทึก commit, dirty state และ content hash ของ snapshot
2. รอบ `acceptance_normal_20260930_0720` API โหลด bundle ไม่ผ่านเพราะ Airflow ส่ง PYTHONPATH ของตนเอง ทำให้ training ใช้ scikit-learn 1.9.1 ขณะที่ serving ใช้ 1.7.2 แก้โดยล้าง PYTHONPATH/PYTHONHOME และตรวจตำแหน่ง import จริงใน initialize
3. รอบ `acceptance_normal_20260930_isolated` พบ bundle เก่าภายใต้ Registry version เดิมแม้ source hash ตรง แก้เงื่อนไข reuse ให้ตรวจ runtime dependency tags ด้วย; รุ่นเก่าที่ไม่มี tags จะสร้างรุ่นใหม่แทน

หลักฐานรอบที่ล้มเหลวยังอยู่ใน reports/orchestration เพื่ออธิบาย debugging และไม่ถูกนับเป็นรอบสำเร็จ ตัวเลขและผลในหัวข้อ 1–2 มาจากรอบที่ตรวจสถานะ Airflow สำเร็จแล้ว

## 5. คำสั่งสำหรับดูงานและสาธิต

เปิด PowerShell ที่ root:

```powershell
cd C:\Users\User\ml-project
docker compose -f orchestration/airflow/compose.yaml ps
Invoke-RestMethod http://127.0.0.1:18015/health
```

Airflow: http://127.0.0.1:18090 — เลือก demand_forecasting_e2e แล้วเลือกรอบ normal ที่ระบุข้างต้นเพื่อดู 16 tasks สีเขียว; รอบ bad_data/bad_quality สีแดงเป็นผลที่ตั้งใจทดสอบ

Production API: http://127.0.0.1:18015/docs — Candidate API: http://127.0.0.1:18016/docs

รันใหม่ครบ flow (จะดาวน์โหลด/สร้างข้อมูล/เทรน และอาจ deploy รุ่นใหม่ตาม gate):

```powershell
.\scripts\run_orchestration.ps1
```

ถ้า stack เปิดอยู่แล้ว:

```powershell
.\scripts\verify_orchestration.ps1 -Scenario normal
.\scripts\verify_orchestration.ps1 -Scenario bad_data
.\scripts\verify_orchestration.ps1 -Scenario bad_quality
.\scripts\verify_orchestration.ps1 -Scenario monitoring
```

อ่านหลักฐานที่ `reports/orchestration/<run_id>/`: summary.json/md, airflow_run.json, airflow_tasks.json, task_logs/, quality_gate.json, registered.json, load_test.json, load_event_reconciliation.json, approval.json, rollback_drill.json และ failure_alert.json สำหรับรอบที่ล้มเหลว โดย acceptance_index.json รวมผลทุก scenario ไว้

PowerShell transcripts, row-level events, model binaries และรหัสผ่านไม่ควรนำเข้า Git รายงาน aggregate และโค้ดเก็บใน branch สำหรับ review ได้

## 6. ขอบเขตที่ยังต้องให้ทีมดำเนินการและขั้นถัดไป

- เจ้าของข้อมูล/โมเดล/API ยืนยัน docs/pipeline_integration.md และเกณฑ์ SLO; ระบบเก็บสถานะ pending ตามจริง
- Daily monitoring รอ reference/events/labels ที่ครบ horizon 7 วัน; เมื่อพร้อมตั้ง monitoring_inputs.json ตามคู่มือ ไม่สร้าง labels แทนข้อมูลจริง
- ผล benchmark เป็นการทดสอบช่วงสั้นบนเครื่องนี้ ไม่ยืนยันความพร้อมใช้งานระยะยาว
- ต่อ CI/CD ด้วย GitHub Actions: เริ่มจาก dependency install → code/tests → data/model gate ที่เหมาะกับ CI → build image → integration checks → เก็บ artifacts → review/approval ก่อน deployment ตามนโยบายทีม

OpenAI Codex ช่วยเขียนและแก้ orchestration, integration adapter, tests, scripts และคู่มือ สมาชิกต้องอ่านและอธิบายโค้ดที่ส่งได้ การสรุปนี้ไม่ใช่การลงชื่ออนุมัติแทนสมาชิก
