# ที่มาของ flow และส่วนที่เพิ่มสำหรับงานคนที่ 6

เอกสารรายวิชาและภาพแบ่งหน้าที่กำหนดความสามารถที่ต้องมี เช่น orchestration, integration, tests และ end-to-end run แต่ไม่ได้กำหนด DAG 16 tasks นี้แบบบรรทัดต่อบรรทัด DAG ปัจจุบันเป็น implementation ที่ Codex เขียนเพิ่มตามงานที่ผู้ใช้ให้ดำเนินการ

## ใช้กระบวนการของทีมจากไฟล์ใด

| งาน | ไฟล์ที่ถูกเรียก | บทบาทของ orchestration |
|---|---|---|
| ดาวน์โหลดข้อมูล | scripts/download_data.py | เรียก URL UCI ที่กำหนดอยู่แล้วในไฟล์ ไม่สร้างข้อมูลฝึกจริงเอง |
| เตรียมยอดขาย/target | scripts/prepare_data.py | เรียกกระบวนการเดิม |
| ตรวจข้อมูล | scripts/validate_data.py | หยุด downstream เมื่อ validation ไม่ผ่าน |
| สร้าง features/splits | scripts/build_features.py | ใช้ feature builder และ manifest ของทีม |
| เปรียบเทียบโมเดล | src/demand_forecasting/training/experiment2.py | เรียกการเทรนและการเลือก best candidate เดิม; เพิ่มการอ่าน revision จาก code snapshot เท่านั้น |
| Final candidate | src/demand_forecasting/training/experiment3.py | ใช้โมเดล/parameters ที่กระบวนการนี้เลือก ไม่เขียนสูตรเลือกโมเดลใหม่ใน DAG |
| ตรวจ folds | src/demand_forecasting/training/verify_full_folds.py | เรียกการตรวจเดิม |
| เกณฑ์และ promotion | src/demand_forecasting/registry.py, config/model_registry.json | ใช้ check_candidate/evaluate_gate/promote/rollback; เชื่อม benchmark ให้ตรง API จริง |
| Export/serve | serving/scripts/export_model.py, serving/app/runtime.py | ใช้ส่วน integration ที่ปรับรองรับ FeatureOrderedModel joblib และ checksum แล้ว |
| API SLO | serving/slo.json, serving/scripts/load_test.py | ใช้เกณฑ์เดิม; เพิ่มการเก็บ request receipts สำหรับเทียบ Monitoring events |
| Drift/retraining | src/demand_forecasting/monitoring/, config/monitoring.json | เรียก reference/check/retrain/simulate ของทีมตาม policy เดิม |

## สิ่งที่ Codex ออกแบบและเขียนเพิ่ม

- Airflow DAG 16 tasks, daily monitoring DAG, stage runner, Docker Compose stack และสคริปต์ PowerShell
- แยก candidate API กับ production API ใน local stack เพื่อทดสอบ candidate ก่อนสลับบริการ
- เชื่อมลงทะเบียนรุ่นจาก artifact ที่ผ่าน gate, export bundle, ตรวจ prediction parity และสลับ deployment pointer
- ใช้ best candidate ที่ Experiment 2 เลือกเป็น fallback สำหรับสาธิต rollback ในการติดตั้งครั้งแรก ใช้ final candidate จาก Experiment 3 เป็นเป้าหมาย deploy ทั้งสองต้องผ่าน gate
- เงื่อนไข reuse ต้องตรง source hash, validation protocol และ dependency versions
- การอนุมัติอัตโนมัติใน local demo ด้วย quality/serving policies เดิม ไม่ใช่ลายเซ็นของเจ้าของงาน
- ตรวจ request_id/row_index ให้ events ครบ ไม่ซ้ำ และตรง prediction/version ของ request ที่ทดสอบ
- สร้าง snapshot, lineage, alerts, acceptance reports, unit tests และคู่มือ

สิ่งเหล่านี้เป็นการเพิ่มโค้ดเพื่อเชื่อมส่วนงาน ไม่ใช่ flow สำเร็จรูปที่มีอยู่ครบในเอกสารเดิม และไม่ควรกล่าวว่าเอกสารรายวิชาบังคับให้ใช้ architecture หรือ task names เหล่านี้โดยเฉพาะ

## ข้อมูลจำลองที่เพิ่มเพื่อทดสอบ

| กรณี | เปลี่ยนอะไร | ขอบเขต |
|---|---|---|
| bad_data | ใส่ daily_sold_units = -1 ในสำเนาข้อมูลรายวัน | workspace ของ failure test เท่านั้น |
| bad_quality | เปลี่ยน aggregate MAE ในสำเนา metadata ให้แย่กว่า baseline | ทดสอบว่า gate ปฏิเสธ ไม่ลงทะเบียน/นำโมเดลนี้ไป serve |
| Drift demo | เรียก simulate ของคนที่ 5 และเพิ่มกรณี feature shift โดยไม่มี labels | ติดป้าย synthetic_demo_only; retrained candidate ไม่ register/promote |
| Unit tests | โมเดลและ events ขนาดเล็กใน temporary directory | ไม่ใช่โมเดลที่นำขึ้น API ของโครงงาน |

การเทรนหลักยังใช้ข้อมูล UCI ผ่าน feature pipeline ของทีม ผลทดสอบจำลองไม่ใช้เป็นหลักฐานคุณภาพโมเดลจริง Daily monitoring ที่ยังไม่มี mature live labels จะรายงาน pending_inputs ตามจริง

ดู git diff ของ branch เทียบ origin/Dec เพื่อตรวจรายละเอียดไฟล์ที่เปลี่ยน และดู lineage.json ของแต่ละ run เพื่อยืนยัน hash ของ code snapshot ที่ถูกใช้จริง
