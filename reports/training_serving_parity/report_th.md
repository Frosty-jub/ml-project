# ผลตรวจ Training–serving parity — 2 ตุลาคม 2026

แก้จาก branch `Petch` ณ commit `ada63d0e47490704da2610f934d18ba86a43b099`
ให้ data pipeline และตัวเตรียมคำขอ API เรียก `build_features()` จากไฟล์ร่วมเดียวกัน
พร้อมตัวตรวจประวัติรายวัน การเทียบ feature manifest/config และคำสั่งตรวจ parity ซ้ำ

## ผลที่รันจริงในเครื่องนี้

| การตรวจ | ผล |
|---|---|
| ชุดทดสอบโปรเจกต์ | 55 ผ่าน, 1 ข้าม เพราะยังไม่มี artifacts จาก Experiment 3 สำหรับตรวจ metadata |
| ชุดทดสอบ Serving รวมการตรวจ parity ใหม่ | 24 ผ่าน |
| Tests ของตัวเตรียมฟีเจอร์ (รวมอยู่ใน 55 ข้างต้น) | 11 ผ่าน |
| ตรวจโค้ดไฟล์ที่แก้ด้วย Ruff | ผ่าน |
| ตรวจ whitespace ของ diff | ผ่าน |
| คำสั่งสร้าง request และส่ง `/predict` ผ่าน localhost HTTP | ผ่าน, 2 SKU |
| คำสั่งตรวจ parity ผ่าน HTTP | ผ่าน: 12 ฟีเจอร์, ความต่างฟีเจอร์สูงสุด 0, ความต่าง prediction สูงสุด 0 |
| คำสั่งตรวจ parity ผ่าน FastAPI TestClient | ผ่าน: ความต่างฟีเจอร์และ prediction สูงสุด 0 |
| คำสั่งตรวจที่ใช้ SKU ไม่มีอยู่ | exit code ไม่เป็นศูนย์ และรายงานเดิมถูกแทนด้วย `status: failed` |

API automated test ตรวจอีก 3 วันพยากรณ์ และส่ง JSON ที่กลับลำดับ keys
เพื่อพิสูจน์ว่า API คืนคอลัมน์กลับเป็นลำดับที่โมเดลต้องการก่อนทำนาย

หลักฐาน: `project-tests.xml`, `feature-tests.xml`, `serving-tests.xml`,
`http-parity.json`, `inprocess-parity.json` และ `environment.json` ในโฟลเดอร์นี้
คำสั่งทดสอบอยู่ใน [คู่มือ](../../docs/training_serving_parity.md)

## ขอบเขตของผล

หลักฐาน parity ที่รันรอบนี้ใช้ daily history สังเคราะห์ 2 SKU และ LightGBM
ที่ฝึกเพื่อทดสอบระบบ (`data_kind: synthetic_test_fixture`, version `test-v1`)
โดยใช้ `FeatureOrderedModel` และ FastAPI ของโปรเจกต์จริง
ไม่ใช่คะแนนหรือการรับรองโมเดล production version 1 ของทีม
Git clone นี้ไม่มี daily history และโมเดลจริงจาก Experiment 1–3
จึงเตรียมคำสั่งสำหรับรันกับ bundle จริงไว้ในคู่มือ

ทางที่ตรวจครอบคลุมการเตรียมคำขอด้วยสคริปต์ใหม่ก่อนเข้า `/predict`
ผู้เรียกที่สร้าง lag/rolling เองต้องรับผิดชอบให้คำนวณตามสัญญาเดียวกัน
history ต้องครบตั้งแต่วันขายแรกจริง และใช้หลังปิดยอดวันพยากรณ์

## การใช้ AI

ใช้ OpenAI Codex ช่วยย้ายฟังก์ชันร่วม เขียนตัวเตรียมคำขอ/ตัวตรวจ parity
เพิ่ม automated tests รัน HTTP บน localhost และจัดทำคู่มือกับรายงานนี้
