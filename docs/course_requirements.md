# การเทียบข้อกำหนดรายวิชากับงานคนที่ 6

ตรวจจากเอกสาร `โครงงานรายวิชา CP413008 Machine Learning Engineering for Production.docx` ที่ผู้ใช้ให้จาก Downloads และภาพแบ่งหน้าที่ วันที่ 30 กันยายน 2026 ข้อความนี้แทนบันทึกเดิมที่เคยระบุว่าไม่พบไฟล์ข้อกำหนด

| ข้อกำหนดที่เกี่ยวข้อง | งานคนที่ 6 | เอกสารประกอบ |
|---|---|---|
| Pipeline ครบจากข้อมูลถึง serving และรันซ้ำได้ | เชื่อมงานทีมเป็น Airflow DAG | pipeline_orchestration.md |
| ข้อมูลผิดต้องหยุดและแจ้งเตือน | เรียก validator เดิมและพิสูจน์ failure path | orchestration_scope_check.md |
| Registry/gate/version และ rollback | เชื่อมโมดูล Registry กับ API | pipeline_integration.md |
| Docker/compose และ dependencies ที่ระบุเวอร์ชัน | environment และ bundle | pipeline_orchestration.md |
| CI/CD รันจริง ตรวจ code/data/model มีหลักฐานผ่านและไม่ผ่าน | GitHub Actions, automated tests, delivery | ci_cd_th.md |
| Monitoring/drift/retraining | เชื่อม trigger ของคนที่ 5 | orchestration_source_map.md |
| Branch/PR คำอธิบายและการใช้ AI | Draft PR และรายงาน | reports/ |

รายวิชาให้เลือกเครื่องมือ ภาพคนที่ 6 ระบุ Prefect/Airflow, GitHub Actions, automated tests, docker-compose/integration และ end-to-end run ผู้ใช้เลือก Airflow จึงใช้ Airflow

ผลทดสอบทางเทคนิคแยกจากการยืนยัน SLO/สัญญาของเจ้าของงาน เอกสารนี้ไม่แทนการลงชื่อยืนยันของทีม และไม่เปลี่ยนหน้าที่เลือกโมเดลหรือพัฒนา Monitoring มาเป็นของคนที่ 6
