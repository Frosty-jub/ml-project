# ตรวจขอบเขตงานคนที่ 6 กับเอกสารรายวิชา

ตรวจเมื่อ 30 กันยายน 2026 จากเอกสาร “โครงงานรายวิชา CP413008 Machine Learning Engineering for Production.docx” และภาพแบ่งหน้าที่ที่ผู้ใช้ส่ง

ขอบเขตคนที่ 6: Integration, Pipeline Orchestration ด้วย Airflow, automated tests และ GitHub Actions CI/CD

| ข้อกำหนดในเอกสาร/ภาพ | งานที่ทำเพื่อรองรับ | ขอบเขต |
|---|---|---|
| ภาพคนที่ 6: Airflow flow, docker-compose/integration, automated tests, end-to-end run | DAG, Compose, scripts, integration tests | งานหลักคนที่ 6 |
| ส่วน 7: DAG รันซ้ำจากข้อมูลดิบถึง serving ด้วยคำสั่ง/ปุ่มเดียว | ต่อ download/validate/features/train/gate/register/export/serve | เรียกโค้ดสมาชิก ไม่ออกแบบโมเดลใหม่ |
| ส่วน 2: ข้อมูลเสียแล้วหยุดและแจ้งเตือน | bad_data acceptance scenario และ failure report | ทดสอบตัว validator ของคนที่ 1 |
| ส่วน 4: gate ก่อนอนุมัติและ rollback จริง | ใช้ Registry policy, ตรวจ deployment และ rollback/restore parity | เชื่อมงานคนที่ 3 กับ API คนที่ 4 |
| ส่วน 5: วัด p50/p95/throughput เทียบ SLO | Registry benchmark, HTTP checks, load test | ใช้เกณฑ์ที่มีอยู่ ไม่ลดเกณฑ์เพื่อให้ผ่าน |
| ส่วน 6: drift/alert/retraining จนได้ candidate | เรียก monitoring/check/retrain และ simulation ของคนที่ 5 | เชื่อมและทดสอบ ไม่เขียน drift detector หรือนโยบายโมเดลใหม่ |
| ส่วน 7: ผู้อื่นรันได้จากเครื่องเปล่า | Dockerfile/lock, clean-volume bootstrap test, README | ทดสอบใน Docker ใหม่บนเครื่องนี้ ไม่อ้างว่าทดสอบหลายเครื่องแล้ว |
| ส่วน 7: branch และ Pull Request | branch งาน integration และชุดโค้ด/หลักฐานสำหรับ review | ไม่รวม merge เข้า branch ทีมโดยอัตโนมัติ |
| ส่วน 8: รายงาน แผนภาพ อธิบายโค้ดและบทบาท AI | คู่มือ flow, source map, รายงานผลจริง | ระบุส่วนที่ Codex เพิ่มตามจริง |

## สถานะปัจจุบันและสิ่งที่อยู่นอกขอบเขตคนที่ 6

- GitHub Actions/CI/CD ทำงานแล้ว: มีรอบปกติบน branch Petch และรอบ failure fixture สำหรับ code/data/model บน branch ci/evidence/*; ลิงก์และผลแยกแต่ละรอบอยู่ใน [รายงาน acceptance](../reports/petch_acceptance_20260930/report_th.md)
- การ deploy อัตโนมัติไป production จริงของทีมยังไม่อยู่ในหลักฐานนี้: ทดสอบ delivery/deploy/rollback ใน Docker CI และ local demo เท่านั้น โดย owner sign-off ยัง pending
- เปลี่ยนโจทย์ ชุดข้อมูลหลัก feature engineering สูตรเลือกโมเดล hyperparameter หรือเกณฑ์คุณภาพที่สมาชิกกำหนด
- เขียนระบบ Monitoring ใหม่แทนคนที่ 5 หรืออ้างว่ามีข้อมูล labels จริงพร้อมแล้ว
- Cloud deployment, Kubernetes, dashboard ใหม่ หรือเครื่องมืออื่นที่ไม่จำเป็นกับการสาธิตนี้

## รายละเอียดที่เป็นการออกแบบ implementation เพิ่ม

เอกสารไม่ได้บังคับว่าต้องมี 16 tasks, candidate/production API แยกพอร์ต หรือ deployment pointer โดยเฉพาะ ส่วนเหล่านี้เป็นวิธีเชื่อมระบบเพื่อให้ทดสอบ candidate ก่อนนำขึ้นบริการ ตรวจย้อนกลับ และเก็บหลักฐานได้ ไม่ใช่ข้อกำหนดเพิ่มเติมที่อาจารย์ระบุ

การทดสอบข้อมูลเสีย/โมเดลไม่ผ่าน/drift เป็นข้อมูลจำลองเฉพาะพื้นที่ทดสอบ ไม่เปลี่ยน training data หรือโมเดลที่ใช้จริงของทีมโดยตรง การอนุมัติใน local demo ใช้ policy ที่มีอยู่และระบุว่า owner sign-off ยัง pending; ไม่ลงชื่อแทนสมาชิก

หากต้องส่งงานเฉพาะคนที่ 6 ให้อธิบายว่าตนเชื่อมและทดสอบส่วนของคนที่ 1–5 ไม่อ้างว่าเป็นผู้สร้างโมเดล/API/Monitoring ทั้งหมด ดูรายละเอียดจาก docs/orchestration_source_map.md
