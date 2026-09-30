# สรุปการทำ CI/CD ของคนที่ 6 — 30 กันยายน 2026

## สถานะ

ยืนยัน CI/CD ในขอบเขตสาธิตตามรายวิชาแล้ว: รอบปกติผ่านตั้งแต่ code/data/model จนถึง Docker integration และชุดส่งมอบ ส่วนรอบ bad ทั้งสามหยุดตรงด่านที่ตั้งใจและไม่มี delivery artifact

งานอยู่บน branch `integration/real-model-serving` และ draft PR #7 ไป `Dec` ยังไม่มีการ merge เข้า `main` หรือ `Dec` การ review และการยืนยันสัญญา/SLO ของทีมยังต้องทำแยกจากผลอัตโนมัติ

## 1. หลักฐาน GitHub Actions จริง

| รอบ | ผลที่เกิดจริง | ลิงก์ |
|---|---|---|
| normal | ผ่านครบและสร้างชุดส่งมอบ | [เปิดรอบ 36661484161](https://github.com/Frosty-jub/ml-project/actions/runs/36661484161) |
| bad_code | ล้มเหลวที่ code; ด่านถัดไปถูกข้าม | [เปิดรอบ 36660579656](https://github.com/Frosty-jub/ml-project/actions/runs/36660579656) |
| bad_data | ล้มเหลวที่ data validation; ไม่ฝึกหรือ deploy | [เปิดรอบ 36660583185](https://github.com/Frosty-jub/ml-project/actions/runs/36660583185) |
| bad_model | ล้มเหลวที่ candidate quality gate; ไม่ register/deploy | [เปิดรอบ 36660585806](https://github.com/Frosty-jub/ml-project/actions/runs/36660585806) |

Head commit ที่ตรวจ: `dfa2a427ed238c0cdda5f63eb31fda3f94739819`
Checkout commit ที่ GitHub ใช้ตรวจ PR: `feadca5dfd9593cc9ffa4e3b3597908867401b29`

GitHub สร้าง merge commit ชั่วคราวเพื่อทดสอบ PR ร่วมกับ base จึงอาจมี SHA ต่างจาก head; ไม่ได้หมายถึง merge PR จริง

## 2. ผลสำคัญของรอบปกติ

- Project unit tests: รัน 45 ข้อ โดยข้ามหนึ่งข้อที่ต้องรอ Experiment 3 artifact ก่อนฝึก; ด่าน model/integration ตรวจ artifact หลังฝึกจริงต่อ
- Serving tests: ดูผลแบบ JUnit ใน reports/ci_cd/normal/serving-tests.xml
- Model quality gate: passed = true
- Load test: 500/500 requests สำเร็จ
- p50 = 22.43 ms; p95 = 28.76 ms
- Throughput = 441.19 requests/s; error = 0.00%
- Monitoring events: 520/520 ตรง request_id และ row_index รวม warmup
- Rollback ไป version 1 แล้วคืน version 2; parity ทั้งสองจุดผ่าน
- ตรวจ checksum ของชุดส่งมอบครบ 31 ไฟล์
- สร้าง image จากชุดส่งมอบจริง และตรวจ HTTP/schema/prediction เทียบ Registry ทั้ง candidate และ fallback ผ่าน

เลขเวอร์ชันเป็นของ Registry แยกใน CI ไม่ใช่การเปลี่ยนเลขเวอร์ชันบนเครื่องผู้ใช้ ผลโหลดทดสอบเป็นผลรอบสั้นบน GitHub runner ไม่ใช่ SLA ระยะยาว

## 3. เพิ่มหรือแก้ไฟล์อะไร และทำไม

| ไฟล์ | สิ่งที่ทำ |
|---|---|
| .github/workflows/ml-ci.yml | แสดงด่าน CI ภาษาไทยบน push/PR เก็บหลักฐานแม้ล้มเหลว และส่งมอบเมื่อผ่านครบ |
| scripts/ci_pipeline.py | เรียก validator/training/gate/stage runner เดิมตามลำดับ ตรวจด่านก่อนหน้า และเขียนผล JSON |
| ci/Dockerfile, ci/test-requirements.lock | environment ตรวจงานบน Python 3.12 และ dependencies ที่ระบุเวอร์ชัน |
| ci/compose.yaml | แยก runner, candidate, production และ Registry/data volume ของแต่ละรอบ |
| ci/runtime.Dockerfile, ci/delivery.compose.yaml | build ชุดส่งมอบและเลือก candidate/fallback |
| tests/__init__.py, tests/test_ci_pipeline.py | แก้ discovery บน Python 3.12 และตรวจการหยุดก่อนส่งมอบ |
| src/demand_forecasting/training/experiment2.py, tests/test_experiment2.py | คืนวิธีตรวจ checksum LF/CRLF จากประวัติโครงการ และเพิ่ม tests ปฏิเสธ config ที่เปลี่ยนจริง |
| .dockerignore, .gitignore | กัน delivery/evidence runtime ออกจาก build context และ Git ตามชนิดไฟล์ |
| docs/course_requirements.md | แก้บันทึกเดิมที่เคยระบุว่าไม่พบเอกสาร หลังได้อ่านไฟล์ที่ผู้ใช้ให้แล้ว |
| docs/ci_cd_th.md, docs/ci_delivery_th.md | คู่มืออธิบาย workflow และวิธีนำชุดส่งมอบไปรัน เป็นภาษาไทย |
| reports/ci_cd/ | หลักฐานจริงที่ดาวน์โหลดและตรวจจาก GitHub API |

## 4. คำสั่งที่ workflow ใช้

หลัง build image และเปิด compose แล้ว GitHub เรียกคำสั่งเหล่านี้ทีละด่าน:

```text
docker compose -f ci/compose.yaml exec -T runner python scripts/ci_pipeline.py code
docker compose -f ci/compose.yaml exec -T runner python scripts/ci_pipeline.py data
docker compose -f ci/compose.yaml exec -T runner python scripts/ci_pipeline.py model
docker compose -f ci/compose.yaml exec -T runner python scripts/ci_pipeline.py integration
docker compose -f ci/compose.yaml exec -T runner python scripts/ci_pipeline.py package
```

จากนั้นคัดลอก delivery ออกมา build image เปิด candidate/fallback แล้วเรียก `ci_pipeline.py delivery` เพื่อตรวจชุดจริง และ `ci_pipeline.py report` เพื่อสรุป กรณีด่านใดล้มเหลวจะข้ามด่านถัดไป

รายละเอียดคำสั่งเต็มอยู่ใน workflow และ log ของ GitHub หน้าต่าง PowerShell บนเครื่องใช้แสดงการทดสอบ/commit/push/เก็บหลักฐาน มี transcript ใน reports/ci/ ซึ่งเก็บไว้ในเครื่อง

## 5. รอบ bad เปลี่ยนอะไร

- bad_code: ข้อความ Python ผิดไวยากรณ์ใน fixture ไม่แก้ source ของทีม
- bad_data: ตั้ง daily_sold_units ของแถวแรกใน sku_daily_sales.csv.gz เป็น -1 เฉพาะ workspace ชั่วคราวของ CI; validator ปฏิเสธยอดขายติดลบ
- bad_model: ตั้ง aggregate_metrics.MAE เป็น 2 เท่าของ baseline ใน final_candidate_metadata.json ชั่วคราว; quality gate เดิมปฏิเสธ
- ไม่แก้ข้อมูลต้นฉบับในเครื่อง ไม่เปลี่ยน threshold และไม่ส่งโมเดลจากรอบ bad ไป API

## 6. ปัญหาที่พบและแก้จริง

1. Python 3.12 ค้นหา tests ไม่ได้: เพิ่ม tests/__init__.py แล้วรัน tests ใหม่
2. Config เดียวกันมี newline ต่างกันบน Windows/Linux: นำ helper ที่มีในประวัติ commit 1357cb9 กลับมาใช้เฉพาะการตรวจ reference; ยังคงตรวจ workbook, split และ manifest ปัจจุบัน
3. เปลี่ยน official GitHub actions เป็นรุ่น Node 24 ที่ตรึง commit SHA เพื่อให้ตรง runner

4. ตรวจ ZIP ที่ดาวน์โหลดจริงแล้วพบว่าไฟล์ placeholder .gitkeep ถูก GitHub ตัดออก แต่ checksum ยังนับอยู่ จึงแก้ขั้นแพ็กให้ไม่คัดลอก .gitkeep เพิ่ม unit test ของแพ็กเกจ และรันรอบปกติใหม่ก่อนส่งมอบ

รอบ bad ทั้งสามอ้างอิง commit 1cd7531 ส่วนรอบปกติฉบับส่งมอบรวมการแก้แพ็ก .gitkeep และ test เพิ่ม โดยไม่ได้เปลี่ยน validator, quality gate หรือเงื่อนไขหยุดของรอบ bad รายละเอียด SHA ของแต่ละรอบอยู่ใน acceptance_index.json

รอบ debugging ที่ล้มเหลวก่อนแก้ยังอยู่ในประวัติ GitHub ไม่ใช้เป็นหลักฐานว่ารอบปกติผ่าน และรอบ bad_model ที่หยุดก่อนถึง gate ไม่ถูกนับเป็นหลักฐาน quality-gate rejection

## 7. ใช้งานต่อและขอบเขตที่เหลือ

1. เปิด draft PR #7 review โค้ดและหลักฐานกับทีม
2. ดาวน์โหลด verified-delivery artifact ของรอบปกติ ก่อนครบอายุ 14 วัน แล้วทำตาม docs/ci_delivery_th.md
3. ให้เจ้าของโมเดล/API ยืนยันสัญญาและ proposed SLO เดิม
4. ให้ทีมตัดสินใจ merge ตามกระบวนการ repository; ยังไม่ได้เปิด required checks หรือ deploy ไป server ที่ไม่ได้ระบุไว้

CD ที่ทำคือ continuous delivery พร้อมสาธิต deployment และ rollback ใน Docker ของ CI งาน Airflow และ Monitoring/drift ยังคงใช้ flow และโมดูลของทีมตามเอกสารก่อนหน้า ไม่เพิ่มงานเลือกโมเดลหรือออกแบบ drift ใหม่

Codex ช่วยเขียนโค้ดเชื่อม CI/CD, tests และเอกสารนี้ สมาชิกต้องอ่านและอธิบายสิ่งที่ส่งได้

[เปิด draft PR #7](https://github.com/Frosty-jub/ml-project/pull/7)

รายการ artifacts และ SHA-256 อยู่ใน reports/ci_cd/acceptance_index.json; ZIP และ logs ฉบับเต็มเก็บใน reports/ci/downloads/ บนเครื่อง

Commit ปิดงานที่เพิ่มเฉพาะรายงาน/หลักฐานใช้ [skip ci] เพื่อไม่ฝึกซ้ำโดยไม่มีการเปลี่ยนโค้ด ผลทดสอบยังอ้างอิง head และ checkout SHA ที่ระบุข้างต้นอย่างชัดเจน
